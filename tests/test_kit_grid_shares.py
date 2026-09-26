"""Shares on this machine, in the terminal: the grid's extension for shares
(tui/sharemounts.py) — the MOUNTED HERE column, and New share, Mount,
Unmount, Copy URL and Remove on the share the cursor is on."""

from __future__ import annotations

import contextlib
from pathlib import Path

from textual.widgets import DataTable, Input, Static

from cloudmorrow.agent.setup import machine_name
from cloudmorrow.client import mounts, rclone
from cloudmorrow.tui.app import CloudmorrowApp
from cloudmorrow.tui.panes.kit_grid import GridPane
from cloudmorrow.tui.screens.install import InstallRcloneModal
from cloudmorrow.tui.screens.modals import NoticeModal
from tests.tui_harness import agent_row, said, settle, start


async def open_files(app, pilot):
    screen = await start(app, pilot)
    await pilot.click("#nav-files")
    await settle(app, pilot)
    return screen


def rows(screen) -> list[list[str]]:
    table = screen.query_one("#grid-table", DataTable)
    return [
        [str(cell) for cell in table.get_row_at(index)] for index in range(table.row_count)
    ]


async def test_files_opens_on_the_shares_with_where_each_is_mounted(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_files(app, pilot)
        pane = screen.active_pane
        assert isinstance(pane, GridPane)
        assert [row[0] for row in rows(screen)] == ["media", "photos"]
        assert rows(screen)[0][1] == "On the server"
        assert "—" in rows(screen)[0][2]
        header = [str(c.label) for c in screen.query_one("#grid-table", DataTable).columns.values()]
        assert header[-1] == "MOUNTED HERE"
        # The selected share's address is in the panel's header, for any other client.
        status = pane.query_one(".pane-read", Static).visual.plain
        assert "https://test.invalid/dav/media/" in status


async def test_mount_asks_where_and_mounts_as_you(app, monkeypatch):
    """On Linux: a path to confirm, then rclone — signed in with the session's token."""
    calls: list[tuple] = []

    def fake_mount(name, url, username, secret, *, path=None):
        calls.append((name, url, username, secret, path))
        mounted = mounts.Mount(name=name, path=path, url=url, tool="rclone")
        mounts.remember(mounted)
        return mounted

    monkeypatch.setattr(mounts, "platform", lambda: "linux")
    monkeypatch.setattr(mounts, "mount", fake_mount)
    monkeypatch.setattr(rclone, "installed", lambda: True)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_files(app, pilot)
        await pilot.click("#pane-files #do-mount")
        await pilot.pause()
        await pilot.pause()
        # The prompt offers ~/Fileshares/<name>; enter takes it.
        assert screen is not app.screen
        await pilot.press("enter")
        await settle(app, pilot)
        assert calls == [
            (
                "media",
                "https://test.invalid/dav/media/",
                "bram",
                "test-token",
                Path.home() / "Fileshares" / "media",
            )
        ]
        assert str(Path.home() / "Fileshares" / "media") in rows(screen)[0][2]
        assert "mounted at" in said(screen)


async def test_on_a_mac_there_is_nothing_to_ask(app, monkeypatch):
    calls: list[tuple] = []

    def fake_mount(name, url, username, secret, *, path=None):
        calls.append((name, path))
        return mounts.Mount(name=name, path=Path("/Volumes") / name, url=url, tool="finder")

    monkeypatch.setattr(mounts, "platform", lambda: "darwin")
    monkeypatch.setattr(mounts, "mount", fake_mount)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_files(app, pilot)
        await pilot.click("#pane-files #do-mount")
        await settle(app, pilot)
        assert calls == [("media", None)]
        assert "/Volumes/media" in said(screen)


async def test_a_mount_that_fails_says_why_in_a_dialog(app, monkeypatch):
    """The reason is a line from rclone's log — too long for the bar."""
    reason = "could not mount media: 2026/09/18 10:00:00 NOTICE: webdav root '': connection refused"

    def fake_mount(*args, **kwargs):
        raise mounts.MountError(reason)

    monkeypatch.setattr(mounts, "platform", lambda: "darwin")
    monkeypatch.setattr(mounts, "mount", fake_mount)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_files(app, pilot)
        await pilot.click("#pane-files #do-mount")
        await settle(app, pilot)
        dialog = app.screen
        assert isinstance(dialog, NoticeModal)
        assert dialog.query_one("#notice-text", Static).visual.plain == reason
        # The bar has the short version, for after the dialog is closed.
        assert "Could not mount media" in said(screen)
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.screen is screen


# -- no rclone ------------------------------------------------------------------------


def without_rclone(monkeypatch, *, command=("sudo", "apt-get", "install", "-y", "rclone")):
    """A Linux machine with no rclone, whose package manager is apt."""
    state = {"installed": False}
    monkeypatch.setattr(mounts, "platform", lambda: "linux")
    monkeypatch.setattr(rclone, "installed", lambda: state["installed"])
    monkeypatch.setattr(rclone, "install_command", lambda: list(command) if command else None)
    return state


async def test_without_rclone_mount_offers_to_install_it_and_then_mounts(app, monkeypatch):
    state = without_rclone(monkeypatch)
    installs: list[bool] = []
    suspended: list[bool] = []

    def fake_install():
        installs.append(True)
        state["installed"] = True
        return Path("/usr/bin/rclone")

    @contextlib.contextmanager
    def fake_suspend(self):
        suspended.append(True)
        yield

    def fake_mount(name, url, username, secret, *, path=None):
        return mounts.Mount(name=name, path=path, url=url, tool="rclone")

    monkeypatch.setattr(rclone, "install", fake_install)
    monkeypatch.setattr(CloudmorrowApp, "suspend", fake_suspend)
    monkeypatch.setattr(mounts, "mount", fake_mount)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_files(app, pilot)
        await pilot.click("#pane-files #do-mount")
        await pilot.pause()
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, InstallRcloneModal)
        assert "sudo apt-get install -y rclone" in (
            dialog.query_one("#install-command", Static).visual.plain
        )
        await pilot.click("#install")
        await pilot.pause()
        await pilot.pause()
        # Installed with the terminal handed over, then straight on to where.
        assert installs == [True] and suspended == [True]
        assert not isinstance(app.screen, InstallRcloneModal) and app.screen is not screen
        await pilot.press("enter")
        await settle(app, pilot)
        assert "mounted at" in said(screen)


