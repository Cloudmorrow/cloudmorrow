"""Files: this machine's backups, your fileshares, and what is in them.

Three things, so three tabs inside the one, the way Secrets has vaults and
Secrets. **Local backups** is a placeholder for now — `cloudmorrow agent run`
still queues one. **Fileshares** is real: your shares — on the server, or on one
of your machines and served by its agent — which of them is mounted on this
machine and where, and the buttons that make, mount, unmount and remove one.
**Browse** is what is in a server share, as a list or as thumbnails, with
the picture the cursor is on drawn beside; it lives in browse.py.

Local backups is first in the strip, because that is the order they will
matter in; Fileshares is where you land, because it is the one that does
the most. Enter on a share there opens it in Browse.
"""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

from textual import work
from textual.app import ComposeResult, SuspendNotSupported
from textual.containers import Vertical
from textual.widgets import ContentSwitcher, DataTable, Static, Tab, Tabs

from cloudmorrow.agent.setup import machine_name
from cloudmorrow.client import mounts, rclone
from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.panes.base import Pane
from cloudmorrow.tui.panes.browse import BrowsePane
from cloudmorrow.tui.screens.install import InstallRcloneModal
from cloudmorrow.tui.screens.modals import (
    CommandModal,
    ConfirmModal,
    NoticeModal,
    PromptModal,
    ShareModal,
)
from cloudmorrow.tui.theme import GOOD, MUTED, WARN
from cloudmorrow.tui.widgets.toolbar import Action


class LocalBackupsPane(Pane):
    """Where this machine's backups will be listed. Nothing to list yet."""

    TAB_LABEL = "Local backups"
    HEAD = False

    def content(self) -> ComposeResult:
        yield Static(
            f"[b]Local backups[/]\n\n"
            f"[{MUTED}]Nothing here yet. This is where the backups this machine keeps "
            f"will be listed, with what is in them and when they ran.\n\n"
            f"Until then, [b]cloudmorrow agent run <id> backup[/] still queues one on any "
            f"machine running the agent.[/]",
            id="backups-placeholder",
        )


