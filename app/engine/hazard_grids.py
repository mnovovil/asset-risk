"""Regional maps of physrisk's non-flood hazard grids around an asset, from the raw zarr arrays.

physrisk's image API serves only the WRI flood maps (see hazard_maps.py), but every resource in its
inventory is a zarr array in the public os-climate-physical-risk bucket, readable anonymously.
data/hazard_grids.json lists the layers and why the others are left out. This module checks it
against physrisk's embedded inventory, reads a window of about +-1 degree around an asset, and draws
it as a PNG with one pixel per cell, north up.

The reader never substitutes a year or a scenario: a pair the inventory doesn't list for a layer
has no data, with a reason. The value at the asset is the cell the asset sits in, the one drawn
under its marker, never an interpolated value. Every zarr read runs under physrisk's lock, as
hazard curves do.
"""

from __future__ import annotations

import io
import json
import math
import string
import threading
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np

from engine.assess import HISTORICAL, _physrisk_lock
from engine.hazard_maps import _Cache

DATA_FILE = Path(__file__).parent / "data" / "hazard_grids.json"
BUCKET_ROOT = "os-climate-physical-risk/hazard-indicators/hazard.zarr"
WINDOW_DEGREES = 1.0
THEMES = ("light", "dark")
ALPHA = 200  # as the flood tiles, so the base map shows through
CACHE_WINDOWS = 128
CACHE_IMAGES = 128
KM_PER_DEGREE_LAT = 110.574
KM_PER_DEGREE_LON = 111.320
_LEGACY_NAN = -9999.0
_COORD_NAMES = {"lat": ("lat", "latitude"), "lon": ("lon", "longitude")}
_PLACEHOLDERS = {"scenario", "year"}


class CatalogueError(RuntimeError):
    """data/hazard_grids.json no longer matches physrisk's inventory or the arrays."""


class NoGridData(Exception):  # noqa: N818 (an outcome, not a failure)
    """A layer has no data for a scenario and year, or around a point. str() is the reason."""


@dataclass(frozen=True)
class GridLayer:
    id: str
    hazard: str
    path: str
    params: Mapping[str, str]
    index: float | None
    index_label: str
    name: str
    dataset: str
    attribution: str
    units: str
    feeds_damage: bool
    caveat: str | None
    netcdf_coords: bool
    nodata_values: tuple[float, ...]
    # Scenario id to years, as physrisk's inventory lists them.
    scenarios: Mapping[str, tuple[int, ...]]

    def array_path(self, scenario: str, year: int | None) -> str:
        """The zarr path for a pair, or NoGridData. Historical has the inventory's baseline year."""
        reason = unavailable_reason(self, scenario, year)
        if reason:
            raise NoGridData(reason)
        if scenario == HISTORICAL:
            year = min(self.scenarios[HISTORICAL])
        path = self.path.format(**self.params, scenario=scenario, year=year)
        return f"{path}/indicator" if self.netcdf_coords else path


@dataclass(frozen=True)
class Window:
    """Cells around an asset, north up: row 0 is the northern edge."""

    values: np.ndarray  # float64, NaN where there's no data
    bounds: tuple[float, float, float, float]  # west, south, east, north, on cell edges
    asset_value: float | None  # the asset's own cell, None when it has no data
    cell_km: tuple[float, float]  # east-west and north-south size of a cell at the asset

    def value_range(self) -> tuple[float, float] | None:
        finite = self.values[np.isfinite(self.values)]
        return (float(finite.min()), float(finite.max())) if finite.size else None


@dataclass(frozen=True)
class GridView:
    """What the panel shows for a layer: a window and its colour scale, or why there's none."""

    layer: GridLayer
    window: Window | None
    reason: str | None
    min_value: float | None = None
    max_value: float | None = None


@dataclass(frozen=True)
class _Grid:
    """Where an array's cells are: x = x0 + col * dx, y = y0 + row * dy, for cell edges."""

    x0: float
    dx: float
    y0: float
    dy: float
    rows: int
    cols: int
    index_position: int

    @property
    def global_columns(self) -> int | None:
        """How many columns make 360 degrees, when the grid wraps around the world."""
        span = self.cols * abs(self.dx)
        return round(360 / abs(self.dx)) if span >= 360 - abs(self.dx) / 2 else None

    @property
    def zero_to_360(self) -> bool:
        return self.x0 >= 0 and self.x0 + self.cols * self.dx > 180


def _data() -> dict[str, Any]:
    return json.loads(DATA_FILE.read_text())


def ramp(theme: str) -> list[str]:
    """The theme's colours, from the lowest value to the highest."""
    if theme not in THEMES:
        raise ValueError(f"theme must be one of {', '.join(THEMES)}")
    return list(_data()["ramps"][theme])


