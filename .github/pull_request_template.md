## Summary

<!-- What does this PR do? 1-3 bullet points. Link the issue: Closes #N -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactoring (no functional change)
- [ ] CI / infrastructure / Docker
- [ ] Documentation
- [ ] Release (`dev` → `main`)

## Checklist

- [ ] Targets `dev` (only release PRs target `main`)
- [ ] Lint and format pass (`.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`)
- [ ] Tests pass and cover the change (`.venv/bin/pytest`, `npm --prefix app/front test`)
- [ ] After an API change: `openapi.json` and `schema.d.ts` regenerated (`/sync-generated`)
- [ ] Contracts in `CLAUDE.md` changed on both sides (for example `.asset-risk.json` in `infra/` and `settings.py`)
- [ ] `type_source` stays visible, and "No model" and "No data" stay distinct from a low score, wherever results are shown
- [ ] Nothing under `vendor/` edited, and no `.asset-risk.json`, `.geolocate.json`, `*.tfstate*` or `*.tfvars` committed

## Manual testing

<!-- What to run or open, what to do, and what you should see -->
