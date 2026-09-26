"""The kit's `calendar` in the terminal: the spaces, the month, and the day.

Three columns' worth of one idea. On the left, every space the screen's
things can be in that you can see — for a calendar Quill, the calendars:
your own at the top, then the shared ones, then everybody's. In the middle,
the month, a cell per day with a coloured dot for each thing on it. Under
that, the day you are standing on, written out.

The list on the left is not a filter. Everything you can see is drawn in
the month, in the colour of the space it is in, because a calendar you have
to switch between is one that lets you double-book yourself. What the list
picks is where a new thing goes, and which space `p`, `s` and `l` are about.

It is all read from the screen's bindings (docs/QUILLS.md, *Screens*):
`starts` and `ends` are the two moments, `all_day` the optional bool,
`space` the link to the spaces, `colour` the space's colour, `title` and
`subtitle` what a line says. Times are the times on the wall: a moment
without a zone is drawn exactly as it is stored, and a bare date is a whole
day whose end is the last day it is on.
"""

from __future__ import annotations

import calendar as cal
import datetime as dt

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Static

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.panes.kit import KitPane
from cloudmorrow.tui.screens.record_sheet import RecordSheet, link_choices
from cloudmorrow.tui.theme import ACCENT, BAD, GOOD, LENS, MUTED, TEXT
from cloudmorrow.tui.widgets.kit import field_of, title_of
from cloudmorrow.tui.widgets.kit_space import NewSpaceModal, SpaceModal, make_space, scope_said
from cloudmorrow.tui.widgets.toolbar import Action

# The days across the top, starting on Monday, which is where a week starts.
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# The colours a space can be, by name, and what each looks like here: the
# same values the web app draws, so a calendar is the same colour on the
# phone and in the terminal.
COLOURS: dict[str, str] = {
    "cyan": "#4fe3d7",
    "violet": "#a78bfa",
    "green": GOOD,
    "amber": LENS,
    "rose": BAD,
}
COLOUR_NAMES = tuple(COLOURS)

# How many dots fit in a cell of the month before they turn into a count.
DOTS = 3


def colour_for(name: object) -> str:
    return COLOURS.get(str(name or ""), COLOURS["cyan"])


def month_start(day: dt.date) -> dt.date:
    return day.replace(day=1)


def shift_month(day: dt.date, months: int) -> dt.date:
    """The same day-of-month, a month or two along, clamped to a real date."""
    total = (day.year * 12 + day.month - 1) + months
    year, month = divmod(total, 12)
    last = cal.monthrange(year, month + 1)[1]
    return dt.date(year, month + 1, min(day.day, last))


def weeks_of(day: dt.date) -> list[list[dt.date]]:
    """The month *day* is in, as whole weeks — the ends belong to its neighbours."""
    return cal.Calendar(firstweekday=0).monthdatescalendar(day.year, day.month)


def wall(value: object) -> str:
    """A stored moment as the wall clock here says it: a zone converted; the
    wall clock, and a bare date, exactly as they are."""
    text = str(value or "")
    if len(text) <= 16:
        return text
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        return text[:16]
    if moment.tzinfo is not None:
        moment = moment.astimezone().replace(tzinfo=None)
    return moment.strftime("%Y-%m-%dT%H:%M")


def clock(stamp: str) -> str:
    """The time out of a stored moment: 2026-09-19T14:03 → 14:03."""
    return stamp[11:16] if len(stamp) > 10 else ""


def occasion(record: dict, b: dict, spaces: dict[str, dict], space_model: dict) -> dict:
    """One record as a thing on a calendar: when, what, and in which space."""
    fields = record.get("fields") or {}
    starts = wall(fields.get(b["starts"]))
    ends = wall(fields.get(b["ends"])) or starts
    space = spaces.get(str(fields.get(b["space"]) or ""))
    return {
        "id": record["id"],
        "record": record,
        "title": str(fields.get(b["title"]) or "") or "Untitled",
        "subtitle": str(fields.get(b["subtitle"]) or "") if b["subtitle"] else "",
        "starts": starts,
        "ends": max(ends, starts),
        "all_day": bool(fields.get(b["all_day"])) if b["all_day"] else len(starts) == 10,
        "colour": (space.get("fields") or {}).get(b["colour"]) if space and b["colour"] else "cyan",
        "space_name": title_of(space, space_model) if space else "",
        "owner": record.get("owner", ""),
    }


