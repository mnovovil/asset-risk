"""Cut the FEMA polygons around known locations into a small test fixture:
.venv/bin/python script/flood_zone_fixture.py [--db data/fema/flood-zones.duckdb]

Reads test/engine/fixtures/flood_zone_locations.json and writes
test/engine/fixtures/flood_zones_sample.parquet: every polygon covering each location, clipped to a
small square around it, with FEMA's attributes unchanged (sentinels included), as GeoParquet in
OGC:CRS84. Rerun it after rebuilding the database from a new FEMA release, then check the expected
zones in the locations file still hold.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from engine.flood_zone_data import REQUIRED_COLUMNS, connect  # noqa: E402

FIXTURES = ROOT / "test" / "engine" / "fixtures"
LOCATIONS = FIXTURES / "flood_zone_locations.json"
OUTPUT = FIXTURES / "flood_zones_sample.parquet"
DEFAULT_DB = ROOT / "data" / "fema" / "flood-zones.duckdb"
# About 200 m: enough to keep each point well inside its clipped shapes.
HALF_SIDE_DEG = 0.002


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()

    locations = json.loads(LOCATIONS.read_text())["locations"]
    con = connect(args.db, read_only=True)
    con.execute("CREATE TEMP TABLE points (lon DOUBLE, lat DOUBLE)")
    con.executemany("INSERT INTO points VALUES (?, ?)", [[p["lon"], p["lat"]] for p in locations])
    columns = ", ".join(f"z.{name}" for name in REQUIRED_COLUMNS)
    # One row per polygon and point; a polygon near two points is kept once per square.
    con.execute(
        f"""
        CREATE TEMP TABLE clipped AS
        SELECT DISTINCT {columns},
               ST_SetCRS(ST_Intersection(z.geom, ST_SetCRS(
                   ST_MakeEnvelope(p.lon - $d, p.lat - $d, p.lon + $d, p.lat + $d), 'OGC:CRS84'
               )), 'OGC:CRS84') AS geom
        FROM points p
        JOIN flood_zones z ON ST_Intersects(z.geom, ST_Point(p.lon, p.lat))
        """,
        {"d": HALF_SIDE_DEG},
    )
    # The output path is this script's own constant, and COPY can't take it as a parameter.
    con.execute(f"COPY (SELECT * FROM clipped ORDER BY FLD_AR_ID) TO '{OUTPUT}' (FORMAT parquet)")
    rows = con.execute("SELECT count(*) FROM clipped").fetchone()[0]
    print(f"Wrote {rows} clipped polygons around {len(locations)} locations to {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
