"""The hail layer against physrisk's real bucket (opt-in: pytest -m s3)."""

import io

import numpy as np
import pytest

from engine import grid_layer, hail_map

pytestmark = pytest.mark.s3


@pytest.fixture(scope="module")
def layer():
    return hail_map.configure()


def value_at(g: grid_layer.Grid, lat: float, lon: float) -> float:
    row = int(np.floor((lat - g.y0) / g.dy))
    col = int(np.floor((lon - g.x0) / g.dx))
    return float(g.values[row, col])


def test_live_array_has_the_expected_layout(layer):
    import zarr

    root = zarr.open(grid_layer.open_bucket(grid_layer.BUCKET_ROOT), mode="r")
    array = root["hail/jupiter/v1/days_above_5cm_ssp585_2050"]
    assert array.shape == (1, 721, 1441)
    assert array.dtype == np.float32
    assert "index_values" not in array.attrs
    g = layer.grid("ssp585", 2050)
    assert g.values.shape == (721, 1441)
    assert (g.x0, g.dx, g.y0, g.dy) == pytest.approx((-180.125, 0.25, 90.125, -0.25))
    assert 0.45 < np.isnan(g.values).mean() < 0.65  # most open ocean, and Antarctica
    finite = g.values[np.isfinite(g.values)]
    assert finite.min() == 0 and finite.max() <= layer.max_value


def test_live_nan_is_open_ocean_not_land_or_seas(layer):
    g = layer.grid("ssp585", 2050)
    land = [(32.78, -96.8), (47.37, 8.54), (-33.87, 151.2), (28.6, 77.2), (23.0, 13.0)]
    assert all(np.isfinite(value_at(g, lat, lon)) for lat, lon in land)
    assert value_at(g, 32.78, -96.8) > 1  # Dallas: more than a potential large-hail day a year
    ocean = [(30.0, -40.0), (0.0, -150.0), (-80.0, 0.0)]  # Atlantic, Pacific, Antarctica
    assert all(np.isnan(value_at(g, lat, lon)) for lat, lon in ocean)
    seas = [(25.0, -90.0), (35.0, 18.0), (15.0, 88.0)]  # Gulf of Mexico, Mediterranean, Bengal
    assert all(np.isfinite(value_at(g, lat, lon)) for lat, lon in seas)


def test_live_2030_is_readable(layer):
    assert layer.grid("ssp585", 2030).values.shape == (721, 1441)


def alpha(png: bytes) -> np.ndarray:
    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))[..., 3]


def test_live_tile_over_texas_is_drawn(layer):
    png = layer.tile("ssp585", 2050, 4, 3, 6)  # Texas, northern Mexico and the western Gulf
    assert png is not None
    assert (alpha(png) == 200).mean() > 0.9  # the Gulf has values too


def test_live_tile_over_the_south_pacific_is_mostly_clear(layer):
    png = layer.tile("ssp585", 2050, 4, 2, 10)  # 135 to 112.5 W, about 41 to 56 S
    assert png is None or (alpha(png) == 0).mean() > 0.5
