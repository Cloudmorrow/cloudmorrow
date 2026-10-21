"""The timeline kit's sums (quill/timeline.py): what every surface works out the same way."""

from __future__ import annotations

import pytest

from cloudmorrow.quill import timeline as tl
from cloudmorrow.quill.screens import TRACKS

KFS = [{"t": 0, "x": 0, "y": 0, "w": 10, "h": 10}, {"t": 2, "x": 20, "y": 40, "w": 30, "h": 10}]


def piece(start=0.0, length=10.0, offset=0.0, track="V1", **extra) -> dict:
    return {"start": start, "length": length, "offset": offset, "track": track, **extra}


# -- times ------------------------------------------------------------------------------
@pytest.mark.parametrize(("typed", "seconds"), [("12.5", 12.5), ("1:02.5", 62.5), ("1:00:03", 3603), ("4s", 4)])
def test_a_time_is_typed_as_seconds_or_minutes(typed, seconds):
    assert tl.parse_time(typed) == seconds


def test_a_time_that_is_not_one_is_refused():
    with pytest.raises(ValueError):
        tl.parse_time("soon")


def test_a_time_is_said_with_hundredths():
    assert tl.timecode(3.2) == "0:03.20"
    assert tl.timecode(3725) == "1:02:05.00"


def test_a_decimal_from_the_server_is_a_string():
    assert tl.seconds("2.5") == 2.5 and tl.seconds(None, 1.0) == 1.0 and tl.seconds("x") == 0.0


# -- keyframes --------------------------------------------------------------------------
def test_a_box_moves_in_a_straight_line_and_stays_put_outside():
    assert tl.box_at(KFS, 1) == {"x": 10, "y": 20, "w": 20, "h": 10}
    assert tl.box_at(KFS, -1) == {"x": 0, "y": 0, "w": 10, "h": 10}
    assert tl.box_at(KFS, 9)["x"] == 20
    assert tl.box_at([], 1) is None


def test_an_effect_is_on_between_its_keyframes_or_always_with_one():
    assert tl.effect_on(KFS, 1) and not tl.effect_on(KFS, 2.5)
    assert tl.effect_on(KFS[:1], 99)
    assert not tl.effect_on([], 0)


def test_a_keyframe_within_half_a_frame_is_changed_not_added():
    changed = tl.set_keyframe(KFS, 2.01, {"x": 1, "y": 1, "w": 1, "h": 1}, fps=30)
    assert len(changed) == 2 and changed[1] == {"t": 2.0, "x": 1, "y": 1, "w": 1, "h": 1}
    added = tl.set_keyframe(KFS, 1, {"x": 1, "y": 1, "w": 1, "h": 1}, fps=30)
    assert [kf["t"] for kf in added] == [0, 1, 2]


def test_keyframes_come_sorted_and_without_what_is_not_one():
    assert [kf["t"] for kf in tl.keyframes_of([{"t": 3}, "junk", {"t": "1"}])] == [1.0, 3.0]


# -- trimming and splitting -------------------------------------------------------------
def test_trimming_the_start_keeps_the_picture_where_it_was():
    fields, change = tl.trim_start(piece(start=10, length=10, offset=2), 13)
    assert fields == {"start": 13, "offset": 5, "length": 7} and change == 3
    # Not before the source begins: 10 - 2 = 8 at the earliest.
    fields, change = tl.trim_start(piece(start=10, length=10, offset=2), 0)
    assert fields == {"start": 8, "offset": 0, "length": 12} and change == -2
    # Never past its own end.
    fields, _ = tl.trim_start(piece(start=0, length=1), 5)
    assert fields["length"] == tl.SHORTEST


def test_trimming_the_start_rewrites_the_keyframes_by_the_change():
    shifted = tl.shift_keyframes(KFS, 1.5)
    assert [kf["t"] for kf in shifted] == [-1.5, 0.5]


