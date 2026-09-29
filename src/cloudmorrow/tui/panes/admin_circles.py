"""Administration → Circles: who may use which data (docs/CIRCLES.md).

A circle is a named set of people — Parents, Kids, Sales — and, for each
kind of data, what they may do with it: write, read, or nothing. Somebody's
access is the most any of their circles gives. There is no deny, so "why
can't I see this?" always has one answer: none of your circles has it.

The table is every circle, with its people and its data. The keys:

- `n` makes one, `e` renames it, `d` deletes it (its people keep their
  other circles), `t` makes it where new accounts go, or stops that.
- `p` is its people: a tick for everybody on the server.
- `a` is its data. Set the way people think of it, by domain — Tasks,
  Calendars, Customers — and stored the way the gate checks it, per
  datamodel: `r` on Calendars writes read on calendar and on event. Enter
  opens a domain to set its datamodels one by one; Everything at the top is
  `*`, which reaches datamodels installed later too.
"""

from __future__ import annotations

from collections.abc import Iterable

from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Checkbox, DataTable, Label, Static

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.panes.base import Pane
from cloudmorrow.tui.screens.modals import ConfirmModal, Modal, PromptModal
from cloudmorrow.tui.theme import ACCENT, BAD, FAINT, GOOD, MUTED, WARN
from cloudmorrow.tui.widgets.toolbar import Action
from cloudmorrow.tui.words import plural

EVERY = "*"
# What a circle gives on a datamodel, and how it is drawn.
ACCESS: tuple[str, ...] = ("write", "read", "none")
SAID = {"write": "Write", "read": "Read", "none": "Nothing"}
COLOURS = {"write": GOOD, "read": ACCENT, "none": BAD}
# A datamodel with no line of its own: whatever Everything gives.
FOLLOW = ""
MIXED = "mixed"


# -- what a circle says -------------------------------------------------------------
def rules_said(rules: dict[str, str]) -> str:
    """A circle's rules on one line, Everything first: `Everything: Write · task: Read`."""
    order = sorted(model for model in rules if model != EVERY)
    if EVERY in rules:
        order.insert(0, EVERY)
    if not order:
        return f"[{MUTED}]no data yet[/]"
    return " · ".join(
        f"{'Everything' if model == EVERY else model}: "
        f"[{COLOURS.get(rules[model], MUTED)}]{SAID.get(rules[model], rules[model])}[/]"
        for model in order
    )


def circles_by_person(circles: Iterable[dict]) -> dict[str, list[str]]:
    """The circles each person is in, by username."""
    found: dict[str, list[str]] = {}
    for circle in circles:
        for name in circle.get("members") or []:
            found.setdefault(name, []).append(circle["name"])
    return found


def _domain_label(domain: str) -> str:
    """ "calendars" is Calendars, "crm" is CRM."""
    if not domain:
        return "Other"
    words = domain.replace(".", " ").replace("_", " ").replace("-", " ")
    return words.upper() if len(words) <= 3 else words[:1].upper() + words[1:]


def domains_of(models: Iterable[dict]) -> list[dict]:
    """The datamodels shelved by domain; a Quill's own datamodel with no domain
    is shelved under the Quill that brought it."""
    shelves: dict[str, dict] = {}
    for model in models:
        source = model.get("source") or ""
        key = model.get("domain") or (source if source and source != "foundation" else "")
        shelf = shelves.setdefault(key, {"id": key, "label": _domain_label(key), "models": []})
        shelf["models"].append(model)
    return sorted(shelves.values(), key=lambda s: (not s["id"], s["label"].lower()))


def domain_value(rules: dict[str, str], models: Iterable[dict]) -> str:
    """A domain's datamodels' one answer — FOLLOW when none has a line — or MIXED."""
    values = {rules.get(model["id"], FOLLOW) for model in models}
    return values.pop() if len(values) == 1 else MIXED


