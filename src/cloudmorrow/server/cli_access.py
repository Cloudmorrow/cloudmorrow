"""`cloudmorrow-server access` — how the cloud is reached, from the server's own shell.

    cloudmorrow-server access status
    cloudmorrow-server access link           # shows a code, waits for it, sets up
    cloudmorrow-server access link --no-wait # shows a code; the server waits
    cloudmorrow-server access unlink
    cloudmorrow-server access set-up         # try the mesh and Caddy again

What the installer runs, as the service user, and what an administrator
without a browser runs. It goes through the same `access_ways.Access` as
Administration → Access, against the same database; a running server reads
the record when it starts and every ten minutes, so the installer restarts
it afterwards (and so can you, after changing things from here: `sudo
systemctl restart cloudmorrow`).

`link` prints what to do on stdout, where the installer's terminal shows
it: *Open cloudmorrow.com/link and enter KXRT-4829*, and the page with the
code filled in. Joining the mesh needs this user to be tailscale's
operator, which the installer arranges as root before it links.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from cloudmorrow.console import console as make_console
from cloudmorrow.server.access_ways import Access, AccessError
from cloudmorrow.server.config import ServerConfig, load_config
from cloudmorrow.server.sealed import use_key
from cloudmorrow.server.settings import SettingsStore

app = typer.Typer(help="How this cloud is reached: the home network, and the mesh once linked.", no_args_is_help=True)
console = make_console(stderr=True, highlight=False)
out = make_console(highlight=False)

ConfigOption = Annotated[
    Path | None,
    typer.Option("--config", "-c", help="Path to server.toml (default: search standard paths)."),
]


def _access(path: Path | None) -> Access:
    config: ServerConfig = load_config(path)
    config.ensure_dirs()
    use_key(config.db_path, config.secrets_key_path)
    settings = SettingsStore(config.db_path)
    access = Access(config, lambda: settings.name(config.name))
    # As the server does at start: the address follows a linked name.
    access.follow(access.cloud())
    return access


def _fail(exc: Exception) -> None:
    console.print(f"[red]{exc}[/]")
    raise typer.Exit(code=1)


def _restart_note() -> None:
    console.print("[dim]restart the server for it to take effect: sudo systemctl restart cloudmorrow[/]")


@app.command("status")
def status(
    config_path: ConfigOption = None,
    as_json: Annotated[bool, typer.Option("--json", help="The whole status, as JSON.")] = False,
) -> None:
    """How the cloud is reached, and how each part of it stands."""
    data = _access(config_path).status(admin=True)
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return
    out.print(f"[b]address[/]       {data['address'] or '(not set)'}")
    out.print(f"[b]home network[/]  {'on' if data['lan']['on'] else 'off'}")
    if not data["linked"]:
        link = data.get("link")
        if link:
            out.print(f"[b]linking[/]       waiting for {link['code']} at {link['place']}")
        else:
            out.print("[b]linked[/]        no — link it with: cloudmorrow-server access link")
        return
    mesh = data["mesh"]
    out.print(f"[b]linked[/]        as {data['host']}  [dim](through {data['control']})[/]")
    line = "on" if mesh["on"] else "not yet"
    if mesh["on"]:
        line += f" — the box is {mesh['address'] or '?'}, tailscale {mesh['box']['state'] or 'not answering'}"
    out.print(f"[b]mesh[/]          {line}")
    if data["setup_error"]:
        out.print(f"[yellow]not set up:[/] {data['setup_error']}")
    if data["caddy"]["error"]:
        out.print(f"[yellow]caddy:[/] {data['caddy']['error']}")


def say_code(link: dict) -> None:
    """The television's sentence, and the link with the code in it."""
    out.print(f"\n  Open [b]{link['place']}[/] and enter [b]{link['code']}[/]")
    out.print(f"  [dim]or open {link['link']}[/]\n")


@app.command("link")
def link(
    wait: Annotated[bool, typer.Option("--wait/--no-wait", help="Wait for the code to be entered.")] = True,
    config_path: ConfigOption = None,
) -> None:
    """Link this cloud to a cloudmorrow.com account: a code to enter on the website."""
    access = _access(config_path)
    cloud = access.cloud()
    if cloud is not None:
        out.print(f"already linked, as {cloud.host}")
        if not cloud.set_up:
            _set_up(access)
        return
    try:
        shown = access.link()
    except AccessError as exc:
        _fail(exc)
    say_code(shown)
    if not wait:
        console.print("[dim]the server waits for it, and sets itself up once it is entered[/]")
        return
    console.print("[dim]waiting for the code to be entered (Ctrl-C to stop waiting; the code stays good)…[/]")
    try:
        state = access.wait_for_link()
    except KeyboardInterrupt:
        console.print("\n[dim]stopped waiting; the server picks the code up when it starts[/]")
        raise typer.Exit(code=1) from None
    if state != "linked":
        _fail(AccessError("the code ran out before it was entered; run this again for a new one"))
    cloud = access.cloud()
    if cloud is None:  # pragma: no cover - linked means a record
        _fail(AccessError("linked, but the record is gone"))
    if cloud.set_up:
        out.print(f"[green]linked[/] as [b]{cloud.host}[/], and on its mesh")
    else:
        out.print(f"[green]linked[/] as [b]{cloud.host}[/]")
        console.print(f"[yellow]not on the mesh yet:[/] {access.setup_error or 'unknown'}")
        console.print("[dim]fix that and run: cloudmorrow-server access set-up[/]")
    if access.caddy.error:
        console.print(f"[yellow]caddy:[/] {access.caddy.error}")
    _restart_note()


def _set_up(access: Access) -> None:
    try:
        cloud = access.set_up()
    except AccessError as exc:
        _fail(exc)
    out.print(f"{cloud.host} is on its mesh at {cloud.mesh_address or '?'}")
    if access.caddy.error:
        console.print(f"[yellow]caddy:[/] {access.caddy.error}")


@app.command("set-up")
def set_up(config_path: ConfigOption = None) -> None:
    """Put a linked cloud on its mesh and give Caddy its site, again."""
    _set_up(_access(config_path))
    _restart_note()


@app.command("unlink")
def unlink(
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask.")] = False,
    config_path: ConfigOption = None,
) -> None:
    """Give the name back. The mesh and every device on it go; the home network stays."""
    access = _access(config_path)
    cloud = access.cloud()
    if cloud is None:
        if access.pending() is not None:
            access.cancel_link()
            out.print("stopped waiting for the link code")
            return
        out.print("this cloud is not linked")
        return
    if not yes and not typer.confirm(f"Unlink {cloud.host}? Its devices lose their way in."):
        raise typer.Exit(code=1)
    try:
        access.unlink()
    except AccessError as exc:
        _fail(exc)
    out.print(f"{cloud.host} is unlinked; the cloud is reached on the home network")
    _restart_note()
