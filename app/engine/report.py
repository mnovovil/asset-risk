"""A finished run's PDF report for one scenario and year, built on request from its SQL views.

It reads only the run's database: no physrisk, no S3 and no map tiles, so it needs neither the
physrisk lock nor the network. The report says what the dashboard says, caveats included, because
someone reading only the PDF has nothing else to go on.

Text from the upload (ids, the file's name) goes through `_text`, because reportlab parses markup in
a Paragraph. Hazard, scenario and exclusion labels match app/front/src/lib, and test_report.py
checks they still do. FEMA text comes from app/engine/data/fema_zones.json only.
"""

from __future__ import annotations

import io
from datetime import datetime
from functools import cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from xml.sax.saxutils import escape

import matplotlib
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from engine import report_charts, results
from engine.flood_zone_data import definitions
from engine.store import Run, status

TOP_ASSETS = 20
HISTORICAL = "historical"
BASELINE_LABEL = "Today (baseline)"
# Past this share, the assumption shapes the results more than the data does (DataQuality.tsx).
ASSUMED_WARNING_SHARE = 0.5
SMALLEST_SHOWN = 0.00001  # 0.001%

# app/front/src/lib/hazards.ts, in its validated order.
HAZARD_LABELS = {
    "RiverineInundation": "River flood",
    "CoastalInundation": "Coastal flood",
    "Wind": "Tropical cyclone wind",
    "Fire": "Wildfire",
    "Hail": "Hail",
    "PluvialInundation": "Surface water flood",
    "ChronicHeat": "Chronic heat",
    "Drought": "Drought",
}
# app/front/src/lib/format.ts
SCENARIO_LABELS = {
    "historical": "Historical",
    "ssp126": "SSP1-2.6",
    "ssp245": "SSP2-4.5",
    "ssp370": "SSP3-7.0",
    "ssp585": "SSP5-8.5",
}
# app/front/src/components/dashboard/DataQuality.tsx
EXCLUSION_LABELS = {
    "invalid": "Invalid (missing id, or bad latitude or longitude)",
    "off_land": "Off land (no building and no country nearby)",
    "no_curve": "No damage model for this building type and region",
}
TYPE_SOURCES = {"class": "from class", "subtype": "from subtype", "assumed": "assumed"}
# physrisk's negative scores: no result, never a low score (lib/dashboard.ts, scoreKind).
NO_RESULT_SCORES = {-1: "No model", -2: "No data"}

MODEL_LIMITS = [
    "This is for screening many sites, not for decisions about one site.",
    "Hazard data has pixels of about 1 km, so results depend on exact coordinates.",
    "Flood results assume a global estimate of flood protection, and a site's real defences may "
    "be very different.",
    "River flood comes from a single climate model.",
    "Wind means tropical cyclones only. Zero wind doesn't mean no wind risk, for example from "
    "European windstorms.",
    "Results are a share of asset value, as asset values aren't known here.",
]
READING_NOTES = [
    "<b>Average annual loss (AAL)</b> is the expected damage per year as a share of asset value. "
    "It isn't a forecast for any one year.",
    "<b>Portfolio figures are equal-weighted means</b> of the assets with results: a list of id, "
    "lat, lon has no asset values, so a small shed counts as much as a large factory, and there "
    "are no currency figures.",
    "<b>A low score or a zero is not proof of low risk.</b> A point in mid-ocean scores Very low "
    "for flood, and a zero river flood loss means the exact point is dry in the data, not that "
    "the area has no flood risk.",
    "<b>Hazards differ by scenario</b>, and physrisk doesn't warn about it. Totals from different "
    "scenarios are only compared over the hazards every scenario has.",
    "<b>No model</b> means physrisk has no damage model for the hazard and building type, and "
    "<b>No data</b> that it has no hazard data there. Neither is a low result.",
    "See docs/methodology.md in the asset-risk repository for the full method.",
]

