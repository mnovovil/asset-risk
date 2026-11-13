"""hazard_grids against physrisk's public bucket. Opt-in: pytest -m live."""

import pytest

from engine import hazard_grids
from engine.assess import HISTORICAL
from engine.settings import SCENARIOS, YEARS

pytestmark = pytest.mark.live

# Williamsburg, Brooklyn.
NYC = (40.712483, -73.955460)


@pytest.fixture(scope="module", autouse=True)
def bucket():
    hazard_grids.use_store(None)
    yield
    hazard_grids.clear_caches()


def _pairs():
    return [(HISTORICAL, None), *((s, y) for s in SCENARIOS for y in YEARS)]


@pytest.mark.parametrize("layer_id", sorted(hazard_grids.catalogue()))
def test_live_every_layer_reads_for_every_pair_it_has(layer_id):
    layer = hazard_grids.catalogue()[layer_id]
    read = 0
    for scenario, year in _pairs():
        if hazard_grids.unavailable_reason(layer, scenario, year):
            continue
        window = hazard_grids.window(layer_id, scenario, year, *NYC)
        assert window.values.size > 1
        read += 1
    assert read, f"{layer_id} has none of the app's scenarios and years"


@pytest.mark.parametrize(
    "path",
    [
        "wind/wisc/v1/max_speed_historical_1999/max_speed",
        "fire/ECB_fire_risk_indicators/v1_1/historical_2010",
    ],
)
def test_live_europe_only_layers_have_nothing_at_nyc(path):
    from physrisk.data.zarr_reader import ZarrReader

    lat, lon = NYC
    assert not ZarrReader().in_bounds(path, [lon], [lat]).any()


def test_live_feeds_damage_matches_physrisks_selectors():
    from physrisk.data.inventory import EmbeddedInventory
    from physrisk.hazard_models.core_hazards import CoreInventorySourcePaths
    from physrisk.kernel.hazards import Fire, Hail, Wind

    paths = CoreInventorySourcePaths(EmbeddedInventory())
    selected = {
        resource.path
        for hazard, indicator in (
            (Wind, "max_speed"),
            (Fire, "fire_probability"),
            (Hail, "days/above/5cm"),
        )
        for resource in paths.get_resources(hazard, indicator)
    }
    feeding = {layer.path for layer in hazard_grids.catalogue().values() if layer.feeds_damage}
    assert feeding == selected


@pytest.mark.parametrize(
    ("layer_id", "scenario", "year", "value"),
    [
        ("heat_jupiter_days_above_35c", "ssp585", 2050, 16.6),
        ("wind_iris_max_speed", HISTORICAL, None, 24.4),
        ("wind_iris_max_speed", "ssp245", 2050, 25.6),
        ("heat_osc_days_wbgt_above", "ssp585", 2050, 58.0),
        ("water_wri_demand", "ssp585", 2050, 109),
        ("water_wri_stress", HISTORICAL, None, 0.03),
        ("water_wri_stress", "ssp126", 2030, 1.2),
    ],
)
def test_live_known_values_at_nyc(layer_id, scenario, year, value):
    window = hazard_grids.window(layer_id, scenario, year, *NYC)
    digits = len(str(value).split(".")[1]) if "." in str(value) else 0
    assert window.asset_value == pytest.approx(value, abs=10**-digits)


def test_live_subsidence_has_no_value_on_this_nyc_cell():
    """physrisk's own get_curves gives NaN here too: no data, never zero."""
    window = hazard_grids.window("subsidence_csm_rate", HISTORICAL, None, *NYC)
    assert window.asset_value is None
    assert window.value_range() is not None


@pytest.mark.parametrize(
    ("layer_id", "scenario", "year", "cell_km"),
    [
        ("heat_jupiter_days_above_35c", "ssp585", 2050, (21.1, 27.6)),
        ("heat_osc_days_wbgt_above", HISTORICAL, None, (21.1, 27.6)),
        ("wind_iris_max_speed", HISTORICAL, None, (8.4, 11.1)),
        ("water_wri_demand", HISTORICAL, None, (7.0, 9.2)),
        ("subsidence_csm_rate", HISTORICAL, None, (0.7, 0.9)),
    ],
)
def test_live_cell_sizes_near_nyc(layer_id, scenario, year, cell_km):
    window = hazard_grids.window(layer_id, scenario, year, *NYC)
    assert window.cell_km == pytest.approx(cell_km, abs=0.1)


def test_live_a_png_draws():
    png = hazard_grids.image("wind_iris_max_speed", "ssp245", 2050, *NYC, "dark")
    assert png.startswith(b"\x89PNG")
