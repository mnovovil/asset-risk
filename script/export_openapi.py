"""Write the API's schema, which the front end's types are generated from:
python script/export_openapi.py [output.json]

Needs no settings file, and test/engine/test_api.py checks the committed copy is current.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from engine.api import create_app  # noqa: E402

OPENAPI_JSON = ROOT / "app" / "front" / "openapi.json"


def schema_text() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else OPENAPI_JSON
    output.write_text(schema_text())
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
