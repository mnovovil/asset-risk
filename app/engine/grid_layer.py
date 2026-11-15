"""Hazard map tiles drawn here from a zarr grid in physrisk's public S3 bucket.

physrisk's image API only draws the public WRI flood maps: it refuses the other hazards' maps on
permissions. Some of their arrays are public anyway, so a GridLayer reads one anonymously with s3fs
and zarr and draws Web Mercator tiles itself. A layer is a GridSpec (what the data is, and how it's
coloured and described: kept in code) plus the run settings from .asset-risk.json (bucket, path,
zoom, alpha, legend and cache sizes). fire_map.py and wind_map.py are the two layers.

Each layer:
- checks its path against physrisk's embedded inventory, and takes its scenarios, years, units,
  licence and colour scale from there. Only an exact scenario and year match gets a map
- checks the array's layout (a north-up, unrotated EPSG:4326 grid), and picks one return period
  from its index when the array has several
- samples each tile pixel from the cell its centre falls in (nearest neighbour), shifting a
  longitude by 360 degrees only when it falls outside the grid
- draws NaN transparent and every finite value on its ramp, interpolated in OKLab

S3 reads never hold assess._physrisk_lock: that lock is only for calls into physrisk, and holding
it for a download would stall a running assessment.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

import numpy as np

from engine.assess import HISTORICAL
from engine.lru import LruCache

BUCKET_ROOT = "os-climate-physical-risk/hazard-indicators/hazard.zarr"
CRS = "EPSG:4326"
# Fixed: physrisk's flood tiles are 512 px, and the dashboard's map asks for that size.
TILE_PX = 512
_LUT_STEPS = 256  # the LUT has _LUT_STEPS + 1 entries, so the ramp's stops land on exact entries


class HazardMapConfigError(RuntimeError):
    """physrisk's inventory or the array no longer looks as the layer expects."""


# --- physrisk's inventory ------------------------------------------------------------------------


@dataclass(frozen=True)
class Coverage:
    """What physrisk's inventory says about a resource."""

    scenarios: Mapping[str, tuple[int, ...]]
    licence: str
    max_value: float
    units: str = ""
    attribution: str = ""


def physrisk_inventory() -> list[dict[str, Any]]:
    """The resources in physrisk's embedded inventory."""
    source = resources.files("physrisk") / "data" / "static" / "hazard" / "inventory.json"
    return json.loads(source.read_text())["resources"]


def read_coverage(inventory: list[dict[str, Any]], path: str, hazard_type: str) -> Coverage:
    """A resource's scenarios, years, licence and top value. Raises if it's gone or changed."""
    resource = next((r for r in inventory if r.get("path") == path), None)
    if resource is None:
        raise HazardMapConfigError(f"physrisk's inventory has no {path}")
    if resource.get("hazard_type") != hazard_type:
        raise HazardMapConfigError(f"{path} is no longer a {hazard_type} resource")
    scenarios = {
        s["id"]: tuple(sorted(s["years"])) for s in resource.get("scenarios", []) if s.get("years")
    }
    if not scenarios:
        raise HazardMapConfigError(f"physrisk's inventory lists no scenarios for {path}")
    try:
        max_value = float(resource["map"]["colormap"]["max_value"])
    except (KeyError, TypeError, ValueError) as e:
        raise HazardMapConfigError(f"{path} has no colour scale in the inventory") from e
    if not max_value > 0:
        raise HazardMapConfigError(f"{path} has a colour scale up to {max_value}")
    return Coverage(
        scenarios,
        str(resource.get("license") or "not stated"),
        max_value,
        str(resource.get("units") or ""),
        str(resource.get("attribution") or ""),
    )


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def unavailable_reason(
    scenario: str, year: int | None, cover: Coverage, noun: str, other_years: str = ""
) -> str | None:
    """Why a scenario and year has no map, or None for an exact inventory match.

    The historical baseline matches when the inventory lists one, whatever its year.
    """
    if scenario == HISTORICAL:
        if HISTORICAL in cover.scenarios:
            return None
        return f"physrisk's {noun} data has no historical baseline"
    projected = sorted(s for s in cover.scenarios if s != HISTORICAL)
    if scenario not in projected:
        return f"physrisk's {noun} data covers {_and(projected)} only"
    years = cover.scenarios[scenario]
    if year not in years:
        return (
            f"physrisk's {noun} data for {scenario} has {_and([str(y) for y in years])} only"
            + other_years
        )
    return None