class FilesharesPane(Pane):
    """Your shares in a table, and what this machine has done with them."""

    TAB_LABEL = "Fileshares"
    HEAD = False
    BINDINGS = [
        ("ctrl+n", "fire('new_share')", "New share"),
        ("b", "fire('browse')", "Browse"),
        ("m", "fire('mount')", "Mount"),
        ("u", "fire('unmount')", "Unmount"),
        ("c", "fire('copy_url')", "Copy URL"),
        ("d", "fire('remove')", "Remove"),
        ("r", "fire('refresh')", "Refresh"),
    ]
    ACTIONS = (
        Action("new_share", "New share", "^n", variant="primary"),
        Action("browse", "Browse", "b", hint="What is in the share, from here; enter too"),
        Action("mount", "Mount", "m", hint="Mount the selected share on this machine"),
        Action("unmount", "Unmount", "u", hint="Unmount it here; the share stays"),
        Action("copy_url", "Copy URL", "c", hint="Its WebDAV address, for any other client"),
        Action("remove", "Remove", "d", variant="error", hint="Stop serving it; files stay"),
    )

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.shares: list[dict] = []

    def content(self) -> ComposeResult:
        with Vertical(id="shares-body"):
            yield DataTable(id="share-table", cursor_type="row")

    def on_mount(self) -> None:
        self.query_one("#share-table", DataTable).add_columns(
            "SHARE", "WHERE", "MOUNTED HERE", "DIRECTORY", "ABOUT"
        )

    def on_show(self) -> None:
        self.reload()

    # -- data --------------------------------------------------------------
    @property
    def selected(self) -> dict | None:
        table = self.query_one("#share-table", DataTable)
        if not self.shares or not 0 <= table.cursor_row < len(self.shares):
            return None
        return self.shares[table.cursor_row]

    @work(exclusive=True, group="shares")
    async def reload(self) -> None:
        client = self.api
        if client is None:
            return
        try:
            self.shares = await client.shares()
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.draw()
        if not self.shares:
            self.status(
                "No shares yet — New share serves a directory from one of your machines.",
                note=True,
            )
        else:
            self.status()

    def draw(self) -> None:
        table = self.query_one("#share-table", DataTable)
        row = table.cursor_row
        table.clear()
        for share in self.shares:
            table.add_row(
                share["name"],
                self._where_cell(share),
                self._mounted_cell(share["name"]),
                self._directory_cell(share),
                share.get("description") or "",
            )
        if self.shares:
            table.move_cursor(row=min(max(row, 0), len(self.shares) - 1))
        self._redraw_status()

    @staticmethod
    def _where_cell(share: dict) -> str:
        """Server, or the machine — lit while its agent is serving."""
        if share.get("kind") == "drive":
            return "server  [dim]yours[/]"
        if share.get("kind") != "machine":
            return "server"
        machine = share.get("machine") or "?"
        if share.get("online"):
            return f"[{GOOD}]●[/] {machine}"
        return f"[{WARN}]○[/] {machine}  [{MUTED}]offline[/]"

    @staticmethod
    def _directory_cell(share: dict) -> str:
        if share.get("kind") == "machine" or share["managed"]:
            return share["path"]
        return f"{share['path']}  [{MUTED}]existing[/]"

    @staticmethod
    def _mounted_cell(name: str) -> str:
        mounted = mounts.lookup(name)
        if mounted is None:
            return f"[{MUTED}]—[/]"
        if mounted.active:
            return f"[{GOOD}]● {mounted.path}[/]"
        # Recorded, but not there: a reboot, or an unmount by hand.
        return f"[{WARN}]○ {mounted.path}[/]"

    def status_detail(self) -> str:
        share = self.selected
        if not share:
            return ""
        if share["url"]:
            return f"[{MUTED}]{share['url']}[/]"
        return f"[{MUTED}]{share.get('machine')} has not said where it serves yet[/]"

    def _redraw_status(self) -> None:
        redraw = getattr(self.screen, "redraw_status", None)
        if callable(redraw):
            redraw()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.act_browse()

    def act_browse(self) -> None:
        """The selected share, opened in the Browse view beside this one."""
        share = self.selected
        if share is None:
            return
        if share.get("kind") == "machine":
            self.status(
                f"{share['name']} is on {share.get('machine') or 'a machine'} — "
                "mount it to browse it.",
                note=True,
            )
            return
        files = next((node for node in self.ancestors if isinstance(node, FilesPane)), None)
        if files is not None:
            files.browse(share["name"])

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "share-table":
            self._redraw_status()

    # -- actions -----------------------------------------------------------
    def act_refresh(self) -> None:
        self.reload()

    def act_new_share(self) -> None:
        self.new_share()

    @work(group="ui")
    async def new_share(self) -> None:
        try:
            me = await self.api.me()
            machines = await self.api.agents()
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        here = machine_name()
        admin = bool(me.get("is_admin"))
        if not admin and not any(m.get("name") == here for m in machines):
            # A share is a directory on this machine, and only its agent can
            # serve one. Without that there is nothing to open a dialog for.
            self.status(
                f"This machine ({here}) has no agent, so nothing here can serve a share — "
                "`cloudmorrow login` enrols it.",
                error=True,
            )
            return
        folders: dict | None = None
        if admin:
            # What a server share of a given name would pick up. Nice to
            # know, not needed: without it the dialog still works.
            try:
                folders = await self.api.share_folders()
            except ApiError:
                folders = None
        fields = await self.app.push_screen_wait(
            ShareModal(machines=machines, admin=admin, this_machine=here, folders=folders)
        )
        if fields is None:
            return
        # The dialog checked a machine share's directory and resolved it.
        path = fields["path"] or None
        try:
            share = await self.api.create_share(
                fields["name"],
                kind=fields["kind"],
                path=path,
                machine=fields["machine"] or None,
                description=fields["description"],
            )
        except ApiError as exc:
            # The reason is the server's — "no such directory on the server:
            # /srv/…", "a share with that name exists" — and has to be read.
            self._complain(f"Could not create {fields['name']}", exc)
            return
        if share.get("kind") == "machine" and not share.get("online"):
            self.status(
                f"Created {share['name']} — {share.get('machine')} starts serving it on its "
                f"agent's next heartbeat."
            )
        else:
            self.status(f"Created {share['name']} — Mount puts it on this machine.")
        self.reload()

    def act_mount(self) -> None:
        self.mount_share()

    @work(group="ui")
    async def mount_share(self) -> None:
        share = self.selected
        if share is None:
            self.status("No share selected.", error=True)
            return
        token = getattr(self.api, "token", None)
        username = getattr(self.app, "username", "")
        if not token or not username:
            self.status("Not signed in.", error=True)
            return
        if share.get("kind") == "machine" and not share.get("online"):
            self.status(
                f"{share['name']} is on {share.get('machine')}, and its agent is not serving "
                f"right now.",
                error=True,
            )
            return
        path: Path | None = None
        if mounts.platform() != mounts.MACOS:
            if not await self._ensure_rclone():
                return
            answer = await self.app.push_screen_wait(
                PromptModal(
                    f"Mount {share['name']} at",
                    value=str(mounts.default_mountpoint(share["name"])),
                    detail=(
                        "[dim]An empty directory; it is made if it is not there. "
                        "rclone does the mounting on Linux.[/]"
                    ),
                )
            )
            if answer is None:
                return
            path = Path(answer).expanduser()
        self.status(f"mounting {share['name']}…", note=True)
        try:
            mounted = await asyncio.to_thread(
                mounts.mount, share["name"], share["url"], username, token, path=path
            )
        except mounts.MountError as exc:
            self._complain(f"Could not mount {share['name']}", exc)
            return
        self.draw()
        self.status(f"{share['name']} is mounted at {mounted.path}")

    async def _ensure_rclone(self) -> bool:
        """rclone, or the dialog that gets it: True once it is on this machine.

        The install runs with the app suspended, so the terminal is the
        package manager's and sudo can ask for a password. Where the app
        cannot step aside — textual-web has no terminal to give — the
        command is shown to run by hand instead.
        """
        if rclone.installed():
            return True
        command = rclone.install_command()
        wanted = await self.app.push_screen_wait(InstallRcloneModal(command))
        if not wanted or command is None:
            return False
        self.status("installing rclone…", note=True)
        try:
            with self.app.suspend():
                found = rclone.install()
        except SuspendNotSupported:
            self.status()
            await self.app.push_screen_wait(
                CommandModal(
                    "Install rclone by hand",
                    shlex.join(command),
                    note="This screen cannot hand the terminal over, so run this in one "
                    "yourself, and then Mount again.",
                )
            )
            return False
        except rclone.InstallError as exc:
            self._complain("rclone was not installed", exc)
            return False
        self.status(f"rclone is installed at {found}")
        return True

    def _complain(self, title: str, exc: Exception) -> None:
        """An error with a reason in it: too long for the bar, so a dialog."""
        self.status(f"{title}.", error=True)
        self.draw()
        self.app.push_screen(NoticeModal(title, str(exc)))

    def act_unmount(self) -> None:
        self.unmount_share()

    @work(group="ui")
    async def unmount_share(self) -> None:
        share = self.selected
        if share is None:
            self.status("No share selected.", error=True)
            return
        try:
            mounted = await asyncio.to_thread(mounts.unmount, share["name"])
        except mounts.MountError as exc:
            self._complain(f"Could not unmount {share['name']}", exc)
            return
        self.draw()
        self.status(f"Unmounted {mounted.path}")

    def act_copy_url(self) -> None:
        share = self.selected
        if share is None:
            self.status("No share selected.", error=True)
            return
        self.app.copy_to_clipboard(share["url"])
        self.status(f"Copied {share['url']}")

    def act_remove(self) -> None:
        self.remove_share()

    @work(group="ui")
    async def remove_share(self) -> None:
        share = self.selected
        if share is None:
            return
        if share.get("kind") == "drive":
            self.status(f"{share['name']} is your own drive on the server — it stays.", error=True)
            return
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(
                "Remove this share?",
                detail=(
                    f"[b]{share['name']}[/]\n"
                    f"It stops being served, and is unmounted here if it is mounted. "
                    + (
                        f"Its files stay on {share.get('machine')} at {share['path']}."
                        if share.get("kind") == "machine"
                        else f"Its files stay on the server at {share['path']} — "
                        f"`cloudmorrow share remove --files` is what deletes them."
                    )
                ),
                confirm_label="Remove",
            )
        )
        if not confirmed:
            return
        if mounts.lookup(share["name"]) is not None:
            try:
                await asyncio.to_thread(mounts.unmount, share["name"])
            except mounts.MountError as exc:
                self._complain(f"Could not unmount {share['name']}", exc)
                return
        try:
            await self.api.delete_share(share["name"])
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.status(f"Removed {share['name']}")
        self.reload()


