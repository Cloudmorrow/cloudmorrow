"""The kit in the terminal: the record sheet, the list, Quill tabs, and installing.

The board has its own file (test_board.py). These are the rest of what a
Quill gets without writing a line of UI: a sheet for any record, a table for
a `list` screen, a tab that comes and goes with the Quill, and the install
sheet in Administration that says what a Quill adds before it is added.

A dialog open holds its worker open, so while one is up these wait with two
pauses rather than `settle()`, which would wait for that worker for ever.
"""

from __future__ import annotations

from textual.widgets import Checkbox, Input, RadioSet, Select, Static

from cloudmorrow.tui.panes.admin_quills import QuillSheet, QuillsView, sheet_text
from cloudmorrow.tui.panes.kit import ListPane, screen_key
from cloudmorrow.tui.panes.kit_board import BoardPane
from cloudmorrow.tui.screens.record_sheet import RecordSheet
from cloudmorrow.tui.widgets.editor import LiveMarkdownEditor
from tests.tui_harness import settle, start
from tests.tui_quills import READING_QUILL, record_row


async def breathe(pilot) -> None:
    await pilot.pause()
    await pilot.pause()


async def open_card(app, pilot, title: str = "Wire the rack") -> RecordSheet:
    screen = await start(app, pilot)
    await pilot.click("#nav-tasks")
    await settle(app, pilot)
    pane = screen.query_one(BoardPane)
    cards = [c for lane in pane.query("Lane") for c in lane.cards()]
    card = next(c for c in cards if c.fields["title"] == title)
    await pilot.click(card)
    await breathe(pilot)
    assert isinstance(app.screen, RecordSheet)
    return app.screen


def tab_labels(screen) -> list[str]:
    """The sidebar's cards as "Name  key", in order."""
    from cloudmorrow.tui.widgets.sidebar import NavCard

    return [
        f"{card.name_text}  {card.tag}"
        for card in screen.query(NavCard)
        if card.display and not card.has_class("admin-card")
    ]


# -- the record sheet ----------------------------------------------------------


async def test_every_field_has_the_widget_its_kind_calls_for(app):
    async with app.run_test(size=(120, 36)) as pilot:
        sheet = await open_card(app, pilot)

        assert isinstance(sheet.query_one("#field-title"), Input)
        board = sheet.query_one("#field-board", Select)
        assert board.value == "r_homelab"
        lane = sheet.query_one("#field-lane", RadioSet)
        assert lane.pressed_button.id == "field-lane--todo"
        assert sheet.query_one("#field-due", Input).placeholder == "YYYY-MM-DD"
        assert isinstance(sheet.query_one("#field-body"), LiveMarkdownEditor)
        # A stamped field is shown, never typed into.
        assert isinstance(sheet.query_one("#field-done_at"), Static)
        # The title first, the long body last.
        rows = [row.query_one(".sheet-label").visual.plain for row in sheet.query(".sheet-row")]
        assert rows == ["Title *", "Board *", "Lane", "Due", "Done", "Body"]
        sheet.action_cancel()
        await settle(app, pilot)


async def test_saving_sends_what_changed_with_the_rev(app):
    seen: list[tuple] = []
    real = app.client.update_record

    async def spy(model, record_id, fields, *, rev=None):
        seen.append((model, record_id, dict(fields), rev))
        return await real(model, record_id, fields, rev=rev)

    app.client.update_record = spy
    async with app.run_test(size=(120, 36)) as pilot:
        sheet = await open_card(app, pilot)
        sheet.query_one("#field-title", Input).value = "Wire the whole rack"
        sheet.query_one("#field-due", Input).value = "2026-10-01"
        await pilot.press("ctrl+s")
        await breathe(pilot)
        assert not isinstance(app.screen, RecordSheet)
        await settle(app, pilot)

        assert seen == [
            ("task", "r_task1", {"title": "Wire the whole rack", "due": "2026-10-01"}, 1)
        ]


async def test_a_bad_date_is_said_in_the_sheet_and_nothing_is_sent(app):
    async with app.run_test(size=(120, 36)) as pilot:
        sheet = await open_card(app, pilot)
        sheet.query_one("#field-due", Input).value = "next tuesday"
        await pilot.click("#save")
        await breathe(pilot)

        assert app.screen is sheet
        assert "is a date" in sheet.query_one("#sheet-complaint").visual.plain
        assert app.client.record_store["task"][0]["rev"] == 1
        sheet.action_cancel()
        await settle(app, pilot)


