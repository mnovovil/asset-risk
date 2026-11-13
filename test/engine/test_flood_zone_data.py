"""The FEMA flood zone database build, on small synthetic GeoParquet files."""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import duckdb
import pytest

from engine.flood_zone_data import (
    CRS,
    FORMAT_VERSION,
    ZONES_FILE,
    FloodZoneDataError,
    build,
    connect,
    database_info,
    known_zones,
)

ROOT = Path(__file__).resolve().parents[2]
AS_OF = date(2026, 11, 13)
INSIDE = (-94.79, 29.29)  # inside both Galveston-like squares below
ELSEWHERE = (-90.07, 29.95)  # inside the X square only
# (FLD_AR_ID, FLD_ZONE, ZONE_SUBTY, WKT in lon/lat)
ROWS = [
    (
        "1",
        "VE",
        None,
        "POLYGON((-94.80 29.28, -94.78 29.28, -94.78 29.30, -94.80 29.30, -94.80 29.28))",
    ),
    (
        "2",
        "OPEN WATER",
        None,
        "POLYGON((-94.81 29.27, -94.77 29.27, -94.77 29.31, -94.81 29.31, -94.81 29.27))",
    ),
    (
        "3",
        "X",
        "AREA WITH REDUCED FLOOD RISK DUE TO LEVEE",
        "POLYGON((-90.10 29.90, -90.00 29.90, -90.00 30.00, -90.10 30.00, -90.10 29.90))",
    ),
    ("4", "AE", None, None),  # no geometry
    ("5", "AE", None, "POLYGON EMPTY"),
    ("6", None, None, "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"),  # no zone
]


@pytest.fixture
def con(flood_con):
    return flood_con


@pytest.fixture
def write_flood_source(write_flood_source):
    """The shared writer, with this module's rows by default."""

    def write(path, rows=ROWS, **kwargs):
        return write_flood_source(path, rows, **kwargs)

    return write


def zones_at(path, lon, lat):
    with connect(path, read_only=True) as db:
        rows = db.execute(
            "SELECT FLD_ZONE FROM flood_zones WHERE ST_Intersects(geom, ST_Point(?, ?)) "
            "ORDER BY FLD_ZONE",
            [lon, lat],
        ).fetchall()
    return [zone for (zone,) in rows]


def test_builds_an_indexed_database(con, tmp_path, write_flood_source):
    out = tmp_path / "fema" / "flood-zones.duckdb"
    report = build(write_flood_source(tmp_path / "source.parquet"), out, AS_OF)

    assert (report.polygons, report.skipped_no_geometry, report.skipped_no_zone) == (3, 2, 1)
    assert (report.source_crs, report.reprojected) == (CRS, False)
    assert zones_at(out, *INSIDE) == ["OPEN WATER", "VE"]
    assert zones_at(out, *ELSEWHERE) == ["X"]
    assert zones_at(out, -100.0, 40.0) == []
    with connect(out, read_only=True) as db:
        plan = db.execute(
            "EXPLAIN SELECT 1 FROM flood_zones "
            "WHERE ST_Intersects(geom, ST_MakeEnvelope(-95, 29, -94, 30))"
        ).fetchall()[0][1]
        assert "RTREE_INDEX_SCAN" in plan.upper().replace(" ", "_")
        values = db.execute("SELECT * FROM flood_zone_values ORDER BY FLD_ZONE").fetchall()
        assert values == [
            ("OPEN WATER", None, 1),
            ("VE", None, 1),
            ("X", "AREA WITH REDUCED FLOOD RISK DUE TO LEVEE", 1),
        ]
    assert not list(out.parent.glob(".*partial*"))


