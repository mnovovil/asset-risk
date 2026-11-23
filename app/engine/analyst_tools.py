"""Read-only tools the portfolio analyst can call on one completed run.

This registry is the one source of the tools' names, argument schemas and descriptions: the
analyst's prompt is filled in from it. A tool reads the run through its SQL views and results.py,
with values passed as `?` parameters, and returns a dict that json.dumps can write. An argument that
doesn't fit the schema or the run (a scenario and year it wasn't assessed for, a hazard it has no
results for, a row_num it doesn't have) returns {"error": "readable message"}, never an exception,
so the model can read the message and try again.

AAL figures are fractions of an asset's value per year, as everywhere else. An asset with no result
(excluded, or in a failed physrisk batch) is left out of every figure, and never shows as 0.
"""

from __future__ import annotations

import datetime
import math
from collections.abc import Callable
from dataclasses import dataclass

import duckdb

from engine import results
from engine.assess import HISTORICAL
from engine.store import Run

MAX_TOP_ASSETS = 25
DEFAULT_TOP_ASSETS = 10
# Rows list_exclusions returns per list. The counts are always complete.
MAX_LISTED = 25

AAL_NOTE = "AAL is a fraction of asset value per year: 0.0123 is 1.23%."
EXCLUSION_REASONS = {
    "invalid": "Missing id, or a missing, non-numeric or out-of-range latitude or longitude.",
    "off_land": "No building within range and no country within 50 km, so likely a bad coordinate.",
    "no_curve": "physrisk has no vulnerability curve for this building type and region.",
}


class ToolError(Exception):
    """An argument the run can't answer for. The message is shown to the model as is."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str  # one line
    parameters: dict  # a JSON Schema object, in the subset _check_args reads
    function: Callable[[Run, dict], dict]


def call(run: Run, name: str, args: object) -> dict:
    """Run one tool on a completed run. Bad arguments give {"error": ...}, never an exception."""
    tool = TOOLS.get(name)
    if tool is None:
        return {"error": f"There's no tool named {name!r}. The tools are: {', '.join(TOOLS)}."}
    try:
        checked = _check_args(tool, args)
        return _jsonable(tool.function(run, checked))
    except ToolError as e:
        return {"error": str(e)}


# --- Arguments ---------------------------------------------------------------------------------

_TYPES = {
    "string": lambda v: isinstance(v, str),
    # bool is an int in Python, and true is never a year or a count.
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "null": lambda v: v is None,
}


def _check_args(tool: Tool, args: object) -> dict:
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ToolError(f"{tool.name} takes an object of arguments, not {type(args).__name__}.")
    properties = tool.parameters["properties"]
    unknown = sorted(set(args) - set(properties))
    if unknown:
        raise ToolError(
            f"{tool.name} has no argument {', '.join(map(repr, unknown))}. "
            f"Its arguments are: {', '.join(properties) or 'none'}."
        )
    missing = [key for key in tool.parameters.get("required", []) if key not in args]
    if missing:
        raise ToolError(f"{tool.name} needs {', '.join(map(repr, missing))}.")
    checked = {}
    for key, schema in properties.items():
        value = args.get(key, schema.get("default"))
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPES[t](value) for t in types):
            raise ToolError(f"{key} must be {' or '.join(types)}, not {value!r}.")
        if isinstance(value, int) and "minimum" in schema and value < schema["minimum"]:
            raise ToolError(f"{key} must be at least {schema['minimum']}, not {value}.")
        checked[key] = value
    return checked


def _hazards(con: duckdb.DuckDBPyConnection) -> list[str]:
    return [h for (h,) in con.execute("SELECT DISTINCT hazard FROM impacts ORDER BY 1").fetchall()]


def _check_hazard(con: duckdb.DuckDBPyConnection, hazard: str | None) -> str | None:
    """The run's own spelling of a hazard, matched without regard to case."""
    if hazard is None:
        return None
    known = _hazards(con)
    for name in known:
        if name.lower() == hazard.strip().lower():
            return name
    raise ToolError(
        f"This run has no results for a hazard named {hazard!r}. "
        f"Its hazards are: {', '.join(known) or 'none'}."
    )


