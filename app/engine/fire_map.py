"""Wildfire map tiles, drawn from Jupiter Intelligence's fire probability array on S3.

physrisk's image API won't draw this resource: its group_id is jupiter_osc, not public, so
get_image raises PermissionError. The array itself is public, so this module reads it anonymously
from s3://os-climate-physical-risk with s3fs and zarr, and draws Web Mercator tiles itself. Facts
that hold for physrisk-lib 1.10.6, checked by test/engine/test_fire_map.py, and against the real
bucket by test/engine/test_fire_map_live.py (-m s3):
- the inventory path is fire/jupiter/v1/fire_probability_{scenario}_{year}, the resource the
  damage figures use. physrisk divides its values by 500 before working out damage
  (config_based_vuln_model_param.py, _adjust_indicator_values), so the map and the losses aren't on
  the same scale
- ssp126 and ssp585 for 2020, 2030, 2040, 2050, 2075 and 2100, and no historical baseline. They're
  read from physrisk's inventory, never from this file, and only an exact match gets a map
- a (1, 721, 1441) float32 array on a 0.25 degree EPSG:4326 grid, transform_mat3x3
  [0.25, 0, -180.125, 0, -0.25, 90.125]. Its first and last columns are both at 180 degrees but hold
  different values, so a longitude is shifted by 360 degrees only when it falls outside the grid
- NaN (about 71% of cells: ocean, or no data) is drawn transparent. 0 is a real value and gets the
  ramp's first colour

The source array is used, not the ..._map one: it's what the damage figures read, and the _map array
(EPSG:3857, 1125 x 1130, about 35 km pixels) has already been resampled once.

The reading, sampling and drawing are grid_layer.py's, shared with the wind layer: this module is
fire's configuration, and keeps module-level functions that its tests call and patch.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from functools import cache
from typing import Any

import numpy as np

from engine import grid_layer
from engine.grid_layer import (  # noqa: F401  re-exported: fire's tests and callers use them here
    CRS,
    TILE_PX,
    Coverage,
    Grid,
    GridLayer,
    GridSettings,
    GridSpec,
    HazardMapConfigError,
    _columns,
    _hex_to_linear,
    _linear_to_oklab,
    grid_from,
    physrisk_inventory,
    pixel_lonlat,
    sample,
)

HAZARD = "Fire"
NOUN = "wildfire"
FIRE_PATH = "fire/jupiter/v1/fire_probability_{scenario}_{year}"
BUCKET_ROOT = grid_layer.BUCKET_ROOT
# Defaults for the settings in .asset-risk.json (fire_map_max_zoom and the hazard_map_* keys).
# A 0.25 degree cell is about 23 px wide at zoom 6 and 11 px at zoom 5: deeper tiles would add
# nothing, and MapLibre stretches them with nearest-neighbour sampling.
MAX_ZOOM = 6
CACHE_ARRAYS = 4  # about 4 MB each
CACHE_TILES = 256
ALPHA = 200  # as the flood tiles, so the base map shows through
LEGEND_STOPS = 9

# Lowest value to highest, one hue (OKLCH hue 45), lightness falling 0.74 to 0.42. One ramp serves
# both themes, so tiles don't depend on the theme. The dataviz validator's --ordinal checks
# (lightness monotone, adjacent steps >= 0.06 apart, light end >= 2:1 on the surface), against the
# --surface colours in app/front/src/styles.css:
#   node scripts/validate_palette.js "#ee8f63,#df6c32,#c84f00,#a53e00,#803200" \
#     --mode light --surface "#fcfcfb" --ordinal    -> ALL CHECKS PASS (2026-11-14)
#   node scripts/validate_palette.js "#ee8f63,#df6c32,#c84f00,#a53e00,#803200" \
#     --mode dark --surface "#0d0d0d" --ordinal     -> ALL CHECKS PASS (2026-11-14)
# Re-run both before changing it. Tiles interpolate between the stops in OKLab, where lightness is
# linear, so values between two stops stay between them in lightness too.
RAMP = ("#ee8f63", "#df6c32", "#c84f00", "#a53e00", "#803200")

MEASURE = "Highest monthly chance of a wildfire within 100 km"
NO_DATA_LABEL = "No data (ocean, or outside the dataset)"
NOTE = (
    "The highest monthly chance in the year of a wildfire within 100 km, not at the building: "
    "0.7 is a 70% chance. physrisk divides it by 500 before working out damage, so this map and "
    "the loss figures aren't on the same scale. Cells are about 28 km across, so the map shows the "
    "region, not the property. A low or empty area is not proof of low risk."
)


def _source(cover: Coverage) -> str:
    return (
        "Source: Jupiter Intelligence, via OS-Climate physrisk. physrisk lists its licence as "
        f'"{cover.licence}".'
    )


SPEC = GridSpec(
    hazard=HAZARD,
    noun=NOUN,
    measure=MEASURE,
    ramp=RAMP,
    no_data_label=NO_DATA_LABEL,
    note=NOTE,
    source=_source,
)


def read_coverage(inventory: list[dict[str, Any]], path: str = FIRE_PATH) -> Coverage:
    """The fire resource's scenarios, years, licence and top value. Raises if it's gone."""
    return grid_layer.read_coverage(inventory, path, HAZARD)


@cache
def coverage() -> Coverage:
    return read_coverage(physrisk_inventory(), _layer.path)


def unavailable_reason(scenario: str, year: int | None, cover: Coverage) -> str | None:
    """Why a scenario and year has no wildfire map, or None for an exact inventory match."""
    return grid_layer.unavailable_reason(scenario, year, cover, NOUN)


def configure(
    path: str = FIRE_PATH, max_zoom: int = MAX_ZOOM, settings: GridSettings | None = None
) -> GridLayer:
    """Build the wildfire layer from the run settings. Its reads, samples and renders go through
    this module's functions, looked up at call time, so patching them here takes effect."""
    global _layer
    store = _layer.store if "_layer" in globals() else None
    _layer = GridLayer(
        SPEC,
        path,
        max_zoom,
        settings or GridSettings(BUCKET_ROOT, ALPHA, LEGEND_STOPS, CACHE_ARRAYS, CACHE_TILES),
        load=lambda scenario, year: _load(scenario, year),
        coverage=lambda: coverage(),
        sample=lambda g, z, x, y: sample(g, z, x, y),
        render=lambda values, max_value: render(values, max_value),
    )
    _layer.store = store
    coverage.cache_clear()
    return _layer