async def test_a_record_changed_elsewhere_is_said_and_shown_again(app):
    """409: the sheet stays open, says so, and shows the version that won."""
    async with app.run_test(size=(120, 36)) as pilot:
        sheet = await open_card(app, pilot)
        # Somebody else saves it while it is open here.
        await app.client.update_record("task", "r_task1", {"title": "Rack, by someone else"})
        sheet.query_one("#field-title", Input).value = "Mine"
        await pilot.press("ctrl+s")
        await breathe(pilot)

        assert app.screen is sheet
        assert "changed somewhere else" in sheet.query_one("#sheet-complaint").visual.plain
        assert sheet.query_one("#field-title", Input).value == "Rack, by someone else"
        assert app.client.record_store["task"][0]["fields"]["title"] == "Rack, by someone else"

        # Saving again now is on top of theirs, so it goes through.
        sheet.query_one("#field-title", Input).value = "Mine after all"
        await pilot.press("ctrl+s")
        await breathe(pilot)
        assert not isinstance(app.screen, RecordSheet)
        await settle(app, pilot)
        assert app.client.record_store["task"][0]["fields"]["title"] == "Mine after all"


async def test_the_sheet_deletes_after_asking(app):
    async with app.run_test(size=(120, 36)) as pilot:
        sheet = await open_card(app, pilot, "Repaint")
        await pilot.click("#sheet-delete")
        await breathe(pilot)
        await pilot.press("y")
        await breathe(pilot)
        assert not isinstance(app.screen, RecordSheet)
        await settle(app, pilot)

        assert "r_task2" not in [row["id"] for row in app.client.record_store["task"]]
        assert sheet is not app.screen


async def test_moving_a_card_to_another_board_from_the_sheet(app):
    async with app.run_test(size=(120, 36)) as pilot:
        sheet = await open_card(app, pilot, "Repaint")
        sheet.query_one("#field-board", Select).value = "r_errands"
        await pilot.press("ctrl+s")
        await breathe(pilot)
        await settle(app, pilot)

        pane = app.screen.query_one(BoardPane)
        assert [c.fields["title"] for c in pane.lane_widget("todo").cards()] == ["Wire the rack"]
        moved = next(r for r in app.client.record_store["task"] if r["id"] == "r_task2")
        assert moved["fields"]["board"] == "r_errands"


# -- Quill tabs ----------------------------------------------------------------


