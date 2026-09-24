"""Your name on the top bar opens the box where you change your password."""

from __future__ import annotations

from textual.widgets import Button, Input, Static

from cloudmorrow.tui.screens.modals import PasswordModal
from tests.tui_harness import PRESS_ANIMATION, settle, start


async def open_it(app, pilot) -> PasswordModal:
    await pilot.click("#topbar-account")
    await settle(app, pilot)
    dialog = app.screen
    assert isinstance(dialog, PasswordModal)
    return dialog


async def fill(pilot, dialog: PasswordModal, current: str, new: str, repeat: str) -> None:
    dialog.query_one("#current-password", Input).value = current
    dialog.query_one("#new-password", Input).value = new
    dialog.query_one("#repeat-password", Input).value = repeat


def error_text(dialog: PasswordModal) -> str:
    return dialog.query_one("#password-error", Static).visual.plain.strip()


async def test_the_account_on_the_top_bar_is_a_button_that_opens_the_dialog(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        account = screen.query_one("#topbar-account", Button)
        assert "bram@test.invalid" in str(account.label)
        dialog = await open_it(app, pilot)
        # The current password is what you type first, so that is where you are.
        assert app.screen.focused is dialog.query_one("#current-password", Input)


async def test_a_new_password_reaches_the_server_and_the_dialog_closes(app):
    async with app.run_test(size=(120, 34)) as pilot:
        await start(app, pilot)
        dialog = await open_it(app, pilot)
        await fill(pilot, dialog, "supersecret1", "evenmoresecret2", "evenmoresecret2")
        await pilot.click("#change")
        await settle(app, pilot)
        assert not isinstance(app.screen, PasswordModal)
        assert app.client.password_calls == [("supersecret1", "evenmoresecret2")]
        assert app.client.password == "evenmoresecret2"
        # Said in the status bar, not popped up: a notification is something else.
        assert "Password changed" in app.screen.query_one("#statusbar", Static).visual.plain
        assert not app._notifications


async def test_enter_walks_down_the_fields_and_submits_from_the_last(app):
    async with app.run_test(size=(120, 34)) as pilot:
        await start(app, pilot)
        dialog = await open_it(app, pilot)
        await pilot.press(*"supersecret1", "enter")
        assert app.screen.focused is dialog.query_one("#new-password", Input)
        await pilot.press(*"evenmoresecret2", "enter")
        assert app.screen.focused is dialog.query_one("#repeat-password", Input)
        await pilot.press(*"evenmoresecret2", "enter")
        await settle(app, pilot)
        assert not isinstance(app.screen, PasswordModal)
        assert app.client.password == "evenmoresecret2"


async def test_the_wrong_current_password_is_said_in_the_dialog(app):
    async with app.run_test(size=(120, 34)) as pilot:
        await start(app, pilot)
        dialog = await open_it(app, pilot)
        await fill(pilot, dialog, "notmypassword", "evenmoresecret2", "evenmoresecret2")
        await pilot.click("#change")
        await settle(app, pilot)
        assert app.screen is dialog
        assert "not your current password" in error_text(dialog)
        # The wrong one is cleared for another go; the new one is kept.
        assert dialog.query_one("#current-password", Input).value == ""
        assert dialog.query_one("#new-password", Input).value == "evenmoresecret2"
        assert app.client.password == "supersecret1"


async def test_a_mismatch_or_a_short_password_never_reaches_the_server(app):
    async with app.run_test(size=(120, 34)) as pilot:
        await start(app, pilot)
        dialog = await open_it(app, pilot)
        await fill(pilot, dialog, "supersecret1", "evenmoresecret2", "evenmoresecret3")
        await pilot.click("#change")
        await settle(app, pilot)
        assert "not the same" in error_text(dialog)

        await fill(pilot, dialog, "supersecret1", "short", "short")
        await pilot.click("#change")
        # The same button twice: a Button ignores a click while its press
        # animation is still running, and on a busy machine that is long
        # enough to swallow this one and leave the first complaint up.
        await settle(app, pilot, delay=PRESS_ANIMATION)
        assert "at least 8" in error_text(dialog)
        assert getattr(app.client, "password_calls", []) == []


async def test_escape_and_cancel_change_nothing(app):
    async with app.run_test(size=(120, 34)) as pilot:
        await start(app, pilot)
        dialog = await open_it(app, pilot)
        await fill(pilot, dialog, "supersecret1", "evenmoresecret2", "evenmoresecret2")
        await pilot.press("escape")
        await settle(app, pilot)
        assert not isinstance(app.screen, PasswordModal)
        assert getattr(app.client, "password_calls", []) == []
