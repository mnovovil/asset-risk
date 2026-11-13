# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright==1.64.1", "imageio-ffmpeg==0.7.0"]
# ///
"""Record docs/assets/demo.gif from a real run of the demo portfolio: uv run script/record_demo.py

After the upload and progress screens, where it holds on the FEMA flood zone stage, it opens the
New Orleans risk-concentration bubble on the map, clicks one of its assets to show its details, its
FEMA flood zone and what that zone means, its river flood depth curve and hazard maps, zooms the
hazard map out to all of southern Louisiana, then goes through the rest of the dashboard,
including the present-day (baseline) view.

It needs the FEMA flood zone database that .asset-risk.json names (flood_zones_db): see
script/build_flood_zones.py. Without it every asset's flood zone would read "unavailable".

It starts its own compose project, port and volume, so other runs can't appear in the GIF and a
running stack isn't touched. It needs a browser (uvx playwright@1.64.1 install
chromium-headless-shell), and reuses the asset-risk:local image unless --build is passed, so pass
that after changing the app.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
# 500 properties in the USA and Spain: 13 dense metro clusters and 48 isolated towns.
SAMPLE = ROOT / "docs" / "assets" / "demo_portfolio.csv"
OUTPUT = ROOT / "docs" / "assets" / "demo.gif"
PROJECT = "asset-risk-demo"
PORT = "18768"
BASE = f"http://127.0.0.1:{PORT}"

VIEWPORT = {"width": 1280, "height": 800}
GIF_WIDTH = 960
GIF_FPS = 10
# Without these, headless Chromium has no WebGL and the map stays blank.
CHROMIUM_ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]

# 500 assets take several minutes, nearly all of it assessing: see .claude/learnings.md.
RUN_TIMEOUT_SECONDS = 1800
PROGRESS_SPEEDUP = 30
SAMPLE_EVERY_SECONDS = 1
# Polled faster than frames are taken, so a short stage the page does show isn't missed.
POLL_SECONDS = 0.2
# The FEMA lookup is usually quicker than the page's 1.5 s progress check, so the page may never
# show it as current. Hold the first frame where it is current or ticked off, long enough to read.
FLOOD_ZONES_STAGE = "Flood zones"
FLOOD_ZONES_HOLD_SECONDS = 3.5
MAP_SETTLE_SECONDS = 4
SCROLL_STEPS = 4
SCROLL_STEP_SECONDS = 0.08
SCROLL_MARGIN_PX = 40
# Hovering the map in steps this far apart finds every bubble (the smallest has a 12 px radius).
BUBBLE_SCAN_STEP_PX = 16
ZOOM_FRAMES = 8
ZOOM_FRAME_SECONDS = 0.1
# The cluster the GIF opens: New Orleans has the portfolio's highest flood and wind losses. The
# point is in the city centre, so it falls inside the cluster's bounds whatever DBSCAN's settings.
FOCUS_NAME = "New Orleans"
FOCUS_LAT, FOCUS_LON = 29.95, -90.07
# The asset the GIF opens, by the French Quarter. FEMA maps it in Zone X, behind the levees.
FOCUS_ASSET = "US-312"
HAZARD_MAPS = [
    ("RiverineInundation", "Hazard maps around it: river flood depth, 1 in 1000 years"),
    ("CoastalInundation", "The same view, a different hazard: coastal flood depth"),
]
# Scrolling out over the panel's hazard map, from street level (zoom 14) to about zoom 5.6, where it
# is about 6 degrees of longitude wide. Each step is about 0.56 zoom levels in headless Chromium.
# Zooming keeps the asset under the pointer, so a pointer right of centre puts the asset there and
# shows more to its west: all of southern Louisiana. physrisk's tiles stop at zoom 6.
ZOOM_OUT_STEPS = 15
ZOOM_OUT_POINTER = (0.72, 0.45)  # share of the map's width and height
ZOOM_OUT_WHEEL_PX = 500
ZOOM_OUT_STEP_SECONDS = 0.15
BASELINE_LABEL = "Today (baseline)"

SHOW_CAPTION = """text => {
  let caption = document.getElementById("demo-caption");
  if (!caption) {
    caption = document.createElement("div");
    caption.id = "demo-caption";
    caption.style.cssText = `position: fixed; left: 50%; bottom: 20px; transform: translateX(-50%);
      z-index: 1000; width: max-content; max-width: 1200px; padding: 10px 20px; color: #fff;
      border-radius: 8px; background: #1f2933; font: 600 20px/1.3 system-ui, sans-serif;
      text-align: center;`;
    document.body.append(caption);
    // So the end of the page can scroll clear of the caption.
    document.body.style.paddingBottom = "100px";
  }
  caption.textContent = text;
}"""


# The map closes its popup on a mousemove with nothing under it.
HIDE_MAP_POPUP = """() => document.querySelector(".map canvas")
  .dispatchEvent(new MouseEvent("mousemove", {clientX: 0, clientY: 0, bubbles: true}))"""


@dataclass
class Frame:
    path: Path
    seconds: float


class Recorder:
    def __init__(self, page: Page, folder: Path):
        self.page = page
        self.folder = folder
        self.frames: list[Frame] = []

    def caption(self, text: str) -> None:
        self.page.evaluate(SHOW_CAPTION, text)

    def click(self, target: Locator) -> None:
        target.click()
        # A pointer left over a chart would open its tooltip in later frames.
        self.page.mouse.move(0, 0)

    def click_at(self, x: float, y: float) -> None:
        """Click the map, then close its popup, which a pointer leaving the page leaves open."""
        self.page.mouse.click(x, y)
        self.page.mouse.move(0, 0)
        self.page.evaluate(HIDE_MAP_POPUP)

    def shot(self, seconds: float) -> None:
        path = self.folder / f"{len(self.frames):04d}.png"
        self.page.screenshot(path=path)
        # Identical frames add to the file for nothing, so hold the last one for longer.
        if self.frames and self.frames[-1].path.read_bytes() == path.read_bytes():
            self.frames[-1].seconds += seconds
            path.unlink()
        else:
            self.frames.append(Frame(path, seconds))

    def scroll_to(self, heading: str, hold: float) -> None:
        """Scroll in steps so a viewer keeps their place, then hold on the section."""
        section = self.page.get_by_role("heading", name=heading, level=2)
        target = section.evaluate(
            f"e => e.getBoundingClientRect().top + scrollY - {SCROLL_MARGIN_PX}"
        )
        self.scroll_to_y(target, hold)

    def scroll_to_y(self, target: float, hold: float) -> None:
        start = self.page.evaluate("scrollY")
        for step in range(1, SCROLL_STEPS + 1):
            y = start + (target - start) * step / SCROLL_STEPS
            self.page.evaluate("y => window.scrollTo({top: y, behavior: 'instant'})", y)
            self.shot(hold if step == SCROLL_STEPS else SCROLL_STEP_SECONDS)


def flood_zones_file() -> Path:
    """The FEMA flood zone database from .asset-risk.json, which the GIF needs to show zones."""
    settings = ROOT / ".asset-risk.json"
    if not settings.is_file():
        raise RuntimeError(f"no {settings.name}: run terraform -chdir=infra apply first")
    configured = json.loads(settings.read_text()).get("flood_zones_db")
    if not configured:
        raise RuntimeError("flood_zones_db is null, so the GIF couldn't show FEMA flood zones")
    path = Path(configured) if Path(configured).is_absolute() else ROOT / configured
    if not path.is_file():
        raise RuntimeError(f"no FEMA flood zone database at {path}: see build_flood_zones.py")
    return path


def compose(*args: str, flood_zones: Path | None = None) -> None:
    env = os.environ | {
        "API_PORT": PORT,
        "HOST_UID": str(os.getuid()),
        "HOST_GID": str(os.getgid()),
    }
    if flood_zones is not None:
        # As script/start.sh does: mount only the file, at the path the container reads.
        env |= {"FLOOD_ZONES_FILE": str(flood_zones), "FLOOD_ZONES_DB": "/fema/flood-zones.duckdb"}
    compose_file = str(ROOT / "docker" / "compose.yml")
    subprocess.run(
        ["docker", "compose", "-p", PROJECT, "-f", compose_file, *args], env=env, check=True
    )


def dashboard_filter(page: Page, name: str) -> Locator:
    # Not get_by_label: a select's accessible name includes its options, and a chart's label
    # mentions "scenario" too.
    return page.locator(".filters label", has_text=name).locator("select")


def fail_on_alert(page: Page) -> None:
    alert = page.get_by_role("alert")
    if alert.count() > 0:
        raise RuntimeError(f"the app showed an error: {alert.first.inner_text()}")


def record_upload(rec: Recorder) -> None:
    rec.page.goto(BASE)
    rec.page.get_by_role("heading", name="Assess a portfolio").wait_for()
    rec.page.wait_for_load_state("networkidle")
    rec.caption("Step 1: upload a CSV of id, lat, lon")
    rec.shot(2.5)
    rec.page.locator('input[type="file"]').set_input_files(SAMPLE)
    start = rec.page.get_by_role("button", name="Assess this portfolio")
    start.wait_for()
    start.evaluate("e => e.scrollIntoView({block: 'center', behavior: 'instant'})")
    rec.shot(3.5)
    rec.click(start)


def record_progress(rec: Recorder) -> list[str]:
    """Capture the real stages, returning the ones the page showed."""
    page = rec.page
    step_caption = (
        f"Step 2: find each building, classify it, calculate its risk (sped up {PROGRESS_SPEEDUP}×)"
    )
    rec.caption(step_caption)
    current_stage = page.locator('.stage-label[aria-current="step"]')
    flood_zones_reached = page.locator(
        ".stage-current .stage-label, .stage-done .stage-label", has_text=FLOOD_ZONES_STAGE
    )
    held_flood_zones = False
    finished = page.get_by_role("heading", name="Where the risk is")
    seen: list[str] = []
    deadline = time.monotonic() + RUN_TIMEOUT_SECONDS
    last = time.monotonic()
    while not finished.is_visible():
        if time.monotonic() > deadline:
            raise RuntimeError(f"the run didn't finish in {RUN_TIMEOUT_SECONDS} s")
        fail_on_alert(page)
        stage = current_stage.inner_text() if current_stage.count() > 0 else None
        new_stage = stage is not None and stage not in seen
        if new_stage:
            seen.append(stage)
        now = time.monotonic()
        if not held_flood_zones and flood_zones_reached.count() > 0:
            held_flood_zones = True
            rec.caption("Each US asset also gets its FEMA flood zone")
            rec.shot((now - last) / PROGRESS_SPEEDUP + FLOOD_ZONES_HOLD_SECONDS)
            rec.caption(step_caption)
            last = now
        elif new_stage or now - last >= SAMPLE_EVERY_SECONDS:
            rec.shot((now - last) / PROGRESS_SPEEDUP)
            last = now
        page.wait_for_timeout(POLL_SECONDS * 1000)
    if not held_flood_zones:
        raise RuntimeError(f"the page never showed the {FLOOD_ZONES_STAGE} stage reached")
    return seen


# Hovers the map in a grid and groups the points by the popup they open, so the script finds bubbles
# and assets where a viewer would, without reaching into the app. A popup's title is either "N
# nearby assets" (a bubble) or an asset's label.
SCAN_MAP = """({step}) => {
  const map = document.querySelector(".map");
  const canvas = map.querySelector("canvas");
  const box = map.getBoundingClientRect();
  const top = Math.max(box.top, 0) + 8, bottom = Math.min(box.bottom, innerHeight) - 8;
  const found = new Map();
  for (let y = top; y < bottom; y += step) {
    for (let x = box.left + 8; x < box.right - 8; x += step) {
      canvas.dispatchEvent(new MouseEvent("mousemove", {clientX: x, clientY: y, bubbles: true}));
      const popup = document.querySelector(".maplibregl-popup");
      const title = popup?.querySelector("strong")?.textContent ?? "";
      if (!title) continue;
      const key = popup.textContent;
      const hit = found.get(key) ?? {title, xs: [], ys: []};
      hit.xs.push(x);
      hit.ys.push(y);
      found.set(key, hit);
    }
  }
  canvas.dispatchEvent(new MouseEvent("mousemove", {clientX: 0, clientY: 0, bubbles: true}));
  const mean = values => values.reduce((a, b) => a + b, 0) / values.length;
  return [...found.values()].map(h => ({title: h.title, x: mean(h.xs), y: mean(h.ys)}));
}"""
BUBBLE_SUFFIX = " nearby assets"


def scan_map(page: Page) -> tuple[list[dict], list[dict]]:
    """The bubbles (with their asset count) and the asset points on screen."""
    hits = page.evaluate(SCAN_MAP, {"step": BUBBLE_SCAN_STEP_PX})
    bubbles = [
        h | {"count": int(h["title"].removesuffix(BUBBLE_SUFFIX))}
        for h in hits
        if h["title"].endswith(BUBBLE_SUFFIX)
    ]
    points = [h for h in hits if not h["title"].endswith(BUBBLE_SUFFIX)]
    return bubbles, points


def api(page: Page, path: str, **params) -> list[dict]:
    response = page.request.get(f"{BASE}/api/runs/{run_id(page)}/{path}", params=params or None)
    if not response.ok:
        raise RuntimeError(f"GET {path} returned {response.status}")
    return response.json()


def contains(bounds: list[float], lat: float, lon: float) -> bool:
    west, south, east, north = bounds
    # East is past 180 for a cluster across the antimeridian.
    return south <= lat <= north and any(west <= x <= east for x in (lon, lon + 360))


def mercator_y(lat: float) -> float:
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def fit_line(pairs: list[tuple[float, float]]) -> tuple[float, float]:
    """Least squares slope and intercept of screen position against map coordinate."""
    n = len(pairs)
    mean_u = sum(u for u, _ in pairs) / n
    mean_v = sum(v for _, v in pairs) / n
    spread = sum((u - mean_u) ** 2 for u, _ in pairs)
    if spread == 0:
        raise RuntimeError("the matched bubbles are in a line, so they can't place the others")
    slope = sum((u - mean_u) * (v - mean_v) for u, v in pairs) / spread
    return slope, mean_v - slope * mean_u


def find_bubble(bubbles: list[dict], clusters: list[dict], target: dict) -> dict:
    """The bubble on screen for the API's target cluster.

    A popup doesn't give a bubble's coordinates, so match by asset count. When another bubble has
    the same count, place the target on screen from the bubbles whose count is unique.
    """
    candidates = [b for b in bubbles if b["count"] == target["assets"]]
    if not candidates:
        raise RuntimeError(f"no bubble on screen has {FOCUS_NAME}'s {target['assets']} assets")
    if len(candidates) == 1:
        return candidates[0]
    on_screen = Counter(b["count"] for b in bubbles)
    in_api = Counter(c["assets"] for c in clusters)
    anchors = [
        (next(c for c in clusters if c["assets"] == b["count"]), b)
        for b in bubbles
        if on_screen[b["count"]] == 1 and in_api[b["count"]] == 1
    ]
    if len(anchors) < 2:
        raise RuntimeError(f"can't tell which of {len(candidates)} bubbles is {FOCUS_NAME}")
    ax, bx = fit_line([(c["lon"], b["x"]) for c, b in anchors])
    ay, by = fit_line([(mercator_y(c["lat"]), b["y"]) for c, b in anchors])
    x, y = ax * target["lon"] + bx, ay * mercator_y(target["lat"]) + by
    return min(candidates, key=lambda b: (b["x"] - x) ** 2 + (b["y"] - y) ** 2)


def record_clusters(rec: Recorder) -> dict:
    """Show the opening bubbles, open New Orleans', and return that cluster."""
    page = rec.page
    rec.caption("Where the risk is: groups of nearby assets, from green (lowest) to red (highest)")
    rec.scroll_to("Where the risk is", 4)
    clusters = api(page, "clusters")
    target = next((c for c in clusters if contains(c["bounds"], FOCUS_LAT, FOCUS_LON)), None)
    if target is None:
        raise RuntimeError(f"no cluster contains {FOCUS_NAME}")
    bubbles, _ = scan_map(page)
    print(f"Bubbles on screen: {len(bubbles)}, API clusters: {len(clusters)}")
    bubble = find_bubble(bubbles, clusters, target)
    print(
        f"{FOCUS_NAME}: cluster {target['cluster_id']} of {target['assets']} assets, "
        f"bubble at ({bubble['x']:.0f}, {bubble['y']:.0f})"
    )
    page.mouse.move(bubble["x"], bubble["y"])
    page.wait_for_timeout(300)
    rec.caption(f"{FOCUS_NAME}: the bubble's mean, and how many of its assets have results")
    rec.shot(4)
    rec.caption("Click a bubble to zoom in to its assets")
    rec.click_at(bubble["x"], bubble["y"])
    for _ in range(ZOOM_FRAMES):
        page.wait_for_timeout(ZOOM_FRAME_SECONDS * 1000)
        rec.shot(ZOOM_FRAME_SECONDS)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(MAP_SETTLE_SECONDS * 1000)
    fail_on_alert(page)
    rec.caption(f"Every asset in {FOCUS_NAME}, coloured by its own annual loss")
    rec.shot(4)
    return target