async def test_a_quill_screen_is_a_tab_after_notes(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        assert tab_labels(screen)[0] == "Notes  f1"
        # Tasks, then Files: the order they were installed in, each with its old key.
        assert tab_labels(screen)[-2:] == ["Tasks  f2", "Files  f5"]
        assert screen.query_one("#nav-section-quills").display
        assert isinstance(screen.query_one("#pane-tasks"), BoardPane)


async def test_the_quill_key_brings_its_tab(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        await pilot.press("f2")
        await settle(app, pilot)
        assert screen.query_one("#panes").current == "pane-tasks"


async def test_a_kit_the_terminal_does_not_draw_yet_has_no_tab(app):
    quill = dict(READING_QUILL, id="diary", name="Diary", installed_version="0.2.0")
    quill["screens"] = [dict(READING_QUILL["screens"][0], kit="thread")]
    app.client.quill_list.append(quill)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        assert not screen.query("#nav-diary")


def test_a_quill_with_several_screens_has_a_key_for_each():
    quill = {"id": "fleet", "screens": [{"id": "cars"}, {"id": "visits"}]}
    assert screen_key(quill, quill["screens"][1]) == "fleet-visits"
    assert screen_key({"id": "tasks", "screens": [{"id": "board"}]}, {"id": "board"}) == "tasks"


# -- the list kit ----------------------------------------------------------------


async def open_reading(app, pilot):
    app.client.quill_list.append(dict(READING_QUILL, installed_version="0.2.0"))
    from tests.tui_harness import feature_row

    app.client.feature_list.append(feature_row("reading", "Reading"))
    app.client.record_store["reading.book"] = [
        record_row("reading.book", "r_book1", 0, title="Middlemarch", author="George Eliot",
                   read=False, pages=880),
        record_row("reading.book", "r_book2", 1, title="Stoner", author="John Williams",
                   read=True, pages=288),
    ]
    screen = await start(app, pilot)
    await pilot.click("#nav-reading")
    await settle(app, pilot)
    return screen, screen.query_one(ListPane)


async def test_a_list_screen_is_a_table_with_a_circle(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen, pane = await open_reading(app, pilot)
        assert "Reading  f4" in tab_labels(screen)
        table = pane.query_one("#kit-table")
        cells = [[str(c) for c in table.get_row_at(i)] for i in range(table.row_count)]
        assert "○" in cells[0][0] and "Middlemarch" in cells[0][1] and "George Eliot" in cells[0][2]
        assert "●" in cells[1][0]


async def test_space_ticks_a_row(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_reading(app, pilot)
        pane.query_one("#kit-table").focus()
        await pilot.press("space")
        await settle(app, pilot)
        assert app.client.record_store["reading.book"][0]["fields"]["read"] is True
        assert app.client.record_store["reading.book"][0]["rev"] == 2


async def test_enter_opens_a_row_in_the_sheet(app):
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_reading(app, pilot)
        pane.query_one("#kit-table").focus()
        await pilot.press("enter")
        await breathe(pilot)
        sheet = app.screen
        assert isinstance(sheet, RecordSheet)
        assert sheet.query_one("#field-title", Input).value == "Middlemarch"
        assert isinstance(sheet.query_one("#field-read"), Checkbox)
        assert sheet.query_one("#field-pages", Input).type == "integer"
        sheet.action_cancel()
        await settle(app, pilot)


async def test_a_new_row_from_the_sheet(app):
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_reading(app, pilot)
        # Every Quill pane has a New button; this one is Reading's.
        await pilot.click("#pane-reading #do-new_record")
        await breathe(pilot)
        for key in "Emma":
            await pilot.press(key)
        await pilot.press("ctrl+s")
        await breathe(pilot)
        await settle(app, pilot)
        titles = [r["fields"]["title"] for r in app.client.record_store["reading.book"]]
        assert titles[-1] == "Emma"
        assert len(pane.records) == 3


# -- Administration: Quills --------------------------------------------------------


async def open_quills(app, pilot):
    screen = await start(app, pilot)
    await pilot.press("f9")
    await settle(app, pilot)
    await pilot.click("#nav-admin-quills")
    await settle(app, pilot)
    return screen, screen.query_one(QuillsView)


async def test_the_catalog_is_shelved_by_category(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen, view = await open_quills(app, pilot)
        table = view.query_one("#admin-quill-table")
        rows = [[str(c) for c in table.get_row_at(i)] for i in range(table.row_count)]
        assert "PERSONAL" in rows[0][0]
        assert "Tasks" in rows[1][0] and "1.0.0" in rows[1][1]
        assert "HOME" in rows[2][0]
        assert "Reading" in rows[3][0] and "—" in rows[3][1]


def test_the_install_sheet_says_what_a_quill_adds():
    text = sheet_text(dict(READING_QUILL, installed_version=None))
    assert "introduces" in text and "reading.book" in text and "new on this server" in text
    assert "Reading" in text and "list of reading.book" in text
    assert "Declared, not run yet by this server: service isbn-lookup" in text


async def test_installing_shows_the_sheet_then_adds_the_tab(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen, view = await open_quills(app, pilot)
        table = view.query_one("#admin-quill-table")
        table.focus()
        table.move_cursor(row=3)
        await pilot.press("i")
        await breathe(pilot)
        assert isinstance(app.screen, QuillSheet)
        assert app.client.quill_calls == [("plan", "reading")]
        await pilot.click("#install")
        await breathe(pilot)
        await settle(app, pilot)

        assert ("install", "reading") in app.client.quill_calls
        # The workspace behind the panel grew the tab, with the next free key.
        assert "Reading  f4" in tab_labels(screen)
        assert "0.2.0" in str(table.get_row_at(3)[1])


async def test_removing_asks_then_takes_the_tab_and_keeps_the_records(app):
    # Tasks alone, so taking it away leaves no Quills at all.
    app.client.quill_list = [q for q in app.client.quill_list if q["id"] != "files"]
    async with app.run_test(size=(120, 34)) as pilot:
        screen, view = await open_quills(app, pilot)
        table = view.query_one("#admin-quill-table")
        table.focus()
        table.move_cursor(row=1)
        await pilot.press("d")
        await breathe(pilot)
        await pilot.press("y")
        await settle(app, pilot)

        assert ("uninstall", "tasks") in app.client.quill_calls
        assert not screen.query("#nav-tasks")
        assert not screen.query_one("#nav-section-quills").display
        assert not screen.query("#pane-tasks")
        assert len(app.client.record_store["task"]) == 3
