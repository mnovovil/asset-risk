"""The wildfire layer, read from a tiny local zarr store with the bucket's layout: no network."""

import io
import threading

import numpy as np
import pytest

from engine import fire_map, hazard_maps
from engine.assess import _physrisk_lock

PATH = "fire/jupiter/v1/fire_probability_ssp585_2050"
# 45 degree cells laid out as the real 0.25 degree array is: cell centres from -180 to 180
# inclusive, so the first and last columns are both at the antimeridian, with different values.
DX = 45.0
TRANSFORM = [DX, 0.0, -180 - DX / 2, 0.0, -DX, 90 + DX / 2, 0.0, 0.0, 1.0]
ROWS, COLS = 5, 9


def cells() -> np.ndarray:
    values = (np.arange(ROWS * COLS, dtype=np.float32).reshape(ROWS, COLS) + 1) / 100
    values[0, 0] = 0.0  # a real zero, not missing
    values[2, 4] = np.nan  # no data at (0, 0) degrees
    values[3, :] = np.nan  # a whole band with no data, around 45 degrees south
    return values


def write_store(path, values=None, attrs=None, name=PATH):
    import numcodecs
    import zarr

    store = zarr.DirectoryStore(str(path))
    root = zarr.open_group(store, mode="a")
    data = cells() if values is None else values
    array = root.create_dataset(
        name,
        shape=(1, *data.shape),
        dtype="float32",
        chunks=(1, 1000, 1000),
        compressor=numcodecs.Blosc(cname="lz4", clevel=5, shuffle=numcodecs.Blosc.SHUFFLE),
        fill_value=0.0,
    )
    array[0] = data
    array.attrs.update({"crs": "EPSG:4326", "transform_mat3x3": TRANSFORM} | (attrs or {}))
    return store


@pytest.fixture
def store(tmp_path):
    store = write_store(tmp_path / "hazard.zarr")
    fire_map.use_store(store)
    yield store
    fire_map.use_store(None)


@pytest.fixture
def loads(monkeypatch):
    """Counts reads of whole arrays."""
    seen = []
    real = fire_map._load

    def counting(scenario, year):
        seen.append((scenario, year))
        return real(scenario, year)

    monkeypatch.setattr(fire_map, "_load", counting)
    return seen


def pixels(png: bytes) -> np.ndarray:
    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))


def grid(values=None, x0=-180 - DX / 2, y0=90 + DX / 2) -> fire_map.Grid:
    return fire_map.Grid(cells() if values is None else values, x0, DX, y0, -DX)


# --- physrisk's inventory ------------------------------------------------------------------------


def fake_inventory(**changes):
    resource = {
        "hazard_type": "Fire",
        "path": fire_map.FIRE_PATH,
        "scenarios": [
            {"id": "ssp585", "years": [2050, 2030]},
            {"id": "ssp126", "years": [2030]},
        ],
        "license": "Commercial",
        "map": {"colormap": {"max_value": 0.7}},
    }
    return [{"path": "other/path", "hazard_type": "Wind"}, resource | changes]


def test_physrisks_inventory_has_the_fire_resource():
    """Fails when a physrisk bump drops or changes the resource the map and damage figures use."""
    cover = fire_map.read_coverage(fire_map.physrisk_inventory())
    assert set(cover.scenarios) == {"ssp126", "ssp585"}
    assert all(2050 in years for years in cover.scenarios.values())
    assert "historical" not in cover.scenarios
    assert cover.licence == "Commercial"
    assert cover.max_value == 0.7


def test_coverage_comes_from_the_inventory():
    cover = fire_map.read_coverage(fake_inventory())
    assert cover.scenarios == {"ssp585": (2030, 2050), "ssp126": (2030,)}
    assert cover.licence == "Commercial"


@pytest.mark.parametrize(
    ("inventory", "message"),
    [
        ([{"path": "other/path", "hazard_type": "Fire"}], "has no fire/jupiter"),
        (fake_inventory(hazard_type="Wind"), "no longer a Fire resource"),
        (fake_inventory(scenarios=[]), "lists no scenarios"),
        (fake_inventory(scenarios=[{"id": "ssp585", "years": []}]), "lists no scenarios"),
        (fake_inventory(map=None), "no colour scale"),
        (fake_inventory(map={"colormap": {"max_value": 0}}), "colour scale up to 0"),
    ],
)
def test_a_changed_inventory_fails_loudly(inventory, message):
    with pytest.raises(fire_map.HazardMapConfigError, match=message):
        fire_map.read_coverage(inventory)