def open_focus_asset(rec: Recorder, cluster: dict) -> Locator:
    """Click the focus asset on the map, and return the panel it opens."""
    page = rec.page
    bubbles, points = scan_map(page)
    if bubbles or not points:
        raise RuntimeError(f"the map didn't zoom in to {FOCUS_NAME}'s assets")
    rows = [a["row_num"] for a in api(page, "assets") if a["asset_id"] == FOCUS_ASSET]
    if len(rows) != 1 or rows[0] not in cluster["row_nums"]:
        raise RuntimeError(f"{FOCUS_ASSET} isn't one asset in the {FOCUS_NAME} cluster")
    point = next((p for p in points if p["title"] == FOCUS_ASSET), None)
    if point is None:
        raise RuntimeError(f"{FOCUS_ASSET} isn't on the map, or is hidden under another point")
    page.mouse.move(point["x"], point["y"])
    page.wait_for_timeout(300)
    if page.locator(".maplibregl-popup strong").first.text_content() != FOCUS_ASSET:
        raise RuntimeError(f"hovering {FOCUS_ASSET}'s point shows another asset")
    rec.caption(f"Click an asset to see its details: {FOCUS_ASSET}, in the Mississippi")
    rec.shot(3)
    rec.click_at(point["x"], point["y"])
    panel = page.get_by_role("dialog", name="Asset details")
    panel.wait_for()
    # The heading reads "Asset" until the asset's details load.
    try:
        panel.get_by_role("heading", name=FOCUS_ASSET, exact=True, level=2).wait_for(timeout=10_000)
    except PlaywrightError:
        raise RuntimeError(f"clicking {FOCUS_ASSET} didn't open its details") from None
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    fail_on_alert(page)
    rec.caption("Its building, and how it was modelled")
    rec.shot(4)
    record_flood_zone(rec, panel, rows[0])
    rec.caption("Its loss by hazard")
    scroll_panel_to(panel, "Results for")
    rec.shot(4)
    rec.caption("River flood depth at the asset, by how rare the flood is")
    scroll_panel_to(panel, "River flood depth")
    page.wait_for_timeout(500)
    rec.shot(5)
    return panel


