"""A `photo` editor: edits of one picture each, and the words on them.

An edit is named by its name or the start of its id, a text on it by its
words or the start of its id, a photo by its name, its path under the
screen's `media`, or its id. The edits are the terminal's (client/photo.py),
so a crop typed here is the crop `c` makes there.
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
from cloudmorrow.client.photo import Photo
from cloudmorrow.console import TITLE
from cloudmorrow.quill import photo as ph

WORDS = "list, add, show, turn, mirror, crop, size, text, move, rm, picture and export"


def _status(fields: dict) -> str:
    status = str(fields.get("status") or "")
    message = str(fields.get("message") or "")
    return " — ".join(part for part in (status, message) if part)


async def _edit(photo: Photo, key: str) -> dict:
    return _find(await photo.edits(), key, photo.title)


def _photo(material: list[dict], key: str) -> dict:
    """A photo of the drive by its id, the start of it, its path, or its name (with or without its extension)."""
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
            fail(f"more than one photo matches {key!r}: give more of its path")
    fail(f"no photo under the drive's photos matches {key!r}")
    return {}


def _text(texts: list[dict], key: str) -> dict:
    """A text by the start of its id, or its words."""
    return _find(texts, key, "text")


def _numbers(args: list[str], how_many: int, what: str) -> list[float]:
    """*how_many* numbers from the arguments, given one each or in one quoted string."""
    parts = [p for a in args for p in a.replace(",", " ").split()]
    try:
        numbers = [float(p) for p in parts]
    except ValueError:
        numbers = []
    if len(numbers) != how_many:
        fail(f"{what} is {how_many} numbers")
    return numbers


def _at(timing: dict) -> dict:
    """`--at "x y"` as fields, when given."""
    if timing.get("at") is None:
        return {}
    x, y = _numbers([str(timing["at"])], 2, "--at")
    return {"x": min(max(x, 0.0), 100.0), "y": min(max(y, 0.0), 100.0)}


def _text_fields(timing: dict) -> dict:
    """What `--at`, `--size` and `--colour` say of a text."""
    fields = _at(timing)
    if timing.get("size") is not None:
        try:
            fields["size"] = min(max(float(timing["size"]), 0.5), 100.0)
        except ValueError:
            fail("--size is a number: percent of the picture's height")
    if timing.get("colour") is not None:
        colour = ph.colour_from(timing["colour"])
        if colour is None:
            fail("--colour is #rrggbb, or one of " + ", ".join(ph.COLOURS))
        fields["colour"] = colour
    return fields


async def _act_photo(
    api: CloudmorrowClient, screen: Screen, action: str, args: list[str], plain: bool, timing: dict
) -> None:
    photo = Photo(api, screen.quill, screen.spec)
    command = f"cm {screen.quill['id']}"
    if action == "list":
        edits = await photo.edits()
        if plain:
            quillrun.emit(json.dumps(edits, indent=2) + "\n")
            return
        table = Table(title=screen.spec.get("label") or screen.quill["name"], title_style=TITLE)
        for column in ("id", "name", "size", "status"):
            table.add_column(column, style="dim" if column == "id" else None)
        for record in edits:
            f = record["fields"]
            table.add_row(
                _short(record["id"]), escape(str(f.get(photo.title) or "")), ph.size_said(f), escape(_status(f))
            )
        quillrun.out.print(table)
        return
    if action == "add":
        if not args:
            fail(f"add which photo? {command} add <photo> [name]")
        file = _photo(await photo.material(), args[0])
        made = await photo.new_edit(file, " ".join(args[1:]))
        name = escape(str(made["fields"].get(photo.title) or ""))
        quillrun.console.print(
            f"[green]Started[/] {name} [dim]from {escape(str(file['fields'].get('name')))} · {_short(made['id'])}[/]"
        )
        return
    if not args:
        fail(f"which edit? {command} {action} <edit> …")
    edit = await _edit(photo, args[0])
    rest = args[1:]
    name = escape(str(edit["fields"].get(photo.title) or edit["id"]))
    if action == "show":
        await _show(photo, edit, plain)
    elif action == "turn":
        said = (rest[0] if rest else "right").lower()
        by = {
            "right": 90,
            "r": 90,
            "cw": 90,
            "90": 90,
            "left": -90,
            "l": -90,
            "ccw": -90,
            "-90": -90,
            "270": -90,
            "180": 180,
            "round": 180,
        }.get(said)
        if by is None:
            fail(f"turn which way? {command} turn <edit> [right|left|180]")
        changed = await photo.rotate(edit, by)
        quillrun.console.print(f"[green]Turned[/] {name}: {ph.rotation_of(changed['fields'])}° clockwise")
    elif action == "mirror":
        changed = await photo.mirror(edit)
        quillrun.console.print(f"[green]{'Mirrored' if ph.mirrored(changed['fields']) else 'As taken again'}[/] {name}")
    elif action == "crop":
        if not rest:
            fail(f"crop to what? {command} crop <edit> <x y w h> | all")
        if rest[0].lower() in ("all", "reset", "whole"):
            await photo.crop(edit, None)
            quillrun.console.print(f"[green]The whole picture[/] of {name}")
            return
        try:
            box = ph.box_from(" ".join(rest))
        except ValueError as exc:
            fail(str(exc))
        await photo.crop(edit, box)
        quillrun.console.print(f"[green]Cropped[/] {name} to {ph.box_said(box)}")
    elif action == "size":
        try:
            size = ph.size_from(" ".join(rest), ph.cropped_size(edit["fields"]))
        except ValueError as exc:
            fail(str(exc))
        changed = await photo.resize(edit, size)
        quillrun.console.print(f"[green]{name}[/] comes out {ph.size_said(changed['fields']) or 'as it is'}")
    elif action == "text":
        if not rest:
            fail(f'what words? {command} text <edit> "words" [--at "x y"] [--size 8] [--colour amber]')
        made = await photo.add_text(edit, " ".join(rest), **_text_fields(timing))
        quillrun.console.print(f"[green]On the picture:[/] {ph.text_said(made['fields'])} [dim]{_short(made['id'])}[/]")
    elif action in ("move", "rm"):
        if not rest:
            fail(f"which text? {command} {action} <edit> <text> …")
        text = _text(await photo.texts(edit["id"]), rest[0])
        words = escape(str(text["fields"].get("text") or text["id"]))
        if action == "rm":
            await photo.remove_text(text)
            quillrun.console.print(f"[green]Took off[/] {words}")
            return
        fields = _text_fields(timing)
        if not fields:
            fail(f'move where? {command} move <edit> <text> --at "x y" [--size 8] [--colour amber]')
        changed = await photo.set_text(text, fields)
        quillrun.console.print(f"[green]Moved[/] {ph.text_said(changed['fields'])}")
    elif action == "picture":
        await _picture(photo, edit, timing)
    elif action == "export":
        if photo.export is None:
            fail(f"{screen.spec['id']} has no export")
        await _press(api, screen.quill, photo.export, [edit["id"], *rest], plain)
    else:
        fail(f"a photo editor has {WORDS}, not {action}")


async def _show(photo: Photo, edit: dict, plain: bool) -> None:
    texts = await photo.texts(edit["id"])
    if plain:
        quillrun.emit(json.dumps({"edit": edit, "texts": texts}, indent=2) + "\n")
        return
    f = edit["fields"]
    about = []
    source = ph.source_size(f)
    about.append(f"{source[0]} × {source[1]} as taken" if source else "size not known yet")
    if ph.rotation_of(f):
        about.append(f"turned {ph.rotation_of(f)}°")
    if ph.mirrored(f):
        about.append("mirrored")
    crop = ph.crop_of(f)
    if crop != ph.WHOLE:
        about.append(f"cropped to {ph.box_said(crop)}")
    if ph.size_said(f):
        about.append(f"comes out {ph.size_said(f)}")
    if _status(f):
        about.append(_status(f))
    table = Table(
        title=f"{escape(str(f.get(photo.title) or ''))}  [dim]{escape(' · '.join(about))}[/]", title_style=TITLE
    )
    for column in ("id", "words", "at", "size", "colour"):
        table.add_column(column, style="dim" if column == "id" else None)
    if not texts:
        table.add_row("", "[dim]no words on it[/]", "", "", "")
    for text in texts:
        t = ph.text_of(text["fields"])
        table.add_row(_short(text["id"]), escape(t["text"]), f"{t['x']:g} {t['y']:g}", f"{t['size']:g}%", t["colour"])
    quillrun.out.print(table)


async def _picture(photo: Photo, edit: dict, timing: dict) -> None:
    if not photo.pictures:
        fail(f"{photo.spec['id']} has no pictures API: the picture is drawn by the Quill's own service")
    size = ph.output_size(edit["fields"])
    data = await photo.picture(edit["id"], size[0] if size else 1280)
    target = timing.get("out") or "picture.jpg"
    if target == "-":
        import sys

        sys.stdout.buffer.write(data)
        return
    path = Path(target).expanduser()
    path.write_bytes(data)
    quillrun.console.print(
        f"[green]Saved[/] {escape(str(path))} "
        f"[dim]{escape(str(edit['fields'].get(photo.title) or ''))}, as it will export[/]"
    )
