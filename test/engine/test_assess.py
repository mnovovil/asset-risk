import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from engine.assess import _request, assess, flatten, hazard_curve
from engine.store import create_run

RECORDED = json.loads((Path(__file__).parent / "fixtures" / "impact_response.json").read_text())
HAZARDS = {"CoastalInundation", "Fire", "Hail", "RiverineInundation", "Wind"}


def recorded_response(assets: int, scenario: str, year: int, hazards=None) -> dict:
    """The recorded physrisk response, resized and relabelled for the request."""
    response = copy.deepcopy(RECORDED)
    template = response["asset_impacts"][0]
    response["asset_impacts"] = []
    for _ in range(assets):
        asset = copy.deepcopy(template)
        asset["impacts"] = [
            i for i in asset["impacts"] if hazards is None or i["key"]["hazard_type"] in hazards
        ]
        for impact in asset["impacts"]:
            if impact["key"]["scenario_id"] != "historical":
                impact["key"].update(scenario_id=scenario, year=str(year))
        response["asset_impacts"].append(asset)
    measures = response["risk_measures"]
    for measure in measures["measures_for_assets"]:
        measure["key"].update(scenario_id=scenario, year=str(year))
        measure["scores"] = measure["scores"][:1] * assets
        measure["measures_0"] = measure["measures_0"][:1] * assets
    definitions = measures["score_based_measure_set_defn"]["asset_measure_ids_for_hazard"]
    for hazard, ids in definitions.items():
        definitions[hazard] = ids[:1] * assets
    return response


class FakeRequester:
    def __init__(self, fail_on=(), hazards_for=None):
        self.requests = []
        self.fail_on = fail_on
        self.hazards_for = hazards_for or {}

    def get(self, *, request_id, request_dict):
        self.requests.append(request_dict)
        scenario, year = request_dict["scenario"], request_dict["years"][0]
        batch = len(self.requests)
        if (scenario, year, batch) in self.fail_on or (scenario, year) in self.fail_on:
            raise RuntimeError("hazard data unavailable")
        return json.dumps(
            recorded_response(
                len(request_dict["assets"]["items"]),
                scenario,
                year,
                self.hazards_for.get(scenario),
            )
        )


@pytest.fixture
def two_assets(tmp_path):
    return make_run(tmp_path, 2)


def make_run(tmp_path, count):
    run = create_run(tmp_path, count)
    with run.connect() as con:
        for i in range(1, count + 1):
            con.execute(
                "INSERT INTO assets (row_num, asset_id, lat, lon, match_type, physrisk_type, "
                "physrisk_location, assessable) VALUES (?, ?, ?, ?, 'intersects', "
                "'Buildings/Commercial', 'Europe', true)",
                [i, f"a{i}", 40.0 + i, -3.0],
            )
    return run


def fetch(run, sql):
    with run.connect() as con:
        return con.execute(sql).fetchall()


def test_requests_each_scenario_and_year(two_assets, settings):
    fake = FakeRequester()
    multi = replace(settings, scenarios=("ssp245", "ssp585"), years=(2030, 2050))
    result = assess(two_assets, multi, fake)
    assert (result.requests, result.failed_requests) == (4, 0)
    assert [(r["scenario"], r["years"]) for r in fake.requests] == [
        ("ssp245", [2030]),
        ("ssp245", [2050]),
        ("ssp585", [2030]),
        ("ssp585", [2050]),
    ]


def test_request_uses_the_classified_values(two_assets, settings):
    fake = FakeRequester()
    assess(two_assets, settings, fake)
    assert fake.requests[0]["assets"]["items"][1] == {
        "asset_class": "RealEstateAsset",
        "type": "Buildings/Commercial",
        "location": "Europe",
        "latitude": 42.0,
        "longitude": -3.0,
    }


def test_only_assessable_assets_are_sent(tmp_path, settings):
    run = make_run(tmp_path, 2)
    with run.connect() as con:
        con.execute("UPDATE assets SET assessable = false WHERE row_num = 1")
    fake = FakeRequester()
    assess(run, settings, fake)
    assert len(fake.requests[0]["assets"]["items"]) == 1
    assert {r[0] for r in fetch(run, "SELECT row_num FROM impacts")} == {2}


def test_no_assessable_assets_makes_no_requests(tmp_path, settings):
    run = create_run(tmp_path, 0)
    fake = FakeRequester()
    assert assess(run, settings, fake).requests == 0
    assert fake.requests == []


def test_batches(tmp_path, settings):
    run = make_run(tmp_path, 5)
    fake = FakeRequester()
    assess(run, replace(settings, physrisk_batch_size=2), fake)
    assert [len(r["assets"]["items"]) for r in fake.requests] == [2, 2, 1]
    assert fetch(run, "SELECT count(DISTINCT row_num) FROM impacts") == [(5,)]


def test_flattens_impacts(two_assets, settings):
    assess(two_assets, settings, FakeRequester())
    rows = fetch(
        two_assets,
        "SELECT hazard, impact_type, year, aal, hazard_paths FROM impacts "
        "WHERE row_num = 1 AND scenario = 'ssp585' AND hazard = 'Wind'",
    )
    assert rows == [
        (
            "Wind",
            "damage",
            2050,
            pytest.approx(0.00125, abs=1e-5),
            ["wind/iris/v1/max_speed_{scenario}_{year}"],
        )
    ]


def test_baseline_is_stored_once(two_assets, settings):
    multi = replace(settings, scenarios=("ssp245", "ssp585"), years=(2030, 2050))
    assess(two_assets, multi, FakeRequester())
    assert fetch(
        two_assets,
        "SELECT count(*), count(year) FROM impacts WHERE scenario = 'historical' AND row_num = 1",
    ) == [(5, 0)]


