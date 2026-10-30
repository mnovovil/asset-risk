"""Rebuild app/engine/data/countries.geojson from Natural Earth (public domain):
python script/build_regions.py

Keeps only each country's name, region and shape. Commit the result; it never needs to change
unless the source does.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

COMMIT = "ca96624a56bd078437bca8184e78163e5039ad19"
URL = (
    f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{COMMIT}"
    "/geojson/ne_50m_admin_0_countries.geojson"
)
OUTPUT = Path(__file__).resolve().parents[1] / "app" / "engine" / "data" / "countries.geojson"

OPEN_OCEAN = "Seven seas (open ocean)"
# Natural Earth files small islands under the open ocean, so fall back on their UN region.
UN_REGION_TO_REGION = {"Africa": "Africa", "Americas": "South America", "Asia": "Asia"}


def region(properties: dict) -> str:
    continent = properties["CONTINENT"]
    return UN_REGION_TO_REGION[properties["REGION_UN"]] if continent == OPEN_OCEAN else continent


def main() -> None:
    with urllib.request.urlopen(URL, timeout=60) as response:
        source = json.load(response)
    features = [
        {
            "type": "Feature",
            "properties": {"name": f["properties"]["NAME"], "region": region(f["properties"])},
            "geometry": f["geometry"],
        }
        for f in source["features"]
    ]
    OUTPUT.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":"))
    )
    print(f"Wrote {len(features)} countries to {OUTPUT}")


if __name__ == "__main__":
    main()