_layer: GridLayer
configure()


def layer() -> GridLayer:
    return _layer


def use_store(store: MutableMapping | None) -> None:
    """Read from this zarr store instead of the public bucket (None: back to the bucket)."""
    _layer.use_store(store)


def clear_caches() -> None:
    _layer.clear_caches()


def _load(scenario: str, year: int) -> Grid:
    return _layer.read(scenario, year)


def grid(scenario: str, year: int) -> Grid:
    """The whole array for a pair, read once and kept while it's among the recently used."""
    return _layer.grid(scenario, year)


def in_range(z: int, x: int, y: int) -> bool:
    return _layer.in_range(z, x, y)


def colour_table() -> np.ndarray:
    """RGBA for 257 evenly spaced values from 0 to the top of the scale."""
    return _layer.colour_table()


def colours(values: np.ndarray, max_value: float) -> np.ndarray:
    """RGBA pixels: NaN is transparent, and a finite value (0 included) is on the ramp."""
    return _layer.colours(values, max_value)


def legend() -> list[str]:
    """CSS colours from 0 to the top of the scale, the same ones the tiles are drawn with."""
    return _layer.legend()


def render(values: np.ndarray, max_value: float) -> bytes | None:
    """A PNG of the pixels, or None when none of them has data."""
    return _layer.draw(values, max_value)


def tile(scenario: str, year: int | None, z: int, x: int, y: int) -> bytes | None:
    """A 512 px PNG tile, or None where there's no map. S3 and layout failures raise."""
    return _layer.tile(scenario, year, z, x, y)
