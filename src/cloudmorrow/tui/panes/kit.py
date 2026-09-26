"""A Quill's screens in the terminal: one pane per screen, drawn from the kit.

A Quill never ships UI (docs/QUILLS.md). It declares screens — `board`,
`list`, `detail`, `form` — bound to the fields of its datamodels, and every
surface draws them. This is where the terminal does: `pane_for` takes one
screen of one installed Quill and returns the pane for its kit, and the
workspace gives it a tab after Notes.

Nothing here knows what any Quill is about. The pane reads its screen's
bindings and the datamodels the server sent beside them, and that is all a
task board has to go on as much as a list of car services does.

- `board` is in kit_board.py: lanes from an enum, cards you drag.
- `list` is a table of records by `title` (and `subtitle`), with a circle for
  the `tick` field that space fills in. With a `group` (and `subgroup`), or a
  `secret` field to keep hidden, it is kit_grouped.py's instead.
- `detail` and `form` are the same table without the circle: the record
  sheet is the point of them, and enter or a click opens it, showing the
  screen's `fields` when it names them.

Every one of them opens a record in the record sheet, where every field has
the widget its kind calls for.
"""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.coordinate import Coordinate
from textual.widgets import DataTable

from cloudmorrow.client.api import ApiError, AuthError
from cloudmorrow.tui.panes.base import Pane
from cloudmorrow.tui.screens.modals import ConfirmModal
from cloudmorrow.tui.screens.record_sheet import RecordSheet, link_choices, shown
from cloudmorrow.tui.theme import GOOD, MUTED
from cloudmorrow.tui.widgets.kit import field_label, field_of, title_of
from cloudmorrow.tui.widgets.toolbar import Action


def screen_key(quill: dict, screen: dict) -> str:
    """The name a Quill screen goes by in the workspace: `tab-<key>`, `pane-<key>`.

    A Quill with one screen is known by its own id, the way a built-in tab is
    known by its feature — so Tasks is `tab-tasks` whether it is a Quill or
    not. A Quill with several screens gets one key each.
    """
    screens = quill.get("screens") or []
    if len(screens) <= 1:
        return str(quill["id"])
    return f"{quill['id']}-{screen['id']}"


class KitPane(Pane):
    """What every kit pane has: its Quill, its screen, and its datamodel."""

    BINDINGS = [
        ("ctrl+n", "fire('new_record')", "New"),
        ("delete", "fire('delete_record')", "Delete"),
    ]

    def __init__(self, quill: dict, screen: dict, *, tab_key: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.quill = quill
        self.spec = screen
        self.models: dict = quill.get("models") or {}
        self.model_id: str = screen["model"]
        self.model: dict = self.models.get(self.model_id) or {"id": self.model_id, "fields": []}
        # Class attributes on a built-in pane; this pane's are its screen's.
        self.TAB_LABEL = str(screen.get("label") or quill.get("name") or quill["id"])
        self.TAB_KEY = tab_key
        self.SUMMARY = str(quill.get("summary") or "")
        self.records: list[dict] = []
        # Whether the records have been read once, so the card can count them.
        self.loaded = False

    @property
    def noun(self) -> str:
        """What one record is called: "task", "service visit"."""
        return str(self.model.get("label") or self.model_id).lower()

    def on_show(self) -> None:
        self.reload()

    async def signed_out(self, exc: Exception) -> bool:
        """An expired session sends you to sign in; anything else is said here."""
        if isinstance(exc, AuthError):
            await self.app.sign_out(message="Session expired — sign in again.")
            return True
        self.status(str(exc), error=True)
        return False

    async def open_sheet(
        self, record: dict | None = None, *, preset: dict | None = None
    ) -> dict | str | None:
        """The record sheet for *record*, or for a new one starting from *preset*.

        Called from a worker: it waits for the sheet to be answered.
        """
        choices = await link_choices(self.api, self.models, self.model)
        # A screen that names its fields shows those on the sheet, in that order.
        only = self.spec.get("fields") or None
        if record is not None and any(f.get("secret") for f in self.model.get("fields", [])):
            # A listing never carries a secret field; the record itself does.
            try:
                record = await self.api.record(self.model_id, record["id"])
            except ApiError as exc:
                await self.signed_out(exc)
                return None
        return await self.app.push_screen_wait(
            RecordSheet(
                self.api,
                self.models,
                self.model_id,
                record=record,
                preset=preset,
                only=only,
                choices=choices,
            )
        )

    async def confirm_delete(self, record: dict) -> bool:
        """Ask, then delete. True when it went."""
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(
                f"Delete {title_of(record, self.model)}?",
                detail="[dim]It is not recoverable.[/]",
            )
        )
        if not confirmed:
            return False
        try:
            await self.api.delete_record(self.model_id, record["id"])
        except ApiError as exc:
            await self.signed_out(exc)
            return False
        return True


