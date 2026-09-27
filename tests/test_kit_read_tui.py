"""Read drawn as read, in the terminal (docs/CIRCLES.md, *What a Quill does with it*).

The server fits every Quill to the person asking: each datamodel carries
their `access`, and on one they may only read, every kit screen is the same
screen without its writing. These are that, kit by kit: the board opens its
cards and moves none, the record sheet shows and saves nothing, the thread
has no line to type in, the grid gets files and puts none — and each only as
far as its own datamodel says, so writing tasks on a board you may only read
still makes tasks. A Quill with nothing left is not there at all.

The refused keys are pressed, not only looked for in the footer: a key that
is merely hidden but still works would be a hole, not a courtesy.

A dialog open holds its worker open, so while one is up these wait with two
pauses rather than `settle()`.
"""

from __future__ import annotations

from textual.widgets import Button, Input, Static, Tabs

from cloudmorrow.tui.panes.kit import ListPane
from cloudmorrow.tui.panes.kit_board import NEW_GROUP_TAB, BoardPane
from cloudmorrow.tui.panes.kit_editor import EditorPane
from cloudmorrow.tui.panes.kit_grid import GridPane
from cloudmorrow.tui.panes.kit_thread import ThreadPane
from cloudmorrow.tui.screens.record_sheet import RecordSheet
from cloudmorrow.tui.widgets.editor import LiveMarkdownEditor
from cloudmorrow.tui.widgets.kit import can_write
from cloudmorrow.tui.widgets.kit_space import SpaceModal
from cloudmorrow.tui.widgets.note_tree import NoteTree
from tests.test_board import drag, titles
from tests.test_kit_calendar_tui import open_calendar, with_calendar
from tests.test_kit_grid_tui import into_holiday
from tests.test_kit_tui import open_reading
from tests.tui_harness import settle, start
from tests.tui_notes import note_id


async def breathe(pilot) -> None:
    await pilot.pause()
    await pilot.pause()


def only_read(app, quill_id: str, *models: str) -> None:
    """What the server sends somebody whose circles give *models* as read."""
    quill = next(q for q in app.client.quill_list if q["id"] == quill_id)
    for model_id in models:
        quill["models"][model_id]["access"] = "read"


def toolbar(pane) -> list[str]:
    return [(button.id or "")[len("do-"):] for button in pane.query(".toolbar Button")]


def test_read_is_read_and_everything_else_is_write():
    assert can_write({"id": "task", "access": "write"})
    assert not can_write({"id": "task", "access": "read"})
    # A server without circles says nothing, and there everybody has everything.
    assert can_write({"id": "task"})
    # A datamodel that is not there is nobody's to write.
    assert not can_write(None)
    assert not can_write({})


# -- the board ---------------------------------------------------------------------


async def test_a_board_you_may_only_read_is_looked_at(app):
    only_read(app, "tasks", "task", "board")
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await start(app, pilot)
        await pilot.click("#nav-tasks")
        await settle(app, pilot)
        pane = screen.query_one(BoardPane)

        assert toolbar(pane) == []
        assert not pane.query(f"#{NEW_GROUP_TAB}")
        tabs = [t.id for t in pane.query_one(Tabs).query("Tab")]
        assert tabs == ["group-r_homelab", "group-r_errands"]


        # ctrl+n and ctrl+b are there on a board you write; here they do nothing.
        await pilot.press("ctrl+n")
        await pilot.press("ctrl+b")
        await breathe(pilot)
        assert app.screen is screen

        todo, doing = pane.lane_widget("todo"), pane.lane_widget("doing")
        before = titles(todo)
        card = todo.cards()[0]
        card.focus()
        await pilot.press("right_square_bracket")
        await pilot.press("space")
        await settle(app, pilot)
        # A card that cannot move is not dragged: pressing and letting go
        # anywhere is a click, and opens it.
        await drag(pilot, pane.lane_widget("todo").cards()[0], doing)
        await breathe(pilot)
        assert isinstance(app.screen, RecordSheet)
        app.screen.action_cancel()
        await settle(app, pilot)
        assert titles(pane.lane_widget("todo")) == before

        assert all(row["rev"] == 1 for row in app.client.record_store["task"])


async def test_writing_tasks_on_boards_you_may_only_read(app):
    """Per datamodel: tasks may be made, boards may not."""
    only_read(app, "tasks", "board")
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await start(app, pilot)
        await pilot.click("#nav-tasks")
        await settle(app, pilot)
        pane = screen.query_one(BoardPane)

        assert toolbar(pane) == ["new_record"]
        assert not pane.query(f"#{NEW_GROUP_TAB}")
        await pilot.press("ctrl+b")
        await breathe(pilot)
        assert app.screen is screen

        # The card still moves: the lane is the task's.
        card = pane.lane_widget("todo").cards()[0]
        title = card.fields["title"]
        card.focus()
        await pilot.press("right_square_bracket")
        await settle(app, pilot)
        assert title in titles(pane.lane_widget("doing"))


# -- the record sheet --------------------------------------------------------------


async def test_the_sheet_of_a_record_you_may_only_read_shows_it_and_saves_nothing(app):
    only_read(app, "tasks", "task")
    seen: list[tuple] = []

    async def spy(*args, **kwargs):
        seen.append(args)

    app.client.update_record = spy
    app.client.delete_record = spy
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await start(app, pilot)
        await pilot.click("#nav-tasks")
        await settle(app, pilot)
        card = screen.query_one(BoardPane).lane_widget("todo").cards()[0]
        await pilot.click(card)
        await breathe(pilot)
        sheet = app.screen
        assert isinstance(sheet, RecordSheet)

        # Every field written out, and nothing to type into.
        assert not sheet.query(Input)
        assert "Wire the rack" in sheet.query_one("#field-title", Static).visual.plain
        # The board a task is on says its name, not its id.
        assert sheet.query_one("#field-board", Static).visual.plain == "Home Lab"
        assert [b.label.plain for b in sheet.query(Button)] == ["Close"]

        await pilot.press("ctrl+s")
        await breathe(pilot)
        assert app.screen is sheet
        sheet.ask_delete()
        await breathe(pilot)
        assert app.screen is sheet

        await pilot.click("#cancel")
        await settle(app, pilot)
        assert app.screen is screen
        assert seen == []


