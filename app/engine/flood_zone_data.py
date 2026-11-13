"""Build and check the FEMA flood zone database that runs look points up in.

FEMA's flood hazard GeoParquet has no bbox column and no geometry statistics, so DuckDB can't skip
any of it: every lookup would read the whole national file. build() copies it once into a DuckDB
file with an R-tree on the polygons, which lookups use through a constant envelope filter.

The database is a contract with the lookup stage: table flood_zones (the kept NFHL columns and geom
in OGC:CRS84), flood_zone_values (polygons per zone and subtype, for auditing) and flood_zone_source
(one row saying what it was built from). FORMAT_VERSION changes whenever that shape does.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

import duckdb

ENGINE_DIR = Path(__file__).parent
SQL_DIR = ENGINE_DIR / "sql"
ZONES_FILE = ENGINE_DIR / "data" / "fema_zones.json"

FORMAT_VERSION = 1
CRS = "OGC:CRS84"
# GeoParquet stores coordinates as (x, y) = (lon, lat) whatever the CRS's axis order, so these need
# only their label changed.
LONLAT_CRSES = frozenset({"OGC:CRS84", "EPSG:4326"})
REQUIRED_COLUMNS = (
    "DFIRM_ID",
    "VERSION_ID",
    "FLD_AR_ID",
    "FLD_ZONE",
    "ZONE_SUBTY",
    "SFHA_TF",
    "STATIC_BFE",
    "V_DATUM",
    "DEPTH",
    "LEN_UNIT",
    "VELOCITY",
    "VEL_UNIT",
)
_TYPED_GEOMETRY = re.compile(r"GEOMETRY\('(.+)'\)")


class FloodZoneDataError(Exception):
    """The source or the database can't be used."""


@dataclass(frozen=True)
class Source:
    geometry_column: str
    crs: str


@dataclass(frozen=True)
class BuildReport:
    polygons: int
    skipped_no_geometry: int
    skipped_no_zone: int
    source_crs: str
    reprojected: bool


@cache
def known_zones() -> frozenset[str]:
    """The FLD_ZONE values fema_zones.json describes."""
    zones = json.loads(ZONES_FILE.read_text())["zones"]
    return frozenset(zone["fld_zone"] for zone in zones)


def connect(path: str | os.PathLike[str] = ":memory:", **kwargs) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(path), **kwargs)
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")
    con.execute("SET geometry_always_xy = true")
    return con


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def inspect_source(con: duckdb.DuckDBPyConnection, source: Path) -> Source:
    """Find the GeoParquet's geometry column and CRS, or say why it can't be used."""
    if not source.is_file():
        raise FloodZoneDataError(f"No file at {source}")
    rows = con.execute(
        "SELECT decode(value) FROM parquet_kv_metadata(?) WHERE decode(key) = 'geo'", [str(source)]
    ).fetchall()
    if not rows:
        raise FloodZoneDataError(f"{source.name} has no GeoParquet 'geo' metadata")
    column = json.loads(rows[0][0]).get("primary_column")
    described = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(source)]).fetchall()
    types = {name: column_type for name, column_type, *_ in described}

    missing = [name for name in REQUIRED_COLUMNS if name not in types]
    if missing:
        raise FloodZoneDataError(f"{source.name} is missing columns {missing}")
    if column not in types or not types[column].startswith("GEOMETRY"):
        raise FloodZoneDataError(f"{source.name} has no geometry column {column!r}")
    # DuckDB reads the GeoParquet CRS into the column's type. A missing "crs" means OGC:CRS84 by
    # the GeoParquet spec, and an explicit null (unknown) leaves the type without one.
    typed = _TYPED_GEOMETRY.fullmatch(types[column])
    if typed is None:
        raise FloodZoneDataError(f"{source.name} doesn't say which CRS {column!r} is in")
    return Source(column, typed.group(1))


def build(source: Path, out: Path, as_of: date) -> BuildReport:
    """Write the database to out, replacing it only once the new one is complete."""
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(f".{out.name}.partial")
    for leftover in (partial, partial.with_name(partial.name + ".wal")):
        leftover.unlink(missing_ok=True)

    con = connect(partial)
    try:
        report = _build(con, source, as_of)
        con.execute("CHECKPOINT")
    except BaseException:
        con.close()
        partial.unlink(missing_ok=True)
        raise
    con.close()
    os.replace(partial, out)
    return report