def _pairs(con: duckdb.DuckDBPyConnection) -> list[tuple[str, int | None]]:
    return con.execute(
        "SELECT DISTINCT scenario, year FROM assessment_pairs ORDER BY scenario, year NULLS FIRST"
    ).fetchall()


def _describe(pair: tuple[str, int | None]) -> str:
    scenario, year = pair
    return f"{scenario} (year null)" if year is None else f"{scenario} {year}"


def _check_pair(
    con: duckdb.DuckDBPyConnection, scenario: str, year: int | None
) -> tuple[str, int | None]:
    """The scenario and year as the run stores them. The historical baseline has year null."""
    scenario = scenario.strip().lower()
    pairs = _pairs(con)
    if (scenario, year) in pairs:
        return scenario, year
    if scenario == HISTORICAL and year is not None:
        raise ToolError(f"The historical baseline has no year: pass year null, not {year}.")
    raise ToolError(
        f"This run wasn't assessed for {_describe((scenario, year))}. "
        f"It was assessed for: {', '.join(map(_describe, pairs)) or 'nothing'}."
    )


def _check_row(con: duckdb.DuckDBPyConnection, row_num: int) -> None:
    found = con.execute("SELECT count(*) FROM assets WHERE row_num = ?", [row_num]).fetchone()[0]
    if not found:
        total = con.execute("SELECT count(*) FROM assets").fetchone()[0]
        raise ToolError(f"There's no asset with row_num {row_num}. This run has rows 1 to {total}.")


# --- Reading -----------------------------------------------------------------------------------


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> list[dict]:
    return results._rows(con, sql, params)


def _one(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> dict:
    return _rows(con, sql, params)[0]


def _currency_if_valued(run: Run) -> tuple[bool, str | None]:
    """Whether the run has usable asset values, and their currency.

    A run from before asset values has no has_values column, and reads as having none.
    """
    summary = results.summary(run)
    return bool(summary.get("has_values", False)), summary.get("currency")


def _jsonable(value):
    """What json.dumps can write without inventing numbers: NaN and infinity become null."""
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, datetime.date | datetime.datetime):
        return value.isoformat()
    return value


# --- Tools -------------------------------------------------------------------------------------

_SCENARIO = {"type": "string", "description": "A scenario the run was assessed for, or historical"}
_YEAR = {"type": ["integer", "null"], "description": "The year; null for the historical baseline"}
_HAZARD = {
    "type": ["string", "null"],
    "default": None,
    "description": "One hazard, or null for all of them",
}


def query_portfolio(run: Run, args: dict) -> dict:
    with run.connect() as con:
        scenario, year = _check_pair(con, args["scenario"], args["year"])
        hazard = _check_hazard(con, args["hazard"])
        hazard_filter = "" if hazard is None else "AND c.hazard = ?"
        hazards = _rows(
            con,
            # Every hazard the run has, so one with no results here shows as not covered.
            "SELECT c.hazard, h.mean_aal, c.assets, c.covered, c.shared "
            "FROM v_hazard_coverage c LEFT JOIN v_portfolio_hazards h "
            "ON h.scenario = c.scenario AND h.year IS NOT DISTINCT FROM c.year "
            "AND h.hazard = c.hazard "
            f"WHERE c.scenario = ? AND c.year IS NOT DISTINCT FROM ? {hazard_filter} "
            "ORDER BY c.hazard",
            [scenario, year] + ([] if hazard is None else [hazard]),
        )
        point = _one(
            con,
            "SELECT * FROM v_portfolio_trajectory "
            "WHERE scenario = ? AND year IS NOT DISTINCT FROM ?",
            [scenario, year],
        )
    result = {
        "scenario": scenario,
        "year": year,
        "assets_with_results": point["assets"],
        "mean_total_aal": point["mean_total_aal"],
        "mean_shared_aal": point["mean_shared_aal"],
        "hazards": hazards,
        "note": f"{AAL_NOTE} Means are equal-weighted over assets with results. Only "
        "mean_shared_aal, over hazards in every scenario, compares across scenarios.",
    }
    has_values, currency = _currency_if_valued(run)
    if has_values:
        result["value_weighted"] = {
            "currency": currency,
            **{
                key: point[key]
                for key in (
                    "valued_assets",
                    "valued_total",
                    "weighted_mean_total_aal",
                    "weighted_mean_shared_aal",
                    "expected_loss_total",
                    "expected_loss_shared",
                )
            },
        }
    return result


