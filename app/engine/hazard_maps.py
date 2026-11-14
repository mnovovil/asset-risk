"""Hazard map tiles around an asset: flood from physrisk, and wildfire and wind drawn from S3.

Each layer describes itself (its measure, units, no-data label, note and source), so the dashboard
shows whatever a layer says and holds no hazard wording of its own. Every layer serves 512 px PNG
tiles through the same URL and decides for itself which scenarios and years it covers.

Flood comes from physrisk's get_image, which only draws the public WRI flood maps. physrisk refuses
the other hazards' maps (wind, fire, hail, heat, drought) on permissions, and that isn't worked
around: where a hazard's array is public, grid_layer.py reads it and draws the tiles itself. Facts
that hold for physrisk-lib 1.10.6, checked by the live tests in
test/engine/test_hazard_maps.py:
- each map holds only the 1-in-1000-year layer: other return periods come back transparent
- tiles exist up to zoom 6 (physrisk reads pyramid level z + 1, and the deepest is 7)
- the resource is the one the assessment uses, and physrisk takes RCP4.5 2030 as its "historical"
- SSP ids map to RCPs, and only RCP4.5 and RCP8.5 exist, so ssp126 and ssp370 have no map

Wildfire is read from Jupiter Intelligence's public fire probability array and drawn here instead:
see fire_map.py. It has no historical baseline, covers ssp126 and ssp585 only, and is divided by
500 before physrisk works out damage, so its map and the losses aren't on the same scale.

Tropical cyclone wind is read from IRIS's public array, the one physrisk's wind losses use: see
wind_map.py. It has a historical baseline and 2050 for ssp119, ssp245 and ssp585, and shows the
1-in-100-year wind speed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

from engine import fire_map, wind_map
from engine.assess import HISTORICAL, HISTORICAL_YEAR, _physrisk_lock, default_requester
from engine.fire_map import HazardMapConfigError
from engine.lru import LruCache

__all__ = ["LAYERS", "HazardMapConfigError", "MapLayer", "tile"]

RETURN_PERIOD = 1000
MAX_ZOOM = 6
SCENARIO_YEARS = (2030, 2080)
CACHE_TILES = 256
_LEGEND_STEPS = 5
_COLORMAP_LAST = 255  # index 0 is no data and index 1 the zero bin, both transparent
_COLORMAP_ALPHA = 200
FLOOD_SCENARIOS = frozenset({HISTORICAL, "ssp245", "ssp585"})
FLOOD_NOTE = (
    "Flood depth for a 1-in-1000-year event, the only one physrisk publishes as a map, at about "
    "1 km resolution and before any flood protection. No flood in the data is not proof of no risk."
)
FLOOD_SOURCE = (
    "Source: WRI Aqueduct Floods, via OS-Climate physrisk. physrisk lists its licence as "
    '"WRI Open Data Commitment: https://www.wri.org/data/open-data-commitment".'
)


class ImageRequester(Protocol):
    def get_image(self, request_or_dict: dict) -> bytes: ...


class MapLayer(Protocol):
    """What the API reads from a layer. Text fields are shown as they are."""

    hazard: str
    measure: str
    units: str
    return_period: int | None
    min_value: float
    max_zoom: int
    no_data_label: str
    note: str

    @property
    def max_value(self) -> float: ...
    @property
    def source(self) -> str: ...
    def reason(self, scenario: str, year: int | None) -> str | None: ...
    def legend(self) -> list[str]: ...
    def tile(
        self, scenario: str, year: int | None, z: int, x: int, y: int, requester=None
    ) -> bytes | None: ...


def unavailable_reason(scenario: str, year: int | None) -> str | None:
    """Why a scenario and year has no flood map, or None when it has one."""
    if scenario not in FLOOD_SCENARIOS:
        return "physrisk has no flood map for this scenario"
    low, high = SCENARIO_YEARS
    if scenario != HISTORICAL and (year is None or not low <= year <= high):
        return f"physrisk's flood maps cover {low} to {high}"
    return None


def in_range(z: int, x: int, y: int) -> bool:
    return 0 <= z <= MAX_ZOOM and 0 <= x < 2**z and 0 <= y < 2**z


_cache: LruCache[bytes | None] = LruCache(CACHE_TILES)


@dataclass(frozen=True)
class FloodLayer:
    hazard: str
    resource: str
    colormap: str
    min_value: float
    max_value: float
    units: str
    measure: str = "Flood depth"
    return_period: int | None = RETURN_PERIOD
    max_zoom: int = MAX_ZOOM
    no_data_label: str = "No flood in the data"
    note: str = FLOOD_NOTE
    source: str = FLOOD_SOURCE

    def reason(self, scenario: str, year: int | None) -> str | None:
        return unavailable_reason(scenario, year)

    def legend(self) -> list[str]:
        """Colours from the lowest to the highest value, as drawn on the map."""
        from physrisk.data.colormap_provider import colormap

        table = colormap(self.colormap)
        span = _COLORMAP_LAST - 2
        stops = [2 + round(span * step / (_LEGEND_STEPS - 1)) for step in range(_LEGEND_STEPS)]
        alpha = round(_COLORMAP_ALPHA / 255, 2)
        return [f"rgba({r}, {g}, {b}, {alpha})" for r, g, b, _ in (table[str(i)] for i in stops)]

    def tile(
        self,
        scenario: str,
        year: int | None,
        z: int,
        x: int,
        y: int,
        requester: ImageRequester | None = None,
    ) -> bytes | None:
        """A 512 px PNG tile, or None when there's no map there. Other physrisk failures raise."""
        if self.reason(scenario, year) or not in_range(z, x, y):
            return None
        key = (self.hazard, scenario, year, z, x, y)
        found, cached = _cache.get(key)
        if found:
            return cached
        from physrisk.api.v1.hazard_image import TileNotAvailableError

        request = {
            "resource": self.resource,
            "scenario_id": scenario,
            "year": HISTORICAL_YEAR if scenario == HISTORICAL else year,
            "tile": {"x": x, "y": y, "z": z},
            "min_value": self.min_value,
            "max_value": self.max_value,
            "index_value": RETURN_PERIOD,
            # physrisk's request defaults to "heating", not the resource's own colormap.
            "colormap": self.colormap,
        }
        try:
            with _physrisk_lock:
                image = (requester or cast(ImageRequester, default_requester())).get_image(request)
        except TileNotAvailableError:
            image = None
        _cache.put(key, image)
        return image


LAYERS: dict[str, MapLayer] = {
    layer.hazard: layer
    for layer in (
        FloodLayer(
            "RiverineInundation",
            "inundation/wri/v2/inunriver_{scenario}_MIROC-ESM-CHEM_{year}",
            "flare",
            0.0,
            2.0,
            "m",
        ),
        FloodLayer(
            "CoastalInundation",
            "inundation/wri/v2/inuncoast_{scenario}_wtsub_{year}_0",
            "flare",
            0.0,
            2.0,
            "m",
        ),
        fire_map.layer(),
        wind_map.configure(),
    )
}


def tile(
    hazard: str,
    scenario: str,
    year: int | None,
    z: int,
    x: int,
    y: int,
    requester: ImageRequester | None = None,
) -> bytes | None:
    """A 512 px PNG tile of a layer, or None when there's no map there. Other failures raise."""
    layer = LAYERS.get(hazard)
    return None if layer is None else layer.tile(scenario, year, z, x, y, requester)
