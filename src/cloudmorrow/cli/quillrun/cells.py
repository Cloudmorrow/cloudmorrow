"""A `sheet`: sheets of cells, worked out here (docs/CELLS.md)."""

from __future__ import annotations

import json

from rich.markup import escape
from rich.table import Table

# quillrun.out, .console and .emit, looked up as they print: see screen.py.
from cloudmorrow.cli import quillrun
from cloudmorrow.cli.common import fail
from cloudmorrow.cli.quillrun.screen import Screen, _find, _pairs, _short
from cloudmorrow.client.api import ApiError, CloudmorrowClient
from cloudmorrow.console import TITLE
from cloudmorrow.quill import cells
from cloudmorrow.quill.screens import sheet_fields


def _title(screen: Screen, record: dict) -> str:
    return str(record["fields"].get(screen.title) or "").strip() or "Untitled"


def _sheet_of(bound: dict, record: dict) -> cells.Sheet:
    return cells.Sheet.from_field(record["fields"].get(bound["cells"]))


def _plain_value(value):
    if isinstance(value, cells.Error):
        return {"error": value.code}
    return value


def _plain_cell(sheet: cells.Sheet, name: str) -> dict:
    return {"raw": sheet.raw(name), "value": _plain_value(sheet.value(name)), "shown": sheet.shown(name)}


def _print_sheet(screen: Screen, bound: dict, record: dict, *, raw: bool, plain: bool) -> None:
    sheet = _sheet_of(bound, record)
    if plain:
        quillrun.emit(
            json.dumps({name: _plain_cell(sheet, name) for name in sorted(sheet.cells, key=cells.sort_key)}, indent=2)
            + "\n"
        )
        return
    rows = cells.table(sheet, raw=raw)
    if len(rows) == 1:
        quillrun.console.print(f"[dim]{escape(_title(screen, record))} is empty[/]")
        return
    table = Table(title=_title(screen, record), title_style=TITLE)
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


async def _act_cells(
    api: CloudmorrowClient, screen: Screen, action: str, args: list[str], plain: bool, raw: bool
) -> None:
    bound = sheet_fields(screen.spec, screen.models[screen.model])
    if action in ("edit", "search", "say", "move", "done", "undone", "groups", "put"):
        fail(f"a sheet has list, show, get, set, add, delete and history, not {action}")
    records = await api.records(screen.model)
    records.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    if action == "list":
        if plain:
            quillrun.emit(json.dumps(records, indent=2) + "\n")
            return
        table = Table(title=screen.spec.get("label") or screen.quill["name"], title_style=TITLE)
        table.add_column("id", style="dim")
        table.add_column("Sheet")
        table.add_column("Cells", justify="right", style="dim")
        for record in records:
            count = len(cells.parse_cells(record["fields"].get(bound["cells"])))
            table.add_row(_short(record["id"]), escape(_title(screen, record)), str(count))
        quillrun.out.print(table)
        if not records:
            quillrun.console.print(f'[dim]nothing yet — cm {screen.quill["id"]} add "<name>" starts one[/]')
        return
    if not args:
        fail(f"which sheet? cm {screen.quill['id']} {action} <name or id>")
    if action == "add":
        name = " ".join(args)
        made = await api.create_record(screen.model, {screen.title: name, bound["cells"]: {}})
        quillrun.console.print(f"[green]Added[/] {escape(_title(screen, made))} [dim]{_short(made['id'])}[/]")
        return
    found = await api.record(screen.model, _find(records, args[0], screen.title)["id"])
    if action == "show":
        _print_sheet(screen, bound, found, raw=raw, plain=plain)
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
        # `set budget name=Costs` is the record's fields; `set budget B4 …` a cell.
        if cells.parse_ref(args[1]) is None and "=" in args[1]:
            changed = await api.update_record(screen.model, found["id"], _pairs(args[1:], screen), rev=found["rev"])
            quillrun.console.print(f"[green]Saved[/] {escape(_title(screen, changed))}")
            return
        name = _cell_name(screen, action, args)
        sheet = _sheet_of(bound, found)
        sheet.set(name, " ".join(args[2:]))
        try:
            await api.update_record(screen.model, found["id"], {bound["cells"]: sheet.to_field()}, rev=found["rev"])
        except ApiError as exc:
            if exc.status_code == 409:
                fail("it changed somewhere else meanwhile; nothing was saved")
            raise
        shown = sheet.shown(name)
        quillrun.console.print(f"[green]{name}[/] {escape(shown) if shown else '[dim]cleared[/]'}")
    elif action == "delete":
        await api.delete_record(screen.model, found["id"])
        quillrun.console.print(f"[green]Deleted[/] {escape(_title(screen, found))}")
    else:
        fail(f"a sheet has list, show, get, set, add, delete and history, not {action}")