def data_year(scenario: str, year: int | None, cover: Coverage) -> int:
    """The year in the array's path: the baseline's own year for historical."""
    if scenario == HISTORICAL:
        return cover.scenarios[HISTORICAL][-1]
    assert year is not None  # an exact match with the inventory has a year
    return year


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


def return_period_index(attrs: Mapping[str, Any], depth: int, return_period: int) -> int:
    """Where a return period sits in an array's first dimension. Raises if it isn't there."""
    values = attrs.get("index_values")
    if not isinstance(values, list | tuple) or len(values) != depth:
        raise HazardMapConfigError(f"expected {depth} index_values, not {values!r}")
    try:
        return [float(v) for v in values].index(float(return_period))
    except ValueError:
        raise HazardMapConfigError(
            f"the array has no {return_period}-year return period, only {list(values)}"
        ) from None


def read_grid(array: Any, return_period: int | None) -> Grid:
    """A zarr array as a Grid, reading only the one return period's slice when there are several."""
    attrs = dict(array.attrs)
    if return_period is None:
        return grid_from(array[:], attrs)
    if len(array.shape) != 3:
        raise HazardMapConfigError(f"expected an (index, rows, cols) array, not {array.shape}")
    i = return_period_index(attrs, array.shape[0], return_period)
    return grid_from(array[i : i + 1], attrs)


def open_bucket(root: str) -> MutableMapping:
    import s3fs

    return s3fs.S3Map(root=root, s3=s3fs.S3FileSystem(anon=True), check=False)


# --- Tiles ---------------------------------------------------------------------------------------


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


# --- Colours -------------------------------------------------------------------------------------


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
def colour_table(ramp: tuple[str, ...], alpha: int) -> np.ndarray:
    """RGBA for _LUT_STEPS + 1 evenly spaced values from the bottom of the scale to the top."""
    stops = np.array([_linear_to_oklab(_hex_to_linear(c)) for c in ramp])
    at = np.linspace(0, len(ramp) - 1, _LUT_STEPS + 1)
    lab = np.array([np.interp(at, np.arange(len(ramp)), stops[:, i]) for i in range(3)]).T
    rgba = np.empty((_LUT_STEPS + 1, 4), dtype=np.uint8)
    rgba[:, :3] = _oklab_to_srgb8(lab)
    rgba[:, 3] = alpha
    rgba.setflags(write=False)
    return rgba


def colours(table: np.ndarray, values: np.ndarray, max_value: float) -> np.ndarray:
    """RGBA pixels: NaN is transparent, and a finite value (0 included) is on the ramp."""
    finite = np.isfinite(values)
    index = np.zeros(values.shape, dtype=int)
    scaled = np.clip(np.where(finite, values, 0) / max_value, 0, 1)
    index[finite] = np.round(scaled[finite] * _LUT_STEPS).astype(int)
    rgba = table[index]
    rgba[~finite] = 0
    return rgba


def legend(table: np.ndarray, stops: int) -> list[str]:
    """CSS colours from 0 to the top of the scale, the same ones the tiles are drawn with."""
    picks = [round(_LUT_STEPS * i / (stops - 1)) for i in range(stops)]
    return [f"rgba({r}, {g}, {b}, {round(a / 255, 2)})" for r, g, b, a in (table[i] for i in picks)]


def png(rgba: np.ndarray) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buffer, format="PNG")
    return buffer.getvalue()


# --- A layer -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GridSpec:
    """What a layer's data is and how it's drawn and described. Kept in code, not in settings."""

    hazard: str  # the physrisk hazard type, and the layer's key
    noun: str  # for reasons, e.g. "physrisk's wildfire data covers ..."
    measure: str
    ramp: tuple[str, ...]  # validated, lowest value first
    no_data_label: str
    note: str
    source: Callable[[Coverage], str]
    return_period: int | None = None  # the index to read, for an array of return periods
    other_years: str = ""  # appended to the reason when only the year is missing


@dataclass(frozen=True)
class GridSettings:
    """The run settings shared by every grid layer, from .asset-risk.json."""

    bucket: str = BUCKET_ROOT
    alpha: int = 200  # as the flood tiles, so the base map shows through
    legend_stops: int = 9
    array_cache: int = 4
    tile_cache: int = 256


