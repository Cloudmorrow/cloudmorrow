"""The kit in the terminal: the record sheet, the list, Quill tabs, and installing.

The board has its own file (test_board.py). These are the rest of what a
Quill gets without writing a line of UI: a sheet for any record, a table for
a `list` screen, a tab that comes and goes with the Quill, and the install
sheet in Administration that says what a Quill adds before it is added.

A dialog open holds its worker open, so while one is up these wait with two
pauses rather than `settle()`, which would wait for that worker for ever.
"""

from __future__ import annotations

from rich.text import Text
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

        assert seen == [("task", "r_task1", {"title": "Wire the whole rack", "due": "2026-10-01"}, 1)]


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


async def test_the_quill_tabs_come_first_notes_then_tasks(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        assert tab_labels(screen)[0] == "Notes  f1"
        # Then Tasks, Files and Chat: the catalog's order, Tasks and Files
        # with their old keys and Chat with the next one free.
        assert tab_labels(screen)[1:4] == ["Tasks  f2", "Files  f5", "Chat  f4"]
        assert screen.query_one("#nav-shelf-personal").display
        assert isinstance(screen.query_one("#pane-tasks"), BoardPane)


def shelves(screen) -> list[tuple[str, list[str]]]:
    """The Quills' shelves in the sidebar as (LABEL, [card names]), in order, the hidden left out."""
    from cloudmorrow.tui.widgets.sidebar import NavCard, SectionLabel

    found: list[tuple[str, list[str]]] = []
    for widget in screen.query_one("#sidebar").children:
        if not widget.display:
            continue
        if isinstance(widget, SectionLabel):
            if not str(widget.id).startswith("nav-shelf-"):
                break  # Your cloud, Administration: not the Quills' own
            found.append((widget.visual.plain, []))
        elif isinstance(widget, NavCard) and found:
            found[-1][1].append(widget.name_text)
    return found


async def test_the_cards_stand_on_the_shelves_of_their_categories(app):
    # The fixtures say a category but, as a server from before did, no label
    # or rank for it: the category's own name, in the order the Quills came.
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        assert shelves(screen) == [
            ("PERSONAL", ["Notes", "Tasks", "Files"]),
            ("HOME", ["Chat"]),
            ("DEVELOPER", ["Secrets"]),
        ]
        assert screen.query_one("#nav-shelf-personal").has_class("-first")
        # A shelf stands while a card of its own does: Secrets off, and
        # DEVELOPER goes with it.
        screen.apply_features(["notes", "tasks", "files", "chat"])
        assert [label for label, _ in shelves(screen)] == ["PERSONAL", "HOME"]
        screen.apply_features(["notes", "tasks", "files", "chat", "secrets"])
        assert [label for label, _ in shelves(screen)] == ["PERSONAL", "HOME", "DEVELOPER"]


async def test_the_shelves_follow_the_catalogs_order(app):
    labels = {"personal": ("Personal", 2), "home": ("Home", 1), "developer": ("Developer", 0)}
    for quill in app.client.quill_list:
        quill["category_label"], quill["category_rank"] = labels[quill["category"]]
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        assert [label for label, _ in shelves(screen)] == ["DEVELOPER", "HOME", "PERSONAL"]
        assert screen.query_one("#nav-shelf-developer").has_class("-first")
        # The keys are still handed out in the order the Quills came, and the
        # workspace still opens on Notes.
        assert tab_labels(screen)[:2] == ["Secrets  f3", "Chat  f4"]
        assert screen.query_one("#panes").current == "pane-notes"
        # Every Quill on a shelf gone: the shelf goes with it.
        app.client.quill_list = [q for q in app.client.quill_list if q["category"] != "home"]
        await screen.sync_quills()
        await settle(app, pilot)
        assert [label for label, _ in shelves(screen)] == ["DEVELOPER", "PERSONAL"]
        assert not screen.query("#nav-shelf-home")


async def test_the_quill_key_brings_its_tab(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        await pilot.press("f2")
        await settle(app, pilot)
        assert screen.query_one("#panes").current == "pane-tasks"


async def test_a_kit_the_terminal_does_not_draw_yet_has_no_tab(app):
    # Every kit is drawn now, the timeline too (test_kit_timeline_tui.py);
    # one from a server newer than this client is not.
    quill = dict(READING_QUILL, id="diary", name="Diary", installed_version="0.2.0")
    quill["screens"] = [dict(READING_QUILL["screens"][0], kit="spreadsheet")]
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
        record_row("reading.book", "r_book1", 0, title="Middlemarch", author="George Eliot", read=False, pages=880),
        record_row("reading.book", "r_book2", 1, title="Stoner", author="John Williams", read=True, pages=288),
    ]
    screen = await start(app, pilot)
    await pilot.click("#nav-reading")
    await settle(app, pilot)
    return screen, screen.query_one("#pane-reading", ListPane)


async def test_a_list_screen_is_a_table_with_a_circle(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen, pane = await open_reading(app, pilot)
        assert "Reading  f10" in tab_labels(screen)
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


async def open_quills(app, pilot, tab: str = "catalog"):
    screen = await start(app, pilot)
    await pilot.press("f9")
    await settle(app, pilot)
    await pilot.click("#nav-admin-quills")
    await settle(app, pilot)
    view = screen.query_one(QuillsView)
    view.show_tab(tab)
    await settle(app, pilot)
    return screen, view


def server_rows(view) -> list[list[str]]:
    """What the Server Quills table says, with the colour markup taken off."""
    table = view.query_one("#admin-server-table")
    return [[Text.from_markup(str(c)).plain for c in table.get_row_at(i)] for i in range(table.row_count)]


async def test_server_quills_is_the_tab_it_opens_on_with_how_each_is(app):
    """Every installed Quill, whether it is on, and where it stands against the catalog."""
    app.client.feature_list[1]["enabled"] = False  # tasks, switched off
    async with app.run_test(size=(140, 40)) as pilot:
        screen, view = await open_quills(app, pilot, tab="server")
        assert view.tab == "server"
        listed = server_rows(view)
        names = [row[1].strip() for row in listed]
        assert names == ["Notes", "Tasks", "Files", "Chat", "Secrets"]
        at = names.index("Tasks")
        assert listed[at][3] == "off" and listed[at][4] == "from the catalog"
        # Notes came from the catalog, which no longer has it: it says so, and cannot be ticked.
        assert listed[0][3] == "on" and listed[0][4] == "no longer in the catalog"
        table = view.query_one("#admin-server-table")
        table.focus()
        table.move_cursor(row=at)
        await settle(app, pilot)
        # The details beside the list say the same, with everything it adds.
        detail = view.query_one("#admin-quill-detail-text").visual.plain
        assert "Tasks" in detail and "off" in detail and "for everyone" in detail
        # o switches it on again, for everybody: the server's switch.
        await pilot.press("o")
        await settle(app, pilot)
        assert app.client.feature_calls == [("tasks", True)]
        assert server_rows(view)[at][3] == "on"


async def test_ticked_quills_are_updated_in_one_go_for_the_same_people(app):
    """Space ticks, u installs each ticked Quill again with who it is for; the
    ticks go once it is done."""
    tasks = next(q for q in app.client.quill_list if q["id"] == "tasks")
    tasks["audience"] = {"circles": ["kids"], "people": []}
    async with app.run_test(size=(140, 40)) as pilot:
        screen, view = await open_quills(app, pilot, tab="server")
        table = view.query_one("#admin-server-table")
        table.focus()
        at = [row[1].strip() for row in server_rows(view)].index("Tasks")
        table.move_cursor(row=at)
        await pilot.press("space")
        await settle(app, pilot)
        assert server_rows(view)[at][0] == "✓"
        await pilot.press("u")
        await breathe(pilot)
        await pilot.click("#confirm")
        await settle(app, pilot)
        assert ("install", "tasks", {"circles": ["kids"], "people": []}) in app.client.quill_calls
        assert server_rows(view)[at][0] == " "


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
    plain = Text.from_markup(text).plain
    assert "Runs code on this server: python services/isbn.py" in plain
    assert "Runs as you, the administrator who installs it, and can read and write only: reading.book" in plain
    assert "Adds to this server" not in plain
    # A program it needs, which the install fetches: said with its size.
    with_runtime = dict(
        READING_QUILL,
        installed_version=None,
        runtimes=[
            {
                "id": "ffmpeg",
                "label": "ffmpeg",
                "summary": "Reads, writes and converts video and sound.",
                "version": "7.1.5",
                "license": "GPL-3.0-or-later",
                "size": 119007364,
                "installed": "",
                "available": True,
                "problem": "",
            }
        ],
    )
    plain = Text.from_markup(sheet_text(with_runtime)).plain
    assert "Adds to this server" in plain and "ffmpeg 7.1.5" in plain
    assert "Reads, writes and converts video and sound. · 119 MB · GPL-3.0-or-later · downloaded" in plain


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
        assert "Reading  f10" in tab_labels(screen)
        assert "0.2.0" in str(table.get_row_at(3)[1])


async def test_a_quill_of_your_own_has_its_card_switched_by_its_own_key(app):
    """Somebody's own Quill is the feature `~owner.id`, not its bare id: on, its card shows."""
    import copy

    from tests.tui_harness import feature_row
    from tests.tui_quills import READING_QUILL

    own = {**copy.deepcopy(READING_QUILL), "key": "~bram.reading", "mine": True}
    app.client.quill_list.append(own)
    app.client.feature_list.append(feature_row("~bram.reading", "Reading"))
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        assert any(label.startswith("Reading") for label in tab_labels(screen))


async def test_somebodys_own_quill_is_removed_from_user_quills(app):
    """User Quills: Remove beside Promote and Switch, asked first, off the server for everybody."""
    from cloudmorrow.tui.panes.admin_quills import QuillsView

    app.client.personal = [
        {
            "id": "vidmorrow",
            "key": "~alice.vidmorrow",
            "name": "Vidmorrow",
            "version": "2.0.0",
            "owner": "alice",
            "holders": ["alice"],
            "shared_with": [],
            "enabled": True,
        }
    ]
    async with app.run_test(size=(120, 40)) as pilot:
        screen, view = await open_quills(app, pilot)
        view.show_tab("own")
        await settle(app, pilot)
        await pilot.click("#premove-0")
        await breathe(pilot)
        await pilot.press("y")
        await settle(app, pilot)
        assert ("remove", "~alice.vidmorrow", []) in app.client.quill_calls
        assert not screen.query_one(QuillsView).query("#premove-0")


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
        # Notes and Chat are still Quills, so the section stays.
        assert screen.query_one("#nav-shelf-personal").display
        assert tab_labels(screen)[0] == "Notes  f1"
        assert not screen.query("#pane-tasks")
        assert len(app.client.record_store["task"]) == 3


async def test_the_sheet_shows_who_did_what_to_the_record(app):
    """Under the fields: the record's history, in words, never a value."""
    app.client.history = {
        "r_task1": [
            {
                "seq": 2,
                "action": "changed",
                "rev": 2,
                "by": "bram",
                "by_kind": "person",
                "at": "2026-10-08T09:41:00+00:00",
                "fields": ["title", "lane"],
            },
            {
                "seq": 1,
                "action": "created",
                "rev": 1,
                "by": "tasks",
                "by_kind": "dataset",
                "at": "2026-10-08T08:10:00+00:00",
                "fields": ["board", "title"],
            },
        ]
    }
    async with app.run_test(size=(120, 36)) as pilot:
        sheet = await open_card(app, pilot)
        # settle() waits while the sheet is open: breathe instead.
        await breathe(pilot)
        await breathe(pilot)
        said = sheet.query_one("#sheet-history").visual.plain
        assert "you changed title and lane" in said
        assert "the tasks Quill made it" in said
        assert "Rack" not in said
        sheet.action_cancel()
        await settle(app, pilot)


async def test_removing_a_quill_that_brought_data_asks_what_goes_with_it(app):
    """What it brought, a tick each to keep: unticked goes with the Quill, records and all."""
    app.client.brought = {
        "tasks": [
            {"id": "tasks.sprint", "kind": "datamodel", "label": "Sprint", "model": "tasks.sprint", "records": 4},
            {"id": "tasks.effort", "kind": "field", "label": "Effort on Task", "model": "task", "records": 2},
            # A program only Tasks needed: offered unticked, so it goes unless kept.
            {
                "id": "runtime:ffmpeg",
                "kind": "runtime",
                "label": "ffmpeg 7.1.5",
                "model": "",
                "records": 0,
                "size": 119007364,
                "size_said": "119 MB",
            },
        ]
    }
    async with app.run_test(size=(120, 36)) as pilot:
        screen, view = await open_quills(app, pilot)
        table = view.query_one("#admin-quill-table")
        table.focus()
        table.move_cursor(row=1)
        await pilot.press("d")
        await breathe(pilot)
        await breathe(pilot)
        sheet = app.screen
        assert sheet.__class__.__name__ == "RemoveSheet"
        boxes = list(sheet.query(Checkbox))
        assert [str(b.label) for b in boxes] == [
            "Sprint  (a datamodel it introduced, 4 records)",
            "Effort on Task  (a field it added, 2 records)",
            "ffmpeg 7.1.5  (a program it added, 119 MB, nothing else needs it)",
        ]
        assert [b.value for b in boxes] == [True, True, False]
        boxes[1].value = False
        await pilot.click("#remove")
        await settle(app, pilot)
        assert ("uninstall", "tasks", ["tasks.effort", "runtime:ffmpeg"]) in app.client.quill_calls
        assert not screen.query("#nav-tasks")


async def test_a_quill_with_several_screens_is_one_card_with_its_screens_under_it(app):
    """A CRM is CRM in the sidebar, with one key: its screens are the items
    under its card, listed only while you are on one of them, and the card
    itself opens the first."""
    from cloudmorrow.tui.widgets.sidebar import NavCard

    quill = dict(READING_QUILL, id="fleet", name="Fleet", summary="The cars, and their visits to the garage.")
    quill["screens"] = [
        dict(READING_QUILL["screens"][0], id="cars", label="Cars"),
        dict(READING_QUILL["screens"][0], id="visits", label="Visits"),
    ]
    app.client.quill_list.append(quill)
    from tests.tui_harness import feature_row

    app.client.feature_list.append(feature_row("fleet", "Fleet"))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await start(app, pilot)
        # One card, the Quill's, with a key; the screens are not cards beside it.
        fleet = screen.query_one("#nav-fleet", NavCard)
        assert fleet.tag and fleet.has_class("-parent")
        assert [label for label in tab_labels(screen) if label.startswith("Fleet")] == [f"Fleet  {fleet.tag}"]
        assert not screen.query_one("#nav-fleet-cars", NavCard).display
        assert shelves(screen)[1] == ("HOME", ["Chat", "Fleet"])
        # Chosen, the card opens the first screen, and its items appear under it.
        await pilot.click("#nav-fleet")
        await settle(app, pilot)
        assert screen.query_one("#panes").current == "pane-fleet-cars"
        assert fleet.active
        cars, visits = screen.query_one("#nav-fleet-cars", NavCard), screen.query_one("#nav-fleet-visits", NavCard)
        assert cars.display and cars.active and cars.has_class("-sub") and not cars.tag
        assert visits.display and not visits.active and visits.has_class("-last")
        assert shelves(screen)[1] == ("HOME", ["Chat", "Fleet", "Cars", "Visits"])
        await pilot.click("#nav-fleet-visits")
        await settle(app, pilot)
        assert screen.query_one("#panes").current == "pane-fleet-visits"
        assert fleet.active and visits.active and not cars.active
        # Somewhere else: the items go, the card stays, unlit.
        await pilot.click("#nav-tasks")
        await settle(app, pilot)
        assert not fleet.active and not cars.display and not visits.display
        assert shelves(screen)[1] == ("HOME", ["Chat", "Fleet"])
        # The Quill's key is the first screen's.
        await pilot.press(fleet.tag)
        await settle(app, pilot)
        assert screen.query_one("#panes").current == "pane-fleet-cars"
        # Switched off, the card goes with its items; on again, it is back.
        screen.apply_features(["notes", "tasks", "files", "chat", "secrets"])
        assert not fleet.display and not cars.display
        screen.apply_features(["notes", "tasks", "files", "chat", "secrets", "fleet"])
        assert fleet.display
