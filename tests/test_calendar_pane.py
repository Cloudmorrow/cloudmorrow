"""The Calendar tab: the calendars, the month beside them, and the day below."""

from __future__ import annotations

import datetime as dt

from textual.widgets import DataTable, Input, Static, Switch

from cloudmorrow.tui.panes.calendar import (
    CalendarPane,
    EventModal,
    _time,
    by_day,
    calendar_row,
    cell_text,
    event_line,
    shift_month,
    weeks_of,
    when_said,
)
from cloudmorrow.tui.screens.modals import ConfirmModal, PromptModal
from tests.tui_harness import TODAY, TOMORROW, settle, start


async def open_calendar(app, pilot):
    screen = await start(app, pilot)
    await pilot.click("#nav-calendar")
    await settle(app, pilot)
    return screen, screen.query_one(CalendarPane)


def timed(starts: str, ends: str, **extra) -> dict:
    return {
        "all_day": False, "starts_at": starts, "ends_at": ends, "colour": "cyan",
        "title": "Thing", "location": "", "notes": "", "calendar_name": "Jimmi",
        "created_by": "bram", **extra,
    }


# -- the month, and what a day says -------------------------------------------------
def test_a_month_is_drawn_in_whole_weeks():
    weeks = weeks_of(dt.date(2026, 9, 15))
    assert all(len(week) == 7 for week in weeks)
    assert weeks[0][0].weekday() == 0, "a week starts on Monday"
    # September 2026 starts on a Tuesday, so the week it is in reaches back
    # into August — the days either side are there to make the weeks whole.
    assert weeks[0][0] == dt.date(2026, 8, 31)
    assert dt.date(2026, 9, 1) in weeks[0]
    assert dt.date(2026, 9, 30) in weeks[-1]


def test_moving_months_lands_on_a_real_date():
    assert shift_month(dt.date(2026, 1, 31), 1) == dt.date(2026, 2, 28)
    assert shift_month(dt.date(2026, 1, 15), -1) == dt.date(2025, 12, 15)
    assert shift_month(dt.date(2026, 12, 15), 1) == dt.date(2027, 1, 15)


def test_a_day_wears_a_dot_for_each_thing_on_it():
    day = dt.date(2026, 9, 19)
    empty = cell_text(day, [], shown=day, today=dt.date(2026, 9, 1))
    assert empty.strip() == "19", "a quiet day is just its number"
    busy = cell_text(
        day, [{"colour": "cyan"}, {"colour": "rose"}], shown=day, today=dt.date(2026, 9, 1)
    )
    assert busy.count("●") == 2
    # Beyond three, the rest are counted rather than drawn.
    many = cell_text(day, [{"colour": "cyan"}] * 6, shown=day, today=dt.date(2026, 9, 1))
    assert many.count("●") == 3
    assert "+3" in many


def test_today_and_the_neighbouring_months_are_marked():
    day = dt.date(2026, 9, 19)
    assert "b " in cell_text(day, [], shown=day, today=day), "today is bold"
    spill = cell_text(dt.date(2026, 10, 1), [], shown=day, today=dt.date(2026, 9, 1))
    assert "#99a1b3" in spill, "a day from the next month is dimmed"


def test_how_long_a_thing_lasts_is_said_in_the_fewest_words():
    assert when_said(timed("2026-09-19T10:00", "2026-09-19T11:00")) == "10:00–11:00"
    assert when_said({"all_day": True, "starts_at": "2026-09-19", "ends_at": "2026-09-19"}) == (
        "all day"
    )
    assert "to 2026-09-21" in when_said(
        {"all_day": True, "starts_at": "2026-09-19", "ends_at": "2026-09-21"}
    )
    assert "→" in when_said(timed("2026-09-19T23:00", "2026-09-20T01:00"))


def test_an_event_is_one_line_and_its_title_is_not_markup():
    line = event_line(timed("2026-09-19T10:00", "2026-09-19T11:00", title="try [b]this[/b]"),
                      me="bram")
    assert "\n" not in line, "one line, because the cursor moves a row at a time"
    assert r"\[b]this\[/b]" in line


def test_somebody_elses_event_says_whose_it_is():
    mine = event_line(timed("2026-09-19T10:00", "2026-09-19T11:00"), me="bram")
    theirs = event_line(
        timed("2026-09-19T10:00", "2026-09-19T11:00", created_by="guest"), me="bram"
    )
    assert "guest" not in mine
    assert "guest" in theirs


def test_an_event_is_filed_under_every_day_it_covers():
    filed = by_day([{"starts_at": "2026-09-19", "ends_at": "2026-09-21"}])
    assert sorted(filed) == [dt.date(2026, 9, 19), dt.date(2026, 9, 20), dt.date(2026, 9, 21)]


