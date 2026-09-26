"""The bottom bar: status left, a few keys right — and ctrl+c, twice, to quit."""

from __future__ import annotations

from textual.widgets import Static

from cloudmorrow.tui import app as app_module
from cloudmorrow.tui.app import CloudmorrowApp
from cloudmorrow.tui.widgets.bottombar import MAX_TIPS, BottomBar
from tests.tui_harness import open_secrets, said, settle, start


def test_textuals_own_extras_are_off():
    assert CloudmorrowApp.ENABLE_COMMAND_PALETTE is False


async def test_ctrl_c_asks_once_and_quits_the_second_time(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert not app._exit
        status = screen.query_one("#statusbar", Static).visual.plain
        assert "ctrl+c again" in status
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert app._exit


async def test_a_lone_ctrl_c_is_forgotten_after_a_moment(app, monkeypatch):
    monkeypatch.setattr(app_module, "QUIT_WINDOW", 0.05)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        await pilot.press("ctrl+c")
        await pilot.pause(0.3)
        assert "ctrl+c again" not in screen.query_one("#statusbar", Static).visual.plain
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert not app._exit


async def test_ctrl_q_does_nothing(app):
    async with app.run_test(size=(120, 34)) as pilot:
        await start(app, pilot)
        await pilot.press("ctrl+q")
        await pilot.pause()
        assert not app._exit


async def test_the_bar_shows_at_most_five_keys_with_quit_last(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_secrets(app, pilot)
        tips = screen.query_one(BottomBar).tips()
        assert len(tips) <= MAX_TIPS
        assert tips[0] == ("n", "New vault")
        assert tips[-1] == ("^c", "Quit")
        # `n` and `ctrl+n` both make a vault; one tip covers them.
        assert [what for _, what in tips].count("New vault") == 1
        assert "^c Quit" in screen.query_one("#shortcuts", Static).visual.plain


async def test_a_message_is_said_once_in_the_log_and_the_bar_keeps_to_keys(app):
    """Said once: the log has it with the time, the bottom line only the keys —
    and a notice, which is the one thing that asks for something now."""
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        screen.set_status("saved")
        await settle(app, pilot)
        bar = screen.query_one(BottomBar)
        assert said(screen).endswith("saved")
        assert screen.query_one("#statusbar", Static).visual.plain == ""
        bar.notice = "look here"
        await pilot.pause()
        assert screen.query_one("#statusbar", Static).visual.plain == "look here"
        bar.notice = ""
        await pilot.pause()
        assert screen.query_one("#statusbar", Static).visual.plain == ""


async def test_how_a_pane_is_goes_in_its_header_not_the_log(app):
    """"2 accounts" is not something that happened, so it is not logged."""
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        pane = screen.active_pane
        pane.status("Nothing here yet", note=True)
        await settle(app, pilot)
        assert "Nothing here yet" not in [line.text for line in screen.query_one("#log").lines]
        assert "Nothing here yet" in pane.query_one(".pane-read", Static).visual.plain