INK = colors.HexColor(report_charts.INK)
MUTED = colors.HexColor(report_charts.MUTED)
LINE = colors.HexColor("#e6e5e0")
WARNING = colors.HexColor("#8a5e00")
WARNING_BG = colors.HexColor("#fdf6e3")
HEADER_BG = colors.HexColor("#f4f3ef")
FONT = "DejaVuSans"
FONT_BOLD = "DejaVuSans-Bold"


@cache
def _register_fonts() -> None:
    """DejaVu Sans, from matplotlib's own data, so the report and its charts share one font and
    ids in most scripts render, which reportlab's built-in Helvetica can't do."""
    fonts = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    pdfmetrics.registerFont(TTFont(FONT, str(fonts / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(fonts / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_BOLD)


def _styles() -> dict[str, ParagraphStyle]:
    body = ParagraphStyle("body", fontName=FONT, fontSize=9, leading=12.5, textColor=INK)
    return {
        "body": body,
        "small": ParagraphStyle("small", parent=body, fontSize=7.5, leading=9.5),
        "cell": ParagraphStyle("cell", parent=body, fontSize=7.5, leading=9.5, alignment=TA_LEFT),
        "muted": ParagraphStyle("muted", parent=body, fontSize=8, leading=11, textColor=MUTED),
        "title": ParagraphStyle(
            "title", parent=body, fontName=FONT_BOLD, fontSize=20, leading=25, spaceAfter=4
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=body, fontSize=11, leading=15, textColor=MUTED, spaceAfter=10
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=body,
            fontName=FONT_BOLD,
            fontSize=13,
            leading=17,
            spaceBefore=12,
            spaceAfter=5,
        ),
        "h3": ParagraphStyle(
            "h3",
            parent=body,
            fontName=FONT_BOLD,
            fontSize=10,
            leading=13,
            spaceBefore=6,
            spaceAfter=3,
        ),
        "kpi": ParagraphStyle("kpi", parent=body, fontName=FONT_BOLD, fontSize=15, leading=19),
        "warning": ParagraphStyle(
            "warning",
            parent=body,
            textColor=WARNING,
            backColor=WARNING_BG,
            borderPadding=5,
            spaceBefore=4,
            spaceAfter=8,
        ),
    }


def _text(value: object) -> str:
    """Untrusted text, made safe to put in reportlab's markup."""
    return escape(str(value))


def percent(value: float | None) -> str:
    """As the dashboard's percent(): zero stays distinct from a very small loss."""
    if value is None:
        return "–"
    if value == 0:
        return "0%"
    if value < SMALLEST_SHOWN:
        return "<0.001%"
    return f"{value * 100:.3f}%"


def _range(low: float, high: float) -> str:
    return percent(low) if percent(low) == percent(high) else f"{percent(low)} to {percent(high)}"


def plural(value: int, one: str, many: str | None = None) -> str:
    return f"{value:,} {one if value == 1 else (many or one + 's')}"


def join_list(items: list[str]) -> str:
    if len(items) < 2:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def hazard_label(key: str) -> str:
    return HAZARD_LABELS.get(key, key)


def scenario_label(key: str) -> str:
    return SCENARIO_LABELS.get(key, key)


def pair_label(scenario: str, year: int | None) -> str:
    return BASELINE_LABEL if scenario == HISTORICAL else f"{scenario_label(scenario)}, {year}"


def sort_hazards(keys) -> list[str]:
    order = list(HAZARD_LABELS)
    rank = {key: i for i, key in enumerate(order)}
    return sorted(set(keys), key=lambda key: (rank.get(key, len(order)), key))


def _asset_label(row: dict) -> str:
    return row["asset_id"] if row["asset_id"] is not None else f"Row {row['row_num']}"


def _physrisk_version() -> str:
    try:
        return version("physrisk-lib")
    except PackageNotFoundError:
        return "unknown"


def _image(png: bytes, width: float) -> Image:
    image = Image(io.BytesIO(png))
    image.drawWidth, image.drawHeight = width, width * image.imageHeight / image.imageWidth
    return image


def _table(rows: list[list], widths: list[float], header: bool = True) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    style = [
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
            ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ]
    table.setStyle(TableStyle(style))
    return table


class _Report:
    """Collects the run's data once, then lays out each section."""

    def __init__(self, run: Run, scenario: str, year: int | None):
        self.run, self.scenario, self.year = run, scenario, year
        self.baseline = scenario == HISTORICAL
        self.s = _styles()
        self.state = status(run)
        self.summary = results.summary(run)
        self.trajectory = results.trajectory(run)
        self.coverage = results.coverage(run)
        self.point = next(
            (p for p in self.trajectory if p["scenario"] == scenario and p["year"] == year),
            None,
        )
        self.hazards = results.portfolio_hazards(run, scenario, year)
        self.score_kinds = {
            row["hazard"]: row["best_score"] for row in results.score_kinds(run, scenario, year)
        }
        self.top = results.top_assets(run, scenario, year, TOP_ASSETS)
        self.map_points = results.map_totals(run, scenario, year)
        self.clusters = results.clusters(run)
        self.fema = results.flood_zone_counts(run)
        self.assumed_types = results.assumed_types(run)
        self.historical = (
            None if self.baseline else results.historical_same_hazards(run, scenario, year)
        )

    # Shared pieces

    def p(self, markup: str, style: str = "body") -> Paragraph:
        return Paragraph(markup, self.s[style])

    def bullets(self, items: list[str], style: str = "body") -> list[Flowable]:
        bullet = ParagraphStyle(f"{style}-bullet", parent=self.s[style], leftIndent=10)
        return [Paragraph(item, bullet, bulletText="•") for item in items]

    def heading(self, text: str) -> Paragraph:
        return self.p(text, "h2")

    @property
    def width(self) -> float:
        return A4[0] - 36 * mm

    # Sections

    def cover(self) -> list[Flowable]:
        source = self.state.get("source_name")
        created = self.state.get("created_at")
        created_text = (
            created.strftime("%-d %B %Y, %H:%M %Z") if isinstance(created, datetime) else "–"
        )
        pairs = [p for p in self.trajectory if p["year"] is not None]
        assessed = join_list(
            sorted(
                {scenario_label(p["scenario"]) for p in pairs},
            )
        )
        years = join_list([str(y) for y in sorted({p["year"] for p in pairs})])
        rows = [
            ["Portfolio", self.p(_text(source) if source else "Unnamed upload", "cell")],
            ["Shown in this report", self.p(_text(pair_label(self.scenario, self.year)), "cell")],
            ["Scenarios assessed", self.p(_text(assessed or "None"), "cell")],
            ["Years assessed", self.p(_text(years or "None"), "cell")],
            [
                "Building type assumed",
                self.p(
                    _text(join_list(self.assumed_types)) if self.assumed_types else "None", "cell"
                ),
            ],
            ["Run", self.p(_text(self.run.run_id), "cell")],
            ["Run started", self.p(_text(created_text), "cell")],
            ["Model", self.p(f"physrisk-lib {_text(_physrisk_version())}", "cell")],
        ]
        return [
            self.p("Physical climate risk report", "title"),
            self.p(
                f"{_text(source) if source else 'Portfolio'} · "
                f"{_text(pair_label(self.scenario, self.year))}",
                "subtitle",
            ),
            _table(rows, [45 * mm, self.width - 45 * mm], header=False),
        ]

    def headline(self) -> list[Flowable]:
        s = self.summary
        assumed = s["assumed_type"] / s["assessable"] if s["assessable"] else 0
        point = self.point or {}
        hazards = point.get("hazards") or 0
        if self.baseline:
            loss_note = (
                f"of asset value, over {plural(hazards, 'hazard')}. physrisk's present-day "
                "baseline, which it treats as 2025."
            )
        else:
            loss_note = (
                f"of asset value, over {plural(hazards, 'hazard')}. Historical, same hazards: "
                f"{percent(self.historical)}."
            )
        assessed_note = (
            f"{plural(s['failed_assets'], 'asset')} missing some results"
            if s["failed_assets"]
            else "Assets sent to physrisk"
        )
        cells = [
            ("Mean annual loss, equal-weighted", percent(point.get("mean_total_aal")), loss_note),
            (
                "Assets assessed",
                f"{s['assessable']:,} of {s['total_assets']:,}",
                assessed_note,
            ),
            ("Assets excluded", f"{s['excluded']:,}", "Invalid, off land or no damage model"),
            (
                "Building type assumed",
                f"{round(assumed * 100)}%",
                f"{plural(s['assumed_type'], 'asset')} had no building type to use",
            ),
        ]
        width = self.width / 2
        grid = [
            [
                [self.p(_text(title), "muted"), self.p(_text(value), "kpi"), self.p(note, "small")]
                for title, value, note in cells[i : i + 2]
            ]
            for i in (0, 2)
        ]
        table = Table(grid, colWidths=[width, width], hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        return [self.heading("Headline figures"), table]

    def trust(self) -> list[Flowable]:
        s = self.summary
        assumed = s["assumed_type"] / s["assessable"] if s["assessable"] else 0
        flowables: list[Flowable] = [self.heading("How far to trust these results")]
        if assumed > ASSUMED_WARNING_SHARE:
            using = f", using {_text(join_list(self.assumed_types))}" if self.assumed_types else ""
            flowables.append(
                self.p(
                    f"The building type was assumed for {round(assumed * 100)}% of assets{using}. "
                    "The type changes the flood damage model, so these results can move materially "
                    "if the assumption is wrong.",
                    "warning",
                )
            )
        items = [
            f"{plural(s['assumed_type'], 'asset')} with an assumed building type",
            f"{plural(s['nearest_match'], 'asset')} matched to a nearby building, which may be "
            "a neighbour",
            f"{plural(s['no_building'], 'asset')} with no building found within range",
            f"{plural(s['global_curve'], 'asset')} using a global, not regional, damage model",
        ]
        if s["failed_assets"]:
            items.append(
                f"{plural(s['failed_assets'], 'asset')} missing results after a failed request. "
                "Missing results are not a zero loss."
            )
        items += [
            f"{e['assets']:,} excluded: {_text(EXCLUSION_LABELS.get(e['reason'], e['reason']))}"
            for e in s["exclusions"]
        ]
        missing = sort_hazards(
            c["hazard"]
            for c in self.coverage
            if c["scenario"] == self.scenario and c["year"] == self.year and not c["covered"]
        )
        if missing:
            items.append(
                "Not available for this scenario: "
                f"{_text(join_list([hazard_label(h) for h in missing]))}"
            )
        empty = sorted(
            {p["scenario"] for p in self.trajectory if p["year"] is not None and p["assets"] == 0}
        )
        if empty:
            items.append(
                f"No results at all for {_text(join_list([scenario_label(e) for e in empty]))}. "
                f"physrisk's data doesn't cover {'it' if len(empty) == 1 else 'them'}."
            )
        flowables += [self.p("This portfolio", "h3"), *self.bullets(items)]
        flowables += [self.p("The model", "h3"), *self.bullets(MODEL_LIMITS)]
        return flowables

    def change_over_time(self) -> list[Flowable]:
        shared = sort_hazards(self.summary["shared_hazards"])
        flowables: list[Flowable] = [self.heading("Change over time")]
        series: dict[str, list[tuple[int, float]]] = {}
        for p in self.trajectory:
            if p["year"] is not None and p["mean_shared_aal"] is not None:
                series.setdefault(p["scenario"], []).append((p["year"], p["mean_shared_aal"]))
        baseline = next(
            (
                p["mean_shared_aal"]
                for p in self.trajectory
                if p["year"] is None and p["mean_shared_aal"] is not None
            ),
            None,
        )
        if not shared or not series:
            flowables.append(
                self.p(
                    "The scenarios in this run share no hazards, so their losses can't be compared "
                    "over time. Each scenario's own figures are in the sections below for the "
                    "scenario and year this report shows."
                )
            )
            return flowables
        flowables.append(
            self.p(
                "Equal-weighted mean annual loss over only the hazards every scenario has: "
                f"{_text(join_list([hazard_label(h) for h in shared]))}. Totals over other "
                "hazards can't be compared across scenarios.",
                "muted",
            )
        )
        labels = {scenario: scenario_label(scenario) for scenario in series}
        png = report_charts.trajectory_chart(dict(sorted(series.items())), baseline, labels)
        flowables.append(_image(png, self.width))
        return [KeepTogether(flowables)]

    def loss_by_hazard(self) -> list[Flowable]:
        flowables: list[Flowable] = [
            self.heading(f"Loss by hazard: {_text(pair_label(self.scenario, self.year))}")
        ]
        by_hazard = {row["hazard"]: row for row in self.hazards}
        ordered = sort_hazards(by_hazard)
        no_result = {
            hazard: NO_RESULT_SCORES.get(best, "Error")
            for hazard, best in self.score_kinds.items()
            if best is not None and best < 0 and hazard not in by_hazard
        }
        if not ordered:
            flowables.append(
                self.p(
                    "physrisk returned no losses for this scenario and year. That means no "
                    "results, not zero loss."
                )
            )
        else:
            values = [(h, hazard_label(h), by_hazard[h]["mean_aal"] or 0.0) for h in ordered]
            flowables.append(_image(report_charts.hazard_bars(values), self.width))
            rows = [["Hazard", "Mean annual loss", "Assets with results"]]
            rows += [
                [
                    hazard_label(h),
                    percent(by_hazard[h]["mean_aal"]),
                    f"{by_hazard[h]['assets']:,}",
                ]
                for h in ordered
            ]
            rows += [[hazard_label(h), kind, "–"] for h, kind in sorted(no_result.items())]
            flowables.append(_table(rows, [60 * mm, 40 * mm, 40 * mm]))
        if no_result:
            flowables.append(Spacer(0, 4))
            flowables.append(
                self.p(
                    "“No model” and “No data” are not low results: physrisk has no damage model, "
                    "or no hazard data, for these assets.",
                    "muted",
                )
            )
        return flowables

    def asset_map(self) -> list[Flowable]:
        flowables: list[Flowable] = [self.heading("Where the assets are")]
        points = [(p["lon"], p["lat"], p["total_aal"]) for p in self.map_points]
        if not points:
            flowables.append(self.p("No asset has coordinates that can be placed on a map."))
            return flowables
        png, legend = report_charts.asset_map(points)
        flowables.append(_image(png, self.width))
        without = sum(1 for _, _, total in points if total is None)
        parts = [
            f'<font color="{item["color"]}">●</font> {_range(item["min"], item["max"])} '
            f"({plural(item['assets'], 'asset')})"
            for item in legend
        ]
        if without:
            parts.append(f"○ No result ({plural(without, 'asset')})")
        clusters = (
            f" {plural(len(self.clusters), 'cluster')} of nearby assets found."
            if self.clusters
            else ""
        )
        flowables.append(
            self.p(
                "Total annual loss for this scenario and year, coloured by quintile so each colour "
                f"holds about a fifth of the assets.{clusters}<br/>" + " · ".join(parts),
                "muted",
            )
        )
        return [KeepTogether(flowables)]

    def top_assets(self) -> list[Flowable]:
        flowables: list[Flowable] = [self.heading("Highest-risk assets")]
        if not self.top:
            flowables.append(self.p("No asset has results for this scenario and year."))
            return flowables
        flowables.append(
            self.p(
                f"The {plural(len(self.top), 'asset')} with the highest total annual loss for "
                f"{_text(pair_label(self.scenario, self.year))}. The CSV download has every asset.",
                "muted",
            )
        )
        zones = {zone["key"]: zone["label"] for zone in definitions()["zones"]}
        statuses = {status_["key"]: status_["label"] for status_ in definitions()["statuses"]}

        def fema(row: dict) -> str:
            if row["fema_status"] == "mapped":
                return zones.get(row["fema_zone_key"], row["fema_zone"] or "Mapped")
            return statuses.get(row["fema_status"], row["fema_status"])

        header = ["#", "Asset", "Lat, lon", "Building type", "FEMA flood zone", "Total loss"]
        if not self.baseline:
            header.append("Highest score")
        rows: list[list] = [header]
        for rank, row in enumerate(self.top, start=1):
            source = TYPE_SOURCES.get(row["type_source"], row["type_source"] or "")
            cells = [
                str(rank),
                self.p(_text(_asset_label(row)), "cell"),
                f"{row['lat']:.3f}, {row['lon']:.3f}",
                self.p(f"{_text(row['physrisk_type'] or '–')}<br/>({_text(source)})", "cell"),
                self.p(_text(fema(row)), "cell"),
                percent(row["total_aal"]),
            ]
            if not self.baseline:
                cells.append(self.p(_text(row["worst_label"] or "–"), "cell"))
            rows.append(cells)
        widths = [7 * mm, 32 * mm, 28 * mm, 34 * mm, 28 * mm, 18 * mm]
        if not self.baseline:
            widths.append(self.width - sum(widths))
        flowables.append(_table(rows, widths))

        hazards = sort_hazards(h for row in self.top for h in row["aal"])
        if hazards:
            flowables.append(self.p("Annual loss by hazard for these assets", "h3"))
            hazard_rows: list[list] = [
                ["Asset", *[self.p(f"<b>{_text(hazard_label(h))}</b>", "cell") for h in hazards]]
            ]
            hazard_rows += [
                [
                    self.p(_text(_asset_label(row)), "cell"),
                    *[percent(row["aal"].get(h)) for h in hazards],
                ]
                for row in self.top
            ]
            first = 40 * mm
            rest = (self.width - first) / len(hazards)
            flowables.append(_table(hazard_rows, [first] + [rest] * len(hazards)))
            flowables.append(
                self.p("A dash means physrisk returned no result for that hazard.", "muted")
            )
        return flowables

    def flood_zones(self) -> list[Flowable]:
        if not any(row["fema_status"] in ("mapped", "not_mapped") for row in self.fema):
            return []
        defs = definitions()
        zones = {zone["key"]: zone for zone in defs["zones"]}
        statuses = {status_["key"]: status_ for status_ in defs["statuses"]}
        rows: list[list] = [["FEMA flood zone", "Assets", "What it means"]]
        for row in self.fema:
            if row["fema_status"] == "mapped":
                zone = zones.get(row["fema_zone_key"], {})
                label, meaning = zone.get("label", row["fema_zone_key"]), zone.get("summary", "")
            else:
                status_ = statuses.get(row["fema_status"], {})
                label = status_.get("label", row["fema_status"])
                meaning = status_.get("summary", "")
            rows.append(
                [
                    self.p(_text(label), "cell"),
                    f"{row['assets']:,}",
                    self.p(_text(meaning), "cell"),
                ]
            )
        return [
            self.heading("FEMA flood zones"),
            self.p(
                "FEMA's regulatory flood zone at each US point, from the flood map the app was set "
                "up with. It's a separate source from physrisk's losses.",
                "muted",
            ),
            _table(rows, [40 * mm, 18 * mm, self.width - 58 * mm]),
        ]

    def reading(self) -> list[Flowable]:
        return [
            KeepTogether([self.heading("How to read this report"), *self.bullets(READING_NOTES)])
        ]

    def flowables(self) -> list[Flowable]:
        return [
            *self.cover(),
            *self.headline(),
            *self.trust(),
            *self.change_over_time(),
            *self.loss_by_hazard(),
            *self.asset_map(),
            *self.top_assets(),
            *self.flood_zones(),
            *self.reading(),
        ]


def build_report(run: Run, scenario: str, year: int | None) -> bytes:
    """The PDF for one assessed scenario and year of a completed run."""
    _register_fonts()
    report = _Report(run, scenario, year)
    buffer = io.BytesIO()
    footer = f"asset-risk · run {run.run_id}"

    def decorate(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(FONT, 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 10 * mm, footer)
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title="Physical climate risk report",
        author="asset-risk",
        subject=pair_label(scenario, year),
    )
    document.build(report.flowables(), onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()
