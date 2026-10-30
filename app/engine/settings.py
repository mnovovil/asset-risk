"""Load .asset-risk.json written by the Terraform stack in infra/.

The JSON keys are a contract with infra/main.tf — change both sides together.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

ENV_VAR = "ASSET_RISK_CONFIG"
GEOLOCATE_ENV_VAR = "GEOLOCATE_CONFIG"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / ".asset-risk.json"
KEYS = (
    "scenarios",
    "years",
    "default_building_type",
    "physrisk_batch_size",
    "geolocate_workers",
    "geolocate_batch_size",
    "max_portfolio_rows",
    "max_upload_mb",
    "data_dir",
    "api_port",
    "geolocate_config",
)
SCENARIOS = ("ssp126", "ssp245", "ssp370", "ssp585")
BUILDING_TYPES = ("Buildings/Commercial", "Buildings/Industrial", "Buildings/Residential")
MIN_YEAR, MAX_YEAR = 2020, 2100
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
    max_portfolio_rows: int
    max_upload_mb: float
    data_dir: Path
    api_port: int
    geolocate_config: Path


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
    if not _distinct_list(years) or not all(
        _is_int(y) and MIN_YEAR <= y <= MAX_YEAR for y in years
    ):
        raise bad("years", f"a distinct, non-empty list of years from {MIN_YEAR} to {MAX_YEAR}")

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

    upload = raw["max_upload_mb"]
    if isinstance(upload, bool) or not isinstance(upload, (int, float)) or upload <= 0:
        raise bad("max_upload_mb", "a positive number")

    for key in ("data_dir", "geolocate_config"):
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise bad(key, "a non-empty string")

    if not _is_int(raw["api_port"]) or not 1 <= raw["api_port"] <= 65535:
        raise bad("api_port", "a whole number from 1 to 65535")

    return Settings(
        scenarios=tuple(scenarios),
        years=tuple(years),
        default_building_type=raw["default_building_type"],
        physrisk_batch_size=raw["physrisk_batch_size"],
        geolocate_workers=raw["geolocate_workers"],
        geolocate_batch_size=raw["geolocate_batch_size"],
        max_portfolio_rows=raw["max_portfolio_rows"],
        max_upload_mb=float(upload),
        data_dir=_from_root(raw["data_dir"]),
        api_port=raw["api_port"],
        # The path Terraform wrote is only valid on its own machine, so the container overrides it.
        geolocate_config=_from_root(os.environ.get(GEOLOCATE_ENV_VAR) or raw["geolocate_config"]),
    )


def _distinct_list(value) -> bool:
    if not isinstance(value, list) or not value:
        return False
    # Unhashable items can't be valid; the callers' value checks reject them.
    return all(isinstance(v, (str, int, float)) for v in value) and len(set(value)) == len(value)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _from_root(path: str) -> Path:
    """Paths in the file are relative to the repo root, not the working directory."""
    return ROOT / path