@pytest.mark.parametrize(
    ("scenario", "year", "reason"),
    [
        ("ssp585", 2050, None),
        ("ssp126", 2030, None),
        ("historical", None, "physrisk's wildfire data has no historical baseline"),
        ("ssp245", 2050, "physrisk's wildfire data covers ssp126 and ssp585 only"),
        ("ssp370", 2050, "physrisk's wildfire data covers ssp126 and ssp585 only"),
        ("ssp585", 2080, "physrisk's wildfire data for ssp585 has 2030 and 2050 only"),
        ("ssp585", 2020, "physrisk's wildfire data for ssp585 has 2030 and 2050 only"),
        ("ssp126", 2050, "physrisk's wildfire data for ssp126 has 2030 only"),
        ("ssp585", None, "physrisk's wildfire data for ssp585 has 2030 and 2050 only"),
    ],
)
def test_only_an_exact_inventory_match_has_a_map(scenario, year, reason):
    cover = fire_map.read_coverage(fake_inventory())
    assert fire_map.unavailable_reason(scenario, year, cover) == reason


def test_the_real_coverage_lists_every_year():
    reason = fire_map.unavailable_reason("ssp585", 2080, fire_map.coverage())
    assert reason == (
        "physrisk's wildfire data for ssp585 has 2020, 2030, 2040, 2050, 2075 and 2100 only"
    )


# --- The array's layout --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("shape", "attrs", "message"),
    [
        ((ROWS, COLS), {"transform_mat3x3": TRANSFORM}, "expected a \\(1, rows, cols\\) array"),
        ((2, ROWS, COLS), {"transform_mat3x3": TRANSFORM}, "expected a \\(1, rows, cols\\) array"),
        ((1, ROWS, COLS), {}, "no transform_mat3x3"),
        ((1, ROWS, COLS), {"transform_mat3x3": TRANSFORM[:6]}, "no transform_mat3x3"),
        ((1, ROWS, COLS), {"transform_mat3x3": TRANSFORM, "crs": "EPSG:3857"}, "not EPSG:3857"),
        (
            (1, ROWS, COLS),
            {"transform_mat3x3": [DX, 1.0, *TRANSFORM[2:]]},
            "north-up grid with no rotation",
        ),
        (
            (1, ROWS, COLS),
            {"transform_mat3x3": [DX, 0.0, -202.5, 0.0, DX, -112.5, 0, 0, 1]},
            "north-up grid with no rotation",
        ),
    ],
)
def test_an_unexpected_layout_fails_loudly(shape, attrs, message):
    with pytest.raises(fire_map.HazardMapConfigError, match=message):
        fire_map.grid_from(np.zeros(shape, dtype=np.float32), attrs)


def test_the_store_is_read_with_its_layout(store):
    g = fire_map.grid("ssp585", 2050)
    assert g.values.shape == (ROWS, COLS)
    assert (g.x0, g.dx, g.y0, g.dy) == (-202.5, 45.0, 112.5, -45.0)
    np.testing.assert_array_equal(g.values, cells())


# --- Tile maths ----------------------------------------------------------------------------------


def test_pixel_centres_span_the_web_mercator_world():
    lon, lat = fire_map.pixel_lonlat(0, 0, 0)
    assert lon[0] == pytest.approx(-180 + 360 / 1024)
    assert lon[-1] == pytest.approx(180 - 360 / 1024)
    assert lat[0] == pytest.approx(85.05, abs=0.2)
    assert lat[-1] == pytest.approx(-85.05, abs=0.2)
    assert lat[255] > 0 > lat[256]  # the equator is between the middle rows


