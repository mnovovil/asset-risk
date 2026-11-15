"""The drought layer against physrisk's real bucket (opt-in: pytest -m s3)."""

import io

import numpy as np
import pytest

from engine import drought_map, grid_layer

pytestmark = pytest.mark.s3


@pytest.fixture(scope="module")
def layer():
    return drought_map.configure()


def value_at(g: grid_layer.Grid, lat: float, lon: float) -> float:
    row = int(np.floor((lat - g.y0) / g.dy))
    col = int(np.floor((lon - g.x0) / g.dx))
    return float(g.values[row, col])


def test_live_group_has_the_expected_layout():
    import zarr

    root = zarr.open(grid_layer.open_bucket(grid_layer.BUCKET_ROOT), mode="r")
    group = root["drought/osc/v2/months_spei12m_below_threshold_multi_model_0_ssp585_2050"]
    assert {"indicator", "latitude", "longitude", "threshold"} <= set(group.keys())
    indicator = group["indicator"]
    assert indicator.shape == (7, 600, 1440)
    assert indicator.dtype == np.float64
    assert drought_map.THRESHOLD in indicator.attrs["threshold_values"]
    assert "index_values" not in indicator.attrs


def test_live_open_water_is_clear_and_land_has_values(layer):
    g = layer.grid("ssp585", 2050)
    assert g.values.shape == (600, 1440)
    assert (g.x0, g.dx, g.y0, g.dy) == pytest.approx((-180.0, 0.25, 90.0, -0.25))
    land = [(23.0, 13.0), (40.4, -3.7), (32.8, -96.8), (-3.0, -60.0)]  # Sahara, Madrid, Dallas
    assert all(value_at(g, lat, lon) > 0 for lat, lon in land)
    assert value_at(g, 23.0, 13.0) > 6  # the Sahara: most of the year
    water = [(30.0, -40.0), (0.0, -150.0), (25.0, -90.0), (35.0, 18.0)]
    assert all(np.isnan(value_at(g, lat, lon)) for lat, lon in water)
    finite = g.values[np.isfinite(g.values)]
    assert finite.min() > 0 and finite.max() <= layer.max_value


def test_live_baseline_reads_2005_and_is_milder(layer):
    baseline = layer.grid("historical", 2005).values
    future = layer.grid("ssp585", 2050).values
    assert baseline.shape == (600, 1440)
    assert np.nanpercentile(baseline, 99) < np.nanpercentile(future, 99)


def test_live_tile_over_iberia_and_north_africa(layer):
    from PIL import Image

    png = layer.tile("ssp585", 2050, 3, 3, 3)  # Iberia, West Africa, the Sahara and the Atlantic
    assert png is not None
    alpha = np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))[..., 3]
    assert (alpha == 200).mean() > 0.2
    assert (alpha == 0).mean() > 0.2  # the Atlantic
