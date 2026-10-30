"""Run a portfolio CSV through the pipeline: python script/run_portfolio.py <portfolio.csv>
[--settings path].

Runs ingest, geolocate and classify so far, then prints a summary. Exit codes: 0 success,
1 settings, geolocate or classification failure, 2 bad portfolio.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from engine.classify import ClassificationError, classify  # noqa: E402
from engine.geolocation import GeolocationError, locate  # noqa: E402
from engine.ingest import PortfolioError, read_portfolio  # noqa: E402
from engine.settings import SettingsError, load_settings  # noqa: E402
from engine.store import create_run, load_assets  # noqa: E402

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
        points = read_portfolio(args.csv_path, settings.max_portfolio_rows)
    except (SettingsError, GeolocationError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_FAILED
    except PortfolioError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_INPUT

    run = create_run(settings.data_dir, len(points), args.csv_path.name)
    try:
        counts = locate(points, run.geolocated_csv, settings)
        load_assets(run)
        classified = classify(run, settings)
    except (GeolocationError, ClassificationError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_FAILED

    matched = ", ".join(f"{k}={v}" for k, v in counts.items())
    assessed = ", ".join(f"{k}={v}" for k, v in classified.items())
    print(f"Run {run.run_id}: {len(points)} rows")
    print(f"Geolocated: {matched}")
    print(f"Classified: {assessed}")
    print(f"Results: {run.directory}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
