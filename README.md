# asset-risk

Upload a CSV of `id, lat, lon` and get a physical climate risk view of the portfolio. Each point is
matched to a building with [geolocate](https://github.com/mnovovil/geolocate), assessed with
[physrisk](https://github.com/os-climate/physrisk), and shown in a web dashboard.

This is a screening tool, not a site-level assessment. Results are a share of asset value, and
[most buildings have no known type](docs/methodology.md#building-type), so read
[the methodology](docs/methodology.md) before relying on a number.

![Uploading the sample CSV, following the geolocating, classifying and assessing stages, then going through the dashboard's figures, map, charts, asset details and data quality notes](docs/assets/demo.gif)

*A real run of the [sample CSV](app/front/public/sample_portfolio.csv), with the stages sped up. Its
figures are screening estimates for illustration. Map data © OpenStreetMap contributors, via
OpenFreeMap and OpenMapTiles.*

## Quick start

You need Docker, [Terraform](https://developer.hashicorp.com/terraform/install) ≥ 1.3 or OpenTofu,
several GB of free disk for the first build, and internet access.

```bash
git clone --recurse-submodules git@github.com:mnovovil/asset-risk.git && cd asset-risk
terraform -chdir=infra init && terraform -chdir=infra apply   # writes the settings files
script/start.sh                                               # http://127.0.0.1:8000
```

Open the address and drop in a CSV. The page has a sample to download, and your file needs a header
with these columns:

```csv
id,lat,lon
empire-state,40.7484,-73.9857
big-ben,51.5007,-0.1246
```

The app has no login, so it only listens on localhost. Don't expose it as it stands.

## How it works

```mermaid
flowchart TB
    csv["CSV of id, lat, lon"] --> front["Website<br/>app/front"]
    front --> api["API and run queue<br/>app/engine/api.py"]

    subgraph run["Each run: app/engine/pipeline.py"]
        ingest["Check the CSV"] --> locate["Find each point's building<br/>geolocate"]
        locate --> classify["Choose the physrisk type and region<br/>classify.py"]
        classify --> assess["Calculate risk per scenario and year<br/>physrisk"]
    end

    api --> ingest
    overture[("Overture buildings<br/>on S3")] --> locate
    hazards[("physrisk hazard data<br/>on S3")] --> assess
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
