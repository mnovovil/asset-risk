import pytest

from engine.store import create_run, summary

# Asset 1 has 1% + 2% and asset 2 has 3% + 4% under ssp585. ssp245 has no fire, as in the real data.
ASSETS = [
    (1, "a1", "intersects", "Buildings/Commercial", "class", False, True, None),
    (2, "a2", "intersects", "Buildings/Commercial", "class", False, True, None),
]
IMPACTS = [
    (1, "Wind", "ssp585", 2050, 0.01),
    (1, "Fire", "ssp585", 2050, 0.02),
    (2, "Wind", "ssp585", 2050, 0.03),
    (2, "Fire", "ssp585", 2050, 0.04),
    (1, "Wind", "ssp245", 2050, 0.05),
    (2, "Wind", "ssp245", 2050, 0.07),
    (1, "Wind", "historical", None, 0.002),
    (1, "Fire", "historical", None, 0.001),
    (2, "Wind", "historical", None, 0.004),
    (2, "Fire", "historical", None, 0.003),
]
PAIRS = [("ssp245", 2050), ("ssp585", 2050), ("ssp370", 2050), ("historical", None)]


@pytest.fixture
def run(make_run):
    return make_run(ASSETS, IMPACTS, PAIRS)


def fetch(run, sql):
    with run.connect() as con:
        return con.execute(sql).fetchall()


def trajectory(run):
    rows = fetch(
        run,
        "SELECT scenario, assets, mean_total_aal, mean_shared_aal, hazards "
        "FROM v_portfolio_trajectory",
    )
    return {r[0]: r[1:] for r in rows}


def test_totals_are_equal_weighted_means(run):
    assert trajectory(run)["ssp585"] == (
        2,
        pytest.approx(0.05),  # (0.03 + 0.07) / 2
        pytest.approx(0.02),  # wind only: (0.01 + 0.03) / 2
        2,
    )


def test_shared_hazards_are_those_in_every_scenario(run):
    assert fetch(run, "SELECT hazard FROM v_shared_hazards") == [("Wind",)]


def test_scenario_with_fewer_hazards_is_comparable_only_on_shared(run):
    t = trajectory(run)
    # Totals say ssp245 is about the same as ssp585. On the shared hazard it's three times worse.
    assert t["ssp245"][1] == pytest.approx(0.06)
    assert t["ssp245"][2] == pytest.approx(0.06)
    assert t["ssp245"][2] == pytest.approx(3 * t["ssp585"][2])


def test_scenario_with_no_results_still_appears(run):
    assert trajectory(run)["ssp370"] == (0, None, None, 0)


def test_coverage_shows_what_is_missing(run):
    rows = fetch(
        run,
        "SELECT scenario, hazard, assets, covered, shared FROM v_hazard_coverage "
        "WHERE scenario IN ('ssp245', 'ssp370') ORDER BY 1, 2",
    )
    assert rows == [
        ("ssp245", "Fire", 0, False, False),
        ("ssp245", "Wind", 2, True, True),
        ("ssp370", "Fire", 0, False, False),
        ("ssp370", "Wind", 0, False, True),
    ]


def test_portfolio_hazards(run):
    rows = fetch(
        run,
        "SELECT hazard, mean_aal, assets FROM v_portfolio_hazards "
        "WHERE scenario = 'ssp585' ORDER BY hazard",
    )
    assert rows == [
        ("Fire", pytest.approx(0.03), 2),
        ("Wind", pytest.approx(0.02), 2),
    ]


def test_asset_totals(run):
    rows = fetch(
        run,
        "SELECT asset_id, total_aal, shared_aal, hazards FROM v_asset_totals "
        "WHERE scenario = 'ssp585' ORDER BY asset_id",
    )
    assert rows == [
        ("a1", pytest.approx(0.03), pytest.approx(0.01), 2),
        ("a2", pytest.approx(0.07), pytest.approx(0.03), 2),
    ]


def test_historical_baseline_is_a_trajectory_row(run):
    assert trajectory(run)["historical"][1] == pytest.approx(0.005)


def test_failed_assets_are_left_out_of_means_and_counted(make_run):
    impacts = [(1, "Wind", "ssp585", 2050, 0.01)]
    run = make_run(ASSETS, impacts, [("ssp585", 2050)], [(2, "ssp585", 2050)])
    assert trajectory(run)["ssp585"][:2] == (1, pytest.approx(0.01))
    assert summary(run)["failed_assets"] == 1


