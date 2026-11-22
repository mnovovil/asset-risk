"""Read and check a portfolio CSV of id, lat, lon, with optional value and currency, before any
work starts.

Whole-file problems are rejected here. A bad row doesn't stop a run: geolocate reports it as
match_type = invalid and it stays in the results, so nothing disappears silently. A bad value
doesn't either: the asset is still assessed, and its value is flagged and left out of weighting.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from dataclasses import dataclass

import duckdb

from engine.geolocation import InvalidPortfolio, read_points

MAX_IDS_IN_MESSAGE = 5

# A plain decimal number. Python's float() also takes "1_000", "nan" and "inf", which aren't values.
_NUMBER = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")
_CURRENCY = re.compile(r"[A-Z]{3}")

Points = list[tuple[str | None, ...]]


class PortfolioError(Exception):
    """The portfolio can't be processed. The message is written for the person who uploaded it."""


@dataclass(frozen=True)
class Portfolio:
    points: Points  # (id, lat, lon) as raw strings, in input order
    values: list[float | None]  # one per point; None unless its status is 'given'
    value_statuses: list[str]  # given | missing | invalid
    currency: str | None  # one ISO 4217 code for the file, upper-cased, or None


def read_portfolio(csv_path: str | os.PathLike[str], max_rows: int) -> Portfolio:
    """Return the portfolio's points, and their values if it has a value column."""
    try:
        points = read_points(csv_path)
    except InvalidPortfolio as e:
        raise PortfolioError(str(e)) from None

    if not points:
        raise PortfolioError("The portfolio has no rows")
    if len(points) > max_rows:
        raise PortfolioError(f"The portfolio has {len(points)} rows; the limit is {max_rows}")

    # Results are keyed on id. Blank ids aren't duplicates: geolocate reports them as invalid.
    counts = Counter(raw_id.strip() for raw_id, _, _ in points if raw_id and raw_id.strip())
    duplicates = [raw_id for raw_id, n in counts.items() if n > 1]
    if duplicates:
        raise PortfolioError(f"Duplicate ids must be removed: {_listed(duplicates)}")

    raw_values, raw_currencies = _optional_columns(csv_path)
    if len(raw_values) != len(points):
        raise ValueError(f"Read {len(raw_values)} values for {len(points)} points")
    parsed = [_parse_value(raw) for raw in raw_values]
    has_values = any(status == "given" for _, status in parsed)
    return Portfolio(
        points=points,
        values=[value for value, _ in parsed],
        value_statuses=[status for _, status in parsed],
        currency=_currency(raw_currencies) if has_values else None,
    )


def _optional_columns(csv_path) -> tuple[list[str | None], list[str | None]]:
    """The value and currency columns as raw strings, one per row, or all None if absent.

    Read with the same options geolocate's read_points uses, so row i here is point i there.
    """
    con = duckdb.connect()
    try:
        cursor = con.execute(
            "SELECT * FROM read_csv(?, header = true, all_varchar = true)", [str(csv_path)]
        )
        columns = [d[0].strip().lower() for d in cursor.description]
        rows = cursor.fetchall()
    finally:
        con.close()

    def column(name: str) -> list[str | None]:
        if name not in columns:
            return [None] * len(rows)
        index = columns.index(name)
        return [row[index] for row in rows]

    return column("value"), column("currency")


def _parse_value(raw: str | None) -> tuple[float | None, str]:
    text = (raw or "").strip()
    if not text:
        return None, "missing"
    if not _NUMBER.fullmatch(text):
        return None, "invalid"
    value = float(text)
    if not math.isfinite(value) or value < 0:
        return None, "invalid"
    return value, "given"


def _currency(raw_currencies: list[str | None]) -> str | None:
    codes = sorted({code.strip().upper() for code in raw_currencies if code and code.strip()})
    if len(codes) > 1:
        raise PortfolioError(
            f"A portfolio can use only one currency, and this one uses {_listed(codes)}"
        )
    if not codes:
        return None
    if not _CURRENCY.fullmatch(codes[0]):
        raise PortfolioError(
            f"The currency {codes[0]!r} isn't a three-letter ISO 4217 code, such as USD or EUR"
        )
    return codes[0]


def _listed(items: list[str]) -> str:
    shown = ", ".join(items[:MAX_IDS_IN_MESSAGE])
    more = len(items) - MAX_IDS_IN_MESSAGE
    return shown + (f" and {more} more" if more > 0 else "")
