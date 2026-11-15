"""The drought layer, read from an in-memory zarr group shaped as OS-Climate's: no network."""

import io
import threading

import numpy as np
import pytest

from engine import drought_map, grid_layer, hazard_maps
from engine.assess import _physrisk_lock
from engine.grid_layer import GridSettings, HazardMapConfigError

GROUP = "drought/osc/v2/months_spei12m_below_threshold_multi_model_0_ssp585_2050"
HISTORICAL_GROUP = "drought/osc/v2/months_spei12m_below_threshold_multi_model_0_historical_2005"
THRESHOLDS = [0.0, -1.0, -1.5, -2.0, -2.5, -3.0, -3.6]
# 30 degree cells from 90 N to 60 S and -180 to 180, as the real 0.25 degree grid is laid out.
DX = 30.0
TRANSFORM = [DX, 0.0, -180.0, 0.0, -DX, 90.0, 0.0, 0.0, 1.0]
ROWS, COLS = 5, 12


def cells(threshold: float) -> np.ndarray:
    """Months below a threshold: fewer the lower it is, with open water stored as 0."""
    values = np.linspace(0.5, 12, ROWS * COLS).reshape(ROWS, COLS) * (1 + threshold / 4)
    values[2, 5] = 0.0  # open water at (15 N to 15 S, 30 W to 0)
    values[:, 0] = 0.0  # a whole column of ocean
    return values


def spei_store(attrs=None, name=GROUP, values=None):
    """The real layout: a group holding a float64 (threshold, lat, lon) indicator and its coords."""
    import zarr

    store = zarr.MemoryStore()
    group = zarr.open_group(store, mode="a").create_group(name)
    data = np.stack([cells(t) for t in THRESHOLDS]) if values is None else values
    indicator = group.create_dataset(
        "indicator", shape=data.shape, dtype="float64", chunks=(len(THRESHOLDS), 3, 5)
    )
    indicator[:] = data
    indicator.attrs.update(
        {
            "crs": "EPSG:4326",
            "dimensions": ["threshold", "latitude", "longitude"],
            "threshold_values": THRESHOLDS,
            "transform_mat3x3": TRANSFORM,
        }
        | (attrs or {})
    )
    group.create_dataset("threshold", data=np.array(THRESHOLDS))
    group.create_dataset("latitude", data=90 - DX * (np.arange(ROWS) + 0.5))
    group.create_dataset("longitude", data=-180 + DX * (np.arange(COLS) + 0.5))
    return store


@pytest.fixture
def layer():
    layer = drought_map.configure()
    layer.use_store(spei_store())
    return layer


def pixels(png: bytes) -> np.ndarray:
    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))


# --- physrisk's inventory and models -------------------------------------------------------------


def test_physrisks_drought_model_reads_multi_model_0():
    """Fails when a physrisk bump changes which drought data its model uses."""
    from physrisk.hazard_models.core_hazards import get_default_source_paths
    from physrisk.kernel.hazards import Drought

    resources = get_default_source_paths().get_resources(
        hazard_type=Drought, indicator_id="months/spei12m/below/threshold"
    )
    assert [r.path.replace("{gcm}", drought_map.GCM) for r in resources] == [
        drought_map.DROUGHT_PATH
    ]
    assert [r.indicator_model_gcm for r in resources] == [drought_map.GCM]


def test_physrisk_models_no_drought_loss_for_buildings():
    """The note says so: only manufacturing disruption has a drought curve."""
    from physrisk.vulnerability_models.vulnerability import VulnerabilityModelsFactory

    curves = [
        item
        for item in VulnerabilityModelsFactory.embedded_vulnerability_config()
        if item.hazard_class == "Drought"
    ]
    assert [(c.asset_class, c.impact_id, c.curve_type) for c in curves] == [
        ("ManufacturingAsset", "disruption", "threshold/piecewise_linear")
    ]
    assert list(curves[0].points_x) == [-3.5, -3.0, -2.5, -2.0]  # starts at the mapped threshold
    assert list(curves[0].points_y)[-1] == 0.0


