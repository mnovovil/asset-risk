import json
import re
from pathlib import Path

import pytest

from engine.settings import (
    BUILDING_TYPES,
    KEYS,
    ROOT,
    SCENARIOS,
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
    "max_portfolio_rows": 5000,
    "max_upload_mb": 10,
    "data_dir": "data",
    "api_port": 8000,
    "geolocate_config": "/abs/vendor/geolocate/.geolocate.json",
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("ASSET_RISK_CONFIG", raising=False)
    monkeypatch.delenv("GEOLOCATE_CONFIG", raising=False)
    monkeypatch.delenv("ASSET_RISK_DATA_DIR", raising=False)


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
        ("years", [2101]),
        ("years", [2050.5]),
        ("years", [True]),
        ("default_building_type", "Buildings/Nonsense"),
        ("default_building_type", None),
        ("physrisk_batch_size", 0),
        ("physrisk_batch_size", 1.5),
        ("geolocate_workers", True),
        ("geolocate_batch_size", -1),
        ("max_portfolio_rows", "5000"),
        ("max_upload_mb", 0),
        ("max_upload_mb", True),
        ("data_dir", ""),
        ("data_dir", 3),
        ("geolocate_config", "  "),
        ("api_port", 0),
        ("api_port", 65536),
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


@pytest.mark.parametrize("value", [*SCENARIOS, *BUILDING_TYPES])
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
