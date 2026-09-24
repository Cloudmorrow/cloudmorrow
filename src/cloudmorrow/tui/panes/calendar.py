"""The calendar in the terminal: the calendars, the month, and the day.

Three columns' worth of one idea. On the left, every calendar you can see —
your own at the top, then the ones shared with you, then the ones everybody
is in. In the middle, the month, a cell per day with a coloured dot for each
thing on it. Below that, the day you are standing on, written out.

The list on the left is not a filter. Everything you can see is drawn in the
month, in the colour of the calendar it belongs to, because a calendar you
have to switch between is a calendar that lets you double-book yourself. What
the list picks is where a new event goes — and which calendar the sharing
buttons are about.

Times here are the times on the wall. The server keeps them that way, so a
quarter past nine is a quarter past nine, and nothing is converted on its way
to a screen; see `cloudmorrow.server.calendar`.
"""

from __future__ import annotations

import calendar as cal
import datetime as dt

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Label, Static, Switch

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.panes.base import Pane
from cloudmorrow.tui.screens.modals import ConfirmModal, Modal, PromptModal
from cloudmorrow.tui.theme import ACCENT, BAD, GOOD, MUTED, SECOND, TEXT, WARN
from cloudmorrow.tui.widgets.toolbar import Action

# The days across the top, starting on Monday, which is where a week starts.
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# What the server's colour names look like here. The names are the server's;
# the values are the one palette, so a calendar is the same colour in the
# terminal as it is on the phone.
COLOUR_OF: dict[str, str] = {
    "cyan": ACCENT,
    "violet": SECOND,
    "green": GOOD,
    "amber": WARN,
    "rose": BAD,
}

# How many dots fit in a cell of the month before they turn into a count.
DOTS = 3


def colour_for(name: str) -> str:
    return COLOUR_OF.get(name, ACCENT)


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


def clock(stamp: str) -> str:
    """The time out of a stored moment: 2026-09-19T14:03 → 14:03."""
    return stamp[11:16] if len(stamp) > 10 else ""


def when_said(event: dict) -> str:
    """How long a thing lasts, in the fewest words that are still true."""
    if event["all_day"]:
        if event["ends_at"][:10] != event["starts_at"][:10]:
            return f"all day, to {event['ends_at'][:10]}"
        return "all day"
    start, end = clock(event["starts_at"]), clock(event["ends_at"])
    if event["ends_at"][:10] != event["starts_at"][:10]:
        return f"{start} → {event['ends_at'][:10]} {end}"
    return f"{start}–{end}"


def days_of(event: dict) -> list[dt.date]:
    """Every day an event is on, so a month can draw it on each of them."""
    first = dt.date.fromisoformat(event["starts_at"][:10])
    last = max(first, dt.date.fromisoformat(event["ends_at"][:10]))
    return [first + dt.timedelta(days=step) for step in range((last - first).days + 1)]


def by_day(events: list[dict]) -> dict[dt.date, list[dict]]:
    """The events, filed under each day they cover."""
    filed: dict[dt.date, list[dict]] = {}
    for event in events:
        for day in days_of(event):
            filed.setdefault(day, []).append(event)
    return filed


def cell_text(day: dt.date, events: list[dict], *, shown: dt.date, today: dt.date) -> str:
    """One square of the month: the date, and a dot for each thing on it.

    Dots rather than titles. A cell is eight characters wide and a title is
    not, and the day underneath the month says what they are in full — so the
    month answers "when am I busy", which is the question a month is for.
    """
    number = f"{day.day:>2}"
    if day == today:
        number = f"[b {ACCENT}]{number}[/]"
    elif day.month != shown.month:
        # The days either side belong to the neighbouring months. They are
        # there so the weeks are whole, not to be read.
        number = f"[{MUTED}]{number}[/]"
    if not events:
        return f"{number}\n"
    dots = "".join(f"[{colour_for(e['colour'])}]●[/]" for e in events[:DOTS])
    more = f"[{MUTED}]+{len(events) - DOTS}[/]" if len(events) > DOTS else ""
    return f"{number}\n {dots}{more}"


