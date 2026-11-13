"""Known addresses and points, from real FEMA polygons clipped around them (no network).

The expectations live in fixtures/flood_zone_locations.json, which the live check in
test_flood_zone_live.py compares with FEMA's own map.
"""

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from engine.flood_zone_data import build
from engine.flood_zones import map_flood_zones
from engine.store import create_run

FIXTURES = Path(__file__).parent / "fixtures"
LOCATIONS = json.loads((FIXTURES / "flood_zone_locations.json").read_text())["locations"]
SAMPLE = FIXTURES / "flood_zones_sample.parquet"


@pytest.fixture(scope="module")
def results(tmp_path_factory, flood_con):
    """Every location's row from the real pipeline stage, keyed by name."""
    from engine.settings import Settings

    root = tmp_path_factory.mktemp("addresses")
    database = root / "flood-zones.duckdb"
    build(SAMPLE, database, date(2026, 11, 13))
    run = create_run(root / "data", len(LOCATIONS))
    with run.connect() as con:
        con.executemany(
            "INSERT INTO assets (row_num, asset_id, lat, lon, match_type, country) "
            "VALUES (?, ?, ?, ?, 'none', 'United States of America')",
            [[i, loc["name"], loc["lat"], loc["lon"]] for i, loc in enumerate(LOCATIONS, 1)],
        )
    settings = Settings(
        scenarios=("ssp585",),
        years=(2050,),
        default_building_type="Buildings/Commercial",
        physrisk_batch_size=1,
        geolocate_workers=1,
        geolocate_batch_size=1,
        cluster_eps_km=50.0,
        cluster_min_samples=5,
        max_portfolio_rows=100,
        max_upload_mb=1.0,
        data_dir=root / "data",
        api_port=8000,
        geolocate_config=root / "missing.json",
    )
    map_flood_zones(run, replace(settings, flood_zones_db=database))
    with run.connect() as con:
        cursor = con.execute(
            "SELECT a.asset_id, f.* FROM assets a JOIN asset_flood_zones f USING (row_num)"
        )
        names = [d[0] for d in cursor.description]
        return {row[0]: dict(zip(names, row, strict=True)) for row in cursor.fetchall()}


@pytest.mark.parametrize("location", LOCATIONS, ids=[loc["name"] for loc in LOCATIONS])
def test_known_location(results, location):
    row = results[location["name"]]
    assert row["fema_status"] == "mapped"
    expected = {"fema_matches": 1, "fema_conflict": False} | location["expected"]
    assert {key: row[key] for key in expected} == expected


def test_every_major_zone_is_covered():
    keys = {loc["expected"]["fema_zone_key"] for loc in LOCATIONS}
    assert keys >= {"A", "AE", "AH", "AO", "A99", "V", "VE", "X_SHADED", "X_UNSHADED", "D"}
    assert keys >= {"OPEN WATER", "AREA NOT INCLUDED"}