def test_a_calendar_says_who_it_is_for():
    assert "mine" in calendar_row(
        {"name": "Jimmi", "kind": "personal", "colour": "cyan", "owner": "bram", "members": []},
        me="bram",
    )[1]
    assert "everyone" in calendar_row(
        {"name": "Holidays", "kind": "public", "colour": "green", "owner": "bram",
         "members": ["bram", "guest"]},
        me="bram",
    )[1]
    assert "2 people" in calendar_row(
        {"name": "Household", "kind": "shared", "colour": "violet", "owner": "bram",
         "members": ["bram", "guest"]},
        me="bram",
    )[1]


def test_a_time_is_read_however_it_is_typed():
    assert _time("9") == "09:00"
    assert _time("930") == "09:30"
    assert _time("09.30") == "09:30"
    assert _time("14:30") == "14:30"
    assert _time("half nine") is None
    assert _time("25:00") is None


# -- the pane ------------------------------------------------------------------------
async def test_the_calendars_are_listed_with_your_own_at_the_top(app):
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        table = pane.query_one("#calendar-table", DataTable)
        assert table.row_count == 3
        assert "Jimmi" in str(table.get_row_at(0)[0])
        # New events go in whichever one the list is standing on.
        assert pane._slug == "my-bram"


async def test_the_month_opens_on_this_one_and_the_day_on_today(app):
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        title = pane.query_one("#month-title", Static).render().plain
        assert TODAY.strftime("%B %Y") in title
        assert TODAY.strftime("%A") in pane.query_one("#day-title", Static).render().plain


async def test_the_day_shows_everything_on_it_whatever_calendar_it_is_on(app):
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        titles = [e["title"] for e in pane.day_events()]
        # All-day first, then by the time it starts: the order the day happens.
        assert titles == ["Bins out", "Dentist"]
        table = pane.query_one("#day-table", DataTable)
        assert table.row_count == 2
        assert "High Street" in str(table.get_row_at(1)[0])
        # Tomorrow's is not today's, but it is in the month.
        assert "Boiler service" not in [e["title"] for e in pane.day_events()]
        assert len(pane._events) == 3


async def test_stepping_to_the_next_month_asks_for_it(app):
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        pane.query_one("#month-grid", DataTable).focus()
        await pilot.press("]")
        await settle(app, pilot)
        nxt = shift_month(TODAY.replace(day=1), 1)
        assert nxt.strftime("%B %Y") in pane.query_one("#month-title", Static).render().plain
        await pilot.press("t")
        await settle(app, pilot)
        assert pane._day == TODAY


async def test_a_new_event_goes_in_the_calendar_the_list_is_on(app):
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        table = pane.query_one("#calendar-table", DataTable)
        table.focus()
        await pilot.press("down")
        await settle(app, pilot)
        assert pane._slug == "household"

        pane.fire("event")
        await settle(app, pilot)
        modal = app.screen
        assert isinstance(modal, EventModal)
        modal.query_one("#event-title", Input).value = "Boiler service"
        modal.query_one("#event-start", Input).value = "930"
        modal.query_one("#event-end", Input).value = "1030"
        await pilot.press("ctrl+s")
        await settle(app, pilot)

        kind, slug, fields = app.client.event_calls[0]
        assert (kind, slug) == ("create", "household")
        assert fields["title"] == "Boiler service"
        assert fields["starts_at"] == f"{TODAY}T09:30"
        assert fields["ends_at"] == f"{TODAY}T10:30"
        assert fields["all_day"] is False


async def test_an_all_day_event_is_dates_rather_than_times(app):
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        pane.fire("event")
        await settle(app, pilot)
        modal = app.screen
        modal.query_one("#event-title", Input).value = "Away"
        modal.query_one("#event-all-day", Switch).value = True
        modal.query_one("#event-end-date", Input).value = str(TOMORROW)
        await pilot.press("ctrl+s")
        await settle(app, pilot)
        _, _, fields = app.client.event_calls[0]
        assert (fields["starts_at"], fields["ends_at"]) == (str(TODAY), str(TOMORROW))
        assert fields["all_day"] is True


async def test_an_event_with_no_title_keeps_the_dialog_open(app):
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        pane.fire("event")
        await settle(app, pilot)
        await pilot.press("ctrl+s")
        await settle(app, pilot)
        assert isinstance(app.screen, EventModal), "nothing typed is thrown away"
        assert app.client.event_calls == []