def when_said(event: dict) -> str:
    """How long a thing lasts, in the fewest words that are still true."""
    if event["all_day"]:
        if event["ends"][:10] != event["starts"][:10]:
            return f"all day, to {event['ends'][:10]}"
        return "all day"
    start, end = clock(event["starts"]), clock(event["ends"])
    if event["ends"][:10] != event["starts"][:10]:
        return f"{start} → {event['ends'][:10]} {end}"
    return start if end == start else f"{start}–{end}"


def days_of(event: dict) -> list[dt.date]:
    """Every day a thing is on, so a month can draw it on each of them."""
    first = dt.date.fromisoformat(event["starts"][:10])
    last = max(first, dt.date.fromisoformat(event["ends"][:10]))
    return [first + dt.timedelta(days=step) for step in range((last - first).days + 1)]


def by_day(events: list[dict]) -> dict[dt.date, list[dict]]:
    """The things, filed under each day they cover."""
    filed: dict[dt.date, list[dict]] = {}
    for event in events:
        for day in days_of(event):
            filed.setdefault(day, []).append(event)
    return filed


def in_order(events: list[dict]) -> list[dict]:
    """Whole days first, then the rest in the order the day happens."""
    return sorted(events, key=lambda e: (not e["all_day"], e["starts"]))


def cell_text(day: dt.date, events: list[dict], *, shown: dt.date, today: dt.date) -> str:
    """One square of the month: the date, and a dot for each thing on it.

    Dots rather than titles: a cell is nine characters wide and a title is
    not, and the day underneath says what they are in full — so the month
    answers "when am I busy", which is the question a month is for.
    """
    number = f"{day.day:>2}"
    if day == today:
        number = f"[b {ACCENT}]{number}[/]"
    elif day.month != shown.month:
        # The days either side belong to the neighbouring months.
        number = f"[{MUTED}]{number}[/]"
    if not events:
        return f"{number}\n"
    dots = "".join(f"[{colour_for(e['colour'])}]●[/]" for e in events[:DOTS])
    more = f"[{MUTED}]+{len(events) - DOTS}[/]" if len(events) > DOTS else ""
    return f"{number}\n {dots}{more}"


def _escape(text: object) -> str:
    """Whatever somebody typed is text, not markup."""
    return str(text or "").replace("[", r"\[")


def event_line(event: dict, *, me: str) -> str:
    """One thing, on one line: when, what, the subtitle, and whose space.

    One line each, and exactly one, because the list this fills is a table
    with a cursor on it.
    """
    parts = [
        f"[{colour_for(event['colour'])}]●[/] [{MUTED}]{when_said(event):>13}[/]",
        f"[{TEXT}]{_escape(event['title'])}[/]",
    ]
    if event["subtitle"]:
        parts.append(f"[{MUTED}]{_escape(event['subtitle'])}[/]")
    whose = event["space_name"]
    if event["owner"] and event["owner"] != me:
        whose = f"{whose} · {event['owner']}"
    if whose:
        parts.append(f"[{MUTED}]{_escape(whose)}[/]")
    return "  ".join(parts)


def space_row(space: dict, model: dict, colour: str, *, me: str) -> tuple[str, str]:
    """A space's two cells: what it is called, and who it is for."""
    dot = colour_for((space.get("fields") or {}).get(colour)) if colour else colour_for("")
    who = scope_said(space)
    if space.get("scope") == "personal" and space.get("owner") != me:
        who = space.get("owner", "")
    return f"[{dot}]●[/] {_escape(title_of(space, model))}", f"[{MUTED}]{who}[/]"


