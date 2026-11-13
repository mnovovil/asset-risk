import copy
import io
import json
import math

import numpy as np
import pytest
import zarr
from PIL import Image

from engine import hazard_grids
from engine.assess import _physrisk_lock
from engine.hazard_grids import CatalogueError, NoGridData

IRIS = "wind/iris/v1/max_speed_{scenario}_{year}"
DROUGHT = "drought/osc/v2/months_spei12m_below_threshold_multi_model_0_{scenario}_{year}"
HEAT_0_360 = "chronic_heat/jupiter/v1/days_above_35c_ssp585_2050"
FIRE_GLOBAL = "fire/jupiter/v1/fire_probability_ssp585_2050"
STRESS = "water_risk/wri/v2/water_stress_{scenario}_{year}"
# Inside the regional fixture grids: row 9 and column 11 of the 0.5 degree cells.
LAT, LON = 40.2, -74.3


class RecordingStore(zarr.DirectoryStore):
    """A local store that records each chunk read, and whether physrisk's lock was held."""

    def __init__(self, path):
        super().__init__(path)
        self.reads: list[tuple[str, bool]] = []

    def __getitem__(self, key):
        if not key.endswith((".zarray", ".zattrs", ".zgroup")):
            self.reads.append((key, _physrisk_lock.locked()))
        return super().__getitem__(key)


def _regional(index_values, offset=0.0, dims=True):
    """20 x 20 cells of 0.5 degrees from (-80, 45), north row first: index*1000 + row*20 + col."""
    index = np.arange(len(index_values))[:, None, None]
    rows = np.arange(20)[None, :, None]
    cols = np.arange(20)[None, None, :]
    return (index * 1000 + rows * 20 + cols + offset).astype("float32")


def _array(root, path, data, transform, attrs=None, chunk=8):
    array = root.create_dataset(path, data=data, chunks=(data.shape[0], chunk, chunk))
    array.attrs.update(
        {"crs": "EPSG:4326", "transform_mat3x3": [*transform, 0, 0, 1], **(attrs or {})}
    )
    return array


REGIONAL = [0.5, 0.0, -80.0, 0.0, -0.5, 45.0]
IRIS_ATTRS = {"dimensions": ["index", "latitude", "longitude"], "index_values": [10, 100, 1000]}


@pytest.fixture
def store(tmp_path):
    store = RecordingStore(str(tmp_path / "hazard.zarr"))
    root = zarr.group(store=store)
    _array(
        root,
        IRIS.format(scenario="historical", year=2010),
        _regional([10, 100, 1000]),
        REGIONAL,
        IRIS_ATTRS,
    )
    future = _regional([10, 100, 1000], offset=500)
    future[1, 0, 0] = np.nan
    future[1, 0, 1] = -9999.0
    _array(root, IRIS.format(scenario="ssp245", year=2050), future, REGIONAL, IRIS_ATTRS)

    # netCDF-style: latitudes run south to north, and the cells come from the coordinates.
    for scenario, year in (("historical", 2005), ("ssp245", 2050)):
        group = root.create_group(DROUGHT.format(scenario=scenario, year=year))
        thresholds = [0.0, -1.0, -2.0]
        data = _regional(thresholds)
        indicator = group.create_dataset("indicator", data=data, chunks=(3, 8, 8))
        indicator.attrs.update(
            {"dimensions": ["threshold", "latitude", "longitude"], "threshold_values": thresholds}
        )
        group.create_dataset("latitude", data=35.25 + 0.5 * np.arange(20))
        group.create_dataset("longitude", data=-79.75 + 0.5 * np.arange(20))

    # Global grids of 1 degree, valued by their column: one stored 0-360, one -180 to 180.
    columns = np.tile(np.arange(360, dtype="float32"), (180, 1))[None]
    _array(root, HEAT_0_360, columns, [1.0, 0.0, 0.0, 0.0, -1.0, 90.0], chunk=90)
    _array(root, FIRE_GLOBAL, columns, [1.0, 0.0, -180.0, 0.0, -1.0, 90.0], chunk=90)

    stress = _regional([0])
    stress[0, 9, 11] = 9999.0
    for scenario, year in (("historical", 1999), ("ssp585", 2050)):
        _array(root, STRESS.format(scenario=scenario, year=year), stress, REGIONAL)

    hazard_grids.use_store(store)
    store.reads.clear()
    yield store
    hazard_grids.use_store(None)


# Catalogue ---------------------------------------------------------------------------------------


