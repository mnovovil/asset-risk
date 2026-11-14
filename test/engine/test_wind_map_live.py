"""The wind layer against physrisk's real bucket (opt-in: pytest -m s3)."""

import io

import numpy as np
import pytest

from engine import grid_layer, wind_map

pytestmark = pytest.mark.s3


@pytest.fixture(scope="module")
def layer():
    return wind_map.configure()


def test_live_array_has_the_expected_layout(layer):
    import zarr

    root = zarr.open(grid_layer.open_bucket(grid_layer.BUCKET_ROOT), mode="r")
    array = root["wind/iris/v1/max_speed_ssp585_2050"]
    assert array.shape == (19, 1200, 3600)
    assert wind_map.RETURN_PERIOD in array.attrs["index_values"]
    g = layer.grid("ssp585", 2050)
    assert g.values.shape == (1200, 3600)
    assert (g.x0, g.dx, g.y0, g.dy) == pytest.approx((-180.0, 0.1, 60.0, -0.1))
    assert 0.5 < np.isnan(g.values).mean() < 0.8  # no tropical cyclone
    finite = g.values[np.isfinite(g.values)]
    assert 0 < finite.min() and finite.max() <= layer.max_value


def test_live_historical_baseline_is_readable(layer):
    assert layer.grid("historical", 2010).values.shape == (1200, 3600)


def test_live_tile_over_the_gulf_of_mexico_has_wind_and_clear_cells(layer):
    from PIL import Image

    png = layer.tile("ssp585", 2050, 4, 3, 6)  # Texas, northern Mexico and the western Gulf
    assert png is not None
    alpha = np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))[..., 3]
    assert (alpha == 200).mean() > 0.2
    assert (alpha == 0).mean() > 0.05
