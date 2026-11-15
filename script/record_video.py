# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = [
#     "kokoro==0.9.4",
#     "misaki[en]==0.9.4",
#     "torch==2.15.0",
#     "numpy==2.4.6",
#     "pillow==13.0.0",
#     "playwright==1.64.1",
#     "imageio-ffmpeg==0.7.0",
#     "en-core-web-sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl",
# ]
#
# [tool.uv.sources]
# torch = { index = "pytorch-cpu" }
#
# [[tool.uv.index]]
# name = "pytorch-cpu"
# url = "https://download.pytorch.org/whl/cpu"
# explicit = true
# ///
"""Record docs/assets/demo.mp4, a narrated 60-second tour: uv run script/record_video.py

It follows the README GIF's tour (script/record_demo.py, whose pieces it reuses) from a real run of
the demo portfolio, with a Kokoro-82M voice-over instead of captions. Each scene zooms into what
its narration is about, and the narration is burned in as subtitles.

1. Voice: one clip per scene from Kokoro-82M on the CPU (voice af_heart, 24 kHz), with word
   timestamps, cached in ~/.cache/asset-risk/voice by text, voice, speed and model.
2. Fit: a scene is its clip plus 0.4 s. Over 60 s, the padding shrinks to 0.2 s, then the voice
   speeds up in steps to 1.1. If it still doesn't fit, it stops.
3. Record: 1920x1080 at device scale 2. Each shot keeps its declared length and the box of the
   element its beat is about. Map animations are stepped at 30 fps on Playwright's fake clock.
4. Zoom, subtitle and encode: Pillow crops each 30 fps frame from the 2x shot, eased between
   beats, and ffmpeg burns in the subtitles with libass, normalises the voice to -16 LUFS and
   encodes H.264 and AAC.

It needs what record_demo.py needs (Docker, the FEMA flood zone database, a browser). The first
run also downloads torch (CPU) and the Kokoro weights from Hugging Face. --frames keeps the shots
and their manifest, and --from-frames makes the video again from them without the browser.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import wave
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import record_demo as demo
import video_edit as edit
from PIL import Image
from playwright.sync_api import Locator, Page, sync_playwright

OUTPUT = demo.ROOT / "docs" / "assets" / "demo.mp4"
WIDTH, HEIGHT = 1920, 1080
SCALE = 2  # device_scale_factor, so a 2.2x zoom is still sharp
VIEWPORT = {"width": WIDTH, "height": HEIGHT}
SAMPLE_RATE = 24_000
VOICE = "af_heart"
MODEL = "hexgrad/Kokoro-82M"
VOICE_CACHE = Path.home() / ".cache" / "asset-risk" / "voice"
# A beat's visual change comes this far ahead of its word, so the eye is there when it's said.
BEAT_LEAD_SECONDS = 0.15
# Around a zoom target, in CSS pixels.
MARGIN_PX = 32
# A point the narration is about, like a bubble: zoomed in as far as allowed.
POINT_BOX_PX = 120
# Under -40 dBFS over a clip's last 100 ms counts as silence.
SILENCE_DBFS = -40
SCROLL_STEPS = 12
ZOOM_OUT_STEP_SECONDS = 0.1
LOUDNESS = "I=-16:TP=-1.5:LRA=11"
SUBTITLE = {"background": "#1f2933", "colour": "#ffffff"}  # as the GIF's caption

Target = Callable[[Page, tuple[float, float] | None], list[Locator] | None]


def css(selector: str) -> Target:
    return lambda page, _: [page.locator(selector).first]


def in_panel(*headings: tuple[str, str]) -> Target:
    """Elements of the asset panel: (heading, XPath from it), such as its section's next sibling."""

    def find(page: Page, _) -> list[Locator]:
        panel = page.get_by_role("dialog", name="Asset details")
        found = []
        for heading, path in headings:
            h3 = panel.locator("h3", has_text=heading).first
            found.append(h3.locator(f"xpath={path}") if path != "." else h3)
        return found

    return find


def section(heading: str) -> Target:
    return lambda page, _: [
        page.locator("section.panel", has=page.get_by_role("heading", name=heading, level=2))
    ]


def point(page: Page, spot: tuple[float, float] | None) -> None:
    return None  # the recorder makes the box from the point itself


