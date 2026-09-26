"""Shares on this machine, in the terminal: mounted here or not, and the buttons for it.

A share is foundation — the core keeps them, serves them over WebDAV, and
mounts them with rclone or Finder through `cm share mount` (client/mounts.py).
What is on screen is a Quill's: the Files Quill draws the shares with the
kit's grid. This is the part in between, and it knows the `share` datamodel
and nothing of any Quill: it hands the grid an extension for any grid whose
groups are shares, which adds

- a MOUNTED HERE column, lit while this machine has the share mounted;
- New share (^n) — on the server for an administrator, or a directory on
  this machine, served by its agent;
- Mount (m), Unmount (u), Copy URL (c) and Remove (d), on the share the
  cursor is on.

The grid calls these with itself and the share record; they talk to the
same `/api/shares` routes and the same mount table as `cm share` does, so
the terminal, the desktop app and the command line agree on what is mounted.
"""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

from textual.app import SuspendNotSupported

from cloudmorrow.agent.setup import machine_name
from cloudmorrow.client import mounts, rclone
from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.panes.kit_grid import GridPane, GroupExtension, register_group_extension
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

ACTIONS = (
    Action(
        "new_group",
        "New share",
        "^n",
        variant="primary",
        hint="On the server, or a directory on this machine",
    ),
    Action("mount", "Mount", "m", hint="Mount the selected share on this machine"),
    Action("unmount", "Unmount", "u", hint="Unmount it here; the share stays"),
    Action("copy_url", "Copy URL", "c", hint="Its WebDAV address, for any other client"),
    Action("remove", "Remove", "d", variant="error", hint="Stop serving it; files stay"),
)


def _fields(share: dict | None) -> dict:
    return (share or {}).get("fields") or {}


def mounted_cell(share: dict) -> tuple[str, ...]:
    mounted = mounts.lookup(share["id"])
    if mounted is None:
        return (f"[{MUTED}]—[/]",)
    if mounted.active:
        return (f"[{GOOD}]● {mounted.path}[/]",)
    # Recorded, but not there: a reboot, or an unmount by hand.
    return (f"[{WARN}]○ {mounted.path}[/]",)


def detail(share: dict) -> str:
    fields = _fields(share)
    if fields.get("url"):
        return f"[{MUTED}]{fields['url']}[/]"
    if fields.get("kind") == "machine":
        return (
            f"[{MUTED}]{fields.get('machine') or 'its machine'} has not said where it serves yet[/]"
        )
    return f"[{MUTED}]{fields.get('path', '')}[/]"


async def run(pane: GridPane, action: str, share: dict | None) -> None:
    if action == "new_group":
        await new_share(pane)
        return
    if share is None:
        pane.status("No share selected.", error=True)
        return
    if action == "mount":
        await mount_share(pane, share)
    elif action == "unmount":
        await unmount_share(pane, share)
    elif action == "copy_url":
        await copy_url(pane, share)
    elif action == "remove":
        await remove_share(pane, share)


def _complain(pane: GridPane, title: str, exc: Exception) -> None:
    """An error with a reason in it: too long for the bar, so a dialog."""
    pane.status(f"{title}.", error=True)
    pane.draw()
    pane.app.push_screen(NoticeModal(title, str(exc)))


async def new_share(pane: GridPane) -> None:
    api = pane.api
    try:
        me = await api.me()
        machines = await api.agents()
    except ApiError as exc:
        pane.status(str(exc), error=True)
        return
    here = machine_name()
    admin = bool(me.get("is_admin"))
    if not admin and not any(m.get("name") == here for m in machines):
        # A share is a directory on this machine, and only its agent can
        # serve one. Without that there is nothing to open a dialog for.
        pane.status(
            f"This machine ({here}) has no agent, so nothing here can serve a share — "
            "`cloudmorrow login` enrols it.",
            error=True,
        )
        return
    folders: dict | None = None
    if admin:
        # What a server share of a given name would pick up. Nice to know,
        # not needed: without it the dialog still works.
        try:
            folders = await api.share_folders()
        except ApiError:
            folders = None
    fields = await pane.app.push_screen_wait(
        ShareModal(machines=machines, admin=admin, this_machine=here, folders=folders)
    )
    if fields is None:
        return
    try:
        share = await api.create_share(
            fields["name"],
            kind=fields["kind"],
            path=fields["path"] or None,
            machine=fields["machine"] or None,
            description=fields["description"],
        )
    except ApiError as exc:
        # The reason is the server's — "a share with that name exists" — and
        # has to be read.
        _complain(pane, f"Could not create {fields['name']}", exc)
        return
    if share.get("kind") == "machine" and not share.get("online"):
        pane.status(
            f"Created {share['name']} — {share.get('machine')} starts serving it on its "
            f"agent's next heartbeat."
        )
    else:
        pane.status(f"Created {share['name']} — Mount puts it on this machine.")
    pane.reload()


