"""The kit's `sheet` in the terminal: the sheets, and one open as a grid (docs/CELLS.md).

Drawn from a Cells Quill as the server sends it, over .cell files faked
the way the record API serves them: opening a sheet draws its cells worked
out, typing into a cell writes the file with the rev it read, a sheet
changed elsewhere asks first, a new sheet is made and opened, a rename
moves the file. The modal waits are two `pilot.pause()`s:
`settle()` hangs while a dialog is open.
"""

from __future__ import annotations

import copy

from textual.widgets import DataTable, Input

from cloudmorrow.client.api import ApiError
from cloudmorrow.quill.cells import file_text, parse_cells
from cloudmorrow.tui.panes.kit import pane_for
from cloudmorrow.tui.panes.kit_cells import CellsPane, SheetGrid
from tests.tui_harness import feature_row, settle, start
from tests.tui_notes import FILE_MODEL
from tests.tui_quills import STAMP, TASKS_QUILL, record_row

ROOT = "Documents"
SUFFIX = ".cell"

CELLS_QUILL = {
    **{k: v for k, v in TASKS_QUILL.items() if k not in ("models", "screens", "jobs", "datasets", "data", "uses")},
    "id": "cells",
    "name": "Cells",
    "summary": "Small spreadsheets.",
    "category": "business",
    "icon": "grid",
    "uses": ["file"],
    "screens": [
        {
            "id": "sheets",
            "kit": "sheet",
            "label": "Cells",
            "model": "file",
            "where": {"share": "my-files", "within": ROOT},
            "suffix": SUFFIX,
            "title": "name",
            "cells": "text",
            "path": "path",
        }
    ],
    "jobs": [],
    "datasets": [],
    "data": [{"id": "file", "label": "File", "how": "uses", "foundation": True, "new": False}],
    "models": {"file": FILE_MODEL},
}

BUDGET = {"A1": "Rent", "B1": "1200", "A2": "Food", "B2": "450", "A4": "Total", "B4": "=SUM(B1:B3)"}


class SheetFiles:
    """The .cell files under Documents, as the record API serves them: the five
    calls the pane makes, put on the fake client in place of its own."""

    def __init__(self, client) -> None:
        self.client = client
        # tree path (no root, no suffix) -> [text, rev]
        self.files: dict[str, list] = {"Budget": [file_text(BUDGET), 1], "Empty": [file_text({}), 1]}
        self.calls: list[tuple] = []
        # Everything that is not a sheet file goes on to the fake as it was.
        self.was = {}
        for name in ("records", "record", "create_record", "update_record", "delete_record"):
            self.was[name] = getattr(client, name)
            setattr(client, name, getattr(self, name))

    @staticmethod
    def id_of(path: str) -> str:
        return "s_" + path.replace("/", "__")

    @staticmethod
    def tree_path(raw: str) -> str:
        path = str(raw or "").strip("/")
        path = path[len(ROOT) + 1 :] if path.startswith(ROOT + "/") else path
        return path[: -len(SUFFIX)] if path.endswith(SUFFIX) else path

    def row(self, path: str, *, body: bool = True) -> dict:
        text, rev = self.files[path]
        folder, _, title = path.rpartition("/")
        return record_row(
            "file",
            self.id_of(path),
            0,
            share="my-files",
            path=f"{ROOT}/{path}{SUFFIX}",
            folder=f"{ROOT}/{folder}" if folder else ROOT,
            name=title + SUFFIX,
            kind="file",
            size=len(text.encode()),
            modified=STAMP,
            mime="",
            text=text if body else None,
        ) | {"rev": rev}

    def path_of(self, record_id: str) -> str:
        for path in self.files:
            if self.id_of(path) == record_id:
                return path
        raise ApiError("no such record", status_code=404)

    def text(self, path: str) -> str:
        return self.files[path][0]

    @staticmethod
    def is_sheet(record_id: str) -> bool:
        return str(record_id).startswith("s_")

    async def records(self, model: str, **where: object) -> list[dict]:
        if model != "file" or where.get("within") != ROOT:
            return await self.was["records"](model, **where)
        self.calls.append(("list", model, dict(where)))
        assert where == {"share": "my-files", "within": ROOT, "suffix": SUFFIX}
        return [self.row(path, body=False) for path in sorted(self.files, key=str.casefold)]

    async def record(self, model: str, record_id: str) -> dict:
        if not self.is_sheet(record_id):
            return await self.was["record"](model, record_id)
        return self.row(self.path_of(record_id))

    async def create_record(self, model: str, fields: dict, *, index=None, scope=None) -> dict:
        if model != "file" or not str(fields.get("path") or "").startswith(ROOT + "/"):
            return await self.was["create_record"](model, fields, index=index, scope=scope)
        path = self.tree_path(str(fields["path"]))
        self.calls.append(("create", path, fields.get("text")))
        if path in self.files:
            raise ApiError(f"there is already something called {path}", status_code=400)
        self.files[path] = [str(fields.get("text") or ""), 1]
        return self.row(path)

    async def update_record(self, model: str, record_id: str, fields: dict, *, rev=None) -> dict:
        if not self.is_sheet(record_id):
            return await self.was["update_record"](model, record_id, fields, rev=rev)
        path = self.path_of(record_id)
        self.calls.append(("update", path, dict(fields), rev))
        if "text" in fields:
            if rev is not None and rev != self.files[path][1]:
                raise ApiError("changed since you read it", status_code=409)
            self.files[path][0] = str(fields["text"])
            self.files[path][1] += 1
        moved = self.tree_path(str(fields["path"])) if fields.get("path") else path
        if moved != path:
            if moved in self.files:
                raise ApiError(f"there is already something called {moved}", status_code=400)
            self.files[moved] = self.files.pop(path)
            path = moved
        return self.row(path)

    async def delete_record(self, model: str, record_id: str) -> None:
        if not self.is_sheet(record_id):
            return await self.was["delete_record"](model, record_id)
        del self.files[self.path_of(record_id)]


