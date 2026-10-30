"""Read and check a portfolio CSV of id, lat, lon before any work starts.

Whole-file problems are rejected here. A bad row doesn't stop a run: geolocate reports it as
match_type = invalid and it stays in the results, so nothing disappears silently.
"""

from __future__ import annotations

import os
from collections import Counter

from engine.geolocation import InvalidPortfolio, read_points

MAX_IDS_IN_MESSAGE = 5


class PortfolioError(Exception):
    """The portfolio can't be processed. The message is written for the person who uploaded it."""


def read_portfolio(csv_path: str | os.PathLike[str], max_rows: int) -> list[tuple[str | None, ...]]:
    """Return (id, lat, lon) rows as raw strings, in input order."""
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
        shown = ", ".join(duplicates[:MAX_IDS_IN_MESSAGE])
        more = len(duplicates) - MAX_IDS_IN_MESSAGE
        suffix = f" and {more} more" if more > 0 else ""
        raise PortfolioError(f"Duplicate ids must be removed: {shown}{suffix}")
    return points