async def test_declining_the_install_mounts_nothing(app, monkeypatch):
    without_rclone(monkeypatch)
    calls: list = []
    monkeypatch.setattr(rclone, "install", lambda: calls.append("install"))
    monkeypatch.setattr(mounts, "mount", lambda *a, **k: calls.append("mount"))
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_files(app, pilot)
        await pilot.click("#pane-files #do-mount")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, InstallRcloneModal)
        await pilot.press("escape")
        await settle(app, pilot)
        assert app.screen is screen
        assert calls == []


async def test_an_install_that_fails_says_why_in_a_dialog(app, monkeypatch):
    without_rclone(monkeypatch)

    def failing_install():
        raise rclone.InstallError("`sudo apt-get install -y rclone` exited 100")

    monkeypatch.setattr(rclone, "install", failing_install)
    monkeypatch.setattr(CloudmorrowApp, "suspend", lambda self: contextlib.nullcontext())
    async with app.run_test(size=(120, 34)) as pilot:
        await open_files(app, pilot)
        await pilot.click("#pane-files #do-mount")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("y")
        await settle(app, pilot)
        dialog = app.screen
        assert isinstance(dialog, NoticeModal)
        assert "exited 100" in dialog.query_one("#notice-text", Static).visual.plain


async def test_where_the_terminal_cannot_be_handed_over_the_command_is_shown(app, monkeypatch):
    """The headless driver cannot suspend, which is what textual-web looks like too."""
    without_rclone(monkeypatch)
    calls: list = []
    monkeypatch.setattr(rclone, "install", lambda: calls.append("install"))
    async with app.run_test(size=(120, 34)) as pilot:
        await open_files(app, pilot)
        await pilot.click("#pane-files #do-mount")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("y")
        # Not settle: the worker is waiting on the dialog, and so would we.
        await pilot.pause()
        await pilot.pause()
        dialog = app.screen
        command = dialog.query_one("#command-text", Static).visual.plain
        assert "sudo apt-get install -y rclone" in command
        assert calls == []
        await pilot.press("escape")
        await settle(app, pilot)


async def test_with_no_package_manager_the_dialog_says_where_to_read(app, monkeypatch):
    without_rclone(monkeypatch, command=None)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_files(app, pilot)
        await pilot.click("#pane-files #do-mount")
        await pilot.pause()
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, InstallRcloneModal)
        assert rclone.DOWNLOAD in dialog.query_one("#install-text", Static).visual.plain
        assert list(dialog.query("#install")) == []
        # y is not an answer when there is nothing to say yes to.
        await pilot.press("y")
        await settle(app, pilot)
        assert app.screen is screen


async def test_new_share_is_created_on_the_server(app):
    """An admin with no machines: the only place a share can go is the server."""
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_files(app, pilot)
        await pilot.click("#pane-files #do-new_group")
        await pilot.pause()
        await pilot.pause()
        await pilot.press(*"docs", "enter")
        await settle(app, pilot)
        assert app.client.share_calls == [("create", "docs", None, "")]
        assert [row[0] for row in rows(screen)] == ["media", "photos", "docs"]
        assert rows(screen)[2][1] == "On the server"


