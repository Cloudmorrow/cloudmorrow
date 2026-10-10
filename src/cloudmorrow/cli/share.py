"""`cloudmorrow share` — fileshares on the server, shared with people, mounted here.

A share is a folder on the server with a name, served over WebDAV at
`/dav/<name>/`. Anybody makes one; it is the folder of that name in the
Shares folder there, and it is theirs to share with people and circles.
An administrator may also share with everybody, and put a share on a
directory elsewhere on the server:

    cloudmorrow share add family --with ann --with circle:kids
    cloudmorrow share add library --with everyone --read       # administrators
    cloudmorrow share add media --path /srv/media               # administrators
    cloudmorrow share with family sam --read
    cloudmorrow share unshare family circle:kids
    cloudmorrow share mount family         # ~/Fileshares/family, or /Volumes/family on a Mac
    cloudmorrow share unmount family

The mount signs in as you, with the token `cloudmorrow login` stored, so it
lasts as long as your session does and no password is written down for it.
"""

from __future__ import annotations

import asyncio
import shlex
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from cloudmorrow.cli.common import client, console, emit, fail, out, run
from cloudmorrow.client import mounts, rclone
from cloudmorrow.client.config import StoredCredentials
from cloudmorrow.client.members import format_members, parse_one, spec

app = typer.Typer(help="Fileshares on the server: make them, share them, mount them here.", no_args_is_help=True)

NameArgument = Annotated[str, typer.Argument(help="The share's name.")]
WhoArgument = Annotated[
    str,
    typer.Argument(help="A username, circle:NAME for a circle, or everyone (administrators)."),
]
ReadOption = Annotated[bool, typer.Option("--read", help="To read what is in it, not to change it.")]


def _mounted_at(name: str) -> str:
    mounted = mounts.lookup(name)
    if mounted is None:
        return ""
    return str(mounted.path) if mounted.active else f"{mounted.path} (gone)"


def _whose(share: dict) -> str:
    """Yours, or whose — and to read, when that is all you may do."""
    if share.get("kind") == "drive":
        return "yours (My Files)"
    if share.get("can_manage"):
        return "yours"
    owner = share.get("owner") or "?"
    return f"{owner}'s" + (", to read" if share.get("access") == "read" else "")


def _with(share: dict) -> str:
    if share.get("kind") == "drive":
        return ""
    return format_members(share.get("members") or []) or "—"


def _warn(share: dict) -> None:
    for warning in share.get("warnings") or []:
        console.print(f"[yellow]warning:[/] {warning}")


@app.command("list")
def list_shares(
    plain: Annotated[bool, typer.Option("--plain", help="One name per line, for scripts.")] = False,
) -> None:
    """List your shares and the ones shared with you, and where each is mounted here."""

    async def _list() -> None:
        _config, api = client()
        async with api:
            shares = await api.shares()
        if plain:
            emit("".join(f"{share['name']}\n" for share in shares))
            return
        table = Table(title="fileshares", title_style="bold cyan")
        table.add_column("name")
        table.add_column("whose")
        table.add_column("shared with", overflow="fold")
        table.add_column("mounted here", style="green")
        table.add_column("about", style="dim", overflow="fold")
        for share in shares:
            whose = _whose(share)
            if share.get("warnings"):
                whose += " [yellow](!)[/]"
            table.add_row(
                share["name"],
                whose,
                _with(share),
                _mounted_at(share["name"]) or "—",
                share.get("description") or "",
            )
        out.print(table)
        if len(shares) == 1:
            console.print("[dim]No shares yet — `cloudmorrow share add NAME --with USER` makes one.[/]")

    run(_list())


@app.command("show")
def show(name: NameArgument) -> None:
    """One share: whose it is, who has it, its URL, and whether it is mounted here."""

    async def _show() -> None:
        _config, api = client()
        async with api:
            share = await api.get_share(name)
        console.print(f"[b]{share['name']}[/]  {share.get('description') or ''}")
        console.print(f"[dim]whose:[/]       {_whose(share)}")
        if share.get("kind") != "drive":
            console.print("[dim]shared with:[/]")
            members = share.get("members") or []
            for found in members:
                console.print(f"  {spec(found):<24} {found['access']:<6} [dim]{found.get('label') or ''}[/]")
            if not members:
                console.print("  [dim]nobody yet[/]")
        console.print(f"[dim]url:[/]         {share['url']}")
        if share.get("path"):
            console.print(f"[dim]on server:[/]   {share['path']}")
        console.print(f"[dim]mounted at:[/]  {_mounted_at(share['name']) or 'not on this machine'}")
        _warn(share)

    run(_show())


@app.command("add")
def add(
    name: NameArgument,
    with_: Annotated[
        list[str] | None,
        typer.Option(
            "--with",
            "-w",
            help="Who to share it with: a username, circle:NAME, or everyone (administrators). Again for more.",
            show_default=False,
        ),
    ] = None,
    read: ReadOption = False,
    path: Annotated[
        str | None,
        typer.Option(
            "--path",
            help="Administrators: a directory elsewhere on the server to share, as the server sees it. "
            "Without it, the share is the folder of its name in the Shares folder there.",
            show_default=False,
        ),
    ] = None,
    description: Annotated[str, typer.Option("--description", "-d", help="What is in it.")] = "",
) -> None:
    """Make a share on the server, yours, and share it with whoever you name."""

    async def _add() -> None:
        _config, api = client()
        async with api:
            share = await api.create_share(
                name,
                path=path,
                description=description,
                members=[parse_one(each, read=read) for each in with_ or []],
            )
        console.print(f"[green]Created[/] [b]{share['name']}[/] — at {share['path']}")
        if share.get("members"):
            console.print(f"[dim]shared with {_with(share)}[/]")
        _warn(share)
        console.print(f"[dim]mount it with `cloudmorrow share mount {share['name']}`[/]")

    run(_add())


