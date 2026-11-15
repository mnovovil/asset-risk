"""The large hail layer, read from an in-memory zarr store shaped as Jupiter's: no network."""

import io
import threading

import numpy as np
import pytest

from engine import grid_layer, hail_map, hazard_maps
from engine.assess import _physrisk_lock
from engine.grid_layer import GridSettings, HazardMapConfigError

PATH = "hail/jupiter/v1/days_above_5cm_ssp585_2050"
# 30 degree cells, laid out as Jupiter's 0.25 degree grid: centred on whole degrees, so the first
# and last columns both sit on 180 degrees, and the rows run from 90 N to 90 S.
DX = 30.0
TRANSFORM = [DX, 0.0, -180.0 - DX / 2, 0.0, -DX, 90.0 + DX / 2, 0.0, 0.0, 1.0]
ROWS, COLS = 7, 13


def cells() -> np.ndarray:
    values = np.linspace(0, 4, ROWS * COLS, dtype=np.float32).reshape(ROWS, COLS)
    values[3, 6] = np.nan  # ocean at (0, 0) degrees
    values[-1, :] = np.nan  # Antarctica
    values[2, 2] = 0.0  # no hail days is a value, not no data
    return values


def jupiter_store(attrs=None, name=PATH, values=None):
    """Jupiter's layout: (1, rows, cols) with no index_values."""
    import zarr

    store = zarr.MemoryStore()
    root = zarr.open_group(store, mode="a")
    data = cells()[None] if values is None else values
    array = root.create_dataset(name, shape=data.shape, dtype="float32", chunks=(1, 4, 4))
    array[:] = data
    array.attrs.update({"crs": "EPSG:4326", "transform_mat3x3": TRANSFORM} | (attrs or {}))
    return store


@pytest.fixture
def layer():
    layer = hail_map.configure()
    layer.use_store(jupiter_store())
    return layer


def pixels(png: bytes) -> np.ndarray:
    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))


# --- physrisk's inventory ------------------------------------------------------------------------


def test_physrisks_hail_damage_reads_this_array():
    """Fails when a physrisk bump changes which hail data the losses use."""
    from physrisk.hazard_models.core_hazards import get_default_source_paths
    from physrisk.kernel.hazards import Hail

    sources = get_default_source_paths()
    resources = sources.get_resources(hazard_type=Hail, indicator_id="days/above/5cm")
    assert [r.path for r in resources] == [hail_map.HAIL_PATH]


def test_physrisks_hail_baseline_is_its_ssp126_2020_data():
    """The note says where the baseline losses come from: check it still holds."""
    from physrisk.hazard_models.core_hazards import get_default_source_paths
    from physrisk.kernel.hazards import Hail

    sources = get_default_source_paths()
    [paths] = sources.resource_paths(Hail, "days/above/5cm", ["historical", "ssp245"])
    assert paths.scenarios["historical"].path(-1) == hail_map.HAIL_PATH.format(
        scenario="ssp126", year=2020
    )
    assert paths.scenarios["ssp245"].years == []


def test_physrisk_does_not_rescale_hail_but_counts_1_in_50_days():
    from physrisk.vulnerability_models.config_based_vuln_model_param import (
        ConfigBasedVulnerabilityModelParam,
    )
    from physrisk.vulnerability_models.vulnerability import VulnerabilityModelsFactory

    values = np.array([0.5, 2.0])
    adjust = ConfigBasedVulnerabilityModelParam._adjust_indicator_values
    np.testing.assert_array_equal(adjust(None, PATH, values), values)
    [generic] = [
        item
        for item in VulnerabilityModelsFactory.embedded_vulnerability_config()
        if item.hazard_class == "Hail" and item.asset_class == "Asset"
    ]
    assert generic.curve_type == "occurrence_probability"
    assert list(generic.points_x) == [pytest.approx(1 / 50)]
    assert list(generic.points_y) == [pytest.approx(0.001)]  # 0.1% damage on a hail day


def test_physrisk_estimates_2080_from_the_years_either_side():
    from physrisk.data.hazard_data_provider import CascadingHazardDataProvider

    years = hail_map.configure().coverage().scenarios["ssp585"]
    weights = CascadingHazardDataProvider._weights("ssp585", years, [2080], 2025)
    [blend] = weights.values()
    assert [(s.year, round(w, 6)) for s, w in blend.weights] == [(2075, 0.8), (2100, 0.2)]


def test_physrisks_inventory_has_the_jupiter_hail_resource():
    cover = hail_map.configure().coverage()
    years = (2020, 2030, 2040, 2050, 2075, 2100)
    assert cover.scenarios == {"ssp126": years, "ssp585": years}
    assert cover.units == "days/year"
    assert cover.max_value == 4.0
    assert cover.licence == "Commercial"
    assert cover.attribution == ""


OTHER_YEARS = (
    "physrisk's hail data for ssp585 has 2020, 2030, 2040, 2050, 2075 and 2100 only. physrisk "
    "estimates the other years' losses from the years either side"
)


@pytest.mark.parametrize(
    ("scenario", "year", "reason"),
    [
        ("ssp585", 2030, None),
        ("ssp585", 2050, None),
        ("ssp126", 2100, None),
        ("historical", None, "physrisk's hail data has no historical baseline"),
        ("ssp245", 2050, "physrisk's hail data covers ssp126 and ssp585 only"),
        ("ssp370", 2050, "physrisk's hail data covers ssp126 and ssp585 only"),
        ("ssp585", 2080, OTHER_YEARS),
    ],
)
def test_only_an_exact_inventory_match_has_a_map(scenario, year, reason):
    assert hail_map.configure().reason(scenario, year) == reason