def test_records_what_it_was_built_from(con, tmp_path, write_flood_source):
    source = write_flood_source(tmp_path / "source.parquet")
    out = tmp_path / "flood-zones.duckdb"
    build(source, out, AS_OF)
    info = database_info(out)
    assert info["format_version"] == FORMAT_VERSION
    assert info["crs"] == CRS
    assert info["source_crs"] == CRS
    assert info["source_name"] == "source.parquet"
    assert info["source_bytes"] == source.stat().st_size
    assert (info["polygons"], info["source_rows"]) == (3, 6)
    assert info["as_of"] == AS_OF


@pytest.mark.parametrize("crs", ["EPSG:4269", "EPSG:3857"])
def test_reprojects_to_lon_lat(con, tmp_path, crs, write_flood_source):
    out = tmp_path / "flood-zones.duckdb"
    report = build(write_flood_source(tmp_path / "source.parquet", crs=crs), out, AS_OF)
    assert (report.source_crs, report.reprojected) == (crs, True)
    assert zones_at(out, *INSIDE) == ["OPEN WATER", "VE"]
    assert zones_at(out, *ELSEWHERE) == ["X"]
    assert database_info(out)["source_crs"] == crs


def test_wgs84_is_only_relabelled(con, tmp_path, write_flood_source):
    out = tmp_path / "flood-zones.duckdb"
    report = build(write_flood_source(tmp_path / "s.parquet", crs="EPSG:4326"), out, AS_OF)
    assert (report.source_crs, report.reprojected) == ("EPSG:4326", False)
    assert zones_at(out, *INSIDE) == ["OPEN WATER", "VE"]


def test_any_geometry_column_name(con, tmp_path, write_flood_source):
    out = tmp_path / "flood-zones.duckdb"
    build(write_flood_source(tmp_path / "s.parquet", column='my "geometry"'), out, AS_OF)
    assert zones_at(out, *ELSEWHERE) == ["X"]


def test_refuses_an_unknown_crs(con, tmp_path):
    # GeoParquet's "crs": null means the CRS is unknown, unlike a missing "crs", which is CRS84.
    path = tmp_path / "s.parquet"
    geo = {
        "version": "1.0.0",
        "primary_column": "geom",
        "columns": {"geom": {"encoding": "WKB", "geometry_types": ["Polygon"], "crs": None}},
    }
    con.execute(
        f"""
        COPY (
            SELECT '48167C' AS DFIRM_ID, '1' AS VERSION_ID, '1' AS FLD_AR_ID, 'X' AS FLD_ZONE,
                   NULL AS ZONE_SUBTY, 'F' AS SFHA_TF, 0.0 AS STATIC_BFE, NULL AS V_DATUM,
                   0.0 AS DEPTH, NULL AS LEN_UNIT, 0.0 AS VELOCITY, NULL AS VEL_UNIT,
                   ST_AsWKB(ST_GeomFromText('POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))')) AS geom
        ) TO '{path}' (FORMAT parquet, KV_METADATA {{geo: '{json.dumps(geo)}'}})
        """
    )
    with pytest.raises(FloodZoneDataError, match="doesn't say which CRS"):
        build(path, tmp_path / "out.duckdb", AS_OF)


def test_refuses_plain_parquet(con, tmp_path):
    path = tmp_path / "plain.parquet"
    con.execute(f"COPY (SELECT 1 AS FLD_ZONE) TO '{path}' (FORMAT parquet)")
    with pytest.raises(FloodZoneDataError, match="no GeoParquet"):
        build(path, tmp_path / "out.duckdb", AS_OF)


def test_refuses_missing_columns(con, tmp_path, write_flood_source):
    path = write_flood_source(tmp_path / "s.parquet", zone_column="ZONE")
    with pytest.raises(FloodZoneDataError, match="FLD_ZONE"):
        build(path, tmp_path / "out.duckdb", AS_OF)


def test_refuses_a_zone_the_lookup_does_not_describe(con, tmp_path, write_flood_source):
    rows = [*ROWS, ("7", "A7", None, "POLYGON((2 2, 3 2, 3 3, 2 3, 2 2))")]
    source = write_flood_source(tmp_path / "s.parquet", rows)
    out = tmp_path / "flood-zones.duckdb"
    out.write_text("the previous database")
    with pytest.raises(FloodZoneDataError, match=r"\['A7'\].*fema_zones.json"):
        build(source, out, AS_OF)
    # A failed build leaves the previous database alone and cleans up after itself.
    assert out.read_text() == "the previous database"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["flood-zones.duckdb", "s.parquet"]