def test_every_non_flood_resource_is_catalogued_or_excluded():
    data = hazard_grids._data()
    catalogued = {layer.path for layer in hazard_grids.catalogue().values()}
    for resource in hazard_grids.physrisk_inventory():
        path = resource["path"]
        assert (path in catalogued) != bool(hazard_grids.excluded_reason(path, data)), path


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("wind/wisc/v1/max_speed_{scenario}_{year}/max_speed", "Europe only"),
        ("fire/ECB_fire_risk_indicators/v1_1/{scenario}_{year}", "Europe only"),
        ("water_risk/wri/v2/water_stress_category_{scenario}_{year}", "Categorical"),
        ("inundation/wri/v2/inunriver_{scenario}_MIROC-ESM-CHEM_{year}", "Flood"),
        ("combined_flood/jupiter/v1/fraction_{scenario}_{year}", "Flood"),
    ],
)
def test_layers_that_would_mislead_are_excluded(path, reason):
    assert hazard_grids.excluded_reason(path).startswith(reason)


def test_only_the_resources_physrisk_assesses_feed_damage():
    feeding = {layer.id for layer in hazard_grids.catalogue().values() if layer.feeds_damage}
    assert feeding == {
        "fire_jupiter_probability",
        "hail_jupiter_days_above_5cm",
        "wind_iris_max_speed",
    }


def test_scenarios_and_years_come_from_the_inventory():
    layers = hazard_grids.catalogue()
    assert layers["wind_iris_max_speed"].scenarios == {
        "historical": (2010,),
        "ssp119": (2050,),
        "ssp245": (2050,),
        "ssp585": (2050,),
    }
    assert "historical" not in layers["fire_jupiter_probability"].scenarios
    assert layers["heat_osc_days_wbgt_above"].scenarios["ssp370"][-1] == 2090


def test_params_fill_the_path_and_netcdf_groups_read_the_indicator():
    layers = hazard_grids.catalogue()
    assert (
        layers["heat_osc_days_tas_above_30c"].array_path("ssp585", 2050)
        == "chronic_heat/osc/v2/days_tas_above_30c_ACCESS-CM2_ssp585_2050"
    )
    assert layers["drought_osc_months_spei12m"].array_path("historical", None) == (
        DROUGHT.format(scenario="historical", year=2005) + "/indicator"
    )


def _broken(change):
    data = copy.deepcopy(hazard_grids._data())
    inventory = copy.deepcopy(hazard_grids.physrisk_inventory())
    change(data, inventory)
    return data, inventory


def _layer_entry(data, layer_id):
    return next(entry for entry in data["layers"] if entry["id"] == layer_id)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d, i: i.remove(next(r for r in i if r["path"] == IRIS)), "has no wind/iris"),
        (
            lambda d, i: _layer_entry(d, "heat_osc_days_wbgt_above")["params"].update(gcm="GONE"),
            "no gcm=GONE",
        ),
        (
            lambda d, i: _layer_entry(d, "heat_osc_days_tas_above_30c")["params"].pop("temp_c"),
            "don't match",
        ),
        (lambda d, i: d["excluded"].append({"path": IRIS, "reason": "x"}), "also excluded"),
        (lambda d, i: d["layers"].append(d["layers"][0]), "listed twice"),
        (
            lambda d, i: _layer_entry(d, "wind_iris_max_speed").update(hazard="Fire"),
            "another hazard",
        ),
    ],
)
def test_a_catalogue_that_no_longer_matches_physrisk_raises(change, message):
    with pytest.raises(CatalogueError, match=message):
        hazard_grids.build_catalogue(*_broken(change))


@pytest.mark.parametrize(
    ("layer_id", "scenario", "year", "reason"),
    [
        ("fire_jupiter_probability", "historical", None, "no historical baseline"),
        ("wind_iris_max_speed", "ssp126", 2050, "no ssp126 scenario"),
        ("wind_iris_max_speed", "ssp245", 2080, "no 2080 for ssp245: it has 2050"),
        ("heat_nluu_weeks_water_temp_above", "ssp585", 2050, "no ssp585 scenario"),
    ],
)
def test_a_missing_pair_has_a_reason_and_no_other_year_is_read(
    store, layer_id, scenario, year, reason
):
    with pytest.raises(NoGridData, match=reason):
        hazard_grids.window(layer_id, scenario, year, LAT, LON)
    shown = hazard_grids.view(layer_id, scenario, year, LAT, LON)
    assert shown.window is None and reason in shown.reason
    assert store.reads == []


def test_an_unknown_layer_is_a_key_error():
    with pytest.raises(KeyError):
        hazard_grids.window("nope", "historical", None, LAT, LON)