def test_scores_keep_their_labels(two_assets, settings):
    assess(two_assets, settings, FakeRequester())
    scores = dict(fetch(two_assets, "SELECT hazard, label FROM scores WHERE row_num = 1"))
    assert scores["ChronicHeat"] == "No vulnerability"
    assert scores["Wind"] not in ("No vulnerability", "No hazard data", None)
    assert len(scores) == 9


def test_failed_batch_is_recorded_and_the_run_continues(two_assets, settings):
    multi = replace(settings, scenarios=("ssp245", "ssp585"), years=(2050,))
    result = assess(two_assets, multi, FakeRequester(fail_on={("ssp245", 2050)}))
    assert (result.requests, result.failed_requests) == (2, 1)
    assert fetch(two_assets, "SELECT row_num, scenario, year, error FROM assess_failures") == [
        (1, "ssp245", 2050, "hazard data unavailable"),
        (2, "ssp245", 2050, "hazard data unavailable"),
    ]
    assert fetch(two_assets, "SELECT count(*) FROM impacts WHERE scenario = 'ssp245'") == [(0,)]
    assert fetch(two_assets, "SELECT count(*) FROM impacts WHERE scenario = 'ssp585'") == [(10,)]


def test_baseline_survives_a_failed_first_request(two_assets, settings):
    multi = replace(settings, scenarios=("ssp245", "ssp585"), years=(2050,))
    assess(two_assets, multi, FakeRequester(fail_on={("ssp245", 2050)}))
    assert fetch(two_assets, "SELECT count(*) FROM impacts WHERE scenario = 'historical'") == [
        (10,)
    ]


def test_wrong_asset_count_is_a_failure(two_assets, settings):
    class Short(FakeRequester):
        def get(self, *, request_id, request_dict):
            return json.dumps(recorded_response(1, "ssp585", 2050))

    assert assess(two_assets, settings, Short()).failed_requests == 1


def test_flatten_drops_nan_to_null():
    response = recorded_response(1, "ssp585", 2050)
    for impact in response["asset_impacts"][0]["impacts"]:
        impact["impact_mean"] = float("nan")
    impacts, _ = flatten(response, [1], set())
    assert all(row[5] is None for row in impacts)


def test_progress_reaches_the_total(tmp_path, settings):
    run = make_run(tmp_path, 3)
    assess(run, replace(settings, physrisk_batch_size=1), FakeRequester())
    assert fetch(run, "SELECT done, total FROM runs") == [(3, 3)]


def test_hazard_curve():
    class Curve:
        def get(self, *, request_id, request_dict):
            assert request_id == "get_hazard_data"
            assert request_dict["items"][0]["year"] == 1980
            return json.dumps(
                {
                    "items": [
                        {
                            "intensity_curve_set": [
                                {"index_values": [2.0, 5.0], "intensities": [0.1, 0.2]}
                            ]
                        }
                    ]
                }
            )

    assert hazard_curve(1.0, 2.0, "historical", None, requester=Curve()) == {
        "return_periods": [2.0, 5.0],
        "intensities": [0.1, 0.2],
    }


# Figures from docs/physrisk_demo.ipynb, section 2: Buildings/Industrial, SSP5-8.5, 2050.
NOTEBOOK = {
    "Cologne": (50.94, 6.96, "Europe", 0.00386, 0.00327),
    "Houston": (29.76, -95.37, "North America", 0.00209, 0.00297),
    "Manila": (14.60, 120.98, "Asia", 0.01215, 0.00876),
}


@pytest.mark.live
def test_live_results_match_the_notebook(tmp_path, settings):
    run = create_run(tmp_path, len(NOTEBOOK))
    with run.connect() as con:
        for i, (name, (lat, lon, location, _, _)) in enumerate(NOTEBOOK.items(), 1):
            con.execute(
                "INSERT INTO assets (row_num, asset_id, lat, lon, match_type, physrisk_type, "
                "physrisk_location, assessable) VALUES (?, ?, ?, ?, 'intersects', "
                "'Buildings/Industrial', ?, true)",
                [i, name, lat, lon, location],
            )
    assert assess(run, settings).failed_requests == 0
    with run.connect() as con:
        rows = con.execute("SELECT asset_id, scenario, total_aal FROM v_asset_totals").fetchall()
    totals = {(name, scenario): total for name, scenario, total in rows}
    for name, (_, _, _, future, baseline) in NOTEBOOK.items():
        assert totals[(name, "ssp585")] == pytest.approx(future, abs=1e-5)
        assert totals[(name, "historical")] == pytest.approx(baseline, abs=1e-5)


@pytest.mark.live
def test_live_aal_rebuilds_from_its_distribution():
    from engine.assess import default_requester

    asset = (1, "Buildings/Industrial", "Europe", 50.94, 6.96)
    response = _request(default_requester(), [asset], "ssp585", 2050)
    record = next(
        i
        for i in response["asset_impacts"][0]["impacts"]
        if i["key"]["hazard_type"] == "RiverineInundation"
        and i["key"]["scenario_id"] == "historical"
    )
    edges = record["impact_distribution"]["bin_edges"]
    probabilities = record["impact_distribution"]["probabilities"]
    rebuilt = sum(
        p * (low + high) / 2 for p, low, high in zip(probabilities, edges, edges[1:], strict=False)
    )
    assert rebuilt == pytest.approx(record["impact_mean"], rel=0.01)


@pytest.mark.live
def test_live_hazard_curve():
    curve = hazard_curve(29.76, -95.37, "ssp585", 2050)
    assert 100.0 in curve["return_periods"]
    assert hazard_curve(29.76, -95.37, "ssp370", 2050) == {
        "return_periods": [],
        "intensities": [],
    }
