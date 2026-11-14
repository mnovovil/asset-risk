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

S3 reads never hold assess._physrisk_lock: that lock is only for calls into physrisk, and holding
it for a download would stall a running assessment.
"""

from __future__ import annotations

import io
import json
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

import numpy as np

from engine.assess import HISTORICAL
from engine.lru import LruCache

HAZARD = "Fire"
FIRE_PATH = "fire/jupiter/v1/fire_probability_{scenario}_{year}"
BUCKET_ROOT = "os-climate-physical-risk/hazard-indicators/hazard.zarr"
CRS = "EPSG:4326"
TILE_PX = 512
# A 0.25 degree cell is about 23 px wide at zoom 6 and 11 px at zoom 5: deeper tiles would add
# nothing, and MapLibre stretches them with nearest-neighbour sampling.
MAX_ZOOM = 6
CACHE_ARRAYS = 4  # about 4 MB each
CACHE_TILES = 256
ALPHA = 200  # as the flood tiles, so the base map shows through
LEGEND_STOPS = 9
_LUT_STEPS = 256  # the LUT has _LUT_STEPS + 1 entries, so the ramp's stops land on exact entries

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


class HazardMapConfigError(RuntimeError):
    """physrisk's inventory or the array no longer looks as this module expects."""


@dataclass(frozen=True)
class Coverage:
    """What physrisk's inventory says about the fire resource."""

    scenarios: Mapping[str, tuple[int, ...]]
    licence: str
    max_value: float


def physrisk_inventory() -> list[dict[str, Any]]:
    """The resources in physrisk's embedded inventory."""
    source = resources.files("physrisk") / "data" / "static" / "hazard" / "inventory.json"
    return json.loads(source.read_text())["resources"]


def read_coverage(inventory: list[dict[str, Any]]) -> Coverage:
    """The fire resource's scenarios, years, licence and top value. Raises if it's gone."""
    resource = next((r for r in inventory if r.get("path") == FIRE_PATH), None)
    if resource is None:
        raise HazardMapConfigError(f"physrisk's inventory has no {FIRE_PATH}")
    if resource.get("hazard_type") != HAZARD:
        raise HazardMapConfigError(f"{FIRE_PATH} is no longer a {HAZARD} resource")
    scenarios = {
        s["id"]: tuple(sorted(s["years"])) for s in resource.get("scenarios", []) if s.get("years")
    }
    if not scenarios:
        raise HazardMapConfigError(f"physrisk's inventory lists no scenarios for {FIRE_PATH}")
    try:
        max_value = float(resource["map"]["colormap"]["max_value"])
    except (KeyError, TypeError, ValueError) as e:
        raise HazardMapConfigError(f"{FIRE_PATH} has no colour scale in the inventory") from e
    if not max_value > 0:
        raise HazardMapConfigError(f"{FIRE_PATH} has a colour scale up to {max_value}")
    return Coverage(scenarios, str(resource.get("license") or "not stated"), max_value)


@cache
def coverage() -> Coverage:
    return read_coverage(physrisk_inventory())


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def unavailable_reason(scenario: str, year: int | None, cover: Coverage) -> str | None:
    """Why a scenario and year has no wildfire map, or None for an exact inventory match."""
    if scenario == HISTORICAL:
        return "physrisk's wildfire data has no historical baseline"
    if scenario not in cover.scenarios:
        return f"physrisk's wildfire data covers {_and(sorted(cover.scenarios))} only"
    years = cover.scenarios[scenario]
    if year not in years:
        return f"physrisk's wildfire data for {scenario} has {_and([str(y) for y in years])} only"
    return None


# --- Reading the array ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Grid:
    """Cell values, north up, on a regular lon/lat grid: cell (row, col) has its corner at
    (x0 + col * dx, y0 + row * dy)."""

    values: np.ndarray  # 2-D float32, NaN where there's no data
    x0: float
    dx: float
    y0: float
    dy: float


