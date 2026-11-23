import json

import pytest

from engine import analyst_tools
from engine.analyst_tools import MAX_TOP_ASSETS, TOOLS, call

# Assets 1 and 2 have results everywhere. Asset 3 is excluded. Asset 4's ssp585 batch failed, so it
# has results only for ssp245 and the baseline. ssp245 has no fire, as in the real data, so Wind is
# the only shared hazard.
IMPACTS = [
    (1, "Wind", "ssp585", 2050, 0.01),
    (1, "Fire", "ssp585", 2050, 0.02),
    (2, "Wind", "ssp585", 2050, 0.03),
    (2, "Fire", "ssp585", 2050, 0.04),
    (1, "Wind", "ssp245", 2050, 0.05),
    (2, "Wind", "ssp245", 2050, 0.07),
    (4, "Wind", "ssp245", 2050, 0.06),
    (1, "Wind", "historical", None, 0.002),
    (1, "Fire", "historical", None, 0.001),
    (2, "Wind", "historical", None, 0.004),
    (2, "Fire", "historical", None, 0.003),
    (4, "Wind", "historical", None, 0.001),
    (4, "Fire", "historical", None, 0.001),
]
PAIRS = [("ssp245", 2050), ("ssp585", 2050), ("historical", None)]
FAILURES = [(4, "ssp585", 2050)]


@pytest.fixture
def assets(asset_row):
    return [
        asset_row(1),
        asset_row(2, source="assumed"),
        asset_row(3, assessable=False, match="invalid", reason="invalid"),
        asset_row(4),
    ]


@pytest.fixture
def run(make_run, assets):
    return make_run(assets, IMPACTS, PAIRS, FAILURES)


@pytest.fixture
def valued(make_run, assets):
    values = [(100.0, "given"), (300.0, "given"), (None, "invalid"), (None, "missing")]
    return make_run(assets, IMPACTS, PAIRS, FAILURES, values=values, currency="EUR")


def ok(run, name, **args):
    result = call(run, name, args)
    assert "error" not in result, result
    # What the model reads: no NaN, no dates, nothing json can't write.
    json.dumps(result, allow_nan=False)
    return result


def test_every_tool_describes_itself():
    assert set(TOOLS) == {
        "query_portfolio",
        "get_asset",
        "top_assets",
        "compare_scenarios",
        "list_exclusions",
    }
    for name, tool in TOOLS.items():
        assert tool.name == name
        assert tool.description and "\n" not in tool.description
        assert tool.parameters["type"] == "object"
        assert set(tool.parameters.get("required", [])) <= set(tool.parameters["properties"])
        for schema in tool.parameters["properties"].values():
            assert schema["description"]


def test_query_portfolio(run):
    result = ok(run, "query_portfolio", scenario="ssp585", year=2050)
    # Asset 4 failed, so the means are over assets 1 and 2 only.
    assert result["assets_with_results"] == 2
    assert result["mean_total_aal"] == pytest.approx(0.05)
    assert result["mean_shared_aal"] == pytest.approx(0.02)
    assert result["hazards"] == [
        {"hazard": "Fire", "mean_aal": pytest.approx(0.03), "assets": 2, "covered": True,
         "shared": False},
        {"hazard": "Wind", "mean_aal": pytest.approx(0.02), "assets": 2, "covered": True,
         "shared": True},
    ]  # fmt: skip
    assert "value_weighted" not in result


def test_a_hazard_a_scenario_lacks_is_no_result_not_zero(run):
    result = ok(run, "query_portfolio", scenario="ssp245", year=2050, hazard="fire")
    assert result["hazards"] == [
        {"hazard": "Fire", "mean_aal": None, "assets": 0, "covered": False, "shared": False}
    ]


def test_the_historical_baseline_has_year_null(run):
    result = ok(run, "query_portfolio", scenario="historical", year=None)
    assert (result["year"], result["assets_with_results"]) == (None, 3)
    assert result["mean_total_aal"] == pytest.approx((0.003 + 0.007 + 0.002) / 3)


