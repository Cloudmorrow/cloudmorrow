"""The settings screen: the machine you are at, and the tick box on it.

The claim the screen makes is that one tick is the whole of the feature — so
these press the button in the top bar, then the box, and check what the server
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
    monkeypatch.setattr("cloudmorrow.tui.screens.settings.describe", lambda: "Omarchy — ~/.config")
    monkeypatch.setattr("cloudmorrow.tui.screens.settings.is_omarchy", lambda: True)


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


async def test_an_omarchy_machine_can_be_ticked(app):
    app.client.agent_list = [agent_row("laptop")]
    async with app.run_test() as pilot:
        screen = await open_settings(app, pilot)
        box = screen.query_one("#sync-omarchy", Checkbox)
        assert not box.disabled
        assert box.value is False
        # Unclaimed: the screen says what ticking it would mean.
        assert "first machine" in text_of(screen, "#settings-bundle")

        await pilot.click("#sync-omarchy")
        await settle(app, pilot)

        assert app.client.sync_calls == [(1, ["omarchy"])]


async def test_unticking_tells_the_server_to_stop(app):
    app.client.agent_list = [agent_row("laptop", sync_bundles=["omarchy"])]
    async with app.run_test() as pilot:
        screen = await open_settings(app, pilot)
        assert screen.query_one("#sync-omarchy", Checkbox).value is True
        # Reading the state back must not post it: only a click does that.
        assert app.client.sync_calls == []

        await pilot.click("#sync-omarchy")
        await settle(app, pilot)
        assert app.client.sync_calls == [(1, [])]


async def test_a_machine_that_is_not_omarchy_cannot_be_ticked(app, monkeypatch):
    monkeypatch.setattr("cloudmorrow.tui.screens.settings.is_omarchy", lambda: False)
    monkeypatch.setattr(
        "cloudmorrow.tui.screens.settings.describe", lambda: "no ~/.config/hypr on this machine"
    )
    app.client.agent_list = [agent_row("laptop", capabilities=["ping", "sysinfo"])]
    async with app.run_test() as pilot:
        screen = await open_settings(app, pilot)
        assert screen.query_one("#sync-omarchy", Checkbox).disabled
        assert "nothing to sync" in text_of(screen, "#settings-omarchy")


async def test_a_machine_with_no_agent_says_so(app):
    app.client.agent_list = [agent_row("some-other-box", id=7)]
    async with app.run_test() as pilot:
        screen = await open_settings(app, pilot)
        assert screen.query_one("#sync-omarchy", Checkbox).disabled
        assert "No agent enrolled" in text_of(screen, "#settings-omarchy")


async def test_a_claimed_bundle_shows_where_it_came_from(app):
    app.client.agent_list = [agent_row("laptop", sync_bundles=["omarchy"])]
    app.client.bundle = {
        "bundle": "omarchy",
        "revision": 4,
        "origin": "desktop",
        "claimed_by": "desktop",
        "claimed_at": "2026-09-01T10:00:00",
        "updated_at": "2026-09-11T08:30:00",
        "files": [{"path": "hypr/hyprland.conf", "sha256": "abc", "mode": 420}],
        "machines": ["desktop", "laptop"],
    }
    async with app.run_test() as pilot:
        screen = await open_settings(app, pilot)
        bundle = text_of(screen, "#settings-bundle")
        assert "revision 4" in bundle
        assert "desktop" in bundle
        assert "1 files" in bundle


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
