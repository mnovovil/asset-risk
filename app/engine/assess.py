"""Run physrisk for every assessable asset, for each configured scenario and year.

Requests run serially, because physrisk's thread safety is untested. A failed batch is recorded and
the run continues, and its assets have no results for that scenario and year, not zeros.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from itertools import product
from typing import Protocol

from engine.classify import ASSET_CLASS
from engine.settings import Settings
from engine.store import Run, set_progress

HISTORICAL = "historical"
HISTORICAL_YEAR = 1980
MAX_ERROR_LENGTH = 500
# Scores have no meaning to report for this one unless the response defines it.
NO_VULNERABILITY = {-1: "No vulnerability"}

logger = logging.getLogger(__name__)

_INSERT_IMPACTS = """
INSERT INTO impacts
SELECT unnest(?::INTEGER[]), unnest(?::VARCHAR[]), unnest(?::VARCHAR[]), unnest(?::VARCHAR[]),
       unnest(?::INTEGER[]), unnest(?::DOUBLE[]), unnest(?::DOUBLE[]), unnest(?::VARCHAR[][])
"""
_INSERT_SCORES = """
INSERT INTO scores
SELECT unnest(?::INTEGER[]), unnest(?::VARCHAR[]), unnest(?::VARCHAR[]), unnest(?::INTEGER[]),
       unnest(?::INTEGER[]), unnest(?::VARCHAR[])
