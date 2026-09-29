"""`cloudmorrow access` — how your cloud is reached, and this computer on its mesh.

    cm access status                 the three ways in, and how each stands
    cm access public larsens         claim larsens.<zone> and turn public on (admin)
    cm access public off             public access off (admin)
    cm access private on|off         the mesh, for enrolled devices (admin)
    cm access release                give the name back (admin)
    cm access pair                   a code for a phone's Tailscale app
    cm access key                    a one-time key for a computer
    cm access join                   put this computer on the mesh
    cm access devices                your enrolled devices (--everyone: all, admin)

The server decides who may do what: an administrator changes the ways in,
and everybody can enroll their own devices while private access is on.
"""

from __future__ import annotations

import json
from typing import Annotated

import typer

from cloudmorrow.cli.common import client, console, fail, run
from cloudmorrow.client import meshjoin

app = typer.Typer(help="How your cloud is reached: home network, public, private.", no_args_is_help=True)


async def _call(what):
    _, api = client()
    try:
        return await what(api)
    finally:
        await api.aclose()


def _show(status: dict) -> None:
    lan = status.get("lan", {})
    public = status.get("public", {})
    private = status.get("private", {})
    console.print(f"[b]address[/]       {status.get('address') or '(none set)'}")
    home = lan.get("hostname") or "not announced"
    console.print(f"[b]home network[/]  {'on' if lan.get('on') else 'off'}  [dim]{home}[/]")
    line = "on" if public.get("on") else "off"
    tunnel = public.get("tunnel")
    if public.get("on") and tunnel:
        line += f"  [dim]tunnel {tunnel.get('state')}"
        if tunnel.get("connected_since"):
            line += f" since {tunnel['connected_since']}, {tunnel.get('reconnects', 0)} reconnects"
        if tunnel.get("error"):
            line += f" — {tunnel['error']}"
        line += "[/]"
    console.print(f"[b]public[/]        {line}  [dim]{status.get('host') or ''}[/]")
    line = "on" if private.get("on") else "off"
    if private.get("on"):
        where = private.get("address") or ""
        line += f"  [dim]login server {private.get('login_server', '')}{', box at ' + where if where else ''}[/]"
    if private.get("error"):
        line += f"  [yellow]{private['error']}[/]"
    console.print(f"[b]private[/]       {line}")
    if status.get("enrolled") is False:
        console.print(
            f"[dim]no name yet — an administrator claims one: "
            f"cm access public {status.get('suggested_name', 'my-cloud')}[/]"
        )
    caddy = status.get("caddy") or {}
    if caddy.get("error"):
        console.print(f"[yellow]caddy:[/] {caddy['error']}")


@app.command("status")
def status(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """The three ways in, and how each stands."""
    data = run(_call(lambda api: api.access()))
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return
    _show(data)


@app.command("public")
def public(
    name: Annotated[str, typer.Argument(help="A name to claim (larsens), or on, or off.")],
) -> None:
    """Claim a name and turn public access on; `off` turns it off. Administrators only."""

    async def act(api):
        if name.lower() in ("off", "on"):
            return await api.set_public(name.lower() == "on")
        current = await api.access()
        return await api.claim_name(
            name, public=True, private=bool(current.get("private", {}).get("on"))
        )

    data = run(_call(act))
    if data.get("public", {}).get("on"):
        console.print(f"[green]public[/]: {data.get('address')}")
    else:
        console.print("public access is off")


@app.command("private")
def private(switch: Annotated[str, typer.Argument(help="on or off")]) -> None:
    """Private access through the mesh, on or off. Administrators only."""
    if switch.lower() not in ("on", "off"):
        fail("on or off")
    data = run(_call(lambda api: api.set_private(switch.lower() == "on")))
    if data.get("private", {}).get("on"):
        console.print(f"[green]private[/]: the box is {data['private'].get('address') or 'on the mesh'}")
    else:
        console.print("private access is off")


@app.command("release")
def release(yes: Annotated[bool, typer.Option("--yes", help="Do not ask.")] = False) -> None:
    """Give the name back. Public and private access end. Administrators only."""
    if not yes and not typer.confirm("Give the name back? Enrolled devices are forgotten too."):
        raise typer.Exit(code=1)
    run(_call(lambda api: api.release_name()))
    console.print("the name is given back; the cloud is reached at home only")


@app.command("pair")
def pair(device: Annotated[str, typer.Option("--device", help="What you call the phone.")] = "a phone") -> None:
    """A pairing code for a phone: good once, for ten minutes."""
    data = run(_call(lambda api: api.mesh_pair(device)))
    typer.echo(data["code"])
    console.print(
        f"[dim]In the Tailscale app: Log in → change server → {data['login_server']},\n"
        f"then enter the code. It works once, until {data.get('expires_at') or 'ten minutes from now'}.[/]"
    )


@app.command("key")
def key(device: Annotated[str, typer.Option("--device", help="What you call the computer.")] = "") -> None:
    """A one-time key for a computer to join the mesh with (stdout: the key)."""
    data = run(_call(lambda api: api.mesh_key(device or meshjoin.device_name())))
    typer.echo(data["key"])
    console.print(
        f"[dim]sudo tailscale up --login-server {data['login_server']} --authkey <that key>[/]"
    )


@app.command("join")
def join(
    yes: Annotated[bool, typer.Option("--yes", help="Install Tailscale without asking.")] = False,
) -> None:
    """Put this computer on the cloud's mesh: a key, Tailscale, and `tailscale up`."""
    here = meshjoin.state()
    if here.running and here.login_server:
        status = run(_call(lambda api: api.access()))
        if here.on(status.get("private", {}).get("login_server", "")):
            console.print(f"this computer is on the mesh already, at {here.address}")
            return
    name = meshjoin.device_name()
    data = run(_call(lambda api: api.mesh_key(name)))

    def consent() -> bool:
        return yes or typer.confirm("Tailscale is not installed. Install it now from tailscale.com?")

    console.print(f"joining as [b]{name}[/] — tailscale up needs your password")
    try:
        joined = meshjoin.join(data, hostname=name, install=consent)
    except meshjoin.JoinError as exc:
        fail(str(exc))
    console.print(
        f"[green]on the mesh[/] at {joined.address or '?'}; "
        f"{data.get('hostname', '')} now goes straight to the box"
    )


@app.command("devices")
def devices(
    everyone: Annotated[bool, typer.Option("--everyone", help="Everybody's (administrators).")] = False,
) -> None:
    """Your enrolled devices."""
    rows = run(_call(lambda api: api.mesh_devices(everyone=everyone)))
    if not rows:
        console.print("[dim]no devices enrolled[/]")
        return
    for row in rows:
        online = "[green]online[/]" if row.get("online") else "[dim]offline[/]"
        typer.echo(f"{row['id']}\t{row.get('name', '')}\t{row.get('address', '')}\t{row.get('owner', '')}")
        console.print(f"[dim]  {row.get('for', '')} · {online}[/]")
