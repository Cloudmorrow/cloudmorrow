"""The Chat tab: the channel list, the thread beside it, and writing a line."""

from __future__ import annotations

from textual.widgets import DataTable, Input, SelectionList, Static

from cloudmorrow.tui.panes.chat import (
    ChatPane,
    channel_label,
    render_messages,
    who_is_in,
)
from cloudmorrow.tui.screens.channel import NewChannelModal
from cloudmorrow.tui.screens.modals import ConfirmModal, PromptModal
from tests.tui_harness import settle, start


async def open_chat(app, pilot):
    screen = await start(app, pilot)
    await pilot.click("#nav-chat")
    await settle(app, pilot)
    return screen, screen.query_one(ChatPane)


# -- what the thread reads like ---------------------------------------------------
def test_a_run_from_one_person_carries_one_name():
    messages = [
        {"id": 1, "author": "guest", "body": "one", "created_at": "2026-09-19T14:02:00",
         "edited_at": None},
        {"id": 2, "author": "guest", "body": "two", "created_at": "2026-09-19T14:03:00",
         "edited_at": None},
        {"id": 3, "author": "bram", "body": "three", "created_at": "2026-09-19T14:04:00",
         "edited_at": None},
    ]
    out = render_messages(messages, "bram")
    assert out.count("guest") == 1, "the second line is under the first, not renamed"
    assert "you" in out, "your own name is 'you'"
    assert "── 2026-09-19 ──" in out, "a date gets a rule across the pane"


def test_a_new_day_starts_again():
    messages = [
        {"id": 1, "author": "guest", "body": "last night",
         "created_at": "2026-09-18T23:50:00", "edited_at": None},
        {"id": 2, "author": "guest", "body": "this morning",
         "created_at": "2026-09-19T08:10:00", "edited_at": None},
    ]
    out = render_messages(messages, "bram")
    assert out.count("── ") == 2
    assert out.count("guest") == 2, "a new day names the speaker again"


def test_a_message_with_brackets_in_it_is_not_markup():
    messages = [
        {"id": 1, "author": "guest", "body": "try [b]this[/b]",
         "created_at": "2026-09-19T14:02:00", "edited_at": None},
    ]
    assert r"\[b]this\[/b]" in render_messages(messages, "bram")


def test_an_empty_channel_says_so():
    assert "Nothing said" in render_messages([], "bram")


def test_a_room_wears_a_hash_and_a_person_does_not():
    assert channel_label({"kind": "public", "name": "general"}) == "#general"
    assert channel_label({"kind": "private", "name": "club"}) == "#club"
    assert channel_label({"kind": "direct", "name": "guest"}) == "guest"


