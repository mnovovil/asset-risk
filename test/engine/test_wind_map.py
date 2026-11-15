"""The tropical cyclone wind layer, read from an in-memory zarr store shaped as IRIS: no network."""

import io
import threading

import numpy as np
import pytest

from engine import grid_layer, hazard_maps, wind_map
from engine.assess import _physrisk_lock
from engine.grid_layer import GridSettings, HazardMapConfigError

PATH = "wind/iris/v1/max_speed_ssp585_2050"
HISTORICAL_PATH = "wind/iris/v1/max_speed_historical_2010"
PERIODS = [10, 100, 1000]
# 30 degree cells from 60 N to 60 S and -180 to 180 with no repeated column, as IRIS lays out its
# 0.1 degree grid, with IRIS's float noise in the transform.
DX = 30.0
TRANSFORM = [DX - 5e-15, 0.0, -180.0 + 3e-14, 0.0, -DX, 60.0 + 1.7e-12, 0.0, 0.0, 1.0]
ROWS, COLS = 4, 12


def cells(period: int) -> np.ndarray:
    values = np.arange(ROWS * COLS, dtype=np.float32).reshape(ROWS, COLS) + period / 10
    values[1, 6] = np.nan  # no tropical cyclone at (0, 0) degrees
    values[0, :] = np.nan  # a whole band with none, 30 to 60 degrees north
    return values


def iris_store(periods=PERIODS, attrs=None, name=PATH, values=None):
    """IRIS's layout: (index, rows, cols), chunks that split the columns, fill_value 0."""
    import numcodecs
    import zarr

    store = zarr.MemoryStore()
    root = zarr.open_group(store, mode="a")
    data = np.stack([cells(p) for p in periods]) if values is None else values
    array = root.create_dataset(
        name,
        shape=data.shape,
        dtype="float32",
        chunks=(len(periods), 3, 5),  # three column chunks, two row chunks
        compressor=numcodecs.Blosc(cname="lz4", clevel=5, shuffle=numcodecs.Blosc.SHUFFLE),
        fill_value=0.0,
    )
    array[:] = data
    array.attrs.update(
        {
            "crs": "EPSG:4326",
            "dimensions": ["index", "latitude", "longitude"],
            "index_name": "return period (years)",
            "index_values": periods,
            "transform_mat3x3": TRANSFORM,
        }
        | (attrs or {})
    )
    return store


@pytest.fixture
def layer():
    layer = wind_map.configure()
    layer.use_store(iris_store())
    return layer


def pixels(png: bytes) -> np.ndarray:
    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))


# --- physrisk's inventory ------------------------------------------------------------------------


def test_physrisks_wind_damage_reads_iris():
    """Fails when a physrisk bump changes which wind data the losses use."""
    from physrisk.hazard_models.core_hazards import get_default_source_paths
    from physrisk.kernel.hazards import Wind

    resources = get_default_source_paths().get_resources(hazard_type=Wind, indicator_id="max_speed")
    assert [r.path for r in resources] == [wind_map.WIND_PATH]


def test_physrisk_does_not_rescale_iris():
    from physrisk.vulnerability_models.config_based_vuln_model_param import (
        ConfigBasedVulnerabilityModelParam,
    )

    values = np.array([30.0, 60.0])
    adjust = ConfigBasedVulnerabilityModelParam._adjust_indicator_values
    np.testing.assert_array_equal(adjust(None, PATH, values), values)
    fire = "fire/jupiter/v1/fire_probability_ssp585_2050"
    np.testing.assert_array_equal(adjust(None, fire, values), values / 500)  # the check still bites


def test_physrisks_inventory_has_the_iris_resource():
    cover = wind_map.configure().coverage()
    assert cover.scenarios == {
        "historical": (2010,),
        "ssp119": (2050,),
        "ssp245": (2050,),
        "ssp585": (2050,),
    }
    assert cover.units == "m/s"
    assert cover.max_value == 90.0
    assert cover.licence.startswith("Creative Commons Attribution 4.0")
    assert "Sparks" in cover.attribution and "doi.org" in cover.attribution


@pytest.mark.parametrize(
    ("scenario", "year", "reason"),
    [
        ("historical", None, None),
        ("ssp245", 2050, None),
        ("ssp585", 2050, None),
        (
            "ssp126",
            2050,
            "physrisk's tropical cyclone wind data covers ssp119, ssp245 and ssp585 only",
        ),
        (
            "ssp370",
            2050,
            "physrisk's tropical cyclone wind data covers ssp119, ssp245 and ssp585 only",
        ),
        (
            "ssp245",
            2030,
            "physrisk's tropical cyclone wind data for ssp245 has 2050 only. physrisk estimates "
            "the other years' losses from it and the baseline",
        ),
        (
            "ssp585",
            2080,
            "physrisk's tropical cyclone wind data for ssp585 has 2050 only. physrisk estimates "
            "the other years' losses from it and the baseline",
        ),
    ],
)
def test_only_an_exact_inventory_match_has_a_map(scenario, year, reason):
    assert wind_map.configure().reason(scenario, year) == reason


# --- The array's layout --------------------------------------------------------------------------


def test_one_return_period_is_read_across_chunks(layer):
    g = layer.grid("ssp585", 2050)
    assert g.values.shape == (ROWS, COLS)
    assert g.dx == pytest.approx(DX) and g.x0 == pytest.approx(-180)
    assert g.y0 == pytest.approx(60) and g.dy == -DX
    np.testing.assert_array_equal(g.values, cells(wind_map.RETURN_PERIOD))