def whole_frame(page: Page, _) -> None:
    return None


@dataclass(frozen=True)
class Beat:
    key: str  # the name the recorder gives what's on screen: see record_demo.py's captions
    target: Target
    word: str | None = None  # the narration's word it lands on; None for the scene's start
    occurrence: int = 1


@dataclass(frozen=True)
class Scene:
    text: str
    beats: tuple[Beat, ...]


MAP = css(".map")
HAZARD_MAP = css(".asset-map")
SCENES = (
    Scene(
        "Upload a list of coordinates. Asset Risk finds each building and assesses its physical "
        "climate risk.",
        (Beat("upload", css(".narrow .card")), Beat("stages", css("ol.stages"), "finds")),
    ),
    Scene(
        "Your whole portfolio at a glance: expected annual loss, and how many building types were "
        "assumed.",
        (Beat("figures", css(".kpis")),),
    ),
    Scene(
        "The map shows where risk concentrates, from green to red.",
        (Beat("map", MAP), Beat("bubble", point, "concentrates")),
    ),
    Scene(
        "Click New Orleans to see every building, coloured by its own annual loss.",
        (Beat("fly", MAP), Beat("assets", MAP, "every")),
    ),
    Scene(
        "Open one to see how it was modelled, its loss by hazard, and how that loss changes by "
        "scenario.",
        (
            Beat("asset", point),
            Beat(
                "modelled",
                in_panel(("Building", "."), ("How it was modelled", "following-sibling::dl[1]")),
                "modelled",
            ),
            Beat(
                "loss",
                in_panel(("Results for", "."), ("Results for", "following-sibling::div[1]")),
                "loss",
            ),
            Beat(
                "over_time",
                in_panel(("Over time", "."), ("Over time", "following-sibling::*[1]")),
                "changes",
            ),
        ),
    ),
    Scene(
        "Its FEMA flood zone, explained in plain language, including whether flood insurance is "
        "required.",
        (
            Beat(
                "zone",
                in_panel(("FEMA flood zone", "."), ("FEMA flood zone", "following-sibling::dl[1]")),
            ),
            Beat("explainer", css(".asset-panel details.twin"), "explained"),
        ),
    ),
    Scene(
        "Explore hazard maps around it: river and coastal flood, wildfire, cyclone wind and large "
        "hail.",
        (
            Beat("RiverineInundation", HAZARD_MAP),
            Beat("zoom_out", HAZARD_MAP, "maps"),
            Beat("CoastalInundation", HAZARD_MAP, "coastal"),
            Beat("Fire", HAZARD_MAP, "wildfire"),
            Beat("Wind", HAZARD_MAP, "cyclone"),
            Beat("Hail", HAZARD_MAP, "large"),
        ),
    ),
    Scene(
        "Compare scenarios on the hazards they share, or switch to present-day risk.",
        (
            Beat("trajectory", section("Change over time")),
            Beat(
                "baseline",
                lambda page, _: [page.locator(".filters"), page.locator(".kpis")],
                "switch",
            ),
        ),
    ),
    Scene(
        "And see exactly how far to trust the results. Asset Risk: know where your portfolio is "
        "exposed.",
        (
            Beat("trust", section("How far to trust these results")),
            Beat("end", whole_frame, "Asset"),
        ),
    ),
)
BEATS = [beat for scene in SCENES for beat in scene.beats]
BEAT_INDEX = {beat.key: index for index, beat in enumerate(BEATS)}


# Voice


@dataclass
class Clip:
    path: Path
    seconds: float
    words: list[edit.Word]
    timed: bool  # False when Kokoro gave no timestamps and the words are spread evenly