def legend(theme: str) -> list[str]:
    """CSS colours from the lowest value to the highest, as the PNG draws them."""
    alpha = round(ALPHA / 255, 2)
    return [f"rgba({r}, {g}, {b}, {alpha})" for r, g, b in map(_rgb, ramp(theme))]


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    value = hex_colour.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def physrisk_inventory() -> list[dict[str, Any]]:
    """The resources in physrisk's embedded inventory."""
    source = resources.files("physrisk") / "data" / "static" / "hazard" / "inventory.json"
    return json.loads(source.read_text())["resources"]


def excluded_reason(path: str, data: Mapping[str, Any] | None = None) -> str | None:
    """Why an inventory path has no layer, or None when it isn't excluded."""
    data = data or _data()
    for item in data["excluded"]:
        if item["path"] == path:
            return item["reason"]
    for item in data["excluded_prefixes"]:
        if path.startswith(item["prefix"]):
            return item["reason"]
    return None


def build_catalogue(
    data: Mapping[str, Any], inventory: list[dict[str, Any]]
) -> dict[str, GridLayer]:
    """Resolve each layer to its inventory resource. Raises CatalogueError on any mismatch."""
    by_path = {resource["path"]: resource for resource in inventory}
    layers: dict[str, GridLayer] = {}
    for entry in data["layers"]:
        layer_id, path = entry["id"], entry["path"]
        if layer_id in layers:
            raise CatalogueError(f"{layer_id} is listed twice")
        resource = by_path.get(path)
        if resource is None:
            raise CatalogueError(f"{layer_id}: physrisk's inventory has no {path}")
        if excluded_reason(path, data):
            raise CatalogueError(f"{layer_id}: {path} is also excluded")
        fields = {name for _, name, _, _ in string.Formatter().parse(path) if name}
        params = dict(entry["params"])
        if fields - _PLACEHOLDERS != set(params):
            raise CatalogueError(
                f"{layer_id}: params {sorted(params)} don't match {sorted(fields - _PLACEHOLDERS)}"
            )
        for name, value in params.items():
            allowed = [str(v) for v in resource.get("params", {}).get(name, [])]
            if value not in allowed:
                raise CatalogueError(f"{layer_id}: physrisk has no {name}={value} for {path}")
        scenarios = {s["id"]: tuple(sorted(s["years"])) for s in resource["scenarios"]}
        if not scenarios:
            raise CatalogueError(f"{layer_id}: physrisk lists no scenarios for {path}")
        layers[layer_id] = GridLayer(
            id=layer_id,
            hazard=entry["hazard"],
            path=path,
            params=params,
            index=entry["index"],
            index_label=entry["index_label"],
            name=entry["name"],
            dataset=entry["dataset"],
            attribution=entry["attribution"],
            units=entry["units"],
            feeds_damage=entry["feeds_damage"],
            caveat=entry["caveat"],
            netcdf_coords=bool(resource.get("store_netcdf_coords")),
            nodata_values=tuple(float(v) for v in entry["nodata_values"]),
            scenarios=scenarios,
        )
        if layers[layer_id].hazard != resource["hazard_type"]:
            raise CatalogueError(f"{layer_id}: physrisk files {path} under another hazard")
    return layers


@cache
def catalogue() -> dict[str, GridLayer]:
    """The layers, checked against physrisk's inventory on first use."""
    return build_catalogue(_data(), physrisk_inventory())


def unavailable_reason(layer: GridLayer, scenario: str, year: int | None) -> str | None:
    """Why a layer has no data for a pair, or None. Never another year or scenario instead."""
    if scenario == HISTORICAL:
        return None if HISTORICAL in layer.scenarios else "This dataset has no historical baseline"
    years = layer.scenarios.get(scenario)
    if years is None:
        return f"This dataset has no {scenario} scenario"
    if year not in years:
        listed = ", ".join(map(str, years))
        return f"This dataset has no {year} for {scenario}: it has {listed}"
    return None


# Reading -----------------------------------------------------------------------------------------

_root: Any = None
_root_lock = threading.Lock()
_grids: dict[str, _Grid] = {}
_windows = _Cache(CACHE_WINDOWS)
_images = _Cache(CACHE_IMAGES)


def use_store(store: MutableMapping | None) -> None:
    """Read from this zarr store instead of the public bucket (None: back to the bucket)."""
    global _root
    with _root_lock:
        _root = None if store is None else _open(store)
        clear_caches()


def clear_caches() -> None:
    _grids.clear()
    _windows.clear()
    _images.clear()


def _open(store: MutableMapping):
    import zarr

    return zarr.open(store, mode="r")


def _store_root():
    """The zarr root group: the public bucket, unless use_store() gave another store."""
    global _root
    with _root_lock:
        if _root is None:
            # Anonymous on purpose: physrisk's own credentials, if any, aren't needed for this.
            import s3fs

            s3 = s3fs.S3FileSystem(anon=True)
            _root = _open(s3fs.S3Map(root=BUCKET_ROOT, s3=s3, check=False))
        return _root


