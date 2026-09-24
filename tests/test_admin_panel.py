"""The Administration menu, and the panel behind it.

Driven with the mouse, like the rest of the workspace: the menu is a click,
the sections are clicks, and switching a feature off is a click on its box.
"""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Button, Checkbox, DataTable, Input, RadioButton, Static

from cloudmorrow.tui.panes.admin import AdminPanel
from tests.tui_harness import settle, start, user_row


def rows(screen) -> list[list[str]]:
    """What the table says, with the colour markup taken off."""
    table = screen.query_one("#admin-user-table", DataTable)
    return [
        [Text.from_markup(str(cell)).plain for cell in table.get_row_at(index)]
        for index in range(table.row_count)
    ]


async def open_dialog(app, pilot, button: str) -> None:
    """Click a toolbar button that opens a modal.

    Not `settle`: the worker behind the button is parked on the dialog until
    it is answered, so waiting for the workers to finish would wait forever.
    """
    await pilot.click(button)
    await pilot.pause()
    await pilot.pause()


async def open_admin(app, pilot):
    """Start, then click the menu on the top bar."""
    screen = await start(app, pilot)
    await pilot.click("#open-admin")
    await settle(app, pilot)
    return screen


async def test_an_admin_has_the_menu_and_a_user_does_not(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        assert screen.query_one("#open-admin", Button).display
        # And it sits left of Settings, where the sentence says it does.
        bar = [button.id for button in screen.query("#topbar-right Button")]
        assert bar.index("open-admin") < bar.index("open-settings")


async def test_a_plain_user_never_sees_it(app):
    async def member():
        return {"username": "guest", "is_admin": False}

    app.client.me = member
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        assert not screen.query_one("#open-admin", Button).display
        # And f9 does nothing for them.
        await pilot.press("f9")
        await settle(app, pilot)
        assert not screen.admin_showing


async def test_the_panel_replaces_the_interface_and_comes_back(app):
    """The whole workspace goes: this is the server, not a sixth tab."""
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_admin(app, pilot)
        assert screen.admin_showing
        assert not screen.query_one("#workspace-view").display
        assert screen.query_one("#open-admin", Button).has_class("-open")
        await pilot.click("#admin-back")
        await settle(app, pilot)
        assert not screen.admin_showing
        assert screen.query_one("#workspace-view").display
        assert not screen.query_one("#open-admin", Button).has_class("-open")


async def test_f9_opens_it_and_shuts_it(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        await pilot.press("f9")
        await settle(app, pilot)
        assert screen.admin_showing
        await pilot.press("f9")
        await settle(app, pilot)
        assert not screen.admin_showing


async def test_users_is_the_section_it_opens_on(app):
    """Every account, with what it may do and what is behind it."""
    app.client.user_list = [
        user_row("bram", role="administrator", display_name="Jimmi"),
        user_row("hallway", role="dashboard_displayer", user_type="systems_user"),
    ]
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_admin(app, pilot)
        assert screen.query_one("#admin-views").current == "admin-view-users"
        listed = rows(screen)
        assert [row[0] for row in listed] == ["bram", "hallway"]
        assert [row[2] for row in listed] == ["Administrator", "DashboardDisplayer"]
        assert [row[3] for row in listed] == ["Human", "SystemsUser"]


async def test_a_new_account_is_a_dialog_with_a_role_and_a_type(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_admin(app, pilot)
        await open_dialog(app, pilot, "#admin-view-users #do-new")
        dialog = app.screen
        dialog.query_one("#user-username", Input).value = "hallway"
        dialog.query_one("#user-password", Input).value = "supersecret1"
        await pilot.click("#role-dashboard_displayer")
        await pilot.click("#type-systems_user")
        await pilot.click("#save")
        await settle(app, pilot)
        assert app.client.user_calls == [
            ("create", "hallway", "dashboard_displayer", "systems_user")
        ]
        # And the table has it, without being told to refresh.
        assert rows(screen)[-1][0] == "hallway"


async def test_the_dialog_will_not_make_an_account_without_a_password(app):
    async with app.run_test(size=(120, 34)) as pilot:
        await open_admin(app, pilot)
        await open_dialog(app, pilot, "#admin-view-users #do-new")
        dialog = app.screen
        dialog.query_one("#user-username", Input).value = "hallway"
        await pilot.click("#save")
        # The dialog stays up and the worker behind it stays parked, so this
        # waits for the click rather than for the worker.
        await pilot.pause()
        await pilot.pause()
        assert app.screen is dialog
        assert "password" in dialog.query_one("#user-complaint", Static).visual.plain
        assert app.client.user_calls == []


async def test_editing_an_account_keeps_the_password_when_the_box_is_empty(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_admin(app, pilot)
        screen.query_one("#admin-user-table", DataTable).move_cursor(row=1)
        await open_dialog(app, pilot, "#admin-view-users #do-edit")
        dialog = app.screen
        # It opens on what the account already is.
        assert dialog.query_one("#user-username", Input).disabled
        assert dialog.query_one("#role-user", RadioButton).value
        await pilot.click("#role-administrator")
        await pilot.click("#save")
        await settle(app, pilot)
        what, username, fields = app.client.user_calls[0]
        assert (what, username) == ("update", "guest")
        assert fields["role"] == "administrator"
        assert "password" not in fields


async def test_features_switch_a_tab_off_everywhere(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_admin(app, pilot)
        await pilot.click("#admin-tab-features")
        await settle(app, pilot)
        await pilot.click("#feature-tasks")
        await settle(app, pilot)
        assert app.client.feature_calls == [("tasks", False)]
        # The strip behind the panel lost the tab, without a restart.
        assert screen.query_one("#nav").query_one("#tab-tasks").display is False
        assert screen.query_one("#nav").query_one("#tab-notes").display is True


async def test_a_switched_off_feature_is_gone_on_the_next_start(app):
    """The tab strip is drawn from what the server says it offers."""
    for row in app.client.feature_list:
        if row["key"] == "files":
            row["enabled"] = False
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        assert screen.query_one("#nav").query_one("#tab-files").display is False
        # And its key does nothing rather than showing an empty pane.
        await pilot.press("f5")
        await settle(app, pilot)
        assert screen.query_one("#panes").current == "pane-notes"


async def test_the_panel_is_where_refresh_goes_while_it_is_open(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_admin(app, pilot)
        app.client.user_list = [*app.client.user_list, user_row("nina")]
        await pilot.press("ctrl+r")
        await settle(app, pilot)
        assert isinstance(screen.query_one("#admin-view"), AdminPanel)
        assert rows(screen)[-1][0] == "nina"


async def test_switching_to_a_tab_shuts_the_panel(app):
    """A pane key means the workspace, so the panel gets out of the way."""
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_admin(app, pilot)
        await pilot.press("f2")
        await settle(app, pilot)
        assert not screen.admin_showing
        assert screen.query_one("#panes").current == "pane-tasks"


async def test_a_feature_the_server_refuses_to_switch_says_so(app):
    from cloudmorrow.client.api import ApiError

    async def refuse(key: str, enabled: bool) -> dict:
        raise ApiError("admin only", status_code=403)

    app.client.set_feature = refuse
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_admin(app, pilot)
        await pilot.click("#admin-tab-features")
        await settle(app, pilot)
        await pilot.click("#feature-notes")
        await settle(app, pilot)
        assert "admin only" in screen.query_one("#statusbar", Static).visual.plain
        # And the box goes back to what the server really thinks.
        assert screen.query_one("#feature-notes", Checkbox).value is True