def event_line(event: dict, *, me: str) -> str:
    """One event, on one line: when, what, where, and whose calendar.

    One line each, and exactly one, because the list this fills is a table
    with a cursor on it — a second line for the notes would put the cursor
    on something that is not an event.
    """
    colour = colour_for(event["colour"])
    parts = [
        f"[{colour}]●[/] [{MUTED}]{when_said(event):>13}[/]",
        f"[{TEXT}]{_escape(event['title'])}[/]",
    ]
    if event["location"]:
        parts.append(f"[{MUTED}]{_escape(event['location'])}[/]")
    note = " ".join(str(event["notes"] or "").split())
    if note:
        parts.append(f"[{MUTED}]{_escape(note[:60])}[/]")
    whose = event["calendar_name"]
    if event["created_by"] and event["created_by"] != me:
        whose = f"{whose} · {event['created_by']}"
    parts.append(f"[{MUTED}]{_escape(whose)}[/]")
    return "  ".join(parts)


def day_lines(events: list[dict], *, me: str) -> str:
    """The selected day, written out, in the order the day happens."""
    if not events:
        return f"[{MUTED}]Nothing on. Press n to put something here.[/]"
    return "\n".join(
        event_line(event, me=me)
        for event in sorted(events, key=lambda e: (not e["all_day"], e["starts_at"]))
    )


def _escape(text: str) -> str:
    """Whatever somebody typed is text, not markup."""
    return str(text or "").replace("[", r"\[")


def calendar_row(calendar: dict, *, me: str) -> tuple[str, str]:
    """A calendar's two cells: what it is called, and who it is for."""
    colour = colour_for(calendar["colour"])
    kind = {
        "personal": "mine" if calendar["owner"] == me else calendar["owner"],
        "public": "everyone",
        "shared": f"{len(calendar['members'])} people",
    }[calendar["kind"]]
    return f"[{colour}]●[/] {calendar['name']}", f"[{MUTED}]{kind}[/]"


