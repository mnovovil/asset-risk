"""Read a finished run's results from its SQL views, for the API."""

from __future__ import annotations

import math
from collections import defaultdict

import duckdb

from engine.store import Run

_ASSET_COLUMNS = """
    row_num, asset_id, lat, lon, match_type, distance_m, building_id, name, class, subtype, height,
    num_floors, region, region_source, physrisk_type, physrisk_location, location_fallback,
    type_source, assessable, exclusion_reason
"""

# A missing row reads as 'unavailable' rather than hiding the asset.
_FLOOD_COLUMNS = """
    coalesce(f.fema_status, 'unavailable') AS fema_status, f.fema_zone, f.fema_zone_subtype,
    f.fema_zone_key, f.in_sfha,
    f.base_flood_elevation, f.base_flood_elevation_unit, f.base_flood_elevation_datum, f.fema_depth,
    f.fema_depth_unit, f.fema_dfirm_id, coalesce(f.fema_matches, 0) AS fema_matches,
    coalesce(f.fema_conflict, false) AS fema_conflict
"""
# What a run from before the FEMA lookup existed reads as.
_NO_FLOOD_ZONES = """(
    SELECT row_num, 'unavailable' AS fema_status, NULL::VARCHAR AS fema_zone,
           NULL::VARCHAR AS fema_zone_subtype, NULL::VARCHAR AS fema_zone_key,
           NULL::BOOLEAN AS in_sfha, NULL::DOUBLE AS base_flood_elevation,
           NULL::VARCHAR AS base_flood_elevation_unit, NULL::VARCHAR AS base_flood_elevation_datum,
           NULL::DOUBLE AS fema_depth, NULL::VARCHAR AS fema_depth_unit,
           NULL::VARCHAR AS fema_dfirm_id, 0 AS fema_matches, false AS fema_conflict
    FROM assets
)"""

_EXPORT = """
SELECT a.asset_id, a.lat, a.lon, a.match_type, a.distance_m, a.building_id, a.name, a.class,
       a.subtype, a.height, a.num_floors, a.region, a.physrisk_type, a.physrisk_location,
       a.location_fallback, a.type_source, a.assessable, a.exclusion_reason,
       coalesce(f.fema_status, 'unavailable') AS fema_status, f.fema_zone, f.fema_zone_subtype,
       f.in_sfha, f.base_flood_elevation, f.base_flood_elevation_unit,
       f.base_flood_elevation_datum, f.fema_depth, f.fema_depth_unit, f.fema_dfirm_id,
       coalesce(f.fema_matches, 0) AS fema_matches,
       coalesce(f.fema_conflict, false) AS fema_conflict,
       i.scenario, i.year, i.hazard, i.impact_type, i.aal, i.aal_std, s.score,
       s.label AS score_label
FROM assets a
LEFT JOIN {flood_zones} f USING (row_num)
LEFT JOIN impacts i USING (row_num)
LEFT JOIN scores s
    ON s.row_num = i.row_num AND s.hazard = i.hazard AND s.scenario = i.scenario
    AND s.year IS NOT DISTINCT FROM i.year
ORDER BY a.row_num, i.scenario, i.year NULLS FIRST, i.hazard, i.impact_type
"""


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> list[dict]:
    cursor = con.execute(sql, params or [])
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _has_table(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    return (
        con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]
        ).fetchone()[0]
        > 0
    )


def _flood_zones(con: duckdb.DuckDBPyConnection) -> str:
    """The relation to read FEMA flood zones from: the table, or 'unavailable' for an old run."""
    return "asset_flood_zones" if _has_table(con, "asset_flood_zones") else _NO_FLOOD_ZONES


def _asset_rows(con: duckdb.DuckDBPyConnection, extra: str = "", where: str = "", params=None):
    # Both pieces are constants from this module; values only ever go in params.
    return _rows(
        con,
        f"SELECT {_ASSET_COLUMNS}, {_FLOOD_COLUMNS}{extra} FROM assets "
        f"LEFT JOIN {_flood_zones(con)} f USING (row_num) {where} ORDER BY row_num",
        params,
    )


def summary(run: Run) -> dict:
    with run.connect() as con:
        result = _rows(con, "SELECT * FROM v_portfolio_summary")[0]
        result["exclusions"] = _rows(con, "SELECT * FROM v_exclusions ORDER BY reason")
        hazards = con.execute("SELECT hazard FROM v_shared_hazards ORDER BY hazard").fetchall()
        result["shared_hazards"] = [hazard for (hazard,) in hazards]
    return result


def assets(run: Run) -> list[dict]:
    """Every row of the portfolio, without footprints, which can be very large."""
    with run.connect() as con:
        return _asset_rows(con)


