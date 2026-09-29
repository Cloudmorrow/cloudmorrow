"""A Quill's screens in the terminal: one pane per screen, drawn from the kit.

A Quill never ships UI (docs/QUILLS.md). It declares screens — `board`,
`list`, `detail`, `form`, `calendar` — bound to the fields of its datamodels, and every
surface draws them. This is where the terminal does: `pane_for` takes one
screen of one installed Quill and returns the pane for its kit, and the
workspace gives it a tab after Notes.

Nothing here knows what any Quill is about. The pane reads its screen's
bindings and the datamodels the server sent beside them, and that is all a
task board has to go on as much as a list of car services does.

- `board` is in kit_board.py: lanes from an enum, cards you drag.
- `calendar` is in kit_calendar.py: the spaces, a month, and the day's list;
  a space's people are widgets/kit_space.py.
- `editor` is in kit_editor.py: a tree of folders and pages beside the live
  Markdown editor.
- `grid` is in kit_grid.py: groups to pick from, then folders and files, as
  a table or as tiles, with the picture beside.
- `list` is a table of records by `title` (and `subtitle`), with a circle for
  the `tick` field that space fills in. With a `group` (and `subgroup`), or a
  `secret` field to keep hidden, it is kit_grouped.py's instead.
- `detail` and `form` are the same table without the circle: the record
  sheet is the point of them, and enter or a click opens it, showing the
  screen's `fields` when it names them.
- `thread` is in kit_thread.py: spaces on the left, what is said in the one
  you are on to the right, and a line to write in.
- `view` is not the kit's: the Quill's own code draws it, as a tree of
  primitives, and kit_view.py turns the tree into widgets.

Every one of them opens a record in the record sheet, where every field has
the widget its kind calls for.

What the person may do is the datamodels' to say (docs/CIRCLES.md): each
comes with their `access`, and on one they may only read, a pane is the same
screen without its writing. Its `WRITING` actions are refused — no button,
and the key does nothing — and so are those on a space or group datamodel
they may only read, which each pane refuses itself.
"""

from __future__ import annotations

from collections.abc import Callable

from textual import work
from textual.app import ComposeResult
from textual.widgets import DataTable

