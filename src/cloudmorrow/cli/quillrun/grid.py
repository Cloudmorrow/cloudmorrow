"""A `grid`: groups, folders, and the bytes of what is in them."""

from __future__ import annotations

import json
from pathlib import Path

from rich.markup import escape
from rich.table import Table

# quillrun.out, .console and .emit, looked up as they print: see screen.py.
from cloudmorrow.cli import quillrun
from cloudmorrow.cli.common import fail
from cloudmorrow.cli.quillrun.screen import (
    Screen,
    _pairs,
    _show_record,
)
from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.console import TITLE
from cloudmorrow.quill.screens import grid_fields


def _size(value: object) -> str:
    size = int(value or 0)
    if size < 1024:
        return f"{size} B"
    number = size / 1024
    for unit in ("KB", "MB", "GB", "TB"):
        if number < 1024 or unit == "TB":
            return f"{number:.0f} {unit}" if number >= 10 else f"{number:.1f} {unit}"
        number /= 1024
    return f"{number:.1f} TB"


class _Grid:
    """What a grid screen binds, read once."""

    def __init__(self, screen: Screen) -> None:
        spec = screen.spec
        self.screen = screen
        self.group = spec["group"]
        self.group_model = screen.models[screen.fields[self.group]["to"]]
        bound = grid_fields(spec, screen.models[screen.model])
        self.folder = bound["folder"]
        self.kind = bound["kind"]
        self.name = screen.title
        self.size = bound["size"]
        self.modified = bound["modified"]
        self.deleted = bound["deleted"]
        self.deleted_from = bound["deleted_from"]
        self.subtitle = bound["subtitle"]

    def where(self, group: str, folder: str) -> dict:
        return {self.group: group, self.folder: folder.strip("/")}


async def _entry(api: CloudmorrowClient, grid: _Grid, group: str, path: str) -> dict:
    folder, _, name = path.strip("/").rpartition("/")
    found = await api.records(grid.screen.model, **grid.where(group, folder))
    for record in found:
        if record["fields"].get(grid.name) == name:
            return record
    fail(f"there is nothing called {path!r} in {group}")


