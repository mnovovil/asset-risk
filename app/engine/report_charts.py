"""The PDF report's figures, drawn with matplotlib and returned as PNG bytes.

Requests run in threads, and pyplot's global state isn't thread-safe, so this builds each `Figure`
directly and never imports pyplot.

Colours are the dashboard's light theme, so a printed report matches what's on screen:
`HAZARD_COLORS` and `SERIES_OTHER` are `--series-N` in app/front/src/styles.css, in the order of
app/front/src/lib/hazards.ts, and `LOSS_RAMP` is `LIGHT_RAMP` in app/front/src/lib/mapColors.ts.
They were validated there, and test_report.py checks they still match.
"""

from __future__ import annotations

import io
import json
import math
from collections.abc import Sequence
from functools import cache
from pathlib import Path

from matplotlib.collections import PolyCollection
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

DATA_DIR = Path(__file__).parent / "data"
DPI = 200

INK = "#0b0b0b"
MUTED = "#52514e"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
CARD = "#ffffff"
LAND = "#efeee9"
COASTLINE = "#c3c2b7"

HAZARD_COLORS = {
    "RiverineInundation": "#2a78d6",
    "CoastalInundation": "#eb6834",
    "Wind": "#1baf7a",
    "Fire": "#eda100",
    "Hail": "#e87ba4",
    "PluvialInundation": "#008300",
    "ChronicHeat": "#6250d6",
    "Drought": "#e34948",
}
SERIES_OTHER = "#898781"
# Scenarios on the trajectory chart reuse the hazard series in order; historical is a dashed line.
SCENARIO_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
LOSS_RAMP = ["#68c85f", "#93a703", "#ad7c0e", "#af4e03", "#a50e15"]
NO_RESULT_COLOR = "#898781"

# The map never zooms closer than this many degrees across, so one asset still shows its region.
MIN_MAP_SPAN_DEG = 6.0
MAP_PADDING = 0.15


def _style(ax) -> None:
    ax.set_facecolor(CARD)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def _png(fig: Figure) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=DPI, facecolor=CARD, bbox_inches="tight", pad_inches=0.04)
    return buffer.getvalue()


def percent_tick(value: float, _=None) -> str:
    """An axis tick as short as the scale allows, as the dashboard's percentTick."""
    if value == 0:
        return "0%"
    return f"{float(f'{value * 100:.2g}'):g}%"


def hazard_color(hazard: str) -> str:
    return HAZARD_COLORS.get(hazard, SERIES_OTHER)


def trajectory_chart(
    series: dict[str, list[tuple[int, float]]], baseline: float | None, labels: dict[str, str]
) -> bytes:
    """Mean loss over shared hazards by year: one line per scenario, and the baseline dashed."""
    fig = Figure(figsize=(6.6, 2.8), layout="constrained")
    ax = fig.add_subplot()
    _style(ax)
    years = sorted({year for points in series.values() for year, _ in points})
    for color, (scenario, points) in zip(SCENARIO_COLORS * 2, series.items(), strict=False):
        xs, ys = zip(*sorted(points), strict=True)
        ax.plot(xs, ys, marker="o", markersize=4, linewidth=2, color=color, label=labels[scenario])
    if baseline is not None:
        ax.axhline(baseline, color=MUTED, linestyle="--", linewidth=1.2, label="Today (baseline)")
    ax.set_xticks(years)
    ax.yaxis.set_major_formatter(FuncFormatter(percent_tick))
    ax.set_ylim(bottom=0)
    ax.set_ylabel("Mean annual loss", color=MUTED, fontsize=8)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="best")
    return _png(fig)


def hazard_bars(values: Sequence[tuple[str, str, float]]) -> bytes:
    """Mean loss by hazard, one horizontal bar each: (hazard key, label, mean loss)."""
    height = 0.45 + 0.32 * len(values)
    fig = Figure(figsize=(6.6, height), layout="constrained")
    ax = fig.add_subplot()
    _style(ax)
    ax.grid(axis="y", visible=False)
    labels = [label for _, label, _ in values]
    means = [mean for _, _, mean in values]
    ax.barh(labels, means, color=[hazard_color(key) for key, _, _ in values], height=0.6, zorder=2)
    ax.invert_yaxis()
    ax.xaxis.set_major_formatter(FuncFormatter(percent_tick))
    ax.set_xlim(left=0, right=max(means) * 1.05 if means and max(means) > 0 else 1e-4)
    return _png(fig)


