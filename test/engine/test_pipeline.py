from dataclasses import replace

import pytest

from engine import pipeline
from engine.assess import Assessment
from engine.ingest import PortfolioError
from engine.pipeline import execute, start
from engine.store import status


@pytest.fixture
def csv_path(tmp_path):
    path = tmp_path / "portfolio.csv"
    path.write_text("id,lat,lon\np1,40.4168270,-3.7037764\nbad,95,1\n")
    return path


def test_bad_portfolio_creates_no_run(tmp_path, settings):
    path = tmp_path / "bad.csv"
    path.write_text("id,lat\na,1\n")
    with pytest.raises(PortfolioError):
        start(path, settings)
    assert not settings.data_dir.exists()


def test_new_run_is_queued(csv_path, settings):
    run, points = start(csv_path, settings, "portfolio.csv")
    assert len(points) == 2
    state = status(run)
    assert (state["status"], state["source_name"], state["total_rows"]) == (
        "queued",
        "portfolio.csv",
        2,
    )


def test_runs_every_stage_in_order(csv_path, local_settings, monkeypatch):
    stages = []
    real_set_status = pipeline.set_status

    def spy(run, state, stage=None, error=None):
        stages.append((state, stage))
        real_set_status(run, state, stage, error)

    monkeypatch.setattr(pipeline, "set_status", spy)
    monkeypatch.setattr(pipeline, "assess", lambda run, settings: Assessment(1, 0))
    run, points = start(csv_path, local_settings)
    assert execute(run, points, local_settings) is True
    assert stages == [
        ("running", "geolocating"),
        ("running", "classifying"),
        ("running", "assessing"),
        ("completed", None),
    ]
    assert status(run)["status"] == "completed"
    with run.connect() as con:
        assert con.execute(
            "SELECT asset_id, assessable, exclusion_reason FROM assets ORDER BY row_num"
        ).fetchall() == [("p1", True, None), ("bad", False, "invalid")]


def test_failed_stage_is_recorded_not_raised(csv_path, settings):
    run, points = start(csv_path, settings)  # the geolocate config doesn't exist
    assert execute(run, points, settings) is False
    state = status(run)
    assert state["status"] == "failed"
    assert "not found" in state["error"]


def test_every_request_failing_fails_the_run(csv_path, local_settings, monkeypatch):
    monkeypatch.setattr(pipeline, "assess", lambda run, settings: Assessment(3, 3))
    run, points = start(csv_path, local_settings)
    assert execute(run, points, local_settings) is False
    assert "Every physrisk request failed" in status(run)["error"]


def test_some_requests_failing_still_completes(csv_path, local_settings, monkeypatch):
    monkeypatch.setattr(pipeline, "assess", lambda run, settings: Assessment(3, 1))
    run, points = start(csv_path, local_settings)
    assert execute(run, points, local_settings) is True


def test_no_assessable_assets_still_completes(tmp_path, local_settings, monkeypatch):
    path = tmp_path / "all_bad.csv"
    path.write_text("id,lat,lon\na,95,1\n")
    monkeypatch.setattr(pipeline, "assess", lambda run, settings: Assessment(0, 0))
    run, points = start(path, replace(local_settings))
    assert execute(run, points, local_settings) is True
