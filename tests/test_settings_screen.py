"""The settings screen: the machine you are at, and the tabs you want.

These press the button in the top bar, then a box, and check what the server
was told. What the machines have been doing is the bell's, and is tested with
it in `test_notifications_modal.py`.
"""

from __future__ import annotations

import pytest
from textual.widgets import Checkbox, Static

from cloudmorrow.tui.screens.settings import SettingsScreen
from tests.tui_harness import agent_row, settle, start


@pytest.fixture(autouse=True)
def this_machine(monkeypatch):
    """Name the machine the tests are sitting at, whatever it is really called."""
    monkeypatch.setattr("cloudmorrow.tui.screens.settings.machine_name", lambda: "laptop")


async def open_settings(app, pilot) -> SettingsScreen:
    await start(app, pilot)
    await pilot.click("#open-settings")
    await settle(app, pilot)
    assert isinstance(app.screen, SettingsScreen)
    return app.screen


def text_of(screen: SettingsScreen, selector: str) -> str:
    """What that line actually says on screen, markup resolved."""
    return screen.query_one(selector, Static).visual.plain


async def test_the_top_bar_opens_the_settings_screen(app):
    app.client.agent_list = [agent_row("laptop")]
    async with app.run_test() as pilot:
        screen = await open_settings(app, pilot)
        assert "laptop" in text_of(screen, "#settings-machine")
        assert "bram" in text_of(screen, "#settings-machine")


async def test_the_keyboard_opens_it_too(app):
    app.client.agent_list = [agent_row("laptop")]
    async with app.run_test() as pilot:
        await start(app, pilot)
        await pilot.press("ctrl+g")
        await settle(app, pilot)
        assert isinstance(app.screen, SettingsScreen)


async def test_there_is_no_config_sync_on_it(app):
    """Omarchy config sync is gone: no tick box for it, and nothing asked about it."""
    app.client.agent_list = [agent_row("laptop")]
    async with app.run_test() as pilot:
        screen = await open_settings(app, pilot)
        assert not screen.query("#sync-omarchy")
        assert not screen.query("#settings-omarchy")
        ids = [box.id or "" for box in screen.query(Checkbox)]
        assert all(box_id.startswith("myfeature-") for box_id in ids)


async def test_escape_closes_it(app):
    app.client.agent_list = [agent_row("laptop")]
    async with app.run_test() as pilot:
        await open_settings(app, pilot)
        await pilot.press("escape")
        await settle(app, pilot)
        assert not isinstance(app.screen, SettingsScreen)


# -- the tabs this account wants ---------------------------------------------------
async def boxes(screen: SettingsScreen) -> dict[str, Checkbox]:
    """The feature tick boxes, keyed by feature."""
    return {
        (box.id or "")[len("myfeature-") :]: box
        for box in screen.query(Checkbox)
        if (box.id or "").startswith("myfeature-")
    }


async def test_every_feature_this_server_offers_has_a_box(app):
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_settings(app, pilot)
        found = await boxes(screen)
        assert set(found) == {row["key"] for row in app.client.feature_list}
        assert all(box.value for box in found.values()), "a fresh account has everything"


async def test_a_feature_the_server_has_off_has_no_box(app):
    for row in app.client.feature_list:
        if row["key"] == "tasks":
            row["enabled"] = False
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_settings(app, pilot)
        found = await boxes(screen)
        assert "tasks" not in found, "not a thing this account can have a view about"
        assert "notes" in found


async def test_unticking_one_tells_the_server_and_takes_its_tab(app):
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_settings(app, pilot)
        (await boxes(screen))["chat"].value = False
        await settle(app, pilot)
        assert app.client.my_feature_calls == [("chat", False)]

        # Closing the dialog is when the strip behind it is drawn again.
        await pilot.press("escape")
        await settle(app, pilot)
        workspace = app.screen
        assert workspace.query_one("#nav-chat").display is False
        assert workspace.query_one("#nav-notes").display is True


async def test_ticking_one_back_on_brings_the_tab_back(app):
    app.client.features_off = {"chat"}
    async with app.run_test(size=(120, 40)) as pilot:
        workspace = await start(app, pilot)
        assert workspace.query_one("#nav-chat").display is False

        await pilot.click("#open-settings")
        await settle(app, pilot)
        (await boxes(app.screen))["chat"].value = True
        await settle(app, pilot)
        await pilot.press("escape")
        await settle(app, pilot)
        assert app.client.my_feature_calls == [("chat", True)]
        assert app.screen.query_one("#nav-chat").display is True


async def test_with_everything_off_the_workspace_says_so(app):
    app.client.features_off = {row["key"] for row in app.client.feature_list}
    async with app.run_test(size=(120, 40)) as pilot:
        workspace = await start(app, pilot)
        assert workspace.query_one("#nothing-showing").display is True
        assert workspace.query_one("#panes").display is False