from cloudmorrow.client.api import ApiError, AuthError
from cloudmorrow.tui.kitdata import (
    CONFLICT,
    SESSION_EXPIRED,
    can_write,
    field_label,
    field_of,
    is_conflict,
    link_choices,
    link_rows,
    shown,
    title_of,
)
from cloudmorrow.tui.panes.base import Pane
from cloudmorrow.tui.quill_actions import run_action
from cloudmorrow.tui.screens.modals import ConfirmModal
from cloudmorrow.tui.screens.record_sheet import RecordSheet
from cloudmorrow.tui.theme import GOOD, MUTED
from cloudmorrow.tui.widgets.kit import settle_widths
from cloudmorrow.tui.widgets.toolbar import Action
from cloudmorrow.tui.words import plural


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
    # The actions that write the screen's own datamodel: not there for
    # somebody who may only read it.
    WRITING: frozenset[str] = frozenset({"new_record", "delete_record"})

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
        # Whether this person may write the screen's datamodel, and the
        # actions they may not take here, whichever datamodel says so.
        self.writes = can_write(self.model)
        self.refused: set[str] = set() if self.writes else set(self.WRITING)
        if not self.writes:
            self.SUMMARY = f"{self.SUMMARY} · read only" if self.SUMMARY else "read only"
        # What the records a link field points at are called, by field and id.
        self.link_titles: dict[str, dict[str, str]] = {}
        # The records links point at, by datamodel, as read since the pane
        # last loaded: the rows' titles, a level's values and a sheet's
        # drop-downs are one read of each, not one apiece.
        self.linked: dict[str, list[dict]] = {}

    def forget_links(self) -> None:
        """What links point at is read afresh: the pane is loading, or a sheet changed something."""
        self.linked.clear()

    async def load_link_titles(self, fields: list[dict | None]) -> None:
        """Read the titles for *fields* that are links, so a row says "Acme", not an id."""
        for field in fields:
            if not field or field.get("kind") != "link" or field.get("to") not in self.models:
                continue
            rows = await link_rows(self.api, field["to"], self.linked)
            if rows is None:
                continue
            target = self.models[field["to"]]
            self.link_titles[field["name"]] = {str(r["id"]): title_of(r, target) for r in rows}

    def say(self, field: dict, value) -> str:
        """A value as a row says it: a link by the title of what it points at."""
        if field.get("kind") == "link" and value:
            return self.link_titles.get(field["name"], {}).get(str(value), "—")
        return shown(field, value)

    @property
    def me(self) -> str:
        """Who is signed in: whose a space or a line is, said by name."""
        return getattr(self.app, "username", "") or ""

    @property
    def noun(self) -> str:
        """What one record is called: "task", "service visit"."""
        return str(self.model.get("label") or self.model_id).lower()

    # -- what this person may do -----------------------------------------------
    def offer(self, actions: list[Action]) -> tuple[Action, ...]:
        """The toolbar: *actions*, less the ones refused."""
        return tuple(action for action in actions if action.id not in self.refused)

    def fire(self, name: str) -> None:
        # A refused action does nothing, whether a button, a key or a message
        # from a widget asked for it.
        if name in self.refused:
            return
        super().fire(name)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """A refused action's key is not in the footer, and does nothing."""
        if action == "fire" and parameters and parameters[0] in self.refused:
            return False
        return True

    def on_show(self) -> None:
        self.reload()

    async def went_wrong(self, exc: ApiError, *, stale: bool = False) -> str:
        """Say what the server refused, each kind of refusal in its one way.

        An expired session sends you to sign in. Somebody else's change
        winning over a write that carried its revision — *stale* says it did
        — is said as that, the same everywhere; anything else is said in the
        server's own words. Which it was, "auth", "conflict" or "other", is
        for a caller that does more about one of them: draws again after a
        conflict, and does nothing at all once signed out.
        """
        if isinstance(exc, AuthError):
            await self.app.sign_out(message=SESSION_EXPIRED)
            return "auth"
        if is_conflict(exc, stale=stale):
            self.status(CONFLICT, error=True)
            return "conflict"
        self.status(str(exc), error=True)
        return "other"

    # What this kit knows about its screen's records that the datamodel does
    # not, as a sheet's `adjust`: given the fields about to be sent and the
    # record as it was, what to send instead. None when it knows nothing more.
    settle: Callable[[dict, dict | None], dict] | None = None

    async def open_sheet(
        self,
        record: dict | None = None,
        *,
        preset: dict | None = None,
        model_id: str = "",
        models: dict | None = None,
        only: list[str] | None = None,
        adjust: Callable[[dict, dict | None], dict] | None = None,
    ) -> dict | str | None:
        """The record sheet for *record*, or for a new one starting from *preset*.

        Of the screen's own datamodel unless *model_id* says another — a
        board's groups, a calendar's spaces. On its own, the screen's
        `fields` are what the sheet shows and `settle` has its say in what is
        sent; *only* and *adjust* say those for another. *models* stands in
        for the Quill's when the pane draws a datamodel its own way: the
        calendar's colour as the five there are.

        Every sheet a kit pane opens comes through here, so each has its
        links' drop-downs filled, its secrets read, and a Quill's actions.
        Called from a worker: it waits for the sheet to be answered.
        """
        model_id = model_id or self.model_id
        models = models if models is not None else self.models
        model = models[model_id]
        if model_id == self.model_id:
            # A screen that names its fields shows those on the sheet, in that order.
            only = only or self.spec.get("fields") or None
            adjust = adjust or self.settle
        choices = await link_choices(self.api, models, model, cache=self.linked)
        if record is not None and any(f.get("secret") for f in model.get("fields", [])):
            # A listing never carries a secret field; the record itself does.
            try:
                record = await self.api.record(model_id, record["id"])
            except ApiError as exc:
                await self.went_wrong(exc)
                return None
        result = await self.app.push_screen_wait(
            RecordSheet(
                self.api,
                models,
                model_id,
                record=record,
                preset=preset,
                only=only,
                choices=choices,
                adjust=adjust,
                run_action=run_action,
            )
        )
        if result is not None:
            # Saved, deleted or acted on: what a link may point at may be different now.
            self.forget_links()
        return result

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
            await self.went_wrong(exc)
            return False
        return True


