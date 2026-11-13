"""Build the FEMA flood zone database that runs look up points in:

.venv/bin/python script/build_flood_zones.py data/flood-hazard.parquet --as-of 2026-11-13

The source is FEMA's NFHL flood hazard polygons (S_FLD_HAZ_AR) as GeoParquet. --as-of is the date
the FEMA data was published or downloaded, shown with every result. The output (by default
data/fema/flood-zones.duckdb, the flood_zones_db setting's default) takes about 1.6 times the
source's size, and the national file takes about a minute.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from engine.flood_zone_data import FloodZoneDataError, build  # noqa: E402

DEFAULT_OUT = ROOT / "data" / "fema" / "flood-zones.duckdb"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("source", type=Path, help="FEMA NFHL S_FLD_HAZ_AR as GeoParquet")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        required=True,
        help="when the FEMA data was published or downloaded (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    started = time.monotonic()
    try:
        report = build(args.source, args.out, args.as_of)
    except FloodZoneDataError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"Wrote {report.polygons:,} polygons to {args.out} in {time.monotonic() - started:.0f} s")
    print(
        f"Source CRS {report.source_crs}"
        + (", reprojected to OGC:CRS84" if report.reprojected else "")
    )
    for count, what in (
        (report.skipped_no_geometry, "with no geometry"),
        (report.skipped_no_zone, "with no FLD_ZONE"),
    ):
        if count:
            print(f"Skipped {count:,} rows {what}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
