"""The bell in the top bar, and the modal behind it.

What the machines have been doing is not about the tab you are on, so it lives
at the far right of the top line on every one of them. These click the bell
rather than pressing the key, and check the count on it as much as the list
inside.
"""

from __future__ import annotations

from textual.widgets import Button, Static

from cloudmorrow.tui.screens.notifications import NotificationsScreen
from tests.tui_harness import settle, start


def note(index: int, **extra) -> dict:
    return {
        "id": index,
        "kind": extra.get("kind", "config.updated"),
        "machine": "desktop",
        "title": extra.get("title", f"something happened {index}"),
        "body": extra.get("body", "and here is a line about it"),
        "created_at": "2026-09-11T08:30:00",
        "read_at": None,
        "unread": extra.get("unread", True),
    }


async def open_bell(app, pilot) -> NotificationsScreen:
    await start(app, pilot)
    await pilot.click("#open-notifications")
    await settle(app, pilot)
    assert isinstance(app.screen, NotificationsScreen)
    return app.screen


def listed(screen: NotificationsScreen) -> str:
    return screen.query_one("#notifications-list", Static).visual.plain


def bell(app) -> Button:
    return app.screen_stack[-1].query_one("#open-notifications", Button)


async def test_the_bell_counts_what_is_unread(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        # The one unread notification the fake server is holding, and the key
        # that opens it, which the bell carries rather than the footer.
        assert str(bell(app).label) == "🔔 1  f8"
        assert bell(app).has_class("has-unread")
        assert screen.query_one("#panes").current == "pane-notes"


async def test_a_quiet_bell_is_a_bell_with_no_count(app):
    app.client.notes = []
    async with app.run_test(size=(120, 34)) as pilot:
        await start(app, pilot)
        assert str(bell(app).label) == "🔔  f8"
        assert not bell(app).has_class("has-unread")


async def test_clicking_the_bell_lists_what_happened(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_bell(app, pilot)
        assert "omarchy config changed on desktop" in listed(screen)


async def test_the_keyboard_opens_it_too(app):
    async with app.run_test(size=(120, 34)) as pilot:
        await start(app, pilot)
        await pilot.press("f8")
        await settle(app, pilot)
        assert isinstance(app.screen, NotificationsScreen)


async def test_marking_them_read_empties_the_bell(app):
    async with app.run_test(size=(120, 34)) as pilot:
        await open_bell(app, pilot)
        await pilot.click("#read")
        await settle(app, pilot)

        assert all(not row["unread"] for row in app.client.notes)
        await pilot.press("escape")
        await settle(app, pilot)
        assert not bell(app).has_class("has-unread")


async def test_the_arrows_move_between_the_buttons_and_enter_presses_one(app):
    """A dialog has to be answerable without knowing that tab moves focus."""
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_bell(app, pilot)
        # It opens on the first button rather than on the list behind it.
        assert app.screen.focused is screen.query_one("#read", Button)

        await pilot.press("right")
        assert app.screen.focused is screen.query_one("#close", Button)
        await pilot.press("left")
        assert app.screen.focused is screen.query_one("#read", Button)
        # Down and up do the same, for whichever way you reach for.
        await pilot.press("down")
        assert app.screen.focused is screen.query_one("#close", Button)
        await pilot.press("up")
        assert app.screen.focused is screen.query_one("#read", Button)

        await pilot.press("enter")
        await settle(app, pilot)
        assert all(not row["unread"] for row in app.client.notes)


async def test_enter_on_close_closes_it(app):
    async with app.run_test(size=(120, 34)) as pilot:
        await open_bell(app, pilot)
        await pilot.press("right")
        await pilot.press("enter")
        await settle(app, pilot)
        assert not isinstance(app.screen, NotificationsScreen)


async def test_the_buttons_stay_on_screen_on_a_small_terminal(app):
    """However long the list, the way out is still visible."""
    app.client.notes = [note(index) for index in range(20)]
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await open_bell(app, pilot)
        close = screen.query_one("#close")
        assert close.region.bottom <= app.screen.size.height, "the buttons fell off the screen"
        assert close.region.height > 0


async def test_escape_closes_it(app):
    async with app.run_test(size=(120, 34)) as pilot:
        await open_bell(app, pilot)
        await pilot.press("escape")
        await settle(app, pilot)
        assert not isinstance(app.screen, NotificationsScreen)
