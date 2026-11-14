import json
import re
from pathlib import Path

import pytest

from engine.settings import (
    BUILDING_TYPES,
    HAZARD_MAP_LAYERS,
    KEYS,
    MAX_CLUSTER_EPS_KM,
    MIN_CLUSTER_SAMPLES,
    ROOT,
    SCENARIOS,
    YEARS,
    Settings,
    SettingsError,
    load_settings,
    settings_path,
)

INFRA = Path(__file__).resolve().parents[2] / "infra"
VALID = {
    "scenarios": ["ssp245", "ssp585"],
    "years": [2030, 2050, 2080],
    "default_building_type": "Buildings/Commercial",
    "physrisk_batch_size": 100,
    "geolocate_workers": 16,
    "geolocate_batch_size": 20,
    "cluster_eps_km": 50,
    "cluster_min_samples": 5,
    "max_portfolio_rows": 5000,
    "max_upload_mb": 10,
    "data_dir": "data",
    "api_port": 8000,
    "geolocate_config": "/abs/vendor/geolocate/.geolocate.json",
    "flood_zones_db": "data/fema/flood-zones.duckdb",
    "hazard_map_layers": ["RiverineInundation", "CoastalInundation", "Fire", "Wind"],
    "hazard_map_bucket": "os-climate-physical-risk/hazard-indicators/hazard.zarr",
    "fire_map_path": "fire/jupiter/v1/fire_probability_{scenario}_{year}",
    "wind_map_path": "wind/iris/v1/max_speed_{scenario}_{year}",
    "fire_map_max_zoom": 6,
    "wind_map_max_zoom": 7,
    "hazard_map_alpha": 200,
    "hazard_map_legend_stops": 9,
    "hazard_map_array_cache": 4,
    "hazard_map_tile_cache": 256,
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("ASSET_RISK_CONFIG", raising=False)
    monkeypatch.delenv("GEOLOCATE_CONFIG", raising=False)
    monkeypatch.delenv("ASSET_RISK_DATA_DIR", raising=False)
    monkeypatch.delenv("FLOOD_ZONES_DB", raising=False)


def write(tmp_path, **overrides):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(VALID | overrides))
    return path


def test_loads_valid_settings(tmp_path):
    s = load_settings(write(tmp_path))
    assert s.scenarios == ("ssp245", "ssp585")
    assert s.years == (2030, 2050, 2080)
    assert s.max_upload_mb == 10.0
    assert s.data_dir == ROOT / "data"
    assert s.geolocate_config == Path("/abs/vendor/geolocate/.geolocate.json")
    assert s.flood_zones_db == ROOT / "data/fema/flood-zones.duckdb"


def test_flood_zones_can_be_turned_off(tmp_path):
    assert load_settings(write(tmp_path, flood_zones_db=None)).flood_zones_db is None


def test_flood_zones_env_overrides_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOOD_ZONES_DB", "/fema/flood-zones.duckdb")
    assert load_settings(write(tmp_path)).flood_zones_db == Path("/fema/flood-zones.duckdb")
    # start.sh sets it empty when the setting is null, which keeps the lookup off.
    monkeypatch.setenv("FLOOD_ZONES_DB", "")
    assert load_settings(write(tmp_path, flood_zones_db=None)).flood_zones_db is None


def test_absolute_data_dir_is_kept(tmp_path):
    assert load_settings(write(tmp_path, data_dir="/var/runs")).data_dir == Path("/var/runs")


def test_resolution_order(tmp_path, monkeypatch):
    assert settings_path() == ROOT / ".asset-risk.json"
    monkeypatch.setenv("ASSET_RISK_CONFIG", str(tmp_path / "env.json"))
    assert settings_path() == tmp_path / "env.json"
    assert settings_path(tmp_path / "arg.json") == tmp_path / "arg.json"


def test_geolocate_env_overrides_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOLOCATE_CONFIG", "/config/.geolocate.json")
    s = load_settings(write(tmp_path))
    assert s.geolocate_config == Path("/config/.geolocate.json")


def test_data_dir_env_overrides_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSET_RISK_DATA_DIR", "/data")
    assert load_settings(write(tmp_path)).data_dir == Path("/data")


