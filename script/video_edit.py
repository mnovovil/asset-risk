"""The pure parts of record_video.py: scene timing, zoom crops, easing and subtitles.

Standard library only, so the unit tests import it without the video script's dependencies.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from dataclasses import dataclass

FPS = 30
# The video's length, in seconds.
MAX_TOTAL = 60.0
MIN_TOTAL = 58.0
# Silence after each scene's clip, shortened to MIN_PAD before the voice is sped up.
PAD = 0.4
MIN_PAD = 0.2
# Kokoro's speed, tried in turn until the scenes fit in MAX_TOTAL.
SPEEDS = (1.0, 1.025, 1.05, 1.075, 1.1)
EASE_SECONDS = 0.6
MAX_ZOOM = 2.2
# The share of a beat that motion frames may take, so the settled view is seen.
MAX_MOTION_SHARE = 0.8


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float

    def union(self, other: Box) -> Box:
        x0, y0 = min(self.x, other.x), min(self.y, other.y)
        x1 = max(self.x + self.w, other.x + other.w)
        y1 = max(self.y + self.h, other.y + other.h)
        return Box(x0, y0, x1 - x0, y1 - y0)


def fit_scenes(
    clips: Sequence[float],
    pad: float = PAD,
    min_pad: float = MIN_PAD,
    max_total: float = MAX_TOTAL,
    min_total: float = MIN_TOTAL,
) -> list[float] | None:
    """Each scene's length: its clip plus the padding, or None if they don't fit in max_total.

    The padding is shortened as far as min_pad before giving up. A clip is never cut. If the scenes
    come to less than min_total, the last scene, the end card, is held for longer.
    """
    room = (max_total - sum(clips)) / len(clips)
    pad = min(pad, room)
    if pad < min_pad - 1e-9:
        return None
    scenes = [clip + pad for clip in clips]
    scenes[-1] += max(0.0, min_total - sum(scenes))
    return scenes


def ease_in_out(t: float) -> float:
    """Cosine ease from 0 to 1: slow at both ends, symmetric about t = 0.5."""
    t = min(max(t, 0.0), 1.0)
    return (1 - math.cos(math.pi * t)) / 2


def crop_box(
    target: Box | None,
    frame_w: float,
    frame_h: float,
    margin: float,
    max_zoom: float = MAX_ZOOM,
) -> Box:
    """The part of the frame to show for a target: the target plus margin, at the frame's aspect.

    It zooms in by at most max_zoom, is centred on the target where it can be, and never goes past
    the frame's edges. With no target, or one as big as the frame, it's the whole frame.
    """
    full = Box(0, 0, frame_w, frame_h)
    if target is None:
        return full
    aspect = frame_w / frame_h
    w = max(target.w + 2 * margin, (target.h + 2 * margin) * aspect, frame_w / max_zoom)
    if w >= frame_w:
        return full
    h = w / aspect
    cx, cy = target.x + target.w / 2, target.y + target.h / 2
    x = min(max(cx - w / 2, 0.0), frame_w - w)
    y = min(max(cy - h / 2, 0.0), frame_h - h)
    return rounded(Box(x, y, w, h))


def rounded(box: Box) -> Box:
    """Every crop is rounded the same way, to 3 decimals, so equal crops compare equal."""
    return Box(round(box.x, 3), round(box.y, 3), round(box.w, 3), round(box.h, 3))


def lerp_box(a: Box, b: Box, t: float) -> Box:
    """Between two crops, kept as floats: the frame is resampled from them, so nothing is rounded
    to whole pixels and nothing shakes. The 3-decimal rounding only makes the result repeatable."""

    def mix(u: float, v: float) -> float:
        return u + (v - u) * t

    return rounded(Box(mix(a.x, b.x), mix(a.y, b.y), mix(a.w, b.w), mix(a.h, b.h)))


@dataclass(frozen=True)
class Shot:
    beat: int  # index into the beats
    seconds: float  # as declared when it was taken
    motion: bool  # a step of a scroll or an animation, shown for its own length


def schedule(shots: Sequence[Shot], beat_starts: Sequence[float], total: float) -> list[float]:
    """When each shot starts, so each beat's shots fill the time from its start to the next one's.

    Motion frames keep their declared length, unless together they'd take more than
    MAX_MOTION_SHARE of a beat that also has a settled view, when they're sped up to fit. The
    settled views share what's left in proportion to their declared lengths. A beat with no shots
    of its own keeps showing the previous beat's last shot.
    """
    beats = [s.beat for s in shots]
    if beats != sorted(beats):
        raise ValueError("shots must be in the order of their beats")
    ends = [*beat_starts[1:], total]
    starts: list[float] = []
    for beat, start in enumerate(beat_starts):
        own = [s for s in shots if s.beat == beat]
        if not own:
            continue
        length = ends[beat] - start
        motion = sum(s.seconds for s in own if s.motion)
        held = sum(s.seconds for s in own if not s.motion)
        limit = length * (MAX_MOTION_SHARE if held else 1.0)
        motion_scale = min(1.0, limit / motion) if motion else 1.0
        rest = length - motion * motion_scale
        t = start
        for shot in own:
            starts.append(t)
            if shot.motion:
                t += shot.seconds * motion_scale
            elif held:
                t += rest * shot.seconds / held
    return starts


def shot_at(starts: Sequence[float], t: float) -> int:
    """The shot on screen at time t."""
    return max(0, bisect.bisect_right(starts, t) - 1)


@dataclass(frozen=True)
class Move:
    start: float
    end: float
    origin: Box
    target: Box


def camera(
    beats: Sequence[tuple[float, Box]],
    end: float,
    full: Box,
    ease: float = EASE_SECONDS,
) -> list[Move]:
    """The camera's moves: it eases to a beat's crop only when the crop changes, and otherwise
    stays still. beats are (start, crop) and the last one lasts until end.

    Going back to the whole frame finishes as the beat starts, so a cut to a new view happens at
    full frame. Any other move starts with its beat, once the new view is on screen.
    """
    moves: list[Move] = []
    current, free = full, 0.0  # where the camera is, and when its last move ends
    stops = [*[b[0] for b in beats[1:]], end]
    for (start, crop), stop in zip(beats, stops, strict=True):
        if crop == current:
            continue
        if crop == full:
            length = max(0.0, min(ease, start - free))
            begin = start - length
        else:
            begin = max(start, free)
            length = max(0.0, min(ease, stop - begin))
        origin = crop_at(moves, begin, full)
        moves.append(Move(begin, begin + length, origin, crop))
        current, free = crop, begin + length
    return moves


def crop_at(moves: Sequence[Move], t: float, full: Box) -> Box:
    box = full
    for move in moves:
        if t < move.start:
            break
        if t >= move.end or move.end == move.start:
            box = move.target
        else:
            box = lerp_box(
                move.origin, move.target, ease_in_out((t - move.start) / (move.end - move.start))
            )
    return box


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def join_punctuation(words: Sequence[Word]) -> list[Word]:
    """Attach punctuation tokens, which Kokoro times on their own, to the word before them."""
    joined: list[Word] = []
    for word in words:
        if joined and not any(c.isalnum() for c in word.text):
            last = joined[-1]
            joined[-1] = Word(last.text + word.text, last.start, word.end)
        else:
            joined.append(word)
    return joined


def even_words(text: str, duration: float) -> list[Word]:
    """Word times for a clip without timestamps: spread over it in proportion to their length."""
    words = text.split()
    total = sum(len(w) + 1 for w in words)
    t, timed = 0.0, []
    for word in words:
        length = duration * (len(word) + 1) / total
        timed.append(Word(word, t, t + length))
        t += length
    return timed


def find_word(words: Sequence[Word], text: str, occurrence: int = 1) -> float:
    """When a word starts: the beat that matches it starts there."""
    seen = 0
    for word in words:
        if word.text.strip(".,:;!?").lower() == text.lower():
            seen += 1
            if seen == occurrence:
                return word.start
    raise ValueError(f"the narration has no {text!r} (occurrence {occurrence})")


def subtitle_cues(
    words: Sequence[Word],
    offset: float,
    scene_end: float,
    max_chars: int = 42,
    min_clause: int = 20,
    linger: float = 0.5,
) -> list[Cue]:
    """Short subtitle lines for one scene, timed from its words.

    A line breaks after a full stop or colon, after a comma once it has min_clause characters, and
    before a word that would take it past max_chars. Each line shows from its first word until the
    next line starts, and the last one lingers after its last word, but not past the scene's end.
    """
    lines: list[list[Word]] = [[]]
    for word in join_punctuation(words):
        current = lines[-1]
        text = " ".join(w.text for w in [*current, word])
        if current and len(text) > max_chars:
            lines.append([word])
        else:
            current.append(word)
        line = " ".join(w.text for w in lines[-1])
        if word.text[-1] in ".:" or (word.text[-1] == "," and len(line) >= min_clause):
            lines.append([])
    lines = [line for line in lines if line]
    cues = []
    for index, line in enumerate(lines):
        start = offset + line[0].start
        if index + 1 < len(lines):
            end = offset + lines[index + 1][0].start
        else:
            end = min(offset + line[-1].end + linger, scene_end)
        cues.append(Cue(round(start, 3), round(end, 3), " ".join(w.text for w in line)))
    return cues


def ass_time(seconds: float) -> str:
    """H:MM:SS.cc, as ASS writes times."""
    centiseconds = round(seconds * 100)
    hours, rest = divmod(centiseconds, 360_000)
    minutes, rest = divmod(rest, 6000)
    return f"{hours}:{minutes:02d}:{rest // 100:02d}.{rest % 100:02d}"


def ass_escape(text: str) -> str:
    """ASS reads braces as override tags and a backslash as an escape."""
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", " ")


def ass_colour(hex_rgb: str) -> str:
    """#rrggbb as ASS's &HAABBGGRR, opaque."""
    r, g, b = hex_rgb[1:3], hex_rgb[3:5], hex_rgb[5:7]
    return f"&H00{b}{g}{r}".upper()


def ass_document(
    cues: Sequence[Cue],
    font: str,
    width: int = 1920,
    height: int = 1080,
    size: int = 34,
    background: str = "#1f2933",
    colour: str = "#ffffff",
    padding: int = 14,
    margin_bottom: int = 44,
) -> str:
    """Subtitles in a bottom bar like the GIF's caption: white bold text in a #1f2933 box."""
    box = ass_colour(background)
    style = ",".join(
        [
            "Style: Caption",
            font,
            str(size),
            ass_colour(colour),
            ass_colour(colour),
            box,
            box,
            "-1,0,0,0,100,100,0,0",  # bold, not italic, underlined or struck out, no scaling
            "3",  # an opaque box behind each line, with the outline as its padding
            str(padding),
            "0",  # no shadow
            "2",  # bottom centre
            "40,40",
            str(margin_bottom),
            "1",
        ]
    )
    events = [
        f"Dialogue: 0,{ass_time(c.start)},{ass_time(c.end)},Caption,,0,0,0,,{ass_escape(c.text)}"
        for c in cues
    ]
    return "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
            "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            style,
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            *events,
            "",
        ]
    )
