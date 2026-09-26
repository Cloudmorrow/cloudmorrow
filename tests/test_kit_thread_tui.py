"""The kit's thread in the terminal: Chat's channels and conversations, drawn generically.

What the old chat pane's tests held, held of the kit's `thread` with Chat
installed as a Quill: the spaces are listed and the first opens, opening one
marks it seen, the count says what is waiting, a line is sent and shown,
making a space asks who can see it, writing to a person finds the
conversation with them, and a public or direct space is not added to or left.

A dialog open holds its worker open, so while one is up these wait with two
pauses rather than `settle()`.
"""

from __future__ import annotations

from textual.widgets import Checkbox, DataTable, Input, Static

from cloudmorrow.tui.panes.kit_thread import ThreadPane, render_lines
from cloudmorrow.tui.widgets.kit_space import NewSpaceModal, PickPersonModal, space_name
from tests.tui_chat import CHAT_MODELS, CHAT_SCREEN, line_row, space_row
from tests.tui_harness import said, settle, start


async def breathe(pilot) -> None:
    await pilot.pause()
    await pilot.pause()


async def open_chat(app, pilot):
    screen = await start(app, pilot)
    await pilot.press("f4")
    await settle(app, pilot)
    return screen, screen.query_one(ThreadPane)


def text_of(pane, selector: str) -> str:
    return pane.query_one(selector, Static).visual.plain


# -- what a conversation looks like ------------------------------------------------
def test_a_run_from_one_person_carries_one_name():
    lines = [
        line_row("a", "s", "guest", "one", "2026-09-19T14:00:00+00:00"),
        line_row("b", "s", "guest", "two", "2026-09-19T14:01:00+00:00"),
        line_row("c", "s", "bram", "three", "2026-09-19T14:02:00+00:00"),
    ]
    drawn = render_lines(lines, "body", "bram")
    assert drawn.count("guest") == 1
    assert "you" in drawn


def test_a_new_day_starts_again():
    lines = [
        line_row("a", "s", "guest", "late", "2026-09-18T23:59:00+00:00"),
        line_row("b", "s", "guest", "early", "2026-09-19T07:00:00+00:00"),
    ]
    drawn = render_lines(lines, "body", "bram")
    assert "── 2026-09-18 ──" in drawn and "── 2026-09-19 ──" in drawn
    assert drawn.count("guest") == 2, "a new day names the person again"


def test_a_line_with_brackets_in_it_is_not_markup():
    drawn = render_lines([line_row("a", "s", "guest", "[b]not bold[/b]", "2026-09-19T14:00:00+00:00")],
                         "body", "bram")
    assert r"\[b]not bold\[/b]" in drawn


def test_an_edited_line_says_so_and_an_empty_space_says_nothing_yet():
    edited = line_row("a", "s", "guest", "fixed", "2026-09-19T14:00:00+00:00", edited="2026-09-19T14:05:00+00:00")
    assert "(edited)" in render_lines([edited], "body", "bram")
    assert "Nothing said here yet" in render_lines([], "body", "bram")


def test_a_space_between_people_is_named_for_the_other_one():
    model = CHAT_MODELS["channel"]
    dm = space_row("r_x", "bram & guest", "direct", owner="guest", members=["bram"])
    room = space_row("r_y", "homelab", "public")
    assert space_name(model, dm, CHAT_SCREEN, "bram") == "guest"
    assert space_name(model, dm, CHAT_SCREEN, "guest") == "bram"
    assert space_name(model, room, CHAT_SCREEN, "bram") == "homelab"


# -- the pane ---------------------------------------------------------------------------
async def test_the_spaces_are_listed_and_the_newest_opens(app):
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_chat(app, pilot)
        table = pane.query_one("#space-table", DataTable)
        # Newest activity first: #general's last line is the day after the direct one's.
        assert [table.get_row_at(i)[0] for i in range(table.row_count)][0] == "#general"
        assert "guest" in table.get_row_at(1)[0]
        assert "#general" in text_of(pane, "#conversation-title")
        assert "everything else" in text_of(pane, "#conversation-title")
        assert "I turned the fan curve down" in text_of(pane, "#conversation-text")


