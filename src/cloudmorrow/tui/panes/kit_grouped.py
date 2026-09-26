"""A `list` picked through, in the terminal: groups down the left, a subgroup bar, the rows.

The kit's list (panes/kit.py) with a `group` and perhaps a `subgroup` bound
(docs/QUILLS.md). Laid out as notes are: the group's values in a list you
pick from on the left, and beside it the subgroup's values as a row of
buttons, and under them the records in both. A new record goes into the
group and subgroup on screen.

The values of a level are the records a link field points at, an enum's
values, or — for an indexed string — the values the records have, with a
way to name a new one (`n` in the list, `e` for the subgroup). A value just
named is a row before anything is in it, or there would be nowhere to put
the first record.

A field the datamodel marks `secret` is never in a listing — the server
sends null — so its column says there is something there, in dots, until
`v` fetches that one record and shows it; `v` again hides it. `c` copies it
without showing it. The record sheet draws it as a password box.

Nothing here knows what it is drawing: a Secrets vault and environment are
a group and a subgroup, as a customer and a project would be.
"""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Static

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.panes.kit import KitPane, ListPane
from cloudmorrow.tui.screens.modals import PromptModal
from cloudmorrow.tui.screens.record_sheet import shown
from cloudmorrow.tui.theme import MUTED
from cloudmorrow.tui.widgets.group_list import GroupList
from cloudmorrow.tui.widgets.kit import field_label, field_of, safe_id, title_of
from cloudmorrow.tui.widgets.toolbar import Action

MASK = "••••••••"


def draws_here(model: dict, screen: dict) -> bool:
    """A list screen this pane draws rather than the plain one: grouped, or hiding a field."""
    subtitle = field_of(model, screen.get("subtitle"))
    return bool(screen.get("group") or (subtitle and subtitle.get("secret")))