def grid_from(values: np.ndarray, attrs: Mapping[str, Any]) -> Grid:
    """Check an array's layout and turn it into a Grid. Raises HazardMapConfigError otherwise."""
    if values.ndim != 3 or values.shape[0] != 1:
        raise HazardMapConfigError(f"expected a (1, rows, cols) array, not {values.shape}")
    crs = attrs.get("crs")
    if crs is not None and str(crs).upper() != CRS:
        raise HazardMapConfigError(f"expected {CRS}, not {crs}")
    t = attrs.get("transform_mat3x3")
    if not isinstance(t, list | tuple) or len(t) != 9:
        raise HazardMapConfigError("the array has no transform_mat3x3")
    dx, rx, x0, ry, dy, y0 = (float(v) for v in t[:6])
    if rx != 0 or ry != 0 or not dx > 0 or not dy < 0:
        raise HazardMapConfigError(f"expected a north-up grid with no rotation, not {list(t)}")
    return Grid(np.asarray(values[0], dtype=np.float32), x0, dx, y0, dy)


_store: MutableMapping | None = None
_arrays: LruCache[Grid] = LruCache(CACHE_ARRAYS)
_tiles: LruCache[bytes | None] = LruCache(CACHE_TILES)


def use_store(store: MutableMapping | None) -> None:
    """Read from this zarr store instead of the public bucket (None: back to the bucket)."""
    global _store
    _store = store
    clear_caches()


def clear_caches() -> None:
    _arrays.clear()
    _tiles.clear()


def _bucket() -> MutableMapping:
    import s3fs

    return s3fs.S3Map(root=BUCKET_ROOT, s3=s3fs.S3FileSystem(anon=True), check=False)


def _load(scenario: str, year: int) -> Grid:
    import zarr

    root = zarr.open(_store if _store is not None else _bucket(), mode="r")
    array = root[FIRE_PATH.format(scenario=scenario, year=year)]
    return grid_from(array[:], dict(array.attrs))


def grid(scenario: str, year: int) -> Grid:
    """The whole array for a pair, read once and kept while it's among the recently used."""
    return _arrays.get_or_load((scenario, year), lambda: _load(scenario, year))


# --- Tiles ---------------------------------------------------------------------------------------


def in_range(z: int, x: int, y: int) -> bool:
    return 0 <= z <= MAX_ZOOM and 0 <= x < 2**z and 0 <= y < 2**z


def pixel_lonlat(z: int, x: int, y: int) -> tuple[np.ndarray, np.ndarray]:
    """The longitudes of a tile's pixel columns and the latitudes of its rows, at pixel centres."""
    n = TILE_PX * 2**z
    offsets = np.arange(TILE_PX) + 0.5
    lon = (x * TILE_PX + offsets) / n * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y * TILE_PX + offsets) / n))))
    return lon, lat


def _columns(g: Grid, lon: np.ndarray) -> np.ndarray:
    """The cell column under each longitude, -1 when none. Shifts by 360 only to fit."""
    cols = g.values.shape[1]
    found = np.full(lon.shape, -1)
    for shift in (0.0, 360.0, -360.0):
        col = np.floor((lon + shift - g.x0) / g.dx).astype(int)
        hit = (found < 0) & (col >= 0) & (col < cols)
        found[hit] = col[hit]
    return found


def sample(g: Grid, z: int, x: int, y: int) -> np.ndarray:
    """The tile's pixels, each the value of the cell its centre falls in (nearest neighbour)."""
    lon, lat = pixel_lonlat(z, x, y)
    cols = _columns(g, lon)
    rows = np.floor((lat - g.y0) / g.dy).astype(int)
    rows[(rows < 0) | (rows >= g.values.shape[0])] = -1
    out = np.full((TILE_PX, TILE_PX), np.nan, dtype=np.float32)
    r_ok, c_ok = rows >= 0, cols >= 0
    out[np.ix_(r_ok, c_ok)] = g.values[np.ix_(rows[r_ok], cols[c_ok])]
    return out


def _hex_to_linear(colour: str) -> np.ndarray:
    srgb = np.array([int(colour[i : i + 2], 16) for i in (1, 3, 5)]) / 255
    return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)


def _linear_to_oklab(rgb: np.ndarray) -> np.ndarray:
    m1 = np.array(
        [
            [0.4122214708, 0.5363325363, 0.0514459929],
            [0.2119034982, 0.6806995451, 0.1073969566],
            [0.0883024619, 0.2817188376, 0.6299787005],
        ]
    )
    m2 = np.array(
        [
            [0.2104542553, 0.7936177850, -0.0040720468],
            [1.9779984951, -2.4285922050, 0.4505937099],
            [0.0259040371, 0.7827717662, -0.8086757660],
        ]
    )
    return np.cbrt(rgb @ m1.T) @ m2.T


