# Reference

Start with the [README](../README.md) for setup. How to read the results is in the
[methodology](methodology.md).

## Settings

`infra/` holds the settings as Terraform variables and writes them to a git-ignored
`.asset-risk.json`. To change one, copy `infra/terraform.tfvars.example` to `infra/terraform.tfvars`,
edit it, run `terraform -chdir=infra apply`, and restart the app.

| Variable | Default | Meaning |
|---|---|---|
| `scenarios` | `ssp245`, `ssp585` | Scenarios to assess. Data [differs by scenario](methodology.md#comparing-scenarios) |
| `years` | `2030`, `2050`, `2080` | Years to assess. Each scenario and year pair adds run time |
| `default_building_type` | `Buildings/Commercial` | Type for assets with no usable class or subtype |
| `physrisk_batch_size` | `100` | Assets per physrisk request |
| `geolocate_workers` | `16` | Threads matching points. Lower it if you see S3 errors |
| `geolocate_batch_size` | `20` | Points per geolocate batch |
| `max_portfolio_rows` | `5000` | Largest portfolio accepted |
| `max_upload_mb` | `10` | Largest upload accepted |
| `data_dir` | `data` | Where `script/serve.py` keeps runs. Docker always uses its volume |
| `api_port` | `8000` | Port on localhost. `API_PORT` overrides it for `script/start.sh` |
| `aws_access_key_id`, `aws_secret_access_key`, `aws_session_token` | empty | Optional, for geolocate. Prefer `TF_VAR_...` environment variables, and note that the Terraform state holds these in plain text |

Environment variables override the settings in a container: `ASSET_RISK_CONFIG`, `GEOLOCATE_CONFIG`
and `ASSET_RISK_DATA_DIR`.

## Portfolio CSV

A header containing `id`, `lat` and `lon` (WGS84 degrees). Case and column order don't matter, and
extra columns are ignored.

The whole file is rejected if it has missing columns, no rows, duplicate ids, or too many rows or
bytes. A bad row doesn't stop a run: it's kept and reported as `invalid`.

## Classification

`app/engine/sql/classify.sql` adds these columns to `assets`:

- **`physrisk_type`:** from the building's Overture `class`, then its `subtype`, then
  `default_building_type`, using `app/engine/sql/building_type_map.csv`. `type_source` records which
  (`class`, `subtype` or `assumed`).
- **`physrisk_location`:** the point's region, or `Global` when physrisk has no curve for that type and
  region. `location_fallback` marks those.
- **`assessable` and `exclusion_reason`:** only assessable rows go to physrisk. The reasons are in the
  [methodology](methodology.md#excluded-assets).

## Running without Docker

```bash
uv venv .venv && uv pip install -p .venv -r requirements-dev.txt
npm --prefix app/front ci && npm --prefix app/front run build
.venv/bin/python script/serve.py                  # the app
.venv/bin/python script/run_portfolio.py my.csv   # or one run, with no website
```

Runs go to `data/` here, and to the `asset-risk_data` volume in Docker. They don't see each other.
To remove Docker's runs, use `docker compose -f docker/compose.yml down --volumes`.

## API

Interactive docs are at `/docs` on the running app. Errors are always
`{"detail": "a readable message"}`.

| Endpoint | Purpose |
|---|---|
| `POST /api/runs` | Upload a CSV as the `file` field. Returns 202, or 413 or 422 with the reason |
| `GET /api/runs`, `GET /api/runs/{id}` | Status, stage, progress and any error |
| `GET /api/runs/{id}/summary` | Counts, exclusions and shared hazards |
| `GET /api/runs/{id}/assets`, `.../assets/{row_num}` | Assets, or one with its footprint and results |
| `GET /api/runs/{id}/assets/{row_num}/hazard-curve` | River flood depth by return period |
| `GET /api/runs/{id}/impacts`, `.../totals`, `.../scores` | Results for one `scenario` and `year`. For the baseline, use `scenario=historical` with no year |
| `GET /api/runs/{id}/trajectory`, `.../coverage` | Means by scenario and year, and which hazards each has |
| `GET /api/runs/{id}/export.csv` | Everything, one row per asset, scenario, year and hazard |
| `GET /api/config`, `GET /api/health` | Allowed scenarios and limits, and a health check |

Results return 409 until a run is `completed`. Assets are addressed by `row_num`, because an invalid
row can have no id. Runs that were queued or running when the app stopped are marked `interrupted`,
and need uploading again.

## Run database

Each run has `runs/<uuid>/run.duckdb`, which you can query directly:

| Table or view | Contents |
|---|---|
| `runs` | Status and progress |
| `assets` | One row per input row: geolocate's output plus classification |
| `assessment_pairs` | Each scenario and year requested |
| `impacts`, `scores` | Results, keyed on `row_num`, `scenario` and `year`. The baseline has year NULL |
| `assess_failures` | Failed batches |
| `v_portfolio_summary`, `v_exclusions` | Counts |
| `v_asset_totals`, `v_asset_hazard_aal`, `v_asset_scores` | Results per asset |
| `v_portfolio_trajectory`, `v_portfolio_hazards` | Means, including over shared hazards |
| `v_shared_hazards`, `v_hazard_coverage` | Which hazards each scenario has |

## Changing the Overture release

The pinned release is `2026-10-21.0`. Overture removes old releases roughly monthly, so a pinned
release eventually stops working. Runs then
fail while geolocating, with a message saying no files match. The release and its file index are
pinned by the geolocate submodule, so update them together:

```bash
git -C vendor/geolocate fetch origin && git -C vendor/geolocate checkout <commit>
git add vendor/geolocate
terraform -chdir=infra apply
```

If geolocate doesn't have the new release yet, follow
[its guide](../vendor/geolocate/docs/reference.md#changing-the-overture-release) in its own repo first.

## Performance

Measured in Docker on a machine with 4 CPUs and 5.8 GB of memory, with the default 2 scenarios and 3
years, using points around 25 large cities. Memory was sampled every few seconds, so its peak is
approximate.

| Rows | Time | Peak memory |
|---|---|---|
| 40 | 55 s | 0.8 GB |
| 100 | 69 s | 0.7 GB |
| 1,000 | 10 min 14 s | 2.3 GB |

The 5,000-row limit hasn't been measured. Time and memory both grow with portfolio size, so check
you have the memory before going far beyond 1,000 rows, or lower `max_portfolio_rows`. Most of the
time is the physrisk stage, and each scenario and year pair adds to it. Runs happen one at a time, and
others wait in a queue.

## Development

```bash
git submodule update --init
uv venv .venv && uv pip install -p .venv -r requirements-dev.txt && npm --prefix app/front ci

.venv/bin/ruff check --fix . && .venv/bin/ruff format .
.venv/bin/pytest                        # no network
.venv/bin/pytest -m s3                  # live Overture
.venv/bin/pytest -m live                # live physrisk data
.venv/bin/pytest -m e2e                 # the whole path, through Docker
npm --prefix app/front test
npm --prefix app/front run typecheck
npm --prefix app/front run dev          # proxies /api to port 8000
```

After changing the API, regenerate the front end's types:

```bash
.venv/bin/python script/export_openapi.py && npm --prefix app/front run gen:api
```

After a visible change to the app, record the README's GIF again. Each new version stays in git
history, so don't do this for small changes:

```bash
uvx playwright@1.64.1 install chromium-headless-shell   # once
uv run script/record_demo.py --build
```

It runs the sample CSV for real in its own compose project and volume, and stops if the run fails or
the map doesn't load. Without `--build` it reuses the existing image. Check that it reports all three
stages: Classifying is short, and the page only checks progress every 1.5 s, so it can be missed.

`script/overture_values.py` audits the building type map against a live release, and
`script/build_regions.py` rebuilds the region data.