def test_missing_file(tmp_path):
    with pytest.raises(SettingsError, match="not found.*terraform"):
        load_settings(tmp_path / "nope.json")


@pytest.mark.parametrize("content", ["{not json", "[1, 2]"])
def test_malformed_file(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_text(content)
    with pytest.raises(SettingsError, match="terraform"):
        load_settings(path)


@pytest.mark.parametrize("key", KEYS)
def test_missing_key(tmp_path, key):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({k: v for k, v in VALID.items() if k != key}))
    with pytest.raises(SettingsError, match=key):
        load_settings(path)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("scenarios", []),
        ("scenarios", "ssp245"),
        ("scenarios", ["ssp245", "ssp245"]),
        ("scenarios", ["rcp8p5"]),
        ("scenarios", [["ssp245"]]),
        ("years", []),
        ("years", [2050, 2050]),
        ("years", [1999]),
        ("years", [2024]),
        ("years", [2025]),
        ("years", [2040]),
        ("years", [2100]),
        ("years", [2101]),
        ("years", [2050.5]),
        ("years", [True]),
        ("default_building_type", "Buildings/Nonsense"),
        ("default_building_type", None),
        ("physrisk_batch_size", 0),
        ("physrisk_batch_size", 1.5),
        ("geolocate_workers", True),
        ("geolocate_batch_size", -1),
        ("cluster_eps_km", 0),
        ("cluster_eps_km", -5),
        ("cluster_eps_km", 1001),
        ("cluster_eps_km", True),
        ("cluster_eps_km", "50"),
        ("cluster_min_samples", 1),
        ("cluster_min_samples", 2.5),
        ("cluster_min_samples", False),
        ("max_portfolio_rows", "5000"),
        ("max_upload_mb", 0),
        ("max_upload_mb", True),
        ("data_dir", ""),
        ("data_dir", 3),
        ("geolocate_config", "  "),
        ("flood_zones_db", ""),
        ("flood_zones_db", "  "),
        ("flood_zones_db", 3),
        ("flood_zones_db", False),
        ("flood_zones_db", ["data/fema/flood-zones.duckdb"]),
        ("api_port", 0),
        ("api_port", 65536),
        ("hazard_map_layers", "Fire"),
        ("hazard_map_layers", ["Fire", "Fire"]),
        ("hazard_map_layers", ["Hail"]),
        ("hazard_map_layers", [1]),
        ("hazard_map_bucket", ""),
        ("hazard_map_bucket", "s3://os-climate-physical-risk"),
        ("hazard_map_bucket", "bucket/"),
        ("hazard_map_bucket", "/bucket"),
        ("hazard_map_bucket", 3),
        ("fire_map_path", "fire/jupiter/v1/fire_probability"),
        ("fire_map_path", "fire/{scenario}"),
        ("fire_map_path", "fire/{year}"),
        ("wind_map_path", "wind/{scenario}_{year}_{year}"),
        ("wind_map_path", "wind/{scenario}_{year}_{other}"),
        ("wind_map_path", "/wind/{scenario}_{year}"),
        ("wind_map_path", "{scenario}{year}"),
        ("wind_map_path", None),
        ("fire_map_max_zoom", -1),
        ("fire_map_max_zoom", 11),
        ("wind_map_max_zoom", 7.5),
        ("wind_map_max_zoom", True),
        ("hazard_map_alpha", 0),
        ("hazard_map_alpha", 256),
        ("hazard_map_legend_stops", 1),
        ("hazard_map_legend_stops", 34),
        ("hazard_map_array_cache", 0),
        ("hazard_map_tile_cache", "256"),
    ],
)
def test_invalid_values(tmp_path, key, value):
    with pytest.raises(SettingsError, match=key):
        load_settings(write(tmp_path, **{key: value}))


def test_repr_never_shows_credentials(tmp_path):
    # Credentials belong to .geolocate.json only, even if one is added here by mistake.
    settings = load_settings(write(tmp_path, aws_secret_access_key="hunter2"))
    assert "hunter2" not in repr(settings)