def record_flood_zone(rec: Recorder, panel: Locator, row_num: int) -> None:
    """Show the asset's FEMA flood zone, then open the explainer of what that zone means."""
    page = rec.page
    asset = page.request.get(f"{BASE}/api/runs/{run_id(page)}/assets/{row_num}").json()
    if asset.get("fema_status") != "mapped":
        raise RuntimeError(f"{FOCUS_ASSET}'s FEMA flood zone is {asset.get('fema_status')}")
    # The caption says so, so check it: FEMA's subtype for a shaded Zone X behind a levee.
    if "LEVEE" not in (asset.get("fema_zone_subtype") or ""):
        raise RuntimeError(f"{FOCUS_ASSET} isn't in a levee-protected FEMA zone any more")
    rec.caption(f"Its FEMA flood zone: {FOCUS_ASSET} is behind New Orleans' levees")
    scroll_panel_to(panel, "FEMA flood zone")
    rec.shot(5)
    explainer = panel.locator("details.twin > summary", has_text="mean?")
    rec.caption("What the zone means, and whether flood insurance is required")
    rec.click(explainer)
    explainer.evaluate("e => e.scrollIntoView({block: 'start', behavior: 'instant'})")
    rec.shot(5.5)
    rec.click(explainer)  # closed again, so the panel's later sections sit where they did


