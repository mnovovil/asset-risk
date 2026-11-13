import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import duckdb
import pytest

from engine.flood_zone_data import connect as connect_flood_zones
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
        cluster_eps_km=50.0,
        cluster_min_samples=5,
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


@pytest.fixture(scope="session")
def flood_con():
    """A DuckDB connection with spatial loaded, for writing and reading flood zone fixtures."""
    try:
        connection = connect_flood_zones()
    except duckdb.IOException as e:  # spatial extension not installed and no network
        pytest.skip(f"DuckDB extensions unavailable: {e}")
    yield connection
    connection.close()


FLOOD_ZONE_DEFAULTS = {
    "subtype": None,
    "sfha": "T",
    "bfe": -9999.0,
    "depth": -9999.0,
    "datum": None,
    "unit": "Feet",
    "dfirm": "48167C",
}


@pytest.fixture
def write_flood_source(flood_con):
    """Write a GeoParquet shaped like FEMA's S_FLD_HAZ_AR and return its path.

    Each row is (FLD_AR_ID, FLD_ZONE, ZONE_SUBTY, WKT) or a dict with id, zone and wkt, and
    optionally subtype, sfha, bfe, depth, datum, unit and dfirm. WKT is in lon/lat; crs is the CRS
    to store the shapes in.
    """

    def write(path, rows, crs=None, column="geom", zone_column="FLD_ZONE"):
        con = flood_con
        records = [
            FLOOD_ZONE_DEFAULTS
            | (
                dict(zip(("id", "zone", "subtype", "wkt"), row, strict=True))
                if isinstance(row, tuple)
                else row
            )
            for row in rows
        ]
        con.execute(
            "CREATE OR REPLACE TEMP TABLE flood_rows (id VARCHAR, zone VARCHAR, subtype VARCHAR, "
            "wkt VARCHAR, sfha VARCHAR, bfe DOUBLE, depth DOUBLE, datum VARCHAR, unit VARCHAR, "
            "dfirm VARCHAR)"
        )
        con.executemany(
            "INSERT INTO flood_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                [
                    r[k]
                    for k in (
                        "id",
                        "zone",
                        "subtype",
                        "wkt",
                        "sfha",
                        "bfe",
                        "depth",
                        "datum",
                        "unit",
                        "dfirm",
                    )
                ]
                for r in records
            ],
        )
        geometry = "ST_GeomFromText(wkt)"
        if crs is not None:
            geometry = f"ST_SetCRS(ST_Transform({geometry}, 'OGC:CRS84', ?, always_xy := true), ?)"
        quoted = '"' + column.replace('"', '""') + '"'
        # Test-only SQL: the path comes from tmp_path, and COPY can't take it as a parameter.
        con.execute(
            f"""
            COPY (
                SELECT dfirm AS DFIRM_ID, '1.1.1.0' AS VERSION_ID, id AS FLD_AR_ID,
                       zone AS {zone_column}, subtype AS ZONE_SUBTY, sfha AS SFHA_TF,
                       bfe AS STATIC_BFE, datum AS V_DATUM, depth AS DEPTH, unit AS LEN_UNIT,
                       -9999.0 AS VELOCITY, 'Feet / Second' AS VEL_UNIT, {geometry} AS {quoted}
                FROM flood_rows
            ) TO '{path}' (FORMAT parquet)
            """,
            [] if crs is None else [crs, crs],
        )
        return path

    return write
