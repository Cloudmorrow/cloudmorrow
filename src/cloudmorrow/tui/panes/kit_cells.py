"""The kit's `sheet` in the terminal: the sheets on the left, the grid on the right.

A sheet screen binds a datamodel, its title, and `cells`, a json field
holding what is typed in each cell by name (docs/CELLS.md). The sheets are
listed newest first; the one picked is drawn as a grid, worked out by
quill/cells.py, with the cell's name and what is typed in it over it.

Arrows move; Enter, or typing, edits the cell on the line above the grid;
Enter there keeps it and moves down, Tab across, Escape leaves the cell as
it was; Delete clears it. While a formula wants a reference — after `=`,
an operator, `(`, a comma or a colon — the arrows point one out instead:
the cell's name is written on the line and follows as they move, Shift
and an arrow make it a range, Enter keeps it and typing goes on. It saves on its own, and `ctrl+s` saves now. A
sheet changed somewhere else since it was opened is not written over: you
are asked. A sheet you may only read shows, and nothing types into it.
"""

from __future__ import annotations

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.message import Message
from textual.timer import Timer
from textual.widgets import DataTable, Input, Static

from cloudmorrow.client.api import ApiError, AuthError
from cloudmorrow.quill import cells
from cloudmorrow.quill.screens import sheet_fields
from cloudmorrow.tui.kitdata import is_conflict
from cloudmorrow.tui.panes.kit import KitPane
from cloudmorrow.tui.screens.modals import ConfirmModal, ConflictModal, PromptModal
from cloudmorrow.tui.theme import MUTED, SECOND
from cloudmorrow.tui.widgets.toolbar import Action
from cloudmorrow.tui.words import plural

