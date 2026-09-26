"""The kit's `calendar` in the terminal: the calendars, the month beside them, the day below.

Drawn from the Calendar Quill's screen, against the fake server's record
store: the same promises the built-in calendar pane kept, now kept by a
kit element that knows no calendar by name.
"""

from __future__ import annotations

import copy
import datetime as dt

from textual.widgets import Checkbox, DataTable, Input, Select, Static

from cloudmorrow.tui.panes.kit_calendar import (
    CalendarPane,
    by_day,
    cell_text,
    event_line,
    settle_times,
    shift_month,
    space_row,
    wall,
    weeks_of,
    when_said,
)
from cloudmorrow.tui.screens.modals import ConfirmModal
from cloudmorrow.tui.screens.record_sheet import RecordSheet
from cloudmorrow.tui.widgets.kit_space import NewSpaceModal, SpaceModal
from tests.tui_harness import feature_row, settle, start
from tests.tui_quills import CALENDAR_MODELS, CALENDAR_QUILL, TODAY, calendar_records

B = {"starts": "starts_at", "ends": "ends_at", "all_day": "all_day", "space": "calendar",
     "colour": "colour", "title": "title", "subtitle": "location"}


def with_calendar(app) -> None:
    app.client.quill_list.append(copy.deepcopy(CALENDAR_QUILL))
    app.client.feature_list.append(feature_row("calendar", "Calendar"))
    app.client.record_store.update(calendar_records())


async def open_calendar(app, pilot):
    screen = await start(app, pilot)
    await pilot.click("#nav-calendar")
    await settle(app, pilot)
    return screen, screen.query_one(CalendarPane)


async def modal_up(pilot) -> None:
    # settle() waits for every worker, and the one that opened a dialog is
    # waiting for it to close: two pauses let the dialog land instead.
    await pilot.pause()
    await pilot.pause()


def thing(starts: str, ends: str, **extra) -> dict:
    return {"all_day": False, "starts": starts, "ends": ends, "colour": "cyan", "title": "Thing",
            "subtitle": "", "space_name": "bram", "owner": "bram", **extra}


# -- what a day and a month say -----------------------------------------------------------
def test_a_month_is_drawn_in_whole_weeks():
    weeks = weeks_of(dt.date(2026, 9, 19))
    assert all(len(week) == 7 for week in weeks)
    assert weeks[0][0].weekday() == 0 and weeks[0][0] <= dt.date(2026, 9, 1)
    assert weeks[-1][-1] >= dt.date(2026, 9, 30)


def test_moving_months_lands_on_a_real_date():
    assert shift_month(dt.date(2026, 1, 31), 1) == dt.date(2026, 2, 28)
    assert shift_month(dt.date(2026, 12, 15), 1) == dt.date(2027, 1, 15)


def test_a_day_wears_a_dot_for_each_thing_on_it_in_its_colour():
    events = [thing("2026-09-19T10:00", "2026-09-19T11:00", colour="violet")] * 4
    text = cell_text(dt.date(2026, 9, 19), events, shown=dt.date(2026, 9, 1), today=dt.date(2026, 9, 1))
    assert text.count("●") == 3 and "+1" in text and "#a78bfa" in text


def test_how_long_a_thing_lasts_is_said_in_the_fewest_words():
    assert when_said(thing("2026-09-19T10:00", "2026-09-19T11:30")) == "10:00–11:30"
    assert when_said(thing("2026-09-19", "2026-09-19", all_day=True)) == "all day"
    assert when_said(thing("2026-09-19", "2026-09-21", all_day=True)) == "all day, to 2026-09-21"


def test_a_line_is_one_line_its_title_is_not_markup_and_it_says_whose():
    line = event_line(thing("2026-09-19T10:00", "2026-09-19T11:00", title="[b]x", owner="guest",
                            space_name="Household"), me="bram")
    assert "\\[b]x" in line and "\n" not in line and "Household · guest" in line


def test_a_thing_is_filed_under_every_day_it_covers():
    filed = by_day([thing("2026-09-19", "2026-09-21", all_day=True)])
    assert sorted(filed) == [dt.date(2026, 9, 19), dt.date(2026, 9, 20), dt.date(2026, 9, 21)]


