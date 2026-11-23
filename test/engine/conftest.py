import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import duckdb
import pytest

from engine.flood_zone_data import connect as connect_flood_zones
from engine.settings import Settings
from engine.store import create_run, save_values

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


@pytest.fixture
def make_run(tmp_path):
    """Build a run database from rows, for tests of the views and what reads them.

    assets: (row_num, asset_id, match_type, physrisk_type, type_source, location_fallback,
    assessable, exclusion_reason), as made by asset_row. impacts: (row_num, hazard, scenario, year,
    aal), all of impact type damage. pairs: (scenario, year). failures: (row_num, scenario, year).
    values: one (value, status) per asset, in row_num order, to fill asset_values.
    """

    def make(assets, impacts=(), pairs=(), failures=(), values=None, currency=None):
        run = create_run(tmp_path, len(assets))
        if values is not None:
            save_values(run, [v for v, _ in values], [s for _, s in values], currency)
        with run.connect() as con:
            statements = (
                (
                    "INSERT INTO assets (row_num, asset_id, match_type, physrisk_type, "
                    "type_source, location_fallback, assessable, exclusion_reason) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    assets,
                ),
                (
                    "INSERT INTO impacts (row_num, hazard, impact_type, scenario, year, aal) "
                    "VALUES (?, ?, 'damage', ?, ?, ?)",
                    impacts,
                ),
                ("INSERT INTO assessment_pairs VALUES (?, ?)", pairs),
                ("INSERT INTO assess_failures VALUES (?, ?, ?, 'boom')", failures),
            )
            for sql, rows in statements:
                if rows:
                    con.executemany(sql, rows)
        return run

    return make


@pytest.fixture
def asset_row():
    """One assets row for make_run, assessable by default, with asset_id a<row_num>."""

    def row(
        row_num, assessable=True, match="intersects", source="class", fallback=False, reason=None
    ):
        return (
            row_num,
            f"a{row_num}",
            match,
            "Buildings/Commercial" if assessable else None,
            source if assessable else None,
            fallback if assessable else None,
            assessable,
            reason,
        )

    return row


@pytest.fixture
def make_run_from_before_values():
    """Drop a run's value tables and put back the views a run made before them has."""

    def make_old(run):
        old_views = (ROOT / "test" / "engine" / "fixtures" / "views_before_values.sql").read_text()
        with run.connect() as con:
            views = con.execute(
                "SELECT view_name FROM duckdb_views() WHERE NOT internal AND database_name = "
                "current_database()"
            ).fetchall()
            for (name,) in views:
                con.execute(f'DROP VIEW IF EXISTS "{name}" CASCADE')  # names from the catalogue
            con.execute("DROP TABLE asset_values")
            con.execute("DROP TABLE portfolio_values")
            con.execute(old_views)
        return run

    return make_old


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