def get_asset(run: Run, args: dict) -> dict:
    row_num = args["row_num"]
    with run.connect() as con:
        _check_row(con, row_num)
        failures = _rows(
            con,
            "SELECT scenario, year FROM assess_failures WHERE row_num = ? ORDER BY scenario, year",
            [row_num],
        )
    asset = results.asset(run, row_num)
    # Footprints can be very large, and the model has no use for coordinates of a shape.
    asset.pop("geometry_wkt", None)
    asset["failed_assessments"] = failures
    asset["note"] = (
        f"{AAL_NOTE} An asset that is excluded, or whose physrisk batch failed, has no impacts for "
        "that scenario and year: that is no result, not zero loss."
    )
    return asset


def top_assets(run: Run, args: dict) -> dict:
    asked = args["n"]
    n = min(asked, MAX_TOP_ASSETS)
    with run.connect() as con:
        scenario, year = _check_pair(con, args["scenario"], args["year"])
        hazard = _check_hazard(con, args["hazard"])
        if hazard is None:
            ranked_by = "total_aal"
            assets = _rows(
                con,
                "SELECT t.row_num, t.asset_id, a.type_source, a.physrisk_type, t.total_aal, "
                "t.shared_aal, t.hazards FROM v_asset_totals t JOIN assets a USING (row_num) "
                "WHERE t.scenario = ? AND t.year IS NOT DISTINCT FROM ? "
                "ORDER BY t.total_aal DESC NULLS LAST, t.row_num LIMIT ?",
                [scenario, year, n],
            )
            with_results = con.execute(
                "SELECT count(*) FROM v_asset_totals "
                "WHERE scenario = ? AND year IS NOT DISTINCT FROM ?",
                [scenario, year],
            ).fetchone()[0]
        else:
            ranked_by = "aal"
            # Summed over impact types, as v_asset_totals sums them.
            assets = _rows(
                con,
                "SELECT i.row_num, i.asset_id, a.type_source, a.physrisk_type, sum(i.aal) AS aal "
                "FROM v_asset_hazard_aal i JOIN assets a USING (row_num) "
                "WHERE i.scenario = ? AND i.year IS NOT DISTINCT FROM ? AND i.hazard = ? "
                "GROUP BY i.row_num, i.asset_id, a.type_source, a.physrisk_type "
                "ORDER BY aal DESC NULLS LAST, i.row_num LIMIT ?",
                [scenario, year, hazard, n],
            )
            with_results = con.execute(
                "SELECT count(DISTINCT row_num) FROM impacts "
                "WHERE scenario = ? AND year IS NOT DISTINCT FROM ? AND hazard = ?",
                [scenario, year, hazard],
            ).fetchone()[0]
    result = {
        "scenario": scenario,
        "year": year,
        "hazard": hazard,
        "ranked_by": ranked_by,
        "n": n,
        "assets_with_results": with_results,
        "assets": assets,
        "note": f"{AAL_NOTE} Only assets with results are ranked. type_source 'assumed' means "
        "the building type is the run's default, not one read from the building.",
    }
    if asked > MAX_TOP_ASSETS:
        result["n_capped_from"] = asked
    return result


def compare_scenarios(run: Run, args: dict) -> dict:
    with run.connect() as con:
        # The baseline has no year, so comparing with it reads year as the other scenario's.
        pairs = [
            _check_pair(con, s, None if s.strip().lower() == HISTORICAL else args["year"])
            for s in (args["a"], args["b"])
        ]
        if pairs[0] == pairs[1]:
            raise ToolError("a and b are the same scenario and year: pick two different ones.")
        shared = [
            h for (h,) in con.execute("SELECT hazard FROM v_shared_hazards ORDER BY 1").fetchall()
        ]
        sides = []
        left_out = {}
        for scenario, year in pairs:
            point = _one(
                con,
                "SELECT assets, mean_shared_aal FROM v_portfolio_trajectory "
                "WHERE scenario = ? AND year IS NOT DISTINCT FROM ?",
                [scenario, year],
            )
            sides.append({"scenario": scenario, "year": year, **point})
            left_out[scenario] = [
                h
                for (h,) in con.execute(
                    "SELECT hazard FROM v_hazard_coverage WHERE scenario = ? "
                    "AND year IS NOT DISTINCT FROM ? AND covered AND NOT shared ORDER BY hazard",
                    [scenario, year],
                ).fetchall()
            ]
    a, b = sides
    difference = (
        None
        if a["mean_shared_aal"] is None or b["mean_shared_aal"] is None
        else b["mean_shared_aal"] - a["mean_shared_aal"]
    )
    return {
        "compared_on": "mean_shared_aal",
        "shared_hazards": shared,
        "a": a,
        "b": b,
        "difference_b_minus_a": difference,
        "hazards_left_out": left_out,
        "note": f"{AAL_NOTE} Scenarios model different hazards, so they're compared only on the "
        "hazards every scenario has. hazards_left_out are hazards a scenario has results for that "
        "aren't in this comparison.",
    }


