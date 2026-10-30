"""Audit the building type map against a live Overture release:
python script/overture_values.py [--files 6] [--seed 1]

Samples whole parquet files, counts class and subtype values, and lists any the map doesn't cover,
along with the share of buildings with no value at all. A file holds millions of buildings, so
expect a few minutes and several GB of memory.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from engine.classify import TYPE_MAP  # noqa: E402
from engine.geolocation import _module  # noqa: E402
from engine.settings import load_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=6, help="parquet files to sample")
    parser.add_argument("--seed", type=int, default=1, help="seed for choosing the files")
    args = parser.parse_args()

    cfg = _module("config").load_config(load_settings().geolocate_config)
    con = _module("db").connect(cfg)
    if not cfg.overture_file_index:
        print("error: the geolocate config has no file index", file=sys.stderr)
        return 1
    files = random.Random(args.seed).sample(list(cfg.overture_file_index), args.files)
    paths = [f.path for f in files]

    with open(TYPE_MAP, newline="") as f:
        known = {(row["source"], row["value"]) for row in csv.DictReader(f)}

    unmapped = 0
    for column in ("subtype", "class"):
        counts = con.execute(
            f"SELECT {column}, count(*) FROM read_parquet(?) GROUP BY 1 ORDER BY 2 DESC", [paths]
        ).fetchall()
        total = sum(n for _, n in counts)
        blank = sum(n for value, n in counts if value is None)
        missing = [(value, n) for value, n in counts if value and (column, value) not in known]
        unmapped += len(missing)
        print(f"{column}: {total} buildings, {blank / total:.1%} with no value")
        print(f"  not in the map: {missing or 'none'}")
    return 1 if unmapped else 0


if __name__ == "__main__":
    sys.exit(main())