async def test_an_event_that_ends_before_it_starts_is_refused_here(app):
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        pane.fire("event")
        await settle(app, pilot)
        modal = app.screen
        modal.query_one("#event-title", Input).value = "Backwards"
        modal.query_one("#event-start", Input).value = "10:00"
        modal.query_one("#event-end", Input).value = "09:00"
        await pilot.press("ctrl+s")
        await settle(app, pilot)
        assert isinstance(app.screen, EventModal)
        assert "end before" in app.screen.query_one("#event-complaint", Static).render().plain
        assert app.client.event_calls == []


async def test_editing_the_event_under_the_cursor(app):
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        day = pane.query_one("#day-table", DataTable)
        day.focus()
        await pilot.press("down")
        await settle(app, pilot)
        assert pane.event["title"] == "Dentist"

        pane.fire("edit")
        await settle(app, pilot)
        modal = app.screen
        assert isinstance(modal, EventModal)
        assert modal.query_one("#event-title", Input).value == "Dentist"
        assert modal.query_one("#event-start", Input).value == "10:00"
        modal.query_one("#event-location", Input).value = "The clinic"
        await pilot.press("ctrl+s")
        await settle(app, pilot)
        kind, event_id, fields = app.client.event_calls[0]
        assert (kind, event_id) == ("edit", 1)
        assert fields["location"] == "The clinic"


async def test_deleting_an_event_asks_first(app):
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        pane.query_one("#day-table", DataTable).focus()
        await settle(app, pilot)
        target = pane.event
        pane.fire("delete")
        await settle(app, pilot)
        assert isinstance(app.screen, ConfirmModal)
        await pilot.click("#confirm")
        await settle(app, pilot)
        assert ("delete", target["id"], None) in app.client.event_calls
        assert target["id"] not in [e["id"] for e in app.client.event_list]


async def test_making_a_calendar_asks_for_a_name_and_stands_on_it(app):
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        pane.fire("calendar")
        await settle(app, pilot)
        assert isinstance(app.screen, PromptModal)
        app.screen.query_one(Input).value = "Work trips"
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.client.calendar_calls[0] == ("create", "work-trips", "shared")
        assert pane._slug == "work-trips"


async def test_your_own_calendar_and_a_public_one_cannot_be_shared_or_left(app):
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        assert pane.calendar["kind"] == "personal"
        pane.fire("share")
        await settle(app, pilot)
        assert not isinstance(app.screen, PromptModal), "your own is yours"
        pane.fire("leave")
        await settle(app, pilot)
        assert not isinstance(app.screen, ConfirmModal)

        pane.query_one("#calendar-table", DataTable).focus()
        await pilot.press("down", "down")
        await settle(app, pilot)
        assert pane.calendar["kind"] == "public"
        pane.fire("share")
        await settle(app, pilot)
        assert not isinstance(app.screen, PromptModal), "everybody is already in it"
        assert app.client.calendar_calls == []


async def test_sharing_a_calendar_puts_somebody_in_it(app):
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        pane.query_one("#calendar-table", DataTable).focus()
        await pilot.press("down")
        await settle(app, pilot)
        pane.fire("share")
        await settle(app, pilot)
        assert isinstance(app.screen, PromptModal)
        app.screen.query_one(Input).value = "Guest"
        await pilot.press("enter")
        await settle(app, pilot)
        # Lowercased on the way out, the way a username is everywhere else.
        assert app.client.calendar_calls[0] == ("share", "household", ["guest"])


async def test_leaving_a_calendar_you_made_is_deleting_it(app):
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        pane.query_one("#calendar-table", DataTable).focus()
        await pilot.press("down")
        await settle(app, pilot)
        assert pane.calendar["mine"] is True

        pane.fire("leave")
        await settle(app, pilot)
        assert isinstance(app.screen, ConfirmModal)
        await pilot.click("#confirm")
        await settle(app, pilot)
        assert ("delete", "household", None) in app.client.calendar_calls
        assert "household" not in [c["slug"] for c in app.client.calendar_list]


async def test_a_calendar_somebody_else_made_is_left_rather_than_deleted(app):
    for row in app.client.calendar_list:
        if row["slug"] == "household":
            row.update(owner="guest", mine=False)
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        pane.query_one("#calendar-table", DataTable).focus()
        await pilot.press("down")
        await settle(app, pilot)
        pane.fire("leave")
        await settle(app, pilot)
        await pilot.click("#confirm")
        await settle(app, pilot)
        assert ("leave", "household", None) in app.client.calendar_calls


async def test_the_tab_is_gone_when_the_server_has_the_calendar_switched_off(app):
    for row in app.client.feature_list:
        if row["key"] == "calendar":
            row["enabled"] = False
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await start(app, pilot)
        assert screen.query_one("#nav-calendar").display is False