def run_id(page: Page) -> str:
    return page.url.rstrip("/").rsplit("/", 1)[-1]


def scroll_panel_to(panel: Locator, heading: str) -> None:
    panel.get_by_role("heading", name=heading, level=3).evaluate(
        "e => e.scrollIntoView({block: 'start', behavior: 'instant'})"
    )


def record_hazard_maps(rec: Recorder, panel: Locator, hazard_tiles: list[str]) -> None:
    """Show river flood around the asset, zoom out to the region, then switch to coastal flood."""
    page = rec.page
    heading = panel.get_by_role("heading", name="Hazard maps", level=3)
    heading.wait_for()
    heading.evaluate("e => e.scrollIntoView({block: 'start', behavior: 'instant'})")
    for index, (hazard, caption) in enumerate(HAZARD_MAPS):
        panel.get_by_label("Hazard").select_option(hazard)
        rec.caption(caption)
        settle_map(page)
        # A tile only loads where physrisk has one: none would mean an empty hazard map.
        if not any(f"/hazard-maps/{hazard}/" in url for url in hazard_tiles):
            raise RuntimeError(f"no {hazard} map tile loaded")
        rec.shot(4.5)
        if index == 0:
            zoom_out_hazard_map(rec, panel)


def settle_map(page: Page) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(MAP_SETTLE_SECONDS * 1000)
    fail_on_alert(page)