def with_cells(app) -> SheetFiles:
    app.client.quill_list = [q for q in app.client.quill_list if q["id"] != "notes"]
    app.client.quill_list.insert(0, copy.deepcopy(CELLS_QUILL))
    app.client.feature_list.append(feature_row("cells", "Cells"))
    return SheetFiles(app.client)


async def _modal(pilot) -> None:
    await pilot.pause()
    await pilot.pause()


async def open_cells(app, pilot):
    """Start, then over to Cells — the workspace lands on the first personal card."""
    screen = await start(app, pilot)
    screen.action_show_pane("cells")
    await settle(app, pilot)
    assert screen.query_one("#panes").current == "pane-cells"
    return screen


def test_the_cells_screen_is_a_cells_pane():
    pane = pane_for(CELLS_QUILL, CELLS_QUILL["screens"][0], tab_key="f1", id="pane-cells")
    assert isinstance(pane, CellsPane)
    assert (pane.title_field, pane.cells_field) == ("name", "text")
    assert pane.filters == {"share": "my-files", "within": ROOT, "suffix": SUFFIX}
    assert [a.id for a in pane.ACTIONS] == [
        "new_record",
        "save",
        "rename",
        "open_anywhere",
        "export_file",
        "delete_record",
    ]


async def test_the_sheets_are_listed_and_one_opens_worked_out(app):
    files = with_cells(app)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_cells(app, pilot)
        pane = screen.query_one(CellsPane)
        listing = pane.query_one("#cells-list", DataTable)
        assert [str(listing.get_row_at(i)[0]) for i in range(listing.row_count)] == ["[b]Budget[/]", "[b]Empty[/]"]
        assert files.calls[0] == ("list", "file", {"share": "my-files", "within": ROOT, "suffix": SUFFIX})
        pane.open_sheet(files.id_of("Budget"))
        await settle(app, pilot)
        grid = pane.query_one(SheetGrid)
        assert str(grid.get_cell("0", "A")) == "Rent"
        assert str(grid.get_cell("0", "B")) == "1200"
        assert str(grid.get_cell("3", "B")) == "1650", "the formula is worked out"
        # The bar says which cell, and what is typed in it.
        grid.move_cursor(row=3, column=1)
        await pilot.pause()
        assert pane.query_one("#cells-formula", Input).value == "=SUM(B1:B3)"
        assert pane.at_name == "B4"


async def test_typing_into_a_cell_saves_with_the_rev_it_read(app):
    files = with_cells(app)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_cells(app, pilot)
        pane = screen.query_one(CellsPane)
        pane.open_sheet(files.id_of("Budget"))
        await settle(app, pilot)
        grid = pane.query_one(SheetGrid)
        grid.move_cursor(row=2, column=1)
        grid.focus()
        await pilot.pause()
        await pilot.press("3", "0", "0", "enter")
        await settle(app, pilot)
        assert str(grid.get_cell("3", "B")) == "1950", "the total follows"
        assert pane.at == (3, 1), "Enter moves down"
        await pane.flush()
        await settle(app, pilot)
        assert files.text("Budget").startswith('{\n  "cells": {\n    "A1": "Rent",\n'), "the file is written whole"
        saved = parse_cells(files.text("Budget"))
        assert saved["B3"] == "300" and list(saved) == ["A1", "B1", "A2", "B2", "B3", "A4", "B4"]
        assert files.calls[-1][3] == 1, "with the rev it read"
        assert not pane.dirty
        # Delete clears the cell, and the sheet drops it.
        await pilot.press("up", "delete")
        await settle(app, pilot)
        await pane.flush()
        await settle(app, pilot)
        assert "B3" not in parse_cells(files.text("Budget"))