# --- The array's layout --------------------------------------------------------------------------


def test_the_single_layer_is_read(layer):
    g = layer.grid("ssp585", 2050)
    assert g.values.shape == (ROWS, COLS)
    assert (g.x0, g.dx, g.y0, g.dy) == pytest.approx((-195.0, DX, 105.0, -DX))
    np.testing.assert_array_equal(g.values, cells())


@pytest.mark.parametrize(
    ("attrs", "message"),
    [
        ({"crs": "EPSG:3857"}, "not EPSG:3857"),
        ({"transform_mat3x3": [DX, 1.0, -195.0, 0.0, -DX, 105.0, 0, 0, 1]}, "no rotation"),
        ({"transform_mat3x3": None}, "no transform_mat3x3"),
    ],
)
def test_an_unexpected_layout_fails_loudly(attrs, message):
    layer = hail_map.configure()
    layer.use_store(jupiter_store(attrs=attrs))
    with pytest.raises(HazardMapConfigError, match=message):
        layer.grid("ssp585", 2050)


def test_a_stack_fails_loudly():
    layer = hail_map.configure()
    layer.use_store(jupiter_store(values=np.zeros((2, ROWS, COLS), "f4")))
    with pytest.raises(HazardMapConfigError, match="expected a \\(1, rows, cols\\) array"):
        layer.grid("ssp585", 2050)


# --- Tiles ---------------------------------------------------------------------------------------


def test_ocean_is_clear_and_zero_is_on_the_ramp(layer):
    g = layer.grid("ssp585", 2050)
    values = grid_layer.sample(g, 0, 0, 0)
    image = pixels(layer.tile("ssp585", 2050, 0, 0, 0))
    alpha = image[..., 3]
    assert (alpha[np.isnan(values)] == 0).all()
    assert (alpha[np.isfinite(values)] == 200).all()
    zero = values == 0
    assert zero.any()
    first = [int(hail_map.RAMP[0][k : k + 2], 16) for k in (1, 3, 5)]
    assert (image[zero][:, :3] == first).all()


def test_a_tile_with_no_data_is_none():
    layer = hail_map.configure()
    layer.use_store(jupiter_store(values=np.full((1, ROWS, COLS), np.nan, "f4")))
    assert layer.tile("ssp585", 2050, 0, 0, 0) is None


def test_no_map_is_none_without_reading(layer, monkeypatch):
    monkeypatch.setattr(layer, "_load", lambda *a: pytest.fail("read"))
    assert layer.tile("historical", None, 0, 0, 0) is None
    assert layer.tile("ssp245", 2050, 0, 0, 0) is None
    assert layer.tile("ssp585", 2080, 0, 0, 0) is None
    assert layer.tile("ssp585", 2050, hail_map.MAX_ZOOM + 1, 0, 0) is None


def test_tiles_are_drawn_without_physrisks_lock(layer):
    done = threading.Event()
    with _physrisk_lock:
        thread = threading.Thread(target=lambda: (layer.tile("ssp585", 2050, 0, 0, 0), done.set()))
        thread.start()
        assert done.wait(10)
    thread.join()


def test_settings_reach_the_layer():
    settings = GridSettings(alpha=120, legend_stops=3, array_cache=1, tile_cache=1)
    layer = hail_map.configure(max_zoom=4, settings=settings)
    layer.use_store(jupiter_store())
    assert layer.max_zoom == 4
    assert len(layer.legend()) == 3 and layer.legend()[0].endswith(", 0.47)")
    assert set(np.unique(pixels(layer.tile("ssp585", 2050, 0, 0, 0))[..., 3])) == {0, 120}


# --- Colours -------------------------------------------------------------------------------------


def test_the_ramp_is_one_pink_hue_with_lightness_falling():
    lab = np.array(
        [grid_layer._linear_to_oklab(grid_layer._hex_to_linear(c)) for c in hail_map.RAMP]
    )
    assert (np.diff(lab[:, 0]) <= -0.06).all()
    hues = np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % 360
    assert np.ptp(hues) < 2 and abs(hues.mean() - 357) < 2


def test_the_ramp_stops_are_drawn_exactly():
    table = hail_map.configure().colour_table()
    for i, colour in enumerate(hail_map.RAMP):
        assert table[i * 64, :3].tolist() == [int(colour[k : k + 2], 16) for k in (1, 3, 5)]


# --- As a hazard map layer -----------------------------------------------------------------------


def test_hail_is_a_hazard_map_layer():
    layer = hazard_maps.LAYERS["Hail"]
    assert (layer.units, layer.return_period, layer.min_value, layer.max_value) == (
        "days/year",
        None,
        0.0,
        4.0,
    )
    assert layer.max_zoom == hail_map.MAX_ZOOM == 6
    assert "5 cm" in layer.measure
    assert "ocean" in layer.no_data_label
    for text in (
        "1 in 50",
        "ssp126 2020",
        "25 km",
        "the region, not the property",
        "not proof of low risk",
    ):
        assert text in layer.note
    assert "Jupiter Intelligence" in layer.source and "OS-Climate physrisk" in layer.source
    assert '"Commercial"' in layer.source
    assert len(layer.legend()) == 9