def list_exclusions(run: Run, args: dict) -> dict:
    with run.connect() as con:
        counts = _rows(con, "SELECT reason, assets FROM v_exclusions ORDER BY reason")
        excluded = _rows(
            con,
            "SELECT row_num, asset_id, exclusion_reason AS reason FROM assets "
            "WHERE exclusion_reason IS NOT NULL ORDER BY row_num LIMIT ?",
            [MAX_LISTED],
        )
        failures = _rows(
            con,
            "SELECT f.row_num, a.asset_id, f.scenario, f.year FROM assess_failures f "
            "LEFT JOIN assets a USING (row_num) ORDER BY f.row_num, f.scenario, f.year LIMIT ?",
            [MAX_LISTED],
        )
        failed = con.execute(
            "SELECT count(*), count(DISTINCT row_num) FROM assess_failures"
        ).fetchone()
    return {
        "excluded_counts": counts,
        "excluded_total": sum(row["assets"] for row in counts),
        "excluded": excluded,
        "reasons": {row["reason"]: EXCLUSION_REASONS.get(row["reason"]) for row in counts},
        "failures": failures,
        "failures_total": failed[0],
        "failed_assets": failed[1],
        "note": f"Lists show at most {MAX_LISTED} rows each; the totals are complete. Excluded "
        "assets were never sent to physrisk. A failure means a physrisk batch failed for that "
        "scenario and year. Neither has results, and neither counts as zero loss.",
    }


TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in (
        Tool(
            "query_portfolio",
            "Portfolio mean AAL for one scenario and year, overall and by hazard.",
            {
                "type": "object",
                "properties": {"scenario": _SCENARIO, "year": _YEAR, "hazard": _HAZARD},
                "required": ["scenario", "year"],
            },
            query_portfolio,
        ),
        Tool(
            "get_asset",
            "One asset's building, classification, FEMA flood zone, value, impacts and scores.",
            {
                "type": "object",
                "properties": {
                    "row_num": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "The asset's row in the uploaded file, from 1",
                    }
                },
                "required": ["row_num"],
            },
            get_asset,
        ),
        Tool(
            "top_assets",
            f"The assets with the highest AAL for one scenario and year, up to {MAX_TOP_ASSETS}.",
            {
                "type": "object",
                "properties": {
                    "scenario": _SCENARIO,
                    "year": _YEAR,
                    "hazard": _HAZARD,
                    "n": {
                        "type": "integer",
                        "minimum": 1,
                        "default": DEFAULT_TOP_ASSETS,
                        "description": f"How many assets, at most {MAX_TOP_ASSETS}",
                    },
                },
                "required": ["scenario", "year"],
            },
            top_assets,
        ),
        Tool(
            "compare_scenarios",
            "Two scenarios' mean AAL on the hazards they share, and its difference.",
            {
                "type": "object",
                "properties": {
                    "a": _SCENARIO,
                    "b": _SCENARIO,
                    "year": {
                        "type": ["integer", "null"],
                        "description": "The year for both; the historical baseline has none",
                    },
                },
                "required": ["a", "b", "year"],
            },
            compare_scenarios,
        ),
        Tool(
            "list_exclusions",
            "Assets left out of the results: excluded before physrisk, or in a failed batch.",
            {"type": "object", "properties": {}},
            list_exclusions,
        ),
    )
}