async def test_a_formula_wanting_a_reference_takes_it_from_the_arrows(app):
    files = with_cells(app)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_cells(app, pilot)
        pane = screen.query_one(CellsPane)
        pane.open_sheet(files.id_of("Budget"))
        await settle(app, pilot)
        grid = pane.query_one(SheetGrid)
        grid.move_cursor(row=4, column=1)
        grid.focus()
        await pilot.pause()
        line = pane.query_one("#cells-formula", Input)
        # `=2*`, then up: B4 is written and shown pointed; up again moves it.
        await pilot.press("=", "2", "*", "up")
        assert line.value == "=2*B4" and pane.point is not None
        assert any(span.style == "reverse" for span in grid.get_cell("3", "B").spans), "B4 is drawn pointed"
        await pilot.press("up")
        assert line.value == "=2*B3"
        # Shift and an arrow make it a range; Enter keeps it and typing goes on.
        await pilot.press("shift+down", "enter")
        assert line.value == "=2*B3:B4" and pane.point is None and line.has_focus
        assert line.cursor_position == len(line.value)
        await pilot.press("+", "1", "enter")
        await settle(app, pilot)
        assert pane.sheet.raw("B5") == "=2*B3:B4+1", "the formula is kept as written, right or not"
        assert pane.at == (5, 1), "and the second Enter commits and moves down"
        # No reference wanted: the arrows move the caret as ever.
        await pilot.press("4", "2", "left", "left", "enter")
        await settle(app, pilot)
        assert pane.sheet.raw("B6") == "42"


async def test_a_sheet_changed_elsewhere_asks_before_writing_over_it(app):
    files = with_cells(app)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_cells(app, pilot)
        pane = screen.query_one(CellsPane)
        pane.open_sheet(files.id_of("Budget"))
        await settle(app, pilot)
        files.files["Budget"][1] = 7  # somebody else saved
        pane.put("C1", "mine")
        pane.save_sheet()
        await _modal(pilot)
        assert app.screen.__class__.__name__ == "ConflictModal"
        await pilot.press("escape")
        await settle(app, pilot)
        assert "C1" not in parse_cells(files.text("Budget"))


async def test_a_new_sheet_is_made_and_opened(app):
    files = with_cells(app)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_cells(app, pilot)
        pane = screen.query_one(CellsPane)
        pane.new_sheet()
        await _modal(pilot)
        await pilot.press(*"Costs", "enter")
        await settle(app, pilot)
        assert ("create", "Costs", file_text({})) in files.calls, "a .cell file under the root, empty"
        assert pane.current_id == files.id_of("Costs")
        assert pane.query_one(SheetGrid).has_focus


async def test_a_rename_moves_the_file_and_the_open_sheet_follows(app):
    files = with_cells(app)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_cells(app, pilot)
        pane = screen.query_one(CellsPane)
        pane.open_sheet(files.id_of("Budget"))
        await settle(app, pilot)
        pane.rename(pane.selected)
        await _modal(pilot)
        await pilot.press("end", *["backspace"] * len("Budget"), *"2026/Costs", "enter")
        await settle(app, pilot)
        assert "2026/Costs" in files.files and "Budget" not in files.files
        assert ("update", "Budget", {"share": "my-files", "path": f"{ROOT}/2026/Costs{SUFFIX}"}, None) in files.calls
        assert pane.current_id == files.id_of("2026/Costs"), "a file kept by its path is a new id afterwards"
        listing = pane.query_one("#cells-list", DataTable)
        assert [str(listing.get_row_at(i)[0]) for i in range(listing.row_count)] == ["[b]2026/Costs[/]", "[b]Empty[/]"]


async def test_read_only_shows_and_takes_nothing(app):
    files = with_cells(app)
    app.client.quill_list[0]["models"]["file"]["access"] = "read"
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_cells(app, pilot)
        pane = screen.query_one(CellsPane)
        # Reading sheets still opens one from anywhere, and exports it.
        assert not pane.writes and [a.id for a in pane.ACTIONS] == ["open_anywhere", "export_file"]
        pane.open_sheet(files.id_of("Budget"))
        await settle(app, pilot)
        assert str(pane.query_one(SheetGrid).get_cell("3", "B")) == "1650"
        assert pane.query_one("#cells-formula", Input).disabled
        pane.query_one(SheetGrid).focus()
        await pilot.press("9", "enter")
        await settle(app, pilot)
        assert parse_cells(files.text("Budget")) == BUDGET
