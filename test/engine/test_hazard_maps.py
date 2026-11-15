import io

import pytest

from engine import hazard_maps
from engine.assess import _physrisk_lock

RIVER = "RiverineInundation"
COAST = "CoastalInundation"
# Zoom 5 tiles over the Ganges delta and the Bay of Bengal coast, where both maps have water.
DELTA_TILE = (5, 23, 13)
COAST_TILE = (6, 47, 27)


class FakeRequester:
    def __init__(self, result=b"png", error=None):
        self.requests = []
        self.result = result
        self.error = error
        self.locked = []

    def get_image(self, request_or_dict):
        self.requests.append(request_or_dict)
        self.locked.append(_physrisk_lock.locked())
        if self.error:
            raise self.error
        return self.result


@pytest.fixture(autouse=True)
def empty_cache():
    hazard_maps._cache.clear()
    yield
    hazard_maps._cache.clear()


def test_a_tile_asks_physrisk_for_the_1000_year_layer():
    requester = FakeRequester()
    assert hazard_maps.tile(RIVER, "ssp585", 2050, 5, 23, 13, requester) == b"png"
    assert requester.requests == [
        {
            "resource": "inundation/wri/v2/inunriver_{scenario}_MIROC-ESM-CHEM_{year}",
            "scenario_id": "ssp585",
            "year": 2050,
            "tile": {"x": 23, "y": 13, "z": 5},
            "min_value": 0.0,
            "max_value": 2.0,
            "index_value": 1000,
            "colormap": "flare",
        }
    ]


def test_historical_uses_physrisks_baseline_year():
    requester = FakeRequester()
    hazard_maps.tile(COAST, "historical", None, 5, 23, 13, requester)
    assert requester.requests[0]["scenario_id"] == "historical"
    assert requester.requests[0]["year"] == 1980


def test_physrisk_is_called_under_the_shared_lock():
    requester = FakeRequester()
    hazard_maps.tile(RIVER, "historical", None, 0, 0, 0, requester)
    assert requester.locked == [True]
    assert not _physrisk_lock.locked()


@pytest.mark.parametrize(
    ("hazard", "scenario", "year", "z", "x", "y"),
    [
        ("Wind", "ssp585", 2050, 5, 0, 0),  # no public map
        (RIVER, "ssp370", 2050, 5, 0, 0),  # no RCP for it
        (RIVER, "ssp126", 2050, 5, 0, 0),
        (RIVER, "ssp585", 2100, 5, 0, 0),  # past the data: physrisk would extrapolate
        (RIVER, "ssp585", None, 5, 0, 0),
        (RIVER, "ssp585", 2050, 7, 0, 0),  # deeper than the pyramid
        (RIVER, "ssp585", 2050, -1, 0, 0),
        (RIVER, "ssp585", 2050, 2, 4, 0),  # off the edge of the world
        (RIVER, "ssp585", 2050, 2, 0, -1),
    ],
)
def test_no_map_is_none_without_calling_physrisk(hazard, scenario, year, z, x, y):
    requester = FakeRequester()
    assert hazard_maps.tile(hazard, scenario, year, z, x, y, requester) is None
    assert requester.requests == []


def test_a_missing_tile_is_none_and_cached():
    from physrisk.api.v1.hazard_image import TileNotAvailableError

    requester = FakeRequester(error=TileNotAvailableError("path/7"))
    assert hazard_maps.tile(RIVER, "ssp585", 2050, 6, 1, 1, requester) is None
    assert hazard_maps.tile(RIVER, "ssp585", 2050, 6, 1, 1, requester) is None
    assert len(requester.requests) == 1


def test_a_tile_is_drawn_once():
    requester = FakeRequester()
    for _ in range(3):
        hazard_maps.tile(RIVER, "ssp585", 2050, 5, 23, 13, requester)
    hazard_maps.tile(RIVER, "ssp585", 2080, 5, 23, 13, requester)
    assert len(requester.requests) == 2


def test_other_failures_raise_and_are_not_cached():
    requester = FakeRequester(error=RuntimeError("S3 down"))
    for _ in range(2):
        with pytest.raises(RuntimeError, match="S3 down"):
            hazard_maps.tile(RIVER, "ssp585", 2050, 5, 23, 13, requester)
    assert len(requester.requests) == 2


def test_the_cache_drops_the_least_recently_used_tile():
    cache = hazard_maps.LruCache(2)
    cache.put("a", b"a")
    cache.put("b", b"b")
    assert cache.get("a") == (True, b"a")
    cache.put("c", b"c")
    assert cache.get("b") == (False, None)
    assert cache.get("a") == (True, b"a")


@pytest.mark.parametrize(
    ("scenario", "year", "reason"),
    [
        ("historical", None, None),
        ("ssp245", 2030, None),
        ("ssp585", 2080, None),
        ("ssp370", 2050, "physrisk has no flood map for this scenario"),
        ("ssp585", 2020, "physrisk's flood maps cover 2030 to 2080"),
    ],
)
def test_unavailable_reason(scenario, year, reason):
    assert hazard_maps.unavailable_reason(scenario, year) == reason


def test_legend_runs_light_to_dark_with_the_maps_transparency():
    colours = hazard_maps.LAYERS[RIVER].legend()
    assert len(colours) == 5
    assert all(c.startswith("rgba(") and c.endswith(", 0.78)") for c in colours)
    lightness = [sum(int(v) for v in c[5:].split(",")[:3]) for c in colours]
    assert lightness == sorted(lightness, reverse=True)