def space_order(space: dict) -> tuple:
    """Yours first, then the shared ones, then everybody's."""
    return ({"personal": 0, "shared": 1, "public": 2}.get(space.get("scope"), 3),)


def settle_times(b: dict, fields: dict, record: dict | None) -> dict:
    """What a calendar knows about time that the datamodel does not.

    Whole days keep their days and drop their times; a thing that stops
    being all day gets an hour from nine. Moving the start drags the end
    along, so it keeps its length. An end is never before its start.
    """
    was = (record or {}).get("fields") or {}
    start0 = wall(was.get(b["starts"]))
    end0 = wall(was.get(b["ends"])) or start0
    out = dict(fields)
    starts = str(out.get(b["starts"]) or start0)
    ends = str(out.get(b["ends"]) or end0 or starts)
    if b["all_day"] and b["all_day"] in out and (record is None or out[b["all_day"]] != was.get(b["all_day"])):
        first = starts[:10]
        if out[b["all_day"]]:
            out[b["starts"]], out[b["ends"]] = first, max(ends[:10], first)
        elif len(starts) == 10:
            out[b["starts"]], out[b["ends"]] = f"{first}T09:00", f"{first}T10:00"
        return out
    if record is not None and b["starts"] in out and b["ends"] not in out and start0 and end0:
        out[b["ends"]] = _shifted(end0, start0, starts)
        return out
    if b["ends"] in out and ends < starts:
        out[b["ends"]] = starts
    return out


def _shifted(end: str, was: str, now: str) -> str:
    """*end*, moved as far as the start moved from *was* to *now*."""
    try:
        if len(was) == 10 or len(now) == 10:
            days = (dt.date.fromisoformat(now[:10]) - dt.date.fromisoformat(was[:10])).days
            moved = dt.date.fromisoformat(end[:10]) + dt.timedelta(days=days)
            return moved.isoformat() + end[10:]
        delta = dt.datetime.fromisoformat(now[:16]) - dt.datetime.fromisoformat(was[:16])
        return (dt.datetime.fromisoformat(end[:16]) + delta).strftime("%Y-%m-%dT%H:%M")
    except ValueError:
        return end


