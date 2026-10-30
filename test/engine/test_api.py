import csv
import importlib.util
import io
import threading
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.api import create_app
from engine.store import all_runs, create_run, find_run, set_status

ROOT = Path(__file__).resolve().parents[2]
CSV = b"id,lat,lon\n=cmd,40.4,-3.7\nb,29.7,-95.3\nbad,95,1\n"


def api_app(settings, execute):
    """The API alone, whether or not the front end has been built on this machine."""
    return create_app(settings, execute=execute, front_dist=Path("/nonexistent"))


def complete_run(run, points, settings):
    """Stands in for the pipeline: writes the results a real run would."""
    with run.connect() as con:
        con.execute(
            "INSERT INTO assets (row_num, asset_id, lat, lon, match_type, distance_m, name, class, "
            "subtype, physrisk_type, physrisk_location, type_source, location_fallback, assessable,"
            " geometry_wkt) VALUES "
            "(1, '=cmd', 40.4, -3.7, 'intersects', 0, 'Casa', 'house', 'residential', "
            "'Buildings/Residential', 'Europe', 'class', false, true, 'POLYGON ((0 0))'), "
            "(2, 'b', 29.7, -95.3, 'none', NULL, NULL, NULL, NULL, 'Buildings/Commercial', "
            "'North America', 'assumed', false, true, NULL)"
        )
        con.execute(
            "INSERT INTO assets (row_num, asset_id, lat, lon, match_type, assessable, "
            "exclusion_reason) VALUES (3, 'bad', 'nan'::DOUBLE, 1, 'invalid', false, 'invalid')"
        )
        con.execute(
            "INSERT INTO assessment_pairs VALUES ('ssp585', 2050), ('ssp370', 2050), "
            "('historical', NULL)"
        )
        con.execute(
            "INSERT INTO impacts VALUES "
            "(1, 'Wind', 'damage', 'ssp585', 2050, 0.01, 0.001, ['wind/path']), "
            "(2, 'Wind', 'damage', 'ssp585', 2050, 0.03, NULL, []), "
            "(1, 'Wind', 'damage', 'historical', NULL, 0.002, NULL, []), "
            "(2, 'Wind', 'damage', 'historical', NULL, 0.004, NULL, [])"
        )
        con.execute(
            "INSERT INTO scores VALUES "
            "(1, 'Wind', 'ssp585', 2050, 1, 'Low impact'), "
            "(2, 'Wind', 'ssp585', 2050, 2, 'Medium impact'), "
            "(1, 'PluvialInundation', 'ssp585', 2050, -2, 'No hazard data')"
        )
    set_status(run, "completed")
    return True


@pytest.fixture
def client(settings):
    with TestClient(api_app(settings, complete_run)) as c:
        yield c


def upload(client, content=CSV, name="portfolio.csv"):
    return client.post("/api/runs", files={"file": (name, content, "text/csv")})


def wait_until_finished(client, run_id):
    for _ in range(500):
        body = client.get(f"/api/runs/{run_id}").json()
        if body["status"] not in ("queued", "running"):
            return body
        threading.Event().wait(0.01)
    raise AssertionError("The run did not finish")


@pytest.fixture
def finished(client):
    run_id = upload(client).json()["run_id"]
    assert wait_until_finished(client, run_id)["status"] == "completed"
    return run_id


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_config(client):
    assert client.get("/api/config").json() == {
        "scenarios": ["ssp585"],
        "years": [2050],
        "default_building_type": "Buildings/Commercial",
        "max_portfolio_rows": 100,
        "max_upload_mb": 1.0,
    }


def test_upload_returns_202_and_starts_a_run(client):
    response = upload(client)
    assert response.status_code == 202
    body = response.json()
    assert body["source_name"] == "portfolio.csv"
    assert body["total_rows"] == 3
    uuid.UUID(body["run_id"])


def test_upload_name_is_only_a_label(client, settings):
    body = upload(client, name="../../evil.csv").json()
    assert body["source_name"] == "evil.csv"
    assert not (settings.data_dir.parent.parent / "evil.csv").exists()
    assert (settings.data_dir / "runs" / body["run_id"]).is_dir()


