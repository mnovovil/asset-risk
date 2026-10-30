# CE Project Configuration

Single source of project-specific values for the `/ce:*` commands and skills.
Fill in the placeholders. Any section left as `TBD` is skipped by the commands.

## Repository

- **Repo**: `mnovovil/asset-risk` (e.g. `owner/name` — if TBD, commands use `gh repo view --json nameWithOwner --jq .nameWithOwner`)
- **Base branch** (PRs target this): `main` (if TBD, use the repo's default branch)
- **Release branch** (production, if different): `TBD`
- **Branch naming**: `feat/<issue>-<slug>`, `fix/<issue>-<slug>`, `chore/<issue>-<slug>`
- **Commit style**: Conventional commits — `feat:`, `fix:`, `ci:`, `chore:`, `docs:`, `test:`, `refactor:`
- **Merge strategy**: squash

## Commands

| Purpose | Command |
|---------|---------|
| Install deps | `git submodule update --init && uv venv .venv && uv pip install -p .venv -r requirements-dev.txt` |
| Lint (+fix) | `.venv/bin/ruff check --fix .` |
| Format | `.venv/bin/ruff format .` |
| Type check | `TBD` |
| Unit tests | `.venv/bin/pytest` |
| Integration / E2E tests | `.venv/bin/pytest -m s3` (live Overture S3), `-m live` (live physrisk data), `-m e2e` (compose stack); all opt-in |
| Start local services | `TBD` |

## Code Areas

Path prefixes used to group changes (`/ce:update`) and tag plan steps (`/ce:plan`).

| Area tag | Paths | Notes |
|----------|-------|-------|
| `[engine]` | `app/engine/**` | Python data computation and API |
| `[front]` | `app/front/**` | TypeScript website |
| `[test]` | `test/**` | Test suite (`test/engine`, `test/front`) |
| `[script]` | `script/**` | Ad-hoc CLIs and tooling |
| `[vendor]` | `vendor/**`, `.gitmodules` | Pinned geolocate submodule — change by bumping the pin, never by editing |
| `[docker]` | `docker/**` | Image and compose stack for the app |
| `[docs]` | `README.md`, `docs/**` | User-facing docs |
| `[infra]` | `infra/**` | Infrastructure — may require a manual apply after merge |
| `[ci]` | `.github/**` | CI/CD |
| `[claude]` | `.claude/**`, `CLAUDE.md` | Agent config / conventions |

## Issue Tracking (optional)

- **Issue title prefix**: `TBD` (e.g. `[SERVICE]`; leave TBD for none)
- **Labels**: `TBD`
- **Issue types** (GraphQL IDs): Feature=`TBD`, Bug=`TBD`, Chore=`TBD`, Improvement=`TBD`
- **Milestones**: `TBD`

## GitHub Project Board (optional)

If all IDs are filled in, `/ce:plan`, `/ce:work` and `/ce:merge` move issues across statuses. Otherwise those steps are skipped.

- **Project ID**: `TBD`
- **Status field ID**: `TBD`
  - Backlog=`TBD`, Todo=`TBD`, In Progress=`TBD`, To Review=`TBD`, Done=`TBD`
- **Priority field ID**: `TBD`
  - Very High=`TBD`, High=`TBD`, Normal=`TBD`, Low=`TBD`

Look up IDs with:

```bash
gh project list --owner <owner>
gh project field-list <number> --owner <owner> --format json
```

## Scaffold Recipes (`/scaffold`)

Each recipe mirrors an existing, known-good unit. `{name}` is the new unit's snake_case name.

| Recipe | Reference | Files | Register in | Follow-up |
|--------|-----------|-------|-------------|-----------|
| `TBD` (e.g. `endpoint`) | `TBD` (e.g. `user`) | `TBD` (e.g. `src/api/{name}.py`, `src/services/{name}.py`, `tests/test_{name}.py`) | `TBD` (e.g. `src/api/__init__.py`) | `TBD` (e.g. create migration, `/sync-generated`) |

## Generated Artifacts (`/sync-generated`)

Files derived from another source. Add their outputs to `.claude/protected-paths` so they aren't hand-edited.

| Artifact | Source | Precondition | Fetch | Generate | Outputs | Verify |
|----------|--------|--------------|-------|----------|---------|--------|
| `api-types` (exists once #7 and #8 land) | FastAPI schemas in `app/engine/` | `app/front` dependencies installed | `.venv/bin/python script/export_openapi.py` | `npm --prefix app/front exec openapi-typescript -- openapi.json -o src/api/schema.d.ts` | `app/front/src/api/schema.d.ts` | `npm --prefix app/front run typecheck` |

## Flagged Paths (`/ce:update`)

Changes under these paths are called out after a pull:

- `infra/**` — infrastructure changed; a manual apply may be needed
- `vendor/**`, `.gitmodules` — geolocate pin changed; run `git submodule update --init` and re-apply `infra/`
- `**/migrations/**` — new DB migrations; run them locally
- `.env.example` — new env vars; check secrets are wired in every environment
- `CLAUDE.md`, `.claude/**` — conventions or skills changed; worth a read