async def test_the_count_beside_a_space_says_what_is_waiting(app):
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_chat(app, pilot)
        table = pane.query_one("#space-table", DataTable)
        assert "2" in table.get_row_at(1)[1]
        assert pane.card_status() == ("news", "2 unread")


async def test_opening_a_space_marks_it_seen(app):
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_chat(app, pilot)
        assert app.client.seen_calls == ["r_general"]
        pane.query_one("#space-table", DataTable).move_cursor(row=1)
        await settle(app, pilot)
        assert app.client.seen_calls[-1] == "r_dm"
        assert "the NAS is beeping" in text_of(pane, "#conversation-text")
        assert pane.query_one("#space-table", DataTable).get_row_at(1)[1] == ""


async def test_writing_a_line_sends_it_and_shows_it(app):
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_chat(app, pilot)
        box = pane.query_one("#thread-input", Input)
        box.focus()
        box.value = "fans are fine now"
        await pilot.press("enter")
        await settle(app, pilot)
        sent = app.client.record_store["message"][-1]
        assert sent["fields"] == {"channel": "r_general", "body": "fans are fine now", "sent_at": None}
        assert "fans are fine now" in text_of(pane, "#conversation-text")
        assert box.value == ""


async def test_an_empty_line_is_not_sent(app):
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_chat(app, pilot)
        before = len(app.client.record_store["message"])
        box = pane.query_one("#thread-input", Input)
        box.focus()
        box.value = "   "
        await pilot.press("enter")
        await settle(app, pilot)
        assert len(app.client.record_store["message"]) == before


async def test_what_arrives_while_open_is_drawn_on_the_next_poll(app):
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_chat(app, pilot)
        app.client.record_store["message"].append(
            line_row("r_new", "r_general", "guest", "you there?", "2026-09-21T09:00:00+00:00"))
        pane.catch_up()
        await settle(app, pilot)
        assert "you there?" in text_of(pane, "#conversation-text")


async def test_making_a_space_asks_who_can_see_it_and_opens_it(app):
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_chat(app, pilot)
        pane.focus()
        await pilot.press("n")
        await breathe(pilot)
        modal = app.screen
        assert isinstance(modal, NewSpaceModal)
        # Public first, and a public space asks nobody's name.
        assert not modal.query_one("#space-people").display
        modal.query_one("#space-name").value = "homelab"
        modal.query_one("#space-field-topic").value = "the rack"
        modal.query_one("#scope-shared").value = True
        await breathe(pilot)
        assert modal.query_one("#space-people").display
        modal.query_one("#person-guest", Checkbox).value = True
        modal.action_save()
        await settle(app, pilot)
        made = [c for c in app.client.space_calls if c[0] == "made"][-1]
        assert made[2:] == ("shared", ["guest"], {"name": "homelab", "kind": "private", "topic": "the rack"})
        assert "#homelab" in text_of(pane, "#conversation-title")
        assert "guest is in it" in said(app.screen)


async def test_a_tick_taken_back_by_going_public_is_not_sent(app):
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_chat(app, pilot)
        pane.focus()
        await pilot.press("n")
        await breathe(pilot)
        modal = app.screen
        modal.query_one("#space-name").value = "everyone"
        modal.query_one("#scope-shared").value = True
        await breathe(pilot)
        modal.query_one("#person-guest", Checkbox).value = True
        modal.query_one("#scope-public").value = True
        await breathe(pilot)
        modal.action_save()
        await settle(app, pilot)
        made = [c for c in app.client.space_calls if c[0] == "made"][-1]
        assert made[2:4] == ("public", [])
        assert made[4]["kind"] == "public"