class EventModal(Modal[dict | None]):
    """An event: what, when, where, and anything else worth writing down.

    One dialog for making one and for changing one, because they are the same
    form with the fields already filled in. Dismisses with the fields, or
    None when nothing is to be saved.
    """

    BINDINGS = [("escape", "cancel", "Cancel"), ("ctrl+s", "save", "Save")]

    def __init__(self, heading: str, *, event: dict | None = None, day: dt.date | None = None,
                 where: str = "") -> None:
        super().__init__()
        self._heading = heading
        self._where = where
        event = event or {}
        whole_day = bool(event.get("all_day"))
        starts = str(event.get("starts_at") or "")
        ends = str(event.get("ends_at") or "")
        self._title = str(event.get("title") or "")
        self._date = starts[:10] or (day or dt.date.today()).isoformat()
        self._end_date = ends[:10] or self._date
        self._all_day = whole_day
        self._start_time = clock(starts) or "09:00"
        self._end_time = clock(ends) or "10:00"
        self._location = str(event.get("location") or "")
        self._notes = str(event.get("notes") or "")

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal modal-wide", id="event-modal"):
            yield Label(self._heading, classes="modal-title")
            if self._where:
                yield Static(f"[{MUTED}]in {self._where}[/]", classes="modal-detail")
            yield Input(value=self._title, placeholder="What is happening", id="event-title")
            # The fields are dates and times with nothing else to go on, so
            # they are captioned: a row of words above them, in the same
            # widths, rather than three boxes to guess at.
            with Horizontal(classes="event-labels"):
                yield Static(f"[{MUTED}]day[/]", id="label-day")
                yield Static(f"[{MUTED}]from[/]", id="label-from")
                yield Static("", classes="event-arrow")
                yield Static(f"[{MUTED}]to[/]", id="label-to")
            with Horizontal(classes="event-when"):
                yield Input(value=self._date, placeholder="2026-09-19", id="event-date")
                yield Input(value=self._start_time, placeholder="09:00", id="event-start")
                yield Static("→", classes="event-arrow")
                yield Input(value=self._end_time, placeholder="10:00", id="event-end")
            with Horizontal(classes="event-allday"):
                yield Switch(value=self._all_day, id="event-all-day")
                yield Static("All day", classes="event-allday-label")
                yield Static(f"[{MUTED}]to[/]", id="label-last")
                yield Input(
                    value=self._end_date, placeholder="last day", id="event-end-date"
                )
            yield Input(value=self._location, placeholder="Where", id="event-location")
            yield Input(value=self._notes, placeholder="Anything else", id="event-notes")
            yield Static("", id="event-complaint", classes="modal-detail")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self._show_times()
        field = self.query_one("#event-title", Input)
        field.focus()
        field.cursor_position = len(field.value)

    def on_switch_changed(self, event: Switch.Changed) -> None:
        event.stop()
        self._show_times()

    def _show_times(self) -> None:
        """An all-day event has days, not times; the fields say which it is."""
        whole = self.query_one("#event-all-day", Switch).value
        for selector in ("#event-start", "#event-end", "#label-from", "#label-to"):
            self.query_one(selector).display = not whole
        for arrow in self.query(".event-arrow"):
            arrow.display = not whole
        self.query_one("#event-end-date", Input).display = whole
        self.query_one("#label-last", Static).display = whole

    def _complain(self, message: str) -> None:
        self.query_one("#event-complaint", Static).update(f"[{BAD}]{message}[/]")

    def _collect(self) -> dict | None:
        title = self.query_one("#event-title", Input).value.strip()
        if not title:
            self._complain("An event needs a title.")
            self.query_one("#event-title", Input).focus()
            return None
        whole = self.query_one("#event-all-day", Switch).value
        date = self.query_one("#event-date", Input).value.strip()
        try:
            dt.date.fromisoformat(date)
        except ValueError:
            self._complain("The date is a date, as 2026-09-19.")
            self.query_one("#event-date", Input).focus()
            return None
        if whole:
            end = self.query_one("#event-end-date", Input).value.strip() or date
            try:
                dt.date.fromisoformat(end)
            except ValueError:
                self._complain("The last day is a date, as 2026-09-21.")
                return None
            starts, ends = date, end
        else:
            start_time = _time(self.query_one("#event-start", Input).value)
            end_time = _time(self.query_one("#event-end", Input).value)
            if start_time is None or end_time is None:
                self._complain("A time is a time, as 14:30.")
                return None
            starts, ends = f"{date}T{start_time}", f"{date}T{end_time}"
        if ends < starts:
            self._complain("It cannot end before it starts.")
            return None
        return {
            "title": title,
            "starts_at": starts,
            "ends_at": ends,
            "all_day": whole,
            "location": self.query_one("#event-location", Input).value.strip(),
            "notes": self.query_one("#event-notes", Input).value.strip(),
        }

    def action_save(self) -> None:
        collected = self._collect()
        if collected is not None:
            self.dismiss(collected)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "save":
            self.action_save()
        else:
            self.dismiss(None)


def _time(raw: str) -> str | None:
    """`9`, `930`, `9:30`, `09.30` — all of them the same time, or None.

    Typing a time should not be a format exercise: whatever somebody means
    by it, we mean too, and what we cannot read we say so about.
    """
    text = raw.strip().replace(".", ":")
    if not text:
        return None
    if ":" not in text:
        text = f"{text[:-2]}:{text[-2:]}" if len(text) > 2 else f"{text}:00"
    hour, _, minute = text.partition(":")
    try:
        return dt.time(int(hour), int(minute)).strftime("%H:%M")
    except ValueError:
        return None