def test_a_rebuild_replaces_the_database(con, tmp_path, write_flood_source):
    out = tmp_path / "flood-zones.duckdb"
    build(write_flood_source(tmp_path / "a.parquet"), out, AS_OF)
    build(write_flood_source(tmp_path / "b.parquet", ROWS[2:3]), out, date(2027, 1, 1))
    info = database_info(out)
    assert (info["source_name"], info["polygons"], info["as_of"]) == (
        "b.parquet",
        1,
        date(2027, 1, 1),
    )


def test_database_info_explains_an_unusable_file(con, tmp_path):
    with pytest.raises(FloodZoneDataError, match="No flood zone database"):
        database_info(tmp_path / "missing.duckdb")
    with pytest.raises(FloodZoneDataError, match="No flood zone database"):
        database_info(Path("/dev/null"))  # what Docker mounts when there's no database

    text = tmp_path / "text.duckdb"
    text.write_text("not a database")
    with pytest.raises(FloodZoneDataError, match="can't be opened"):
        database_info(text)

    other = tmp_path / "other.duckdb"
    duckdb.connect(str(other)).close()
    with pytest.raises(FloodZoneDataError, match="isn't a flood zone database"):
        database_info(other)


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("format_version", FORMAT_VERSION + 1, "rebuild it"),
        ("crs", "EPSG:4269", "expected OGC:CRS84"),
    ],
)
def test_database_info_refuses_another_shape(
    con, tmp_path, column, value, message, write_flood_source
):
    out = tmp_path / "flood-zones.duckdb"
    build(write_flood_source(tmp_path / "s.parquet"), out, AS_OF)
    with duckdb.connect(str(out)) as db:
        db.execute(f"UPDATE flood_zone_source SET {column} = ?", [value])
    with pytest.raises(FloodZoneDataError, match=message):
        database_info(out)


def test_the_lookup_table_is_consistent():
    zones = json.loads(ZONES_FILE.read_text())["zones"]
    keys = [zone["key"] for zone in zones]
    ranks = [zone["risk_rank"] for zone in zones]
    assert len(set(keys)) == len(keys)
    assert sorted(ranks) == list(range(1, len(zones) + 1))
    # Zone X is split by shading, and every other key is the FLD_ZONE itself.
    assert {z["key"] for z in zones if z["fld_zone"] == "X"} == {"X", "X_SHADED", "X_UNSHADED"}
    assert all(z["key"] == z["fld_zone"] for z in zones if z["fld_zone"] != "X")
    assert known_zones() >= {"A", "AE", "AH", "AO", "AR", "A99", "V", "VE", "X", "D"}


def test_script(con, tmp_path, write_flood_source):
    source = write_flood_source(tmp_path / "s.parquet", crs="EPSG:4269")
    out = tmp_path / "out" / "flood-zones.duckdb"
    script = ROOT / "script" / "build_flood_zones.py"

    def run(*args):
        return subprocess.run(
            [sys.executable, str(script), *args], capture_output=True, text=True, check=False
        )

    result = run(str(source), "--out", str(out), "--as-of", "2026-11-13")
    assert result.returncode == 0, result.stderr
    assert "Wrote 3 polygons" in result.stdout
    assert "reprojected to OGC:CRS84" in result.stdout
    assert "Skipped 2 rows with no geometry" in result.stdout
    assert "Skipped 1 rows with no FLD_ZONE" in result.stdout

    failed = run(str(tmp_path / "missing.parquet"), "--out", str(out), "--as-of", "2026-11-13")
    assert failed.returncode == 1
    assert failed.stderr.startswith("error:")
