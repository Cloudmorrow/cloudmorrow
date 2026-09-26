"""The kit's `board`: pick a group from the strip, and work the lanes across it.

The screen names an enum field as its `lane`, and each of the enum's values
is a column, left to right in the order declared — the direction work
travels. A `group` (a link field) puts a strip of tabs above the board, one
per record of the linked datamodel, with a `＋` at the end that makes
another: which ones you have is visible at a glance rather than one click
down, and switching between them is one click rather than two. The server
seeds the first one, so there is always a group to stand on.

New records start in the first lane of the group you are on. The `done`
lane is where space sends a card; when the Quill has an expire job on the
datamodel, the lane says how long it keeps things, and every card the job
will take says how long it has left.

Tasks is the first board — task, lane, board — but nothing below says so:
all of it is read from the screen's bindings and the datamodels.
"""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Tab, Tabs

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.panes.kit import KitPane
from cloudmorrow.tui.screens.modals import ConfirmModal, PromptModal
from cloudmorrow.tui.screens.record_sheet import RecordSheet, link_choices
from cloudmorrow.tui.theme import MUTED
from cloudmorrow.tui.widgets.kit import (
    Lane,
    RecordCard,
    enum_options,
    field_of,
    how_long,
    lane_under,
    neighbour_lane,
    safe_id,
    title_of,
)
from cloudmorrow.tui.widgets.toolbar import Action

# A group's tab is `group-<record id>`. Record ids are `r_…`, so `new` can
# never be one, and the ＋ tab has it to itself.
TAB_PREFIX = "group-"
NEW_GROUP_TAB = "group-new"


def group_tab_id(record_id: str) -> str:
    return f"{TAB_PREFIX}{safe_id(record_id)}"