class RulesModal(Modal[dict | None]):
    """A circle's data, a row per domain, opening to its datamodels.

    `w`, `r` and `n` set the row under the cursor to write, read or nothing;
    `-` puts a datamodel back to following Everything. Enter opens a domain.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("w", "set('write')", "Write"),
        ("r", "set('read')", "Read"),
        ("n", "set('none')", "Nothing"),
        ("minus", "set('')", "As everything"),
        ("ctrl+s", "save", "Save"),
    ]

    def __init__(self, circle: dict, models: list[dict], *, partial: bool = False) -> None:
        super().__init__()
        self.circle = circle
        self.rules: dict[str, str] = dict(circle.get("rules") or {})
        self.shelves = domains_of(models)
        self.open: set[str] = set()
        # Whether the datamodels listed are only the ones this administrator reaches.
        self.partial = partial
        # One entry per table row: ("*", None), ("domain", shelf) or ("model", model).
        self._rows: list[tuple[str, dict | None]] = []

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal modal-wide", id="rules-modal"):
            yield Label(f"{self.circle['name']}: its data", classes="modal-title")
            note = "w write · r read · n nothing · - as everything · enter opens a domain"
            if self.partial:
                note += "\nOnly the datamodels your own circles reach are listed."
            yield Static(f"[{MUTED}]{note}[/]", classes="modal-detail")
            yield DataTable(id="rules-table", cursor_type="row", zebra_stripes=False)
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="primary", id="save")

    def on_mount(self) -> None:
        table = self.query_one("#rules-table", DataTable)
        table.add_columns("DATA", "ACCESS", "")
        self._draw()
        table.focus()

    # -- drawing ---------------------------------------------------------------
    @staticmethod
    def _said(value: str, *, follows: str = "") -> str:
        if value == MIXED:
            return f"[{WARN}]Mixed[/]"
        if value == FOLLOW:
            return f"[{MUTED}]as everything ({SAID[follows or 'none'].lower()})[/]"
        return f"[{COLOURS.get(value, MUTED)}]{SAID.get(value, value)}[/]"

    def _draw(self) -> None:
        table = self.query_one("#rules-table", DataTable)
        row = table.cursor_row
        table.clear()
        self._rows = []
        every = self.rules.get(EVERY, "none")
        table.add_row("[b]Everything[/]", self._said(every), f"[{FAINT}]and datamodels installed later[/]")
        self._rows.append((EVERY, None))
        for shelf in self.shelves:
            opened = shelf["id"] in self.open
            value = domain_value(self.rules, shelf["models"])
            names = ", ".join(m.get("label") or m["id"] for m in shelf["models"])
            table.add_row(
                f"{'▾' if opened else '▸'} [b]{escape(shelf['label'])}[/]",
                self._said(value, follows=every),
                f"[{FAINT}]{escape(names)}[/]",
            )
            self._rows.append(("domain", shelf))
            if opened:
                for model in shelf["models"]:
                    table.add_row(
                        f"    {escape(model.get('label') or model['id'])}",
                        self._said(self.rules.get(model["id"], FOLLOW), follows=every),
                        f"[{FAINT}]{escape(model['id'])}[/]",
                    )
                    self._rows.append(("model", model))
        table.move_cursor(row=min(max(row, 0), len(self._rows) - 1))

    # -- changing --------------------------------------------------------------
    @property
    def _current(self) -> tuple[str, dict | None]:
        table = self.query_one("#rules-table", DataTable)
        return self._rows[min(max(table.cursor_row, 0), len(self._rows) - 1)]

    def _put(self, model: str, value: str) -> None:
        if model == EVERY:
            # Nothing on `*` is the same as no `*` line.
            if value in (FOLLOW, "none"):
                self.rules.pop(EVERY, None)
            else:
                self.rules[EVERY] = value
        elif value == FOLLOW:
            self.rules.pop(model, None)
        else:
            self.rules[model] = value

    def action_set(self, value: str) -> None:
        kind, what = self._current
        if kind == EVERY:
            self._put(EVERY, value)
        elif kind == "domain" and what is not None:
            for model in what["models"]:
                self._put(model["id"], value)
        elif what is not None:
            self._put(what["id"], value)
        self._draw()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        kind, what = self._current
        if kind == "domain" and what is not None:
            self.open ^= {what["id"]}
            self._draw()

    def action_save(self) -> None:
        self.dismiss(self.rules)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "save":
            self.action_save()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class PeopleModal(Modal[list[str] | None]):
    """Who is in a circle: a tick for everybody on the server."""

    BINDINGS = [("escape", "cancel", "Cancel"), ("ctrl+s", "save", "Save")]

    def __init__(self, circle: dict, users: list[dict]) -> None:
        super().__init__()
        self.circle = circle
        self.users = users

    def compose(self) -> ComposeResult:
        members = set(self.circle.get("members") or [])
        with Vertical(classes="modal", id="people-modal"):
            yield Label(f"Who is in {self.circle['name']}", classes="modal-title")
            yield Static(f"[{MUTED}]space ticks · ↑↓ move · ctrl+s saves[/]", classes="modal-detail")
            with VerticalScroll(id="people-list"):
                for index, user in enumerate(self.users):
                    name = user["username"]
                    if user.get("display_name"):
                        name += f"  ({user['display_name']})"
                    yield Checkbox(name, value=user["username"] in members, id=f"member-{index}")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="primary", id="save")

    def on_mount(self) -> None:
        boxes = list(self.query(Checkbox))
        if boxes:
            boxes[0].focus()

    def action_save(self) -> None:
        self.dismiss(
            [
                user["username"]
                for index, user in enumerate(self.users)
                if self.query_one(f"#member-{index}", Checkbox).value
            ]
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "save":
            self.action_save()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class CirclesView(Pane):
    """Every circle, with its people and its data."""

    TAB_LABEL = "Circles"
    SUMMARY = "who may use which data"
    BINDINGS = [
        ("n", "fire('new')", "New circle"),
        ("a", "fire('access')", "Data"),
        ("p", "fire('people')", "People"),
        ("e", "fire('rename')", "Rename"),
        ("t", "fire('default')", "Default"),
        ("d", "fire('remove')", "Delete"),
    ]
    ACTIONS = (
        Action("new", "New circle", "n", variant="primary", hint="A named set of people"),
        Action("access", "Data…", "a", hint="What its people may do with each kind of data"),
        Action("people", "People…", "p", hint="Who is in it"),
        Action("rename", "Rename", "e"),
        Action("default", "Default", "t", hint="Whether new accounts go into it"),
        Action("remove", "Delete", "d", variant="error", hint="Its people keep their other circles"),
    )

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._circles: list[dict] = []

    def content(self) -> ComposeResult:
        yield Static("", id="admin-circles-note")
        yield DataTable(id="admin-circle-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        self.query_one("#admin-circle-table", DataTable).add_columns("CIRCLE", "DEFAULT", "PEOPLE", "DATA")

    def on_show(self) -> None:
        self.reload()

    @property
    def selected(self) -> dict | None:
        table = self.query_one("#admin-circle-table", DataTable)
        if not self._circles or not 0 <= table.cursor_row < len(self._circles):
            return None
        return self._circles[table.cursor_row]

    @work(exclusive=True, group="admin-circles")
    async def reload(self) -> None:
        client = self.api
        if client is None:
            return
        try:
            self._circles = await client.circles()
            users = await client.users()
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        table = self.query_one("#admin-circle-table", DataTable)
        row = table.cursor_row
        table.clear()
        for circle in self._circles:
            table.add_row(
                f"[b]{escape(circle['name'])}[/]",
                f"[{GOOD}]yes[/]" if circle.get("default") else "",
                escape(", ".join(circle.get("members") or [])) or f"[{MUTED}]nobody[/]",
                rules_said(circle.get("rules") or {}),
            )
        if self._circles:
            table.move_cursor(row=min(max(row, 0), len(self._circles) - 1))
        # Rule 3: in no circle is no data, said where it cannot be missed.
        placed = circles_by_person(self._circles)
        adrift = [u["username"] for u in users if u["username"] not in placed]
        self.query_one("#admin-circles-note", Static).update(
            f"[{WARN}]In no circle, so reaching no data: {escape(', '.join(adrift))}[/]"
            if adrift
            else f"[{FAINT}]Everybody gets the most any of their circles gives. "
            f"a sets a circle's data, p its people.[/]"
        )
        count = len(self._circles)
        self.status(plural(count, "circle"), note=True)

    def _pick(self) -> dict | None:
        circle = self.selected
        if circle is None:
            self.status("No circle selected.", error=True)
        return circle

    # -- making, naming, deleting ---------------------------------------------
    def act_refresh(self) -> None:
        self.reload()

    def act_new(self) -> None:
        self.new_circle()

    @work(group="ui")
    async def new_circle(self) -> None:
        name = await self.app.push_screen_wait(
            PromptModal(
                "New circle",
                placeholder="Kids",
                detail=f"[{MUTED}]It starts with nobody in it and no data.[/]",
            )
        )
        if not name:
            return
        try:
            circle = await self.api.create_circle(name)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.status(f"Made {circle['name']}. a gives it data, p gives it people.")
        self.reload()

    def act_rename(self) -> None:
        if (circle := self._pick()) is not None:
            self.rename(circle)

    @work(group="ui")
    async def rename(self, circle: dict) -> None:
        name = await self.app.push_screen_wait(PromptModal(f"Rename {circle['name']}", value=circle["name"]))
        if not name or name == circle["name"]:
            return
        try:
            changed = await self.api.update_circle(circle["id"], name=name)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.status(f"{circle['name']} is {changed['name']} now.")
        self.reload()

    def act_default(self) -> None:
        if (circle := self._pick()) is not None:
            self.toggle_default(circle)

    @work(group="admin-circles-write")
    async def toggle_default(self, circle: dict) -> None:
        try:
            changed = await self.api.update_circle(circle["id"], default=not circle.get("default"))
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        if changed.get("default"):
            self.status(f"New accounts go into {changed['name']}.")
        else:
            self.status(f"New accounts no longer go into {changed['name']}.")
        self.reload()

    def act_remove(self) -> None:
        if (circle := self._pick()) is not None:
            self.remove_circle(circle)

    @work(group="ui")
    async def remove_circle(self, circle: dict) -> None:
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(
                f"Delete {circle['name']}?",
                detail=(
                    "Its people keep their other circles. Anybody in no other "
                    "circle reaches no data until they are put in one."
                ),
                confirm_label="Delete",
            )
        )
        if not confirmed:
            return
        try:
            await self.api.delete_circle(circle["id"])
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.status(f"Deleted {circle['name']}.")
        self.reload()

    # -- its people and its data ------------------------------------------------
    def act_people(self) -> None:
        if (circle := self._pick()) is not None:
            self.people(circle)

    @work(group="ui")
    async def people(self, circle: dict) -> None:
        try:
            users = await self.api.users()
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        wanted = await self.app.push_screen_wait(PeopleModal(circle, users))
        if wanted is None:
            return
        before = set(circle.get("members") or [])
        try:
            for name in sorted(set(wanted) - before):
                await self.api.join_circle(circle["id"], name)
            for name in sorted(before - set(wanted)):
                await self.api.leave_circle(circle["id"], name)
        except ApiError as exc:
            self.status(str(exc), error=True)
            self.reload()
            return
        self.status(f"Saved who is in {circle['name']}.")
        self.reload()

    def act_access(self) -> None:
        if (circle := self._pick()) is not None:
            self.access(circle)

    @work(group="ui")
    async def access(self, circle: dict) -> None:
        try:
            models = await self.api.datamodels()
            me = await self.api.me()
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        # The datamodels are the ones this administrator reaches: all of them
        # from a `*` circle, some of them otherwise, which the dialog says.
        whole = any(
            me.get("username") in (c.get("members") or []) and (c.get("rules") or {}).get(EVERY) for c in self._circles
        )
        rules = await self.app.push_screen_wait(RulesModal(circle, models, partial=not whole))
        if rules is None:
            return
        try:
            changed = await self.api.update_circle(circle["id"], rules=rules)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.status(f"Saved {changed['name']}'s data.")
        self.reload()