class GridLayer:
    """A hazard map layer drawn from one zarr array per scenario and year (hazard_maps.MapLayer).

    load, coverage, sample and render can be swapped, so a module can keep its own functions on
    the call path: fire_map's tests patch them there.
    """

    min_value = 0.0

    def __init__(
        self,
        spec: GridSpec,
        path: str,
        max_zoom: int,
        settings: GridSettings | None = None,
        *,
        load: Callable[[str, int], Grid] | None = None,
        coverage: Callable[[], Coverage] | None = None,
        sample: Callable[[Grid, int, int, int], np.ndarray] | None = None,
        render: Callable[[np.ndarray, float], bytes | None] | None = None,
    ):
        self.spec = spec
        self.path = path
        self.max_zoom = max_zoom
        self.settings = settings = settings or GridSettings()
        self.store: MutableMapping | None = None
        self._load = load or self.read
        self._coverage = coverage or self._inventory_coverage
        self._sample = sample or globals()["sample"]
        self._render = render or self.draw
        self._arrays: LruCache[Grid] = LruCache(settings.array_cache)
        self._tiles: LruCache[bytes | None] = LruCache(settings.tile_cache)
        self._cover: Coverage | None = None

    # Self-description, as the API reads it.

    @property
    def hazard(self) -> str:
        return self.spec.hazard

    @property
    def measure(self) -> str:
        return self.spec.measure

    @property
    def return_period(self) -> int | None:
        return self.spec.return_period

    @property
    def no_data_label(self) -> str:
        return self.spec.no_data_label

    @property
    def note(self) -> str:
        return self.spec.note

    @property
    def units(self) -> str:
        return self._coverage().units

    @property
    def max_value(self) -> float:
        return self._coverage().max_value

    @property
    def source(self) -> str:
        return self.spec.source(self._coverage())

    def coverage(self) -> Coverage:
        return self._coverage()

    def _inventory_coverage(self) -> Coverage:
        if self._cover is None:
            self._cover = read_coverage(physrisk_inventory(), self.path, self.spec.hazard)
        return self._cover

    def reason(self, scenario: str, year: int | None) -> str | None:
        return unavailable_reason(
            scenario, year, self._coverage(), self.spec.noun, self.spec.other_years
        )

    # Colours.

    def colour_table(self) -> np.ndarray:
        return colour_table(self.spec.ramp, self.settings.alpha)

    def colours(self, values: np.ndarray, max_value: float) -> np.ndarray:
        return colours(self.colour_table(), values, max_value)

    def legend(self) -> list[str]:
        return legend(self.colour_table(), self.settings.legend_stops)

    def draw(self, values: np.ndarray, max_value: float) -> bytes | None:
        """A PNG of the pixels, or None when none of them has data."""
        if not np.isfinite(values).any():
            return None
        return png(self.colours(values, max_value))

    # Reading.

    def use_store(self, store: MutableMapping | None) -> None:
        """Read from this zarr store instead of the bucket (None: back to the bucket)."""
        self.store = store
        self.clear_caches()

    def clear_caches(self) -> None:
        self._arrays.clear()
        self._tiles.clear()

    def read(self, scenario: str, year: int) -> Grid:
        """Read one scenario and year's array from the store, or the bucket."""
        import zarr

        root = zarr.open(
            self.store if self.store is not None else open_bucket(self.settings.bucket), mode="r"
        )
        array = root[self.path.format(scenario=scenario, year=year)]
        return read_grid(array, self.spec.return_period)

    def grid(self, scenario: str, year: int) -> Grid:
        """The whole array for a pair, read once and kept while it's among the recently used."""
        return self._arrays.get_or_load((scenario, year), lambda: self._load(scenario, year))

    # Tiles.

    def in_range(self, z: int, x: int, y: int) -> bool:
        return 0 <= z <= self.max_zoom and 0 <= x < 2**z and 0 <= y < 2**z

    def tile(
        self, scenario: str, year: int | None, z: int, x: int, y: int, requester=None
    ) -> bytes | None:
        """A 512 px PNG tile, or None where there's no map. S3 and layout failures raise."""
        cover = self._coverage()
        if self.reason(scenario, year) or not self.in_range(z, x, y):
            return None
        at = data_year(scenario, year, cover)
        key = (scenario, at, z, x, y)
        found, cached = self._tiles.get(key)
        if found:
            return cached
        image = self._render(self._sample(self.grid(scenario, at), z, x, y), cover.max_value)
        self._tiles.put(key, image)
        return image