class BoardPane(KitPane):
    """The board, the strip of groups above it, and everything you can do to a card."""

    BINDINGS = [
        *KitPane.BINDINGS,
        ("ctrl+b", "fire('new_group')", "New group"),
    ]

    def __init__(self, quill: dict, screen: dict, **kwargs) -> None:
        super().__init__(quill, screen, **kwargs)
        lane = field_of(self.model, screen.get("lane")) or {"name": "lane", "values": []}
        self.lane_field: str = lane["name"]
        self.lanes: list[tuple[str, str]] = enum_options(lane)
        self.lane_values = [value for value, _ in self.lanes]
        self.title_field: str = screen.get("title") or self.model.get("title") or "title"
        body = field_of(self.model, screen.get("body"))
        self.body_field: str | None = body["name"] if body else None
        done = screen.get("done")
        self.done: str | None = done if done in self.lane_values else None
        group = field_of(self.model, screen.get("group"))
        self.group_field: str | None = group["name"] if group and group.get("to") else None
        self.group_model_id: str | None = group["to"] if self.group_field else None
        self.group_model: dict = self.models.get(self.group_model_id or "") or {}
        self.groups: list[dict] = []
        self.group: str | None = None
        # What the strip is showing, so it is only rebuilt when it is wrong.
        self._drawn: list[tuple[str, str]] = []
        first = self.lanes[0][1] if self.lanes else "the first lane"
        actions = [
            Action("new_record", f"New {self.noun}", "^n", variant="primary",
                   hint=f"Starts in {first}"),
        ]
        if self.group_field:
            group_noun = self.group_noun
            actions += [
                Action("new_group", f"New {group_noun}", "^b"),
                Action("rename_group", f"Rename {group_noun}"),
                Action("delete_group", f"Delete {group_noun}",
                       hint=f"The {group_noun} and every {self.noun} on it"),
            ]
        self.ACTIONS = tuple(actions)

    @property
    def group_noun(self) -> str:
        return str(self.group_model.get("label") or self.group_model_id or "group").lower()

    def _lane_note(self, value: str) -> str:
        """What the done lane says about itself: how long it keeps things."""
        if value != self.done:
            return ""
        for job in self.quill.get("jobs") or []:
            if job.get("action") == "expire" and job.get("model") == self.model_id:
                return f"kept {how_long(str(job.get('after', '')))}"
        return ""

    # -- layout ------------------------------------------------------------
    def content(self) -> ComposeResult:
        if self.group_field:
            with Horizontal(id="board-bar"):
                yield Tabs(id="board-nav")
        with Horizontal(id="lanes"):
            for value, label in self.lanes:
                yield Lane(
                    value, label, note=self._lane_note(value),
                    id=f"lane-{safe_id(value)}", classes="lane",
                )

    def lane_widget(self, value: str) -> Lane:
        return self.query_one(f"#lane-{safe_id(value)}", Lane)

    # -- loading -----------------------------------------------------------
    @work(exclusive=True, group="kit-board")
    async def reload(self) -> None:
        if self.api is None:
            return
        if self.group_field:
            try:
                self.groups = await self.api.records(self.group_model_id)
            except ApiError as exc:
                await self.signed_out(exc)
                return
            ids = {row["id"] for row in self.groups}
            if self.group not in ids:
                # The group went, or there was never one selected.
                self.group = self.groups[0]["id"] if self.groups else None
            await self.draw_strip()
        await self.load_records()

    async def draw_strip(self) -> None:
        """One tab per group, then the ＋ that makes another.

        Rebuilding a Tabs activates whichever tab lands first, and moving the
        active one activates that — both of which would read as you choosing a
        group. Neither is, so the strip is redrawn with those muted and the
        loading is done here, in the order this method decides.
        """
        strip = self.query_one("#board-nav", Tabs)
        wanted = [(row["id"], title_of(row, self.group_model)) for row in self.groups]
        with self.prevent(Tabs.TabActivated, Tabs.Cleared):
            if wanted != self._drawn:
                await strip.clear()
                for record_id, title in wanted:
                    await strip.add_tab(Tab(title, id=group_tab_id(record_id)))
                await strip.add_tab(Tab("＋", id=NEW_GROUP_TAB))
                self._drawn = wanted
            if self.group is not None:
                strip.active = group_tab_id(self.group)

    def _restore_strip(self) -> None:
        """Put the highlight back on the group you are actually looking at."""
        strip = self.query_one("#board-nav", Tabs)
        with self.prevent(Tabs.TabActivated, Tabs.Cleared):
            strip.active = group_tab_id(self.group) if self.group else ""

    async def load_records(self) -> None:
        """Fill the lanes from the selected group, or empty them when there is none."""
        if self.group_field and self.group is None:
            self.records = []
            await self.draw_lanes()
            self.status(f"No {self.group_noun} yet — New {self.group_noun} starts one.", note=True)
            return
        where = {self.group_field: self.group} if self.group_field else {}
        try:
            self.records = await self.api.records(self.model_id, **where)
        except ApiError as exc:
            await self.signed_out(exc)
            return
        self.loaded = True
        await self.draw_lanes()
        self.status("")

    def card_status(self) -> tuple[str, str] | None:
        """How many are in the first lane: "3 to do"."""
        if not self.loaded or not self.lanes:
            return None
        value, label = self.lanes[0]
        count = sum(1 for row in self.records if self._lane_of(row) == value)
        if not count:
            return "ok", f"nothing in {label}"
        return "news", f"{count} {label.lower()}"

    async def draw_lanes(self) -> None:
        for value in self.lane_values:
            await self.lane_widget(value).show(
                [row for row in self.records if self._lane_of(row) == value],
                title=self.title_field,
                body=self.body_field,
            )

    def _lane_of(self, record: dict) -> str:
        value = (record.get("fields") or {}).get(self.lane_field)
        # A record with no lane, or one the enum no longer has, is in the first.
        return value if value in self.lane_values else (self.lane_values or [""])[0]

    def status_detail(self) -> str:
        if self.group_field and self.group is None:
            return ""
        counts = "  ".join(
            f"{label} {sum(1 for row in self.records if self._lane_of(row) == value)}"
            for value, label in self.lanes
        )
        return f"[{MUTED}]{counts}[/]"

    # -- the strip ---------------------------------------------------------
    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        """Handled here so it never reaches the workspace's own tab strip."""
        event.stop()
        tab_id = (event.tab.id or "") if event.tab is not None else ""
        if tab_id == NEW_GROUP_TAB:
            # ＋ is a button wearing a tab's clothes: the strip goes back where
            # it was, and the new group — if there is one — selects itself.
            self._restore_strip()
            self.new_group()
            return
        if not tab_id.startswith(TAB_PREFIX):
            return
        chosen = next((row["id"] for row in self.groups if group_tab_id(row["id"]) == tab_id), None)
        if chosen is None or chosen == self.group:
            return
        self.group = chosen
        self.open_group()

    @work(group="ui")
    async def open_group(self) -> None:
        await self.load_records()

    def _current_group(self) -> dict | None:
        return next((row for row in self.groups if row["id"] == self.group), None)

    # -- groups ------------------------------------------------------------
    def _group_is_just_a_name(self) -> bool:
        """Whether a new group is a name and nothing else, so a prompt will do."""
        title = self.group_model.get("title")
        return all(
            f["name"] == title or not f.get("required") or f.get("default") is not None
            for f in self.group_model.get("fields", [])
        )

    def act_new_group(self) -> None:
        self.new_group()

    @work(group="ui")
    async def new_group(self) -> None:
        if not self.group_field:
            return
        if self._group_is_just_a_name():
            title = await self.app.push_screen_wait(
                PromptModal(
                    f"New {self.group_noun}",
                    detail=f"[dim]The same lanes on every {self.group_noun}. They are yours.[/]",
                )
            )
            if not title:
                # Nothing made; the strip was already put back before the prompt.
                return
            try:
                made = await self.api.create_record(
                    self.group_model_id, {self.group_model.get("title") or "title": title}
                )
            except ApiError as exc:
                await self.signed_out(exc)
                return
        else:
            choices = await link_choices(self.api, self.models, self.group_model)
            made = await self.app.push_screen_wait(
                RecordSheet(self.api, self.models, self.group_model_id, choices=choices)
            )
            if not isinstance(made, dict):
                return
        self.group = made["id"]
        self.reload()

    def act_rename_group(self) -> None:
        self.rename_group()

    @work(group="ui")
    async def rename_group(self) -> None:
        current = self._current_group()
        if current is None:
            self.status(f"no {self.group_noun} selected", error=True)
            return
        title_field = self.group_model.get("title") or "title"
        title = await self.app.push_screen_wait(
            PromptModal(
                f"Rename {self.group_noun}",
                value=str((current.get("fields") or {}).get(title_field) or ""),
            )
        )
        if not title:
            return
        try:
            await self.api.update_record(
                self.group_model_id, current["id"], {title_field: title}, rev=current.get("rev")
            )
        except ApiError as exc:
            if exc.status_code == 409:
                self.status(f"That {self.group_noun} changed somewhere else — try again.",
                            error=True)
                self.reload()
                return
            await self.signed_out(exc)
            return
        self.reload()

    def act_delete_group(self) -> None:
        self.delete_group()

    @work(group="ui")
    async def delete_group(self) -> None:
        current = self._current_group()
        if current is None:
            self.status(f"no {self.group_noun} selected", error=True)
            return
        count = len(self.records)
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(
                f"Delete the {self.group_noun} {title_of(current, self.group_model)}?",
                detail=(
                    f"[dim]Every {self.noun} on it goes too — "
                    f"{count} of them. Nothing else is touched.[/]"
                ),
            )
        )
        if not confirmed:
            return
        try:
            await self.api.delete_record(self.group_model_id, current["id"])
        except ApiError as exc:
            await self.signed_out(exc)
            return
        self.group = None
        self.reload()

    # -- records -----------------------------------------------------------
    def act_new_record(self) -> None:
        self.new_record()

    @work(group="ui")
    async def new_record(self) -> None:
        if self.group_field and self.group is None:
            self.status(f"make a {self.group_noun} first", error=True)
            return
        preset: dict = {}
        if self.group_field:
            preset[self.group_field] = self.group
        if self.lane_values:
            preset[self.lane_field] = self.lane_values[0]
        saved = await self.open_sheet(None, preset=preset)
        if not isinstance(saved, dict):
            return
        await self.load_records()
        lane = dict(self.lanes).get(self._lane_of(saved), "")
        self.status(f"added to {lane}" if lane else "added")

    def on_record_card_opened(self, event: RecordCard.Opened) -> None:
        event.stop()
        self.edit_record(event.record)

    @work(group="ui")
    async def edit_record(self, record: dict) -> None:
        result = await self.open_sheet(record)
        if result is None:
            return
        await self.load_records()
        if isinstance(result, dict):
            self._refocus(result["id"])

    def act_delete_record(self) -> None:
        card = self._focused_card()
        if card is None:
            self.status(f"pick a {self.noun} first — click one, or tab to it", error=True)
            return
        self.delete_record(card.record)

    @work(group="ui")
    async def delete_record(self, record: dict) -> None:
        if await self.confirm_delete(record):
            await self.load_records()

    def _focused_card(self) -> RecordCard | None:
        focused = self.screen.focused
        return focused if isinstance(focused, RecordCard) else None

    # -- moving ------------------------------------------------------------
    def on_record_card_dragging(self, event: RecordCard.Dragging) -> None:
        """Light up the lane the card would land in, so a drop is not a guess."""
        event.stop()
        target = lane_under(self.screen, event.x, event.y)
        for value in self.lane_values:
            self.lane_widget(value).set_class(
                target is not None and target.value == value, "-drop-target"
            )

    def on_record_card_dropped(self, event: RecordCard.Dropped) -> None:
        event.stop()
        for value in self.lane_values:
            self.lane_widget(value).remove_class("-drop-target")
        target = lane_under(self.screen, event.x, event.y)
        if target is None or target not in self.query(Lane):
            # Dropped off the board. The card stays where it was.
            return
        index = target.index_at(event.y)
        if target.value == self._lane_of(event.record) and index == self._position_of(event.record):
            return
        self.move_record(event.record, target.value, index)

    def on_record_card_shifted(self, event: RecordCard.Shifted) -> None:
        """`[` and `]`: the same move, for when the mouse is not where you are."""
        event.stop()
        current = self._lane_of(event.record)
        lane = neighbour_lane(self.lane_values, current, event.delta)
        if lane == current:
            return
        self.move_record(event.record, lane, None)

    def on_record_card_ticked(self, event: RecordCard.Ticked) -> None:
        """Space: to the done lane, and from it back to the first."""
        event.stop()
        if self.done is None:
            return
        current = self._lane_of(event.record)
        lane = self.lane_values[0] if current == self.done else self.done
        if lane != current:
            self.move_record(event.record, lane, None)

    @work(group="ui")
    async def move_record(self, record: dict, lane: str, index: int | None) -> None:
        try:
            await self.api.move_record(self.model_id, record["id"], {self.lane_field: lane}, index)
        except ApiError as exc:
            await self.signed_out(exc)
            # The board on screen no longer matches the server; ask again.
            await self.load_records()
            return
        await self.load_records()
        self._refocus(record["id"])
        note = self._lane_note(lane)
        if note:
            self.status(f"{dict(self.lanes)[lane].lower()} — {note}")

    def _refocus(self, record_id: str) -> None:
        """Keep the moved card focused, so `]` twice goes across two lanes."""
        try:
            self.query_one(f"#card-{safe_id(record_id)}", RecordCard).focus()
        except Exception:
            return

    def _position_of(self, record: dict) -> int:
        """Where a record currently sits in its own lane."""
        lane = self._lane_of(record)
        same = [row for row in self.records if self._lane_of(row) == lane]
        for index, row in enumerate(same):
            if row["id"] == record["id"]:
                return index
        return -1