def zoom_out_hazard_map(rec: Recorder, panel: Locator) -> None:
    """Scroll out over the panel's map until it shows all of southern Louisiana."""
    page = rec.page
    box = panel.locator(".asset-map").bounding_box()
    if box is None:
        raise RuntimeError("the asset panel has no hazard map")
    rec.caption("Zoom out: physrisk's flood maps cover all of southern Louisiana")
    # Start at the asset, in the map's centre, so the pointer's spot is the asset's.
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.wheel(0, ZOOM_OUT_WHEEL_PX)
    page.wait_for_timeout(ZOOM_OUT_STEP_SECONDS * 1000)
    share_x, share_y = ZOOM_OUT_POINTER
    page.mouse.move(box["x"] + box["width"] * share_x, box["y"] + box["height"] * share_y)
    for _ in range(ZOOM_OUT_STEPS - 1):
        page.mouse.wheel(0, ZOOM_OUT_WHEEL_PX)
        page.wait_for_timeout(ZOOM_OUT_STEP_SECONDS * 1000)
        rec.shot(ZOOM_OUT_STEP_SECONDS)
    page.mouse.move(0, 0)
    settle_map(page)
    rec.shot(5)


def record_results(rec: Recorder, tiles_loaded: list[str], hazard_tiles: list[str]) -> None:
    page = rec.page
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(MAP_SETTLE_SECONDS * 1000)
    fail_on_alert(page)
    # The attribution is a licence condition, and no tiles means a blank map.
    if not tiles_loaded:
        raise RuntimeError("no map tiles loaded")
    if "OpenStreetMap" not in page.locator(".maplibregl-ctrl-attrib").inner_text():
        raise RuntimeError("the map's attribution isn't showing")

    rec.caption("Step 3: see the results, including how many building types were assumed")
    rec.shot(4.5)
    cluster = record_clusters(rec)
    panel = open_focus_asset(rec, cluster)
    record_hazard_maps(rec, panel, hazard_tiles)
    page.keyboard.press("Escape")
    panel.wait_for(state="hidden")
    rec.caption("What drives the loss, against the historical baseline")
    rec.scroll_to("Annual loss by hazard", 3.5)
    rec.caption('Scores per hazard: "No model" and "No data" are not low risk')
    rec.scroll_to("Risk by asset and hazard", 4)
    rec.caption("Change over time, comparing scenarios on shared hazards only")
    rec.scroll_to("Change over time", 3.5)
    record_baseline(rec)
    rec.caption("How far to trust these results: a screening tool, not a site assessment")
    rec.scroll_to("How far to trust these results", 5.5)