def _axis(group, names: tuple[str, ...]) -> np.ndarray:
    for name in names:
        if name in group:
            return np.asarray(group[name][:], dtype=float)
    raise CatalogueError(f"{group.path} has none of {', '.join(names)}")


def _regular_edges(centres: np.ndarray, what: str) -> tuple[float, float]:
    """The first cell edge and the step of evenly spaced cell centres."""
    if centres.size < 2:
        raise CatalogueError(f"{what} has fewer than two cells")
    steps = np.diff(centres)
    step = float(steps.mean())
    if not np.allclose(steps, step, rtol=1e-4, atol=1e-6):
        raise CatalogueError(f"{what} isn't evenly spaced")
    return float(centres[0]) - step / 2, step


def _index_values(array) -> list:
    """The values along the leading axis, read as physrisk's ZarrReader.get_index_values does."""
    dimension = array.attrs.get("dimensions", ["index"])[0]
    return array.attrs.get(f"{dimension}_values") or [0]


def _index_position(layer: GridLayer, array) -> int:
    values = _index_values(array)
    if layer.index is None:
        if array.shape[0] != 1:
            raise CatalogueError(f"{layer.id}: {array.path} has {array.shape[0]} indexes, pick one")
        return 0
    for position, value in enumerate(values):
        if math.isclose(float(value), float(layer.index), abs_tol=1e-9):
            return position
    raise CatalogueError(f"{layer.id}: {array.path} has no index {layer.index} in {values}")


def _grid(layer: GridLayer, path: str, array) -> _Grid:
    if path in _grids:
        return _grids[path]
    if array.ndim != 3:
        raise CatalogueError(f"{layer.id}: {path} has {array.ndim} dimensions, not 3")
    _, rows, cols = array.shape
    if layer.netcdf_coords:
        group = _store_root()[path.rsplit("/", 1)[0]]
        x0, dx = _regular_edges(_axis(group, _COORD_NAMES["lon"]), f"{path} longitudes")
        y0, dy = _regular_edges(_axis(group, _COORD_NAMES["lat"]), f"{path} latitudes")
    else:
        crs = str(array.attrs.get("crs", "epsg:4326")).lower()
        if crs != "epsg:4326":
            raise CatalogueError(f"{layer.id}: {path} isn't in longitude and latitude ({crs})")
        a, b, x0, d, e, y0 = array.attrs["transform_mat3x3"][:6]
        if b or d:
            raise CatalogueError(f"{layer.id}: {path} is rotated")
        dx, dy = a, e
    grid = _Grid(x0, dx, y0, dy, rows, cols, _index_position(layer, array))
    _grids[path] = grid
    return grid


def _asset_cell(grid: _Grid, lon: float, lat: float) -> tuple[int, int, float]:
    """The row and column holding a point, and the longitude shift from the asset to the grid."""
    grid_lon = lon % 360 if grid.zero_to_360 else lon
    if grid.global_columns:
        # Bring the point into the grid's 360 degrees, whatever its own convention.
        while grid_lon < grid.x0:
            grid_lon += 360
        while grid_lon >= grid.x0 + 360:
            grid_lon -= 360
    col = math.floor((grid_lon - grid.x0) / grid.dx)
    row = math.floor((lat - grid.y0) / grid.dy)
    return row, col, grid_lon - lon


def _read_window(layer: GridLayer, scenario: str, year: int | None, lon: float, lat: float):
    path = layer.array_path(scenario, year)
    known = _grids.get(path)
    if known is not None:
        # Assets in the same cell share a window, and a cached one needs no read at all.
        found, cached = _windows.get((path, *_asset_cell(known, lon, lat)[:2]))
        if found:
            return cached
    root = _store_root()
    with _physrisk_lock:
        try:
            array = root[path]
        except KeyError:
            raise CatalogueError(f"{layer.id}: the store has no {path}") from None
        grid = _grid(layer, path, array)
        row, col, shift = _asset_cell(grid, lon, lat)
        key = (path, row, col)
        found, cached = _windows.get(key)
        if found:
            return cached
        half_cols = max(1, round(WINDOW_DEGREES / abs(grid.dx)))
        half_rows = max(1, round(WINDOW_DEGREES / abs(grid.dy)))
        cols = np.arange(col - half_cols, col + half_cols + 1)
        if grid.global_columns:
            read_cols = cols % grid.global_columns
            keep = read_cols < grid.cols
        else:
            read_cols = cols
            keep = (cols >= 0) & (cols < grid.cols)
        rows = np.arange(max(0, row - half_rows), min(grid.rows, row + half_rows + 1))
        if not keep.any() or rows.size == 0:
            raise NoGridData("This dataset doesn't cover this point")
        cols, read_cols = cols[keep], read_cols[keep]
        if not grid.global_columns:
            # Clipped at the grid's edge, the window stays contiguous.
            cols = np.arange(cols[0], cols[-1] + 1)
            read_cols = cols
        values = array.get_orthogonal_selection((grid.index_position, rows, read_cols))
    values = np.asarray(values, dtype=float)
    values[np.isin(values, (_LEGACY_NAN, *layer.nodata_values))] = np.nan
    window = _make_window(grid, rows, cols, values, row, col, lat, shift)
    _windows.put(key, window)
    return window