def _build(con: duckdb.DuckDBPyConnection, source: Path, as_of: date) -> BuildReport:
    found = inspect_source(con, source)
    # A view can't take a prepared parameter, so the path goes through a variable. The column name
    # comes from the file's metadata and can only be an identifier, so it's quoted as one.
    con.execute("SET VARIABLE flood_zone_source_path = ?", [str(source)])
    con.execute(
        "CREATE TEMP VIEW flood_zone_source_rows AS "
        f"SELECT * RENAME ({_quote(found.geometry_column)} AS geom) "
        "FROM read_parquet(getvariable('flood_zone_source_path'))"
    )
    total, no_geometry, no_zone = con.execute(
        "SELECT count(*), "
        "count(*) FILTER (WHERE geom IS NULL OR ST_IsEmpty(geom)), "
        "count(*) FILTER (WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom) AND FLD_ZONE IS NULL) "
        "FROM flood_zone_source_rows"
    ).fetchone()
    zones = {
        zone
        for (zone,) in con.execute(
            "SELECT DISTINCT FLD_ZONE FROM flood_zone_source_rows WHERE FLD_ZONE IS NOT NULL"
        ).fetchall()
    }
    unknown = sorted(zones - known_zones())
    if unknown:
        raise FloodZoneDataError(
            f"{source.name} has flood zones {unknown} that {ZONES_FILE.name} doesn't describe. "
            "Add them there first."
        )

    reproject = found.crs not in LONLAT_CRSES
    con.execute(
        (SQL_DIR / "build_flood_zones.sql").read_text(),
        {"reproject": reproject, "source_crs": found.crs},
    )
    con.execute("CREATE INDEX flood_zones_geom ON flood_zones USING RTREE (geom)")
    con.execute(
        "CREATE TABLE flood_zone_values AS "
        "SELECT FLD_ZONE, ZONE_SUBTY, count(*) AS polygons FROM flood_zones GROUP BY ALL"
    )
    polygons = con.execute("SELECT count(*) FROM flood_zones").fetchone()[0]
    con.execute(
        """
        CREATE TABLE flood_zone_source AS
        SELECT ?::INTEGER AS format_version, ?::VARCHAR AS source_name, ?::BIGINT AS source_bytes,
               ?::VARCHAR AS source_crs, ?::VARCHAR AS crs, ?::BIGINT AS polygons,
               ?::BIGINT AS source_rows, ?::DATE AS as_of, current_timestamp AS built_at
        """,
        [
            FORMAT_VERSION,
            source.name,
            source.stat().st_size,
            found.crs,
            CRS,
            polygons,
            total,
            as_of,
        ],
    )
    return BuildReport(polygons, no_geometry, no_zone, found.crs, reproject)


def database_info(path: Path) -> dict:
    """What the database was built from. Raises if it isn't one this code can read."""
    if not path.is_file():
        raise FloodZoneDataError(f"No flood zone database at {path}")
    try:
        con = connect(path, read_only=True)
    except duckdb.Error as e:
        raise FloodZoneDataError(f"{path.name} can't be opened: {e}") from None
    try:
        cursor = con.execute("SELECT * FROM flood_zone_source")
        names = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
    except duckdb.CatalogException:
        raise FloodZoneDataError(f"{path.name} isn't a flood zone database") from None
    finally:
        con.close()
    if len(rows) != 1:
        raise FloodZoneDataError(f"{path.name} has {len(rows)} source rows, expected 1")
    info = dict(zip(names, rows[0], strict=True))
    if info["format_version"] != FORMAT_VERSION:
        raise FloodZoneDataError(
            f"{path.name} is format {info['format_version']}, expected {FORMAT_VERSION}: "
            "rebuild it with script/build_flood_zones.py"
        )
    if info["crs"] != CRS:
        raise FloodZoneDataError(f"{path.name} is in {info['crs']}, expected {CRS}")
    return info