def test_a_calendar_says_who_it_is_for():
    rows = calendar_records()["calendar"]
    model = CALENDAR_MODELS["calendar"]
    assert "only you" in space_row(rows[0], model, "colour", me="bram")[1]
    assert "2 people" in space_row(rows[1], model, "colour", me="bram")[1]
    assert "everyone" in space_row(rows[2], model, "colour", me="bram")[1]


def test_the_wall_clock_is_drawn_as_it_is_and_a_zone_is_converted():
    assert wall("2026-09-19T10:00") == "2026-09-19T10:00"
    assert wall("2026-09-19") == "2026-09-19"
    zoned = dt.datetime(2026, 9, 19, 10, tzinfo=dt.UTC)
    assert wall(zoned.isoformat()) == zoned.astimezone().strftime("%Y-%m-%dT%H:%M")


def test_time_keeps_its_shape_when_it_is_changed():
    was = {"fields": {"starts_at": "2026-09-19T10:00", "ends_at": "2026-09-19T11:00", "all_day": False}}
    # Moving the start drags the end along.
    assert settle_times(B, {"starts_at": "2026-09-19T11:30"}, was)["ends_at"] == "2026-09-19T12:30"
    # Whole days are dates.
    whole = settle_times(B, {"all_day": True}, was)
    assert (whole["starts_at"], whole["ends_at"]) == ("2026-09-19", "2026-09-19")
    # And a timed thing again is an hour from nine.
    day = {"fields": {"starts_at": "2026-09-19", "ends_at": "2026-09-20", "all_day": True}}
    timed = settle_times(B, {"all_day": False}, day)
    assert (timed["starts_at"], timed["ends_at"]) == ("2026-09-19T09:00", "2026-09-19T10:00")
    # An end before the start is the start.
    assert settle_times(B, {"ends_at": "2026-09-19T09:00"}, was)["ends_at"] == "2026-09-19T10:00"


# -- the pane ---------------------------------------------------------------------------------
async def test_the_calendars_are_listed_with_your_own_at_the_top(app):
    with_calendar(app)
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        table = pane.query_one("#calendar-table", DataTable)
        assert table.row_count == 3
        assert "bram" in str(table.get_row_at(0)[0])
        # New things go in whichever one the list is standing on: your own.
        assert pane.space_id == "r_mine"


async def test_the_month_opens_on_this_one_and_the_day_on_today(app):
    with_calendar(app)
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        assert TODAY.strftime("%B %Y") in pane.query_one("#month-title", Static).render().plain
        assert TODAY.strftime("%A") in pane.query_one("#day-title", Static).render().plain


async def test_the_day_shows_everything_on_it_whatever_calendar_it_is_in(app):
    with_calendar(app)
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        assert [e["title"] for e in pane.day_events()] == ["Bins out", "Dentist"]
        table = pane.query_one("#day-table", DataTable)
        assert "High Street" in str(table.get_row_at(1)[0])
        assert len(pane.events) == 3
        # It asked for the weeks of the month, with a range on each moment.
        model, where = next(call for call in app.client.record_calls if call[0] == "event")
        assert set(where) == {"starts_at__lte", "ends_at__gte"}


async def test_stepping_to_the_next_month_asks_for_it(app):
    with_calendar(app)
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        pane.query_one("#month-grid", DataTable).focus()
        await pilot.press("]")
        await settle(app, pilot)
        nxt = shift_month(TODAY.replace(day=1), 1)
        assert nxt.strftime("%B %Y") in pane.query_one("#month-title", Static).render().plain
        await pilot.press("t")
        await settle(app, pilot)
        assert pane.day == TODAY


async def test_a_new_thing_goes_in_the_calendar_the_list_is_on_on_the_day_you_are_on(app):
    with_calendar(app)
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        pane.query_one("#calendar-table", DataTable).focus()
        await pilot.press("down")
        await settle(app, pilot)
        assert pane.space_id == "r_house"
        pane.fire("new_record")
        await modal_up(pilot)
        sheet = app.screen
        assert isinstance(sheet, RecordSheet)
        sheet.query_one("#field-title", Input).value = "Plumber"
        sheet.query_one("#field-starts_at", Input).value = f"{TODAY} 09:30"
        await sheet.action_save()
        await settle(app, pilot)
        made = next(row for row in app.client.record_store["event"] if row["fields"]["title"] == "Plumber")
        assert made["fields"]["calendar"] == "r_house"
        # Typed without a zone: the time on the wall, as typed.
        assert made["fields"]["starts_at"] == f"{TODAY}T09:30"
        assert made["fields"]["ends_at"] == f"{TODAY}T10:00"