def _make_window(grid: _Grid, rows, cols, values, row: int, col: int, lat: float, shift: float):
    xs = (grid.x0 + cols[0] * grid.dx - shift, grid.x0 + (cols[-1] + 1) * grid.dx - shift)
    ys = (grid.y0 + rows[0] * grid.dy, grid.y0 + (rows[-1] + 1) * grid.dy)
    if grid.dy > 0:
        values = values[::-1]  # row 0 was the southern edge
    if grid.dx < 0:
        values = values[:, ::-1]
    asset_value = None
    if rows[0] <= row <= rows[-1] and cols[0] <= col <= cols[-1]:
        r = row - rows[0] if grid.dy < 0 else rows[-1] - row
        c = col - cols[0] if grid.dx > 0 else cols[-1] - col
        cell = float(values[r, c])
        asset_value = cell if math.isfinite(cell) else None
    cell_km = (
        abs(grid.dx) * KM_PER_DEGREE_LON * math.cos(math.radians(lat)),
        abs(grid.dy) * KM_PER_DEGREE_LAT,
    )
    bounds = (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)))
    return Window(values, bounds, asset_value, cell_km)


def _layer(layer_id: str) -> GridLayer:
    layer = catalogue().get(layer_id)
    if layer is None:
        raise KeyError(layer_id)
    return layer


def window(layer_id: str, scenario: str, year: int | None, lat: float, lon: float) -> Window:
    """The cells around a point. NoGridData with a reason when there are none, KeyError for an
    unknown layer, and CatalogueError or the store's own error when a read fails."""
    return _read_window(_layer(layer_id), scenario, year, lon, lat)


def view(layer_id: str, scenario: str, year: int | None, lat: float, lon: float) -> GridView:
    """A layer's window for a pair, with a colour scale over both the baseline and the pair, so
    switching between Historical and Future compares on one scale. If only one has data, its own."""
    layer = _layer(layer_id)
    try:
        selected = _read_window(layer, scenario, year, lon, lat)
    except NoGridData as no_data:
        return GridView(layer, None, str(no_data))
    ranges = [selected.value_range()]
    if scenario != HISTORICAL:
        try:
            ranges.append(_read_window(layer, HISTORICAL, None, lon, lat).value_range())
        except NoGridData:
            pass
    found = [r for r in ranges if r is not None]
    if not found:
        return GridView(layer, selected, None)
    return GridView(
        layer, selected, None, min(low for low, _ in found), max(high for _, high in found)
    )


def render(values: np.ndarray, low: float, high: float, theme: str) -> bytes:
    """A PNG with one pixel per cell, coloured on the theme's ramp. NaN is transparent."""
    from PIL import Image

    stops = np.array([_rgb(colour) for colour in ramp(theme)], dtype=float)
    finite = np.isfinite(values)
    span = high - low
    t = np.zeros(values.shape)
    if span > 0:
        t[finite] = np.clip((values[finite] - low) / span, 0, 1)
    position = t * (len(stops) - 1)
    below = np.minimum(np.floor(position).astype(int), len(stops) - 2)
    fraction = (position - below)[..., None]
    rgb = stops[below] * (1 - fraction) + stops[below + 1] * fraction
    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
    rgba[..., :3] = np.rint(rgb).astype(np.uint8)
    rgba[..., 3] = np.where(finite, ALPHA, 0)
    buffer = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buffer, format="PNG")
    return buffer.getvalue()


def image(
    layer_id: str, scenario: str, year: int | None, lat: float, lon: float, theme: str
) -> bytes:
    """The layer's window as a PNG, on the scale view() reports. NoGridData when it has no data."""
    ramp(theme)
    shown = view(layer_id, scenario, year, lat, lon)
    if shown.window is None:
        raise NoGridData(shown.reason or "No data")
    if shown.min_value is None or shown.max_value is None:
        raise NoGridData("No data around this point")
    key = (layer_id, scenario, year, theme, shown.window.bounds, shown.min_value, shown.max_value)
    found, cached = _images.get(key)
    if found and cached is not None:
        return cached
    png = render(shown.window.values, shown.min_value, shown.max_value, theme)
    _images.put(key, png)
    return png