class SubgroupBar(Horizontal):
    """The subgroup's values, as buttons. Clicking one stands on it."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.add_class("kit-subgroup-bar")
        self.values: dict[str, str] = {}

    async def show(self, choices: list[tuple[str, str, int]], current: str | None, noun: str) -> None:
        # Awaited: removal is scheduled, and remounting the same ids before it
        # lands is a duplicate-id error.
        await self.remove_children()
        self.values = {}
        for value, label, count in choices:
            wid = f"sub-{safe_id(value)}"
            self.values[wid] = value
            button = Button(
                f"{label}  {count}" if count else label,
                id=wid,
                compact=True,
                variant="primary" if value == current else "default",
            )
            button.tooltip = f"{count} in {label}"
            await self.mount(button)
        add = Button("＋", id="sub-new", compact=True)
        add.tooltip = f"Another {noun}"
        await self.mount(add)


class GroupedListPane(ListPane):
    """`list` with a group (and a subgroup), or with a secret field, opened in the sheet."""

    BINDINGS = [
        *KitPane.BINDINGS,
        ("v", "fire('reveal')", "Reveal"),
        ("c", "fire('copy')", "Copy"),
        ("e", "fire('new_subgroup')", "New subgroup"),
        ("r", "fire('refresh')", "Refresh"),
    ]

    def __init__(self, quill: dict, screen: dict, **kwargs) -> None:
        super().__init__(quill, screen, **kwargs)
        self.levels: list[dict] = [
            f for f in (field_of(self.model, screen.get(n)) for n in ("group", "subgroup")) if f
        ]
        self.hidden = self.subtitle if self.subtitle and self.subtitle.get("secret") else None
        self.all: list[dict] = []
        self.chosen: list[str | None] = [None] * len(self.levels)
        self.offered: list[list[tuple[str, str, int]]] = [[] for _ in self.levels]
        # Values fetched by `v`, by record id, while this pane is up.
        self.revealed: dict[str, str] = {}
        actions = [Action("new_record", f"New {self.noun}", "^n", variant="primary")]
        actions.append(Action("open_record", "Open", "enter"))
        if self.hidden:
            label = field_label(self.hidden).lower()
            actions.append(Action("reveal", "Reveal", "v", hint=f"Show the {label}, or hide it again"))
            actions.append(Action("copy", "Copy", "c", hint=f"Copy the {label} without showing it"))
        if self.tick:
            actions.append(Action("tick", field_label(self.tick), "space"))
        actions.append(Action("delete_record", "Delete", "del", variant="error"))
        self.ACTIONS = tuple(actions)

    def content(self) -> ComposeResult:
        with Horizontal(classes="kit-grouped"):
            if self.levels:
                yield GroupList(id="kit-group-list", classes="kit-group-list")
            with Vertical(classes="kit-group-side"):
                if self.levels:
                    yield Static("", id="kit-group-name", classes="kit-group-name")
                if len(self.levels) > 1:
                    yield SubgroupBar(id="kit-subgroup-bar")
                with Vertical(classes="kit-group-rows"):
                    yield DataTable(id="kit-table", cursor_type="row", zebra_stripes=True)
                    yield Static("", id="kit-group-empty", classes="kit-group-empty")

    def on_mount(self, event) -> None:
        # The plain list's columns are not these: its handler is not run too.
        event.prevent_default()
        table = self.query_one("#kit-table", DataTable)
        columns = [" "] if self.tick else []
        title = field_of(self.model, self.title_field)
        columns.append(field_label(title).upper() if title else "")
        if self.subtitle:
            columns.append(field_label(self.subtitle).upper())
        columns.append("UPDATED")
        table.add_columns(*columns)

    def on_show(self) -> None:
        self.reload()
        # Focus lands in the pane so its keys are in the footer before you
        # touch anything, unless you are already working inside it.
        focused = self.screen.focused
        if focused is None or self not in focused.ancestors:
            target = self.query("#kit-group-list") or self.query("#kit-table")
            target.first().focus()

    # -- the levels ----------------------------------------------------------
    async def _choices(self, field: dict, records: list[dict]) -> list[tuple[str, str]]:
        if field.get("kind") == "link":
            target = self.models.get(field.get("to")) or {}
            try:
                rows = await self.api.records(field["to"])
            except ApiError:
                rows = []
            return [(str(r["id"]), title_of(r, target)) for r in rows]
        if field.get("kind") == "enum":
            labels = field.get("labels") or field.get("values") or []
            return list(zip(field.get("values") or [], labels, strict=False))
        seen = {r["fields"].get(field["name"]) for r in records}
        return [(str(v), str(v)) for v in sorted(v for v in seen if v not in (None, ""))]

    async def _place(self) -> None:
        """Work out each level's choices and where it stands, then draw it all."""
        inside = self.all
        for index, field in enumerate(self.levels):
            choices = await self._choices(field, inside)
            values = [value for value, _ in choices]
            current = self.chosen[index]
            # Where it stood stays where it stands, even emptied or just named.
            if current is None:
                default = field.get("default")
                current = (
                    str(default) if default is not None and str(default) in values
                    else values[0] if values else (str(default) if default is not None else None)
                )
            if current is not None and current not in values:
                choices.append((current, current))
            self.chosen[index] = current
            counted = [
                (value, label, sum(1 for r in inside if str(r["fields"].get(field["name"])) == value))
                for value, label in choices
            ]
            self.offered[index] = counted
            inside = [r for r in inside if current is None or str(r["fields"].get(field["name"])) == current]
        self.records = inside
        await self._draw_levels()
        self.draw()

    async def _draw_levels(self) -> None:
        if not self.levels:
            return
        self.query_one(GroupList).show(self.offered[0], self.chosen[0])
        names = [self._label_of(i) for i in range(len(self.levels)) if self.chosen[i] is not None]
        self.query_one("#kit-group-name", Static).update(f"[b]{' · '.join(names)}[/]")
        if len(self.levels) > 1:
            await self.query_one(SubgroupBar).show(
                self.offered[1], self.chosen[1], field_label(self.levels[1]).lower()
            )

    def _label_of(self, index: int) -> str:
        value = self.chosen[index]
        return next((label for v, label, _ in self.offered[index] if v == value), str(value))

    # -- loading -----------------------------------------------------------
    @work(exclusive=True, group="kit-list")
    async def reload(self, message: str = "", keep: str | None = None) -> None:
        if self.api is None:
            return
        try:
            self.all = await self.api.records(self.model_id)
        except ApiError as exc:
            await self.signed_out(exc)
            return
        self.loaded = True
        if keep is not None:
            # Stand where the record just saved is, whatever it was named as.
            record = next((r for r in self.all if r["id"] == keep), None)
            if record is not None:
                self.chosen = [str(record["fields"].get(f["name"])) for f in self.levels]
        await self._place()
        if keep is not None:
            self.draw(keep=keep)
        if message:
            self.status(message)

    def draw(self, *, keep: str | None = None) -> None:
        super().draw(keep=keep)
        empty = self.query_one("#kit-group-empty", Static)
        table = self.query_one("#kit-table", DataTable)
        table.display = bool(self.records)
        empty.display = not self.records
        if not self.records:
            where = " · ".join(self._label_of(i) for i in range(len(self.levels)) if self.chosen[i])
            place = f" in [/][b]{where}[/][{MUTED}]" if where else ""
            empty.update(f"[{MUTED}]Nothing{place} yet. New {self.noun} (^n) starts one here.[/]")
            self.status("")

    def _row(self, record: dict) -> tuple[str, ...]:
        cells = list(super()._row(record))
        if self.hidden:
            value = self.revealed.get(record["id"])
            cells[-1] = f"[{MUTED}]{MASK}[/]" if value is None else (value or f"[{MUTED}](empty)[/]")
        stamp = str(record.get("updated_at") or "")
        cells.append(f"[{MUTED}]{shown({'kind': 'datetime'}, stamp) if stamp else ''}[/]")
        return tuple(cells)

    def card_status(self) -> tuple[str, str] | None:
        if not self.loaded:
            return None
        count = len(self.all)
        said = f"{count} {self.noun}{'' if count == 1 else 's'}"
        if self.levels:
            groups = len([g for g in self.offered[0] if g[2]])
            noun = field_label(self.levels[0]).lower()
            said = f"{groups} {noun}{'' if groups == 1 else 's'}, {said}"
        return "ok", said

    # -- picking -------------------------------------------------------------
    def on_group_list_chosen(self, event: GroupList.Chosen) -> None:
        event.stop()
        if event.value != self.chosen[0]:
            self.stand(0, event.value)

    def on_group_list_new_requested(self, _: GroupList.NewRequested) -> None:
        self.name_value(0)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        wid = event.button.id or ""
        if not wid.startswith("sub-"):
            return
        event.stop()
        if wid == "sub-new":
            self.name_value(1)
            return
        bar = self.query_one(SubgroupBar)
        if wid in bar.values:
            self.stand(1, bar.values[wid])

    @work(exclusive=True, group="kit-list")
    async def stand(self, index: int, value: str) -> None:
        """Stand on another value of a level; the levels under it start again."""
        self.chosen[index] = value
        for below in range(index + 1, len(self.levels)):
            self.chosen[below] = None
        # What was on screen belongs to where it was revealed.
        self.revealed.clear()
        await self._place()

    def act_new_group(self) -> None:
        self.name_value(0)

    def act_new_subgroup(self) -> None:
        if len(self.levels) > 1:
            self.name_value(1)

    @work(group="ui")
    async def name_value(self, index: int) -> None:
        if index >= len(self.levels):
            return
        field = self.levels[index]
        noun = field_label(field).lower()
        if field.get("kind") == "enum":
            self.status(f"a {noun} is one of the ones there are", error=True)
            return
        text = await self.app.push_screen_wait(
            PromptModal(
                f"New {noun}",
                placeholder=str(field.get("default") or ""),
                detail=f"[dim]A {noun} is there once something is in it: add one next.[/]",
            )
        )
        text = (text or "").strip()
        if not text:
            return
        value = text
        if field.get("kind") == "link":
            target = self.models.get(field["to"]) or {}
            try:
                made = await self.api.create_record(field["to"], {target.get("title", "title"): text})
            except ApiError as exc:
                await self.signed_out(exc)
                return
            value = str(made["id"])
        self.stand(index, value)

    # -- the records -----------------------------------------------------------
    @work(group="ui")
    async def new_record(self) -> None:
        preset = {f["name"]: v for f, v in zip(self.levels, self.chosen, strict=False) if v is not None}
        if self.tick:
            preset[self.tick["name"]] = False
        saved = await self.open_sheet(None, preset=preset)
        if not isinstance(saved, dict):
            return
        self.reload(f"Added {title_of(saved, self.model)}.", keep=saved["id"])

    @work(group="ui")
    async def edit_record(self, record: dict) -> None:
        result = await self.open_sheet(record)
        if result is None:
            return
        if result == "deleted":
            self.revealed.pop(record["id"], None)
            self.reload(f"Deleted {title_of(record, self.model)}.")
            return
        self.revealed.pop(record["id"], None)
        self.reload(keep=result["id"] if isinstance(result, dict) else None)

    @work(group="ui")
    async def delete_record(self, record: dict) -> None:
        if await self.confirm_delete(record):
            self.revealed.pop(record["id"], None)
            self.reload(f"Deleted {title_of(record, self.model)}.")

    def act_refresh(self) -> None:
        self.reload()

    def act_reveal(self) -> None:
        self.reveal()

    @work(group="ui")
    async def reveal(self) -> None:
        record = self.selected
        if record is None or self.hidden is None:
            return
        name = title_of(record, self.model)
        if record["id"] in self.revealed:
            del self.revealed[record["id"]]
            self.draw(keep=record["id"])
            return
        value = await self._value_of(record)
        if value is None:
            return
        self.revealed[record["id"]] = value
        self.draw(keep=record["id"])
        self.status(f"{name} is on screen — reveal again to hide it.")

    def act_copy(self) -> None:
        self.copy_value()

    @work(group="ui")
    async def copy_value(self) -> None:
        record = self.selected
        if record is None or self.hidden is None:
            return
        value = self.revealed.get(record["id"])
        if value is None:
            value = await self._value_of(record)
        if value is None:
            return
        # Textual copies via OSC 52, so this works over SSH in most terminals.
        self.app.copy_to_clipboard(value)
        self.status(f"Copied {title_of(record, self.model)} to the clipboard.")

    async def _value_of(self, record: dict) -> str | None:
        """The hidden field of one record: asked for, one record at a time."""
        try:
            full = await self.api.record(self.model_id, record["id"])
        except ApiError as exc:
            await self.signed_out(exc)
            return None
        return str((full.get("fields") or {}).get(self.hidden["name"]) or "")