async def test_opening_the_thing_under_the_cursor_is_its_record_sheet(app):
    with_calendar(app)
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        pane.query_one("#day-table", DataTable).focus()
        await pilot.press("down")
        pane.fire("open_record")
        await modal_up(pilot)
        sheet = app.screen
        assert isinstance(sheet, RecordSheet)
        assert sheet.record["id"] == "r_dentist"
        # The calendar is a choice of the ones you can see, by name.
        choices = sheet.query_one("#field-calendar", Select)
        assert choices.value == "r_mine"
        assert sheet.query_one("#field-starts_at", Input).value == f"{TODAY} 10:00"
        sheet.query_one("#field-starts_at", Input).value = f"{TODAY} 14:00"
        await sheet.action_save()
        await settle(app, pilot)
        dentist = next(r for r in app.client.record_store["event"] if r["id"] == "r_dentist")
        assert (dentist["fields"]["starts_at"], dentist["fields"]["ends_at"]) == (
            f"{TODAY}T14:00", f"{TODAY}T15:00")


async def test_deleting_a_thing_asks_first(app):
    with_calendar(app)
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        pane.fire("delete_record")
        await modal_up(pilot)
        assert isinstance(app.screen, ConfirmModal)
        await pilot.click("#confirm")
        await settle(app, pilot)
        assert "r_bins" not in [r["id"] for r in app.client.record_store["event"]]


async def test_making_a_calendar_asks_its_name_who_sees_it_and_who_is_in_it(app):
    with_calendar(app)
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        pane.fire("new_space")
        await modal_up(pilot)
        modal = app.screen
        assert isinstance(modal, NewSpaceModal)
        modal.query_one("#space-name", Input).value = "Work trips"
        modal.query_one("#person-guest", Checkbox).value = True
        modal.action_save()
        await settle(app, pilot)
        made = next(r for r in app.client.record_store["calendar"] if r["fields"]["name"] == "Work trips")
        assert made["scope"] == "shared" and made["members"] == ["guest"]
        # A colour nobody has yet.
        assert made["fields"]["colour"] == "amber"
        assert pane.space_id == made["id"]


async def test_the_people_in_a_calendar_are_added_and_you_can_leave_one(app):
    with_calendar(app)
    for row in app.client.record_store["calendar"]:
        if row["id"] == "r_house":
            row.update(owner="guest", can_manage=False, members=["bram"])
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        pane.query_one("#calendar-table", DataTable).focus()
        await pilot.press("down")
        await settle(app, pilot)
        pane.fire("people")
        await modal_up(pilot)
        modal = app.screen
        assert isinstance(modal, SpaceModal)
        modal.query_one("#space-add-who", Select).value = "ada"
        await modal.add()
        await pilot.pause()
        assert ("add:r_house", {"username": "ada"}) in app.client.record_calls
        await pilot.click("#space-leave")
        await modal_up(pilot)
        await pilot.click("#confirm")
        await settle(app, pilot)
        assert ("remove:r_house", {"username": "bram"}) in app.client.record_calls


async def test_your_own_calendar_has_nobody_to_add_and_no_way_out(app):
    with_calendar(app)
    async with app.run_test(size=(140, 40)) as pilot:
        _, pane = await open_calendar(app, pilot)
        pane.fire("people")
        await modal_up(pilot)
        modal = app.screen
        assert isinstance(modal, SpaceModal)
        assert modal.query_one("#space-add").display is False
        assert modal.query_one("#space-leave").display is False
        assert "only you" in modal.query_one("#space-scope-line", Static).render().plain


async def test_the_tab_is_gone_when_the_server_has_the_calendar_switched_off(app):
    with_calendar(app)
    app.client.feature_list[-1]["enabled"] = False
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await start(app, pilot)
        assert screen.query_one("#nav-calendar").display is False


async def test_it_has_the_key_the_calendar_always_had(app):
    with_calendar(app)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await start(app, pilot)
        # Tasks first, as a server that had both gets them, and then Calendar.
        assert screen._quill_keys == {"tasks": "f2", "calendar": "f7"}
        screen.action_quill_key("f7")
        await settle(app, pilot)
        assert screen.query_one("#panes").current == "pane-calendar"
