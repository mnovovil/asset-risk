# asset-risk

Take a CSV of `(id, lat, lon)`, identify each point's building with `geolocate`, assess its physical
climate risk with `physrisk`, and show the portfolio in a web dashboard.

The plan is epic #1. Only the scaffold exists so far; the modules below arrive with issues #3–#11.

## Stack
- Python >= 3.11, DuckDB >= 2.0, `physrisk-lib` (pinned exactly: its output has no stability promise)
- `geolocate`: git submodule at `vendor/geolocate`, imported directly
- FastAPI for the API, TypeScript (Vite + React) for the front end
- Terraform or OpenTofu (`infra/`) owns the run settings and writes a git-ignored `.asset-risk.json`
- Docker (`docker/`): one image and a compose stack

## Architecture
```
app/front            upload a CSV, follow progress, view results
  → app/engine/api.py        FastAPI: start a background run, serve results
  → app/engine/pipeline.py   ingest → geolocate → classify → assess → store
      geolocation.py   the only importer of vendor/geolocate/src
      classify.py      Overture class/subtype + region → valid physrisk (type, location)
      assess.py        physrisk get_asset_impact per (scenario, year)
      store.py, sql/   one DuckDB file per run, SQL views for the results
script/              ad-hoc CLIs
```
`app/` is on the path through pytest (`pythonpath` in `pyproject.toml`), so the package is `engine`.

## Rules
- Never edit `vendor/`. To change geolocate, change its own repo and bump the submodule. A bump also
  moves the Overture release, because geolocate's `infra/` pins it.
- geolocate exposes top-level modules named `config`, `db`, `match` and `geolocate`. Don't add
  top-level modules with those names, and don't put `app/engine` itself on the path.
- No `__init__.py` under `test/`: `test/engine` as a package would shadow the `engine` package, and
  `test` would shadow the standard library's. Test file names must therefore be unique.
- Unit tests never touch the network. Live tests are marked `s3`, `live` or `e2e` and are excluded by
  default.
- physrisk accepts unknown types and locations without error and returns a fallback result. Only send
  values checked against its embedded vulnerability config.
- Never treat a low score as proof of low risk: a mid-ocean point scores `Very low` for flood, and
  scenarios can silently drop hazards. See `docs/physrisk_demo.ipynb`, section 8.
- Pass values into SQL as parameters (`?`), never via string formatting.
- Never commit `.asset-risk.json`, `.geolocate.json`, `*.tfstate*` or `*.tfvars`: they may contain
  credentials.

## Commands
- Install: `git submodule update --init && uv venv .venv && uv pip install -p .venv -r requirements-dev.txt`
- Lint: `.venv/bin/ruff check --fix .` · Format: `.venv/bin/ruff format .`
- Tests: `.venv/bin/pytest` (no network) · Live: `.venv/bin/pytest -m s3`, `-m live` or `-m e2e`
