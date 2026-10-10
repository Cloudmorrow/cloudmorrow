"""Shares on this machine, in the terminal: the grid's extension for shares
(tui/sharemounts.py) — the MOUNTED HERE column, and New share, Share with,
Mount, Unmount, Copy URL and Remove on the share the cursor is on."""

from __future__ import annotations

import contextlib
from pathlib import Path

from textual.widgets import DataTable, Input, Static

from cloudmorrow.client import mounts, rclone
from cloudmorrow.tui.app import CloudmorrowApp
from cloudmorrow.tui.panes.kit_grid import GridPane
from cloudmorrow.tui.screens.install import InstallRcloneModal
from cloudmorrow.tui.screens.share_modals import NoticeModal
from tests.tui_harness import said, settle, start


async def open_files(app, pilot):
    screen = await start(app, pilot)
    await pilot.click("#nav-files")
    await settle(app, pilot)
    return screen


def rows(screen) -> list[list[str]]:
    table = screen.query_one("#grid-table", DataTable)
    return [[str(cell) for cell in table.get_row_at(index)] for index in range(table.row_count)]


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
        assert "sudo apt-get install -y rclone" in (dialog.query_one("#install-command", Static).visual.plain)
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
    """A name is all it takes: the folder of that name in Shares, yours."""
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_files(app, pilot)
        await pilot.click("#pane-files #do-new_group")
        await pilot.pause()
        await pilot.pause()
        await pilot.press(*"docs", "enter")
        await settle(app, pilot)
        assert app.client.share_calls == [("create", "docs", None, "", [])]
        assert [row[0] for row in rows(screen)] == ["media", "photos", "docs"]
        assert rows(screen)[2][1] == "On the server"


async def test_a_new_share_is_shared_with_people_and_circles(app):
    async with app.run_test(size=(120, 34)) as pilot:
        await open_files(app, pilot)
        await pilot.click("#pane-files #do-new_group")
        await pilot.pause()
        await pilot.pause()
        dialog = app.screen
        # Who there is to share with is said under the field.
        hint = dialog.query_one("#share-with-hint", Static).visual.plain
        assert "ann" in hint and "circle:Kids" in hint and "everyone" in hint
        await pilot.press(*"family")
        dialog.query_one("#share-with", Input).focus()
        await pilot.press(*"ann, circle:kids (read)", "enter")
        await settle(app, pilot)
        assert app.client.share_calls == [
            (
                "create",
                "family",
                None,
                "",
                [
                    {"kind": "user", "who": "ann", "access": "write"},
                    {"kind": "circle", "who": "kids", "access": "read"},
                ],
            )
        ]


async def test_an_administrator_sees_the_path_and_may_change_it(app):
    """The path follows the name; left as it is, the share is in Shares."""
    async with app.run_test(size=(120, 34)) as pilot:
        await open_files(app, pilot)
        await pilot.click("#pane-files #do-new_group")
        await pilot.pause()
        await pilot.pause()
        dialog = app.screen
        path = dialog.query_one("#share-path", Input)
        assert path.display
        # What is in Shares unshared is offered.
        assert "Pictures" in dialog.query_one("#share-path-hint", Static).visual.plain
        await pilot.press(*"pictures")
        await pilot.pause()
        assert path.value == "/srv/cloudmorrow/notes/Shares/pictures"
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.client.share_calls == [("create", "pictures", None, "", [])]


async def test_a_path_with_something_wrong_is_shared_and_said(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_files(app, pilot)
        await pilot.click("#pane-files #do-new_group")
        await pilot.pause()
        await pilot.pause()
        dialog = app.screen
        await pilot.press(*"world")
        dialog.query_one("#share-path", Input).value = "/srv/world"
        dialog.query_one("#share-name", Input).focus()
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.client.share_calls == [("create", "world", "/srv/world", "", [])]
        notice = app.screen
        assert isinstance(notice, NoticeModal)
        assert "world-writable" in notice.query_one("#notice-text", Static).visual.plain
        await pilot.press("escape")
        await settle(app, pilot)
        assert app.screen is screen


async def test_somebody_who_is_not_an_administrator_is_not_asked_for_a_path(app):
    async def member():
        return {"username": "bram", "is_admin": False}

    app.client.me = member
    async with app.run_test(size=(120, 34)) as pilot:
        await open_files(app, pilot)
        await pilot.click("#pane-files #do-new_group")
        await pilot.pause()
        await pilot.pause()
        assert not app.screen.query_one("#share-path", Input).display
        await pilot.press(*"docs", "enter")
        await settle(app, pilot)
        assert app.client.share_calls == [("create", "docs", None, "", [])]


async def test_who_has_a_share_is_changed_as_a_line(app):
    app.client.share_list[0]["members"] = [{"kind": "user", "who": "ann", "access": "write", "label": "Ann"}]
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_files(app, pilot)
        await pilot.click("#pane-files #do-share_with")
        await pilot.pause()
        await pilot.pause()
        line = app.screen.query_one("#members-line", Input)
        assert line.value == "ann"
        line.value = "circle:kids (read)"
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.client.share_calls == [
            ("unshare", "media", "user", "ann"),
            ("with", "media", "circle", "kids", "read"),
        ]
        assert "kids" in said(screen)


async def test_a_share_somebody_else_made_is_not_theirs_to_share(app):
    app.client.share_list[0].update(owner="ann", can_manage=False, access="read")
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_files(app, pilot)
        await pilot.click("#pane-files #do-share_with")
        await settle(app, pilot)
        assert app.screen is screen
        assert "only they decide" in said(screen)
        await pilot.click("#pane-files #do-remove")
        await settle(app, pilot)
        assert app.screen is screen
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
