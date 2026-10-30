"""Run a portfolio through every stage, recording progress on the run.

A bad portfolio is rejected by start() before a run exists. After that, failures are recorded on
the run instead of raised, so a caller in the background has one place to look.
"""

from __future__ import annotations

import logging
import os

from engine.assess import assess
from engine.classify import classify
from engine.geolocation import locate
from engine.ingest import read_portfolio
from engine.settings import Settings
from engine.store import Run, create_run, load_assets, set_progress, set_status

logger = logging.getLogger(__name__)

Points = list[tuple[str | None, ...]]


class AssessmentFailed(Exception):
    """physrisk returned no results at all, so an empty dashboard would mislead."""


def start(
    csv_path: str | os.PathLike[str], settings: Settings, source_name: str | None = None
) -> tuple[Run, Points]:
    """Check the portfolio and create its run. Raises PortfolioError if it's unusable."""
    points = read_portfolio(csv_path, settings.max_portfolio_rows)
    return create_run(settings.data_dir, len(points), source_name), points


def execute(run: Run, points: Points, settings: Settings) -> bool:
    """Run every stage and return whether it completed. The outcome is recorded on the run."""
    try:
        set_status(run, "running", "geolocating")
        locate(points, run.geolocated_csv, settings, lambda d, t: set_progress(run, d, t))
        load_assets(run)

        set_status(run, "running", "classifying")
        classify(run, settings)

        set_status(run, "running", "assessing")
        assessment = assess(run, settings)
        if assessment.requests and assessment.failed_requests == assessment.requests:
            raise AssessmentFailed("Every physrisk request failed; see assess_failures")
    except Exception as e:
        logger.exception("Run %s failed", run.run_id)
        set_status(run, "failed", error=str(e))
        return False
    set_status(run, "completed")
    return True