def test_physrisk_does_not_rescale_drought():
    from physrisk.vulnerability_models.config_based_vuln_model_param import (
        ConfigBasedVulnerabilityModelParam,
    )

    values = np.array([1.0, 6.0])
    adjust = ConfigBasedVulnerabilityModelParam._adjust_indicator_values
    np.testing.assert_array_equal(adjust(None, GROUP, values), values)


def test_physrisks_inventory_has_the_osc_drought_resource():
    cover = drought_map.configure().coverage()
    years = (2030, 2040, 2050, 2080)
    assert cover.scenarios == {
        "historical": (2005,),
        "ssp126": years,
        "ssp245": years,
        "ssp585": years,
    }
    assert (cover.units, cover.max_value) == ("months/year", 12.0)
    assert (cover.licence, cover.attribution) == ("not stated", "")
    assert cover.netcdf_coords is True


def test_a_gcm_the_inventory_doesnt_list_fails_loudly():
    path = drought_map.DROUGHT_PATH.replace(drought_map.GCM, "NOT-A-GCM")
    with pytest.raises(HazardMapConfigError, match="no"):
        grid_layer.read_coverage(
            grid_layer.physrisk_inventory(), path, "Drought", {"gcm": "NOT-A-GCM"}
        )
    with pytest.raises(HazardMapConfigError, match="no gcm NOT-A-GCM"):
        grid_layer.read_coverage(
            [
                {
                    "path": "d/{gcm}_{scenario}_{year}",
                    "hazard_type": "Drought",
                    "params": {"gcm": ["multi_model_0"]},
                }
            ],
            "d/NOT-A-GCM_{scenario}_{year}",
            "Drought",
            {"gcm": "NOT-A-GCM"},
        )


@pytest.mark.parametrize(
    ("scenario", "year", "reason"),
    [
        ("historical", None, None),
        ("ssp245", 2030, None),
        ("ssp245", 2050, None),
        ("ssp245", 2080, None),
        ("ssp585", 2030, None),
        ("ssp585", 2050, None),
        ("ssp585", 2080, None),
        ("ssp370", 2050, "physrisk's drought data covers ssp126, ssp245 and ssp585 only"),
        (
            "ssp585",
            2025,
            "physrisk's drought data for ssp585 has 2030, 2040, 2050 and 2080 only. physrisk "
            "estimates the other years from the years either side",
        ),
    ],
)
def test_every_default_pair_has_a_map(scenario, year, reason):
    assert drought_map.configure().reason(scenario, year) == reason


# --- The array's layout --------------------------------------------------------------------------


def test_the_minus_2_threshold_is_read_from_the_groups_indicator(layer):
    g = layer.grid("ssp585", 2050)
    assert g.values.dtype == np.float32 and g.values.shape == (ROWS, COLS)
    assert (g.x0, g.dx, g.y0, g.dy) == pytest.approx((-180.0, DX, 90.0, -DX))
    expected = cells(drought_map.THRESHOLD).astype(np.float32)
    expected[expected == 0] = np.nan
    np.testing.assert_array_equal(g.values, expected)


def test_the_baseline_reads_2005():
    layer = drought_map.configure()
    layer.use_store(spei_store(name=HISTORICAL_GROUP))
    assert layer.tile("historical", None, 0, 0, 0).startswith(b"\x89PNG")


@pytest.mark.parametrize(
    ("attrs", "message"),
    [
        ({"threshold_values": [0.0, -1.0, -1.5, -2.5, -3.0, -3.5, -4.0]}, "no threshold_values -2"),
        ({"threshold_values": [0.0, -2.0]}, "expected 7 threshold_values"),
        ({"threshold_values": None}, "expected 7 threshold_values"),
        ({"crs": "EPSG:3857"}, "not EPSG:3857"),
    ],
)
def test_an_unexpected_layout_fails_loudly(attrs, message):
    layer = drought_map.configure()
    layer.use_store(spei_store(attrs=attrs))
    with pytest.raises(HazardMapConfigError, match=message):
        layer.grid("ssp585", 2050)