class CalendarPane(Pane):
    """The calendars, the month across from them, and the day underneath."""

    TAB_LABEL = "Calendar"
    TAB_KEY = "f7"
    BINDINGS = [
        ("n", "fire('event')", "New event"),
        ("e", "fire('edit')", "Edit event"),
        ("delete", "fire('delete')", "Delete event"),
        ("c", "fire('calendar')", "New calendar"),
        ("s", "fire('share')", "Share"),
        ("l", "fire('leave')", "Leave"),
        ("t", "fire('today')", "Today"),
        Binding("[", "month(-1)", "Last month", show=False),
        Binding("]", "month(1)", "Next month", show=False),
    ]
    ACTIONS = (
        Action("event", "New event", "n", variant="primary", hint="On the day you are on"),
        Action("edit", "Edit", "e", hint="The event under the cursor"),
        Action("delete", "Delete", "del", variant="error"),
        Action("calendar", "New calendar", "c", hint="Shared, or one everybody is in"),
        Action("share", "Share", "s", hint="Put somebody in this calendar"),
        Action("leave", "Leave", "l"),
        Action("today", "Today", "t"),
    )

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._calendars: list[dict] = []
        self._events: list[dict] = []
        self._day = dt.date.today()
        self._shown = month_start(dt.date.today())
        # The calendar a new event goes in: whichever one the left-hand list
        # is standing on. Empty until the list has arrived.
        self._slug = ""
        # The days in the grid, in the order they were drawn, so a cell can
        # be turned back into a date.
        self._grid: list[list[dt.date]] = []

    # -- layout --------------------------------------------------------------
    def content(self) -> ComposeResult:
        with Horizontal(id="calendar-body"):
            with Vertical(id="calendar-list"):
                yield Static(f"[{MUTED}]calendars[/]", classes="pane-title")
                yield DataTable(id="calendar-table", cursor_type="row")
            with Vertical(id="month-pane"):
                yield Static("", id="month-title", classes="pane-title")
                yield DataTable(id="month-grid", cursor_type="cell")
                yield Static("", id="day-title", classes="pane-title")
                yield DataTable(id="day-table", cursor_type="row", show_header=False)

    def on_mount(self) -> None:
        self.query_one("#calendar-table", DataTable).add_columns("calendar", "who")
        grid = self.query_one("#month-grid", DataTable)
        for weekday in WEEKDAYS:
            grid.add_column(weekday, width=9)
        self.query_one("#day-table", DataTable).add_column("event")

    def on_show(self) -> None:
        self.reload()

    @property
    def me(self) -> str:
        return getattr(self.app, "username", "") or ""

    @property
    def calendar(self) -> dict | None:
        return next((c for c in self._calendars if c["slug"] == self._slug), None)

    @property
    def event(self) -> dict | None:
        """The event the cursor is on, down in the day's list."""
        table = self.query_one("#day-table", DataTable)
        row = table.cursor_row
        showing = self.day_events()
        return showing[row] if 0 <= row < len(showing) else None

    def day_events(self) -> list[dict]:
        """What is on the selected day, in the order the day happens."""
        return sorted(
            by_day(self._events).get(self._day, []),
            key=lambda e: (not e["all_day"], e["starts_at"]),
        )

    # -- loading ---------------------------------------------------------------
    @work(exclusive=True, group="calendar")
    async def reload(self) -> None:
        client = self.api
        if client is None:
            return
        try:
            self._calendars = await client.calendars()
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        if not any(c["slug"] == self._slug for c in self._calendars):
            self._slug = self._calendars[0]["slug"] if self._calendars else ""
        self._draw_calendars()
        await self._fetch_events()
        self._draw_month()
        self._draw_day()
        self.status()

    async def _fetch_events(self) -> None:
        """Everything in the weeks the month is drawn from, neighbours and all."""
        client = self.api
        if client is None:
            return
        weeks = weeks_of(self._shown)
        try:
            self._events = await client.events(
                start=weeks[0][0].isoformat(), end=weeks[-1][-1].isoformat()
            )
        except ApiError as exc:
            self._events = []
            self.status(str(exc), error=True)

    def _draw_calendars(self) -> None:
        table = self.query_one("#calendar-table", DataTable)
        table.clear()
        for calendar in self._calendars:
            table.add_row(*calendar_row(calendar, me=self.me))
        for row, calendar in enumerate(self._calendars):
            if calendar["slug"] == self._slug:
                table.move_cursor(row=row)
                break

    def _draw_month(self) -> None:
        filed = by_day(self._events)
        today = dt.date.today()
        grid = self.query_one("#month-grid", DataTable)
        grid.clear()
        self._grid = weeks_of(self._shown)
        for week in self._grid:
            grid.add_row(
                *(
                    cell_text(day, filed.get(day, []), shown=self._shown, today=today)
                    for day in week
                ),
                height=2,
            )
        self.query_one("#month-title", Static).update(
            f"[{ACCENT}]{self._shown.strftime('%B %Y')}[/]  "
            f"[{MUTED}][ ] move months, t for today[/]"
        )
        self._put_cursor_on_the_day()

    def _put_cursor_on_the_day(self) -> None:
        grid = self.query_one("#month-grid", DataTable)
        for row, week in enumerate(self._grid):
            if week[0] <= self._day <= week[-1]:
                grid.move_cursor(row=row, column=self._day.weekday())
                return

    def _draw_day(self) -> None:
        showing = self.day_events()
        self.query_one("#day-title", Static).update(
            f"[{ACCENT}]{self._day.strftime('%A %d %B')}[/]"
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
        # Where the cursor is now, not where it was when this was posted:
        # redrawing the table queues a highlight for row 0 that lands after
        # the cursor has been put back where it belongs.
        row = event.data_table.cursor_row
        if 0 <= row < len(self._calendars):
            self._slug = self._calendars[row]["slug"]
            self.status()

    def on_data_table_cell_highlighted(self, event: DataTable.CellHighlighted) -> None:
        if event.data_table.id != "month-grid":
            return
        # Where the cursor is now, not where it was when this was posted.
        # Filling the grid queues a highlight for the top-left cell — which
        # is a day of last month — and it lands after the cursor has been
        # put on the day we actually mean.
        here = event.data_table.cursor_coordinate
        row, column = here.row, here.column
        if not (0 <= row < len(self._grid) and 0 <= column < 7):
            return
        day = self._grid[row][column]
        if day == self._day:
            return
        self._day = day
        # Stepping off the end of a month is how you walk into the next one.
        if day.month != self._shown.month:
            self.show_month(month_start(day))
        else:
            self._draw_day()

    def action_month(self, step: int) -> None:
        self.show_month(month_start(shift_month(self._shown, step)))

    def show_month(self, first: dt.date) -> None:
        """Draw another month, and fetch what is on it."""
        self._shown = first
        if self._day.replace(day=1) != first:
            self._day = first
        self.load_month()

    @work(exclusive=True, group="calendar-month")
    async def load_month(self) -> None:
        await self._fetch_events()
        self._draw_month()
        self._draw_day()

    def act_today(self) -> None:
        self._day = dt.date.today()
        self.show_month(month_start(self._day))

    def act_refresh(self) -> None:
        self.reload()

    # -- the events ---------------------------------------------------------------
    def act_event(self) -> None:
        calendar = self.calendar
        if calendar is None:
            self.status("No calendar to put it in yet.", error=True)
            return
        self.app.push_screen(
            EventModal(
                f"New event · {self._day.strftime('%a %d %B')}",
                day=self._day,
                where=calendar["name"],
            ),
            self._made_event,
        )

    @work(group="calendar-add")
    async def _made_event(self, fields: dict | None) -> None:
        client = self.api
        if client is None or not fields or not self._slug:
            return
        try:
            await client.create_event(self._slug, **fields)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.status(f"{fields['title']} is in.")
        self.reload()

    def act_edit(self) -> None:
        event = self.event
        if event is None:
            self.status("Nothing to edit on this day.", error=True)
            return
        self.app.push_screen(
            EventModal("Edit event", event=event, where=event["calendar_name"]),
            lambda fields: self._save_event(event["id"], fields),
        )

    @work(group="calendar-edit")
    async def _save_event(self, event_id: int, fields: dict | None) -> None:
        client = self.api
        if client is None or not fields:
            return
        try:
            await client.edit_event(event_id, **fields)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.status("Changed.")
        self.reload()

    def act_delete(self) -> None:
        event = self.event
        if event is None:
            self.status("Nothing to delete on this day.", error=True)
            return
        self.app.push_screen(
            ConfirmModal(
                f"Delete “{event['title']}”?",
                detail=f"{when_said(event)} on {event['calendar_name']}. This cannot be undone.",
            ),
            lambda yes: self._delete_event(event["id"], yes),
        )

    @work(group="calendar-delete")
    async def _delete_event(self, event_id: int, confirmed: bool | None) -> None:
        client = self.api
        if client is None or not confirmed:
            return
        try:
            await client.delete_event(event_id)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.status("Gone.")
        self.reload()

    # -- the calendars ----------------------------------------------------------------
    def act_calendar(self) -> None:
        self.app.push_screen(
            PromptModal(
                "New calendar",
                placeholder="Household",
                detail="Shared: yours until you put somebody in it. Press s to share it.",
            ),
            self._make_calendar,
        )

    @work(group="calendar-make")
    async def _make_calendar(self, name: str | None) -> None:
        client = self.api
        if client is None or not name or not name.strip():
            return
        try:
            made = await client.create_calendar(name.strip(), kind="shared")
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self._slug = made["slug"]
        self.status(f"{made['name']} is yours. Press s to share it.")
        self.reload()

    def act_share(self) -> None:
        calendar = self.calendar
        if calendar is None:
            return
        if calendar["kind"] != "shared":
            self.status(
                "Everybody is already in a public calendar."
                if calendar["kind"] == "public"
                else "Your own calendar is yours; make a shared one to share.",
                error=True,
            )
            return
        self.app.push_screen(
            PromptModal(
                f"Share {calendar['name']}",
                placeholder="username",
                detail="They are added, not invited — they will be told.",
            ),
            self._add_member,
        )

    @work(group="calendar-share")
    async def _add_member(self, username: str | None) -> None:
        client = self.api
        if client is None or not username or not username.strip():
            return
        try:
            added = await client.add_calendar_members(self._slug, [username.strip().lower()])
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        who = added.get("added") or []
        self.status(f"{who[0]} is in." if who else "They were already in it.")
        self.reload()

    def act_leave(self) -> None:
        calendar = self.calendar
        if calendar is None:
            return
        if calendar["kind"] != "shared":
            self.status(
                "A public calendar is everybody's; you cannot leave it."
                if calendar["kind"] == "public"
                else "Your own calendar stays yours.",
                error=True,
            )
            return
        if calendar["mine"]:
            self.app.push_screen(
                ConfirmModal(
                    f"Delete {calendar['name']}?",
                    detail="You made this one, so leaving it is deleting it — "
                    "for everybody in it, events and all.",
                ),
                self._delete_calendar,
            )
            return
        self.app.push_screen(
            ConfirmModal(
                f"Leave {calendar['name']}?",
                detail="You will stop seeing what is on it. Somebody can add you back.",
                confirm_label="Leave",
            ),
            self._leave_calendar,
        )

    @work(group="calendar-leave")
    async def _leave_calendar(self, confirmed: bool | None) -> None:
        client = self.api
        if client is None or not confirmed:
            return
        try:
            await client.leave_calendar(self._slug)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self._slug = ""
        self.reload()

    @work(group="calendar-delete-one")
    async def _delete_calendar(self, confirmed: bool | None) -> None:
        client = self.api
        if client is None or not confirmed:
            return
        try:
            await client.delete_calendar(self._slug)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self._slug = ""
        self.reload()

    # -- what the bottom bar says --------------------------------------------------------
    def status_detail(self) -> str:
        calendar = self.calendar
        if calendar is None:
            return f"[{MUTED}]no calendars[/]"
        colour = colour_for(calendar["colour"])
        return (
            f"new events go in [{colour}]{calendar['name']}[/]  "
            f"[{MUTED}]{len(self._events)} this month[/]"
        )


__all__ = [
    "CalendarPane",
    "EventModal",
    "by_day",
    "calendar_row",
    "cell_text",
    "day_lines",
    "event_line",
    "days_of",
    "shift_month",
    "weeks_of",
    "when_said",
]