async def test_a_server_share_is_named_not_placed(app):
    """An admin choosing the server sees no path field, and what a name would pick up."""
    here = machine_name()
    app.client.agent_list = [agent_row(here, online=True)]
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_files(app, pilot)
        await pilot.click("#pane-files #do-new_group")
        await pilot.pause()
        await pilot.pause()
        dialog = app.screen
        # This machine has an agent, so the dialog starts there, path and all.
        assert dialog.query_one("#share-path", Input).display
        await pilot.click("#kind-server")
        await pilot.pause()
        assert not dialog.query_one("#share-path", Input).display
        # The name is the folder in Shares; what is in there unshared is offered.
        name_hint = dialog.query_one("#share-name-hint", Static).visual.plain
        assert "/srv/cloudmorrow/notes/Shares" in name_hint
        assert "Pictures" in dialog.query_one("#share-hint", Static).visual.plain
        dialog.query_one("#share-name", Input).focus()
        await pilot.press(*"pictures", "enter")
        await settle(app, pilot)
        assert app.client.share_calls == [("create", "pictures", None, "")]
        assert rows(screen)[2][1] == "On the server"


async def test_new_share_goes_on_this_machine_when_it_has_an_agent(app, tmp_path):
    """With this machine enrolled, a new share is on it by default, and needs its path."""
    here = machine_name()
    music = tmp_path / "Music"
    music.mkdir()
    app.client.agent_list = [agent_row("laptop", online=True), agent_row(here, online=True)]
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_files(app, pilot)
        await pilot.click("#pane-files #do-new_group")
        await pilot.pause()
        await pilot.pause()
        await pilot.press(*"music", "enter")
        await pilot.pause()
        # Name alone is not enough: the directory on this machine is asked for.
        assert app.client.share_calls == []
        await pilot.press(*str(music), "enter")
        await settle(app, pilot)
        assert app.client.share_calls == [("create", "music", str(music.resolve()), "")]
        created = app.client.share_list[-1]
        # This machine, not the laptop: there was never a choice to make.
        assert (created["kind"], created["machine"]) == ("machine", here)
        assert rows(screen)[2][1].startswith(f"On {here}")


async def test_a_directory_that_cannot_be_shared_keeps_the_dialog_open(app, tmp_path):
    """Not there, or not yours to read: said under the path, and nothing is sent."""
    here = machine_name()
    app.client.agent_list = [agent_row(here, online=True)]
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_files(app, pilot)
        await pilot.click("#pane-files #do-new_group")
        await pilot.pause()
        await pilot.pause()
        dialog = app.screen
        await pilot.press(*"music", "enter")
        await pilot.pause()
        await pilot.press(*str(tmp_path / "nowhere"), "enter")
        await pilot.pause()
        await pilot.pause()
        assert app.screen is dialog
        assert "not there" in dialog.query_one("#share-hint", Static).visual.plain
        assert app.client.share_calls == []
        await pilot.press("escape")
        await settle(app, pilot)
        assert app.screen is screen


async def test_a_share_is_never_made_from_another_machine(app):
    """Other machines are not on offer: an admin here without an agent gets the server."""
    app.client.agent_list = [agent_row("laptop", online=True)]
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_files(app, pilot)
        await pilot.click("#pane-files #do-new_group")
        await pilot.pause()
        await pilot.pause()
        dialog = app.screen
        assert dialog.query_one("#kind-machine").disabled
        assert dialog.query_one("#kind-server").value
        assert list(dialog.query("#share-machine")) == []
        await pilot.press(*"docs", "enter")
        await settle(app, pilot)
        assert app.client.share_calls == [("create", "docs", None, "")]
        assert rows(screen)[2][1] == "On the server"


async def test_a_machine_with_no_agent_cannot_share_and_says_so(app):
    """Not an admin, and no agent here: nothing can serve a share, so no dialog."""

    async def member():
        return {"username": "bram", "is_admin": False}

    app.client.me = member
    app.client.agent_list = [agent_row("laptop", online=True)]
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_files(app, pilot)
        await pilot.click("#pane-files #do-new_group")
        await settle(app, pilot)
        assert app.screen is screen
        assert "no agent" in said(screen)
        assert app.client.share_calls == []


async def test_remove_unmounts_here_and_keeps_the_files(app, monkeypatch):
    unmounted: list[str] = []
    monkeypatch.setattr(mounts, "unmount", lambda name: unmounted.append(name))
    mounts.remember(mounts.Mount("media", Path("/tmp/x"), "u", "rclone"))
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_files(app, pilot)
        await pilot.click("#pane-files #do-remove")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("y")
        await settle(app, pilot)
        assert unmounted == ["media"]
        # Files stay: the TUI never asks the server to delete them.
        assert app.client.share_calls == [("delete", "media", False)]
        assert [row[0] for row in rows(screen)] == ["photos"]