def _oklab_to_srgb8(lab: np.ndarray) -> np.ndarray:
    m1 = np.array(
        [
            [1.0, 0.3963377774, 0.2158037573],
            [1.0, -0.1055613458, -0.0638541728],
            [1.0, -0.0894841775, -1.2914855480],
        ]
    )
    m2 = np.array(
        [
            [4.0767416621, -3.3077115913, 0.2309699292],
            [-1.2684380046, 2.6097574011, -0.3413193965],
            [-0.0041960863, -0.7034186147, 1.7076147010],
        ]
    )
    rgb = np.clip(((lab @ m1.T) ** 3) @ m2.T, 0, 1)
    srgb = np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * rgb ** (1 / 2.4) - 0.055)
    return np.round(srgb * 255).astype(np.uint8)


@cache
def colour_table() -> np.ndarray:
    """RGBA for _LUT_STEPS + 1 evenly spaced values from 0 to the top of the scale."""
    stops = np.array([_linear_to_oklab(_hex_to_linear(c)) for c in RAMP])
    at = np.linspace(0, len(RAMP) - 1, _LUT_STEPS + 1)
    lab = np.array([np.interp(at, np.arange(len(RAMP)), stops[:, i]) for i in range(3)]).T
    rgba = np.empty((_LUT_STEPS + 1, 4), dtype=np.uint8)
    rgba[:, :3] = _oklab_to_srgb8(lab)
    rgba[:, 3] = ALPHA
    return rgba


def colours(values: np.ndarray, max_value: float) -> np.ndarray:
    """RGBA pixels: NaN is transparent, and a finite value (0 included) is on the ramp."""
    finite = np.isfinite(values)
    index = np.zeros(values.shape, dtype=int)
    scaled = np.clip(np.where(finite, values, 0) / max_value, 0, 1)
    index[finite] = np.round(scaled[finite] * _LUT_STEPS).astype(int)
    rgba = colour_table()[index]
    rgba[~finite] = 0
    return rgba


def legend() -> list[str]:
    """CSS colours from 0 to the top of the scale, the same ones the tiles are drawn with."""
    table = colour_table()
    picks = [round(_LUT_STEPS * i / (LEGEND_STOPS - 1)) for i in range(LEGEND_STOPS)]
    alpha = round(ALPHA / 255, 2)
    return [f"rgba({r}, {g}, {b}, {alpha})" for r, g, b, _ in (table[i] for i in picks)]


def render(values: np.ndarray, max_value: float) -> bytes | None:
    """A PNG of the pixels, or None when none of them has data."""
    if not np.isfinite(values).any():
        return None
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(colours(values, max_value), "RGBA").save(buffer, format="PNG")
    return buffer.getvalue()


def tile(scenario: str, year: int | None, z: int, x: int, y: int) -> bytes | None:
    """A 512 px PNG tile, or None where there's no map. S3 and layout failures raise."""
    cover = coverage()
    if unavailable_reason(scenario, year, cover) or not in_range(z, x, y):
        return None
    assert year is not None  # an exact match with the inventory has a year
    key = (scenario, year, z, x, y)
    found, cached = _tiles.get(key)
    if found:
        return cached
    image = render(sample(grid(scenario, year), z, x, y), cover.max_value)
    _tiles.put(key, image)
    return image


@dataclass(frozen=True)
class FireLayer:
    """The wildfire layer, as hazard_maps.LAYERS lists it."""

    hazard: str = HAZARD
    measure: str = MEASURE
    units: str = ""
    return_period: int | None = None
    min_value: float = 0.0
    max_zoom: int = MAX_ZOOM
    no_data_label: str = NO_DATA_LABEL
    note: str = NOTE

    @property
    def max_value(self) -> float:
        return coverage().max_value

    @property
    def source(self) -> str:
        return (
            "Source: Jupiter Intelligence, via OS-Climate physrisk. physrisk lists its licence as "
            f'"{coverage().licence}".'
        )

    def reason(self, scenario: str, year: int | None) -> str | None:
        return unavailable_reason(scenario, year, coverage())

    def legend(self) -> list[str]:
        return legend()

    def tile(self, scenario: str, year: int | None, z: int, x: int, y: int, requester=None):
        return tile(scenario, year, z, x, y)