def test_query_portfolio_adds_value_weighting_only_when_the_run_has_values(valued):
    weighted = ok(valued, "query_portfolio", scenario="ssp585", year=2050)["value_weighted"]
    assert weighted == {
        "currency": "EUR",
        "valued_assets": 2,
        "valued_total": 400.0,
        "weighted_mean_total_aal": pytest.approx((0.03 * 100 + 0.07 * 300) / 400),
        "weighted_mean_shared_aal": pytest.approx((0.01 * 100 + 0.03 * 300) / 400),
        "expected_loss_total": pytest.approx(24.0),
        "expected_loss_shared": pytest.approx(10.0),
    }


def test_get_asset_drops_the_footprint(run):
    with run.connect() as con:
        con.execute(
            "UPDATE assets SET geometry_wkt = 'POLYGON ((0 0, 1 0, 1 1, 0 0))', lat = 'NaN'"
        )
    result = ok(run, "get_asset", row_num=2)
    assert "geometry_wkt" not in result
    assert (result["asset_id"], result["type_source"], result["lat"]) == ("a2", "assumed", None)
    assert {(i["scenario"], i["hazard"]) for i in result["impacts"]} >= {("ssp585", "Fire")}
    assert result["failed_assessments"] == []


def test_failed_and_excluded_assets_have_no_results_never_zero(run):
    failed = ok(run, "get_asset", row_num=4)
    assert failed["failed_assessments"] == [{"scenario": "ssp585", "year": 2050}]
    assert "ssp585" not in {i["scenario"] for i in failed["impacts"]}
    excluded = ok(run, "get_asset", row_num=3)
    assert (excluded["exclusion_reason"], excluded["impacts"]) == ("invalid", [])

    top = ok(run, "top_assets", scenario="ssp585", year=2050)
    assert [a["row_num"] for a in top["assets"]] == [2, 1]
    assert top["assets_with_results"] == 2


def test_top_assets_by_total(run):
    result = ok(run, "top_assets", scenario="ssp245", year=2050, n=2)
    assert result["ranked_by"] == "total_aal"
    assert [(a["row_num"], a["asset_id"], a["type_source"]) for a in result["assets"]] == [
        (2, "a2", "assumed"),
        (4, "a4", "class"),
    ]
    assert result["assets"][0]["total_aal"] == pytest.approx(0.07)
    assert result["assets_with_results"] == 3
    assert "n_capped_from" not in result


def test_top_assets_by_hazard(run):
    result = ok(run, "top_assets", scenario="ssp585", year=2050, hazard="Fire")
    assert result["ranked_by"] == "aal"
    assert [(a["row_num"], a["aal"]) for a in result["assets"]] == [
        (2, pytest.approx(0.04)),
        (1, pytest.approx(0.02)),
    ]


def test_top_assets_caps_n(run):
    result = ok(run, "top_assets", scenario="ssp245", year=2050, n=1000)
    assert (result["n"], result["n_capped_from"]) == (MAX_TOP_ASSETS, 1000)


def test_compare_scenarios_uses_only_shared_hazards(run):
    result = ok(run, "compare_scenarios", a="ssp245", b="ssp585", year=2050)
    assert result["shared_hazards"] == ["Wind"]
    assert (result["a"]["mean_shared_aal"], result["b"]["mean_shared_aal"]) == (
        pytest.approx(0.06),
        pytest.approx(0.02),  # Wind only; ssp585's total, with Fire, is 0.05
    )
    assert result["difference_b_minus_a"] == pytest.approx(-0.04)
    assert result["hazards_left_out"] == {"ssp245": [], "ssp585": ["Fire"]}
    # Fire is only ever named as left out, never given a figure.
    figures = {k: v for k, v in result.items() if k != "hazards_left_out"}
    assert "fire" not in json.dumps(figures).lower()


