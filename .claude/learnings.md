# Learnings

Append-only knowledge base. See `.claude/skills/compound/SKILL.md` for rules and categories.

---

### [Performance] The physrisk stage sets a run's time, and small portfolios mislead — 2026-10-30

In Docker on 4 CPUs with 2 scenarios and 3 years, 40 rows took 55 s and 100 rows 69 s, but 1,000 rows took 614 s, of which about 560 s was assessing. About 20 s of a small run is fixed startup cost in the geolocating stage, so timing a small run says little about a large one. Peak memory went from 0.7 GB at 100 rows to 2.3 GB at 1,000, and 5,000 rows is still unmeasured.

### [Testing] `find /` as a non-root container user exits non-zero on unreadable folders — 2026-10-30

The test that the image holds no secrets failed with `CalledProcessError`, not because it found anything, but because `find` can't read some folders as the image's user and exits 1. Run it with `--user root`. Otherwise a test using `check=True` fails on a clean image, and without `check=True` it can pass while having skipped those folders.

### [Deployment] A first image build can fill a small disk — 2026-10-30

The image is 1.65 GB, mostly physrisk's dependencies, but the first build needed several GB more and ran a 56 GB disk out of space when Docker's build cache was already at 10 GB. `docker system df` is the place to look, and `docker builder prune` affects every project on the machine.

### [Data] physrisk can return scores but no impacts for a year, with no error — 2026-11-11

A run that asked for 2025 got 54 rows in `scores` for each scenario's 2025, 0 in `impacts` and nothing in `assess_failures`. The pair still sits in `assessment_pairs`, so `v_portfolio_trajectory` lists it with `assets = 0`, and the dashboard offered a year that only ever said "no results". Settings now allow only 2030, 2050 and 2080. When a year looks empty, count `impacts` and `scores` separately in the run's DuckDB: scores existing doesn't mean impacts do.

### [Deployment] Docker runs aren't in `data/` on the host — 2026-11-11

The compose stack writes runs to the `asset-risk_data` volume, so `data/runs` on the host holds only runs from `script/serve.py` and can look fine while the app shows the problem. To inspect a Docker run, copy its `run.duckdb` out with a throwaway container, e.g. `docker run --rm -v asset-risk_data:/d:ro -v "$OUT":/o alpine cp /d/runs/<id>/run.duckdb /o/`, and open it with `.venv/bin/python`. Also, the local git-ignored `infra/terraform.tfvars` overrides the `variables.tf` defaults, which is how 2025 got into runs while the default was `[2030, 2050, 2080]`.

### [Testing] Driving the dashboard with Playwright has three traps — 2026-11-12

`get_by_label("Scenario")` matches two elements: the filter's `<label>` wraps its `<select>`, so the select's accessible name includes every option, and the trajectory chart's `aria-label` mentions scenarios too. Scope it as `.filters label` with `has_text`, then `select`. The asset panel's `h2` reads "Asset" until the details load, so wait for the heading by name rather than reading it once. And `mouse.move(0, 0)` after a map click leaves the MapLibre popup open in every later frame, because the pointer leaves the canvas without a mousemove on it; dispatch a `mousemove` on `.map canvas` at a spot with nothing under it.

### [Data] Zero flood loss at a point can sit inside a flooded hazard map — 2026-11-12

`US-241` in the demo portfolio is in mid-channel in the Mississippi. physrisk gives it 0% river and coastal flood loss and a flat depth curve, yet its 1-in-1000-year flood maps are coloured all around it, because the curve is for the exact point and the map's cells are about 1 km. Check the map before captioning a zero as "no flood here": the app's own wording, "this exact point is dry in the data", is the accurate one.

### [Testing] Zooming the panel's hazard map in headless Chromium — 2026-11-12

A 500 px `mouse.wheel` step zooms the MapLibre map out by about 0.56 levels, so 15 steps take it from street level (zoom 14) to about 5.6, Houston to Mobile. Zooming keeps the spot under the pointer fixed, so the pointer's position sets where the asset ends up. Probe with `page.screenshot(clip=box)`: an element screenshot scrolls the page and moves the map out from under the pointer, so later wheel steps miss it.

### [Dependencies] `uv run --with` in the repo root writes a `uv.lock` — 2026-11-12

The repo has a `pyproject.toml`, so `uv run --with <pkg> python ...` from the root resolves the project and leaves an untracked `uv.lock`. Use `uv run --no-project`, or run from a folder outside the repo, for one-off tools.