def asset(run: Run, row_num: int) -> dict | None:
    with run.connect() as con:
        rows = _asset_rows(con, ", geometry_wkt", "WHERE row_num = ?", [row_num])
        if not rows:
            return None
        result = rows[0]
        source = (
            con.execute("SELECT max(as_of) FROM flood_zone_source").fetchone()
            if _has_table(con, "flood_zone_source")
            else (None,)
        )
        result["fema_map_as_of"] = source[0]
        result["impacts"] = _rows(
            con,
            "SELECT scenario, year, hazard, impact_type, aal, aal_std, hazard_paths "
            "FROM v_asset_hazard_aal WHERE row_num = ? "
            "ORDER BY scenario, year NULLS FIRST, hazard, impact_type",
            [row_num],
        )
        result["scores"] = _rows(
            con,
            "SELECT scenario, year, hazard, score, label FROM v_asset_scores WHERE row_num = ? "
            "ORDER BY scenario, year, hazard",
            [row_num],
        )
    return result


def pair_exists(run: Run, scenario: str, year: int | None) -> bool:
    with run.connect() as con:
        return (
            con.execute(
                "SELECT count(*) FROM assessment_pairs "
                "WHERE scenario = ? AND year IS NOT DISTINCT FROM ?",
                [scenario, year],
            ).fetchone()[0]
            > 0
        )


def impacts(run: Run, scenario: str, year: int | None) -> list[dict]:
    with run.connect() as con:
        return _rows(
            con,
            "SELECT row_num, asset_id, lat, lon, hazard, impact_type, aal, aal_std "
            "FROM v_asset_hazard_aal WHERE scenario = ? AND year IS NOT DISTINCT FROM ? "
            "ORDER BY row_num, hazard, impact_type",
            [scenario, year],
        )


def totals(run: Run, scenario: str, year: int | None) -> list[dict]:
    with run.connect() as con:
        return _rows(
            con,
            "SELECT row_num, asset_id, total_aal, shared_aal, hazards FROM v_asset_totals "
            "WHERE scenario = ? AND year IS NOT DISTINCT FROM ? ORDER BY row_num",
            [scenario, year],
        )


def scores(run: Run, scenario: str, year: int | None) -> list[dict]:
    with run.connect() as con:
        return _rows(
            con,
            "SELECT row_num, asset_id, hazard, score, label FROM v_asset_scores "
            "WHERE scenario = ? AND year IS NOT DISTINCT FROM ? ORDER BY row_num, hazard",
            [scenario, year],
        )


def trajectory(run: Run) -> list[dict]:
    with run.connect() as con:
        return _rows(
            con, "SELECT * FROM v_portfolio_trajectory ORDER BY scenario, year NULLS FIRST"
        )


def coverage(run: Run) -> list[dict]:
    with run.connect() as con:
        return _rows(
            con, "SELECT * FROM v_hazard_coverage ORDER BY scenario, year NULLS FIRST, hazard"
        )


def clusters(run: Run) -> list[dict]:
    """The run's DBSCAN clusters with their members, centre and bounds.

    Runs made before clustering existed have no asset_clusters table, and read as having none.
    """
    with run.connect() as con:
        if not _has_table(con, "asset_clusters"):
            return []
        rows = con.execute(
            "SELECT c.cluster_id, a.row_num, a.lat, a.lon FROM asset_clusters c "
            "JOIN assets a USING (row_num) ORDER BY c.cluster_id, a.row_num"
        ).fetchall()
    members: dict[int, list[tuple[int, float, float]]] = defaultdict(list)
    for cluster_id, row_num, lat, lon in rows:
        members[cluster_id].append((row_num, lat, lon))
    return [_cluster(cluster_id, points) for cluster_id, points in members.items()]


def _cluster(cluster_id: int, points: list[tuple[int, float, float]]) -> dict:
    lats = [lat for _, lat, _ in points]
    lons = [lon for _, _, lon in points]
    # A circular mean, so a cluster across the antimeridian isn't centred near 0°.
    lon = math.degrees(
        math.atan2(
            sum(math.sin(math.radians(x)) for x in lons),
            sum(math.cos(math.radians(x)) for x in lons),
        )
    )
    west, east = min(lons), max(lons)
    if east - west > 180:  # across the antimeridian: east goes past 180, as the map expects
        west = min(x for x in lons if x >= 0)
        east = max(x for x in lons if x < 0) + 360
    return {
        "cluster_id": cluster_id,
        "assets": len(points),
        "row_nums": [row_num for row_num, _, _ in points],
        "lat": sum(lats) / len(lats),
        "lon": lon,
        "bounds": [west, min(lats), east, max(lats)],
    }


def export_rows(run: Run) -> tuple[list[str], list[tuple]]:
    """One row per asset, scenario, year and hazard; an asset with no results appears once."""
    with run.connect() as con:
        cursor = con.execute(_EXPORT.format(flood_zones=_flood_zones(con)))
        return [d[0] for d in cursor.description], cursor.fetchall()
