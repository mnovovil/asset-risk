# Learnings

Append-only knowledge base. See `.claude/skills/compound/SKILL.md` for rules and categories.

---

### [Performance] The physrisk stage sets a run's time, and small portfolios mislead — 2026-10-30

In Docker on 4 CPUs with 2 scenarios and 3 years, 40 rows took 55 s and 100 rows 69 s, but 1,000 rows took 614 s, of which about 560 s was assessing. About 20 s of a small run is fixed startup cost in the geolocating stage, so timing a small run says little about a large one. Peak memory went from 0.7 GB at 100 rows to 2.3 GB at 1,000, and 5,000 rows is still unmeasured.

### [Testing] `find /` as a non-root container user exits non-zero on unreadable folders — 2026-10-30

The test that the image holds no secrets failed with `CalledProcessError`, not because it found anything, but because `find` can't read some folders as the image's user and exits 1. Run it with `--user root`. Otherwise a test using `check=True` fails on a clean image, and without `check=True` it can pass while having skipped those folders.

### [Deployment] A first image build can fill a small disk — 2026-10-30

The image is 1.65 GB, mostly physrisk's dependencies, but the first build needed several GB more and ran a 56 GB disk out of space when Docker's build cache was already at 10 GB. `docker system df` is the place to look, and `docker builder prune` affects every project on the machine.