VIEWS: tuple[type[Pane], ...] = (LocalBackupsPane, FilesharesPane, BrowsePane)
LANDING = FilesharesPane


class FilesPane(Pane):
    """The Files tab: its three views, and the strip that picks one."""

    TAB_LABEL = "Files"
    TAB_KEY = "f5"
    SUMMARY = "backups and shares"
    BINDINGS = [
        ("1", "show_view('local-backups')", "Local backups"),
        ("2", "show_view('fileshares')", "Fileshares"),
        ("3", "show_view('browse')", "Browse"),
    ]

    def content(self) -> ComposeResult:
        yield Tabs(
            *(Tab(view.TAB_LABEL, id=self._tab_id(view)) for view in VIEWS),
            active=self._tab_id(LANDING),
            id="files-nav",
        )
        with ContentSwitcher(id="files-views", initial=self._view_id(LANDING)):
            for view in VIEWS:
                yield view(id=self._view_id(view))

    @staticmethod
    def _key(view: type[Pane]) -> str:
        return view.TAB_LABEL.lower().replace(" ", "-")

    @classmethod
    def _tab_id(cls, view: type[Pane]) -> str:
        return f"files-tab-{cls._key(view)}"

    @classmethod
    def _view_id(cls, view: type[Pane]) -> str:
        return f"files-view-{cls._key(view)}"

    @property
    def active_view(self) -> Pane | None:
        switcher = self.query_one("#files-views", ContentSwitcher)
        current = switcher.current
        return switcher.query_one(f"#{current}", Pane) if current else None

    def action_show_view(self, key: str) -> None:
        self.query_one("#files-nav", Tabs).active = f"files-tab-{key}"

    def browse(self, share: str) -> None:
        """Open *share* in the Browse view, and bring that view to the front.

        Bringing it to the front lists it; only when it is in front already
        is there nothing else to do the listing."""
        view = self.query_one(BrowsePane)
        if self.active_view is view:
            view.open_share(share)
        else:
            view.go_to(share)
            self.action_show_view("browse")

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        """Handled here so it never reaches the screen's own tab strip."""
        event.stop()
        if event.tab is None or not (event.tab.id or "").startswith("files-tab-"):
            return
        self.query_one("#files-views", ContentSwitcher).current = (
            f"files-view-{event.tab.id[len('files-tab-') :]}"
        )
        self.status()
        view = self.active_view
        if view is not None:
            view.reload()
        self.focus_view()

    def card_status(self) -> tuple[str, str] | None:
        shares = self.query_one(FilesharesPane).shares
        if not shares:
            return None
        count = len(shares)
        return "ok", f"{count} share{'' if count == 1 else 's'}"

    def on_show(self) -> None:
        self.reload()
        self.focus_view()

    def focus_view(self) -> None:
        """The keys go to the view in front: its table, unless focus is in it already."""
        view = self.active_view
        if view is None:
            return
        focused = self.screen.focused
        if focused is not None and view in focused.ancestors_with_self:
            return
        table = view.query(DataTable)
        if table:
            table.first().focus()

    def reload(self) -> None:
        view = self.active_view
        if view is not None:
            view.reload()

    def status_detail(self) -> str:
        view = self.active_view
        getter = getattr(view, "status_detail", None)
        return getter() if callable(getter) else ""
