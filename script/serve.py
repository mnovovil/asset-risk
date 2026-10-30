"""Start the app: python script/serve.py [--host 127.0.0.1] [--port 8000]

There is no login, so only bind beyond localhost inside a container that publishes to localhost.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import uvicorn  # noqa: E402

from engine.settings import SettingsError, load_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the app.")
    parser.add_argument(
        "--host", default="127.0.0.1", help="address to bind (default: %(default)s)"
    )
    parser.add_argument("--port", type=int, help="port (default: api_port from the settings)")
    args = parser.parse_args()
    try:
        port = args.port or load_settings().api_port
    except SettingsError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    # One worker: the queue and its work live in this process.
    uvicorn.run(
        "engine.api:create_app",
        factory=True,
        host=args.host,
        port=port,
        app_dir=str(ROOT / "app"),
        workers=1,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
