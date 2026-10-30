import importlib
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAX_DEMO_GIF_BYTES = 8 * 1024 * 1024


@pytest.mark.parametrize(
    "folder",
    ["app/engine", "app/front", "docker", "docs", "infra", "script", "test/engine", "test/front"],
)
def test_expected_folders_exist(folder):
    assert (ROOT / folder).is_dir()


def test_geolocate_submodule_present():
    assert (ROOT / "vendor/geolocate/src/geolocate.py").is_file(), (
        "vendor/geolocate is empty: run `git submodule update --init`"
    )


def test_engine_importable():
    importlib.import_module("engine")


@pytest.mark.parametrize(
    "path",
    [
        ".asset-risk.json",
        "infra/terraform.tfstate",
        "infra/terraform.tfvars",
        "data/runs/x/run.duckdb",
    ],
)
def test_sensitive_and_run_files_are_ignored(path):
    assert subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 0


@pytest.mark.parametrize("path", ["app/engine/data/countries.geojson", "infra/x.tfvars.example"])
def test_committed_files_are_not_ignored(path):
    assert subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 1


def test_readme_demo_gif_exists_and_stays_small():
    assert "(docs/assets/demo.gif)" in (ROOT / "README.md").read_text()
    # Each version stays in git history for good, and the README loads the whole file.
    assert (ROOT / "docs/assets/demo.gif").stat().st_size < MAX_DEMO_GIF_BYTES
