"""A `sheet`: sheets of cells in `.cell` files, worked out here (docs/CELLS.md)."""

from __future__ import annotations

import json
from pathlib import PurePosixPath

from rich.markup import escape
from rich.table import Table

# quillrun.out, .console and .emit, looked up as they print: see screen.py.
from cloudmorrow.cli import quillrun
from cloudmorrow.cli.common import fail
from cloudmorrow.cli.quillrun.screen import Screen, _pairs
from cloudmorrow.client.api import ApiError, CloudmorrowClient
from cloudmorrow.console import TITLE
from cloudmorrow.quill import cells
from cloudmorrow.quill.screens import listing_filters, page_fields, page_path, page_title, sheet_fields


def _bound(screen: Screen) -> dict:
    return sheet_fields(screen.spec, screen.models[screen.model])


def _key(bound: dict, record: dict) -> str:
    """What a sheet is called on the command line: its path under the root,
    without the suffix, else its title."""
    return page_path(bound, record) or page_title(bound, record)


def _title(bound: dict, record: dict) -> str:
    return page_title(bound, record) or "Untitled"


def _find_sheet(bound: dict, records: list[dict], key: str) -> dict:
    """A sheet by its path, its title, or its id — whole, or the start of one."""
    suffix = bound["suffix"]
    wanted = key.strip().strip("/")
    if suffix and wanted.lower().endswith(suffix.lower()):
        wanted = wanted[: -len(suffix)]
    for test in (
        lambda r: _key(bound, r) == wanted,
        lambda r: r["id"] == key,
        lambda r: _key(bound, r).casefold() == wanted.casefold(),
        lambda r: _title(bound, r).casefold() == wanted.casefold(),
    ):
        matches = [r for r in records if test(r)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            fail(f"more than one sheet matches {key!r}: {', '.join(_key(bound, r) for r in matches)}")
    fail(f"no sheet matches {key!r}")


def _sheet_of(bound: dict, record: dict) -> cells.Sheet:
    return cells.Sheet.from_text(record["fields"].get(bound["cells"]))


def _plain_value(value):
    if isinstance(value, cells.Error):
        return {"error": value.code}
    return value


def _plain_cell(sheet: cells.Sheet, name: str) -> dict:
    return {"raw": sheet.raw(name), "value": _plain_value(sheet.value(name)), "shown": sheet.shown(name)}


def _print_sheet(bound: dict, record: dict, *, raw: bool, plain: bool) -> None:
    sheet = _sheet_of(bound, record)
    if plain:
        quillrun.emit(
            json.dumps({name: _plain_cell(sheet, name) for name in sorted(sheet.cells, key=cells.sort_key)}, indent=2)
            + "\n"
        )
        return
    rows = cells.table(sheet, raw=raw)
    if len(rows) == 1:
        quillrun.console.print(f"[dim]{escape(_title(bound, record))} is empty[/]")
        return
    table = Table(title=_title(bound, record), title_style=TITLE)
    for col in rows[0]:
        table.add_column(col, style="dim" if not col else None, justify="left" if raw or not col else "right")
    for line in rows[1:]:
        table.add_row(*(escape(c) for c in line))
    quillrun.out.print(table)


def _cell_name(screen: Screen, action: str, args: list[str]) -> str:
    if len(args) < 2:
        fail(f"which cell? cm {screen.quill['id']} {action} <sheet> B4")
    at = cells.parse_ref(args[1])
    if at is None:
        fail(f"{args[1]!r} is no cell: a column and a row, as B4")
    return cells.ref_name(*at)


def _moved_fields(bound: dict, screen: Screen, record: dict, pairs: list[str]) -> dict:
    """`set <sheet> name=Costs` renames the file, suffix and folders kept;
    `path=2026/Costs` moves it; any other field is set as it is."""
    plain = [p for p in pairs if p.partition("=")[0] not in (bound["title"], bound["path"], "name", "path")]
    fields = _pairs(plain, screen) if plain else {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        if key in (bound["path"], "path") and bound["path"]:
            fields.update(page_fields(bound, value))
        elif key in (bound["title"], "name"):
            folder = PurePosixPath(_key(bound, record)).parent.as_posix()
            fields.update(page_fields(bound, f"{folder}/{value}" if folder not in ("", ".") else value))
    return fields


async def _act_cells(
    api: CloudmorrowClient, screen: Screen, action: str, args: list[str], plain: bool, raw: bool
) -> None:
    bound = _bound(screen)
    if action in ("edit", "search", "say", "move", "done", "undone", "groups", "put"):
        fail(f"a sheet has list, show, get, set, add, delete and history, not {action}")
    records = await api.records(screen.model, **listing_filters(bound))
    records.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    if action == "list":
        if plain:
            quillrun.emit(json.dumps(records, indent=2) + "\n")
            return
        table = Table(title=screen.spec.get("label") or screen.quill["name"], title_style=TITLE)
        table.add_column("Sheet")
        table.add_column("Changed", style="dim")
        for record in records:
            table.add_row(escape(_key(bound, record)), str(record.get("updated_at") or "")[:16].replace("T", " "))
        quillrun.out.print(table)
        if not records:
            quillrun.console.print(f'[dim]nothing yet — cm {screen.quill["id"]} add "<name>" starts one[/]')
        return
    if not args:
        fail(f"which sheet? cm {screen.quill['id']} {action} <name or path>")
    if action == "add":
        name = " ".join(args).strip("/")
        if any(_key(bound, r).casefold() == name.casefold() for r in records):
            fail(f"there is already a sheet {name!r}")
        made = await api.create_record(screen.model, {**page_fields(bound, name), bound["cells"]: cells.file_text({})})
        quillrun.console.print(f"[green]Added[/] {escape(_key(bound, made))}")
        return
    found = await api.record(screen.model, _find_sheet(bound, records, args[0])["id"])
    if action == "show":
        _print_sheet(bound, found, raw=raw, plain=plain)
    elif action == "get":
        name = _cell_name(screen, action, args)
        sheet = _sheet_of(bound, found)
        if plain:
            quillrun.emit(json.dumps(_plain_cell(sheet, name)) + "\n")
        else:
            quillrun.emit((sheet.raw(name) if raw else sheet.shown(name)) + "\n")
    elif action == "set":
        if len(args) < 2:
            fail(f'which cell? cm {screen.quill["id"]} set <sheet> B4 "=SUM(B1:B3)" — or a field, as name=Budget')
        # `set budget name=Costs` is the file's fields; `set budget B4 …` a cell.
        if cells.parse_ref(args[1]) is None and "=" in args[1]:
            changed = await api.update_record(screen.model, found["id"], _moved_fields(bound, screen, found, args[1:]))
            quillrun.console.print(f"[green]Saved[/] {escape(_key(bound, changed))}")
            return
        name = _cell_name(screen, action, args)
        sheet = _sheet_of(bound, found)
        sheet.set(name, " ".join(args[2:]))
        try:
            await api.update_record(screen.model, found["id"], {bound["cells"]: sheet.to_text()}, rev=found["rev"])
        except ApiError as exc:
            if exc.status_code == 409:
                fail("it changed somewhere else meanwhile; nothing was saved")
            raise
        shown = sheet.shown(name)
        quillrun.console.print(f"[green]{name}[/] {escape(shown) if shown else '[dim]cleared[/]'}")
    elif action == "delete":
        await api.delete_record(screen.model, found["id"])
        quillrun.console.print(f"[green]Deleted[/] {escape(_key(bound, found))}")
    else:
        fail(f"a sheet has list, show, get, set, add, delete and history, not {action}")
