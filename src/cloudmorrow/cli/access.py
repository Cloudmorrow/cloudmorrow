"""`cloudmorrow access` — your own access, how your cloud is reached, and this computer on its mesh.

    cm access                        what you may do with each datamodel (circles)
    cm access status                 home network, linked or not, the mesh
    cm access link                   a code to enter at cloudmorrow.com/link (admin)
    cm access unlink                 give the name back; the mesh goes (admin)
    cm access invite                 an invite code for a device
    cm access join                   put this computer on the mesh (signed in, at home)
    cm access join --invite CODE --server https://larsens.cloudmorrow.tech
                                     the same with an invite, from anywhere, no sign-in
    cm access mine                   tell the cloud this computer on its mesh is yours
    cm access devices                your devices on the mesh (--everyone: all, admin)
    cm access remove ID              take one off the mesh

The server decides who may do what: an administrator links and unlinks,
and everybody signed in can invite and join their own devices once the
cloud is on its mesh.
"""

from __future__ import annotations

import json
import time
from typing import Annotated

import typer

from cloudmorrow.cli import circle
from cloudmorrow.cli.common import client, console, fail, run
from cloudmorrow.client import meshjoin
from cloudmorrow.client.config import ClientConfig, StoredCredentials

app = typer.Typer(help="Your own access, and how your cloud is reached: home network, and its mesh once linked.")


@app.callback(invoke_without_command=True)
def mine_by_default(ctx: typer.Context) -> None:
    """With nothing after it: what you may do with each datamodel, and the circles that say so."""
    if ctx.invoked_subcommand is None:
        circle.access()


async def _call(what):
    _, api = client()
    async with api:
        return await what(api)


def _show(status: dict) -> None:
    lan = status.get("lan", {})
    mesh = status.get("mesh", {})
    console.print(f"[b]address[/]       {status.get('address') or '(none set)'}")
    home = lan.get("hostname") or "not announced"
    console.print(f"[b]home network[/]  {'on' if lan.get('on') else 'off'}  [dim]{home}[/]")
    if status.get("linked"):
        console.print(f"[b]linked[/]        as {status.get('host')}")
        line = "on" if mesh.get("on") else "not yet"
        if mesh.get("on") and mesh.get("address"):
            line += f"  [dim]the box is {mesh['address']}[/]"
        console.print(f"[b]mesh[/]          {line}")
    else:
        link = status.get("link")
        if link:
            console.print(f"[b]linking[/]       open {link['place']} and enter [b]{link['code']}[/]")
        else:
            console.print("[b]linked[/]        no  [dim]an administrator links it: cm access link[/]")
    if status.get("setup_error"):
        console.print(f"[yellow]not on the mesh yet:[/] {status['setup_error']}")
    caddy = status.get("caddy") or {}
    if caddy.get("error"):
        console.print(f"[yellow]caddy:[/] {caddy['error']}")


