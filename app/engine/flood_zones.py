"""Look up each US asset's FEMA flood zone, as a pipeline stage.

Points are grouped into small square tiles, and each tile is one query against the flood zone
database's R-tree (see flood_zone_data.py), so only polygons near the portfolio are read. The
result is stored per asset in asset_flood_zones, with a status saying why an asset has no zone.

FEMA data is optional: with none configured, or an unusable file, every US asset reads as
'unavailable' and the run carries on.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from engine.flood_zone_data import FloodZoneDataError, database_info, zone_ranks
from engine.settings import Settings
from engine.store import Run

logger = logging.getLogger(__name__)

SQL_DIR = Path(__file__).parent / "sql"
# The names countries.geojson gives the US and the territories FEMA maps.
US_COUNTRIES = (
    "United States of America",
    "Puerto Rico",
    "U.S. Virgin Is.",
    "Guam",
    "American Samoa",
    "N. Mariana Is.",
)
# About 11 km: points in one town share a tile, and a tile's envelope stays small enough for the
# R-tree to return few polygons. Measured: 5,000 scattered US points in 1,201 tiles took 17 s.
TILE_DEG = 0.1
PROGRESS_SECONDS = 1.0

Progress = Callable[[int, int], None]


def map_flood_zones(
    run: Run, settings: Settings, progress: Progress | None = None
) -> dict[str, int]:
    """Fill asset_flood_zones for the run and return how many assets have each status."""
    database = _usable_database(settings.flood_zones_db)
    with run.connect() as con:
        con.execute("INSTALL spatial")
        con.execute("LOAD spatial")
        con.execute("SET geometry_always_xy = true")
        con.execute("DELETE FROM asset_flood_zones")
        con.execute("DELETE FROM flood_zone_source")
        con.execute(
            (SQL_DIR / "flood_zone_points.sql").read_text(),
            {"tile_deg": TILE_DEG, "us_countries": list(US_COUNTRIES)},
        )
        con.execute(
            "CREATE OR REPLACE TEMP TABLE flood_zone_matches (row_num INTEGER, DFIRM_ID VARCHAR, "
            "FLD_AR_ID VARCHAR, FLD_ZONE VARCHAR, ZONE_SUBTY VARCHAR, SFHA_TF VARCHAR, "
            "STATIC_BFE DOUBLE, V_DATUM VARCHAR, LEN_UNIT VARCHAR, DEPTH DOUBLE)"
        )
        con.execute(
            "CREATE OR REPLACE TEMP TABLE flood_zone_ranks (zone_key VARCHAR, risk_rank INTEGER)"
        )
        con.executemany("INSERT INTO flood_zone_ranks VALUES (?, ?)", sorted(zone_ranks().items()))

        if database is not None:
            path, info = database
            con.execute("DETACH DATABASE IF EXISTS fema")
            con.execute("ATTACH ? AS fema (READ_ONLY)", [str(path)])
            try:
                _look_up(con, progress)
            finally:
                con.execute("DETACH DATABASE IF EXISTS fema")
            con.execute(
                "INSERT INTO flood_zone_source VALUES (?, ?, ?, ?, ?)",
                [
                    info["source_name"],
                    info["source_crs"],
                    info["polygons"],
                    info["as_of"],
                    info["built_at"],
                ],
            )

        con.execute((SQL_DIR / "flood_zones.sql").read_text(), {"available": database is not None})
        return dict(
            con.execute(
                "SELECT fema_status, count(*) FROM asset_flood_zones GROUP BY fema_status"
            ).fetchall()
        )


def _usable_database(path: Path | None) -> tuple[Path, dict] | None:
    if path is None:
        logger.info("No flood_zones_db is set, so FEMA flood zones are unavailable")
        return None
    try:
        return path, database_info(path)
    except FloodZoneDataError as e:
        logger.warning("FEMA flood zones are unavailable: %s", e)
        return None


def _look_up(con, progress: Progress | None) -> None:
    tiles = con.execute(
        "SELECT tile_x, tile_y, min(ST_X(pt)), min(ST_Y(pt)), max(ST_X(pt)), max(ST_Y(pt)) "
        "FROM flood_zone_points GROUP BY tile_x, tile_y ORDER BY tile_x, tile_y"
    ).fetchall()
    lookup = (SQL_DIR / "flood_zone_lookup.sql").read_text()
    reported = time.monotonic()
    for done, (tile_x, tile_y, west, south, east, north) in enumerate(tiles, 1):
        con.execute(
            lookup,
            {
                "tile_x": tile_x,
                "tile_y": tile_y,
                "west": west,
                "south": south,
                "east": east,
                "north": north,
            },
        )
        if progress and (done == len(tiles) or time.monotonic() - reported >= PROGRESS_SECONDS):
            progress(done, len(tiles))
            reported = time.monotonic()