def test_upload_leaves_no_temporary_file(client, settings):
    upload(client)
    upload(client, b"id,lat\na,1\n")
    assert list((settings.data_dir / "uploads").iterdir()) == []


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"id,lat\na,1\n", "lon"),
        (b"id,lat,lon\na,1,2\na,3,4\n", "Duplicate ids"),
        (b"id,lat,lon\n", "no rows"),
    ],
)
def test_bad_portfolio_is_rejected_with_a_readable_message(client, settings, content, message):
    response = upload(client, content)
    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert str(settings.data_dir) not in response.json()["detail"]
    assert client.get("/api/runs").json() == []


def test_too_many_rows_is_rejected(client):
    rows = "".join(f"r{i},1,2\n" for i in range(101))
    response = upload(client, f"id,lat,lon\n{rows}".encode())
    assert response.status_code == 422
    assert "limit is 100" in response.json()["detail"]


def test_too_many_bytes_is_rejected(settings):
    small = replace(settings, max_upload_mb=0.001)
    with TestClient(api_app(small, complete_run)) as client:
        response = upload(client, b"id,lat,lon\n" + b"a,1,2\n" * 1000)
    assert response.status_code == 413
    assert "MB limit" in response.json()["detail"]


def test_missing_file_has_the_same_error_shape(client):
    response = client.post("/api/runs")
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


@pytest.mark.parametrize(
    "run_id",
    [
        "not-a-uuid",
        "..",
        "..%2f..%2fetc",
        str(uuid.uuid4()),
        str(uuid.uuid4()).upper(),
        str(uuid.uuid4()).replace("-", ""),
    ],
)
def test_unknown_or_malformed_run_id_is_404(client, run_id):
    assert client.get(f"/api/runs/{run_id}").status_code in (404, 405)
    assert client.get(f"/api/runs/{run_id}/summary").status_code in (404, 405)


def test_find_run_never_builds_a_path_from_a_bad_id(tmp_path):
    (tmp_path / "runs" / "x").mkdir(parents=True)
    (tmp_path / "runs" / "x" / "run.duckdb").touch()
    assert find_run(tmp_path, "x") is None
    assert find_run(tmp_path, "../runs/x") is None


def test_runs_are_listed_newest_first(client):
    first = upload(client).json()["run_id"]
    second = upload(client).json()["run_id"]
    assert [r["run_id"] for r in client.get("/api/runs").json()] == [second, first]


class Blocking:
    """A pipeline that waits to be released, so a test can look at the queue."""

    def __init__(self):
        self.started = []
        self.proceed = threading.Event()
        self.first_started = threading.Event()

    def __call__(self, run, points, settings):
        self.started.append(run.run_id)
        self.first_started.set()
        set_status(run, "running", "geolocating")
        assert self.proceed.wait(10)
        set_status(run, "completed")
        return True


def test_queue_runs_one_at_a_time_in_order(settings):
    pipeline = Blocking()
    with TestClient(api_app(settings, pipeline)) as client:
        first = upload(client).json()["run_id"]
        assert pipeline.first_started.wait(10)
        second = upload(client).json()
        third = upload(client).json()

        assert second["queue_position"] == 1
        assert third["queue_position"] == 2
        assert client.get(f"/api/runs/{first}").json()["status"] == "running"
        assert client.get(f"/api/runs/{first}").json()["queue_position"] is None
        assert pipeline.started == [first]

        pipeline.proceed.set()
        wait_until_finished(client, third["run_id"])
        assert pipeline.started == [first, second["run_id"], third["run_id"]]


def test_results_wait_for_the_run_to_complete(settings):
    pipeline = Blocking()
    with TestClient(api_app(settings, pipeline)) as client:
        run_id = upload(client).json()["run_id"]
        assert pipeline.first_started.wait(10)
        response = client.get(f"/api/runs/{run_id}/summary")
        assert response.status_code == 409
        assert "running" in response.json()["detail"]
        pipeline.proceed.set()


def test_failed_run_reports_its_error_and_has_no_results(settings):
    def fail(run, points, settings):
        set_status(run, "failed", error="geolocate failed: S3 is down")
        return False

    with TestClient(api_app(settings, fail)) as client:
        run_id = upload(client).json()["run_id"]
        body = wait_until_finished(client, run_id)
        assert (body["status"], body["error"]) == ("failed", "geolocate failed: S3 is down")
        assert client.get(f"/api/runs/{run_id}/assets").status_code == 409
        assert client.get(f"/api/runs/{run_id}/export.csv").status_code == 409