def test_the_historical_baseline_reads_its_own_year():
    layer = wind_map.configure()
    layer.use_store(iris_store(name=HISTORICAL_PATH))
    assert layer.tile("historical", None, 0, 0, 0).startswith(b"\x89PNG")


@pytest.mark.parametrize(
    ("attrs", "message"),
    [
        ({"index_values": [10, 20, 1000]}, "no 100-year return period"),
        ({"index_values": [10, 100]}, "expected 3 index_values"),
        ({"index_values": None}, "expected 3 index_values"),
        ({"crs": "EPSG:3857"}, "not EPSG:3857"),
    ],
)
def test_an_unexpected_layout_fails_loudly(attrs, message):
    layer = wind_map.configure()
    layer.use_store(iris_store(attrs=attrs))
    with pytest.raises(HazardMapConfigError, match=message):
        layer.grid("ssp585", 2050)


def test_a_flat_array_fails_loudly():
    layer = wind_map.configure()
    layer.use_store(iris_store(values=np.zeros((3, ROWS, COLS), "f4")))
    store = layer.store
    del store[f"{PATH}/.zarray"]  # replace it with a 2-D array
    import zarr

    zarr.open_group(store, mode="a").create_dataset(PATH, data=np.zeros((ROWS, COLS), "f4"))
    with pytest.raises(HazardMapConfigError, match="expected an \\(index, rows, cols\\) array"):
        layer.grid("ssp585", 2050)


# --- Tiles ---------------------------------------------------------------------------------------


def test_beyond_60_degrees_and_no_cyclone_are_clear(layer):
    image = pixels(layer.tile("ssp585", 2050, 0, 0, 0))
    _, lat = grid_layer.pixel_lonlat(0, 0, 0)
    alpha = image[..., 3]
    assert (alpha[lat > 60.1] == 0).all()
    assert (alpha[lat < -60.1] == 0).all()
    assert (alpha[(lat < 59) & (lat > 31)] == 0).all()  # the NaN band
    band = (lat < 29) & (lat > -59)
    assert (alpha[band] == 200).mean() > 0.9


def test_the_antimeridian_reads_both_edge_columns(layer):
    g = layer.grid("ssp585", 2050)
    west = grid_layer.sample(g, 1, 0, 1)
    east = grid_layer.sample(g, 1, 1, 1)
    _, lat = grid_layer.pixel_lonlat(1, 0, 1)
    assert 0 > lat[50] > -30  # row 2
    assert west[50, 0] == cells(100)[2, 0]  # just east of -180
    assert east[50, -1] == cells(100)[2, COLS - 1]  # just west of 180


def test_a_tile_with_no_data_is_none():
    layer = wind_map.configure()
    layer.use_store(iris_store(values=np.full((3, ROWS, COLS), np.nan, "f4")))
    assert layer.tile("ssp585", 2050, 0, 0, 0) is None


def test_no_map_is_none_without_reading(layer, monkeypatch):
    monkeypatch.setattr(layer, "_load", lambda *a: pytest.fail("read"))
    assert layer.tile("ssp585", 2030, 0, 0, 0) is None
    assert layer.tile("ssp126", 2050, 0, 0, 0) is None
    assert layer.tile("ssp585", 2050, wind_map.MAX_ZOOM + 1, 0, 0) is None


def test_tiles_are_drawn_without_physrisks_lock(layer):
    done = threading.Event()
    with _physrisk_lock:
        thread = threading.Thread(target=lambda: (layer.tile("ssp585", 2050, 0, 0, 0), done.set()))
        thread.start()
        assert done.wait(10)
    thread.join()


def test_settings_reach_the_layer():
    settings = GridSettings(alpha=120, legend_stops=3, array_cache=1, tile_cache=1)
    layer = wind_map.configure(max_zoom=4, settings=settings)
    layer.use_store(iris_store())
    assert layer.max_zoom == 4
    assert len(layer.legend()) == 3 and layer.legend()[0].endswith(", 0.47)")
    assert set(np.unique(pixels(layer.tile("ssp585", 2050, 0, 0, 0))[..., 3])) == {0, 120}


# --- Colours -------------------------------------------------------------------------------------


def test_the_ramp_is_one_hue_with_lightness_falling():
    lab = np.array(
        [grid_layer._linear_to_oklab(grid_layer._hex_to_linear(c)) for c in wind_map.RAMP]
    )
    assert (np.diff(lab[:, 0]) <= -0.06).all()
    hues = np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % 360
    assert np.ptp(hues) < 2 and abs(hues.mean() - 162) < 2


def test_the_ramp_stops_are_drawn_exactly():
    table = wind_map.configure().colour_table()
    for i, colour in enumerate(wind_map.RAMP):
        assert table[i * 64, :3].tolist() == [int(colour[k : k + 2], 16) for k in (1, 3, 5)]


# --- As a hazard map layer -----------------------------------------------------------------------


def test_wind_is_a_hazard_map_layer():
    layer = hazard_maps.LAYERS["Wind"]
    assert (layer.units, layer.return_period, layer.min_value, layer.max_value) == (
        "m/s",
        100,
        0.0,
        90.0,
    )
    assert layer.max_zoom == wind_map.MAX_ZOOM
    assert "Tropical cyclone" in layer.measure
    assert "60°" in layer.no_data_label
    for text in ("once in 100 years", "10 km", "not proof of low risk", "no wind loss"):
        assert text in layer.note
    assert "Imperial College" in layer.source and "Sparks" in layer.source
    assert "Creative Commons Attribution 4.0" in layer.source
    assert len(layer.legend()) == 9
