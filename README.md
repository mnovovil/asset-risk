# asset-risk

Upload a CSV of `id, lat, lon` and get a physical climate risk view of the portfolio. Each point is
matched to a building with [geolocate](https://github.com/mnovovil/geolocate), assessed with
[physrisk](https://github.com/os-climate/physrisk), and shown in a web dashboard. Give each asset
a value and the results can also be weighted by it, and an optional analyst running on your own
machine answers questions about a finished portfolio, with every number it quotes checked.

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
**New portfolio** and drop in a CSV. The upload page has a sample to download, and your file needs
a header with at least id, lat, lon columns. You can add a `value` column, and a `currency` such as `USD`, for value-weighted results and
expected losses in money:

```csv
id,lat,lon,value,currency
empire-state,40.7484,-73.9857,2300000000,USD
big-ben,51.5007,-0.1246,,
```

A missing or unreadable value never drops an asset: it's still assessed, flagged, and left out of
the weighting. The dashboard then offers **Weighting: By value** beside the default equal weighting.
See [Portfolio CSV](docs/reference.md#portfolio-csv) for the rules and
[the methodology](docs/methodology.md#weighting-by-value) for how to read them.

A finished portfolio's page has two downloads beside its filters: **Download results as CSV**, with
every figure, and **Download report as PDF**, the map, loss bars and change over time for the
selected scenario, year and map colouring. With values, the CSV adds each asset's value and expected
loss, and the PDF follows the selected weighting. The browser builds the PDF itself, so it needs the map tiles to load.

### Asking the analyst (optional)

A finished portfolio's page can have an **Ask the analyst** chat, where Claude answers questions
about the run, such as "Which assets have the highest flood loss under ssp585 in 2050?". It reads
the results only through read-only tools, and every number in its answer is checked against what
those tools returned. An answer whose numbers don't all match is marked **Unverified figures**.

The model runs on Anthropic's API, so **the tool results it reads leave the machine**: portfolio
figures, and for any asset it looks up, its row number, id, coordinates, building, values and
results. Leave the analyst off for a portfolio that mustn't be shared.

It's off by default. To turn it on:
1. Get an API key. A Max, Ultra or Team plan includes monthly
   [API credits](https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers):
   claim them on claude.ai under Settings → Billing → API credits, linking a Claude Console
   organization. In the Console, create a workspace for asset-risk with a spend limit, and a key in
   it.
2. Set `analyst_enabled = true` in `infra/terraform.tfvars` and run `terraform -chdir=infra apply`.
   Never put the key there: Terraform state holds every variable in plain text.
3. `export ANTHROPIC_API_KEY=...` and start with `script/start.sh`, which refuses to start without
   it. Compose passes it to the app, and nothing writes it to disk.

Each tool call is another billed call to the model, so `analyst_max_calls` (5 by default, up to 10)
caps the cost of one question, and only one question is answered at a time. When the credits run
out, the chat says so and the rest of the dashboard works the same. `analyst_model` picks the model
(`claude-opus-5-5` by default; `claude-sonnet-5-5` or `claude-haiku-5-5` cost less). See
[the methodology](docs/methodology.md#the-analyst) for what it can and can't tell you.

The app has no login, so it only listens on localhost. Don't expose it as it stands. It also
refuses any request addressed to a host name other than `localhost`, `127.0.0.1` or `[::1]`, so
that a web page can't reach it by pointing its own domain at your machine (DNS rebinding). Opening
it as `http://<machine-name>:8000`, by a LAN address or behind a reverse proxy returns 400.

## How it works

```mermaid
flowchart TB
    csv["CSV of id, lat, lon<br/>optional value, currency"] --> front["Website<br/>app/front"]
    front --> api["API and run queue<br/>app/engine/api.py"]

    subgraph run["Each run: app/engine/pipeline.py"]
        ingest["Check the CSV and its values<br/>ingest.py"] --> locate["Find each point's building<br/>geolocate"]
        locate --> classify["Choose the physrisk type and region<br/>classify.py"]
        classify --> flood["Find each US point's FEMA flood zone<br/>flood_zones.py"]
        flood --> assess["Calculate risk per scenario and year<br/>physrisk"]
    end

    api --> ingest
    overture[("Overture buildings<br/>on S3")] --> locate
    hazards[("physrisk hazard data<br/>on S3")] --> assess
    fema[("FEMA flood zones<br/>data/fema")] --> flood
    assess --> db[("One DuckDB file per run<br/>equal- and value-weighted views")]
    ingest -->|"asset values"| db
    db --> api

    subgraph analyst["Portfolio analyst, optional: analyst_enabled"]
        chat["Chat endpoint<br/>POST /api/runs/{id}/chat"] --> loop["Model loop and grounding check<br/>analyst.py"]
        loop <-->|"one JSON reply at a time"| claude["Claude<br/>Anthropic API, key from ANTHROPIC_API_KEY"]
        loop <-->|"tool calls and results"| tools["Read-only tools<br/>analyst_tools.py"]
    end

    front -->|"Ask the analyst"| chat
    tools --> db
    loop -->|"answer, verified or not"| front

    tf["Terraform variables<br/>infra/"] --> settings[".asset-risk.json"]
    settings --> api
    settings --> loop
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