class Voice:
    """Kokoro-82M on the CPU, loaded only when a clip isn't cached."""

    def __init__(self, voice: str):
        self.voice = voice
        self.pipeline = None

    def clip(self, text: str, speed: float) -> Clip:
        key = json.dumps([text, self.voice, speed, MODEL, kokoro_version()])
        stem = VOICE_CACHE / hashlib.sha256(key.encode()).hexdigest()[:24]
        wav, meta = stem.with_suffix(".wav"), stem.with_suffix(".json")
        if not (wav.is_file() and meta.is_file()):
            self.generate(text, speed, wav, meta)
        info = json.loads(meta.read_text())
        words = [edit.Word(*w) for w in info["words"]]
        return Clip(wav, info["seconds"], words, info["timed"])

    def generate(self, text: str, speed: float, wav: Path, meta: Path) -> None:
        if self.pipeline is None:
            from kokoro import KPipeline

            self.pipeline = KPipeline(lang_code="a", repo_id=MODEL)
        chunks, words, offset, timed = [], [], 0.0, True
        for result in self.pipeline(text, voice=self.voice, speed=speed):
            audio = result.audio.numpy()
            for token in result.tokens or []:
                if token.start_ts is None or token.end_ts is None:
                    timed = False
                    continue
                words.append([token.text, offset + token.start_ts, offset + token.end_ts])
            chunks.append(audio)
            offset += len(audio) / SAMPLE_RATE
        audio = np.concatenate(chunks)
        if not timed or not words:
            timed = False
            words = [[w.text, w.start, w.end] for w in edit.even_words(text, offset)]
        VOICE_CACHE.mkdir(parents=True, exist_ok=True)
        write_wav(wav, audio)
        meta.write_text(json.dumps({"seconds": offset, "words": words, "timed": timed}))
        print(f"Voiced {len(audio) / SAMPLE_RATE:.2f} s at speed {speed}: {text[:40]}…")


def kokoro_version() -> str:
    from importlib.metadata import version

    return version("kokoro")


def write_wav(path: Path, audio: np.ndarray) -> None:
    samples = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(samples.tobytes())


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as source:
        data = source.readframes(source.getnframes())
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32767


def tail_dbfs(audio: np.ndarray, seconds: float = 0.1) -> float:
    tail = audio[-int(SAMPLE_RATE * seconds) :]
    rms = float(np.sqrt(np.mean(np.square(tail)))) if len(tail) else 0.0
    return 20 * np.log10(max(rms, 1e-9))


def narrate(voice: str) -> tuple[list[Clip], list[float], float]:
    """The clips and scene lengths at the slowest speed that fits in 60 s."""
    speaker = Voice(voice)
    for speed in edit.SPEEDS:
        clips = [speaker.clip(scene.text, speed) for scene in SCENES]
        scenes = edit.fit_scenes([c.seconds for c in clips])
        if scenes is not None:
            return clips, scenes, speed
        print(f"At speed {speed} the voice takes {sum(c.seconds for c in clips):.1f} s")
    raise RuntimeError(
        f"the narration doesn't fit in {edit.MAX_TOTAL:.0f} s even at speed {edit.SPEEDS[-1]}"
    )


@dataclass
class Timeline:
    scene_starts: list[float]
    scene_ends: list[float]
    beat_starts: list[float]
    cues: list[edit.Cue]


def timeline(clips: list[Clip], scenes: list[float]) -> Timeline:
    starts, beat_starts, cues, t = [], [], [], 0.0
    for scene, clip, length in zip(SCENES, clips, scenes, strict=True):
        starts.append(t)
        for index, beat in enumerate(scene.beats):
            if index == 0 or beat.word is None:
                beat_starts.append(t)
            else:
                word = edit.find_word(clip.words, beat.word, beat.occurrence)
                beat_starts.append(max(t, t + word - BEAT_LEAD_SECONDS, beat_starts[-1]))
        cues += edit.subtitle_cues(clip.words, t, t + length)
        t += length
    return Timeline(starts, [*starts[1:], t], beat_starts, cues)


# Recording


@dataclass
class Shot:
    path: str
    seconds: float
    motion: bool
    beat: str
    box: list[float] | None  # x, y, w, h in the shot's pixels


