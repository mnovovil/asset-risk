"""Hazard map tiles around an asset, drawn by physrisk from its public map data.

Only the WRI flood maps can be read without permission. physrisk refuses the other hazards' maps
(wind, fire, hail, heat, drought). Facts that hold for physrisk-lib 1.10.6, checked by the
live tests in test/engine/test_hazard_maps.py:
- each map holds only the 1-in-1000-year layer: other return periods come back transparent
- tiles exist up to zoom 6 (physrisk reads pyramid level z + 1, and the deepest is 7)
- the resource is the one the assessment uses, and physrisk takes RCP4.5 2030 as its "historical"
- SSP ids map to RCPs, and only RCP4.5 and RCP8.5 exist, so ssp126 and ssp370 have no map
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Protocol, cast

from engine.assess import HISTORICAL, HISTORICAL_YEAR, _physrisk_lock, default_requester

RETURN_PERIOD = 1000
MAX_ZOOM = 6
SCENARIO_YEARS = (2030, 2080)
CACHE_TILES = 256
_LEGEND_STEPS = 5
_COLORMAP_LAST = 255  # index 0 is no data and index 1 the zero bin, both transparent
_COLORMAP_ALPHA = 200


@dataclass(frozen=True)
class MapLayer:
    hazard: str
    resource: str
    colormap: str
    min_value: float
    max_value: float
    units: str


LAYERS: dict[str, MapLayer] = {
    layer.hazard: layer
    for layer in (
        MapLayer(
            "RiverineInundation",
            "inundation/wri/v2/inunriver_{scenario}_MIROC-ESM-CHEM_{year}",
            "flare",
            0.0,
            2.0,
            "m",
        ),
        MapLayer(
            "CoastalInundation",
            "inundation/wri/v2/inuncoast_{scenario}_wtsub_{year}_0",
            "flare",
            0.0,
            2.0,
            "m",
        ),
    )
}
SCENARIOS = frozenset({HISTORICAL, "ssp245", "ssp585"})


class ImageRequester(Protocol):
    def get_image(self, request_or_dict: dict) -> bytes: ...


def unavailable_reason(scenario: str, year: int | None) -> str | None:
    """Why a scenario and year has no flood map, or None when it has one."""
    if scenario not in SCENARIOS:
        return "physrisk has no flood map for this scenario"
    low, high = SCENARIO_YEARS
    if scenario != HISTORICAL and (year is None or not low <= year <= high):
        return f"physrisk's flood maps cover {low} to {high}"
    return None


def legend(layer: MapLayer) -> list[str]:
    """Colours from the lowest to the highest value, as drawn on the map."""
    from physrisk.data.colormap_provider import colormap

    table = colormap(layer.colormap)
    span = _COLORMAP_LAST - 2
    stops = [2 + round(span * step / (_LEGEND_STEPS - 1)) for step in range(_LEGEND_STEPS)]
    alpha = round(_COLORMAP_ALPHA / 255, 2)
    return [f"rgba({r}, {g}, {b}, {alpha})" for r, g, b, _ in (table[str(i)] for i in stops)]


def in_range(z: int, x: int, y: int) -> bool:
    return 0 <= z <= MAX_ZOOM and 0 <= x < 2**z and 0 <= y < 2**z


class _Cache:
    """Least recently used tiles. A tile physrisk doesn't have is cached too, as None."""

    def __init__(self, size: int):
        self._size = size
        self._items: OrderedDict[tuple, bytes | None] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple) -> tuple[bool, bytes | None]:
        with self._lock:
            if key not in self._items:
                return False, None
            self._items.move_to_end(key)
            return True, self._items[key]

    def put(self, key: tuple, value: bytes | None) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self._size:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


_cache = _Cache(CACHE_TILES)


def tile(
    hazard: str,
    scenario: str,
    year: int | None,
    z: int,
    x: int,
    y: int,
    requester: ImageRequester | None = None,
) -> bytes | None:
    """A 512 px PNG tile, or None when there's no map there. Other physrisk failures raise."""
    layer = LAYERS.get(hazard)
    if layer is None or unavailable_reason(scenario, year) or not in_range(z, x, y):
        return None
    key = (hazard, scenario, year, z, x, y)
    found, cached = _cache.get(key)
    if found:
        return cached
    from physrisk.api.v1.hazard_image import TileNotAvailableError

    request = {
        "resource": layer.resource,
        "scenario_id": scenario,
        "year": HISTORICAL_YEAR if scenario == HISTORICAL else year,
        "tile": {"x": x, "y": y, "z": z},
        "min_value": layer.min_value,
        "max_value": layer.max_value,
        "index_value": RETURN_PERIOD,
        # physrisk's request defaults to "heating", not the resource's own colormap.
        "colormap": layer.colormap,
    }
    try:
        with _physrisk_lock:
            image = (requester or cast(ImageRequester, default_requester())).get_image(request)
    except TileNotAvailableError:
        image = None
    _cache.put(key, image)
    return image