def test_keys_match_terraform():
    block = re.search(r"jsonencode\(\{(.*?)\}\)", (INFRA / "main.tf").read_text(), re.DOTALL)
    assert set(re.findall(r"^\s*(\w+)\s*=", block.group(1), re.MULTILINE)) == set(KEYS)


@pytest.mark.parametrize("value", [*SCENARIOS, *BUILDING_TYPES, *HAZARD_MAP_LAYERS])
def test_allowed_values_match_terraform(value):
    assert f'"{value}"' in (INFRA / "variables.tf").read_text()


def test_every_key_has_a_terraform_variable():
    text = (INFRA / "variables.tf").read_text()
    for key in set(KEYS) - {"geolocate_config"}:  # comes from the geolocate module's output
        assert f'variable "{key}"' in text


def test_terraform_default_building_type_is_allowed():
    text = (INFRA / "variables.tf").read_text()
    default = re.search(r'variable "default_building_type".*?default\s*=\s*"(.+?)"', text, re.S)
    assert default.group(1) in BUILDING_TYPES


def test_terraform_flood_zones_default_matches_the_build_script():
    text = (INFRA / "variables.tf").read_text()
    default = re.search(r'variable "flood_zones_db".*?default\s*=\s*"(.+?)"', text, re.S)
    assert default.group(1) == "data/fema/flood-zones.duckdb"
    script = (ROOT / "script" / "build_flood_zones.py").read_text()
    assert 'ROOT / "data" / "fema" / "flood-zones.duckdb"' in script


def test_cluster_limits_match_terraform():
    text = (INFRA / "variables.tf").read_text()
    assert f"var.cluster_eps_km <= {MAX_CLUSTER_EPS_KM}" in text
    assert f"var.cluster_min_samples >= {MIN_CLUSTER_SAMPLES}" in text


def test_a_subset_of_the_years_is_accepted(tmp_path):
    assert load_settings(write(tmp_path, years=[2050])).years == (2050,)


def test_years_match_terraform():
    text = (INFRA / "variables.tf").read_text()
    assert f"contains([{', '.join(map(str, YEARS))}], y)" in text


def test_hazard_maps_can_be_turned_off(tmp_path):
    assert load_settings(write(tmp_path, hazard_map_layers=[])).hazard_map_layers == ()


def test_hazard_map_settings_are_loaded(tmp_path):
    settings = load_settings(
        write(tmp_path, hazard_map_layers=["Wind"], wind_map_max_zoom=5, hazard_map_alpha=150)
    )
    assert settings.hazard_map_layers == ("Wind",)
    assert (settings.wind_map_max_zoom, settings.hazard_map_alpha) == (5, 150)


def _terraform_default(name: str) -> str:
    text = (INFRA / "variables.tf").read_text()
    return re.search(rf'variable "{name}".*?default\s*=\s*(.+?)\n', text, re.S).group(1)


def test_hazard_map_defaults_match_terraform_and_the_code():
    """The Terraform defaults, the Settings defaults and VALID all reproduce today's maps."""
    defaults = Settings.__dataclass_fields__
    for key in [k for k in KEYS if k.startswith(("hazard_map", "fire_map", "wind_map"))]:
        value = json.loads(_terraform_default(key))
        code = defaults[key].default
        assert value == (list(code) if isinstance(code, tuple) else code), key
        assert VALID[key] == value, key


def test_hazard_map_defaults_match_the_layers():
    from engine import fire_map, grid_layer, wind_map

    defaults = Settings.__dataclass_fields__
    assert defaults["fire_map_path"].default == fire_map.FIRE_PATH
    assert defaults["wind_map_path"].default == wind_map.WIND_PATH
    assert defaults["fire_map_max_zoom"].default == fire_map.MAX_ZOOM
    assert defaults["wind_map_max_zoom"].default == wind_map.MAX_ZOOM
    assert defaults["hazard_map_bucket"].default == grid_layer.BUCKET_ROOT
    assert defaults["hazard_map_alpha"].default == fire_map.ALPHA
    assert defaults["hazard_map_legend_stops"].default == fire_map.LEGEND_STOPS
    assert defaults["hazard_map_array_cache"].default == fire_map.CACHE_ARRAYS
    assert defaults["hazard_map_tile_cache"].default == fire_map.CACHE_TILES