class VideoRecorder(demo.Recorder):
    """The GIF's recorder without captions, keeping each shot's beat and zoom target, and stepping
    animations at 30 fps on the page's fake clock."""

    scroll_steps = SCROLL_STEPS
    scroll_step_seconds = 1 / edit.FPS

    def __init__(self, page: Page, folder: Path):
        super().__init__(page, folder)
        self.shots: list[Shot] = []
        self.beat: str | None = None
        self.spot: tuple[float, float] | None = None
        self.paused = False

    def caption(self, text: str, beat: str, point: tuple[float, float] | None = None) -> None:
        if beat not in BEAT_INDEX:
            raise RuntimeError(f"the video has no beat {beat!r}: see SCENES")
        self.beat, self.spot = beat, point

    def shot(self, seconds: float, motion: bool = False) -> None:
        if self.beat is None:
            raise RuntimeError("a shot was taken before its beat")
        path = self.folder / f"{len(self.shots):04d}.png"
        self.page.screenshot(path=path)
        last = self.shots[-1] if self.shots else None
        if (
            last is not None
            and last.beat == self.beat
            and not (motion or last.motion)
            and (self.folder / last.path).read_bytes() == path.read_bytes()
        ):
            last.seconds += seconds
            path.unlink()
            return
        # A scroll's early steps can have the target off screen, so only a settled shot must
        # have it. A beat's last shot with a box sets its zoom.
        box = self.target_box(required=not motion)
        self.shots.append(Shot(path.name, seconds, motion, self.beat, box))

    def target_box(self, required: bool) -> list[float] | None:
        beat = BEATS[BEAT_INDEX[self.beat]]
        if beat.target is point:
            if self.spot is None:
                raise RuntimeError(f"the {beat.key} beat has no point")
            x, y = self.spot
            half = POINT_BOX_PX / 2
            box = edit.Box(x - half, y - half, POINT_BOX_PX, POINT_BOX_PX)
        else:
            locators = beat.target(self.page, self.spot)
            if locators is None:
                return None
            found = [loc.bounding_box() for loc in locators]
            boxes = [edit.Box(b["x"], b["y"], b["width"], b["height"]) for b in found if b]
            if not boxes:
                if not required:
                    return None
                raise RuntimeError(f"the {beat.key} beat's element isn't on screen")
            box = boxes[0]
            for other in boxes[1:]:
                box = box.union(other)
        visible = clip_to_viewport(box)
        if visible is None:
            if not required:
                return None
            raise RuntimeError(f"the {beat.key} beat's element is off screen")
        return [v * SCALE for v in (visible.x, visible.y, visible.w, visible.h)]

    @contextmanager
    def motion(self) -> Iterator[None]:
        now = self.page.evaluate("Date.now()") / 1000
        self.page.clock.pause_at(datetime.fromtimestamp(now, tz=UTC))
        self.paused = True
        try:
            yield
        finally:
            self.paused = False
            self.page.clock.resume()

    def wait(self, seconds: float) -> None:
        if self.paused:
            self.page.clock.run_for(round(seconds * 1000))
        else:
            super().wait(seconds)

    def advance(self, seconds: float) -> None:
        if not self.paused:
            super().advance(seconds)
            return
        for _ in range(max(1, round(seconds * edit.FPS))):
            self.page.clock.run_for(round(1000 / edit.FPS))
            self.shot(1 / edit.FPS, motion=True)


def clip_to_viewport(box: edit.Box) -> edit.Box | None:
    x0, y0 = max(box.x, 0), max(box.y, 0)
    x1, y1 = min(box.x + box.w, WIDTH), min(box.y + box.h, HEIGHT)
    if x1 <= x0 or y1 <= y0:
        return None
    return edit.Box(x0, y0, x1 - x0, y1 - y0)


END_CARD = """([title, url]) => {
  const card = document.createElement("div");
  card.style.cssText = `position: fixed; inset: 0; z-index: 2000; display: grid;
    place-content: center; gap: 24px; text-align: center; background: var(--surface);
    color: var(--ink);`;
  const name = document.createElement("div");
  name.textContent = title;
  name.style.cssText = "font-size: 112px; font-weight: 700; letter-spacing: -0.02em;";
  const link = document.createElement("div");
  link.textContent = url;
  link.style.cssText = "font-size: 40px; font-weight: 600; color: var(--accent);";
  card.append(name, link);
  document.body.append(card);
}"""


def repo_url() -> str:
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=demo.ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    # git@github.com:owner/name.git or https://github.com/owner/name.git
    match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", remote)
    if match is None:
        raise RuntimeError(f"origin isn't a GitHub URL: {remote}")
    return f"github.com/{match.group(1)}"


