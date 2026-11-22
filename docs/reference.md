# Reference

Start with the [README](../README.md) for setup. How to read the results is in the
[methodology](methodology.md).

## Settings

`infra/` holds the settings as Terraform variables and writes them to a git-ignored
`.asset-risk.json`. To change one, copy `infra/terraform.tfvars.example` to `infra/terraform.tfvars`,
edit it, run `terraform -chdir=infra apply`, and restart the app.

| Variable | Default | Meaning |
|---|---|---|
| `scenarios` | `ssp245`, `ssp585` | Scenarios to assess. Data [differs by scenario](methodology.md#comparing-scenarios): adding `ssp126` leaves no hazard shared by every scenario, so **Change over time** goes empty |
| `years` | `2030`, `2050`, `2080` | Years to assess, from `2030`, `2050` and `2080` (2025 returns no losses). Each scenario and year pair adds run time. The [baseline](methodology.md#today-baseline) always comes back too |
| `default_building_type` | `Buildings/Commercial` | Type for assets with no usable class or subtype |
| `physrisk_batch_size` | `100` | Assets per physrisk request |
| `geolocate_workers` | `16` | Threads matching points. Lower it if you see S3 errors |
| `geolocate_batch_size` | `20` | Points per geolocate batch |
| `cluster_eps_km` | `50` | DBSCAN radius for the map's [risk-concentration bubbles](methodology.md#risk-concentration), more than 0 and at most 1000 |
| `cluster_min_samples` | `5` | Assets within that radius, itself included, for DBSCAN to start a cluster. At least 2 |
| `max_portfolio_rows` | `5000` | Largest portfolio accepted |
| `max_upload_mb` | `10` | Largest upload accepted |
| `data_dir` | `data` | Where `script/serve.py` keeps runs. Docker always uses its volume |
| `flood_zones_db` | `data/fema/flood-zones.duckdb` | FEMA flood zone database [built by `script/build_flood_zones.py`](data-sources.md#fema-flood-zones). `null` turns the lookup off |
| `hazard_map_layers` | `RiverineInundation`, `CoastalInundation`, `Fire`, `Wind`, `Hail`, `Drought` | Hazard maps offered in the asset panel. `[]` turns them off |
| `hazard_map_bucket` | `os-climate-physical-risk/hazard-indicators/hazard.zarr` | Bucket and folder the wildfire, wind, hail and drought arrays are read from, anonymously. No `s3://` |
| `fire_map_path`, `wind_map_path`, `hail_map_path`, `drought_map_path` | `fire/jupiter/v1/fire_probability_{scenario}_{year}`, `wind/iris/v1/max_speed_{scenario}_{year}`, `hail/jupiter/v1/days_above_5cm_{scenario}_{year}`, `drought/osc/v2/months_spei12m_below_threshold_multi_model_0_{scenario}_{year}` | Array paths, with `{scenario}` and `{year}` once each. Each must stay a resource of its hazard in physrisk's inventory, or the maps return 502. Drought's has the inventory's `{gcm}` filled in as `multi_model_0`, the model physrisk picks |
| `fire_map_max_zoom`, `wind_map_max_zoom`, `hail_map_max_zoom`, `drought_map_max_zoom` | `6`, `7`, `6`, `6` | Deepest zoom with tiles, 0 to 10. Deeper adds nothing at these cell sizes |
| `hazard_map_alpha` | `200` | Opacity of the wildfire, wind, hail and drought tiles, 1 to 255. physrisk draws flood's |
| `hazard_map_legend_stops` | `9` | Colours in the wildfire, wind, hail and drought legends, 2 to 33 |
| `hazard_map_array_cache` | `4` | Arrays kept per layer: about 4 MB each for wildfire, hail and drought, 17 MB for wind |
| `hazard_map_tile_cache` | `256` | Tiles kept per layer |
| `api_port` | `8000` | Port on localhost. `API_PORT` overrides it for `script/start.sh` |
| `aws_access_key_id`, `aws_secret_access_key`, `aws_session_token` | empty | Optional, for geolocate. Prefer `TF_VAR_...` environment variables, and note that the Terraform state holds these in plain text |

Environment variables override the settings in a container: `ASSET_RISK_CONFIG`, `GEOLOCATE_CONFIG`,
`ASSET_RISK_DATA_DIR` and `FLOOD_ZONES_DB`.

## Portfolio CSV

A header containing `id`, `lat` and `lon` (WGS84 degrees). Case and column order don't matter, and
extra columns are ignored.

Two optional columns give each asset a value, for value-weighted figures and losses in money:

| Column | Contents |
|---|---|
| `value` | The asset's value, a plain number such as `1500000` or `1.5e6`. No thousands separators or currency signs |
| `currency` | An ISO 4217 code such as `USD` or `EUR`, in any case. Optional: values without one are shown as plain amounts |

```csv
id,lat,lon,value,currency
empire-state,40.7484,-73.9857,2300000000,USD
big-ben,51.5007,-0.1246,,
```

- A blank value counts as `missing`. A value that isn't a plain number, or is negative or not
  finite (such as `1,000`, `$5M`, `-5` or `inf`), counts as `invalid`. Either way, the asset is
  still assessed and is left out of value-weighted figures only. `0` is a value.
- A file uses one currency. Blank `currency` cells take the file's currency. Two different codes
  reject the file, and nothing is converted.
- A `currency` column without `value` is ignored.

The whole file is rejected if it has missing columns, no rows, duplicate ids, more than one currency,
a currency that isn't a three-letter code, or too many rows or bytes. A bad row doesn't stop a run:
it's kept and reported as `invalid`.

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
To remove one run, use **Delete** on its card on the Portfolios page, or `DELETE /api/runs/{id}`.

## API

Interactive docs are at `/docs` on the running app. Errors are always
`{"detail": "a readable message"}`.

| Endpoint | Purpose |
|---|---|
| `POST /api/runs` | Upload a CSV as the `file` field. Returns 202, or 413 or 422 with the reason |
| `GET /api/runs` | Every run's status, newest first, as on the Portfolios page at `/`. A run whose database can't be read is left out and logged |
| `GET /api/runs/{id}` | Status, stage, progress and any error |
| `DELETE /api/runs/{id}` | Delete a run and its results for good. 204, or 409 while it's queued or running, or while its database is in use |
| `GET /api/runs/{id}/overview` | What the Portfolios page's card needs: summary, trajectory, clusters and the placeable assets' `row_num`, `lat` and `lon`. The card shows the scenario and year the dashboard opens on, so its figures match the dashboard |
| `GET /api/runs/{id}/summary` | Counts, exclusions and shared hazards |
| `GET /api/runs/{id}/assets`, `.../assets/{row_num}` | Assets, or one with its footprint and results |
| `GET /api/runs/{id}/clusters` | DBSCAN clusters with their members, centre and bounds. Empty when none was found |
| `GET /api/runs/{id}/assets/{row_num}/hazard-curve` | River flood depth by return period |
| `GET /api/runs/{id}/hazard-maps` | The hazards with a map (river flood, coastal flood, wildfire, tropical cyclone wind, hail, drought, as enabled by `hazard_map_layers`) for one `scenario` and `year`. Each says what it shows (`measure`, `units`, `return_period`, null when it isn't one event), what a clear area means (`no_data_label`), how to read it (`note`), its `source` and licence, its legend and tile URL, or the reason it has none. 502 if a layer's source no longer matches |
| `GET /api/runs/{id}/hazard-maps/{hazard}/{z}/{x}/{y}.png` | One 512 px map tile, zoom 0 to the layer's `max_zoom` (7 for wind, 6 for the others), for the same `scenario` and `year`. 404 where there's no map, 502 when physrisk or S3 fails |
| `GET /api/runs/{id}/impacts`, `.../totals`, `.../scores` | Results for one `scenario` and `year`. For the baseline, use `scenario=historical` with no year |
| `GET /api/runs/{id}/trajectory`, `.../coverage` | Means by scenario and year, and which hazards each has |
| `GET /api/runs/{id}/export.csv` | Everything, one row per asset, scenario, year and hazard, with each asset's FEMA flood zone, value, currency and expected loss (`aal` × `value`) |
| `GET /api/flood-zone-definitions` | What each FEMA flood zone, insurance rule and lookup status means, with sources |
| `GET /api/config`, `GET /api/health` | Allowed scenarios and limits, and a health check |

Flood tiles are drawn by physrisk on request, through the same lock as a run, so they can be slow
while another run is assessing. Only river and coastal flood have public map images, and `pytest -m
live` checks that after a version bump. Wildfire tiles are drawn by the app from Jupiter
Intelligence's fire probability array, which it reads anonymously from physrisk's public S3 bucket
(`app/engine/fire_map.py`), without that lock. Wind tiles are drawn the same way from IRIS's array
(`app/engine/wind_map.py`), hail tiles from Jupiter's large-hail array (`app/engine/hail_map.py`),
and drought tiles from OS-Climate's 12-month SPEI array (`app/engine/drought_map.py`); all four are
configurations of `app/engine/grid_layer.py`. The first tile for a scenario and year downloads the
whole array: about 4 MB for wildfire (1.4 to 2 s when measured), 73 MB for wind (3.5 to 7 s), under
1 MB for hail (about 0.2 s) and 10 to 13 MB for drought (about 0.5 s). Each layer keeps its last
`hazard_map_array_cache` arrays (4) and `hazard_map_tile_cache` tiles (256) in memory.
`app/engine/hazard_maps.py` builds the layers from the settings. Unit tests check each layer against
physrisk's embedded inventory, and that physrisk's wind, hail and drought models still read the
mapped arrays, so a physrisk bump that changes one fails, and `pytest -m s3` reads real tiles.

Drought's array isn't laid out like the others, so `grid_layer.py`'s `GridSpec` has options for it,
each off by default: `params` fills the inventory path's `{gcm}` with `multi_model_0`, the path is a
zarr group whose `indicator` array is read (the inventory's `store_netcdf_coords`), `index_value` and
`index_attr` pick the SPEI −2 slice from `threshold_values` rather than a return period, and
`zero_is_no_data` draws 0 clear, because the array stores open water as 0.

Each asset carries its FEMA flood zone: `fema_status` (`mapped`, `not_mapped`, `not_us`,
`not_located` or `unavailable`), `fema_zone` and `fema_zone_subtype` as FEMA writes them,
`fema_zone_key` (a key in `/api/flood-zone-definitions`, which splits Zone X into `X_SHADED`,
`X_UNSHADED` and `X`), `in_sfha`, `base_flood_elevation` with its unit and datum, `fema_depth` with its
unit, `fema_dfirm_id`, `fema_matches` (FEMA areas covering the point) and `fema_conflict` (they
disagree on the zone). An asset's detail adds `fema_map_as_of`. Runs from before the lookup existed
read as `unavailable`.

Results return 409 until a run is `completed`. Assets are addressed by `row_num`, because an invalid
row can have no id. Runs that were queued or running when the app stopped are marked `interrupted`,
and need uploading again.

## Run database

Each run has `runs/<uuid>/run.duckdb`, which you can query directly:

| Table or view | Contents |
|---|---|
| `runs` | Status and progress |
| `assets` | One row per input row: geolocate's output plus classification |
| `asset_clusters` | The DBSCAN cluster of each clustered asset. Noise has no row, and runs made before clustering have no table |
| `asset_flood_zones` | Each asset's FEMA flood zone and lookup status. Runs made before the lookup have no table |
| `asset_values`, `portfolio_values` | Each asset's value and `value_status` (`given`, `missing` or `invalid`), and the portfolio's currency. Runs made before values have neither table, and read as having no values |
| `flood_zone_source` | Which FEMA data the run used, and its date. Empty when there was none |
| `assessment_pairs` | Each scenario and year requested |
| `impacts`, `scores` | Results, keyed on `row_num`, `scenario` and `year`. The baseline has year NULL |
| `assess_failures` | Failed batches |
| `v_portfolio_summary`, `v_exclusions` | Counts |
| `v_asset_totals`, `v_asset_hazard_aal`, `v_asset_scores` | Results per asset |
| `v_portfolio_trajectory`, `v_portfolio_hazards` | Means, including over shared hazards. The trajectory also has value-weighted means and expected losses |
| `v_asset_expected_loss`, `v_portfolio_value_weighted` | AAL × value per asset, and its value-weighted sums, over assets with a `given` value |
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

Measured in Docker on a machine with 4 CPUs and 5.8 GB of memory, with 2 scenarios (the default
before ssp126 was added) and 3 years, using points around 25 large cities. Memory was sampled every
few seconds, so its peak is approximate. The default is now 3 scenarios, so expect the assessing
stage to take about half as long again.

| Rows | Time | Peak memory |
|---|---|---|
| 40 | 55 s | 0.8 GB |
| 100 | 69 s | 0.7 GB |
| 1,000 | 10 min 14 s | 2.3 GB |

The FEMA flood zone stage took 7.8 s for 5,000 points spread across the US, outside Docker, and
well under a second for a few dozen.

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
.venv/bin/pytest -m fema                # known locations against FEMA's live flood map
npm --prefix app/front test
npm --prefix app/front run typecheck
npm --prefix app/front run dev          # proxies /api to port 8000
```

After changing the API, regenerate the front end's types:

```bash
.venv/bin/python script/export_openapi.py && npm --prefix app/front run gen:api
```

After a visible change to the app, record the demo GIF again. Each new version stays in git
history, so don't do this for small changes:

```bash
uvx playwright@1.64.1 install chromium-headless-shell   # once
uv run script/record_demo.py --build
```

It runs the [demo portfolio](assets/demo_portfolio.csv) for real in its own compose project and
volume, opens the New Orleans cluster on the map, clicks `US-312`, shows its FEMA flood zone and
what the zone means, zooms its hazard map out to southern Louisiana, and switches it to coastal
flood, wildfire and tropical cyclone wind. A wildfire or wind map with no data for the dashboard's
scenario and year is shown for the historical period instead. It needs the FEMA flood zone database
that `flood_zones_db` names, and mounts it the way `script/start.sh` does. It stops if that database
is missing, the run fails, the upload and progress take 2 s or more, the map doesn't load,
no cluster contains New Orleans, no bubble on screen can be matched to that cluster, `US-312` can't
be clicked on the map, isn't mapped in a levee-protected Zone X as its caption says, a wildfire or
wind layer isn't in `hazard_map_layers` or has no map for the period, or its hazard maps load no
tile. Without `--build` it reuses the existing image. The upload and progress screens get one short
frame per stage the page shows as current, and it reports those stages.

A narrated 60-second video of the same tour is made the same way, and the README shows it. It
isn't committed:

```bash
uv run script/record_video.py --build        # writes docs/assets/demo.mp4
uv run script/record_video.py --voice-only   # just voice the narration and time the scenes
```

GitHub only plays a README video from its own attachments: drag the file into a comment box on
GitHub and use the `https://github.com/user-attachments/assets/...` link it gives. Free plans take
videos up to 10 MB, so the README's copy is cut to 53 s, inside the end card, and encoded in two
passes at 1.45 Mbit/s:

```bash
ffmpeg -i docs/assets/demo.mp4 -t 53 -c:v libx264 -preset veryslow -b:v 1450k -pass 1 -an -f mp4 /dev/null
ffmpeg -i docs/assets/demo.mp4 -t 53 -c:v libx264 -preset veryslow -b:v 1450k -pass 2 \
  -pix_fmt yuv420p -c:a aac -b:a 160k -movflags +faststart demo-github.mp4
```

It reuses the GIF script's stack, upload and map steps, so it needs the same things, plus torch
(CPU) and the Kokoro-82M weights, which the first run downloads. The narration is in `SCENES` in
the script. Each line is voiced with Kokoro (voice `af_heart`, or `--voice`) and cached in
`~/.cache/asset-risk/voice`. A scene lasts as long as its line plus 0.4 s, and its beats land on
the words Kokoro times. Over 60 s, the padding shrinks to 0.2 s and then the voice speeds up to
1.1, and past that the script stops rather than cut a line. Under 58 s, the end card is held
longer. The page is recorded at 1920x1080 and device scale 2, map animations are stepped at 30 fps
on Playwright's fake clock, and each shot keeps the box of the element its line is about. Pillow
zooms in on those boxes (at most 2.2x) only for the upload and the asset panel, whose text is too
small at full frame, and only moves the camera when the box changes. ffmpeg burns in the narration
as subtitles and
normalises the voice to -16 LUFS. `--frames DIR` keeps the shots, and `--from-frames DIR` makes
the video again from them without Docker or the browser. It stops for the same reasons as the GIF
script, and also if the dashboard's sections are recorded in another order than the
narration's.

`script/overture_values.py` audits the building type map against a live release, and
`script/build_regions.py` rebuilds the region data.
