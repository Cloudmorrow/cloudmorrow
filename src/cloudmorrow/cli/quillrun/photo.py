"""A `photo` editor: edits of one picture each, and the layers on them.

An edit is named by its name or the start of its id, a layer on it by its
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

WORDS = "list, add, show, layers, turn, mirror, crop, size, text, move, rm, picture, save and export"


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


def _layer(layers: list[dict], key: str) -> dict:
    """A layer by the start of its id, or its words."""
    return _find(layers, key, "text")


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
    """What `--at`, `--size` and `--colour` say of a layer."""
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
    if action in ("show", "layers"):
        await _show(photo, edit, plain)
    elif action == "turn":
        said = (rest[0] if rest else "right").lower()
        turns = {"right": 90, "r": 90, "cw": 90, "90": 90, "left": -90, "l": -90, "ccw": -90, "-90": -90, "270": -90}
        turns.update({"180": 180, "round": 180})
        by = turns.get(said)
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
        quillrun.console.print(
            f"[green]On the picture:[/] {ph.layer_said(made['fields'])} [dim]{_short(made['id'])}[/]"
        )
    elif action in ("move", "rm"):
        if not rest:
            fail(f"which layer? {command} {action} <edit> <layer> …")
        layer = _layer(await photo.layers(edit["id"]), rest[0])
        said = escape(ph.layer_said(layer["fields"]))
        if action == "rm":
            await photo.remove_layer(layer)
            quillrun.console.print(f"[green]Took off[/] {said}")
            return
        fields = _text_fields(timing)
        if not fields:
            fail(f'move where? {command} move <edit> <layer> --at "x y" [--size 8] [--colour amber]')
        shown = ph.layer_of(layer["fields"])
        if shown["kind"] == "mark" and "x" in fields:
            dx, dy = fields["x"] - shown["x"], fields["y"] - shown["y"]
            fields["points"] = [
                [min(max(px + dx, 0.0), 100.0), min(max(py + dy, 0.0), 100.0)] for px, py in shown["points"]
            ]
        changed = await photo.set_layer(layer, fields)
        quillrun.console.print(f"[green]Moved[/] {escape(ph.layer_said(changed['fields']))}")
    elif action == "picture":
        await _picture(photo, edit, timing)
    elif action == "save":
        if photo.save_action is None:
            fail(f"{screen.spec['id']} has no save")
        source = await photo.source_file(edit)
        photo_name = str(((source or {}).get("fields") or {}).get("name") or "")
        wanted = " ".join(rest).strip()
        overwrite = not wanted or wanted == photo_name
        effects = await photo.save(edit, overwrite=overwrite, name=wanted or photo_name)
        told = next((e.get("text") for e in effects if e.get("effect") in ("toast", "error")), "")
        how = f"over {photo_name or 'the photo'}" if overwrite else f"as {wanted}"
        quillrun.console.print(
            f"[green]Saving[/] {name} {escape(how)}" + (f" [dim]{escape(str(told))}[/]" if told else "")
        )
    elif action == "export":
        if photo.export is None:
            fail(f"{screen.spec['id']} has no export")
        await _press(api, screen.quill, photo.export, [edit["id"], *rest], plain)
    else:
        fail(f"a photo editor has {WORDS}, not {action}")


async def _show(photo: Photo, edit: dict, plain: bool) -> None:
    layers = await photo.layers(edit["id"])
    if plain:
        quillrun.emit(json.dumps({"edit": edit, "layers": layers}, indent=2) + "\n")
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
    for column in ("id", "layer", "at", "size", "colour"):
        table.add_column(column, style="dim" if column == "id" else None)
    if not layers:
        table.add_row("", "[dim]nothing on it[/]", "", "", "")
    # The top layer first, as the editor lists them.
    for record in reversed(layers):
        layer = ph.layer_of(record["fields"])
        hidden = " [dim](hidden)[/]" if layer["hidden"] else ""
        if layer["kind"] == "text":
            table.add_row(
                _short(record["id"]),
                escape(layer["text"]) + hidden,
                f"{layer['x']:g} {layer['y']:g}",
                f"{layer['size']:g}%",
                layer["colour"],
            )
        elif layer["kind"] == "mark":
            table.add_row(
                _short(record["id"]),
                f"mark, {len(layer['points'])} points" + hidden,
                f"{layer['x']:g} {layer['y']:g}",
                f"{layer['width']:g}% wide",
                layer["colour"],
            )
        else:
            table.add_row(
                _short(record["id"]),
                "piece" + hidden,
                f"{layer['x']:g} {layer['y']:g}",
                f"{layer['w']:g} × {layer['h']:g}",
                "",
            )
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
        f"[dim]{escape(str(edit['fields'].get(photo.title) or ''))}, as it will save[/]"
    )
