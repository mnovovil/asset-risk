# asset-risk

Upload a CSV of `id, lat, lon` and get a physical climate risk view of the portfolio. Each point is
matched to a building with [geolocate](https://github.com/mnovovil/geolocate), assessed with
[physrisk](https://github.com/os-climate/physrisk), and shown in a web dashboard.

This is a screening tool, not a site-level assessment. Results are a share of asset value, and
[most buildings have no known type](docs/methodology.md#building-type), so read
[the methodology](docs/methodology.md) before relying on a number.

https://github.com/user-attachments/assets/97d704e0-aa61-42ec-8060-1aaca6f5165f

## Quick start

You need Docker, [Terraform](https://developer.hashicorp.com/terraform/install) ≥ 1.3 or OpenTofu,
several GB of free disk for the first build, and internet access.

```bash
git clone --recurse-submodules git@github.com:mnovovil/asset-risk.git && cd asset-risk
terraform -chdir=infra init && terraform -chdir=infra apply   # writes the settings files
script/start.sh                                               # http://127.0.0.1:8000
```

For FEMA flood zones on US assets, build their database once from FEMA's flood hazard data (see
[Data sources](docs/data-sources.md#fema-flood-zones)). Without it, runs work as usual and show the
zones as unavailable.

Open the address to see every portfolio assessed so far, each as a card with its mean annual loss,
its counts and a picture of its risk map. **Delete** removes a finished one. Choose
**New portfolio** and drop in a CSV. The upload page has a sample to download, and your file needs a header with these columns:

```csv
id,lat,lon
empire-state,40.7484,-73.9857
big-ben,51.5007,-0.1246
```

You can add a `value` column, and a `currency` such as `USD`, for value-weighted results and
expected losses in money: the dashboard then offers **Weighting: By value**. See
[Portfolio CSV](docs/reference.md#portfolio-csv) for the rules and
[the methodology](docs/methodology.md#weighting-by-value) for how to read them.

A finished portfolio's page has two downloads beside its filters: **Download results as CSV**, with
every figure, and **Download report as PDF**, the map, loss bars and change over time for the
selected scenario, year and map colouring. The browser builds the PDF itself, so it needs the map
tiles to load.

The app has no login, so it only listens on localhost. Don't expose it as it stands.

## How it works

```mermaid
flowchart TB
    csv["CSV of id, lat, lon"] --> front["Website<br/>app/front"]
    front --> api["API and run queue<br/>app/engine/api.py"]

    subgraph run["Each run: app/engine/pipeline.py"]
        ingest["Check the CSV"] --> locate["Find each point's building<br/>geolocate"]
        locate --> classify["Choose the physrisk type and region<br/>classify.py"]
        classify --> flood["Find each US point's FEMA flood zone<br/>flood_zones.py"]
        flood --> assess["Calculate risk per scenario and year<br/>physrisk"]
    end

    api --> ingest
    overture[("Overture buildings<br/>on S3")] --> locate
    hazards[("physrisk hazard data<br/>on S3")] --> assess
    fema[("FEMA flood zones<br/>data/fema")] --> flood
    assess --> db[("One DuckDB file per run")]
    db --> api
    tf["Terraform variables<br/>infra/"] --> settings[".asset-risk.json"]
    settings --> api
```

## Project layout

| Path | Contents |
|---|---|
| `app/engine` | Python computation and API |
| `app/front` | TypeScript website |
| `docker` | Image and compose stack |
| `docs` | [Reference](docs/reference.md), [methodology](docs/methodology.md), [data sources](docs/data-sources.md) and the physrisk demo notebook |
| `infra` | Terraform variables |
| `script` | Start script and ad-hoc tools |
| `test` | Tests |
| `vendor/geolocate` | geolocate, pinned as a submodule |

Settings, the API, performance and development commands are in the [reference](docs/reference.md).

## Branches and pull requests

All work goes through `dev`. `main` only receives releases from `dev`.

```mermaid
gitGraph
    commit id: "release 1"
    branch dev
    checkout dev
    branch feat/42-thing
    checkout feat/42-thing
    commit id: "work"
    commit id: "more work"
    checkout dev
    merge feat/42-thing id: "PR #42, squash" type: HIGHLIGHT
    branch fix/43-bug
    checkout fix/43-bug
    commit id: "fix"
    checkout dev
    merge fix/43-bug id: "PR #43, squash" type: HIGHLIGHT
    checkout main
    merge dev id: "release PR, merge commit" type: HIGHLIGHT
```

- Branch from `dev` and open the PR against `dev`. It's squash-merged.
- A release is a PR from `dev` to `main`, merged with a merge commit (never squashed, so the two
  branches keep sharing history).
- PRs into `main` from any other branch fail the `Source branch` check.
- Every PR needs green CI: `Source branch`, `Engine`, `Front end` and `Infra`.
- No direct pushes, force pushes or deletion on `dev` or `main`.

## License

[MIT](LICENSE). `vendor/geolocate`, physrisk and the data sources have their own terms.

## About the demo video

A real run of the [demo portfolio](docs/assets/demo_portfolio.csv), 500 properties in the USA and
Spain. Its figures are screening estimates, its flood zone isn't an official determination, and a
low score doesn't make an asset low risk.

Voice by Kokoro-82M. Map data © OpenStreetMap contributors, via OpenFreeMap and OpenMapTiles.
Hazard maps from WRI Aqueduct Floods, Jupiter Intelligence and IRIS, via physrisk. Flood zones
from FEMA's National Flood Hazard Layer.