class ListPane(KitPane):
    """`list`, `detail` and `form`: the records in a table, opened in the sheet."""

    BINDINGS = [
        *KitPane.BINDINGS,
        ("space", "fire('tick')", "Tick"),
    ]
    WRITING = KitPane.WRITING | {"tick"}

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
        self.ACTIONS = self.offer(actions)

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
        if not await self._fetch():
            return
        self.loaded = True
        self.draw()

    async def _fetch(self) -> bool:
        """The records again, and what their links are called. False when it failed."""
        self.forget_links()
        try:
            self.records = await self.api.records(self.model_id)
            await self.load_link_titles([self.subtitle])
        except ApiError as exc:
            await self.went_wrong(exc)
            return False
        return True

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
            table.call_after_refresh(settle_widths, table)
        empty = "Nothing here."
        if self.writes:
            empty = f"Nothing here yet — New {self.noun} starts one."

        self.status("" if self.records else empty, note=True)

    def _row(self, record: dict) -> tuple[str, ...]:
        fields = record.get("fields") or {}
        cells: list[str] = []
        if self.tick:
            cells.append(f"[{GOOD}]●[/]" if fields.get(self.tick["name"]) else f"[{MUTED}]○[/]")
        title = str(fields.get(self.title_field) or "")
        ticked = self.tick and fields.get(self.tick["name"])
        cells.append(f"[{MUTED} strike]{title}[/]" if ticked else f"[b]{title}[/]")
        if self.subtitle:
            cells.append(f"[{MUTED}]{self.say(self.subtitle, fields.get(self.subtitle['name']))}[/]")
        return tuple(cells)

    def card_status(self) -> tuple[str, str] | None:
        if not self.loaded:
            return None
        if self.tick:
            name = self.tick["name"]
            waiting = sum(1 for r in self.records if not (r.get("fields") or {}).get(name))
            return ("news", f"{waiting} open") if waiting else ("ok", "all done")
        count = len(self.records)
        return "ok", plural(count, self.noun)

    def status_detail(self) -> str:
        count = len(self.records)
        return f"[{MUTED}]{plural(count, self.noun)}[/]"

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
        if not isinstance(saved, dict) or not await self._fetch():
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
            if await self.went_wrong(exc, stale=True) != "auth":
                self.reload()
            return
        if await self._fetch():
            self.draw(keep=record["id"])


def pane_for(quill: dict, screen: dict, **kwargs) -> KitPane | None:
    """The pane for one screen of a Quill, or None for a kit not drawn here yet.

    Every element in the kit is drawn here now. Each that is more than a
    table is a file of its own: panes/kit_<kit>.py.
    """
    from cloudmorrow.tui.panes.kit_board import BoardPane
    from cloudmorrow.tui.panes.kit_calendar import CalendarPane
    from cloudmorrow.tui.panes.kit_editor import EditorPane
    from cloudmorrow.tui.panes.kit_grid import GridPane
    from cloudmorrow.tui.panes.kit_grouped import GroupedListPane, draws_here
    from cloudmorrow.tui.panes.kit_thread import ThreadPane
    from cloudmorrow.tui.panes.kit_view import ViewPane

    kit = screen.get("kit")
    if kit == "view":
        # About no datamodel, or one the server kept it for (docs/CIRCLES.md).
        return ViewPane(quill, screen, **kwargs)
    if screen.get("model") not in (quill.get("models") or {}):
        return None
    if kit == "board":
        return BoardPane(quill, screen, **kwargs)
    if kit == "calendar":
        return CalendarPane(quill, screen, **kwargs)
    if kit == "editor":
        return EditorPane(quill, screen, **kwargs)
    if kit == "list" and draws_here(quill["models"][screen["model"]], screen):
        return GroupedListPane(quill, screen, **kwargs)
    if kit == "grid":
        return GridPane(quill, screen, **kwargs)
    if kit in ("list", "detail", "form"):
        return ListPane(quill, screen, **kwargs)
    if kit == "thread":
        return ThreadPane(quill, screen, **kwargs)
    return None
