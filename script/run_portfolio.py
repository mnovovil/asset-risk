"""Run a portfolio CSV through the full pipeline: python script/run_portfolio.py <portfolio.csv>
[--settings path].

Prints a summary and the mean average annual loss per scenario and year. Exit codes: 0 success,
1 settings or pipeline failure, 2 bad portfolio.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from engine.geolocation import GeolocationError  # noqa: E402
from engine.ingest import PortfolioError  # noqa: E402
from engine.pipeline import execute, start  # noqa: E402
from engine.settings import SettingsError, load_settings  # noqa: E402
from engine.store import status, summary  # noqa: E402

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_INPUT = 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a portfolio CSV through the pipeline.")
    parser.add_argument("csv_path", type=Path, help="input CSV with columns id, lat, lon")
    parser.add_argument("--settings", type=Path, help="settings JSON (overrides the default)")
    args = parser.parse_args(argv)

    try:
        settings = load_settings(args.settings)
        run, points = start(args.csv_path, settings, args.csv_path.name)
    except (SettingsError, GeolocationError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_FAILED
    except PortfolioError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_INPUT

    if not execute(run, points, settings):
        print(f"error: {status(run)['error']}", file=sys.stderr)
        return EXIT_FAILED

    print(f"Run {run.run_id}: {summary(run)}")
    with run.connect() as con:
        rows = con.execute(
            "SELECT scenario, year, assets, mean_total_aal, mean_shared_aal, hazards "
            "FROM v_portfolio_trajectory ORDER BY scenario, year"
        ).fetchall()
        hazards = con.execute("SELECT hazard FROM v_shared_hazards ORDER BY 1").fetchall()
    shared = [hazard for (hazard,) in hazards]
    print(f"Hazards in every scenario: {shared}")
    print("scenario    year  assets  total AAL  shared AAL  hazards")
    for scenario, year, assets, total, comparable, covered in rows:
        print(
            f"{scenario:<11} {year or '':<5} {assets:>6}  {_percent(total):>9}  "
            f"{_percent(comparable):>10}  {covered:>7}"
        )
    print(f"Results: {run.directory}")
    return EXIT_OK


def _percent(value: float | None) -> str:
    return "-" if value is None else f"{value:.3%}"


if __name__ == "__main__":
    sys.exit(main())
