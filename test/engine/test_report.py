import io
import re
import threading
from pathlib import Path

import pytest
from pypdf import PdfReader

from engine import report, report_charts
from engine.report import TOP_ASSETS, build_report
from engine.store import create_run, set_status

ROOT = Path(__file__).resolve().parents[2]
FRONT = ROOT / "app" / "front" / "src"

# DejaVu Sans covers Latin, Greek and Cyrillic, but not CJK.
HOSTILE = "<b>bold</b> & =cmd() Москва"


def make_run(tmp_path, assets, impacts=(), scores=(), pairs=(), flood=(), failures=(), name=None):
    """A completed run. assets: (row_num, asset_id, lat, lon, type_source, assessable, reason)."""
    run = create_run(tmp_path, len(assets), name)
    with run.connect() as con:
        con.executemany(
            "INSERT INTO assets (row_num, asset_id, lat, lon, match_type, physrisk_type, "
            "type_source, location_fallback, assessable, exclusion_reason) "
            "VALUES (?, ?, ?, ?, 'intersects', ?, ?, false, ?, ?)",
            [
                (n, i, lat, lon, "Buildings/Commercial" if ok else None, src, ok, reason)
                for n, i, lat, lon, src, ok, reason in assets
            ],
        )
        for sql, rows in (
            (
                "INSERT INTO impacts (row_num, hazard, impact_type, scenario, year, aal) "
                "VALUES (?, ?, 'damage', ?, ?, ?)",
                impacts,
            ),
            ("INSERT INTO scores VALUES (?, ?, ?, ?, ?, ?)", scores),
            ("INSERT INTO assessment_pairs VALUES (?, ?)", pairs),
            (
                "INSERT INTO asset_flood_zones (row_num, fema_status, fema_zone, fema_zone_key, "
                "fema_matches, fema_conflict) VALUES (?, ?, ?, ?, 1, false)",
                flood,
            ),
            ("INSERT INTO assess_failures VALUES (?, ?, ?, 'boom')", failures),
        ):
            if rows:
                con.executemany(sql, rows)
    set_status(run, "completed")
    return run


ASSETS = [
    (1, HOSTILE, 29.7, -95.3, "assumed", True, None),
    (2, "warehouse", 40.4, -3.7, "class", True, None),
    (3, None, 51.0, 7.0, "assumed", True, None),
    (4, "bad", None, None, None, False, "invalid"),
]
IMPACTS = [
    (1, "Wind", "ssp585", 2050, 0.03),
    (1, "RiverineInundation", "ssp585", 2050, 0.01),
    (2, "Wind", "ssp585", 2050, 0.001),
    (3, "RiverineInundation", "ssp585", 2050, 0.0),
    (1, "Wind", "ssp245", 2050, 0.02),
    (2, "Wind", "ssp245", 2050, 0.0005),
    (1, "Wind", "historical", None, 0.01),
    (2, "Wind", "historical", None, 0.0002),
    (1, "RiverineInundation", "historical", None, 0.005),
]
SCORES = [
    (1, "Wind", "ssp585", 2050, 3, "High impact"),
    (2, "Wind", "ssp585", 2050, 1, "Low impact"),
    (1, "Hail", "ssp585", 2050, -1, "No vulnerability"),
    (2, "Hail", "ssp585", 2050, -1, "No vulnerability"),
]
PAIRS = [("ssp585", 2050), ("ssp245", 2050), ("ssp370", 2050), ("historical", None)]
FLOOD = [(1, "mapped", "AE", "AE"), (2, "not_us", None, None), (3, "not_us", None, None)]


@pytest.fixture
def run(tmp_path):
    return make_run(
        tmp_path,
        ASSETS,
        IMPACTS,
        SCORES,
        PAIRS,
        FLOOD,
        failures=[(3, "ssp585", 2050)],
        name="portfolio <q3>.csv",
    )


def text_of(pdf: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf))
    return re.sub(r"\s+", " ", " ".join(page.extract_text() for page in reader.pages))


def test_report_is_a_pdf_with_every_section(run):
    pdf = build_report(run, "ssp585", 2050)
    assert pdf.startswith(b"%PDF")
    text = text_of(pdf)
    for heading in (
        "Physical climate risk report",
        "Headline figures",
        "How far to trust these results",
        "Change over time",
        "Loss by hazard: SSP5-8.5, 2050",
        "Where the assets are",
        "Highest-risk assets",
        "FEMA flood zones",
        "How to read this report",
    ):
        assert heading in text


def test_upload_text_is_shown_literally(run):
    text = text_of(build_report(run, "ssp585", 2050))
    assert HOSTILE in text
    assert "portfolio <q3>.csv" in text
    assert "Row 3" in text  # an asset with no id


def test_top_assets_are_sorted_by_total_with_their_type_source(run):
    text = text_of(build_report(run, "ssp585", 2050))
    table = text[text.index("Highest-risk assets") : text.index("Annual loss by hazard")]
    assert table.index(HOSTILE) < table.index("warehouse") < table.index("Row 3")
    assert "(assumed)" in table and "(from class)" in table
    assert "Zone AE" in table and "Outside the US" in table
    assert "High impact" in table


def test_top_assets_are_capped(tmp_path):
    count = TOP_ASSETS + 5
    assets = [(n, f"site-{n:03}", 10.0, float(n), "class", True, None) for n in range(1, count + 1)]
    impacts = [(n, "Wind", "ssp585", 2050, n / 1000) for n in range(1, count + 1)]
    run = make_run(tmp_path, assets, impacts, pairs=[("ssp585", 2050)])
    text = text_of(build_report(run, "ssp585", 2050))
    table = text[text.index("Highest-risk assets") :]
    assert f"site-{count:03}" in table
    assert "site-005" not in table  # the five smallest are left out
    assert f"The {TOP_ASSETS} assets with the highest" in text