@cache
def _countries() -> list[list[tuple[float, float]]]:
    """Every country's outer rings as (lon, lat) lists, from the committed Natural Earth data."""
    features = json.loads((DATA_DIR / "countries.geojson").read_text())["features"]
    rings = []
    for feature in features:
        geometry = feature["geometry"]
        polygons = (
            [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        )
        rings.extend([tuple(point[:2]) for point in polygon[0]] for polygon in polygons)
    return rings


def loss_breaks(totals: Sequence[float]) -> list[float]:
    """The quintiles of the losses, as the dashboard map's lossBreaks."""
    if not totals:
        return []
    ordered = sorted(totals)
    steps = len(LOSS_RAMP)
    breaks = []
    for i in range(1, steps):
        position = (len(ordered) - 1) * i / steps
        below = math.floor(position)
        above = min(below + 1, len(ordered) - 1)
        breaks.append(ordered[below] + (ordered[above] - ordered[below]) * (position - below))
    return breaks


def loss_class(total: float, breaks: Sequence[float]) -> int:
    """A loss equal to a break stays below it, so ties share a class."""
    return sum(1 for limit in breaks if total > limit)


def _extent(points: Sequence[tuple[float, float]]) -> tuple[float, float, float, float]:
    lons = [lon for lon, _ in points]
    lats = [lat for _, lat in points]
    west, east, south, north = min(lons), max(lons), min(lats), max(lats)
    pad_x = max((east - west) * MAP_PADDING, (MIN_MAP_SPAN_DEG - (east - west)) / 2, 0)
    pad_y = max((north - south) * MAP_PADDING, (MIN_MAP_SPAN_DEG - (north - south)) / 2, 0)
    return (
        max(west - pad_x, -180),
        min(east + pad_x, 180),
        max(south - pad_y, -85),
        min(north + pad_y, 85),
    )


def asset_map(points: Sequence[tuple[float, float, float | None]]) -> tuple[bytes, list[dict]]:
    """Assets as (lon, lat, total loss) on a plain map, coloured by loss quintile.

    Returns the PNG and its legend: one entry per class with assets, with the range of losses in it.
    Assets with no result are hollow, so they can't be mistaken for a low loss.
    """
    fig = Figure(figsize=(6.6, 3.6), layout="constrained")
    ax = fig.add_subplot()
    ax.set_facecolor("#f6f9fc")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color(AXIS)
    west, east, south, north = _extent([(lon, lat) for lon, lat, _ in points])
    ax.add_collection(
        PolyCollection(_countries(), facecolors=LAND, edgecolors=COASTLINE, linewidths=0.4)
    )
    ax.set_xlim(west, east)
    ax.set_ylim(south, north)
    ax.set_aspect(1 / max(math.cos(math.radians((south + north) / 2)), 0.2))

    totals = [total for _, _, total in points if total is not None]
    breaks = loss_breaks(totals)
    empty = [(lon, lat) for lon, lat, total in points if total is None]
    if empty:
        xs, ys = zip(*empty, strict=True)
        ax.scatter(xs, ys, s=14, facecolors="none", edgecolors=NO_RESULT_COLOR, linewidths=0.8)
    # Highest losses last, so they're drawn on top.
    scored = sorted(
        ((lon, lat, total) for lon, lat, total in points if total is not None), key=lambda p: p[2]
    )
    if scored:
        xs, ys, values = zip(*scored, strict=True)
        colors = [LOSS_RAMP[loss_class(value, breaks)] for value in values]
        ax.scatter(xs, ys, s=16, c=colors, edgecolors=CARD, linewidths=0.4, zorder=3)

    legend: dict[int, dict] = {}
    for total in totals:
        step = loss_class(total, breaks)
        item = legend.setdefault(
            step, {"color": LOSS_RAMP[step], "min": total, "max": total, "assets": 0}
        )
        item["min"] = min(item["min"], total)
        item["max"] = max(item["max"], total)
        item["assets"] += 1
    return _png(fig), [legend[step] for step in sorted(legend)]
