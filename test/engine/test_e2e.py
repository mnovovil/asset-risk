"""The whole path, through Docker, over HTTP, with live Overture and physrisk data.

Opt-in with `pytest -m e2e`. It uses its own project, port and volume, so it can't touch a running
copy of the app.
"""

import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "app" / "front" / "public" / "sample_portfolio.csv"
PROJECT = "asset-risk-e2e"
PORT = "18767"
BASE = f"http://127.0.0.1:{PORT}/api"
RUN_TIMEOUT_SECONDS = 300


def _compose(*args: str, timeout: int = 120) -> None:
    env = os.environ | {
        "API_PORT": PORT,
        "HOST_UID": str(os.getuid()),
        "HOST_GID": str(os.getgid()),
    }
    compose_file = str(ROOT / "docker" / "compose.yml")
    subprocess.run(
        ["docker", "compose", "-p", PROJECT, "-f", compose_file, *args],
        env=env,
        check=True,
        capture_output=True,
        timeout=timeout,
    )


def _get_bytes(path: str) -> bytes:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=30) as response:
        return response.read()


def _get(path: str):
    return json.loads(_get_bytes(path))


def _upload(path: Path) -> dict:
    boundary = uuid.uuid4().hex
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{path.name}"\r\nContent-Type: text/csv\r\n\r\n'
    ).encode()
    body += path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"{BASE}/runs",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        assert response.status == 202
        return json.loads(response.read())


@pytest.fixture(scope="module")
def run_id():
    try:
        _compose("up", "--build", "--detach", timeout=1200)
        for _ in range(60):
            try:
                if _get("/health") == {"status": "ok"}:
                    break
            except OSError:
                time.sleep(1)
        else:
            raise AssertionError("The app didn't start")

        identifier = _upload(SAMPLE)["run_id"]
        deadline = time.monotonic() + RUN_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            status = _get(f"/runs/{identifier}")
            if status["status"] not in ("queued", "running"):
                break
            time.sleep(2)
        assert status["status"] == "completed", status
        yield identifier
    finally:
        _compose("down", "--volumes")


@pytest.mark.e2e
def test_each_outcome_is_reported(run_id):
    summary = _get(f"/runs/{run_id}/summary")
    assert summary["total_assets"] == 6
    assert summary["assessable"] == 4
    assert summary["failed_assets"] == 0
    assert {e["reason"]: e["assets"] for e in summary["exclusions"]} == {
        "invalid": 1,
        "off_land": 1,
    }


@pytest.mark.e2e
def test_assets_are_classified(run_id):
    assets = {a["asset_id"]: a for a in _get(f"/runs/{run_id}/assets")}
    assert assets["empire-state"]["class"] == "office"
    assert assets["empire-state"]["physrisk_type"] == "Buildings/Commercial"
    assert assets["empire-state"]["region"] == "North America"
    assert assets["nairobi-centre"]["physrisk_location"] == "Global"
    assert assets["mid-atlantic"]["exclusion_reason"] == "off_land"
    assert assets["bad-latitude"]["exclusion_reason"] == "invalid"


@pytest.mark.e2e
def test_results_exist_for_every_configured_scenario_and_year(run_id):
    config = _get("/config")
    trajectory = {(p["scenario"], p["year"]): p for p in _get(f"/runs/{run_id}/trajectory")}
    assert trajectory[("historical", None)]["assets"] == 4
    for scenario in config["scenarios"]:
        for year in config["years"]:
            assert (scenario, year) in trajectory
            query = urllib.parse.urlencode({"scenario": scenario, "year": year})
            assert isinstance(_get(f"/runs/{run_id}/impacts?{query}"), list)
            assert isinstance(_get(f"/runs/{run_id}/scores?{query}"), list)


@pytest.mark.e2e
def test_scenarios_are_comparable_on_shared_hazards(run_id):
    summary = _get(f"/runs/{run_id}/summary")
    assert summary["shared_hazards"]
    for point in _get(f"/runs/{run_id}/trajectory"):
        if point["assets"] > 0:
            assert point["mean_shared_aal"] is not None


@pytest.mark.e2e
def test_export_has_every_asset(run_id):
    text = _get_bytes(f"/runs/{run_id}/export.csv").decode()
    for asset_id in ("empire-state", "mid-atlantic", "bad-latitude"):
        assert asset_id in text


@pytest.mark.e2e
def test_a_bad_portfolio_is_rejected(tmp_path, run_id):
    bad = tmp_path / "bad.csv"
    bad.write_text("id,lat\na,1\n")
    with pytest.raises(urllib.error.HTTPError) as error:
        _upload(bad)
    assert error.value.code == 422
    assert "lon" in json.loads(error.value.read())["detail"]