# -- the pane -----------------------------------------------------------------------
async def test_the_channels_are_listed_and_the_first_one_opens(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_chat(app, pilot)
        table = pane.query_one("#channel-table", DataTable)
        assert table.row_count == 2
        # The first channel is open without being asked for.
        assert pane._slug == "general"
        assert "the fans are loud again" in pane.query_one("#thread-text", Static).render().plain


async def test_opening_a_channel_marks_it_read(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_chat(app, pilot)
        assert app.client.read_marks[0] == ("general", 2), "read up to the last message"


async def test_moving_down_the_list_opens_the_other_one(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_chat(app, pilot)
        pane.query_one("#channel-table", DataTable).focus()
        await pilot.press("down")
        await settle(app, pilot)
        assert pane._slug == "dm-bram-guest"
        assert "are you up" in pane.query_one("#thread-text", Static).render().plain
        # The two waiting in it are no longer waiting.
        assert ("dm-bram-guest", 3) in app.client.read_marks


async def test_the_count_beside_a_channel_says_what_is_waiting(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_chat(app, pilot)
        table = pane.query_one("#channel-table", DataTable)
        # The direct channel has two unread; it is the second row.
        assert "2" in str(table.get_row_at(1)[1])
        assert str(table.get_row_at(0)[1]) == "", "nothing waiting in the open one"


async def test_writing_a_line_sends_it_and_shows_it(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_chat(app, pilot)
        box = pane.query_one("#chat-input", Input)
        box.focus()
        await pilot.press(*"hello there")
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.client.sent_messages == [("general", "hello there")]
        assert box.value == "", "the box is emptied on send"
        assert "hello there" in pane.query_one("#thread-text", Static).render().plain


async def test_an_empty_line_is_not_sent(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_chat(app, pilot)
        pane.query_one("#chat-input", Input).focus()
        await pilot.press("space", "enter")
        await settle(app, pilot)
        assert app.client.sent_messages == []


async def open_new_channel(app, pilot):
    """Fire the action and hand back the dialog it puts up.

    Not settle(): the action is a worker parked on the dialog, so waiting for
    the workers to finish while the dialog is open waits forever.
    """
    _, pane = await open_chat(app, pilot)
    pane.fire("channel")
    await pilot.pause()
    await pilot.pause()
    modal = app.screen
    assert isinstance(modal, NewChannelModal)
    return pane, modal


async def test_making_a_channel_asks_who_can_see_it_and_opens_it(app):
    async with app.run_test(size=(120, 40)) as pilot:
        pane, modal = await open_new_channel(app, pilot)
        modal.query_one("#channel-name", Input).value = "Rack Talk"
        modal.query_one("#channel-topic", Input).value = "the noisy cupboard"
        modal.query_one("#create").press()
        await settle(app, pilot)
        # Public by default, and nobody to add to a room everybody is in.
        assert app.client.channel_calls[0] == ("create", "rack-talk", "public", [])
        assert pane._slug == "rack-talk"


async def test_a_public_channel_does_not_ask_who_is_in_it(app):
    async with app.run_test(size=(120, 40)) as pilot:
        _, modal = await open_new_channel(app, pilot)
        assert modal.kind == "public"
        assert not modal.query_one("#channel-people").display, (
            "everybody is in a public channel; there is nobody to pick"
        )


async def test_picking_private_brings_up_the_people(app):
    async with app.run_test(size=(120, 40)) as pilot:
        _, modal = await open_new_channel(app, pilot)
        await pilot.click("#kind-private")
        await pilot.pause()
        assert modal.kind == "private"
        people = modal.query_one("#channel-people")
        assert people.display
        picker = modal.query_one("#channel-members", SelectionList)
        assert [option.value for option in picker.options] == ["guest", "ada"]
        assert "Guest (guest)" in str(picker.get_option_at_index(0).prompt), (
            "a display name is shown with the account name behind it"
        )


async def test_a_private_channel_is_made_with_the_people_ticked(app):
    async with app.run_test(size=(120, 40)) as pilot:
        pane, modal = await open_new_channel(app, pilot)
        modal.query_one("#channel-name", Input).value = "Plumbing"
        await pilot.click("#kind-private")
        await pilot.pause()
        modal.query_one("#channel-members", SelectionList).select("ada")
        await pilot.pause()
        modal.query_one("#create").press()
        await settle(app, pilot)
        assert app.client.channel_calls[0] == ("create", "plumbing", "private", ["ada"])
        assert pane._slug == "plumbing"


def test_the_bar_names_who_is_in_a_channel_just_made():
    public = {"kind": "public", "members": []}
    assert who_is_in(public) == "everybody is in it."
    assert "yours alone" in who_is_in({"kind": "private", "members": []})
    assert who_is_in({"kind": "private", "members": ["ada"]}) == "ada is in it."
    assert who_is_in({"kind": "private", "members": ["ada", "guest"]}) == (
        "ada and guest are in it."
    )
    assert who_is_in({"kind": "private", "members": list("abcd")}) == (
        "4 other people are in it."
    )


async def test_a_tick_taken_back_by_going_public_is_not_sent(app):
    async with app.run_test(size=(120, 40)) as pilot:
        _, modal = await open_new_channel(app, pilot)
        modal.query_one("#channel-name", Input).value = "Plumbing"
        await pilot.click("#kind-private")
        await pilot.pause()
        modal.query_one("#channel-members", SelectionList).select("ada")
        await pilot.pause()
        await pilot.click("#kind-public")
        await pilot.pause()
        modal.query_one("#create").press()
        await settle(app, pilot)
        assert app.client.channel_calls[0] == ("create", "plumbing", "public", [])


async def test_a_channel_with_no_name_is_complained_about_not_made(app):
    async with app.run_test(size=(120, 40)) as pilot:
        _, modal = await open_new_channel(app, pilot)
        modal.query_one("#create").press()
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, NewChannelModal), "the dialog stays up"
        assert "needs a name" in modal.query_one("#channel-complaint", Static).render().plain
        assert app.client.channel_calls == []


async def test_enter_in_the_name_moves_on_rather_than_making_it(app):
    async with app.run_test(size=(120, 40)) as pilot:
        _, modal = await open_new_channel(app, pilot)
        name = modal.query_one("#channel-name", Input)
        name.value = "Rack Talk"
        name.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert app.client.channel_calls == [], "who can see it has not been asked yet"
        assert modal.query_one("#channel-topic", Input).has_focus


async def test_writing_to_a_person_opens_the_channel_with_them(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_chat(app, pilot)
        pane.fire("direct")
        await settle(app, pilot)
        app.screen.query_one(Input).value = "Ada"
        await pilot.press("enter")
        await settle(app, pilot)
        # Lowercased on the way out, and the slug is the two names in order.
        assert app.client.channel_calls[0] == ("direct", "dm-ada-bram", "ada")
        assert pane._slug == "dm-ada-bram"


async def test_a_public_channel_refuses_to_be_added_to_or_left(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_chat(app, pilot)
        assert pane.channel["kind"] == "public"
        pane.fire("add")
        await settle(app, pilot)
        assert not isinstance(app.screen, PromptModal), "nothing to ask: everybody is in it"
        pane.fire("leave")
        await settle(app, pilot)
        assert not isinstance(app.screen, ConfirmModal)
        assert app.client.channel_calls == []


async def test_leaving_a_private_channel_confirms_first(app):
    app.client.channel_list.append(
        dict(app.client.channel_list[0], slug="club", name="club", kind="private", unread=0)
    )
    app.client.channel_messages["club"] = []
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_chat(app, pilot)
        pane.query_one("#channel-table", DataTable).focus()
        await pilot.press("down", "down")
        await settle(app, pilot)
        assert pane._slug == "club"

        pane.fire("leave")
        await settle(app, pilot)
        assert isinstance(app.screen, ConfirmModal)
        await pilot.click("#confirm")
        await settle(app, pilot)
        assert ("leave", "club", None) in app.client.channel_calls
        assert "club" not in [c["slug"] for c in app.client.channel_list]


async def test_the_tab_is_gone_when_the_server_has_chat_switched_off(app):
    for row in app.client.feature_list:
        if row["key"] == "chat":
            row["enabled"] = False
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        assert screen.query_one("#nav-chat").display is False
