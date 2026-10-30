import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import duckdb
import pytest

from engine.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "vendor" / "geolocate" / "tests" / "fixtures"


def _geolocate_fixtures():
    # Loaded by path: geolocate's tests aren't importable, and a bump should surface any change.
    spec = importlib.util.spec_from_file_location(
        "geolocate_make_buildings", FIXTURES / "make_buildings.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def coords_csv():
    """geolocate's own test input: id, lat, lon, note, with valid and invalid rows."""
    return FIXTURES / "coords.csv"


@pytest.fixture(scope="session")
def buildings_parquet(tmp_path_factory):
    """Overture-shaped buildings around central Madrid, read locally with no network."""
    path = tmp_path_factory.mktemp("overture") / "buildings.parquet"
    try:
        _geolocate_fixtures().write_buildings(str(path))
    except duckdb.IOException as e:  # spatial extension not installed and no network
        pytest.skip(f"DuckDB extensions unavailable: {e}")
    return path


@pytest.fixture
def settings(tmp_path):
    return Settings(
        scenarios=("ssp585",),
        years=(2050,),
        default_building_type="Buildings/Commercial",
        physrisk_batch_size=100,
        geolocate_workers=2,
        geolocate_batch_size=3,
        max_portfolio_rows=100,
        max_upload_mb=1.0,
        data_dir=tmp_path / "data",
        api_port=8000,
        geolocate_config=tmp_path / "missing.json",
    )


@pytest.fixture
def local_settings(settings, buildings_parquet, tmp_path):
    """Settings whose geolocate config reads the local parquet."""
    config = tmp_path / ".geolocate.json"
    config.write_text(
        json.dumps(
            {
                "overture_buildings_path": str(buildings_parquet),
                "s3_region": "us-west-2",
                "aws_access_key_id": "",
                "aws_secret_access_key": "",
                "aws_session_token": "",
                "search_radius_m": 100,
            }
        )
    )
    return replace(settings, geolocate_config=config)