# --- Tiles ---------------------------------------------------------------------------------------


def test_open_water_is_clear_and_land_is_on_the_ramp(layer):
    g = layer.grid("ssp585", 2050)
    values = grid_layer.sample(g, 0, 0, 0)
    alpha = pixels(layer.tile("ssp585", 2050, 0, 0, 0))[..., 3]
    assert np.isnan(values).any()
    assert (alpha[np.isnan(values)] == 0).all()
    assert (alpha[np.isfinite(values)] == 200).all()


def test_a_tile_of_open_water_is_none():
    layer = drought_map.configure()
    layer.use_store(spei_store(values=np.zeros((len(THRESHOLDS), ROWS, COLS))))
    assert layer.tile("ssp585", 2050, 0, 0, 0) is None


def test_no_map_is_none_without_reading(layer, monkeypatch):
    monkeypatch.setattr(layer, "_load", lambda *a: pytest.fail("read"))
    assert layer.tile("ssp370", 2050, 0, 0, 0) is None
    assert layer.tile("ssp585", 2050, drought_map.MAX_ZOOM + 1, 0, 0) is None


def test_tiles_are_drawn_without_physrisks_lock(layer):
    done = threading.Event()
    with _physrisk_lock:
        thread = threading.Thread(target=lambda: (layer.tile("ssp585", 2050, 0, 0, 0), done.set()))
        thread.start()
        assert done.wait(10)
    thread.join()


def test_settings_reach_the_layer():
    settings = GridSettings(alpha=120, legend_stops=3, array_cache=1, tile_cache=1)
    layer = drought_map.configure(max_zoom=4, settings=settings)
    layer.use_store(spei_store())
    assert layer.max_zoom == 4
    assert len(layer.legend()) == 3 and layer.legend()[0].endswith(", 0.47)")
    assert set(np.unique(pixels(layer.tile("ssp585", 2050, 0, 0, 0))[..., 3])) == {0, 120}


# --- Colours -------------------------------------------------------------------------------------


def test_the_ramp_is_one_red_hue_with_lightness_falling():
    lab = np.array(
        [grid_layer._linear_to_oklab(grid_layer._hex_to_linear(c)) for c in drought_map.RAMP]
    )
    assert (np.diff(lab[:, 0]) <= -0.06).all()
    hues = np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % 360
    assert np.ptp(hues) < 2 and abs(hues.mean() - 25) < 2


def test_the_ramp_stops_are_drawn_exactly():
    table = drought_map.configure().colour_table()
    for i, colour in enumerate(drought_map.RAMP):
        assert table[i * 64, :3].tolist() == [int(colour[k : k + 2], 16) for k in (1, 3, 5)]


# --- As a hazard map layer -----------------------------------------------------------------------


def test_drought_is_a_hazard_map_layer():
    layer = hazard_maps.LAYERS["Drought"]
    assert (layer.units, layer.return_period, layer.min_value, layer.max_value) == (
        "months/year",
        None,
        0.0,
        12.0,
    )
    assert layer.max_zoom == drought_map.MAX_ZOOM == 6
    assert "SPEI below −2" in layer.measure
    assert "Open water" in layer.no_data_label
    for text in (
        "20-year mean",
        "multi_model_0",
        "no drought loss for these buildings",
        "2005",
        "25 km",
        "the region, not the property",
        "not proof of low risk",
    ):
        assert text in layer.note
    assert layer.source == (
        "Source: OS-Climate physrisk's drought indicators. physrisk lists no licence for them."
    )
    assert len(layer.legend()) == 9