@app.command("with")
def share_with(name: NameArgument, who: WhoArgument, read: ReadOption = False) -> None:
    """Share it with somebody, a circle or everybody — or change what they may do."""

    async def _with_one() -> None:
        _config, api = client()
        wanted = parse_one(who, read=read)
        async with api:
            share = await api.share_with(name, wanted["kind"], wanted["who"], wanted["access"])
        console.print(f"[green]Shared[/] {share['name']} with {who} ({wanted['access']})")

    run(_with_one())


@app.command("unshare")
def unshare(name: NameArgument, who: WhoArgument) -> None:
    """Stop sharing it with somebody, a circle or everybody."""

    async def _unshare() -> None:
        _config, api = client()
        wanted = parse_one(who)
        async with api:
            await api.unshare(name, wanted["kind"], wanted["who"])
        console.print(f"[green]Stopped sharing[/] {name} with {who}")

    run(_unshare())


@app.command("leave")
def leave(name: NameArgument) -> None:
    """Take yourself off a share somebody shared with you by name."""

    async def _leave() -> None:
        _config, api = client()
        credentials = StoredCredentials.load()
        if credentials is None:
            fail("not signed in — `cloudmorrow login` first")
        async with api:
            await api.unshare(name, "user", credentials.username)
        console.print(f"[green]Left[/] {name}")

    run(_leave())


@app.command("move")
def move(
    name: NameArgument,
    path: Annotated[
        str | None,
        typer.Argument(help="The directory on the server, as the server sees it.", show_default=False),
    ] = None,
    back: Annotated[bool, typer.Option("--back", help="Put it back in its own folder in the Shares folder.")] = False,
) -> None:
    """Administrators: point a share at another directory on the server. Files are not moved."""
    if bool(path) == back:
        fail("give the directory to point it at, or --back for its own folder in Shares")

    async def _move() -> None:
        _config, api = client()
        async with api:
            share = await api.change_share(name, path="" if back else path)
        console.print(f"[green]Moved[/] {share['name']} — at {share['path']}")
        _warn(share)

    run(_move())


@app.command("remove")
def remove(
    name: NameArgument,
    files: Annotated[
        bool,
        typer.Option(
            "--files",
            help="Delete its folder in the Shares folder too. "
            "A directory elsewhere on the server is never deleted from here.",
        ),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation.")] = False,
) -> None:
    """Remove a share you made, for everybody it was shared with. Unmounts it here first."""

    async def _remove() -> None:
        _config, api = client()
        async with api:
            share = await api.get_share(name)
            if not yes:
                what = (
                    "and delete its files on the server"
                    if files and share["managed"]
                    else "— its files stay where they are"
                )
                shared = f", for {_with(share)} too" if share.get("members") else ""
                typer.confirm(f"Remove share {share['name']} {what}{shared}?", abort=True)
            mounted = mounts.lookup(share["name"])
            if mounted is not None:
                try:
                    mounts.unmount(share["name"])
                    console.print(f"[dim]unmounted {mounted.path}[/]")
                except mounts.MountError as exc:
                    console.print(f"[yellow]{exc}[/]")
            await api.delete_share(share["name"], remove_files=files)
        console.print(f"[green]Removed[/] {share['name']}")

    run(_remove())


@app.command("mount")
def mount(
    name: NameArgument,
    path: Annotated[
        Path | None,
        typer.Argument(
            help="Where to mount it. Defaults to ~/Fileshares/NAME; a Mac always uses /Volumes.",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Mount a share on this machine, signed in as you."""

    async def _mount() -> None:
        _config, api = client()
        async with api:
            credentials = StoredCredentials.load()
            if credentials is None or not api.token:
                fail("not signed in — `cloudmorrow login` first")
            share = await api.get_share(name)
        if mounts.platform() != mounts.MACOS and not rclone.installed():
            _install_rclone()
        try:
            mounted = await asyncio.to_thread(
                mounts.mount_share,
                share,
                credentials.username,
                credentials.access_token,
                path=path,
            )
        except mounts.MountError as exc:
            fail(str(exc))
        console.print(f"[green]Mounted[/] [b]{share['name']}[/] at {mounted.path}")
        emit(f"{mounted.path}\n")

    run(_mount())


def _install_rclone() -> None:
    """rclone is missing: offer to install it, when there is someone to ask.

    In a terminal the question is put and the package manager runs right
    here, sudo prompt and all. In a script there is nobody to answer, so the
    message says the command and the mount does not happen.
    """
    command = rclone.install_command()
    if command is None or not sys.stdin.isatty():
        fail(rclone.hint())
    console.print(f"[yellow]{rclone.MISSING}[/]")
    if not typer.confirm(f"Install it now with `{shlex.join(command)}`?", default=True):
        fail(rclone.hint())
    try:
        found = rclone.install()
    except rclone.InstallError as exc:
        fail(str(exc))
    console.print(f"[green]Installed[/] rclone at {found}")


@app.command("unmount")
def unmount(name: NameArgument) -> None:
    """Unmount a share this machine mounted."""
    try:
        mounted = mounts.unmount(name)
    except mounts.MountError as exc:
        fail(str(exc))
    console.print(f"[green]Unmounted[/] {mounted.path}")