def test_compare_with_the_baseline_reads_it_as_year_null(run):
    result = ok(run, "compare_scenarios", a="historical", b="ssp245", year=2050)
    assert (result["a"]["scenario"], result["a"]["year"]) == ("historical", None)
    assert result["a"]["mean_shared_aal"] == pytest.approx((0.002 + 0.004 + 0.001) / 3)
    assert result["hazards_left_out"]["historical"] == ["Fire"]


def test_list_exclusions(run):
    result = ok(run, "list_exclusions")
    assert result["excluded_counts"] == [{"reason": "invalid", "assets": 1}]
    assert result["excluded"] == [{"row_num": 3, "asset_id": "a3", "reason": "invalid"}]
    assert result["reasons"]["invalid"]
    assert result["failures"] == [
        {"row_num": 4, "asset_id": "a4", "scenario": "ssp585", "year": 2050}
    ]
    assert (result["failures_total"], result["failed_assets"]) == (1, 1)


def test_list_exclusions_lists_a_few_rows_and_counts_them_all(make_run, asset_row):
    many = analyst_tools.MAX_LISTED + 5
    rows = [
        asset_row(i, assessable=False, match="none", reason="off_land") for i in range(1, many + 1)
    ]
    result = ok(make_run(rows), "list_exclusions")
    assert (len(result["excluded"]), result["excluded_total"]) == (analyst_tools.MAX_LISTED, many)


@pytest.mark.parametrize(
    ("name", "args", "message"),
    [
        ("no_such_tool", {}, "no tool named"),
        ("list_exclusions", ["not", "an", "object"], "object of arguments"),
        ("list_exclusions", {"verbose": True}, "no argument 'verbose'"),
        ("query_portfolio", {"scenario": "ssp585"}, "needs 'year'"),
        (
            "query_portfolio",
            {"scenario": "ssp126", "year": 2050},
            "wasn't assessed for ssp126 2050",
        ),
        ("query_portfolio", {"scenario": "ssp585", "year": 2080}, "ssp245 2050"),
        ("query_portfolio", {"scenario": "ssp585", "year": "2050"}, "integer or null"),
        ("query_portfolio", {"scenario": "ssp585", "year": True}, "integer or null"),
        ("query_portfolio", {"scenario": "historical", "year": 2050}, "pass year null"),
        ("query_portfolio", {"scenario": 585, "year": 2050}, "must be string"),
        ("query_portfolio", {"scenario": "ssp585", "year": 2050, "hazard": "Hail"}, "Fire, Wind"),
        ("get_asset", {"row_num": 99}, "rows 1 to 4"),
        ("get_asset", {"row_num": 0}, "at least 1"),
        ("get_asset", {"row_num": "2"}, "must be integer"),
        ("top_assets", {"scenario": "ssp585", "year": 2050, "n": 0}, "at least 1"),
        ("top_assets", {"scenario": "ssp585", "year": 2050, "hazard": "Flood"}, "no results"),
        ("compare_scenarios", {"a": "ssp585", "b": "ssp585", "year": 2050}, "the same scenario"),
        ("compare_scenarios", {"a": "ssp585", "b": "ssp370", "year": 2050}, "ssp370 2050"),
    ],
)
def test_an_invalid_argument_returns_a_readable_error(run, name, args, message):
    result = call(run, name, args)
    assert list(result) == ["error"]
    assert message in result["error"]


def test_a_quote_in_an_argument_is_only_ever_a_value(run):
    result = call(run, "query_portfolio", {"scenario": "x'; DROP TABLE assets; --", "year": 2050})
    assert "error" in result
    assert ok(run, "get_asset", row_num=1)["asset_id"] == "a1"


def test_a_run_from_before_values_still_works(valued, make_run_from_before_values):
    old = make_run_from_before_values(valued)
    assert "value_weighted" not in ok(old, "query_portfolio", scenario="ssp585", year=2050)
    assert ok(old, "get_asset", row_num=1)["value_status"] == "missing"
    ok(old, "top_assets", scenario="ssp585", year=2050)
    ok(old, "compare_scenarios", a="ssp245", b="ssp585", year=2050)
    ok(old, "list_exclusions")