class CalendarPane(KitPane):
    """The spaces, the month across from them, and the day underneath."""

    BINDINGS = [
        *KitPane.BINDINGS,
        # Written on the toolbar with the words for this screen's things, so
        # the bottom line does not say them again in the kit's own words.
        Binding("n", "fire('new_record')", "New", show=False),
        Binding("e", "fire('open_record')", "Edit", show=False),
        Binding("c", "fire('new_space')", "New space", show=False),
        Binding("p", "fire('people')", "People", show=False),
        Binding("r", "fire('edit_space')", "Rename", show=False),
        Binding("t", "fire('today')", "Today", show=False),
        Binding("[", "month(-1)", "Last month", show=False),
        Binding("]", "month(1)", "Next month", show=False),
    ]

    def __init__(self, quill: dict, screen: dict, **kwargs) -> None:
        super().__init__(quill, screen, **kwargs)
        space = field_of(self.model, screen.get("space")) or {}
        self.b = {
            "starts": screen.get("starts") or "starts",
            "ends": screen.get("ends") or "ends",
            "all_day": screen.get("all_day") or "",
            "space": space.get("name") or "",
            "colour": screen.get("colour") or "",
            "title": screen.get("title") or self.model.get("title") or "title",
            "subtitle": screen.get("subtitle") or "",
        }
        self.space_model_id: str = space.get("to") or ""
        self.space_model: dict = self.models.get(self.space_model_id) or {}
        self.spaces: list[dict] = []
        self.events: list[dict] = []
        self.day = dt.date.today()
        self.shown = month_start(self.day)
        # The space a new thing goes in: whichever one the list is on.
        self.space_id = ""
        self._grid: list[list[dt.date]] = []
        space_noun = self.space_noun
        self.ACTIONS = (
            Action("new_record", f"New {self.noun}", "n", variant="primary",
                   hint="On the day you are on"),
            Action("open_record", "Edit", "e", hint=f"The {self.noun} under the cursor"),
            Action("delete_record", "Delete", "del"),
            Action("new_space", f"New {space_noun}", "c", hint="Shared, or one everybody is in"),
            Action("people", "People", "p", hint=f"Who is in this {space_noun}: add, take out, leave"),
            Action("edit_space", f"Rename {space_noun}", "r", hint="Its name and its colour"),
            Action("today", "Today", "t"),
        )

    @property
    def space_noun(self) -> str:
        return str(self.space_model.get("label") or self.space_model_id or "space").lower()

    @property
    def me(self) -> str:
        return getattr(self.app, "username", "") or ""

    # -- layout --------------------------------------------------------------
    def content(self) -> ComposeResult:
        with Horizontal(id="calendar-body"):
            with Vertical(id="calendar-list"):
                yield Static(f"[{MUTED}]{self.space_noun}s[/]", classes="pane-title")
                yield DataTable(id="calendar-table", cursor_type="row")
            with Vertical(id="month-pane"):
                yield Static("", id="month-title", classes="pane-title")
                yield DataTable(id="month-grid", cursor_type="cell")
                yield Static("", id="day-title", classes="pane-title")
                yield DataTable(id="day-table", cursor_type="row", show_header=False)

    def on_mount(self) -> None:
        self.query_one("#calendar-table", DataTable).add_columns(self.space_noun.upper(), "WHO")
        grid = self.query_one("#month-grid", DataTable)
        for weekday in WEEKDAYS:
            grid.add_column(weekday, width=9)
        self.query_one("#day-table", DataTable).add_column("event")

    def card_status(self) -> tuple[str, str] | None:
        if not self.loaded:
            return None
        count = len(by_day(self.events).get(dt.date.today(), []))
        return ("news", f"{count} today") if count else ("ok", "nothing today")

    def status_detail(self) -> str:
        space = self.space
        if space is None:
            return f"[{MUTED}]no {self.space_noun}s[/]"
        colour = colour_for((space.get("fields") or {}).get(self.b["colour"]))
        return (
            f"new go in [{colour}]{_escape(title_of(space, self.space_model))}[/]  "
            f"[{MUTED}]{len(self.events)} this month[/]"
        )

    @property
    def space(self) -> dict | None:
        return next((s for s in self.spaces if s["id"] == self.space_id), None)

    @property
    def selected(self) -> dict | None:
        """The thing the cursor is on, down in the day's list."""
        row = self.query_one("#day-table", DataTable).cursor_row
        showing = self.day_events()
        return showing[row]["record"] if 0 <= row < len(showing) else None

    def day_events(self) -> list[dict]:
        return in_order(by_day(self.events).get(self.day, []))

    # -- loading ---------------------------------------------------------------
    @work(exclusive=True, group="kit-calendar")
    async def reload(self) -> None:
        if self.api is None:
            return
        try:
            spaces = await self.api.records(self.space_model_id)
        except ApiError as exc:
            await self.signed_out(exc)
            return
        self.spaces = sorted(spaces, key=space_order)
        if self.space is None:
            mine = next((s for s in self.spaces if s.get("scope") == "personal"), None)
            self.space_id = (mine or (self.spaces[0] if self.spaces else {})).get("id", "")
        self._draw_spaces()
        await self._fetch()
        self.loaded = True
        self._draw_month()
        self._draw_day()
        self.status()

    async def _fetch(self) -> None:
        """Everything in the weeks the month is drawn from, neighbours and all."""
        weeks = weeks_of(self.shown)
        first, last = weeks[0][0].isoformat(), weeks[-1][-1].isoformat()
        try:
            records = await self.api.records(
                self.model_id,
                **{f"{self.b['starts']}__lte": f"{last}T23:59", f"{self.b['ends']}__gte": first},
            )
        except ApiError as exc:
            self.events = []
            self.status(str(exc), error=True)
            return
        by_id = {s["id"]: s for s in self.spaces}
        self.events = [occasion(r, self.b, by_id, self.space_model) for r in records]

    def _draw_spaces(self) -> None:
        table = self.query_one("#calendar-table", DataTable)
        table.clear()
        for space in self.spaces:
            table.add_row(*space_row(space, self.space_model, self.b["colour"], me=self.me))
        for row, space in enumerate(self.spaces):
            if space["id"] == self.space_id:
                table.move_cursor(row=row)
                break

    def _draw_month(self) -> None:
        filed = by_day(self.events)
        today = dt.date.today()
        grid = self.query_one("#month-grid", DataTable)
        grid.clear()
        self._grid = weeks_of(self.shown)
        for week in self._grid:
            grid.add_row(
                *(cell_text(day, filed.get(day, []), shown=self.shown, today=today) for day in week),
                height=2,
            )
        self.query_one("#month-title", Static).update(
            f"[{ACCENT}]{self.shown.strftime('%B %Y')}[/]  [{MUTED}]\\[ ] move months, t for today[/]"
        )
        for row, week in enumerate(self._grid):
            if week[0] <= self.day <= week[-1]:
                grid.move_cursor(row=row, column=self.day.weekday())
                break

    def _draw_day(self) -> None:
        showing = self.day_events()
        self.query_one("#day-title", Static).update(
            f"[{ACCENT}]{self.day.strftime('%A %d %B')}[/]"
            + (f"  [{MUTED}]{len(showing)} on[/]" if showing else "")
        )
        table = self.query_one("#day-table", DataTable)
        table.clear()
        if not showing:
            table.add_row(f"[{MUTED}]Nothing on. Press n to put something here.[/]")
            return
        for event in showing:
            table.add_row(event_line(event, me=self.me))

    # -- moving about ------------------------------------------------------------
    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "calendar-table":
            return
        # Where the cursor is now: redrawing queues a highlight for row 0
        # that lands after the cursor has been put back where it belongs.
        row = event.data_table.cursor_row
        if 0 <= row < len(self.spaces):
            self.space_id = self.spaces[row]["id"]
            self.status()

    def on_data_table_cell_highlighted(self, event: DataTable.CellHighlighted) -> None:
        if event.data_table.id != "month-grid":
            return
        here = event.data_table.cursor_coordinate
        if not (0 <= here.row < len(self._grid) and 0 <= here.column < 7):
            return
        day = self._grid[here.row][here.column]
        if day == self.day:
            return
        self.day = day
        # Stepping off the end of a month is how you walk into the next one.
        if day.month != self.shown.month:
            self.show_month(month_start(day))
        else:
            self._draw_day()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "day-table":
            event.stop()
            self.act_open_record()
        elif event.data_table.id == "calendar-table":
            event.stop()
            self.act_people()

    def action_month(self, step: int) -> None:
        self.show_month(month_start(shift_month(self.shown, step)))

    def show_month(self, first: dt.date) -> None:
        self.shown = first
        if month_start(self.day) != first:
            self.day = first
        self.load_month()

    @work(exclusive=True, group="kit-calendar-month")
    async def load_month(self) -> None:
        await self._fetch()
        self._draw_month()
        self._draw_day()

    def act_today(self) -> None:
        self.day = dt.date.today()
        self.show_month(month_start(self.day))

    def act_refresh(self) -> None:
        self.reload()

    # -- the things on it ---------------------------------------------------------
    def _adjust(self, fields: dict, record: dict | None) -> dict:
        return settle_times(self.b, fields, record)

    async def open_sheet(self, record: dict | None = None, *, preset: dict | None = None):
        choices = await link_choices(self.api, self.models, self.model)
        return await self.app.push_screen_wait(
            RecordSheet(self.api, self.models, self.model_id, record=record, preset=preset,
                        choices=choices, adjust=self._adjust)
        )

    def act_open_record(self) -> None:
        record = self.selected
        if record is None:
            self.status("Nothing to open on this day.", error=True)
            return
        self.edit_record(record)

    @work(group="ui")
    async def edit_record(self, record: dict) -> None:
        result = await self.open_sheet(record)
        if result is None:
            return
        self.status(f"Deleted {title_of(record, self.model)}." if result == "deleted" else "Changed.")
        self.reload()

    def act_new_record(self) -> None:
        if self.space is None:
            self.status(f"No {self.space_noun} to put it in yet.", error=True)
            return
        self.new_record()

    @work(group="ui")
    async def new_record(self) -> None:
        day = self.day.isoformat()
        preset = {
            self.b["space"]: self.space_id,
            self.b["starts"]: f"{day}T09:00",
            self.b["ends"]: f"{day}T10:00",
        }
        if self.b["all_day"]:
            preset[self.b["all_day"]] = False
        saved = await self.open_sheet(None, preset=preset)
        if not isinstance(saved, dict):
            return
        self.status(f"{title_of(saved, self.model)} is in.")
        self.reload()

    def act_delete_record(self) -> None:
        record = self.selected
        if record is None:
            self.status("Nothing to delete on this day.", error=True)
            return
        self.delete_record(record)

    @work(group="ui")
    async def delete_record(self, record: dict) -> None:
        if await self.confirm_delete(record):
            self.status("Gone.")
            self.reload()

    # -- the spaces ------------------------------------------------------------------
    def act_new_space(self) -> None:
        self.new_space()

    @work(group="ui")
    async def new_space(self) -> None:
        try:
            people = await self.api.people()
        except ApiError:
            people = []
        answers = await self.app.push_screen_wait(NewSpaceModal(self.space_model, people))
        if not answers:
            return
        extra = {}
        if self.b["colour"]:
            taken = {(s.get("fields") or {}).get(self.b["colour"]) for s in self.spaces}
            extra[self.b["colour"]] = next(
                (c for c in COLOUR_NAMES if c not in taken), COLOUR_NAMES[len(self.spaces) % len(COLOUR_NAMES)]
            )
        try:
            made = await make_space(self.api, self.space_model, answers, extra)
        except ApiError as exc:
            await self.signed_out(exc)
            return
        self.space_id = made["id"]
        self.status(f"{title_of(made, self.space_model)} is made. Press p for who is in it.")
        self.reload()

    def act_people(self) -> None:
        if self.space is None:
            return
        self.people()

    @work(group="ui")
    async def people(self) -> None:
        try:
            everyone = await self.api.people()
            space = await self.api.record(self.space_model_id, self.space_id)
        except ApiError as exc:
            await self.signed_out(exc)
            return
        result = await self.app.push_screen_wait(
            SpaceModal(self.api, self.space_model, space, everyone, me=self.me)
        )
        if result == "left":
            self.space_id = ""
            self.status(f"You left {title_of(space, self.space_model)}.")
        if result:
            self.reload()

    def act_edit_space(self) -> None:
        space = self.space
        if space is None:
            return
        if not space.get("can_manage"):
            self.status(f"Only whoever made {title_of(space, self.space_model)} may change it.",
                        error=True)
            return
        self.edit_space(space)

    @work(group="ui")
    async def edit_space(self, space: dict) -> None:
        # The colour is a word on the record; here it is the five there are.
        models = dict(self.models)
        model = dict(self.space_model)
        fields = []
        for f in model.get("fields") or []:
            if f["name"] == self.b["colour"]:
                f = {**f, "kind": "enum", "values": list(COLOUR_NAMES),
                     "labels": [name.capitalize() for name in COLOUR_NAMES]}
            fields.append(f)
        model["fields"] = fields
        models[self.space_model_id] = model
        result = await self.app.push_screen_wait(
            RecordSheet(self.api, models, self.space_model_id, record=space)
        )
        if result == "deleted":
            self.space_id = ""
        if result is not None:
            self.reload()


__all__ = [
    "COLOURS",
    "CalendarPane",
    "by_day",
    "cell_text",
    "days_of",
    "event_line",
    "occasion",
    "settle_times",
    "shift_month",
    "space_row",
    "wall",
    "weeks_of",
    "when_said",
]