@app.command("status")
def status(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Home network, linked or not, and the mesh."""
    data = run(_call(lambda api: api.access()))
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return
    _show(data)


@app.command("link")
def link(
    wait: Annotated[bool, typer.Option("--wait/--no-wait", help="Wait here until the code is entered.")] = True,
) -> None:
    """Link the cloud to a cloudmorrow.com account: a code to enter there. Administrators only."""
    data = run(_call(lambda api: api.start_link()))
    shown = data.get("link") or {}
    console.print(f"\n  Open [b]{shown.get('place')}[/] and enter [b]{shown.get('code')}[/]")
    console.print(f"  [dim]or open {shown.get('link')}[/]\n")
    if not wait:
        return
    console.print("[dim]waiting for the code to be entered (Ctrl-C stops waiting; the cloud keeps waiting)…[/]")
    try:
        while True:
            time.sleep(3)
            now = run(_call(lambda api: api.access()))
            if now.get("linked"):
                console.print(f"[green]linked[/] as [b]{now.get('host')}[/]")
                if not now.get("mesh", {}).get("on"):
                    console.print(f"[yellow]not on the mesh yet:[/] {now.get('setup_error') or 'still joining'}")
                return
            if now.get("link_state") == "expired":
                fail("the code ran out before it was entered; run this again for a new one")
    except KeyboardInterrupt:
        raise typer.Exit(code=1) from None


@app.command("unlink")
def unlink(yes: Annotated[bool, typer.Option("--yes", help="Do not ask.")] = False) -> None:
    """Give the name back. The mesh and every device on it go; the home network stays. Administrators only."""
    if not yes and not typer.confirm("Unlink the cloud? Every device on its mesh loses its way in."):
        raise typer.Exit(code=1)
    run(_call(lambda api: api.unlink()))
    console.print("unlinked; the cloud is reached on the home network")


@app.command("invite")
def invite() -> None:
    """An invite code for a device: good once, for ten minutes (stdout: the code)."""
    data = run(_call(lambda api: api.mesh_invite()))
    typer.echo(data["code"])
    console.print(
        f"[dim]A computer:  {data['command']}\n"
        f"             (it asks for the code)\n"
        f"A phone:     the Tailscale app, log in with another server: {data['login_server']}\n"
        f"             then enter the code. Until {data.get('expires_at') or 'ten minutes from now'}.[/]"
    )


def _consent(yes: bool):
    def ask() -> bool:
        return yes or typer.confirm("Tailscale is not installed. Install it now from tailscale.com?")

    return ask


def _claim(address: str, device: str) -> bool:
    """Tell the cloud this computer is yours, when signed in to it; False when not."""
    config = ClientConfig.load()
    if StoredCredentials.load() is None or not config.api_url:
        return False
    run(_call(lambda api: api.claim_mesh_device(address, device or meshjoin.device_name())))
    return True


@app.command("join")
def join(
    invite_code: Annotated[
        str | None, typer.Option("--invite", help="An invite code from Me → Invite a device.")
    ] = None,
    server: Annotated[str, typer.Option("--server", help="The cloud's address, with --invite.")] = "",
    access_control: Annotated[
        str, typer.Option("--access-control", help="The relay, when it is not relay.<zone>.")
    ] = "",
    device: Annotated[str, typer.Option("--device", help="What you call this computer.")] = "",
    yes: Annotated[bool, typer.Option("--yes", help="Install Tailscale without asking.")] = False,
) -> None:
    """Put this computer on the cloud's mesh: a key, Tailscale, and `tailscale up`."""
    if invite_code is not None:
        server = server or ClientConfig.load().api_url
        if not invite_code:
            invite_code = typer.prompt("Invite code (from Me → Invite a device)")
        try:
            key = meshjoin.redeem(server, invite_code, access_control=access_control)
        except meshjoin.JoinError as exc:
            fail(str(exc))
    else:
        here = meshjoin.state()
        status = run(_call(lambda api: api.access()))
        if here.running and here.on(status.get("mesh", {}).get("login_server", "")) and here.login_server:
            console.print(f"this computer is on the mesh already, at {here.address}")
            if here.address:
                _claim(here.address, device)
            return
        key = run(_call(lambda api: api.mesh_key()))
    hostname = str(key.get("hostname") or "") or meshjoin.new_hostname()
    console.print(f"joining as [b]{hostname}[/] — tailscale up needs your password")
    try:
        joined = meshjoin.join(key, hostname=hostname, install=_consent(yes))
    except meshjoin.JoinError as exc:
        fail(str(exc))
    console.print(f"[green]on the mesh[/] at {joined.address or '?'}")
    if joined.address and invite_code is None:
        _claim(joined.address, device)
    elif invite_code is not None:
        console.print("[dim]sign in, then: cloudmorrow access mine — so the cloud knows it is yours[/]")


@app.command("mine")
def mine(device: Annotated[str, typer.Argument(help="What you call this computer.")] = "") -> None:
    """Tell the cloud this computer, on its mesh, is yours. Kept on the cloud, never sent anywhere else."""
    here = meshjoin.state()
    if not here.running or not here.address:
        fail("this computer is not on a mesh; join it first: cloudmorrow access join")
    if not _claim(here.address, device):
        fail("sign in first: cloudmorrow login")
    console.print(f"this computer ({here.address}) is yours on the cloud")


@app.command("devices")
def devices(
    everyone: Annotated[bool, typer.Option("--everyone", help="Everybody's (administrators).")] = False,
) -> None:
    """Your devices on the mesh."""
    rows = run(_call(lambda api: api.mesh_devices(everyone=everyone)))
    if not rows:
        console.print("[dim]no devices on the mesh[/]")
        return
    for row in rows:
        online = "online" if row.get("online") else "offline"
        label = row.get("label") or "(nobody's yet)"
        typer.echo(f"{row['id']}\t{label}\t{row.get('address', '')}\t{online}")


@app.command("remove")
def remove(device_id: Annotated[str, typer.Argument(help="The id `cm access devices` shows.")]) -> None:
    """Take a device off the mesh."""
    run(_call(lambda api: api.remove_mesh_device(device_id)))
    console.print(f"{device_id} is off the mesh")