async def mount_share(pane: GridPane, share: dict) -> None:
    name = share["id"]
    token = getattr(pane.api, "token", None)
    username = getattr(pane.app, "username", "")
    if not token or not username:
        pane.status("Not signed in.", error=True)
        return
    fields = _fields(share)
    if fields.get("kind") == "machine" and not fields.get("online"):
        pane.status(
            f"{name} is on {fields.get('machine')}, and its agent is not serving right now.",
            error=True,
        )
        return
    try:
        # Where to mount from is the server's to say, as it says to `cm share mount`.
        url = (await pane.api.get_share(name))["url"]
    except ApiError as exc:
        pane.status(str(exc), error=True)
        return
    path: Path | None = None
    if mounts.platform() != mounts.MACOS:
        if not await _ensure_rclone(pane):
            return
        answer = await pane.app.push_screen_wait(
            PromptModal(
                f"Mount {name} at",
                value=str(mounts.default_mountpoint(name)),
                detail=(
                    "[dim]An empty directory; it is made if it is not there. "
                    "rclone does the mounting on Linux.[/]"
                ),
            )
        )
        if answer is None:
            return
        path = Path(answer).expanduser()
    pane.status(f"mounting {name}…", note=True)
    try:
        mounted = await asyncio.to_thread(mounts.mount, name, url, username, token, path=path)
    except mounts.MountError as exc:
        _complain(pane, f"Could not mount {name}", exc)
        return
    pane.draw()
    pane.status(f"{name} is mounted at {mounted.path}")


async def _ensure_rclone(pane: GridPane) -> bool:
    """rclone, or the dialog that gets it: True once it is on this machine.

    The install runs with the app suspended, so the terminal is the package
    manager's and sudo can ask for a password. Where the app cannot step
    aside — textual-web has no terminal to give — the command is shown to
    run by hand instead.
    """
    if rclone.installed():
        return True
    command = rclone.install_command()
    wanted = await pane.app.push_screen_wait(InstallRcloneModal(command))
    if not wanted or command is None:
        return False
    pane.status("installing rclone…", note=True)
    try:
        with pane.app.suspend():
            found = rclone.install()
    except SuspendNotSupported:
        pane.status()
        await pane.app.push_screen_wait(
            CommandModal(
                "Install rclone by hand",
                shlex.join(command),
                note="This screen cannot hand the terminal over, so run this in one "
                "yourself, and then Mount again.",
            )
        )
        return False
    except rclone.InstallError as exc:
        _complain(pane, "rclone was not installed", exc)
        return False
    pane.status(f"rclone is installed at {found}")
    return True


async def unmount_share(pane: GridPane, share: dict) -> None:
    try:
        mounted = await asyncio.to_thread(mounts.unmount, share["id"])
    except mounts.MountError as exc:
        _complain(pane, f"Could not unmount {share['id']}", exc)
        return
    pane.draw()
    pane.status(f"Unmounted {mounted.path}")


async def copy_url(pane: GridPane, share: dict) -> None:
    try:
        url = (await pane.api.get_share(share["id"]))["url"]
    except ApiError as exc:
        pane.status(str(exc), error=True)
        return
    if not url:
        pane.status(
            f"{share['id']} has no address yet: its machine has not said where it serves.",
            error=True,
        )
        return
    pane.app.copy_to_clipboard(url)
    pane.status(f"Copied {url}")


async def remove_share(pane: GridPane, share: dict) -> None:
    name = share["id"]
    fields = _fields(share)
    if fields.get("kind") == "drive":
        pane.status(
            f"{fields.get('label') or name} is your own drive on the server — it stays.", error=True
        )
        return
    confirmed = await pane.app.push_screen_wait(
        ConfirmModal(
            "Remove this share?",
            detail=(
                f"[b]{name}[/]\n"
                f"It stops being served, and is unmounted here if it is mounted. "
                + (
                    f"Its files stay on {fields.get('machine')} at {fields.get('path')}."
                    if fields.get("kind") == "machine"
                    else f"Its files stay on the server at {fields.get('path')} — "
                    f"`cloudmorrow share remove --files` is what deletes them."
                )
            ),
            confirm_label="Remove",
        )
    )
    if not confirmed:
        return
    if mounts.lookup(name) is not None:
        try:
            await asyncio.to_thread(mounts.unmount, name)
        except mounts.MountError as exc:
            _complain(pane, f"Could not unmount {name}", exc)
            return
    try:
        await pane.api.delete_share(name)
    except ApiError as exc:
        pane.status(str(exc), error=True)
        return
    pane.status(f"Removed {name}")
    pane.reload()


EXTENSION = GroupExtension(
    applies=lambda model: model.get("id") == "share",
    columns=("MOUNTED HERE",),
    cells=mounted_cell,
    actions=ACTIONS,
    run=run,
    detail=detail,
    keys={"mount": "m", "unmount": "u", "copy_url": "c", "remove": "d"},
)
register_group_extension(EXTENSION)