def record(folder: Path) -> list[Shot]:
    with sync_playwright() as p:
        browser = p.chromium.launch(args=demo.CHROMIUM_ARGS)
        page, tiles_loaded, hazard_tiles = demo.new_page(browser, VIEWPORT, SCALE)
        # Before the first page loads, so its animations run on a clock the recorder can step.
        page.clock.install()
        rec = VideoRecorder(page, folder)
        demo.record_upload(rec)
        demo.record_progress(rec)
        demo.wait_for_results(page, tiles_loaded)
        rec.caption("", "figures")
        rec.shot(4)
        cluster = demo.record_clusters(rec)
        panel, row_num = demo.open_focus_asset(rec, cluster)
        demo.record_asset_results(rec, panel)
        demo.record_flood_zone(rec, panel, row_num)
        demo.record_hazard_maps(rec, panel, hazard_tiles, ZOOM_OUT_STEP_SECONDS)
        demo.close_panel(page, panel)
        rec.caption("", "trajectory")
        rec.scroll_to("Change over time", 4)
        demo.record_baseline(rec, show_loss=False)
        rec.caption("", "trust")
        rec.scroll_to("How far to trust these results", 5)
        rec.caption("", "end")
        page.evaluate(END_CARD, ["Asset Risk", repo_url()])
        rec.shot(4)
        browser.close()
    order = list(dict.fromkeys(s.beat for s in rec.shots))
    if order != [b.key for b in BEATS]:
        raise RuntimeError(f"the beats were recorded as {order}, not in the narration's order")
    return rec.shots


# Post