def test_each_pixel_takes_the_cell_its_centre_is_in():
    g = grid()
    tile = fire_map.sample(g, 0, 0, 0)
    lon, lat = fire_map.pixel_lonlat(0, 0, 0)
    for i in (0, 100, 300, 511):
        for j in (0, 200, 400, 511):
            row = int((lat[i] - 112.5) // -45)
            col = int((lon[j] + 202.5) // 45)
            np.testing.assert_equal(tile[i, j], cells()[row, col])


def test_cells_stay_blocky():
    """Nearest neighbour: a tile shows only the grid's own values, never blends of them."""
    tile = fire_map.sample(grid(), 2, 1, 1)
    finite = tile[np.isfinite(tile)]
    assert set(np.unique(finite)) <= set(cells()[np.isfinite(cells())].tolist())


def test_the_antimeridian_reads_both_edge_columns():
    """The array's first and last columns are both at 180 degrees: west of it reads the last."""
    west, east = fire_map.sample(grid(), 1, 0, 0), fire_map.sample(grid(), 1, 1, 0)
    assert west[300, 0] == cells()[1, 0]  # just east of -180
    assert east[300, -1] == cells()[1, COLS - 1]  # just west of 180


def test_a_grid_stored_0_to_360_wraps_west_longitudes():
    values = cells()[:, :8]
    g = fire_map.Grid(values, 0.0, DX, 90 + DX / 2, -DX)
    lon, _ = fire_map.pixel_lonlat(0, 0, 0)
    cols = fire_map._columns(g, lon)
    assert cols[0] == 4  # -179.6 is 180.4 on a 0-360 grid
    assert cols[-1] == 3  # 179.6
    assert (cols >= 0).all()


def test_beyond_a_grids_edges_is_no_data():
    values = cells()[1:3, :3]  # 67.5 N to -22.5 S, -202.5 to -67.5 E
    g = fire_map.Grid(values, -202.5, DX, 67.5, -DX)
    tile = fire_map.sample(g, 0, 0, 0)
    lon, lat = fire_map.pixel_lonlat(0, 0, 0)
    assert np.isnan(tile[lat > 67.5]).all()
    assert np.isnan(tile[lat < -22.5]).all()
    assert np.isnan(tile[:, (lon > -67.5) & (lon < 157.5)]).all()
    # -202.5 is 157.5 east: the grid's west edge is read there, shifted by 360 degrees.
    assert np.isfinite(tile[(lat < 60) & (lat > -20)][:, lon > 158]).any()
    assert np.isfinite(tile[(lat < 60) & (lat > -20)][:, lon < -70]).any()


def test_the_poles_past_web_mercator_are_never_asked_for():
    _, lat = fire_map.pixel_lonlat(fire_map.MAX_ZOOM, 0, 0)
    assert lat.max() < 85.06
    _, lat = fire_map.pixel_lonlat(fire_map.MAX_ZOOM, 0, 2**fire_map.MAX_ZOOM - 1)
    assert lat.min() > -85.06


# --- Colours -------------------------------------------------------------------------------------


def test_no_data_is_transparent_and_zero_is_not():
    values = np.array([[np.nan, 0.0, 0.7, 5.0, -0.1]], dtype=np.float32)
    rgba = fire_map.colours(values, 0.7)
    first = fire_map.colour_table()[0]
    last = fire_map.colour_table()[-1]
    assert rgba[0, 0, 3] == 0
    np.testing.assert_array_equal(rgba[0, 1], first)
    assert rgba[0, 1, 3] == fire_map.ALPHA
    np.testing.assert_array_equal(rgba[0, 2], last)
    np.testing.assert_array_equal(rgba[0, 3], last)  # above the scale: clamped
    np.testing.assert_array_equal(rgba[0, 4], first)


def test_the_ramp_stops_are_drawn_exactly():
    table = fire_map.colour_table()
    for i, colour in enumerate(fire_map.RAMP):
        rgb = [int(colour[k : k + 2], 16) for k in (1, 3, 5)]
        assert table[i * 64, :3].tolist() == rgb


def test_lightness_falls_all_the_way_up_the_scale():
    lab = fire_map._linear_to_oklab(
        np.array(
            [
                fire_map._hex_to_linear("#{:02x}{:02x}{:02x}".format(*c[:3]))
                for c in fire_map.colour_table()
            ]
        )
    )
    assert (np.diff(lab[:, 0]) < 0.002).all()  # rounding to 8 bits can wobble by a hair
    assert lab[0, 0] - lab[-1, 0] > 0.3


def test_the_legend_is_drawn_with_the_tiles_colours():
    legend = fire_map.legend()
    assert len(legend) == fire_map.LEGEND_STOPS
    max_value = 0.7
    for i, colour in enumerate(legend):
        value = max_value * i / (len(legend) - 1)
        r, g, b, _ = fire_map.colours(np.array([[value]]), max_value)[0, 0]
        assert colour == f"rgba({r}, {g}, {b}, 0.78)"


# --- Tiles, caching and the lock -----------------------------------------------------------------


def test_a_tile_is_a_512_px_png_with_clear_no_data(store):
    image = pixels(fire_map.tile("ssp585", 2050, 0, 0, 0))
    assert image.shape == (512, 512, 4)
    alpha = image[..., 3]
    assert (alpha == 0).any() and (alpha == fire_map.ALPHA).any()
    _, lat = fire_map.pixel_lonlat(0, 0, 0)
    band = (lat < -27) & (lat > -63)  # row 3, all NaN
    assert (alpha[band] == 0).all()


def test_a_tile_with_no_data_is_none(tmp_path):
    fire_map.use_store(write_store(tmp_path / "z", values=np.full((ROWS, COLS), np.nan, "f4")))
    try:
        assert fire_map.tile("ssp585", 2050, 0, 0, 0) is None
    finally:
        fire_map.use_store(None)


@pytest.mark.parametrize(
    ("scenario", "year", "z", "x", "y"),
    [
        ("historical", None, 0, 0, 0),
        ("ssp245", 2050, 0, 0, 0),
        ("ssp585", 2080, 0, 0, 0),
        ("ssp585", 2050, fire_map.MAX_ZOOM + 1, 0, 0),
        ("ssp585", 2050, -1, 0, 0),
        ("ssp585", 2050, 2, 4, 0),
        ("ssp585", 2050, 2, 0, 4),
        ("ssp585", 2050, 2, -1, 0),
    ],
)
def test_no_map_is_none_without_reading(store, loads, scenario, year, z, x, y):
    assert fire_map.tile(scenario, year, z, x, y) is None
    assert loads == []


def test_the_array_is_read_once_for_many_tiles(store, loads):
    for z, x, y in [(0, 0, 0), (1, 0, 0), (1, 1, 1), (2, 3, 1)]:
        fire_map.tile("ssp585", 2050, z, x, y)
    assert loads == [("ssp585", 2050)]


def test_tiles_are_cached_including_empty_ones(store, monkeypatch):
    drawn = []
    real = fire_map.render
    monkeypatch.setattr(fire_map, "render", lambda *a: drawn.append(1) or real(*a))
    for _ in range(3):
        fire_map.tile("ssp585", 2050, 0, 0, 0)
    monkeypatch.setattr(fire_map, "sample", lambda *a: np.full((2, 2), np.nan))
    for _ in range(2):
        assert fire_map.tile("ssp585", 2050, 1, 0, 0) is None
    assert len(drawn) == 2


def test_cold_requests_at_once_read_the_array_once(store, monkeypatch):
    calls = []
    release = threading.Event()
    real = fire_map._load

    def slow(scenario, year):
        calls.append(1)
        release.wait(5)
        return real(scenario, year)

    monkeypatch.setattr(fire_map, "_load", slow)
    results = []
    threads = [
        threading.Thread(target=lambda i=i: results.append(fire_map.tile("ssp585", 2050, 2, i, 1)))
        for i in range(4)
    ]
    for thread in threads:
        thread.start()
    release.set()
    for thread in threads:
        thread.join(10)
    assert len(calls) == 1
    assert len(results) == 4


def test_a_failed_read_raises_and_is_not_cached(store, monkeypatch):
    calls = []

    def fail(scenario, year):
        calls.append(1)
        raise OSError("S3 down")

    monkeypatch.setattr(fire_map, "_load", fail)
    for _ in range(2):
        with pytest.raises(OSError, match="S3 down"):
            fire_map.tile("ssp585", 2050, 0, 0, 0)
    assert len(calls) == 2


def test_a_missing_array_raises(tmp_path):
    fire_map.use_store(write_store(tmp_path / "z", name="fire/jupiter/v1/other"))
    try:
        with pytest.raises(KeyError):
            fire_map.tile("ssp585", 2050, 0, 0, 0)
    finally:
        fire_map.use_store(None)


def test_only_a_few_arrays_are_kept(store, loads, monkeypatch):
    monkeypatch.setattr(fire_map, "_load", lambda s, y: (loads.append((s, y)), grid())[1])
    for year in range(fire_map.CACHE_ARRAYS + 1):
        fire_map.grid("ssp585", year)
    fire_map.grid("ssp585", fire_map.CACHE_ARRAYS)  # still kept
    fire_map.grid("ssp585", 0)  # the least recently used: dropped, so read again
    assert loads.count(("ssp585", 0)) == 2
    assert loads.count(("ssp585", fire_map.CACHE_ARRAYS)) == 1


def test_tiles_are_drawn_without_physrisks_lock(store):
    """A download mustn't wait for, or stall, a running assessment."""
    done = threading.Event()
    with _physrisk_lock:
        thread = threading.Thread(
            target=lambda: (fire_map.tile("ssp585", 2050, 0, 0, 0), done.set())
        )
        thread.start()
        assert done.wait(10)
    thread.join()


# --- As a hazard map layer -----------------------------------------------------------------------


def test_fire_is_a_hazard_map_layer(store):
    layer = hazard_maps.LAYERS["Fire"]
    assert layer.return_period is None
    assert (layer.min_value, layer.max_value, layer.max_zoom) == (0.0, 0.7, 6)
    assert "within 100 km" in layer.measure
    for text in ("not at the building", "divides it by 500", "28 km", "not proof of low risk"):
        assert text in layer.note
    assert "Jupiter Intelligence" in layer.source and '"Commercial"' in layer.source
    assert layer.reason("historical", None) == "physrisk's wildfire data has no historical baseline"
    assert hazard_maps.tile("Fire", "ssp585", 2050, 0, 0, 0).startswith(b"\x89PNG")