def test_trimming_the_end_stops_at_the_source():
    assert tl.trim_end(piece(start=10, length=5), 12) == {"length": 2}
    assert tl.trim_end(piece(start=10, length=5, offset=1), 30, source_length=8) == {"length": 7}


def test_a_split_plays_the_same_as_the_piece_did():
    first, second = tl.split(piece(start=10, length=6, offset=1, name="beach"), 12)
    assert first == {"length": 2}
    assert second == {"start": 12, "offset": 3, "length": 4, "track": "V1", "name": "beach"}
    assert tl.split(piece(start=10, length=6), 10) is None
    assert tl.split(piece(start=10, length=6), 20) is None


def test_a_split_shares_the_effects_out():
    # Across the cut: both, with the box where it was at the cut.
    before, after = tl.split_keyframes(KFS, 1)
    assert before[-1] == {"t": 1, "x": 10, "y": 20, "w": 20, "h": 10}
    assert after[0] == {"t": 0.0, "x": 10, "y": 20, "w": 20, "h": 10} and after[-1]["t"] == 1
    # Over before the cut, or after it.
    assert tl.split_keyframes(KFS, 5) == (tl.keyframes_of(KFS), None)
    before, after = tl.split_keyframes([{"t": 4, **tl.MIDDLE}, {"t": 6, **tl.MIDDLE}], 3)
    assert before is None and [kf["t"] for kf in after] == [1, 3]
    # One keyframe is the whole piece: both halves.
    before, after = tl.split_keyframes(KFS[:1], 3)
    assert before and after


# -- tracks and pieces ------------------------------------------------------------------
def test_a_higher_video_track_covers_a_lower_one():
    pieces = [piece(track="V1", name="low"), piece(track="V2", start=2, length=2, name="high")]
    assert tl.seen_at(pieces, TRACKS, 3)["name"] == "high"
    assert tl.seen_at(pieces, TRACKS, 5)["name"] == "low"
    assert tl.seen_at(pieces, TRACKS, 11) is None


def test_another_track_is_one_of_the_same_kind():
    assert tl.next_track(TRACKS, "V1", -1) == "V2"
    assert tl.next_track(TRACKS, "V1", 1) is None
    assert tl.next_track(TRACKS, "A1", 1) == "A2"
    assert tl.first_track(TRACKS, "audio")["id"] == "A1"
    # Video 1, under Video 2: counted out from the middle.
    assert tl.first_track(TRACKS, "video")["id"] == "V1"


def test_a_move_snaps_to_an_edge_or_the_playhead():
    others = [piece(start=0, length=5), piece(start=12, length=3)]
    near = tl.edges(others, playhead=8)
    assert tl.snap_start(5.3, 4, near, 0.5) == 5  # its start on the first's end
    assert tl.snap_start(7.8, 4, near, 0.5) == 8  # on the playhead
    assert tl.snap_start(8.2, 4, near, 0.1) == 8.2
    assert tl.snap_start(7.9, 4, near, 0.5) == 8  # its end on 12 would be 8 too


def test_what_a_file_is_by_its_type_or_name():
    assert tl.media_kind("a.MOV") == "video" and tl.media_kind("x", "audio/mpeg") == "audio"
    assert tl.media_kind("notes.txt") is None


def test_a_crop_is_four_numbers_kept_inside_the_picture():
    assert tl.box_from("10 10 80 80") == {"x": 10, "y": 10, "w": 80, "h": 80}
    assert tl.box_from("90, 0, 50, 100")["w"] == 10
    with pytest.raises(ValueError):
        tl.box_from("10 10")
    assert tl.crop_of({}) == tl.WHOLE


def test_pieces_fall_on_a_row_to_scale():
    rows = tl.spans([piece(start=0, length=2), piece(start=5, length=1), piece(start=100, length=1)], 0, 0.5, 20)
    assert [(a, b) for a, b, _ in rows] == [(0, 4), (10, 12)]