def subtitle_font() -> tuple[str, Path | None]:
    """The font Chromium uses for the GIF caption's system-ui at 600, as fontconfig picks it."""
    try:
        found = subprocess.run(
            ["fc-match", "-f", "%{family[0]}\n%{file}", "system-ui:weight=600"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        return found[0], Path(found[1]).parent
    except (OSError, subprocess.CalledProcessError, IndexError):
        print("warning: no fc-match, so the subtitles use libass's default sans-serif")
        return "sans-serif", None


def render(shots: list[Shot], folder: Path, times: Timeline, total: float, video: Path) -> None:
    """Crop and scale every 30 fps frame from the shots, and burn in the subtitles."""
    beat_shots = [edit.Shot(BEAT_INDEX[s.beat], s.seconds, s.motion) for s in shots]
    starts = edit.schedule(beat_shots, times.beat_starts, total)
    full = edit.Box(0, 0, WIDTH * SCALE, HEIGHT * SCALE)
    crops, crop = [], full
    for index in range(len(BEATS)):
        boxes = [s.box for s in shots if BEAT_INDEX[s.beat] == index and s.box is not None]
        if any(BEAT_INDEX[s.beat] == index for s in shots):
            target = edit.Box(*boxes[-1]) if boxes else None
            crop = edit.crop_box(target, full.w, full.h, MARGIN_PX * SCALE)
        crops.append(crop)
    moves = edit.camera(list(zip(times.beat_starts, crops, strict=True)), times.scene_ends, full)

    font, fonts_dir = subtitle_font()
    ass = folder / "subtitles.ass"
    ass.write_text(edit.ass_document(times.cues, font, WIDTH, HEIGHT, **SUBTITLE))
    ass_filter = "ass=subtitles.ass" + (f":fontsdir={fonts_dir}" if fonts_dir else "")
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error"]
    command += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}"]
    command += ["-r", str(edit.FPS), "-i", "-", "-vf", ass_filter]
    command += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p"]
    encoder = subprocess.Popen([*command, str(video)], stdin=subprocess.PIPE, cwd=folder)
    loaded, image = -1, None
    frames = round(total * edit.FPS)
    for n in range(frames):
        t = n / edit.FPS
        index = edit.shot_at(starts, t)
        if index != loaded:
            image = Image.open(folder / shots[index].path).convert("RGB")
            loaded = index
        box = edit.crop_at(moves, t, full)
        frame = image.resize(
            (WIDTH, HEIGHT),
            Image.Resampling.LANCZOS,
            box=(box.x, box.y, box.x + box.w, box.y + box.h),
        )
        encoder.stdin.write(frame.tobytes())
        if n % (edit.FPS * 10) == 0:
            print(f"Frame {n} of {frames}")
    encoder.stdin.close()
    if encoder.wait() != 0:
        raise RuntimeError("ffmpeg couldn't encode the frames")


def soundtrack(clips: list[Clip], times: Timeline, total: float, path: Path) -> None:
    track = np.zeros(round(total * SAMPLE_RATE), dtype=np.float32)
    for clip, start in zip(clips, times.scene_starts, strict=True):
        audio = read_wav(clip.path)
        at = round(start * SAMPLE_RATE)
        track[at : at + len(audio)] = audio[: len(track) - at]
    write_wav(path, track)


def mux(video: Path, voice: Path, total: float, output: Path) -> None:
    """Normalise the voice to -16 LUFS in two passes, and put it with the video."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    measure = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(voice), "-af", f"loudnorm={LOUDNESS}:print_format=json"]
        + ["-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stderr
    stats = json.loads(measure[measure.rindex("{") : measure.rindex("}") + 1])
    loudnorm = (
        f"loudnorm={LOUDNESS}:measured_I={stats['input_i']}:measured_TP={stats['input_tp']}"
        f":measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}"
        f":offset={stats['target_offset']}:linear=true,aresample=48000"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [ffmpeg, "-y", "-loglevel", "error", "-i", str(video), "-i", str(voice)]
    command += ["-map", "0:v", "-map", "1:a", "-c:v", "copy", "-af", loudnorm]
    command += ["-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart"]
    subprocess.run([*command, str(output)], check=True)


def duration(path: Path) -> float:
    probe = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
    ).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", probe).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def make_video(
    shots: list[Shot], folder: Path, clips: list[Clip], scenes: list[float], output: Path
) -> None:
    times = timeline(clips, scenes)
    total = times.scene_ends[-1]
    video, voice = folder / "video.mp4", folder / "voice.wav"
    render(shots, folder, times, total, video)
    soundtrack(clips, times, total, voice)
    mux(video, voice, total, output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Record the narrated demo video.")
    parser.add_argument("--build", action="store_true", help="rebuild the image first")
    parser.add_argument("--output", type=Path, default=OUTPUT, help="default: %(default)s")
    parser.add_argument("--voice", default=VOICE, help="a Kokoro voice, default: %(default)s")
    parser.add_argument("--frames", type=Path, help="keep the shots and their manifest here")
    parser.add_argument(
        "--from-frames", type=Path, help="make the video from shots kept with --frames"
    )
    parser.add_argument(
        "--voice-only", action="store_true", help="voice and time the scenes, then stop"
    )
    args = parser.parse_args()

    try:
        clips, scenes, speed = narrate(args.voice)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for scene, clip in zip(SCENES, clips, strict=True):
        tail = tail_dbfs(read_wav(clip.path))
        if tail > SILENCE_DBFS:
            print(f"warning: this clip doesn't end in silence ({tail:.0f} dBFS): {scene.text}")
        if not clip.timed:
            print(f"warning: no word timestamps, so its beats are spread evenly: {scene.text}")
    print(f"Voice at speed {speed}, {sum(scenes):.2f} s")
    if args.voice_only:
        for number, (clip, seconds) in enumerate(zip(clips, scenes, strict=True), 1):
            print(f"  {number}. clip {clip.seconds:5.2f} s, scene {seconds:5.2f} s")
        return 0

    def work(folder: Path) -> None:
        manifest = folder / "manifest.json"
        if args.from_frames:
            shots = [Shot(**s) for s in json.loads(manifest.read_text())]
        else:
            shots = record(folder)
            manifest.write_text(json.dumps([asdict(s) for s in shots], indent=1))
        print(f"Shots: {len(shots)}")
        make_video(shots, folder, clips, scenes, args.output)

    def in_folder() -> None:
        if args.from_frames or args.frames:
            folder = args.from_frames or args.frames
            folder.mkdir(parents=True, exist_ok=True)
            work(folder)
        else:
            with tempfile.TemporaryDirectory() as folder:
                work(Path(folder))

    if args.from_frames:
        try:
            in_folder()
        except RuntimeError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    elif demo.with_stack(args.build, in_folder):
        return 1
    length = duration(args.output)
    print(f"Wrote {args.output}: {length:.2f} s, {args.output.stat().st_size / 1024 / 1024:.1f} MB")
    for number, (scene, seconds) in enumerate(zip(SCENES, scenes, strict=True), 1):
        print(f"  {number}. {seconds:5.2f} s  {scene.text[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