def test_a_crash_in_the_pipeline_does_not_stop_the_queue(settings):
    calls = []

    def crash_once(run, points, settings):
        calls.append(run.run_id)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return complete_run(run, points, settings)

    with TestClient(api_app(settings, crash_once)) as client:
        upload(client)
        second = upload(client).json()["run_id"]
        assert wait_until_finished(client, second)["status"] == "completed"


@pytest.mark.parametrize("state", ["queued", "running"])
def test_unfinished_runs_are_marked_interrupted_at_startup(settings, state):
    run = create_run(settings.data_dir, 1)
    if state == "running":
        set_status(run, "running", "assessing")
    with TestClient(api_app(settings, complete_run)) as client:
        body = client.get(f"/api/runs/{run.run_id}").json()
    assert body["status"] == "interrupted"
    assert "Upload the portfolio again" in body["error"]


def test_finished_runs_survive_a_restart(settings):
    run = create_run(settings.data_dir, 1)
    set_status(run, "completed")
    with TestClient(api_app(settings, complete_run)) as client:
        assert client.get(f"/api/runs/{run.run_id}").json()["status"] == "completed"
    assert len(all_runs(settings.data_dir)) == 1


def test_summary(client, finished):
    body = client.get(f"/api/runs/{finished}/summary").json()
    assert body["total_assets"] == 3
    assert body["assessable"] == 2
    assert body["assumed_type"] == 1
    assert body["exclusions"] == [{"reason": "invalid", "assets": 1}]
    assert body["shared_hazards"] == ["Wind"]


def test_assets_use_the_real_column_name_and_handle_nan(client, finished):
    rows = client.get(f"/api/runs/{finished}/assets").json()
    assert [r["row_num"] for r in rows] == [1, 2, 3]
    assert rows[0]["class"] == "house"
    assert "geometry_wkt" not in rows[0]
    assert rows[2]["lat"] is None
    assert rows[2]["exclusion_reason"] == "invalid"


def test_asset_detail(client, finished):
    body = client.get(f"/api/runs/{finished}/assets/1").json()
    assert body["geometry_wkt"] == "POLYGON ((0 0))"
    assert body["class"] == "house"
    assert [(i["scenario"], i["year"]) for i in body["impacts"]] == [
        ("historical", None),
        ("ssp585", 2050),
    ]
    assert body["impacts"][1]["hazard_paths"] == ["wind/path"]
    assert {s["label"] for s in body["scores"]} == {"Low impact", "No hazard data"}


@pytest.mark.parametrize("row_num", ["99", "abc"])
def test_unknown_asset(client, finished, row_num):
    assert client.get(f"/api/runs/{finished}/assets/{row_num}").status_code in (404, 422)


def test_impacts_for_a_scenario_and_year(client, finished):
    rows = client.get(
        f"/api/runs/{finished}/impacts", params={"scenario": "ssp585", "year": 2050}
    ).json()
    assert [(r["asset_id"], r["aal"]) for r in rows] == [("=cmd", 0.01), ("b", 0.03)]


def test_impacts_for_the_baseline_have_no_year(client, finished):
    rows = client.get(f"/api/runs/{finished}/impacts", params={"scenario": "historical"}).json()
    assert [r["aal"] for r in rows] == [0.002, 0.004]


def test_totals(client, finished):
    rows = client.get(
        f"/api/runs/{finished}/totals", params={"scenario": "ssp585", "year": 2050}
    ).json()
    assert [(r["total_aal"], r["shared_aal"], r["hazards"]) for r in rows] == [
        (0.01, 0.01, 1),
        (0.03, 0.03, 1),
    ]


def test_scores_keep_no_data_apart_from_low(client, finished):
    rows = client.get(
        f"/api/runs/{finished}/scores", params={"scenario": "ssp585", "year": 2050}
    ).json()
    labels = {(r["row_num"], r["hazard"]): r["label"] for r in rows}
    assert labels[(1, "PluvialInundation")] == "No hazard data"
    assert labels[(1, "Wind")] == "Low impact"


@pytest.mark.parametrize("endpoint", ["impacts", "totals", "scores"])
def test_pair_that_was_not_assessed_is_404(client, finished, endpoint):
    url = f"/api/runs/{finished}/{endpoint}"
    assert client.get(url, params={"scenario": "ssp126", "year": 2050}).status_code == 404
    assert client.get(url, params={"scenario": "ssp585", "year": 1999}).status_code == 404
    assert client.get(url, params={"scenario": "ssp585"}).status_code == 404
    assert client.get(url).status_code == 422


