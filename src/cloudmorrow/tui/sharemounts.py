"""Shares on this machine, in the terminal: mounted here or not, and the buttons for it.

A share is foundation — the core keeps them, serves them over WebDAV, and
mounts them with rclone or Finder through `cm share mount` (client/mounts.py).
What is on screen is a Quill's: the Files Quill draws the shares with the
kit's grid. This is the part in between, and it knows the `share` datamodel
and nothing of any Quill: it hands the grid an extension for any grid whose
groups are shares, which adds

- a MOUNTED HERE column, lit while this machine has the share mounted;
- New share (^n) — a folder on the server, yours, shared with whoever you
  name; an administrator may point it at another directory there;
- Share with (s), Mount (m), Unmount (u), Copy URL (c) and Remove (d), on
  the share the cursor is on.

The grid calls these with itself and the share record; they talk to the
same `/api/shares` routes and the same mount table as `cm share` does, so
the terminal, the desktop app and the command line agree on what is mounted.
"""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

from textual.app import SuspendNotSupported

from cloudmorrow.client import mounts, rclone
from cloudmorrow.client.api import ApiError
from cloudmorrow.client.members import changes, format_members, parse
from cloudmorrow.tui.panes.kit_grid import GridPane, GroupExtension, register_group_extension
from cloudmorrow.tui.screens.install import InstallRcloneModal
from cloudmorrow.tui.screens.modals import ConfirmModal, PromptModal
from cloudmorrow.tui.screens.share_modals import CommandModal, MembersModal, NoticeModal, ShareModal
from cloudmorrow.tui.theme import GOOD, MUTED, WARN
from cloudmorrow.tui.widgets.toolbar import Action

ACTIONS = (
    Action(
        "new_group",
        "New share",
        "^n",
        variant="primary",
        hint="A folder on the server, shared with whoever you name",
    ),
    Action("share_with", "Share with", "s", hint="Who has the selected share"),
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
    lines = []
    if fields.get("kind") == "server":
        whose = "yours" if fields.get("can_manage") else f"{fields.get('owner') or '?'}'s"
        if fields.get("access") == "read":
            whose += ", to read"
        lines.append(f"[{MUTED}]{whose} — shared with {fields.get('shared_with') or 'nobody yet'}[/]")
    lines.append(f"[{MUTED}]{fields.get('url') or fields.get('path', '')}[/]")
    return "\n".join(lines)


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
    elif action == "share_with":
        await edit_members(pane, share)
    elif action == "copy_url":
        await copy_url(pane, share)
    elif action == "remove":
        await remove_share(pane, share)


def _complain(pane: GridPane, title: str, exc: Exception) -> None:
    """An error with a reason in it: too long for the bar, so a dialog."""
    pane.status(f"{title}.", error=True)
    pane.draw()
    pane.app.push_screen(NoticeModal(title, str(exc)))


async def _candidates(pane: GridPane) -> dict:
    """Who there is to share with; nice to have, so nothing when it cannot be had."""
    try:
        return await pane.api.share_candidates()
    except ApiError:
        return {}


def _warned(pane: GridPane, share: dict, done: str) -> None:
    """Said on the bar — or, when the server found something wrong with the
    share's directory, in a dialog, because it has to be read and fixed."""
    warnings = share.get("warnings") or []
    if warnings:
        pane.status(f"{done} — with something to fix.", error=True)
        pane.app.push_screen(NoticeModal(f"{share['name']}: check its folder", "\n\n".join(warnings)))
    else:
        pane.status(done)


async def new_share(pane: GridPane) -> None:
    api = pane.api
    try:
        me = await api.me()
    except ApiError as exc:
        pane.status(str(exc), error=True)
        return
    admin = bool(me.get("is_admin"))
    folders: dict | None = None
    if admin:
        # What a share of a given name would pick up. Nice to know,
        # not needed: without it the dialog still works.
        try:
            folders = await api.share_folders()
        except ApiError:
            folders = None
    candidates = await _candidates(pane)
    fields = await pane.app.push_screen_wait(ShareModal(admin=admin, candidates=candidates, folders=folders))
    if fields is None:
        return
    try:
        share = await api.create_share(
            fields["name"],
            path=fields["path"] or None,
            description=fields["description"],
            members=fields["members"],
        )
    except ApiError as exc:
        # The reason is the server's — "a share with that name exists", or
        # what is wrong with the path — and has to be read.
        _complain(pane, f"Could not create {fields['name']}", exc)
        return
    _warned(pane, share, f"Created {share['name']} — Mount puts it on this machine")
    pane.reload()


async def edit_members(pane: GridPane, share: dict) -> None:
    """Who has it, as a line to edit; what changed is asked for, one by one."""
    name = share["id"]
    fields = _fields(share)
    if fields.get("kind") == "drive":
        pane.status(f"{fields.get('label') or name} is your own drive — it is not shared.", error=True)
        return
    if not fields.get("can_manage"):
        pane.status(f"{name} is {fields.get('owner') or 'somebody else'}'s; only they decide who has it.", error=True)
        return
    try:
        current = (await pane.api.get_share(name)).get("members") or []
    except ApiError as exc:
        pane.status(str(exc), error=True)
        return
    line = await pane.app.push_screen_wait(MembersModal(name, format_members(current), await _candidates(pane)))
    if line is None:
        return
    put, gone = changes(current, parse(line))
    try:
        for member in gone:
            await pane.api.unshare(name, member["kind"], member["who"])
        for member in put:
            await pane.api.share_with(name, member["kind"], member["who"], member["access"])
    except ApiError as exc:
        _complain(pane, f"Could not change who has {name}", exc)
        pane.reload()
        return
    pane.status(f"{name} is shared with {format_members(parse(line)) or 'nobody but you'}")
    pane.reload()


async def mount_share(pane: GridPane, share: dict) -> None:
    name = share["id"]
    token = getattr(pane.api, "token", None)
    username = getattr(pane.app, "username", "")
    if not token or not username:
        pane.status("Not signed in.", error=True)
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
                    "[dim]An empty directory; it is made if it is not there. rclone does the mounting on Linux.[/]"
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
                note="This screen cannot hand the terminal over, so run this in one yourself, and then Mount again.",
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
    pane.app.copy_to_clipboard(url)
    pane.status(f"Copied {url}")


async def remove_share(pane: GridPane, share: dict) -> None:
    name = share["id"]
    fields = _fields(share)
    if fields.get("kind") == "drive":
        pane.status(f"{fields.get('label') or name} is your own drive on the server — it stays.", error=True)
        return
    if not fields.get("can_manage"):
        pane.status(f"{name} is {fields.get('owner') or 'somebody else'}'s; only they remove it.", error=True)
        return
    confirmed = await pane.app.push_screen_wait(
        ConfirmModal(
            "Remove this share?",
            detail=(
                f"[b]{name}[/]\n"
                + (f"Whoever has it loses it too: {fields['shared_with']}.\n" if fields.get("shared_with") else "")
                + "It stops being served, and is unmounted here if it is mounted. "
                + f"Its files stay on the server at {fields.get('path')} — "
                + "`cloudmorrow share remove --files` is what deletes them."
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
    keys={"share_with": "s", "mount": "m", "unmount": "u", "copy_url": "c", "remove": "d"},
)
register_group_extension(EXTENSION)