async def _act_grid(api: CloudmorrowClient, screen: Screen, action: str, args: list[str], plain: bool) -> None:
    grid = _Grid(screen)
    command = f"cm {screen.quill['id']}"
    if action in ("list", "groups") and not args:
        groups = await api.records(grid.group_model["id"])
        if plain:
            quillrun.emit(json.dumps(groups, indent=2) + "\n")
            return
        table = Table(title=screen.spec.get("label") or screen.quill["name"], title_style=TITLE)
        table.add_column("id", style="dim")
        table.add_column(grid.group_model["label"])
        if grid.subtitle:
            table.add_column("")
        for record in groups:
            row = [record["id"], escape(str(record["fields"].get(grid.group_model["title"], "")))]
            if grid.subtitle:
                row.append(escape(str(record["fields"].get(grid.subtitle) or "")))
            table.add_row(*row)
        quillrun.out.print(table)
        return
    if not args:
        fail(f"which {grid.group_model['label'].lower()}? {command} {action} <id> …")
    group, rest = args[0], args[1:]
    if action == "list":
        folder = rest[0] if rest else ""
        found = await api.records(screen.model, **grid.where(group, folder))
        if plain:
            quillrun.emit(json.dumps(found, indent=2) + "\n")
            return
        table = Table(title=f"{group}/{folder.strip('/')}", title_style=TITLE)
        for column in ("name", "size", "modified"):
            table.add_column(column)
        folders = [r for r in found if r["fields"].get(grid.kind) == "folder"]
        others = [r for r in found if r["fields"].get(grid.kind) != "folder"]
        for record in sorted(folders, key=lambda r: str(r["fields"].get(grid.name, "")).casefold()) + sorted(
            others, key=lambda r: str(r["fields"].get(grid.name, "")).casefold()
        ):
            fields = record["fields"]
            is_dir = fields.get(grid.kind) == "folder"
            table.add_row(
                escape(str(fields.get(grid.name, ""))) + ("/" if is_dir else ""),
                "" if is_dir or not grid.size else _size(fields.get(grid.size)),
                str(fields.get(grid.modified) or "")[:16].replace("T", " ") if grid.modified else "",
            )
        quillrun.out.print(table)
    elif action == "get":
        if not rest:
            fail(f"get what? {command} get {group} <path> [out]")
        record = await _entry(api, grid, group, rest[0])
        data = await api.record_content(screen.model, record["id"])
        target = rest[1] if len(rest) > 1 else str(record["fields"].get(grid.name))
        if target == "-":
            import sys

            sys.stdout.buffer.write(data)
            return
        path = Path(target).expanduser()
        if path.is_dir():
            path = path / str(record["fields"].get(grid.name))
        if path.exists():
            fail(f"{path} is there already")
        path.write_bytes(data)
        quillrun.console.print(f"[green]Saved[/] {escape(str(path))} [dim]{_size(len(data))}[/]")
    elif action == "put":
        if len(rest) < 2:
            fail(f"put what, where? {command} put {group} <folder> <file> [file…]")
        folder, files = rest[0], rest[1:]
        for name in files:
            source = Path(name).expanduser()
            if not source.is_file():
                fail(f"there is no file at {source}")
            made = await api.upload_record(
                screen.model,
                {**grid.where(group, folder), grid.name: source.name},
                source.read_bytes(),
            )
            quillrun.console.print(
                f"[green]Put[/] {escape(str(made['fields'].get(grid.name)))} "
                f"in {escape(group)}/{escape(folder.strip('/'))}"
            )
    elif action == "add":
        if not rest:
            fail(f"add what? {command} add {group} <folder/new folder>")
        folder, _, name = rest[0].strip("/").rpartition("/")
        await api.create_record(screen.model, {**grid.where(group, folder), grid.name: name, grid.kind: "folder"})
        quillrun.console.print(f"[green]Made[/] {escape(rest[0].strip('/'))}/")
    elif action in ("show", "delete", "set", "restore", "copy"):
        if not rest:
            fail(f"which one? {command} {action} {group} <path>")
        record = await _entry(api, grid, group, rest[0])
        in_trash = bool(grid.deleted and record["fields"].get(grid.deleted))
        if action == "show":
            if plain:
                quillrun.emit(json.dumps(record, indent=2) + "\n")
            else:
                _show_record(screen, record)
        elif action == "set":
            changed = await api.update_record(screen.model, record["id"], _pairs(rest[1:], screen), rev=record["rev"])
            quillrun.console.print(f"[green]Saved[/] {escape(str(changed['fields'].get(grid.name, '')))}")
        elif action == "copy":
            # To a folder, in this group or another (`group:folder`); with
            # neither, a duplicate beside it. A taken name is numbered.
            fields: dict = {}
            if len(rest) > 1:
                where, sep, folder = rest[1].rpartition(":")
                fields = {**grid.where(where if sep else group, folder)}
            made = await api.copy_record(screen.model, record["id"], fields)
            copied = escape(str(made["fields"].get(grid.name, "")))
            quillrun.console.print(f"[green]Copied[/] {escape(rest[0])} to {copied}")
        elif action == "restore":
            # Back where it was before it was deleted; the server makes the
            # folders on the way if they are gone, and numbers a taken name.
            if not in_trash:
                fail(f"{rest[0]} is not in the Trash")
            was = str(record["fields"].get(grid.deleted_from) or record["fields"].get(grid.name))
            folder, _, name = was.rpartition("/")
            changed = await api.update_record(
                screen.model, record["id"], {grid.folder: folder, grid.name: name}, rev=record["rev"]
            )
            restored = escape(str(changed["fields"].get(grid.name, "")))
            quillrun.console.print(f"[green]Restored[/] {restored} to {escape(folder or 'the top')}")
        elif in_trash or not grid.deleted:
            await api.delete_record(screen.model, record["id"])
            quillrun.console.print(f"[green]Deleted[/] {escape(rest[0])} for good")
        else:
            await api.delete_record(screen.model, record["id"])
            quillrun.console.print(f"[green]Moved[/] {escape(rest[0])} to the Trash")
    else:
        fail(f"a {screen.kit} has list, get, put, add, show, set, copy, delete and restore, not {action}")