# Windows -----------------------------------------------------------------------------------------


def test_a_window_spans_a_degree_each_way_on_cell_edges(store):
    window = hazard_grids.window("wind_iris_max_speed", "historical", None, LAT, LON)
    assert window.bounds == (-75.5, 39.0, -73.0, 41.5)
    assert window.values.shape == (5, 5)
    # North-west corner first, on the 100-year index (the second).
    assert window.values[0, 0] == 1000 + 7 * 20 + 9
    assert window.asset_value == 1000 + 9 * 20 + 11
    assert window.cell_km == pytest.approx(
        (0.5 * 111.32 * math.cos(math.radians(LAT)), 0.5 * 110.574)
    )


def test_a_window_is_clipped_at_the_edge_of_a_regional_grid(store):
    window = hazard_grids.window("wind_iris_max_speed", "historical", None, 44.9, -79.9)
    assert window.bounds == (-80.0, 43.5, -78.5, 45.0)
    assert window.values.shape == (3, 3)
    assert window.asset_value == 1000


def test_a_point_off_the_grid_has_no_data(store):
    with pytest.raises(NoGridData, match="doesn't cover this point"):
        hazard_grids.window("wind_iris_max_speed", "historical", None, 60.0, LON)


def test_nan_and_legacy_nan_cells_have_no_value(store):
    window = hazard_grids.window("wind_iris_max_speed", "ssp245", 2050, 44.9, -79.9)
    assert math.isnan(window.values[0, 0]) and math.isnan(window.values[0, 1])
    assert window.asset_value is None


def test_a_layers_own_fill_value_is_no_data(store):
    window = hazard_grids.window("water_wri_stress", "historical", None, LAT, LON)
    assert window.asset_value is None
    assert np.isnan(window.values).sum() == 1


def test_netcdf_coordinates_south_first_are_read_north_up(store):
    window = hazard_grids.window("drought_osc_months_spei12m", "historical", None, LAT, LON)
    # Cells from latitude 35 up, so the asset is in row 10 from the south.
    assert window.bounds == (-75.5, 39.0, -73.0, 41.5)
    assert window.asset_value == 2000 + 10 * 20 + 11  # the threshold -2 is the third
    assert window.values[0, 0] == 2000 + 12 * 20 + 9


def test_a_grid_stored_0_to_360_wraps_at_greenwich(store):
    window = hazard_grids.window("heat_jupiter_days_above_35c", "ssp585", 2050, 10.5, -0.5)
    assert window.bounds == (-2.0, 9.0, 1.0, 12.0)
    assert window.values[0].tolist() == [358, 359, 0]
    assert window.asset_value == 359


def test_a_window_crossing_the_antimeridian_wraps(store):
    window = hazard_grids.window("fire_jupiter_probability", "ssp585", 2050, 10.5, 179.5)
    assert window.bounds == (178.0, 9.0, 181.0, 12.0)
    assert window.values[0].tolist() == [358, 359, 0]
    assert window.asset_value == 359


def test_a_missing_default_index_raises(store, tmp_path):
    other = RecordingStore(str(tmp_path / "other.zarr"))
    attrs = {**IRIS_ATTRS, "index_values": [10, 50, 1000]}
    _array(
        zarr.group(store=other),
        IRIS.format(scenario="historical", year=2010),
        _regional([0, 1, 2]),
        REGIONAL,
        attrs,
    )
    hazard_grids.use_store(other)
    with pytest.raises(CatalogueError, match="no index 100"):
        hazard_grids.window("wind_iris_max_speed", "historical", None, LAT, LON)


def test_reads_hold_physrisks_lock(store):
    hazard_grids.window("wind_iris_max_speed", "historical", None, LAT, LON)
    assert store.reads and all(locked for _, locked in store.reads)
    assert not _physrisk_lock.locked()


def test_assets_in_the_same_cell_share_a_window_without_a_read(store):
    first = hazard_grids.window("wind_iris_max_speed", "historical", None, LAT, LON)
    reads = len(store.reads)
    again = hazard_grids.window("wind_iris_max_speed", "historical", None, LAT + 0.1, LON + 0.1)
    assert again is first and len(store.reads) == reads
    hazard_grids.window("wind_iris_max_speed", "historical", None, LAT + 0.5, LON)
    assert len(store.reads) > reads


