"""Turn geolocated rows into physrisk assets.

physrisk accepts unknown types and locations without error and returns a fallback result, so
everything it receives is checked here against its own embedded vulnerability config. How each
value was decided is recorded with the asset, because the assumed building type moves the results.
"""

from __future__ import annotations

import csv
import re
from functools import cache
from pathlib import Path

from engine.settings import Settings
from engine.store import Run

ENGINE_DIR = Path(__file__).parent
SQL_DIR = ENGINE_DIR / "sql"
TYPE_MAP = SQL_DIR / "building_type_map.csv"
COUNTRIES = ENGINE_DIR / "data" / "countries.geojson"

ASSET_CLASS = "RealEstateAsset"
# How far from the (1:50m, so coarse) coastline an unmatched point can be and still count as land.
MAX_LAND_DISTANCE_KM = 50.0

_IDENTIFIER = re.compile(r"type=([^,]+),location=(.+)")


class ClassificationError(Exception):
    """The classification tables disagree with physrisk's vulnerability curves."""


@cache
def valid_curves() -> frozenset[tuple[str, str]]:
    """Every (type, location) that physrisk has a real estate curve for."""
    # Imported here because it takes seconds, and only this needs it.
    from physrisk.vulnerability_models.vulnerability import VulnerabilityModelsFactory

    matches = (
        _IDENTIFIER.fullmatch(item.asset_identifier)
        for item in VulnerabilityModelsFactory.embedded_vulnerability_config()
        if item.asset_class == ASSET_CLASS
    )
    return frozenset((m.group(1), m.group(2)) for m in matches if m)


def check_building_types(default_building_type: str, curves=None) -> None:
    """Fail loudly if a type we might send isn't one physrisk knows."""
    known = {building_type for building_type, _ in (curves or valid_curves())}
    with open(TYPE_MAP, newline="") as f:
        mapped = {row["physrisk_type"] for row in csv.DictReader(f) if row["physrisk_type"]}
    unknown = sorted((mapped | {default_building_type}) - known)
    if unknown:
        raise ClassificationError(f"Building types with no physrisk curve: {unknown}")


def classify(run: Run, settings: Settings) -> dict[str, int]:
    """Fill in the assets table's classification columns and return a summary of the run."""
    curves = valid_curves()
    check_building_types(settings.default_building_type, curves)
    with run.connect() as con:
        con.execute("INSTALL spatial")
        con.execute("LOAD spatial")
        con.execute("SET geometry_always_xy = true")
        con.execute(
            "CREATE OR REPLACE TEMP TABLE building_type_map AS "
            "SELECT * FROM read_csv(?, header = true, all_varchar = true) "
            "WHERE physrisk_type IS NOT NULL",
            [str(TYPE_MAP)],
        )
        con.execute(
            "CREATE OR REPLACE TEMP TABLE valid_curves (building_type VARCHAR, location VARCHAR)"
        )
        con.executemany("INSERT INTO valid_curves VALUES (?, ?)", sorted(curves))
        con.execute(
            "CREATE OR REPLACE TEMP TABLE regions AS SELECT region, geom FROM ST_Read(?)",
            [str(COUNTRIES)],
        )
        con.execute((SQL_DIR / "assign_regions.sql").read_text())
        con.execute(
            (SQL_DIR / "classify.sql").read_text(),
            [MAX_LAND_DISTANCE_KM, settings.default_building_type],
        )
        return dict(
            con.execute(
                """
                SELECT 'assessable', count(*) FROM assets WHERE assessable
                UNION ALL
                SELECT 'assumed_type', count(*) FROM assets WHERE assessable
                    AND type_source = 'assumed'
                UNION ALL
                SELECT 'global_curve', count(*) FROM assets WHERE location_fallback
                UNION ALL
                SELECT 'excluded_' || exclusion_reason, count(*) FROM assets
                    WHERE exclusion_reason IS NOT NULL GROUP BY exclusion_reason
                """
            ).fetchall()
        )
