"""The timeline kit's arithmetic: what every surface works out the same way.

A timeline (docs/TIMELINE.md) is pieces on tracks — `start`, `offset` and
`length` in seconds — and effects on pieces whose keyframes count `t` from
the piece's start. The terminal and the command line work on those numbers
with what is here, and the web app's kit_timeline.js does the same sums in
JavaScript: a change to a rule here is a change to it there.

Nothing here talks to a server or draws anything. A piece is its fields (a
dict with `start`, `offset`, `length`, `track`, …), a keyframe is
`{"t", "x", "y", "w", "h"}`, and every function answers with new values
rather than changing what it was given.

The rules:

- *A box between keyframes* moves and resizes in a straight line; before the
  first and after the last it stays where that one says (`box_at`). An effect
  is on from its first keyframe to its last, and through the whole piece
  when it has one (`effect_on`).
- *Setting a keyframe* replaces one within half a frame of the time, or
  makes one (`set_keyframe`).
- *Trimming the start* moves `start` and `offset` together, so the picture
  stays where it was on the timeline, and every keyframe's `t` moves back by
  the same amount (`trim_start`, `shift_keyframes`). Keyframes that fall
  before the new start are kept: trimming back out brings them back.
- *Splitting* at a time inside a piece makes two that play the same as the
  one did (`split`); each effect goes to the half it is on, or to both,
  with a keyframe made where it is cut (`split_keyframes`).
- *Moving* snaps the start or the end to another piece's edge, or to the
  playhead, when one is that close (`snap_start`).
- A box — a keyframe's, the crop — is in percent of the project's picture
  (`width` × `height`), each piece fitted into it letterboxed; the crop is
  taken last.
- A piece is never shorter than `SHORTEST`, nor begins before 0, nor reads
  from before its source's beginning.
"""

from __future__ import annotations

import re

# The shortest a piece can be cut to, in seconds: a frame or so.
SHORTEST = 0.04
# The frames per second a project is stepped at before it has its own.
FPS = 30.0
# The box an effect starts with: the middle of the picture, in percent.
MIDDLE = {"x": 35.0, "y": 25.0, "w": 30.0, "h": 40.0}
# The crop that keeps all of it.
WHOLE = {"x": 0.0, "y": 0.0, "w": 100.0, "h": 100.0}
BOX = ("x", "y", "w", "h")

# What a file is, by its extension when its type does not say.
VIDEO_EXT = frozenset({"mp4", "m4v", "mov", "mkv", "webm", "avi", "wmv", "mpg", "mpeg", "3gp"})
AUDIO_EXT = frozenset({"mp3", "m4a", "aac", "flac", "wav", "ogg", "opus", "aiff", "wma"})


def seconds(value: object, default: float = 0.0) -> float:
    """A stored number as seconds: a decimal arrives as a string, a blank as *default*."""
    if value is None or value == "":
        return default
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def parse_time(text: str) -> float:
    """What a person types for a time: `12.5`, `1:02.5`, `1:02:03`. ValueError otherwise."""
    text = text.strip().rstrip("s")
    if not re.fullmatch(r"\d+(:\d+){0,2}(\.\d*)?|\.\d+", text):
        raise ValueError(f"{text!r} is not a time: give seconds, or m:ss")
    total = 0.0
    for part in text.split(":"):
        total = total * 60 + float(part)
    return total


