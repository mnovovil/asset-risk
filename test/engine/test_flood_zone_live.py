"""Compare the known locations with FEMA's live flood map (opt-in: pytest -m fema).

FEMA's National Flood Hazard Layer map service answers which flood hazard polygon covers a point.
A location whose answer is known to differ says why in flood_zone_locations.json, and is an
expected failure until FEMA's map or the data changes.
"""

import json
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.fema

LOCATIONS = json.loads(
    (Path(__file__).parent / "fixtures" / "flood_zone_locations.json").read_text()
)["locations"]
# Layer 28 is Flood Hazard Zones.
NFHL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"


def live_zones(lon: float, lat: float) -> set[str]:
    query = urllib.parse.urlencode(
        {
            "geometry": f"{lon},{lat}",
            "geometryType": "esriGeometryPoint",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "FLD_ZONE",
            "returnGeometry": "false",
            "f": "json",
        }
    )
    with urllib.request.urlopen(f"{NFHL}?{query}", timeout=60) as response:
        body = json.load(response)
    if "error" in body:
        raise RuntimeError(f"FEMA's map service failed: {body['error']}")
    return {feature["attributes"]["FLD_ZONE"] for feature in body["features"]}


@pytest.mark.parametrize(
    "location",
    [
        pytest.param(loc, marks=pytest.mark.xfail(reason=loc["live_differs"], strict=True))
        if "live_differs" in loc
        else loc
        for loc in LOCATIONS
    ],
    ids=[loc["name"] for loc in LOCATIONS],
)
def test_fema_live_map_agrees(location):
    expected = location["expected"]["fema_zone_key"]
    fld_zone = "X" if expected.startswith("X_") else expected
    assert live_zones(location["lon"], location["lat"]) == {fld_zone}
