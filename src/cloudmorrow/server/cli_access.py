"""`cloudmorrow-server access` — how the cloud is reached, from the server's own shell.

    cloudmorrow-server access status
    cloudmorrow-server access claim larsens              # public
    cloudmorrow-server access claim larsens --private --no-public
    cloudmorrow-server access public on|off
    cloudmorrow-server access private on|off
    cloudmorrow-server access release
    cloudmorrow-server access mesh-key                   # for the installer

What the installer runs, as the service user, and what an administrator
without a browser runs. It goes through the same `access_ways.Access` as
Administration → Access, against the same database; a running server reads
the record when it starts, so the installer restarts it afterwards (and so
should you, after changing things from here: `sudo systemctl restart
cloudmorrow`).

`mesh-key` is the one the installer needs for private access: joining the
mesh the first time is root's job (`tailscale up … --operator=cloudmorrow`),
so it asks for the box's key here and runs tailscale itself. It prints
`<login_server> <key>` on one line and nothing else on stdout.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from cloudmorrow.console import console as make_console
from cloudmorrow.server.access_control import ControlError
from cloudmorrow.server.access_ways import BOX_LABEL, KEY_SECONDS, Access, AccessError
from cloudmorrow.server.config import ServerConfig, load_config
from cloudmorrow.server.sealed import use_key
from cloudmorrow.server.settings import SettingsStore

app = typer.Typer(help="How this cloud is reached: home network, public, private.", no_args_is_help=True)
console = make_console(stderr=True, highlight=False)

ConfigOption = Annotated[
    Path | None,
    typer.Option("--config", "-c", help="Path to server.toml (default: search standard paths)."),
]


def _access(path: Path | None) -> Access:
    config: ServerConfig = load_config(path)
    config.ensure_dirs()
    use_key(config.db_path, config.secrets_key_path)
    settings = SettingsStore(config.db_path)
    return Access(config, lambda: settings.name(config.name))


def _fail(exc: Exception) -> None:
    console.print(f"[red]{exc}[/]")
    raise typer.Exit(code=1)


def _switch(value: str) -> bool:
    if value.lower() in ("on", "true", "yes", "1"):
        return True
    if value.lower() in ("off", "false", "no", "0"):
        return False
    raise typer.BadParameter("on or off")


def _restart_note() -> None:
    console.print("[dim]restart the server for it to take effect: sudo systemctl restart cloudmorrow[/]")


@app.command("status")
def status(
    config_path: ConfigOption = None,
    as_json: Annotated[bool, typer.Option("--json", help="The whole status, as JSON.")] = False,
) -> None:
    """The three ways in, and how each stands."""
    access = _access(config_path)
    data = access.status(admin=True)
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return
    console.print(f"[b]address[/]  {data['address'] or '(not set)'}")
    lan = data["lan"]
    console.print(f"[b]home network[/]  {'on' if lan['on'] else 'off'}")
    if not data["enrolled"]:
        console.print(f"[b]public[/]  off — no name yet (try: claim {data['suggested_name']})")
        console.print("[b]private[/]  off")
        return
    console.print(f"[b]name[/]  {data['host']}  [dim](at {data['control']})[/]")
    console.print(f"[b]public[/]  {'on' if data['public']['on'] else 'off'}")
    private = data["private"]
    mesh = private["mesh"]
    line = "on" if private["on"] else "off"
    if private["on"]:
        line += f" — box at {private['address'] or '?'}, tailscale {mesh['state'] or 'not answering'}"
    console.print(f"[b]private[/]  {line}")
    if data["caddy"]["error"]:
        console.print(f"[yellow]caddy:[/] {data['caddy']['error']}")


@app.command("claim")
def claim(
    name: Annotated[str, typer.Argument(help="The name: larsens → larsens.<zone>.")],
    public: Annotated[bool, typer.Option("--public/--no-public", help="Reach it from anywhere.")] = True,
    private: Annotated[bool, typer.Option("--private/--no-private", help="Reach it from enrolled devices.")] = False,
    config_path: ConfigOption = None,
) -> None:
    """Claim a name at the control server (or move to another), and turn on the ways asked for."""
    access = _access(config_path)
    try:
        cloud = access.claim(name, public=public, private=private)
    except AccessError as exc:
        _fail(exc)
    ways = [w for w, on in (("public", cloud.public), ("private", cloud.private)) if on]
    console.print(f"[green]{cloud.host}[/] is this cloud's name" + (f" ({', '.join(ways)})" if ways else ""))
    if access.caddy.error:
        console.print(f"[yellow]caddy:[/] {access.caddy.error}")
    _restart_note()


@app.command("public")
def public(
    switch: Annotated[str, typer.Argument(help="on or off")],
    config_path: ConfigOption = None,
) -> None:
    """Turn public access on or off."""
    try:
        cloud = _access(config_path).set_public(_switch(switch))
    except AccessError as exc:
        _fail(exc)
    console.print(f"public access is {'on' if cloud.public else 'off'}")
    _restart_note()


@app.command("private")
def private(
    switch: Annotated[str, typer.Argument(help="on or off")],
    config_path: ConfigOption = None,
) -> None:
    """Turn private access on (join the mesh) or off (leave it)."""
    try:
        cloud = _access(config_path).set_private(_switch(switch))
    except AccessError as exc:
        _fail(exc)
    if cloud.private:
        console.print(f"private access is on; the box is {cloud.mesh_address} on the mesh")
    else:
        console.print("private access is off")
    _restart_note()


@app.command("release")
def release(
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask.")] = False,
    config_path: ConfigOption = None,
) -> None:
    """Give the name back. Public and private access end; enrolled devices are forgotten."""
    access = _access(config_path)
    cloud = access.cloud()
    if cloud is None:
        console.print("this cloud has no name")
        return
    if not yes and not typer.confirm(f"Give {cloud.host} back?"):
        raise typer.Exit(code=1)
    try:
        access.release()
    except AccessError as exc:
        _fail(exc)
    console.print(f"{cloud.host} is given back")
    _restart_note()


@app.command("mesh-key")
def mesh_key(
    label: Annotated[str, typer.Option("--for", help="What the key is for.")] = BOX_LABEL,
    config_path: ConfigOption = None,
) -> None:
    """A one-time key to join the mesh with: `<login_server> <key>` on stdout."""
    access = _access(config_path)
    cloud = access.cloud()
    if cloud is None:
        _fail(AccessError("this cloud has no name yet: claim one first"))
    try:
        with access.control(cloud) as control:
            answer = control.mesh_key(label, expires_in=KEY_SECONDS)
    except ControlError as exc:
        _fail(exc)
    typer.echo(f"{answer.get('login_server') or cloud.login_server} {answer['key']}")
