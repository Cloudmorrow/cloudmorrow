"""`cloudmorrow share` — fileshares, mounted here.

A share is a directory with a name, served over WebDAV at `/dav/<name>/`.
It is a directory on the machine you are standing on, served by the agent
here while it runs — you share what is in front of you, never a path on some
other machine typed from memory. An admin may put one on the server instead:

    cloudmorrow share add music --path ~/Music       # this machine
    cloudmorrow share add media --server             # the server (admins)
    cloudmorrow share mount music         # ~/Fileshares/music, or /Volumes/music on a Mac
    cloudmorrow share unmount music

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

from cloudmorrow.agent.setup import machine_name
from cloudmorrow.cli.common import client, console, emit, fail, out, run
from cloudmorrow.client import mounts, rclone, sharing
from cloudmorrow.client.api import ApiError
from cloudmorrow.client.config import StoredCredentials

app = typer.Typer(
    help="Fileshares: on the server or on your machines, mounted here.", no_args_is_help=True
)

NameArgument = Annotated[str, typer.Argument(help="The share's name.")]


def _mounted_at(name: str) -> str:
    mounted = mounts.lookup(name)
    if mounted is None:
        return ""
    return str(mounted.path) if mounted.active else f"{mounted.path} (gone)"


def _where(share: dict) -> str:
    """Server, or which machine — and whether that machine is serving right now."""
    if share.get("kind") == "drive":
        return "server (yours)"
    if share.get("kind") != "machine":
        return "server"
    machine = share.get("machine") or "?"
    return f"{machine}" if share.get("online") else f"{machine} (offline)"


@app.command("list")
def list_shares(
    plain: Annotated[bool, typer.Option("--plain", help="One name per line, for scripts.")] = False,
) -> None:
    """List your shares, where each lives, and where each is mounted on this machine."""

    async def _list() -> None:
        _config, api = client()
        try:
            shares = await api.shares()
        finally:
            await api.aclose()
        if plain:
            emit("".join(f"{share['name']}\n" for share in shares))
            return
        if not shares:
            console.print(
                "[dim]No shares yet — `cloudmorrow share add NAME --path DIR` shares a "
                "directory on this machine.[/]"
            )
            return
        table = Table(title="fileshares", title_style="bold cyan")
        table.add_column("name")
        table.add_column("where")
        table.add_column("mounted here", style="green")
        table.add_column("directory", style="dim", overflow="fold")
        table.add_column("about", style="dim", overflow="fold")
        for share in shares:
            where = _where(share)
            table.add_row(
                share["name"],
                f"[yellow]{where}[/]" if "offline" in where else where,
                _mounted_at(share["name"]) or "—",
                share["path"],
                share.get("description") or "",
            )
        out.print(table)

    run(_list())


@app.command("show")
def show(name: NameArgument) -> None:
    """One share: its URL, its directory, and whether it is mounted here."""

    async def _show() -> None:
        _config, api = client()
        try:
            share = await api.get_share(name)
        finally:
            await api.aclose()
        console.print(f"[b]{share['name']}[/]  {share.get('description') or ''}")
        console.print(f"[dim]where:[/]      {_where(share)}")
        url = share["url"] or "— (the machine has not said where it serves yet)"
        console.print(f"[dim]url:[/]        {url}")
        if share.get("kind") == "machine":
            console.print(
                f"[dim]directory:[/]  {share['path']}  [dim](on {share.get('machine')})[/]"
            )
        else:
            console.print(f"[dim]server:[/]     {share['path']}")
        console.print(f"[dim]mounted at:[/] {_mounted_at(share['name']) or 'not on this machine'}")

    run(_show())


@app.command("add")
def add(
    name: NameArgument,
    path: Annotated[
        str | None,
        typer.Option(
            "--path",
            help="The directory to share, on this machine.",
            show_default=False,
        ),
    ] = None,
    server: Annotated[
        bool,
        typer.Option(
            "--server",
            help="Put the share on the server instead: the folder of that name in the "
            "Shares folder there, made if it is not there. Admins only.",
        ),
    ] = False,
    description: Annotated[str, typer.Option("--description", "-d", help="What is in it.")] = "",
) -> None:
    """Share a directory on this machine — or, as an admin, one on the server."""

    async def _add() -> None:
        _config, api = client()
        if server:
            if path:
                await api.aclose()
                fail(
                    "a server share is the folder of that name in the Shares folder on "
                    "the server — there is no path to give\n"
                    "(--path is for a share on this machine)"
                )
            kind, machine, directory = "server", None, None
        else:
            if not path:
                await api.aclose()
                fail(
                    "a share is a directory on this machine: --path DIR\n"
                    "(an admin puts one on the server with --server)"
                )
            # The machine is the one you are on — the only one whose paths
            # you can see, where `~` means something, and where whether it
            # can be shared at all is known before the server is asked.
            complaint = sharing.problem(path)
            if complaint:
                await api.aclose()
                fail(complaint)
            kind, machine = "machine", machine_name()
            directory = str(sharing.resolve(path))
        try:
            share = await api.create_share(
                name, kind=kind, path=directory, machine=machine, description=description
            )
        except ApiError as exc:
            if kind == "machine" and exc.status_code == 404:
                fail(
                    f"this machine ({machine}) has no agent, so nothing here can serve a "
                    "share — `cloudmorrow login` enrols it"
                )
            raise
        finally:
            await api.aclose()
        console.print(f"[green]Created[/] [b]{share['name']}[/] — {_where(share)}")
        if share.get("kind") == "machine" and not share.get("online"):
            console.print(
                f"[dim]{share.get('machine')} starts serving it on its agent's next heartbeat.[/]"
            )
        else:
            console.print(f"[dim]at {share['url']}[/]")
        console.print(f"[dim]mount it with `cloudmorrow share mount {share['name']}`[/]")

    run(_add())


@app.command("remove")
def remove(
    name: NameArgument,
    files: Annotated[
        bool,
        typer.Option(
            "--files",
            help="Delete its folder on the server too. A directory on a machine is never "
            "deleted from here.",
        ),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation.")] = False,
) -> None:
    """Stop serving a share. Unmounts it here first, if it is mounted."""

    async def _remove() -> None:
        _config, api = client()
        try:
            share = await api.get_share(name)
            if not yes:
                what = (
                    "and delete its files on the server"
                    if files and share["managed"]
                    else "— its files stay where they are"
                )
                typer.confirm(f"Remove share {share['name']} {what}?", abort=True)
            mounted = mounts.lookup(share["name"])
            if mounted is not None:
                try:
                    mounts.unmount(share["name"])
                    console.print(f"[dim]unmounted {mounted.path}[/]")
                except mounts.MountError as exc:
                    console.print(f"[yellow]{exc}[/]")
            await api.delete_share(share["name"], remove_files=files)
        finally:
            await api.aclose()
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
        credentials = StoredCredentials.load()
        if credentials is None or not api.token:
            await api.aclose()
            fail("not signed in — `cloudmorrow login` first")
        try:
            share = await api.get_share(name)
        finally:
            await api.aclose()
        # Said before rclone is offered: installing it would not help.
        why = mounts.refusal(share)
        if why:
            fail(why)
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