class ListPane(KitPane):
    """`list`, `detail` and `form`: the records in a table, opened in the sheet."""

    BINDINGS = [
        *KitPane.BINDINGS,
        ("space", "fire('tick')", "Tick"),
    ]

    def __init__(self, quill: dict, screen: dict, **kwargs) -> None:
        super().__init__(quill, screen, **kwargs)
        # Only a `list` has a circle, and only when the field is a bool.
        tick = field_of(self.model, screen.get("tick")) if screen.get("kit") == "list" else None
        self.tick = tick if tick and tick.get("kind") == "bool" else None
        self.title_field = screen.get("title") or self.model.get("title") or "title"
        self.subtitle = field_of(self.model, screen.get("subtitle"))
        actions = [
            Action("new_record", f"New {self.noun}", "^n", variant="primary"),
            Action("open_record", "Open", "enter"),
        ]
        if self.tick:
            actions.append(Action("tick", field_label(self.tick), "space"))
        actions.append(Action("delete_record", "Delete", "del"))
        self.ACTIONS = tuple(actions)

    def content(self) -> ComposeResult:
        yield DataTable(id="kit-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        table = self.query_one("#kit-table", DataTable)
        columns = []
        if self.tick:
            columns.append(" ")
        title = field_of(self.model, self.title_field)
        columns.append(field_label(title).upper() if title else "")
        if self.subtitle:
            columns.append(field_label(self.subtitle).upper())
        table.add_columns(*columns)

    # -- loading -----------------------------------------------------------
    @work(exclusive=True, group="kit-list")
    async def reload(self) -> None:
        if self.api is None:
            return
        try:
            self.records = await self.api.records(self.model_id)
        except ApiError as exc:
            await self.signed_out(exc)
            return
        self.loaded = True
        self.draw()

    def draw(self, *, keep: str | None = None) -> None:
        table = self.query_one("#kit-table", DataTable)
        row = table.cursor_row
        table.clear()
        for record in self.records:
            table.add_row(*self._row(record), key=str(record["id"]))
        if keep is not None:
            row = next(
                (index for index, record in enumerate(self.records) if record["id"] == keep), row
            )
        if self.records:
            table.move_cursor(row=min(max(row, 0), len(self.records) - 1))
            table.call_after_refresh(self._settle_widths, table)
        self.status(
            "" if self.records else f"Nothing here yet — New {self.noun} starts one.", note=True
        )

    @staticmethod
    def _settle_widths(table: DataTable) -> None:
        """Draw the table again once its columns know how wide they are.

        A DataTable measures new rows when it is next idle, but a frame
        drawn before then is cached at the old widths — which, after a table
        that was empty, is the width of the header: "Middl". Writing one cell
        back as it was is the public way to make it draw afresh.
        """
        if table.row_count:
            table.update_cell_at(Coordinate(0, 0), table.get_cell_at(Coordinate(0, 0)),
                                 update_width=True)

    def _row(self, record: dict) -> tuple[str, ...]:
        fields = record.get("fields") or {}
        cells: list[str] = []
        if self.tick:
            cells.append(f"[{GOOD}]●[/]" if fields.get(self.tick["name"]) else f"[{MUTED}]○[/]")
        title = str(fields.get(self.title_field) or "")
        ticked = self.tick and fields.get(self.tick["name"])
        cells.append(f"[{MUTED} strike]{title}[/]" if ticked else f"[b]{title}[/]")
        if self.subtitle:
            cells.append(f"[{MUTED}]{shown(self.subtitle, fields.get(self.subtitle['name']))}[/]")
        return tuple(cells)

    def card_status(self) -> tuple[str, str] | None:
        if not self.loaded:
            return None
        if self.tick:
            name = self.tick["name"]
            waiting = sum(1 for r in self.records if not (r.get("fields") or {}).get(name))
            return ("news", f"{waiting} open") if waiting else ("ok", "all done")
        count = len(self.records)
        return "ok", f"{count} {self.noun}{'' if count == 1 else 's'}"

    def status_detail(self) -> str:
        count = len(self.records)
        return f"[{MUTED}]{count} {self.noun}{'' if count == 1 else 's'}[/]"

    @property
    def selected(self) -> dict | None:
        table = self.query_one("#kit-table", DataTable)
        if not self.records or not 0 <= table.cursor_row < len(self.records):
            return None
        return self.records[table.cursor_row]

    # -- actions -----------------------------------------------------------
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter on a row, or a click on it: the record sheet."""
        event.stop()
        self.act_open_record()

    def act_open_record(self) -> None:
        record = self.selected
        if record is None:
            return
        self.edit_record(record)

    @work(group="ui")
    async def edit_record(self, record: dict) -> None:
        result = await self.open_sheet(record)
        if result is None:
            return
        self.reload()
        if result == "deleted":
            self.status(f"Deleted {title_of(record, self.model)}.")

    def act_new_record(self) -> None:
        self.new_record()

    @work(group="ui")
    async def new_record(self) -> None:
        preset = {self.tick["name"]: False} if self.tick else None
        saved = await self.open_sheet(None, preset=preset)
        if not isinstance(saved, dict):
            return
        try:
            self.records = await self.api.records(self.model_id)
        except ApiError as exc:
            await self.signed_out(exc)
            return
        self.draw(keep=saved["id"])
        self.status(f"Added {title_of(saved, self.model)}.")

    def act_delete_record(self) -> None:
        record = self.selected
        if record is None:
            self.status(f"pick a {self.noun} first", error=True)
            return
        self.delete_record(record)

    @work(group="ui")
    async def delete_record(self, record: dict) -> None:
        if await self.confirm_delete(record):
            self.reload()

    def act_tick(self) -> None:
        record = self.selected
        if self.tick is None or record is None:
            return
        self.flip(record)

    @work(group="ui")
    async def flip(self, record: dict) -> None:
        """Space: the circle filled in, or emptied again."""
        name = self.tick["name"]
        value = not bool((record.get("fields") or {}).get(name))
        try:
            await self.api.update_record(
                self.model_id, record["id"], {name: value}, rev=record.get("rev")
            )
        except ApiError as exc:
            if exc.status_code == 409:
                self.status("That changed somewhere else — here it is as it is now.", error=True)
            else:
                await self.signed_out(exc)
            self.reload()
            return
        try:
            self.records = await self.api.records(self.model_id)
        except ApiError as exc:
            await self.signed_out(exc)
            return
        self.draw(keep=record["id"])


def pane_for(quill: dict, screen: dict, **kwargs) -> KitPane | None:
    """The pane for one screen of a Quill, or None for a kit not drawn here yet.

    `calendar`, `thread`, `grid` and `editor` come next (docs/QUILLS.md); a
    Quill that declares one simply has no tab for it in this version.
    """
    from cloudmorrow.tui.panes.kit_board import BoardPane
    from cloudmorrow.tui.panes.kit_grouped import GroupedListPane, draws_here

    kit = screen.get("kit")
    if screen.get("model") not in (quill.get("models") or {}):
        return None
    if kit == "board":
        return BoardPane(quill, screen, **kwargs)
    if kit == "list" and draws_here(quill["models"][screen["model"]], screen):
        return GroupedListPane(quill, screen, **kwargs)
    if kit in ("list", "detail", "form"):
        return ListPane(quill, screen, **kwargs)
    return None