# -- the list ------------------------------------------------------------------------


async def test_a_list_you_may_only_read_ticks_nothing(app):
    async def read_only_quills():
        quills = await real()
        for quill in quills:
            if quill["id"] == "reading":
                quill["models"]["reading.book"]["access"] = "read"
        return quills

    real = app.client.quills
    app.client.quills = read_only_quills
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_reading(app, pilot)
        assert isinstance(pane, ListPane)

        assert toolbar(pane) == ["open_record"]
        pane.query_one("#kit-table").focus()
        await pilot.press("space")
        await pilot.press("delete")
        await settle(app, pilot)
        assert app.client.record_store["reading.book"][0]["fields"]["read"] is False
        assert len(app.client.record_store["reading.book"]) == 2


# -- the thread ----------------------------------------------------------------------


async def test_a_thread_you_may_only_read_has_no_line_to_type_in(app):
    only_read(app, "chat", "message", "channel")
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await start(app, pilot)
        await pilot.press("f4")
        await settle(app, pilot)
        pane = screen.query_one(ThreadPane)

        assert not pane.query("#thread-input")
        assert toolbar(pane) == []
        # What is said is still there to read.
        assert "I turned the fan curve down" in pane.query_one(
            "#conversation-text", Static
        ).visual.plain
        pane.query_one("#space-table").focus()
        for key in ("n", "m", "a", "l", "e"):
            await pilot.press(key)
            await breathe(pilot)
            assert app.screen is screen


async def test_saying_things_in_channels_you_may_only_read(app):
    """Messages written, channels read: the line is there, making a channel is not."""
    only_read(app, "chat", "channel")
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await start(app, pilot)
        await pilot.press("f4")
        await settle(app, pilot)
        pane = screen.query_one(ThreadPane)

        assert toolbar(pane) == []
        pane.query_one("#space-table").focus()
        await pilot.press("n")
        await breathe(pilot)
        assert app.screen is screen

        box = pane.query_one("#thread-input", Input)
        box.focus()
        box.value = "read-only channels still hear me"
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.client.record_store["message"][-1]["fields"]["body"] == (
            "read-only channels still hear me"
        )


# -- the grid ------------------------------------------------------------------------


async def test_a_grid_you_may_only_read_gets_files_and_puts_none(app):
    only_read(app, "files", "file")
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await into_holiday(app, pilot)
        pane = screen.query_one(GridPane)

        shown = [
            (b.id or "")[len("do-"):] for b in pane.query(".toolbar Button") if b.display
        ]
        assert shown == ["toggle_view", "sort", "refresh"]
        assert "get" not in pane.refused
        for key in ("p", "ctrl+n", "e", "M", "delete"):
            await pilot.press(key)
            await breathe(pilot)
            assert app.screen is screen
        assert app.client.file_calls == []


# -- the calendar ----------------------------------------------------------------------


async def test_events_on_calendars_you_may_only_read(app):
    """The family calendar: events may be put on it, calendars are not made."""
    with_calendar(app)
    only_read(app, "calendar", "calendar")
    for row in app.client.record_store["calendar"]:
        if row["id"] == "r_house":
            row.update(owner="guest", can_manage=False, members=["bram"])
    async with app.run_test(size=(140, 40)) as pilot:
        screen, pane = await open_calendar(app, pilot)
        assert toolbar(pane) == ["new_record", "open_record", "delete_record", "people", "today"]
        for key in ("c", "r"):
            await pilot.press(key)
            await breathe(pilot)
            assert app.screen is screen

        pane.query_one("#calendar-table").focus()
        await pilot.press("down")
        await settle(app, pilot)
        pane.fire("people")
        await breathe(pilot)
        modal = app.screen
        assert isinstance(modal, SpaceModal)
        # Who is in it, and nothing to change about that.
        assert not modal.query_one("#space-add").display
        assert not modal.query_one("#space-leave").display
        modal.action_close()
        await settle(app, pilot)


# -- the editor ----------------------------------------------------------------------


async def test_pages_you_may_only_read_open_read_only(app):
    only_read(app, "notes", "note")
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        pane = screen.query_one(EditorPane)
        assert toolbar(pane) == ["search", "export_file"]
        pane.open_page(note_id("architecture"))
        await settle(app, pilot)
        editor = screen.query_one(LiveMarkdownEditor)
        assert editor.read_only
        editor.focus()
        await pilot.press("x", "ctrl+s")
        await pane.flush()
        await settle(app, pilot)
        assert app.client.note_files["architecture"][0].startswith("# Architecture\n")
        assert "x" not in editor.text

        tree = screen.query_one(NoteTree)
        tree.focus()
        for key in ("n", "N", "r", "d", "ctrl+n", "ctrl+o", "f6"):
            await pilot.press(key)
            await breathe(pilot)
            assert app.screen is screen


# -- a Quill with nothing left -----------------------------------------------------------


async def test_a_quill_with_nothing_left_draws_no_tab(app):
    chat = next(q for q in app.client.quill_list if q["id"] == "chat")
    chat.update(available=False, enabled=False)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        assert not screen.query("#nav-chat")
        assert screen.query("#nav-tasks")