def test_summary_counts(make_run, asset_row):
    run = make_run(
        [
            asset_row(1),
            asset_row(2, source="assumed"),
            asset_row(3, source="assumed", match="none"),
            asset_row(4, match="nearest", fallback=True),
            asset_row(5, assessable=False, match="invalid", reason="invalid"),
            asset_row(6, assessable=False, match="none", reason="off_land"),
        ],
    )
    assert summary(run) == {
        "total_assets": 6,
        "assessable": 4,
        "excluded": 2,
        "assumed_type": 2,
        "global_curve": 1,
        "nearest_match": 1,
        "no_building": 1,
        "failed_assets": 0,
        "valued_assets": 0,
        "missing_values": 0,
        "invalid_values": 0,
        "total_value": None,
        "currency": None,
        "has_values": False,
    }
    assert sorted(fetch(run, "SELECT reason, assets FROM v_exclusions")) == [
        ("invalid", 1),
        ("off_land", 1),
    ]


def test_views_work_on_an_empty_run(tmp_path):
    run = create_run(tmp_path, 0)
    assert summary(run)["total_assets"] == 0
    assert fetch(run, "SELECT * FROM v_portfolio_trajectory") == []


# Asset 1 is worth 100 and asset 2 is worth 300, so asset 2 counts three times as much.
VALUES = [(100.0, "given"), (300.0, "given")]


def weighted(run):
    rows = fetch(
        run,
        "SELECT scenario, valued_assets, valued_total, weighted_mean_total_aal, "
        "weighted_mean_shared_aal, expected_loss_total, expected_loss_shared "
        "FROM v_portfolio_trajectory",
    )
    return {r[0]: r[1:] for r in rows}


def test_value_weighted_means_and_expected_losses(make_run):
    run = make_run(ASSETS, IMPACTS, PAIRS, values=VALUES, currency="EUR")
    # ssp585: asset 1 totals 3% (Wind 1%, shared) and asset 2 totals 7% (Wind 3%, shared).
    assert weighted(run)["ssp585"] == pytest.approx(
        (
            2,
            400.0,
            (0.03 * 100 + 0.07 * 300) / 400,
            (0.01 * 100 + 0.03 * 300) / 400,
            0.03 * 100 + 0.07 * 300,
            0.01 * 100 + 0.03 * 300,
        )
    )
    # Equal-weighted means are still there, unchanged.
    assert trajectory(run)["ssp585"][1] == pytest.approx(0.05)


def test_weighted_shared_figures_compare_scenarios_on_shared_hazards(make_run):
    run = make_run(ASSETS, IMPACTS, PAIRS, values=VALUES)
    rows = weighted(run)
    # ssp245 has only Wind, so its total and shared figures agree.
    assert rows["ssp245"][3] == pytest.approx((0.05 * 100 + 0.07 * 300) / 400)
    assert rows["ssp245"][3] == pytest.approx(rows["ssp245"][2])
    assert rows["ssp585"][3] < rows["ssp585"][2]


def test_assets_without_a_usable_value_are_left_out_of_weighting(make_run):
    values = [(None, "missing"), (300.0, "given")]
    run = make_run(ASSETS, IMPACTS, PAIRS, values=values)
    assert weighted(run)["ssp585"][:4] == (1, 300.0, pytest.approx(0.07), pytest.approx(0.03))
    assert trajectory(run)["ssp585"][0] == 2  # equal weighting still counts both


def test_failed_assets_are_left_out_of_weighting_not_counted_as_zero(make_run):
    impacts = [(1, "Wind", "ssp585", 2050, 0.01)]
    run = make_run(ASSETS, impacts, [("ssp585", 2050)], [(2, "ssp585", 2050)], values=VALUES)
    assert weighted(run)["ssp585"][:4] == (1, 100.0, pytest.approx(0.01), pytest.approx(0.01))


def test_a_zero_total_value_has_no_weighted_mean(make_run):
    values = [(0.0, "given"), (0.0, "given")]
    run = make_run(ASSETS, IMPACTS, PAIRS, values=values)
    assert weighted(run)["ssp585"] == (2, 0.0, None, None, 0.0, 0.0)


def test_pairs_without_results_have_no_weighted_figures(make_run):
    run = make_run(ASSETS, IMPACTS, PAIRS, values=VALUES)
    assert weighted(run)["ssp370"] == (0, None, None, None, None, None)


def test_summary_counts_values(make_run, asset_row):
    assets = [asset_row(1), asset_row(2), asset_row(3)]
    values = [(100.0, "given"), (None, "missing"), (None, "invalid")]
    run = make_run(assets, values=values, currency="USD")
    result = summary(run)
    assert {k: result[k] for k in ("valued_assets", "missing_values", "invalid_values")} == {
        "valued_assets": 1,
        "missing_values": 1,
        "invalid_values": 1,
    }
    assert (result["total_value"], result["currency"], result["has_values"]) == (
        100.0,
        "USD",
        True,
    )


def test_a_value_column_with_no_usable_value_has_no_values(make_run):
    run = make_run(ASSETS, values=[(None, "invalid"), (None, "missing")])
    assert summary(run)["has_values"] is False