def test_layers_list_flood_then_wildfire_then_wind():
    assert list(hazard_maps.LAYERS) == [RIVER, COAST, "Fire", "Wind"]


@pytest.mark.parametrize("hazard", [RIVER, COAST])
def test_flood_layers_describe_themselves(hazard):
    layer = hazard_maps.LAYERS[hazard]
    assert (layer.measure, layer.units, layer.return_period) == ("Flood depth", "m", 1000)
    assert layer.no_data_label == "No flood in the data"
    assert "1-in-1000-year" in layer.note and "not proof of no risk" in layer.note
    assert layer.reason("ssp370", 2050) == "physrisk has no flood map for this scenario"


def test_the_flood_source_quotes_physrisks_licence():
    from engine.fire_map import physrisk_inventory

    licences = {
        r["license"]
        for r in physrisk_inventory()
        for layer in hazard_maps.LAYERS.values()
        if isinstance(layer, hazard_maps.FloodLayer) and r["path"] == layer.resource
    }
    assert len(licences) == 1
    assert f'"{licences.pop()}"' in hazard_maps.FLOOD_SOURCE


def test_an_unknown_hazard_has_no_tile():
    assert hazard_maps.tile("Hail", "ssp585", 2050, 0, 0, 0, FakeRequester()) is None


def opaque_pixels(png: bytes) -> int:
    from PIL import Image

    image = Image.open(io.BytesIO(png)).convert("RGBA")
    return sum(1 for alpha in image.getchannel("A").get_flattened_data() if alpha)


@pytest.mark.live
@pytest.mark.parametrize("hazard", [RIVER, COAST])
@pytest.mark.parametrize(("scenario", "year"), [("historical", None), ("ssp585", 2050)])
def test_live_flood_maps_have_water(hazard, scenario, year):
    image = hazard_maps.tile(hazard, scenario, year, *COAST_TILE)
    assert image is not None
    assert opaque_pixels(image) > 0


@pytest.mark.live
def test_live_tiles_use_the_legends_colormap():
    """physrisk's request defaults to "heating", which would leave the legend wrong."""
    from physrisk.data.colormap_provider import colormap
    from PIL import Image

    layer = hazard_maps.LAYERS[RIVER]
    image = hazard_maps.tile(RIVER, "historical", None, *COAST_TILE)
    drawn = {p for p in Image.open(io.BytesIO(image)).convert("RGBA").get_flattened_data() if p[3]}
    assert drawn
    assert drawn <= {tuple(entry) for entry in colormap(layer.colormap).values()}


@pytest.mark.live
def test_live_only_the_1000_year_layer_has_data():
    from engine.assess import default_requester

    request = {
        "resource": hazard_maps.LAYERS[RIVER].resource,
        "scenario_id": "historical",
        "year": 1980,
        "tile": dict(zip("zxy", DELTA_TILE, strict=True)),
        "min_value": 0.0,
        "max_value": 2.0,
    }
    requester = default_requester()
    assert opaque_pixels(requester.get_image(request | {"index_value": 1000})) > 0
    # If this fails, physrisk has added return periods: the map could offer a choice.
    assert opaque_pixels(requester.get_image(request | {"index_value": 100})) == 0


@pytest.mark.live
def test_live_tiles_stop_at_max_zoom():
    from physrisk.api.v1.hazard_image import TileNotAvailableError

    from engine.assess import default_requester

    z = hazard_maps.MAX_ZOOM + 1
    with pytest.raises(TileNotAvailableError):
        default_requester().get_image(
            {
                "resource": hazard_maps.LAYERS[RIVER].resource,
                "scenario_id": "historical",
                "year": 1980,
                "tile": {"z": z, "x": 2 ** (z - 1), "y": 2 ** (z - 1)},
                "min_value": 0.0,
                "max_value": 2.0,
                "index_value": 1000,
            }
        )


@pytest.mark.live
def test_live_catalogue_matches_physrisks_inventory():
    from physrisk.requests import _read_permitted

    from engine.assess import default_requester

    resources = default_requester().inventory.resources
    for layer in hazard_maps.LAYERS.values():
        if not isinstance(layer, hazard_maps.FloodLayer):
            continue
        resource = resources[layer.resource]
        assert resource.hazard_type == layer.hazard
        assert _read_permitted(["public"], resource)
        assert resource.map.colormap.name == layer.colormap
        assert resource.map.colormap.units == layer.units
        assert resource.map.colormap.max_value == layer.max_value
        scenarios = {s.id: s.years for s in resource.scenarios}
        assert set(scenarios) == {"rcp4p5", "rcp8p5"}
        assert all(
            (min(years), max(years)) == hazard_maps.SCENARIO_YEARS for years in scenarios.values()
        )


@pytest.mark.live
def test_live_other_hazards_have_no_public_map():
    """If this fails, physrisk has opened up more maps, and the catalogue could grow."""
    from physrisk.requests import _read_permitted

    from engine.assess import default_requester

    for resource in default_requester().inventory.resources.values():
        if resource.hazard_type in ("Wind", "Fire", "Hail", "Drought"):
            assert not _read_permitted(["public"], resource), resource.path
