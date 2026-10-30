import pytest

from engine.store import create_run, summary


def make_run(tmp_path, assets, impacts=(), pairs=(), failures=()):
    run = create_run(tmp_path, len(assets))
    with run.connect() as con:
        statements = (
            (
                "INSERT INTO assets (row_num, asset_id, match_type, physrisk_type, type_source, "
                "location_fallback, assessable, exclusion_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                assets,
            ),
            (
                "INSERT INTO impacts (row_num, hazard, impact_type, scenario, year, aal) "
                "VALUES (?, ?, 'damage', ?, ?, ?)",
                impacts,
            ),
            ("INSERT INTO assessment_pairs VALUES (?, ?)", pairs),
            ("INSERT INTO assess_failures VALUES (?, ?, ?, 'boom')", failures),
        )
        for sql, rows in statements:
            if rows:
                con.executemany(sql, rows)
    return run


def asset(
    row_num, assessable=True, match="intersects", source="class", fallback=False, reason=None
):
    return (
        row_num,
        f"a{row_num}",
        match,
        "Buildings/Commercial" if assessable else None,
        source if assessable else None,
        fallback if assessable else None,
        assessable,
        reason,
    )


# Asset 1 has 1% + 2% and asset 2 has 3% + 4% under ssp585. ssp245 has no fire, as in the real data.
ASSETS = [asset(1), asset(2)]
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
def run(tmp_path):
    return make_run(tmp_path, ASSETS, IMPACTS, PAIRS)


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


def test_failed_assets_are_left_out_of_means_and_counted(tmp_path):
    impacts = [(1, "Wind", "ssp585", 2050, 0.01)]
    run = make_run(tmp_path, ASSETS, impacts, [("ssp585", 2050)], [(2, "ssp585", 2050)])
    assert trajectory(run)["ssp585"][:2] == (1, pytest.approx(0.01))
    assert summary(run)["failed_assets"] == 1


def test_summary_counts(tmp_path):
    run = make_run(
        tmp_path,
        [
            asset(1),
            asset(2, source="assumed"),
            asset(3, source="assumed", match="none"),
            asset(4, match="nearest", fallback=True),
            asset(5, assessable=False, match="invalid", reason="invalid"),
            asset(6, assessable=False, match="none", reason="off_land"),
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
    }
    assert sorted(fetch(run, "SELECT reason, assets FROM v_exclusions")) == [
        ("invalid", 1),
        ("off_land", 1),
    ]


def test_views_work_on_an_empty_run(tmp_path):
    run = create_run(tmp_path, 0)
    assert summary(run)["total_assets"] == 0
    assert fetch(run, "SELECT * FROM v_portfolio_trajectory") == []