async def test_a_space_with_no_name_is_complained_about_not_made(app):
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_chat(app, pilot)
        pane.focus()
        await pilot.press("n")
        await breathe(pilot)
        modal = app.screen
        modal.action_save()
        await breathe(pilot)
        assert app.screen is modal
        assert "needs a name" in modal.query_one("#space-complaint", Static).visual.plain
        modal.action_cancel()
        await settle(app, pilot)
        assert not [c for c in app.client.space_calls if c[0] == "made"]


async def test_writing_to_a_person_finds_the_conversation_with_them(app):
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_chat(app, pilot)
        pane.focus()
        await pilot.press("m")
        await breathe(pilot)
        assert isinstance(app.screen, PickPersonModal)
        app.screen.dismiss("guest")
        await settle(app, pilot)
        # The one there is, not a second.
        assert app.client.space_calls[-1] == ("found", "r_dm")
        assert "guest" in text_of(pane, "#conversation-title")
        # The line to write in has the keyboard now; a key is a letter there.
        assert pane.query_one("#thread-input", Input).has_focus
        pane.query_one("#space-table", DataTable).focus()
        await pilot.press("m")
        await breathe(pilot)
        assert isinstance(app.screen, PickPersonModal), (app.screen, app.focused)
        app.screen.dismiss("ada")
        await settle(app, pilot)
        made = app.client.space_calls[-1]
        assert made[0] == "made" and made[2:] == ("shared", ["ada"], {"name": "ada & bram", "kind": "direct"})


async def test_a_public_or_direct_space_is_not_added_to_or_left(app):
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_chat(app, pilot)
        pane.focus()
        await pilot.press("a")
        await breathe(pilot)
        assert "Everybody is already in it" in said(app.screen)
        await pilot.press("l")
        await breathe(pilot)
        assert "nobody leaves it" in said(app.screen)
        pane.query_one("#space-table", DataTable).move_cursor(row=1)
        await settle(app, pilot)
        pane.focus()
        await pilot.press("l")
        await breathe(pilot)
        assert "stays as it is" in said(app.screen)
        assert not [c for c in app.client.space_calls if c[0] in ("add", "remove")]


async def test_leaving_a_private_space_confirms_first(app):
    app.client.record_store["channel"].append(
        space_row("r_club", "club", "private", owner="guest", members=["bram"], at="2026-09-25T09:00:00+00:00"))
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_chat(app, pilot)
        assert pane.space["id"] == "r_club"
        pane.focus()
        await pilot.press("l")
        await breathe(pilot)
        await pilot.press("y")
        await settle(app, pilot)
        assert ("remove", "r_club", "bram") in app.client.space_calls
        assert "club" not in [s["fields"]["name"] for s in pane.spaces]


async def test_adding_somebody_offers_only_who_is_not_in_it(app):
    app.client.record_store["channel"].append(
        space_row("r_club", "club", "private", members=["guest"], at="2026-09-25T09:00:00+00:00"))
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_chat(app, pilot)
        pane.focus()
        await pilot.press("a")
        await breathe(pilot)
        picker = app.screen
        assert [p["username"] for p in picker.people] == ["ada"]
        picker.dismiss("ada")
        await settle(app, pilot)
        assert ("add", "r_club", "ada") in app.client.space_calls
        assert "ada is in" in said(app.screen)


async def test_the_tab_is_gone_when_the_server_has_chat_switched_off(app):
    app.client.features_off = {"chat"}
    for row in app.client.feature_list:
        if row["key"] == "chat":
            row["enabled"] = False
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await start(app, pilot)
        card = screen.query("#nav-chat")
        assert not card or not card.first().display


def test_the_new_space_dialog_names_scopes_after_the_screen():
    modal = NewSpaceModal(CHAT_MODELS["channel"], [], screen=CHAT_SCREEN)
    assert modal.scopes == ["public", "shared"]
    assert [f["name"] for f in modal.extra] == ["topic"], "kind is made_as's to set, not a field to type"