COLUMN_WIDTH = 12
ARROWS = {"up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1)}


class SheetGrid(DataTable):
    """The cells, in a table whose rows are numbered and whose columns are lettered.

    The keys that edit are the pane's: this only says what was pressed.
    """

    BINDINGS = [
        Binding("enter", "edit", "Edit", show=False),
        Binding("delete,backspace", "clear", "Clear", show=False),
        Binding("tab", "across(1)", "Right", show=False),
        Binding("shift+tab", "across(-1)", "Left", show=False),
    ]

    class EditRequested(Message):
        def __init__(self, initial: str | None) -> None:
            self.initial = initial
            super().__init__()

    class ClearRequested(Message):
        pass

    def action_edit(self) -> None:
        self.post_message(self.EditRequested(None))

    def action_clear(self) -> None:
        self.post_message(self.ClearRequested())

    def action_across(self, step: int) -> None:
        here = self.cursor_coordinate
        self.move_cursor(row=here.row, column=max(0, here.column + step))

    def on_key(self, event: Key) -> None:
        # A letter, a digit, `=`: start editing the cell with it.
        if event.is_printable and event.character and not event.key.startswith("ctrl"):
            event.stop()
            event.prevent_default()
            self.post_message(self.EditRequested(event.character))


class CellsPane(KitPane):
    """The sheets, and the one open as a grid."""

    BINDINGS = [
        ("ctrl+n", "fire('new_record')", "New"),
        ("ctrl+s", "fire('save')", "Save"),
        ("f2", "fire('rename')", "Rename"),
        ("delete", "fire('delete_record')", "Delete"),
    ]
    WRITING = frozenset({"new_record", "save", "rename", "delete_record"})

    def __init__(self, quill: dict, screen: dict, **kwargs) -> None:
        super().__init__(quill, screen, **kwargs)
        self.bound = sheet_fields(screen, self.model)
        self.title_field: str = self.bound["title"]
        self.cells_field: str = self.bound["cells"]
        self.ACTIONS = self.offer(
            [
                Action("new_record", f"New {self.noun}", "^n", variant="primary"),
                Action("save", "Save", "^s"),
                Action("rename", "Rename", "f2"),
                Action("delete_record", "Delete", "del"),
            ]
        )
        self.sheet = cells.Sheet()
        # The sheet that is open: its id and its rev.
        self.current_id: str | None = None
        self.current_rev: object = None
        self.dirty = False
        # A reference being pointed out on the line: where it is written in
        # the text (start, end), and the cells it names (anchor, at).
        self.point: dict | None = None
        self._autosave_timer: Timer | None = None
        # How many rows and columns the grid draws; it grows as the sheet does.
        self.rows = 0
        self.cols = 0

    def content(self) -> ComposeResult:
        with Horizontal(id="cells-body"):
            yield DataTable(id="cells-list", cursor_type="row", zebra_stripes=True)
            with Vertical(id="cells-pane"):
                yield Static(f"no {self.noun} open", id="cells-name")
                with Horizontal(id="cells-bar"):
                    yield Static("A1", id="cells-where")
                    # Typing into a cell starts with what was typed to start it:
                    # the line must not select what it holds when it takes focus.
                    line = Input(id="cells-formula", placeholder="a value, or =SUM(B1:B3)", select_on_focus=False)
                    line.disabled = not self.writes
                    yield line
                yield SheetGrid(id="cells-grid", cursor_type="cell", zebra_stripes=False)

    def on_mount(self) -> None:
        table = self.query_one("#cells-list", DataTable)
        table.add_columns("SHEET", "CELLS")

    # -- the sheets -----------------------------------------------------------------
    @property
    def listing(self) -> DataTable:
        return self.query_one("#cells-list", DataTable)

    @property
    def grid(self) -> SheetGrid:
        return self.query_one(SheetGrid)

    @property
    def line(self) -> Input:
        return self.query_one("#cells-formula", Input)

    def title_of(self, record: dict) -> str:
        return str((record.get("fields") or {}).get(self.title_field) or "").strip() or "Untitled"

    @work(exclusive=True, group="kit-list")
    async def reload(self, select: str | None = None) -> None:
        if self.api is None:
            return
        try:
            self.records = await self.api.records(self.model_id)
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        self.records.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
        self.loaded = True
        self.draw(keep=select or self.current_id)

    def draw(self, *, keep: str | None = None) -> None:
        table = self.listing
        row = table.cursor_row
        table.clear()
        for record in self.records:
            count = len(cells.parse_cells((record.get("fields") or {}).get(self.cells_field)))
            table.add_row(f"[b]{self.title_of(record)}[/]", f"[{MUTED}]{count}[/]", key=str(record["id"]))
        if keep is not None:
            row = next((i for i, r in enumerate(self.records) if r["id"] == keep), row)
        if self.records:
            table.move_cursor(row=min(max(row, 0), len(self.records) - 1))
        empty = "Nothing here."
        if self.writes:
            empty = f"Nothing here yet — New {self.noun} starts one."
        self.status("" if self.records else empty, note=True)
        # The one open may have gone, or come back with another rev.
        if self.current_id and self.current_id not in {r["id"] for r in self.records}:
            self.forget_open()

    def card_status(self) -> tuple[str, str] | None:
        if not self.loaded:
            return None
        return "ok", plural(len(self.records), self.noun)

    @property
    def selected(self) -> dict | None:
        table = self.listing
        if not self.records or not 0 <= table.cursor_row < len(self.records):
            return None
        return self.records[table.cursor_row]

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter on a sheet, or a click on it: open it."""
        if event.data_table.id != "cells-list":
            return
        event.stop()
        record = self.selected
        if record is not None and record["id"] != self.current_id:
            self.open_sheet(str(record["id"]))

    # -- open / save -------------------------------------------------------------------
    @work(exclusive=True, group="io")
    async def open_sheet(self, record_id: str) -> None:
        if self.dirty and self.current_id:
            await self._save()
        try:
            record = await self.api.record(self.model_id, record_id)
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        self._show(record)

    def _show(self, record: dict) -> None:
        self.current_id = str(record["id"])
        self.current_rev = record.get("rev")
        self.dirty = False
        self.point = None
        self.sheet = cells.Sheet.from_field((record.get("fields") or {}).get(self.cells_field))
        self.draw_grid(keep=(0, 0))
        self.query_one("#cells-name", Static).update(f"[{SECOND}]{self.title_of(record)}[/]")
        self.status()

    def forget_open(self) -> None:
        self.current_id = None
        self.current_rev = None
        self.dirty = False
        self.point = None
        self.sheet = cells.Sheet()
        self.draw_grid(keep=(0, 0))
        self.query_one("#cells-name", Static).update(f"no {self.noun} open")

    def _schedule_autosave(self) -> None:
        if self._autosave_timer is not None:
            self._autosave_timer.stop()
        delay = max(0.3, float(self.app.client_config.autosave_seconds))
        self._autosave_timer = self.set_timer(delay, self._autosave)

    def _autosave(self) -> None:
        self._autosave_timer = None
        if self.dirty and self.current_id:
            self.save_sheet()

    def act_save(self) -> None:
        if self.current_id is None:
            self.status("Nothing open.", error=True)
            return
        self.save_sheet()

    @work(exclusive=True, group="io")
    async def save_sheet(self) -> None:
        if self.current_id:
            await self._save()

    async def flush(self) -> None:
        """Save anything unsaved. The workspace calls this before it moves on."""
        if self.dirty and self.current_id and self.writes:
            await self._save()

    async def _save(self, *, force: bool = False) -> None:
        content = self.sheet.to_field()
        record_id = self.current_id
        try:
            saved = await self.api.update_record(
                self.model_id, record_id, {self.cells_field: content}, rev=None if force else self.current_rev
            )
        except AuthError as exc:
            await self.went_wrong(exc)
            return
        except ApiError as exc:
            if not is_conflict(exc, stale=True):
                self.status(f"Save failed: {exc}", error=True)
                return
            choice = await self.app.push_screen_wait(ConflictModal(self.title_of(self.selected or {})))
            if choice == "overwrite":
                await self._save(force=True)
            elif choice == "reload":
                self.dirty = False
                self.open_sheet(record_id)
            else:
                self.status("Save cancelled — the server copy is newer.", error=True)
            return
        self.current_rev = saved.get("rev")
        # Anything typed while the request was in flight keeps the sheet dirty.
        self.dirty = self.sheet.to_field() != content
        self.status("" if self.dirty else "saved")
        for record in self.records:
            if record["id"] == record_id:
                record["fields"] = saved.get("fields") or record["fields"]
        self.draw(keep=record_id)

    # -- the grid ---------------------------------------------------------------------
    @property
    def at(self) -> tuple[int, int]:
        here = self.grid.cursor_coordinate
        return here.row, here.column

    @property
    def at_name(self) -> str:
        return cells.ref_name(*self.at)

    def _cell_text(self, name: str) -> Text:
        value = self.sheet.value(name)
        shown = self.sheet.shown(name)
        if isinstance(value, cells.Error):
            text = Text(shown, style="bold red", justify="center")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            text = Text(shown, justify="right")
        else:
            text = Text(shown)
        if self.point is not None and self._pointed(name):
            text.stylize("reverse")
        return text

    def draw_grid(self, *, keep: tuple[int, int] | None = None) -> None:
        """The whole grid again: as many rows and columns as the sheet uses,
        with room beyond, and never fewer than the cursor needs."""
        grid = self.grid
        at = keep or self.at
        rows, cols = self.sheet.extent
        self.rows = max(rows, at[0] + 2)
        self.cols = max(cols, at[1] + 2)
        grid.clear(columns=True)
        for c in range(self.cols):
            grid.add_column(Text(cells.col_name(c), justify="center"), width=COLUMN_WIDTH, key=cells.col_name(c))
        for r in range(self.rows):
            grid.add_row(
                *(self._cell_text(cells.ref_name(r, c)) for c in range(self.cols)), key=str(r), label=str(r + 1)
            )
        grid.move_cursor(row=min(at[0], self.rows - 1), column=min(at[1], self.cols - 1), scroll=False)
        self.say_cell()

    def refresh_cells(self) -> None:
        """Every cell's text again, from the sheet as it now is."""
        grid = self.grid
        for r in range(self.rows):
            for c in range(self.cols):
                grid.update_cell(str(r), cells.col_name(c), self._cell_text(cells.ref_name(r, c)))

    def say_cell(self) -> None:
        """The bar: which cell the cursor is on, and what is typed in it."""
        if not self.is_mounted:
            return
        name = self.at_name
        self.query_one("#cells-where", Static).update(f"[{SECOND}]{name}[/]")
        line = self.line
        if not line.has_focus:
            line.value = self.sheet.raw(name)

    def on_data_table_cell_highlighted(self, event: DataTable.CellHighlighted) -> None:
        if event.data_table.id != "cells-grid":
            return
        event.stop()
        here = event.coordinate
        # Past the edge: more rows or columns to type into.
        if self.current_id and (here.row >= self.rows - 1 or here.column >= self.cols - 1):
            self.draw_grid(keep=(here.row, here.column))
            return
        self.say_cell()

    # -- editing ----------------------------------------------------------------------
    def on_sheet_grid_edit_requested(self, event: SheetGrid.EditRequested) -> None:
        event.stop()
        if self.current_id is None or not self.writes:
            return
        self._end_point()
        line = self.line
        line.focus()
        line.value = self.sheet.raw(self.at_name) if event.initial is None else event.initial
        line.cursor_position = len(line.value)

    def on_sheet_grid_clear_requested(self, event: SheetGrid.ClearRequested) -> None:
        event.stop()
        if self.current_id is None or not self.writes:
            return
        self.put(self.at_name, "")

    def put(self, name: str, raw: str) -> bool:
        """What is typed into a cell: the sheet, the grid, and a save soon."""
        if self.sheet.raw(name) == raw:
            self.say_cell()
            return False
        self.sheet.set(name, raw)
        rows, cols = self.sheet.extent
        if rows > self.rows or cols > self.cols:
            self.draw_grid()
        else:
            self.refresh_cells()
            self.say_cell()
        self.dirty = True
        self.status()
        self._schedule_autosave()
        return True

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "cells-formula":
            return
        event.stop()
        self._end_point()
        if self.current_id is None or not self.writes:
            return
        self.put(self.at_name, event.value)
        row, col = self.at
        self.grid.move_cursor(row=row + 1, column=col)
        self.grid.focus()

    def on_key(self, event: Key) -> None:
        line = self.line
        if not line.has_focus:
            return
        if self._point_key(event):
            return
        if event.key == "escape":
            event.stop()
            line.value = self.sheet.raw(self.at_name)
            self.grid.focus()
        elif event.key in ("tab", "shift+tab"):
            event.stop()
            event.prevent_default()
            if self.current_id is not None and self.writes:
                self.put(self.at_name, line.value)
            row, col = self.at
            self.grid.move_cursor(row=row, column=max(0, col + (1 if event.key == "tab" else -1)))
            self.grid.focus()

    # -- pointing -----------------------------------------------------------------------
    # Excel's way of writing a reference. While the formula wants one, the
    # arrows pick a cell and its name is written where the cursor is,
    # following as they move; Shift and an arrow make it a range. Enter
    # keeps the name and typing goes on, as does any other key.
    def _pointing(self) -> bool:
        if self.point is not None:
            return True
        line = self.line
        return self.current_id is not None and self.writes and cells.wants_ref(line.value[: line.cursor_position])

    def _point_key(self, event: Key) -> bool:
        """A key on the line: True when it was pointing's."""
        arrow = ARROWS.get(event.key.removeprefix("shift+"))
        if arrow is not None and self._pointing():
            event.stop()
            event.prevent_default()
            frm = self.point["at"] if self.point is not None else self.at
            self._point_to((frm[0] + arrow[0], frm[1] + arrow[1]), extend=event.key.startswith("shift+"))
            return True
        if self.point is None:
            return False
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self._end_point()
            return True
        self._end_point()
        return False

    def _point_to(self, target: tuple[int, int], *, extend: bool) -> None:
        line = self.line
        at = (min(max(0, target[0]), self.rows - 1), min(max(0, target[1]), self.cols - 1))
        point = self.point or {"start": line.cursor_position, "end": line.cursor_position, "anchor": at}
        point["at"] = at
        if not extend:
            point["anchor"] = at
        name = cells.range_name(point["anchor"], at)
        line.value = line.value[: point["start"]] + name + line.value[point["end"] :]
        point["end"] = point["start"] + len(name)
        line.cursor_position = point["end"]
        self.point = point
        self.refresh_cells()

    def _pointed(self, name: str) -> bool:
        place = cells.parse_ref(name)
        if place is None or self.point is None:
            return False
        (r0, c0), (r1, c1) = self.point["anchor"], self.point["at"]
        return min(r0, r1) <= place[0] <= max(r0, r1) and min(c0, c1) <= place[1] <= max(c0, c1)

    def _end_point(self) -> None:
        if self.point is None:
            return
        self.point = None
        self.refresh_cells()

    # -- new, rename, delete ------------------------------------------------------------
    def act_new_record(self) -> None:
        self.new_sheet()

    @work(group="ui")
    async def new_sheet(self) -> None:
        name = await self.app.push_screen_wait(PromptModal(f"New {self.noun}", placeholder="name"))
        if not name:
            return
        try:
            record = await self.api.create_record(self.model_id, {self.title_field: name, self.cells_field: {}})
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.reload(select=str(record["id"]))
        self._show(record)
        self.grid.focus()

    def act_rename(self) -> None:
        record = self.selected
        if record is not None:
            self.rename(record)

    @work(group="ui")
    async def rename(self, record: dict) -> None:
        name = await self.app.push_screen_wait(PromptModal("Rename", value=self.title_of(record), placeholder="name"))
        if not name or name == self.title_of(record):
            return
        try:
            renamed = await self.api.update_record(self.model_id, record["id"], {self.title_field: name})
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        if self.current_id == record["id"]:
            self.current_rev = renamed.get("rev")
            self.query_one("#cells-name", Static).update(f"[{SECOND}]{self.title_of(renamed)}[/]")
        self.reload(select=str(record["id"]))

    def act_delete_record(self) -> None:
        record = self.selected
        if record is not None:
            self.delete(record)

    @work(group="ui")
    async def delete(self, record: dict) -> None:
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(f"Delete {self.noun}?", detail=f"[b]{self.title_of(record)}[/]")
        )
        if not confirmed:
            return
        try:
            await self.api.delete_record(self.model_id, record["id"])
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        if self.current_id == record["id"]:
            self.forget_open()
        self.reload()
        self.status(f"Deleted {self.title_of(record)}")

    # -- the status line the workspace shows for this pane ---------------------------------
    def status_detail(self) -> str:
        if self.current_id is None:
            return f"[{MUTED}]{plural(len(self.records), self.noun)}[/]"
        state = "●  unsaved" if self.dirty else "✓  saved"
        filled = len(self.sheet.cells)
        return f"[{MUTED}]{state}  ·  {self.at_name}  ·  {filled} cell{'' if filled == 1 else 's'}[/]"
