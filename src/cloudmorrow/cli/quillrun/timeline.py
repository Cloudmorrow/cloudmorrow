"""A `timeline`: projects, the pieces on their tracks, and a frame of the cut.

A project is named by its name or the start of its id, a piece the same
way within its project, a file by its name, its path under the screen's
`media`, or its id. Times are seconds, or `m:ss`. The edits are the TUI's
(client/timeline.py), so a cut here shares a piece's blurs out the way `s`
in the terminal does.
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.markup import escape
from rich.table import Table

# quillrun.out, .console and .emit, looked up as they print: see screen.py.
from cloudmorrow.cli import quillrun
from cloudmorrow.cli.common import fail
from cloudmorrow.cli.quillrun.actions import _press
from cloudmorrow.cli.quillrun.screen import Screen, _find, _short
from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.client.timeline import Timeline
from cloudmorrow.console import TITLE
from cloudmorrow.quill import timeline as tl
from cloudmorrow.quill.screens import tracks_of

WORDS = "list, show, add, cut, trim, move, rm, frame and export"


def _time(value: str | float | None, what: str) -> float:
    if isinstance(value, int | float):
        return float(value)
    try:
        return tl.parse_time(str(value or ""))
    except ValueError:
        fail(f"{what} is a time: seconds, or m:ss")
    return 0.0


def _size(fields: dict) -> str:
    if not fields.get("width"):
        return ""
    fps = tl.seconds(fields.get("fps"))
    return f"{fields['width']}×{fields.get('height')}" + (f" {fps:g} fps" if fps else "")


def _status(fields: dict) -> str:
    status = str(fields.get("status") or "")
    message = str(fields.get("message") or "")
    return " — ".join(part for part in (status, message) if part)


async def _project(line: Timeline, key: str) -> dict:
    return _find(await line.projects(), key, line.title)


def _file(material: list[dict], key: str) -> dict:
    """A file of the material by its id, the start of it, its path, or its name (with or without its extension)."""
    wanted = key.strip().strip("/").casefold()
    for test in (
        lambda r: r["id"] == key or r["id"].startswith(key) or r["id"].startswith("r_" + key),
        lambda r: str(r["fields"].get("path") or "").strip("/").casefold().endswith(wanted),
        lambda r: str(r["fields"].get("name") or "").casefold() == wanted,
        lambda r: str(r["fields"].get("name") or "").rsplit(".", 1)[0].casefold() == wanted,
    ):
        found = [r for r in material if test(r)]
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            fail(f"more than one file matches {key!r}: give more of its path")
    fail(f"no video or sound under the material matches {key!r}")
    return {}


def _piece(pieces: list[dict], key: str) -> dict:
    """A piece by the start of its id, or its name (with or without the extension)."""
    stems = [p for p in pieces if str(p["fields"].get("name") or "").rsplit(".", 1)[0].casefold() == key.casefold()]
    return stems[0] if len(stems) == 1 else _find(pieces, key, "name")


async def _act_timeline(
    api: CloudmorrowClient, screen: Screen, action: str, args: list[str], plain: bool, timing: dict
) -> None:
    line = Timeline(api, screen.quill, screen.spec)
    command = f"cm {screen.quill['id']}"
    if action == "list":
        projects = await line.projects()
        if plain:
            quillrun.emit(json.dumps(projects, indent=2) + "\n")
            return
        table = Table(title=screen.spec.get("label") or screen.quill["name"], title_style=TITLE)
        for column in ("id", "name", "picture", "status"):
            table.add_column(column, style="dim" if column == "id" else None)
        for record in projects:
            f = record["fields"]
            table.add_row(_short(record["id"]), escape(str(f.get(line.title) or "")), _size(f), escape(_status(f)))
        quillrun.out.print(table)
        return
    if action == "add" and (len(args) == 1 or (len(args) == 2 and args[1].startswith("size="))):
        # `add <name> [size=1920x1080]` with nothing to put on it: a new
        # project, its size the first clip's unless one is said.
        size = None
        if len(args) == 2:
            size = tl.size_from(args[1].removeprefix("size="))
            if size is None:
                fail(f"a size is width x height: {command} add <name> size=1920x1080")
        made = await line.new_project(args[0], size)
        quillrun.console.print(f"[green]Made[/] {escape(args[0])} [dim]{_short(made['id'])}[/]")
        return
    if not args:
        fail(f"which project? {command} {action} <project> …")
    project = await _project(line, args[0])
    rest = args[1:]
    pieces = await line.pieces(project["id"])
    if action == "show":
        await _show(line, project, pieces, plain)
    elif action == "add":
        await _add(line, project, pieces, rest, timing)
    elif action == "export":
        if line.export is None:
            fail(f"{screen.spec['id']} has no export")
        await _press(api, screen.quill, line.export, [project["id"], *rest], plain)
    elif action == "frame":
        await _frame(line, project, timing)
    elif action in ("cut", "trim", "move", "rm"):
        if not rest:
            fail(f"which piece? {command} {action} <project> <piece> …")
        piece = _piece(pieces, rest[0])
        effects = (await line.effects([piece])).get(piece["id"], [])
        name = escape(str(piece["fields"].get("name") or piece["id"]))
        if action == "cut":
            if len(rest) < 2:
                fail(f"where? {command} cut <project> <piece> <seconds>")
            made = await line.cut(piece, effects, _time(rest[1], "where to cut"))
            if made is None:
                fail(f"{rest[1]} is not inside {name}: it plays {_span(piece['fields'])}")
            quillrun.console.print(f"[green]Cut[/] {name} at {tl.timecode(_time(rest[1], 'at'))}")
        elif action == "trim":
            if timing.get("start") is None and timing.get("end") is None:
                fail(f"trim which end? {command} trim <project> <piece> --start <s> | --end <s>")
            source = await line.info(str(piece["fields"].get("source") or ""))
            changed = await line.trim(
                piece,
                effects,
                start=None if timing.get("start") is None else _time(timing["start"], "--start"),
                end=None if timing.get("end") is None else _time(timing["end"], "--end"),
                source_length=tl.seconds((source or {}).get("duration")) or None,
            )
            quillrun.console.print(f"[green]Trimmed[/] {name}: {_span(changed['fields'])}")
        elif action == "move":
            changes: dict = {}
            if timing.get("at") is not None:
                changes.update(tl.moved(_time(timing["at"], "--at")))
            if timing.get("track"):
                tracks = tracks_of(project["fields"])
                kind = tl.kind_of_track(tracks, str(piece["fields"].get("track")))
                wanted = next((t for t in tracks if t["id"] == timing["track"]), None)
                if wanted is None or wanted["kind"] != kind:
                    same = ", ".join(t["id"] for t in tracks if t["kind"] == kind)
                    fail(f"{name} goes on a {kind} track: {same}")
                changes["track"] = wanted["id"]
            if not changes:
                fail(f"move where? {command} move <project> <piece> --at <s> [--track V1]")
            changed = await line.update(piece, changes)
            quillrun.console.print(f"[green]Moved[/] {name} to {changed['fields']['track']} {_span(changed['fields'])}")
        else:
            await line.remove(piece)
            quillrun.console.print(f"[green]Took out[/] {name}")
    else:
        fail(f"a timeline has {WORDS}, not {action}")


def _span(fields: dict) -> str:
    return f"{tl.timecode(tl.seconds(fields.get('start')))}–{tl.timecode(tl.end_of(fields))}"


async def _show(line: Timeline, project: dict, pieces: list[dict], plain: bool) -> None:
    effects = await line.effects(pieces)
    if plain:
        quillrun.emit(json.dumps({"project": project, "pieces": pieces, "effects": effects}, indent=2) + "\n")
        return
    f = project["fields"]
    about = [p for p in (_size(f), f"{tl.timecode(tl.duration([p['fields'] for p in pieces]))} long") if p]
    crop = tl.crop_of(f)
    if crop != tl.WHOLE:
        about.append(f"cropped to {tl.box_said(crop)}")
    if _status(f):
        about.append(_status(f))
    table = Table(
        title=f"{escape(str(f.get(line.title) or ''))}  [dim]{escape(' · '.join(about))}[/]", title_style=TITLE
    )
    for column in ("track", "id", "piece", "plays", "from source", "effects"):
        table.add_column(column, style="dim" if column == "id" else None)
    for track in tracks_of(f):
        on = tl.on_track([dict(p["fields"], id=p["id"]) for p in pieces], track["id"])
        if not on:
            table.add_row(f"{track['id']} [dim]{escape(track['name'])}[/]", "", "[dim]—[/]", "", "", "")
        for index, piece in enumerate(on):
            said = []
            for effect in effects.get(piece["id"], []):
                ef = effect["fields"]
                kfs = tl.keyframes_of(ef.get("keyframes"))
                said.append(f"{ef.get('kind')} {ef.get('label') or ''} ({len(kfs)} keyframes)".replace("  ", " "))
            sound = " muted" if piece.get("muted") else ""
            table.add_row(
                f"{track['id']} [dim]{escape(track['name'])}[/]" if index == 0 else "",
                _short(piece["id"]),
                escape(str(piece.get("name") or "")) + sound,
                _span(piece),
                f"{tl.timecode(tl.seconds(piece.get('offset')))} +{round(tl.seconds(piece.get('length')), 2):g}s",
                escape(", ".join(said)),
            )
    quillrun.out.print(table)


async def _add(line: Timeline, project: dict, pieces: list[dict], rest: list[str], timing: dict) -> None:
    if not rest:
        fail("add which file? <project> <file> [--track V1] [--at 0] [--length 12]")
    file = _file(await line.material(), rest[0])
    info = await line.info(file["id"])
    length = timing.get("length")
    if length is None:
        length = tl.seconds((info or {}).get("duration")) or None
    if not length:
        fail(f"how long is {file['fields'].get('name')}? There is no frames API to ask: --length <seconds>")
    tracks = tracks_of(project["fields"])
    track = timing.get("track") or (tl.first_track(tracks, file["kind"]) or {}).get("id", "")
    at = timing.get("at")
    # Without --at, after whatever is on the track already.
    start = _time(at, "--at") if at is not None else tl.end_after([p["fields"] for p in pieces], track)
    made = await line.add(project, file, at=start, length=_time(length, "--length"), track=track, info=info)
    quillrun.console.print(
        f"[green]Added[/] {escape(str(made['fields'].get('name')))} on {made['fields']['track']} "
        f"{_span(made['fields'])} [dim]{_short(made['id'])}[/]"
    )


async def _frame(line: Timeline, project: dict, timing: dict) -> None:
    if not line.frames:
        fail(f"{line.spec['id']} has no frames API: a frame is drawn by the Quill's own service")
    at = _time(timing.get("at") or 0, "--at")
    width = int(project["fields"].get("width") or 1280)
    data = await line.frame(project["id"], at, width)
    target = timing.get("out") or "frame.jpg"
    if target == "-":
        import sys

        sys.stdout.buffer.write(data)
        return
    path = Path(target).expanduser()
    path.write_bytes(data)
    quillrun.console.print(f"[green]Saved[/] {escape(str(path))} [dim]the cut at {tl.timecode(at)}[/]")
