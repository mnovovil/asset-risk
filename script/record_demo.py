# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright==1.64.1", "imageio-ffmpeg==0.7.0"]
# ///
"""Record docs/assets/demo.gif from a real run of the sample CSV: uv run script/record_demo.py

It starts its own compose project, port and volume, so other runs can't appear in the GIF and a
running stack isn't touched. It needs a browser (uvx playwright@1.64.1 install
chromium-headless-shell), and reuses the asset-risk:local image unless --build is passed, so pass
that after changing the app.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "app" / "front" / "public" / "sample_portfolio.csv"
OUTPUT = ROOT / "docs" / "assets" / "demo.gif"
PROJECT = "asset-risk-demo"
PORT = "18768"
BASE = f"http://127.0.0.1:{PORT}"

VIEWPORT = {"width": 1280, "height": 800}
GIF_WIDTH = 960
GIF_FPS = 10
# Without these, headless Chromium has no WebGL and the map stays blank.
CHROMIUM_ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]

RUN_TIMEOUT_SECONDS = 300
PROGRESS_SPEEDUP = 4
SAMPLE_EVERY_SECONDS = 0.25
MAP_SETTLE_SECONDS = 4
SCROLL_STEPS = 4
SCROLL_STEP_SECONDS = 0.08
SCROLL_MARGIN_PX = 40

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
        start = self.page.evaluate("scrollY")
        for step in range(1, SCROLL_STEPS + 1):
            y = start + (target - start) * step / SCROLL_STEPS
            self.page.evaluate("y => window.scrollTo({top: y, behavior: 'instant'})", y)
            self.shot(hold if step == SCROLL_STEPS else SCROLL_STEP_SECONDS)


def compose(*args: str) -> None:
    env = os.environ | {
        "API_PORT": PORT,
        "HOST_UID": str(os.getuid()),
        "HOST_GID": str(os.getgid()),
    }
    compose_file = str(ROOT / "docker" / "compose.yml")
    subprocess.run(
        ["docker", "compose", "-p", PROJECT, "-f", compose_file, *args], env=env, check=True
    )


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
    rec.caption(
        f"Step 2: find each building, classify it, calculate its risk (sped up {PROGRESS_SPEEDUP}×)"
    )
    current_stage = page.locator('.stage-label[aria-current="step"]')
    finished = page.get_by_role("heading", name="Where the risk is")
    seen: list[str] = []
    deadline = time.monotonic() + RUN_TIMEOUT_SECONDS
    last = time.monotonic()
    while not finished.is_visible():
        if time.monotonic() > deadline:
            raise RuntimeError(f"the run didn't finish in {RUN_TIMEOUT_SECONDS} s")
        fail_on_alert(page)
        if current_stage.count() > 0:
            stage = current_stage.inner_text()
            if stage not in seen:
                seen.append(stage)
        now = time.monotonic()
        rec.shot((now - last) / PROGRESS_SPEEDUP)
        last = now
        page.wait_for_timeout(SAMPLE_EVERY_SECONDS * 1000)
    return seen


def record_results(rec: Recorder, tiles_loaded: list[str]) -> None:
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
    rec.caption("Where the risk is, by asset")
    rec.scroll_to("Where the risk is", 3.5)
    rec.caption("What drives the loss, against the historical baseline")
    rec.scroll_to("Annual loss by hazard", 3.5)
    rec.caption('Scores per hazard: "No model" and "No data" are not low risk')
    rec.scroll_to("Risk by asset and hazard", 4)
    rec.caption("The details of one asset")
    rec.click(page.get_by_role("button", name="nairobi-centre").first)
    page.get_by_role("dialog", name="Asset details").wait_for()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    fail_on_alert(page)
    rec.shot(4.5)
    page.keyboard.press("Escape")
    page.get_by_role("dialog", name="Asset details").wait_for(state="hidden")
    rec.caption("Change over time, comparing scenarios on shared hazards only")
    rec.scroll_to("Change over time", 3.5)
    rec.caption("How far to trust these results: a screening tool, not a site assessment")
    rec.scroll_to("How far to trust these results", 5.5)


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
        page.on(
            "response",
            lambda r: tiles_loaded.append(r.url) if r.ok and r.url.endswith(".pbf") else None,
        )
        rec = Recorder(page, folder)
        record_upload(rec)
        seen = record_progress(rec)
        record_results(rec, tiles_loaded)
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
        compose("up", "--detach", "--wait", *(["--build"] if args.build else []))
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