"""


class Requester(Protocol):
    def get(self, *, request_id: str, request_dict: dict) -> str: ...


@dataclass(frozen=True)
class Assessment:
    requests: int
    failed_requests: int


@cache
def default_requester() -> Requester:
    # Imported here because it takes seconds, and only this needs it.
    from physrisk.container import Container

    return Container().requester()


def assess(run: Run, settings: Settings, requester: Requester | None = None) -> Assessment:
    """Fill in impacts and scores, and return how many physrisk requests were made and failed."""
    with run.connect() as con:
        assets = con.execute(
            "SELECT row_num, physrisk_type, physrisk_location, lat, lon FROM assets "
            "WHERE assessable ORDER BY row_num"
        ).fetchall()
        pairs = list(product(settings.scenarios, settings.years))
        con.executemany("INSERT INTO assessment_pairs VALUES (?, ?)", [*pairs, (HISTORICAL, None)])
    if not assets:
        return Assessment(0, 0)

    requester = requester or default_requester()
    batches = [
        assets[i : i + settings.physrisk_batch_size]
        for i in range(0, len(assets), settings.physrisk_batch_size)
    ]
    total = len(pairs) * len(batches)
    seen_baseline: set[tuple[int, str, str]] = set()
    failed = 0
    for done, ((scenario, year), batch) in enumerate(product(pairs, batches), 1):
        try:
            response = _request(requester, batch, scenario, year)
            impacts, scores = flatten(response, [a[0] for a in batch], seen_baseline)
        except Exception as e:
            logger.warning("physrisk failed for %s %s: %s", scenario, year, e)
            _record_failure(run, batch, scenario, year, e)
            failed += 1
        else:
            _store(run, impacts, scores)
        set_progress(run, done, total)
    return Assessment(total, failed)


def _request(requester: Requester, batch: list[tuple], scenario: str, year: int) -> dict:
    items = [
        {
            "asset_class": ASSET_CLASS,
            "type": building_type,
            "location": location,
            "latitude": lat,
            "longitude": lon,
        }
        for _, building_type, location, lat, lon in batch
    ]
    return json.loads(
        requester.get(
            request_id="get_asset_impact",
            request_dict={
                "assets": {"items": items},
                "scenario": scenario,
                "years": [year],
                "include_asset_level": True,
                "include_calc_details": True,
                "include_measures": True,
            },
        )
    )


def flatten(
    response: dict, row_nums: list[int], seen_baseline: set[tuple[int, str, str]]
) -> tuple[list[tuple], list[tuple]]:
    """Turn a response into impacts and scores rows. Results come back in request order."""
    asset_impacts = response["asset_impacts"]
    if len(asset_impacts) != len(row_nums):
        raise ValueError(f"Expected {len(row_nums)} assets, got {len(asset_impacts)}")

    impacts = []
    for row_num, asset in zip(row_nums, asset_impacts, strict=True):
        for impact in asset["impacts"]:
            key = impact["key"]
            hazard, scenario, impact_type = (
                key["hazard_type"],
                key["scenario_id"],
                impact["impact_type"],
            )
            if scenario == HISTORICAL:
                if (row_num, hazard, impact_type) in seen_baseline:
                    continue
                seen_baseline.add((row_num, hazard, impact_type))
            details = impact.get("calc_details") or {}
            impacts.append(
                (
                    row_num,
                    hazard,
                    impact_type,
                    scenario,
                    _year(key.get("year")),
                    _number(impact.get("impact_mean")),
                    _number(impact.get("impact_std_deviation")),
                    details.get("hazard_path") or [],
                )
            )
    return impacts, _scores(response.get("risk_measures") or {}, row_nums)


def _scores(measures: dict, row_nums: list[int]) -> list[tuple]:
    if not measures.get("measures_for_assets"):
        return []
    definitions = measures["score_based_measure_set_defn"]
    rows = []
    for measure in measures["measures_for_assets"]:
        key = measure["key"]
        hazard = key["hazard_type"]
        # Labels differ between hazard groups, so they're looked up per hazard and asset.
        ids = definitions["asset_measure_ids_for_hazard"][hazard]
        for row_num, definition_id, score in zip(row_nums, ids, measure["scores"], strict=True):
            values = definitions["score_definitions"][definition_id]["values"]
            labels = NO_VULNERABILITY | {v["value"]: v["label"] for v in values}
            year = _year(key.get("year"))
            rows.append((row_num, hazard, key["scenario_id"], year, score, labels.get(score)))
    return rows


def hazard_curve(
    lat: float,
    lon: float,
    scenario: str,
    year: int | None,
    hazard: str = "RiverineInundation",
    indicator: str = "flood_depth",
    requester: Requester | None = None,
) -> dict[str, list[float]]:
    """Intensity by return period at one point. Empty when the scenario has no data for it."""
    response = json.loads(
        (requester or default_requester()).get(
            request_id="get_hazard_data",
            request_dict={
                "items": [
                    {
                        "request_item_id": "curve",
                        "latitudes": [lat],
                        "longitudes": [lon],
                        "hazard_type": hazard,
                        "indicator_id": indicator,
                        "scenario": scenario,
                        "year": HISTORICAL_YEAR if scenario == HISTORICAL else year,
                    }
                ]
            },
        )
    )
    curve = response["items"][0]["intensity_curve_set"][0]
    return {"return_periods": curve["index_values"], "intensities": curve["intensities"]}


def _store(run: Run, impacts: list[tuple], scores: list[tuple]) -> None:
    with run.connect() as con:
        if impacts:
            con.execute(_INSERT_IMPACTS, _columns(impacts))
        if scores:
            con.execute(_INSERT_SCORES, _columns(scores))


def _record_failure(run: Run, batch: list[tuple], scenario: str, year: int, error: Exception):
    message = str(error)[:MAX_ERROR_LENGTH]
    with run.connect() as con:
        con.executemany(
            "INSERT INTO assess_failures VALUES (?, ?, ?, ?)",
            [(asset[0], scenario, year, message) for asset in batch],
        )


def _columns(rows: Iterable[tuple]) -> list[list]:
    # Column-wise, because executemany takes minutes for the row counts of a large portfolio.
    return [list(column) for column in zip(*rows, strict=True)]


def _year(value) -> int | None:
    # physrisk writes the baseline's year as the string "None".
    return None if value in (None, "None") else int(value)


def _number(value) -> float | None:
    return None if value is None or math.isnan(value) else float(value)