def test_sql_in_a_query_value_is_only_a_value(client, finished):
    response = client.get(
        f"/api/runs/{finished}/impacts", params={"scenario": "x'; DROP TABLE assets; --"}
    )
    assert response.status_code == 404
    assert len(client.get(f"/api/runs/{finished}/assets").json()) == 3


def test_trajectory_includes_a_scenario_with_no_results(client, finished):
    rows = client.get(f"/api/runs/{finished}/trajectory").json()
    assert {r["scenario"]: r["assets"] for r in rows} == {
        "historical": 2,
        "ssp370": 0,
        "ssp585": 2,
    }


def test_coverage(client, finished):
    rows = client.get(f"/api/runs/{finished}/coverage").json()
    assert {(r["scenario"], r["covered"]) for r in rows} == {
        ("historical", True),
        ("ssp370", False),
        ("ssp585", True),
    }


def test_hazard_curve(client, finished, monkeypatch):
    seen = []

    def fake(lat, lon, scenario, year):
        seen.append((lat, lon, scenario, year))
        return {"return_periods": [2.0], "intensities": [0.1]}

    monkeypatch.setattr("engine.api.hazard_curve", fake)
    url = f"/api/runs/{finished}/assets/1/hazard-curve"
    assert client.get(url).json() == {"return_periods": [2.0], "intensities": [0.1]}
    assert client.get(url, params={"scenario": "ssp585", "year": 2050}).status_code == 200
    assert seen == [(40.4, -3.7, "historical", None), (40.4, -3.7, "ssp585", 2050)]


def test_hazard_curve_needs_a_year_for_a_scenario(client, finished):
    url = f"/api/runs/{finished}/assets/1/hazard-curve"
    assert client.get(url, params={"scenario": "ssp585"}).status_code == 422


def test_hazard_curve_for_an_excluded_asset(client, finished):
    assert client.get(f"/api/runs/{finished}/assets/3/hazard-curve").status_code == 409


def test_hazard_curve_failure_is_reported(client, finished, monkeypatch):
    def fail(*args):
        raise RuntimeError("no data")

    monkeypatch.setattr("engine.api.hazard_curve", fail)
    response = client.get(f"/api/runs/{finished}/assets/1/hazard-curve")
    assert response.status_code == 502
    assert "no data" in response.json()["detail"]


def test_export_is_a_download_with_every_asset(client, finished):
    response = client.get(f"/api/runs/{finished}/export.csv")
    assert response.headers["content-type"].startswith("text/csv")
    assert f"asset-risk-{finished}.csv" in response.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 5  # 2 assets x 2 pairs, plus the excluded one
    excluded = rows[-1]
    assert (excluded["asset_id"], excluded["exclusion_reason"]) == ("bad", "invalid")
    assert excluded["hazard"] == ""


def test_export_escapes_formulas_but_not_numbers(client, finished):
    response = client.get(f"/api/runs/{finished}/export.csv")
    first = next(csv.DictReader(io.StringIO(response.text)))
    assert first["asset_id"] == "'=cmd"
    assert first["lon"] == "-3.7"


def spa_app(settings, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "main.js").write_text("console.log(1)")
    return create_app(settings, execute=complete_run, front_dist=dist)


def test_front_end_routes_serve_the_app(settings, tmp_path):
    with TestClient(spa_app(settings, tmp_path)) as client:
        assert client.get("/").text == "<html>app</html>"
        assert client.get("/assets/main.js").text == "console.log(1)"
        assert client.get(f"/runs/{uuid.uuid4()}").text == "<html>app</html>"


def test_unknown_api_paths_stay_404_with_a_front_end(settings, tmp_path):
    with TestClient(spa_app(settings, tmp_path)) as client:
        assert client.get("/api/nope").status_code == 404


def test_static_files_cannot_escape_the_folder(settings, tmp_path):
    (tmp_path / "secret.txt").write_text("secret")
    with TestClient(spa_app(settings, tmp_path)) as client:
        assert "secret" not in client.get("/..%2fsecret.txt").text
        assert "secret" not in client.get("/api/runs/..%2f..%2f..%2fsecret.txt").text


def test_committed_openapi_is_current():
    spec = importlib.util.spec_from_file_location(
        "export_openapi", ROOT / "script" / "export_openapi.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.OPENAPI_JSON.read_text() == module.schema_text(), (
        "Run `.venv/bin/python script/export_openapi.py`"
    )
