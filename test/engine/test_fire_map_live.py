"""The wildfire layer against physrisk's real bucket (opt-in: pytest -m s3)."""

import io

import numpy as np
import pytest

from engine import fire_map

pytestmark = pytest.mark.s3


@pytest.fixture(autouse=True)
def bucket():
    fire_map.use_store(None)
    yield
    fire_map.clear_caches()


def test_live_array_has_the_expected_layout():
    grid = fire_map.grid("ssp585", 2050)
    assert grid.values.shape == (721, 1441)
    assert (grid.x0, grid.dx, grid.y0, grid.dy) == (-180.125, 0.25, 90.125, -0.25)
    finite = grid.values[np.isfinite(grid.values)]
    assert 0.5 < np.isnan(grid.values).mean() < 0.9  # ocean and no data
    assert finite.min() == 0.0  # real zeros, apart from NaN
    assert finite.max() <= fire_map.coverage().max_value


def test_live_tile_over_the_western_us_has_land_and_sea():
    from PIL import Image

    png = fire_map.tile("ssp585", 2050, 4, 2, 6)  # California and the Pacific
    assert png is not None
    alpha = np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))[..., 3]
    assert alpha.shape == (512, 512)
    assert (alpha == fire_map.ALPHA).mean() > 0.2
    assert (alpha == 0).mean() > 0.2