def timecode(t: float) -> str:
    """A time as the timeline says it: `0:03.20`, `1:02:03.00` past an hour."""
    t = max(0.0, t)
    hours, rest = divmod(t, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{int(hours)}:{int(minutes):02d}:{secs:05.2f}"
    return f"{int(minutes)}:{secs:05.2f}"


def fps_of(project_fields: dict) -> float:
    fps = seconds(project_fields.get("fps"))
    return fps if fps > 0 else FPS


# -- material -------------------------------------------------------------------------
def media_kind(name: str, mime: str = "") -> str | None:
    """ "video", "audio", or None for a file that is neither."""
    for kind in ("video", "audio"):
        if mime.startswith(kind + "/"):
            return kind
    ext = name.rsplit(".", 1)[1].lower() if "." in name else ""
    return "video" if ext in VIDEO_EXT else "audio" if ext in AUDIO_EXT else None


# -- tracks ---------------------------------------------------------------------------
def first_track(tracks: list[dict], kind: str) -> dict | None:
    """Where Add puts a file: the first track of its kind, counted out from the middle.

    Video tracks are listed top down (V2 over V1) and sound tracks after them
    (A1 then A2), so Video 1 is the last video track in the list and Audio 1
    the first audio one: the track nearest the line between the two.
    """
    same = [t for t in tracks if t.get("kind") == kind]
    if not same:
        return None
    return same[-1] if kind == "video" else same[0]


def kind_of_track(tracks: list[dict], track_id: str) -> str:
    return next((str(t.get("kind")) for t in tracks if t.get("id") == track_id), "video")


def next_track(tracks: list[dict], track_id: str, step: int) -> str | None:
    """The next track up (-1) or down (+1) of the same kind as *track_id*, or None at the end."""
    kind = kind_of_track(tracks, track_id)
    same = [t["id"] for t in tracks if t.get("kind") == kind]
    if track_id not in same:
        return same[0] if same else None
    index = same.index(track_id) + step
    return same[index] if 0 <= index < len(same) else None


# -- pieces ---------------------------------------------------------------------------
def end_of(piece: dict) -> float:
    return seconds(piece.get("start")) + seconds(piece.get("length"))


def duration(pieces: list[dict]) -> float:
    """How long the whole cut is: to the end of the last piece."""
    return max((end_of(p) for p in pieces), default=0.0)


def on_track(pieces: list[dict], track_id: str) -> list[dict]:
    return sorted((p for p in pieces if p.get("track") == track_id), key=lambda p: seconds(p.get("start")))


def piece_at(pieces: list[dict], track_id: str, t: float) -> dict | None:
    """The piece on *track_id* playing at *t* (the later one where two touch)."""
    found = None
    for piece in on_track(pieces, track_id):
        if seconds(piece.get("start")) <= t < end_of(piece):
            found = piece
    return found


def pieces_at(pieces: list[dict], tracks: list[dict], t: float) -> list[tuple[dict, dict]]:
    """(track, piece) for every track with a piece at *t*, top to bottom."""
    found = []
    for track in tracks:
        piece = piece_at(pieces, track["id"], t)
        if piece is not None:
            found.append((track, piece))
    return found


def seen_at(pieces: list[dict], tracks: list[dict], t: float) -> dict | None:
    """The piece whose picture shows at *t*: the highest video track's."""
    for track, piece in pieces_at(pieces, tracks, t):
        if track.get("kind") == "video":
            return piece
    return None


def end_after(pieces: list[dict], track_id: str) -> float:
    """Where a piece added to the end of a track begins."""
    return max((end_of(p) for p in pieces if p.get("track") == track_id), default=0.0)


def edges(pieces: list[dict], *, leave: dict | None = None, playhead: float | None = None) -> list[float]:
    """Where a moved piece may snap: 0, every other piece's start and end, and the playhead."""
    found = {0.0}
    for piece in pieces:
        if piece is leave:
            continue
        found.add(round(seconds(piece.get("start")), 6))
        found.add(round(end_of(piece), 6))
    if playhead is not None:
        found.add(round(playhead, 6))
    return sorted(found)


def snap_start(start: float, length: float, at: list[float], within: float) -> float:
    """*start*, moved to put the piece's start or end on the nearest of *at* within *within* seconds."""
    best, gap = start, within
    for edge in at:
        for candidate in (edge, edge - length):
            moved = abs(candidate - start)
            if moved <= gap and candidate >= 0:
                best, gap = candidate, moved
    return max(0.0, best)


def moved(start: float) -> dict:
    """The fields that put a piece at *start* (never before 0)."""
    return {"start": round(max(0.0, start), 6)}


def trim_start(piece: dict, at: float) -> tuple[dict, float]:
    """The fields that begin *piece* at *at*, and how far its `offset` moved.

    The picture stays put on the timeline: start and offset move together,
    the length takes up the difference. It cannot begin before its source
    does, before 0, or less than `SHORTEST` before its end.
    """
    start, offset, end = seconds(piece.get("start")), seconds(piece.get("offset")), end_of(piece)
    at = max(at, start - offset, 0.0)
    at = min(at, end - SHORTEST)
    change = at - start
    fields = {
        "start": round(at, 6),
        "offset": round(offset + change, 6),
        "length": round(end - at, 6),
    }
    return fields, round(change, 6)


def trim_end(piece: dict, at: float, source_length: float | None = None) -> dict:
    """The fields that end *piece* at *at*: not before `SHORTEST` past its start,
    nor past the end of its source when that is known."""
    start, offset = seconds(piece.get("start")), seconds(piece.get("offset"))
    end = max(at, start + SHORTEST)
    if source_length:
        end = min(end, start + source_length - offset)
    return {"length": round(max(end - start, SHORTEST), 6)}


def split(piece: dict, at: float) -> tuple[dict, dict] | None:
    """*piece* cut at *at*: the fields the first half keeps, and the second half's whole fields.

    None when *at* is not far enough inside it to leave two pieces.
    """
    start, offset, end = seconds(piece.get("start")), seconds(piece.get("offset")), end_of(piece)
    if not start + SHORTEST <= at <= end - SHORTEST:
        return None
    first = {"length": round(at - start, 6)}
    second = {
        **{k: v for k, v in piece.items() if k not in ("id",)},
        "start": round(at, 6),
        "offset": round(offset + at - start, 6),
        "length": round(end - at, 6),
    }
    return first, second


# -- keyframes ------------------------------------------------------------------------
def keyframes_of(value: object) -> list[dict]:
    """An effect's keyframes, sorted, every number a float; whatever is not one left out."""
    found = []
    for kf in value if isinstance(value, list) else []:
        if isinstance(kf, dict) and "t" in kf:
            found.append({"t": seconds(kf.get("t")), **{k: seconds(kf.get(k)) for k in BOX}})
    return sorted(found, key=lambda kf: kf["t"])


def box_at(keyframes: list[dict], t: float) -> dict | None:
    """The box at *t* (from the piece's start), in a straight line between keyframes.

    Before the first and after the last it is where that one says; None with none.
    """
    kfs = keyframes_of(keyframes)
    if not kfs:
        return None
    if t <= kfs[0]["t"]:
        return {k: kfs[0][k] for k in BOX}
    for a, b in zip(kfs, kfs[1:], strict=False):
        if t <= b["t"]:
            span = b["t"] - a["t"]
            part = (t - a["t"]) / span if span > 0 else 1.0
            return {k: round(a[k] + (b[k] - a[k]) * part, 4) for k in BOX}
    return {k: kfs[-1][k] for k in BOX}


def effect_on(keyframes: list[dict], t: float) -> bool:
    """Whether an effect is on at *t*: between its first and last keyframes, always with one."""
    kfs = keyframes_of(keyframes)
    if len(kfs) == 1:
        return True
    return bool(kfs) and kfs[0]["t"] <= t <= kfs[-1]["t"]


def set_keyframe(keyframes: list[dict], t: float, box: dict, fps: float = FPS) -> list[dict]:
    """The keyframes with the box at *t*: the one within half a frame changed, or a new one."""
    kfs = keyframes_of(keyframes)
    half = 0.5 / (fps if fps > 0 else FPS)
    near = [kf for kf in kfs if abs(kf["t"] - t) <= half]
    keep = [kf for kf in kfs if kf not in near]
    at = near[0]["t"] if near else round(t, 4)
    made = {"t": at, **{k: round(min(max(seconds(box.get(k)), 0.0), 100.0), 4) for k in BOX}}
    return sorted([*keep, made], key=lambda kf: kf["t"])


def shift_keyframes(keyframes: list[dict], by: float) -> list[dict]:
    """Every `t` moved back by *by*: what a piece's start moving *by* into its source does."""
    return [{**kf, "t": round(kf["t"] - by, 4)} for kf in keyframes_of(keyframes)]


def split_keyframes(keyframes: list[dict], cut: float) -> tuple[list[dict] | None, list[dict] | None]:
    """An effect's keyframes for each half of a piece cut *cut* seconds in; None where it is not on.

    One keyframe is on through the whole piece, so it goes to both. An effect
    that ends before the cut stays with the first half, one that starts after
    it goes to the second (its times counted from there); one across the cut
    goes to both, with a keyframe on each side of the cut where the box was.
    """
    kfs = keyframes_of(keyframes)
    if not kfs:
        return [], None
    if len(kfs) == 1:
        return kfs, [{**kfs[0], "t": round(max(kfs[0]["t"] - cut, 0.0), 4)}]
    if kfs[-1]["t"] <= cut:
        return kfs, None
    if kfs[0]["t"] >= cut:
        return None, [{**kf, "t": round(kf["t"] - cut, 4)} for kf in kfs]
    there = box_at(kfs, cut) or MIDDLE
    first = [kf for kf in kfs if kf["t"] < cut] + [{"t": round(cut, 4), **there}]
    second = [{"t": 0.0, **there}] + [{**kf, "t": round(kf["t"] - cut, 4)} for kf in kfs if kf["t"] > cut]
    return first, second


# -- the crop -------------------------------------------------------------------------
def box_from(text: str) -> dict:
    """Four typed numbers, `x y w h` in percent, as a box kept inside the picture. ValueError otherwise."""
    parts = [p for p in re.split(r"[\s,]+", text.strip()) if p]
    if len(parts) != 4:
        raise ValueError("give four numbers: x y w h, in percent of the picture")
    x, y, w, h = (float(p) for p in parts)
    x, y = min(max(x, 0.0), 99.0), min(max(y, 0.0), 99.0)
    w, h = min(max(w, 1.0), 100.0 - x), min(max(h, 1.0), 100.0 - y)
    return {"x": x, "y": y, "w": w, "h": h}


def crop_of(project_fields: dict) -> dict:
    """The part of the picture kept: all of it when the project says nothing."""
    crop = project_fields.get("crop")
    if not isinstance(crop, dict):
        return dict(WHOLE)
    return {k: seconds(crop.get(k), WHOLE[k]) for k in BOX}


def box_said(box: dict) -> str:
    return " ".join(f"{round(box[k], 1):g}" for k in BOX)


# -- drawing to scale -----------------------------------------------------------------
def spans(pieces: list[dict], first: float, per_cell: float, width: int) -> list[tuple[int, int, dict]]:
    """Where each piece falls in a row *width* cells wide from *first*, at *per_cell* seconds a cell:
    (from cell, to cell exclusive, piece), at least one cell each, left out when off the row."""
    found = []
    for piece in sorted(pieces, key=lambda p: seconds(p.get("start"))):
        a = int((seconds(piece.get("start")) - first) / per_cell)
        b = int(round((end_of(piece) - first) / per_cell))
        b = max(b, a + 1)
        if b <= 0 or a >= width:
            continue
        found.append((max(a, 0), min(b, width), piece))
    return found


__all__ = [
    "BOX",
    "FPS",
    "MIDDLE",
    "SHORTEST",
    "WHOLE",
    "box_at",
    "box_from",
    "box_said",
    "crop_of",
    "duration",
    "edges",
    "effect_on",
    "end_after",
    "end_of",
    "first_track",
    "fps_of",
    "keyframes_of",
    "kind_of_track",
    "media_kind",
    "moved",
    "next_track",
    "on_track",
    "parse_time",
    "piece_at",
    "pieces_at",
    "seconds",
    "seen_at",
    "set_keyframe",
    "shift_keyframes",
    "snap_start",
    "spans",
    "split",
    "split_keyframes",
    "timecode",
    "trim_end",
    "trim_start",
]