def test_the_window_cache_drops_the_least_recently_used(store, monkeypatch):
    monkeypatch.setattr(hazard_grids, "_windows", hazard_grids._Cache(1))
    hazard_grids.window("wind_iris_max_speed", "historical", None, LAT, LON)
    hazard_grids.window("wind_iris_max_speed", "ssp245", 2050, LAT, LON)
    reads = len(store.reads)
    hazard_grids.window("wind_iris_max_speed", "historical", None, LAT, LON)
    assert len(store.reads) > reads


# Scale and images --------------------------------------------------------------------------------


def test_the_scale_spans_the_baseline_and_the_pair(store):
    shown = hazard_grids.view("wind_iris_max_speed", "ssp245", 2050, LAT, LON)
    assert shown.min_value == 1000 + 7 * 20 + 9  # the baseline's lowest
    assert shown.max_value == 500 + 1000 + 11 * 20 + 13  # the future's highest
    assert shown.window.asset_value == 500 + 1000 + 9 * 20 + 11


def test_without_a_baseline_the_scale_is_the_pairs_own(store):
    shown = hazard_grids.view("fire_jupiter_probability", "ssp585", 2050, LAT, LON)
    assert (shown.min_value, shown.max_value) == shown.window.value_range()


def _pixels(png):
    image = Image.open(io.BytesIO(png))
    assert image.mode == "RGBA"
    return np.asarray(image)


def _hex(pixel):
    return "#" + "".join(f"{int(v):02x}" for v in pixel[:3])


def test_render_colours_on_the_ramp_and_leaves_nan_transparent():
    ramp = hazard_grids.ramp("light")
    pixels = _pixels(hazard_grids.render(np.array([[0.0, np.nan], [1.0, 0.5]]), 0.0, 1.0, "light"))
    assert pixels.shape == (2, 2, 4)
    assert _hex(pixels[0, 0]) == ramp[0] and pixels[0, 0, 3] == hazard_grids.ALPHA
    assert _hex(pixels[1, 0]) == ramp[-1]
    assert _hex(pixels[1, 1]) == ramp[2]
    assert pixels[0, 1, 3] == 0


def test_a_flat_window_draws_the_lowest_colour():
    pixels = _pixels(hazard_grids.render(np.full((2, 2), 3.0), 3.0, 3.0, "dark"))
    assert _hex(pixels[0, 0]) == hazard_grids.ramp("dark")[0]


def test_the_image_is_one_pixel_per_cell_north_up(store):
    png = hazard_grids.image("wind_iris_max_speed", "historical", None, LAT, LON, "light")
    pixels = _pixels(png)
    assert pixels.shape == (5, 5, 4)
    ramp = hazard_grids.ramp("light")
    assert _hex(pixels[0, 0]) == ramp[0] and _hex(pixels[-1, -1]) == ramp[-1]


def test_images_are_cached_per_theme(store):
    light = hazard_grids.image("wind_iris_max_speed", "historical", None, LAT, LON, "light")
    reads = len(store.reads)
    assert hazard_grids.image("wind_iris_max_speed", "historical", None, LAT, LON, "light") is light
    dark = hazard_grids.image("wind_iris_max_speed", "historical", None, LAT, LON, "dark")
    assert dark != light and len(store.reads) == reads


def test_an_image_with_no_data_raises(store):
    with pytest.raises(NoGridData, match="no historical baseline"):
        hazard_grids.image("fire_jupiter_probability", "historical", None, LAT, LON, "light")


def test_an_unknown_theme_is_refused():
    with pytest.raises(ValueError, match="theme"):
        hazard_grids.ramp("sepia")


# Ramps -------------------------------------------------------------------------------------------


def _oklab_lightness(hex_colour):
    def linear(channel):
        c = channel / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(v) for v in hazard_grids._rgb(hex_colour))
    lms = (
        0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b,
        0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b,
        0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b,
    )
    l_, m_, s_ = (math.copysign(abs(v) ** (1 / 3), v) for v in lms)
    return 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_


@pytest.mark.parametrize(("theme", "direction"), [("light", -1), ("dark", 1)])
def test_ramp_lightness_moves_one_way_away_from_the_surface(theme, direction):
    lightness = [_oklab_lightness(colour) for colour in hazard_grids.ramp(theme)]
    steps = np.diff(lightness) * direction
    assert (steps >= 0.06).all(), lightness


def test_the_legend_is_the_ramp_as_drawn():
    data = json.loads(hazard_grids.DATA_FILE.read_text())
    assert hazard_grids.legend("dark")[0] == "rgba(24, 79, 149, 0.78)"
    assert len(hazard_grids.legend("light")) == len(data["ramps"]["light"])
