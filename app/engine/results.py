"""Read a finished run's results from its SQL views, for the API."""

from __future__ import annotations

import duckdb

from engine.store import Run

_ASSET_COLUMNS = """
    row_num, asset_id, lat, lon, match_type, distance_m, building_id, name, class, subtype, height,
    num_floors, region, region_source, physrisk_type, physrisk_location, location_fallback,
    type_source, assessable, exclusion_reason
"""

_EXPORT = """
SELECT a.asset_id, a.lat, a.lon, a.match_type, a.distance_m, a.building_id, a.name, a.class,
       a.subtype, a.height, a.num_floors, a.region, a.physrisk_type, a.physrisk_location,
       a.location_fallback, a.type_source, a.assessable, a.exclusion_reason,
       i.scenario, i.year, i.hazard, i.impact_type, i.aal, i.aal_std, s.score,
       s.label AS score_label
FROM assets a
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
        return _rows(con, f"SELECT {_ASSET_COLUMNS} FROM assets ORDER BY row_num")


def asset(run: Run, row_num: int) -> dict | None:
    with run.connect() as con:
        rows = _rows(
            con, f"SELECT {_ASSET_COLUMNS}, geometry_wkt FROM assets WHERE row_num = ?", [row_num]
        )
        if not rows:
            return None
        result = rows[0]
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


def export_rows(run: Run) -> tuple[list[str], list[tuple]]:
    """One row per asset, scenario, year and hazard; an asset with no results appears once."""
    with run.connect() as con:
        cursor = con.execute(_EXPORT)
        return [d[0] for d in cursor.description], cursor.fetchall()
