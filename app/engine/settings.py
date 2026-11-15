"""Load .asset-risk.json written by the Terraform stack in infra/.

The JSON keys are a contract with infra/main.tf — change both sides together.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

ENV_VAR = "ASSET_RISK_CONFIG"
GEOLOCATE_ENV_VAR = "GEOLOCATE_CONFIG"
DATA_DIR_ENV_VAR = "ASSET_RISK_DATA_DIR"
FLOOD_ZONES_ENV_VAR = "FLOOD_ZONES_DB"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / ".asset-risk.json"
KEYS = (
    "scenarios",
    "years",
    "default_building_type",
    "physrisk_batch_size",
    "geolocate_workers",
    "geolocate_batch_size",
    "cluster_eps_km",
    "cluster_min_samples",
    "max_portfolio_rows",
    "max_upload_mb",
    "data_dir",
    "api_port",
    "geolocate_config",
    "flood_zones_db",
    "hazard_map_layers",
    "hazard_map_bucket",
    "fire_map_path",
    "wind_map_path",
    "fire_map_max_zoom",
    "wind_map_max_zoom",
    "hazard_map_alpha",
    "hazard_map_legend_stops",
    "hazard_map_array_cache",
    "hazard_map_tile_cache",
)
SCENARIOS = ("ssp126", "ssp245", "ssp370", "ssp585")
BUILDING_TYPES = ("Buildings/Commercial", "Buildings/Industrial", "Buildings/Residential")
# The years the app assesses. Asking physrisk for 2025 returned scores but no impacts, without an
# error. Present-day risk is the historical baseline, which always comes back.
YEARS = (2030, 2050, 2080)
# The hazard map layers, in the order the API lists them.
HAZARD_MAP_LAYERS = ("RiverineInundation", "CoastalInundation", "Fire", "Wind")
MAX_MAP_ZOOM = 10
MAX_LEGEND_STOPS = 33
# A layer's path names one array per scenario and year, so it needs both placeholders and nothing
# else that str.format would read.
_MAP_PATH = re.compile(r"[A-Za-z0-9_.\-/]*")
_BUCKET = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]*(/[A-Za-z0-9_.\-]+)*")
MAX_CLUSTER_EPS_KM = 1000
MIN_CLUSTER_SAMPLES = 2
_APPLY_HINT = "run `terraform -chdir=infra apply` to generate it"


class SettingsError(Exception):
    """The settings file is missing or malformed."""


@dataclass(frozen=True)
class Settings:
    scenarios: tuple[str, ...]
    years: tuple[int, ...]
    default_building_type: str
    physrisk_batch_size: int
    geolocate_workers: int
    geolocate_batch_size: int
    cluster_eps_km: float
    cluster_min_samples: int
    max_portfolio_rows: int
    max_upload_mb: float
    data_dir: Path
    api_port: int
    geolocate_config: Path
    # The FEMA flood zone database from script/build_flood_zones.py. None turns the lookup off.
    flood_zones_db: Path | None = None
    # The hazard map layers. The defaults are the code's, so a test can leave them out.
    hazard_map_layers: tuple[str, ...] = HAZARD_MAP_LAYERS
    hazard_map_bucket: str = "os-climate-physical-risk/hazard-indicators/hazard.zarr"
    fire_map_path: str = "fire/jupiter/v1/fire_probability_{scenario}_{year}"
    wind_map_path: str = "wind/iris/v1/max_speed_{scenario}_{year}"
    fire_map_max_zoom: int = 6
    wind_map_max_zoom: int = 7
    hazard_map_alpha: int = 200
    hazard_map_legend_stops: int = 9
    hazard_map_array_cache: int = 4
    hazard_map_tile_cache: int = 256


def settings_path(path: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the file location: explicit path, then $ASSET_RISK_CONFIG, then the repo root."""
    if path is not None:
        return Path(path)
    if env := os.environ.get(ENV_VAR):
        return Path(env)
    return DEFAULT_PATH


