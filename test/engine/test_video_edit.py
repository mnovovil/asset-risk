"""The pure parts of script/record_video.py: no Kokoro, browser or network."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "script" / "video_edit.py"
spec = importlib.util.spec_from_file_location("video_edit", SCRIPT)
video_edit = importlib.util.module_from_spec(spec)
sys.modules["video_edit"] = video_edit  # dataclasses look their module up by name
spec.loader.exec_module(video_edit)

Box, Shot, Word = video_edit.Box, video_edit.Shot, video_edit.Word
W, H = 3840, 2160
FULL = Box(0, 0, W, H)


# Fitting the scenes to 60 s


def test_scenes_get_the_full_padding_when_they_fit():
    scenes = video_edit.fit_scenes([6.2] * 9)  # 55.8 s of voice
    assert scenes == pytest.approx([6.6] * 9)


def test_the_padding_shrinks_before_giving_up():
    clips = [6.4] * 9  # 57.6 s, leaving 0.267 s each
    scenes = video_edit.fit_scenes(clips)
    assert scenes == pytest.approx([6.4 + 2.4 / 9] * 9)
    assert sum(scenes) == pytest.approx(60)


def test_scenes_that_dont_fit_even_at_the_shortest_padding_are_refused():
    assert video_edit.fit_scenes([6.5] * 9) is None  # 58.5 s leaves 0.167 s each
    assert video_edit.fit_scenes([60 / 9 - 0.2] * 9) == pytest.approx([60 / 9] * 9)


def test_a_short_video_holds_its_end_card_to_reach_the_minimum():
    scenes = video_edit.fit_scenes([5.0] * 9)
    assert scenes[:-1] == pytest.approx([5.4] * 8)
    assert sum(scenes) == pytest.approx(58)


def test_clips_are_never_cut():
    clips = [5.1, 7.3, 6.2, 6.0, 7.9, 6.6, 6.8, 5.0, 7.0]
    scenes = video_edit.fit_scenes(clips)
    assert all(s >= c + video_edit.MIN_PAD - 1e-9 for s, c in zip(scenes, clips, strict=True))


def test_speeds_rise_in_steps_to_1_1():
    speeds = video_edit.SPEEDS
    assert speeds[0] == 1.0 and speeds[-1] == pytest.approx(1.1)
    assert list(speeds) == sorted(speeds)


# Easing


def test_easing_starts_and_ends_at_rest_and_is_symmetric():
    ease = video_edit.ease_in_out
    assert ease(0) == 0 and ease(1) == pytest.approx(1)
    assert ease(-1) == 0 and ease(2) == pytest.approx(1)
    assert ease(0.5) == pytest.approx(0.5)
    for t in (0.1, 0.25, 0.4):
        assert ease(t) + ease(1 - t) == pytest.approx(1)
    assert ease(0.05) < 0.05  # slow out of the start
    values = [ease(i / 20) for i in range(21)]
    assert values == sorted(values)


# Crops


def aspect(box):
    return box.w / box.h


def test_a_crop_has_the_frames_aspect():
    for target in (Box(100, 100, 300, 900), Box(1000, 500, 1800, 200), Box(10, 10, 10, 10)):
        crop = video_edit.crop_box(target, W, H, margin=40)
        assert aspect(crop) == pytest.approx(16 / 9)


def test_a_crop_zooms_in_at_most_2_2x():
    crop = video_edit.crop_box(Box(1900, 1000, 20, 20), W, H, margin=10)
    assert crop.w == pytest.approx(W / 2.2)
    assert W / crop.w <= 2.2 + 1e-9


def test_a_crop_contains_the_target_and_its_margin():
    target = Box(1200, 700, 1600, 500)
    crop = video_edit.crop_box(target, W, H, margin=50)
    assert crop.x <= target.x - 50 and crop.x + crop.w >= target.x + target.w + 50
    assert crop.y <= target.y - 50 and crop.y + crop.h >= target.y + target.h + 50


@pytest.mark.parametrize(
    "target",
    [
        Box(0, 0, 50, 50),
        Box(W - 50, 0, 50, 50),
        Box(0, H - 50, 50, 50),
        Box(W - 50, H - 50, 50, 50),
    ],
)
def test_a_crop_stays_inside_the_frame_at_every_corner(target):
    crop = video_edit.crop_box(target, W, H, margin=40)
    assert crop.x >= 0 and crop.y >= 0
    assert crop.x + crop.w <= W + 1e-9 and crop.y + crop.h <= H + 1e-9


def test_a_target_past_the_frames_edge_is_clamped():
    crop = video_edit.crop_box(Box(-300, 1800, 600, 900), W, H, margin=40)
    assert crop.x == 0 and crop.y + crop.h == pytest.approx(H)


def test_a_target_as_big_as_the_frame_shows_all_of_it():
    assert video_edit.crop_box(Box(-10, 100, W + 50, 500), W, H, margin=40) == FULL
    assert video_edit.crop_box(Box(100, 100, 500, H), W, H, margin=40) == FULL
    assert video_edit.crop_box(None, W, H, margin=40) == FULL


def test_crops_between_two_boxes_are_repeatable_and_dont_jump():
    a, b = FULL, video_edit.crop_box(Box(2000, 1200, 400, 300), W, H, margin=40)
    steps = [video_edit.lerp_box(a, b, video_edit.ease_in_out(i / 18)) for i in range(19)]
    assert steps[0] == a and steps[-1] == b
    assert steps == [video_edit.lerp_box(a, b, video_edit.ease_in_out(i / 18)) for i in range(19)]
    widths = [s.w for s in steps]
    assert widths == sorted(widths, reverse=True)
    for box in steps:
        assert aspect(box) == pytest.approx(16 / 9, rel=1e-4)


def test_the_union_of_two_boxes_covers_both():
    assert Box(10, 20, 30, 40).union(Box(0, 50, 5, 30)) == Box(0, 20, 40, 60)


# Camera


def test_the_camera_eases_in_on_each_beat_and_out_at_the_end_of_a_scene():
    near = video_edit.crop_box(Box(400, 400, 400, 300), W, H, margin=0)
    moves = video_edit.camera([(0.0, near), (5.0, FULL)], scene_ends=[5.0, 10.0], full=FULL)
    crop_at = video_edit.crop_at
    assert crop_at(moves, 0.0, FULL) == FULL
    assert crop_at(moves, 0.3, FULL).w == pytest.approx((W + near.w) / 2, rel=1e-3)
    assert crop_at(moves, 2.0, FULL) == near
    assert FULL.w > crop_at(moves, 4.7, FULL).w > near.w  # easing out before the scene ends
    assert crop_at(moves, 5.0, FULL) == FULL


def test_a_beat_shorter_than_the_ease_reaches_its_crop_before_the_next():
    a = video_edit.crop_box(Box(400, 400, 400, 300), W, H, margin=0)
    b = video_edit.crop_box(Box(2400, 1400, 400, 300), W, H, margin=0)
    moves = video_edit.camera([(0.0, a), (1.0, b), (1.3, a)], scene_ends=[8.0], full=FULL)
    assert video_edit.crop_at(moves, 1.3, FULL) == b
    # Each move starts where the camera was, so the crop never jumps.
    for t in (0.999, 1.0, 1.001, 1.299, 1.3, 1.301):
        before = video_edit.crop_at(moves, t - 1 / 30, FULL)
        assert abs(video_edit.crop_at(moves, t, FULL).x - before.x) < W / 10


# Shot timing


def test_motion_frames_keep_their_length_and_holds_fill_the_beat():
    shots = [Shot(0, 1 / 30, True)] * 3 + [Shot(0, 4, False), Shot(1, 2, False), Shot(1, 1, False)]
    starts = video_edit.schedule(shots, beat_starts=[0.0, 3.0], total=6.0)
    assert starts[:4] == pytest.approx([0, 1 / 30, 2 / 30, 0.1])
    assert starts[4:] == pytest.approx([3.0, 5.0])  # 2 s and 1 s of declared hold over 3 s


def test_motion_that_would_crowd_out_the_hold_is_sped_up():
    shots = [Shot(0, 0.15, True)] * 20 + [Shot(0, 5, False)]  # 3 s of motion in a 2 s beat
    starts = video_edit.schedule(shots, beat_starts=[0.0], total=2.0)
    assert starts[-1] == pytest.approx(2.0 * video_edit.MAX_MOTION_SHARE)


def test_a_beat_without_shots_keeps_the_last_one_on_screen():
    shots = [Shot(0, 1, False), Shot(2, 1, False)]
    starts = video_edit.schedule(shots, beat_starts=[0.0, 1.0, 2.0], total=3.0)
    assert starts == [0.0, 2.0]
    assert video_edit.shot_at(starts, 1.5) == 0
    assert video_edit.shot_at(starts, 2.0) == 1


def test_shots_out_of_beat_order_are_refused():
    with pytest.raises(ValueError):
        video_edit.schedule([Shot(1, 1, False), Shot(0, 1, False)], [0.0, 1.0], 2.0)


# Subtitles

# Kokoro's timing of scene 7's narration, as it gives it: punctuation is a token of its own.
SCENE_7 = [
    ("Explore", 0.275, 0.7), ("hazard", 0.7, 1.05), ("maps", 1.05, 1.375),
    ("around", 1.375, 1.7), ("it", 1.7, 2.125), (":", 2.125, 2.2625),
    ("river", 2.2625, 2.6), ("and", 2.6, 2.725), ("coastal", 2.725, 3.1875),
    ("flood", 3.1875, 3.725), (",", 3.725, 3.8625), ("wildfire", 3.8625, 4.675),
    (",", 4.675, 4.7875), ("cyclone", 4.7875, 5.3), ("wind", 5.3, 5.65), ("and", 5.65, 5.775),
    ("large", 5.775, 6.075), ("hail", 6.075, 6.65), (".", 6.65, 6.8),
]  # fmt: skip
WORDS_7 = [Word(*w) for w in SCENE_7]


def test_subtitles_break_into_short_lines_at_punctuation():
    cues = video_edit.subtitle_cues(WORDS_7, offset=30.0, scene_end=37.3)
    assert [c.text for c in cues] == [
        "Explore hazard maps around it:",
        "river and coastal flood,",
        "wildfire, cyclone wind and large hail.",
    ]
    assert all(len(c.text) <= 42 for c in cues)


def test_subtitles_are_timed_from_the_words_and_dont_overlap():
    cues = video_edit.subtitle_cues(WORDS_7, offset=30.0, scene_end=37.0)
    assert cues[0].start == pytest.approx(30.275)
    assert cues[1].start == pytest.approx(32.2625, abs=1e-3)
    for a, b in zip(cues, cues[1:], strict=False):
        assert a.end <= b.start and a.start < a.end
    assert cues[-1].end == pytest.approx(37.0)  # 36.8 + 0.5 lingers, cut at the scene's end


def test_a_long_line_breaks_before_the_word_that_overflows():
    words = video_edit.even_words("one two three four five six seven eight nine ten eleven", 5)
    cues = video_edit.subtitle_cues(words, 0, 5, max_chars=20)
    assert all(len(c.text) <= 20 for c in cues)
    assert (
        " ".join(c.text for c in cues) == "one two three four five six seven eight nine ten eleven"
    )


def test_even_words_split_a_clip_without_timestamps():
    words = video_edit.even_words("Open one to see it.", 4.0)
    assert [w.text for w in words] == ["Open", "one", "to", "see", "it."]
    assert words[0].start == 0 and words[-1].end == pytest.approx(4.0)
    for a, b in zip(words, words[1:], strict=False):
        assert a.end == pytest.approx(b.start)


def test_a_beat_finds_its_word():
    assert video_edit.find_word(WORDS_7, "coastal") == 2.725
    assert video_edit.find_word(WORDS_7, "and", occurrence=2) == 5.65
    with pytest.raises(ValueError):
        video_edit.find_word(WORDS_7, "drought")


def test_ass_times_and_escaping():
    assert video_edit.ass_time(0) == "0:00:00.00"
    assert video_edit.ass_time(61.236) == "0:01:01.24"
    assert video_edit.ass_time(3600.5) == "1:00:00.50"
    assert video_edit.ass_escape(r"a {b} \c") == r"a \{b\} \\c"
    assert video_edit.ass_colour("#1f2933") == "&H0033291F"


def test_the_ass_document_has_the_captions_style_and_one_event_per_cue():
    cues = video_edit.subtitle_cues(WORDS_7, 0, 7.3)
    doc = video_edit.ass_document(cues, font="DejaVu Sans")
    assert "PlayResX: 1920" in doc and "PlayResY: 1080" in doc
    style = next(line for line in doc.splitlines() if line.startswith("Style:"))
    fields = style.removeprefix("Style: ").split(",")
    assert fields[1] == "DejaVu Sans" and fields[3] == "&H00FFFFFF" and fields[5] == "&H0033291F"
    assert fields[7] == "-1" and fields[15] == "3"  # bold, in an opaque box
    assert doc.count("Dialogue:") == len(cues)