def record_baseline(rec: Recorder) -> None:
    """Switch the whole dashboard to present-day risk."""
    page = rec.page
    rec.caption("Or see present-day risk: physrisk's historical baseline")
    rec.scroll_to_y(0, 1.5)
    dashboard_filter(page, "Scenario").select_option(label=BASELINE_LABEL)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(MAP_SETTLE_SECONDS * 1000)
    fail_on_alert(page)
    rec.shot(4.5)
    rec.caption("Today's loss by hazard, on the hazards the baseline has")
    rec.scroll_to("Annual loss by hazard", 4)


def encode(frames: list[Frame], folder: Path, output: Path) -> None:
    # The concat format ignores the last duration unless the last file is listed again.
    listing = [line for f in frames for line in (f"file '{f.path}'", f"duration {f.seconds:.3f}")]
    listing.append(f"file '{frames[-1].path}'")
    concat = folder / "frames.txt"
    concat.write_text("\n".join(listing) + "\n")
    video_filter = (
        f"fps={GIF_FPS},scale={GIF_WIDTH}:-1:flags=lanczos,split[a][b];"
        "[a]palettegen=max_colors=128:stats_mode=diff[palette];"
        "[b][palette]paletteuse=dither=none:diff_mode=rectangle"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error"]
    command += ["-f", "concat", "-safe", "0", "-i", str(concat)]
    subprocess.run([*command, "-vf", video_filter, "-loop", "0", str(output)], check=True)


def record(folder: Path, output: Path) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(args=CHROMIUM_ARGS)
        page = browser.new_page(viewport=VIEWPORT, color_scheme="light")
        tiles_loaded: list[str] = []
        hazard_tiles: list[str] = []

        def on_response(response) -> None:
            if not response.ok:
                return
            if response.url.endswith(".pbf"):
                tiles_loaded.append(response.url)
            elif "/hazard-maps/" in response.url:
                hazard_tiles.append(response.url)

        page.on("response", on_response)
        rec = Recorder(page, folder)
        record_upload(rec)
        seen = record_progress(rec)
        record_results(rec, tiles_loaded, hazard_tiles)
        browser.close()
    print(f"Stages on screen: {', '.join(seen) or 'none'}")
    print(f"Frames: {len(rec.frames)}, {sum(f.seconds for f in rec.frames):.0f} s")
    encode(rec.frames, folder, output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Record the README's demo GIF.")
    parser.add_argument("--build", action="store_true", help="rebuild the image first")
    parser.add_argument("--output", type=Path, default=OUTPUT, help="default: %(default)s")
    args = parser.parse_args()

    try:
        # Inside the try, because a container that fails its health check is still left running.
        flood_zones = flood_zones_file()
        compose(
            "up",
            "--detach",
            "--wait",
            *(["--build"] if args.build else []),
            flood_zones=flood_zones,
        )
        with tempfile.TemporaryDirectory() as folder:
            record(Path(folder), args.output)
    except (RuntimeError, PlaywrightError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        compose("down", "--volumes")
    print(f"Wrote {args.output} ({args.output.stat().st_size / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