def test_baseline_has_losses_and_no_scores(run):
    text = text_of(build_report(run, "historical", None))
    assert "Loss by hazard: Today (baseline)" in text
    assert "Highest score" not in text
    assert "treats as 2025" in text


def test_scenario_compares_with_history_over_the_same_hazards(run):
    text = text_of(build_report(run, "ssp245", 2050))
    # ssp245 has only wind: (0.01 + 0.0002) / 2 of the historical wind loss.
    assert "Historical, same hazards: 0.510%" in text


def test_no_model_hazards_are_not_low_results(run):
    text = text_of(build_report(run, "ssp585", 2050))
    assert "Hail No model" in text
    assert "are not low results" in text


def test_caveats_are_reported(run):
    text = text_of(build_report(run, "ssp585", 2050))
    assert "1 asset missing results after a failed request" in text
    assert "Missing results are not a zero loss" in text
    assert "1 excluded: Invalid" in text
    assert "No results at all for SSP3-7.0" in text
    assert "The building type was assumed for 67% of assets" in text
    assert "A low score or a zero is not proof of low risk" in text


def test_a_pair_without_results_says_so(run):
    text = text_of(build_report(run, "ssp370", 2050))
    assert "physrisk returned no losses for this scenario and year" in text
    assert "No asset has results for this scenario and year" in text


def test_scenarios_with_no_shared_hazards_get_a_sentence_not_a_chart(tmp_path):
    assets = [(1, "a", 10.0, 10.0, "class", True, None)]
    impacts = [(1, "Wind", "ssp245", 2050, 0.01), (1, "Fire", "ssp126", 2050, 0.02)]
    run = make_run(tmp_path, assets, impacts, pairs=[("ssp245", 2050), ("ssp126", 2050)])
    text = text_of(build_report(run, "ssp245", 2050))
    assert "share no hazards" in text


def test_a_run_from_before_flood_zones_and_clusters_still_builds(run):
    with run.connect() as con:
        con.execute("DROP TABLE asset_flood_zones")
        con.execute("DROP TABLE asset_clusters")
    text = text_of(build_report(run, "ssp585", 2050))
    assert "FEMA flood zones" not in text
    assert "FEMA data not loaded" in text


def test_reports_build_in_parallel(run):
    pdfs: list[bytes] = []
    errors: list[Exception] = []

    def build():
        try:
            pdfs.append(build_report(run, "ssp585", 2050))
        except Exception as e:  # noqa: BLE001 - reported below
            errors.append(e)

    threads = [threading.Thread(target=build) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert len(pdfs) == 4 and all("Highest-risk assets" in text_of(pdf) for pdf in pdfs)


def test_loss_breaks_match_the_dashboard():
    # lossBreaks([1..10]) in mapColors.ts: linear quantiles at 0.2, 0.4, 0.6 and 0.8.
    breaks = report_charts.loss_breaks([float(n) for n in range(1, 11)])
    assert breaks == pytest.approx([2.8, 4.6, 6.4, 8.2])
    assert report_charts.loss_class(2.8, breaks) == 0  # a tie stays below
    assert report_charts.loss_class(10.0, breaks) == 4


def test_percent_matches_the_dashboard():
    assert report.percent(None) == "–"
    assert report.percent(0) == "0%"
    assert report.percent(0.000001) == "<0.001%"
    assert report.percent(0.0123456) == "1.235%"


# The report repeats labels and colours that live in the front end. These keep them in step.


def _ts_entries(path: Path, pattern: str) -> list[tuple[str, ...]]:
    return re.findall(pattern, path.read_text())


def test_hazard_labels_and_colours_match_the_dashboard():
    hazards = _ts_entries(
        FRONT / "lib" / "hazards.ts",
        r'\{ key: "(\w+)", label: "([^"]+)", color: "var\(--(series-\d)\)" \}',
    )
    css = (FRONT / "styles.css").read_text()
    light = css[: css.index("@media")]
    tokens = dict(re.findall(r"--(series-[\w]+): (#[0-9a-f]{6});", light))
    assert [(k, label) for k, label, _ in hazards] == list(report.HAZARD_LABELS.items())
    assert {k: tokens[token] for k, _, token in hazards} == report_charts.HAZARD_COLORS
    assert tokens["series-other"] == report_charts.SERIES_OTHER


def test_scenario_and_exclusion_labels_match_the_dashboard():
    format_ts = (FRONT / "lib" / "format.ts").read_text()
    block = format_ts[format_ts.index("SCENARIO_LABELS") :]
    scenarios = dict(re.findall(r"(\w+): \"([^\"]+)\",", block[: block.index("};")]))
    assert scenarios == report.SCENARIO_LABELS
    quality = (FRONT / "components" / "dashboard" / "DataQuality.tsx").read_text()
    block = quality[quality.index("EXCLUSION_LABELS") :]
    exclusions = dict(re.findall(r'(\w+): "([^"]+)",', block[: block.index("};")]))
    assert exclusions == report.EXCLUSION_LABELS


def test_loss_ramp_matches_the_dashboard_map():
    map_colors = (FRONT / "lib" / "mapColors.ts").read_text()
    light = re.search(r"const LIGHT_RAMP = \[([^\]]+)\]", map_colors).group(1)
    assert re.findall(r'"(#[0-9a-f]{6})"', light) == report_charts.LOSS_RAMP
    no_result = re.search(r'NO_RESULT_COLOR = "(#[0-9a-f]{6})"', map_colors).group(1)
    assert no_result == report_charts.NO_RESULT_COLOR