def load_settings(path: str | os.PathLike[str] | None = None) -> Settings:
    p = settings_path(path)
    try:
        raw = json.loads(p.read_text())
    except FileNotFoundError:
        raise SettingsError(f"Settings file not found: {p} — {_APPLY_HINT}") from None
    except json.JSONDecodeError as e:
        raise SettingsError(f"Settings file {p} is not valid JSON ({e}) — {_APPLY_HINT}") from None
    if not isinstance(raw, dict):
        raise SettingsError(f"Settings file {p} must contain a JSON object — {_APPLY_HINT}")

    missing = [k for k in KEYS if k not in raw]
    if missing:
        raise SettingsError(f"Settings file {p} is missing keys {missing} — {_APPLY_HINT}")

    def bad(key: str, expected: str) -> SettingsError:
        return SettingsError(f"{key} in {p} must be {expected}, got {raw[key]!r}")

    scenarios = raw["scenarios"]
    if not _distinct_list(scenarios) or not set(scenarios) <= set(SCENARIOS):
        raise bad("scenarios", f"a distinct, non-empty list from {SCENARIOS}")

    years = raw["years"]
    if not _distinct_list(years) or not all(_is_int(y) and y in YEARS for y in years):
        raise bad("years", f"a distinct, non-empty list from {YEARS}")

    if raw["default_building_type"] not in BUILDING_TYPES:
        raise bad("default_building_type", f"one of {BUILDING_TYPES}")

    for key in (
        "physrisk_batch_size",
        "geolocate_workers",
        "geolocate_batch_size",
        "max_portfolio_rows",
    ):
        if not _is_int(raw[key]) or raw[key] < 1:
            raise bad(key, "a whole number of at least 1")

    eps = raw["cluster_eps_km"]
    if not _is_number(eps) or not 0 < eps <= MAX_CLUSTER_EPS_KM:
        raise bad("cluster_eps_km", f"a number more than 0 and at most {MAX_CLUSTER_EPS_KM}")

    if not _is_int(raw["cluster_min_samples"]) or raw["cluster_min_samples"] < MIN_CLUSTER_SAMPLES:
        raise bad("cluster_min_samples", f"a whole number of at least {MIN_CLUSTER_SAMPLES}")

    upload = raw["max_upload_mb"]
    if not _is_number(upload) or upload <= 0:
        raise bad("max_upload_mb", "a positive number")

    for key in ("data_dir", "geolocate_config"):
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise bad(key, "a non-empty string")

    flood_zones_db = raw["flood_zones_db"]
    if flood_zones_db is not None and (
        not isinstance(flood_zones_db, str) or not flood_zones_db.strip()
    ):
        raise bad("flood_zones_db", "null or a non-empty string")
    # A container finds the database at its mount. An empty variable leaves the file's value.
    flood_zones_db = os.environ.get(FLOOD_ZONES_ENV_VAR) or flood_zones_db

    if not _is_int(raw["api_port"]) or not 1 <= raw["api_port"] <= 65535:
        raise bad("api_port", "a whole number from 1 to 65535")

    layers = raw["hazard_map_layers"]
    if (
        not isinstance(layers, list)
        or len(set(map(str, layers))) != len(layers)
        or not all(isinstance(v, str) and v in HAZARD_MAP_LAYERS for v in layers)
    ):
        raise bad("hazard_map_layers", f"a distinct list from {HAZARD_MAP_LAYERS}, or empty")

    bucket = raw["hazard_map_bucket"]
    if not isinstance(bucket, str) or not _BUCKET.fullmatch(bucket):
        raise bad("hazard_map_bucket", "a bucket and folder, like my-bucket/hazard.zarr, no s3://")

    for key in ("fire_map_path", "wind_map_path"):
        if not _is_map_path(raw[key]):
            raise bad(key, "a path with {scenario} and {year} once each")

    for key in ("fire_map_max_zoom", "wind_map_max_zoom"):
        if not _is_int(raw[key]) or not 0 <= raw[key] <= MAX_MAP_ZOOM:
            raise bad(key, f"a whole number from 0 to {MAX_MAP_ZOOM}")

    if not _is_int(raw["hazard_map_alpha"]) or not 1 <= raw["hazard_map_alpha"] <= 255:
        raise bad("hazard_map_alpha", "a whole number from 1 to 255")

    stops = raw["hazard_map_legend_stops"]
    if not _is_int(stops) or not 2 <= stops <= MAX_LEGEND_STOPS:
        raise bad("hazard_map_legend_stops", f"a whole number from 2 to {MAX_LEGEND_STOPS}")

    for key in ("hazard_map_array_cache", "hazard_map_tile_cache"):
        if not _is_int(raw[key]) or raw[key] < 1:
            raise bad(key, "a whole number of at least 1")

    return Settings(
        scenarios=tuple(scenarios),
        years=tuple(years),
        default_building_type=raw["default_building_type"],
        physrisk_batch_size=raw["physrisk_batch_size"],
        geolocate_workers=raw["geolocate_workers"],
        geolocate_batch_size=raw["geolocate_batch_size"],
        cluster_eps_km=float(eps),
        cluster_min_samples=raw["cluster_min_samples"],
        max_portfolio_rows=raw["max_portfolio_rows"],
        max_upload_mb=float(upload),
        # In a container, data lives on its volume wherever the settings put it on the host.
        data_dir=_from_root(os.environ.get(DATA_DIR_ENV_VAR) or raw["data_dir"]),
        api_port=raw["api_port"],
        # The path Terraform wrote is only valid on its own machine, so the container overrides it.
        geolocate_config=_from_root(os.environ.get(GEOLOCATE_ENV_VAR) or raw["geolocate_config"]),
        flood_zones_db=_from_root(flood_zones_db) if flood_zones_db else None,
        hazard_map_layers=tuple(layers),
        hazard_map_bucket=bucket,
        fire_map_path=raw["fire_map_path"],
        wind_map_path=raw["wind_map_path"],
        fire_map_max_zoom=raw["fire_map_max_zoom"],
        wind_map_max_zoom=raw["wind_map_max_zoom"],
        hazard_map_alpha=raw["hazard_map_alpha"],
        hazard_map_legend_stops=stops,
        hazard_map_array_cache=raw["hazard_map_array_cache"],
        hazard_map_tile_cache=raw["hazard_map_tile_cache"],
    )


def _is_map_path(value) -> bool:
    if not isinstance(value, str):
        return False
    rest = value.replace("{scenario}", "", 1).replace("{year}", "", 1)
    return (
        value.count("{scenario}") == 1
        and value.count("{year}") == 1
        and not value.startswith("/")
        and bool(rest)
        and _MAP_PATH.fullmatch(rest) is not None
    )


def _distinct_list(value) -> bool:
    if not isinstance(value, list) or not value:
        return False
    # Unhashable items can't be valid; the callers' value checks reject them.
    return all(isinstance(v, (str, int, float)) for v in value) and len(set(value)) == len(value)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _from_root(path: str) -> Path:
    """Paths in the file are relative to the repo root, not the working directory."""
    return ROOT / path
