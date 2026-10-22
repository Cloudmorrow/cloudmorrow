"""The kit's `sheet` in the terminal: the sheets, and one open as a grid (docs/CELLS.md).

Drawn from a Cells Quill as the server sends it, against the fake record
store: opening a sheet draws its cells worked out, typing into a cell saves
the sheet with the rev it read, a sheet changed elsewhere asks first, a new
sheet is made and opened. The modal waits are two `pilot.pause()`s:
`settle()` hangs while a dialog is open.
"""

from __future__ import annotations

import copy

from textual.widgets import DataTable, Input

from cloudmorrow.tui.panes.kit import pane_for
from cloudmorrow.tui.panes.kit_cells import CellsPane, SheetGrid
from tests.tui_harness import feature_row, settle, start
from tests.tui_quills import TASKS_QUILL, record_row

SHEET_MODEL = {
    "id": "sheet",
    "version": 1,
    "label": "Sheet",
    "description": "A small spreadsheet.",
    "domain": "sheets",
    "scopes": ["personal"],
    "title": "name",
    "ordered_within": [],
    "source": "foundation",
    "fields": [
        {"name": "name", "kind": "string", "label": "Name", "required": True, "indexed": True},
        {"name": "cells", "kind": "json", "label": "Cells"},
        {"name": "notes", "kind": "text", "label": "Notes"},
    ],
}

CELLS_QUILL = {
    **{k: v for k, v in TASKS_QUILL.items() if k not in ("models", "screens", "jobs", "datasets", "data", "uses")},
    "id": "cells",
    "name": "Cells",
    "summary": "Small spreadsheets.",
    "category": "business",
    "icon": "grid",
    "uses": ["sheet"],
    "screens": [
        {"id": "sheets", "kit": "sheet", "label": "Cells", "model": "sheet", "title": "name", "cells": "cells"}
    ],
    "jobs": [],
    "datasets": [],
    "data": [{"id": "sheet", "label": "Sheet", "how": "uses", "foundation": True, "new": False}],
    "models": {"sheet": SHEET_MODEL},
}

BUDGET = {"A1": "Rent", "B1": "1200", "A2": "Food", "B2": "450", "A4": "Total", "B4": "=SUM(B1:B3)"}


def with_cells(app) -> None:
    app.client.quill_list = [q for q in app.client.quill_list if q["id"] != "notes"]
    app.client.quill_list.insert(0, copy.deepcopy(CELLS_QUILL))
    app.client.feature_list.append(feature_row("cells", "Cells"))
    app.client.record_store["sheet"] = [
        record_row("sheet", "r_budget", 0, name="Budget", cells=dict(BUDGET)),
        record_row("sheet", "r_empty", 1, name="Empty", cells={}),
    ]


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
    assert (pane.title_field, pane.cells_field) == ("name", "cells")
    assert [a.id for a in pane.ACTIONS] == ["new_record", "save", "rename", "delete_record"]


async def test_the_sheets_are_listed_and_one_opens_worked_out(app):
    with_cells(app)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_cells(app, pilot)
        pane = screen.query_one(CellsPane)
        listing = pane.query_one("#cells-list", DataTable)
        assert [str(listing.get_row_at(i)[0]) for i in range(listing.row_count)] == ["[b]Budget[/]", "[b]Empty[/]"]
        pane.open_sheet("r_budget")
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
    with_cells(app)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_cells(app, pilot)
        pane = screen.query_one(CellsPane)
        pane.open_sheet("r_budget")
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
        saved = app.client.record_store["sheet"][0]["fields"]["cells"]
        assert saved["B3"] == "300" and list(saved) == ["A1", "B1", "A2", "B2", "B3", "A4", "B4"]
        assert not pane.dirty
        # Delete clears the cell, and the sheet drops it.
        await pilot.press("up", "delete")
        await settle(app, pilot)
        await pane.flush()
        await settle(app, pilot)
        assert "B3" not in app.client.record_store["sheet"][0]["fields"]["cells"]


async def test_a_sheet_changed_elsewhere_asks_before_writing_over_it(app):
    with_cells(app)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_cells(app, pilot)
        pane = screen.query_one(CellsPane)
        pane.open_sheet("r_budget")
        await settle(app, pilot)
        app.client.record_store["sheet"][0]["rev"] = 7  # somebody else saved
        pane.put("C1", "mine")
        pane.save_sheet()
        await _modal(pilot)
        assert app.screen.__class__.__name__ == "ConflictModal"
        await pilot.press("escape")
        await settle(app, pilot)
        assert "C1" not in app.client.record_store["sheet"][0]["fields"]["cells"]


async def test_a_new_sheet_is_made_and_opened(app):
    with_cells(app)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_cells(app, pilot)
        pane = screen.query_one(CellsPane)
        pane.new_sheet()
        await _modal(pilot)
        await pilot.press(*"Costs", "enter")
        await settle(app, pilot)
        made = next(r for r in app.client.record_store["sheet"] if r["fields"]["name"] == "Costs")
        assert made["fields"]["cells"] == {}
        assert pane.current_id == made["id"]
        assert pane.query_one(SheetGrid).has_focus


async def test_read_only_shows_and_takes_nothing(app):
    with_cells(app)
    app.client.quill_list[0]["models"]["sheet"]["access"] = "read"
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_cells(app, pilot)
        pane = screen.query_one(CellsPane)
        assert not pane.writes and [a.id for a in pane.ACTIONS] == []
        pane.open_sheet("r_budget")
        await settle(app, pilot)
        assert str(pane.query_one(SheetGrid).get_cell("3", "B")) == "1650"
        assert pane.query_one("#cells-formula", Input).disabled
        pane.query_one(SheetGrid).focus()
        await pilot.press("9", "enter")
        await settle(app, pilot)
        assert app.client.record_store["sheet"][0]["fields"]["cells"] == BUDGET
