# asset-risk

Physical climate risk for a portfolio of `id, lat, lon` points. Each point is matched to a building
with [geolocate](https://github.com/mnovovil/geolocate), assessed with
[physrisk](https://github.com/os-climate/physrisk), and shown in a web dashboard.

Under construction: the plan is in [issue #1](https://github.com/mnovovil/asset-risk/issues/1).

## Setup

```bash
git clone --recurse-submodules git@github.com:mnovovil/asset-risk.git && cd asset-risk
uv venv .venv && uv pip install -p .venv -r requirements-dev.txt
.venv/bin/pytest
```

If you cloned without `--recurse-submodules`, run `git submodule update --init`.

## Run it

Needs Docker, and [Terraform](https://developer.hashicorp.com/terraform/install) or OpenTofu.

```bash
terraform -chdir=infra init && terraform -chdir=infra apply   # writes the settings files
script/start.sh                                               # http://127.0.0.1:8000
```

The app has no login, so it only listens on localhost. Don't expose it as it stands.

## Layout

| Path | Contents |
|---|---|
| `app/engine` | Python data computation and API |
| `app/front` | TypeScript website |
| `docker` | Image and compose stack |
| `docs` | Documentation and `physrisk_demo.ipynb` |
| `infra` | Terraform variables |
| `script` | Ad-hoc scripts |
| `test` | Tests |
| `vendor/geolocate` | Pinned geolocate submodule |

To run the notebook, also install `matplotlib` and `ipykernel`.
