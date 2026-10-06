"""`cloudmorrow` — the command line.

Every command reads `cloudmorrow RESOURCE ACTION`:

    cloudmorrow secret get OPENAI_API_KEY
    cloudmorrow note show "Architecture"
    cloudmorrow share mount media

The resource is singular, and the actions are the same words everywhere.

`--dev` anywhere in the arguments runs the checkout you are standing in rather
than the installed client; see `cloudmorrow.cli.dev`.
"""

from __future__ import annotations

import getpass
import os
import sys
from typing import Annotated

import typer

from cloudmorrow.agent.setup import ensure_agent, stop_agent
from cloudmorrow.cli import (
    agent,
    circle,
    desktop,
    dev,
    note,
    quill,
    quillrun,
    secret,
    settings,
    share,
    uninstall,
    update,
)
from cloudmorrow.cli.common import client, console, run
from cloudmorrow.client import discover
from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.client.config import (
    ClientConfig,
    StoredCredentials,
    clear_credentials,
    config_path,
    credentials_path,
)
from cloudmorrow.links import ensure_commands_linked
from cloudmorrow.logo import banner

app = typer.Typer(
    help="Cloudmorrow — your own cloud: notes, secrets, files and more, on every machine.",
    no_args_is_help=False,
)
app.add_typer(secret.app, name="secret")
app.add_typer(note.app, name="note")
app.add_typer(agent.app, name="agent")
app.add_typer(share.app, name="share")
app.add_typer(settings.app, name="config")
app.add_typer(update.app, name="update")
app.add_typer(quill.app, name="quill")
app.add_typer(circle.app, name="circle")
# Your own access: what your circles give you, per datamodel.
app.command("access")(circle.access)
# The way out: `cloudmorrow uninstall`, in its own file beside the way in.
app.command("uninstall")(uninstall.uninstall)
# The desktop app: the web app in a window, with this computer behind it.
app.command("app")(desktop.app_command)

# What the resources used to be called, kept working but out of the help.
# (Not `notes` nor `secrets`: those are the Notes and Secrets Quills' now,
# `cm notes …` and `cm secrets list` through the kit.)
app.add_typer(agent.app, name="agents", hidden=True)
app.add_typer(share.app, name="shares", hidden=True)
# Where `cm <quill> ...` lands once `main` has seen it is not a command.
app.command("run-quill", hidden=True, context_settings={"allow_interspersed_args": True})(quillrun.main)


@app.callback(invoke_without_command=True)
def default(ctx: typer.Context) -> None:
    """Open the TUI when no command is given."""
    if ctx.invoked_subcommand is None:
        _run_tui()


def _run_tui() -> None:
    from cloudmorrow.tui.app import CloudmorrowApp

    CloudmorrowApp().run()


@app.command()
def tui() -> None:
    """Open the TUI."""
    _run_tui()


@app.command()
def login(
    username: Annotated[str | None, typer.Option("--user", "-u")] = None,
    server: Annotated[str | None, typer.Option("--server", "-s", help="API base URL.")] = None,
    agent_setup: Annotated[
        bool,
        typer.Option("--agent/--no-agent", help="Set this machine up as an agent (runs as you)."),
    ] = True,
) -> None:
    """Sign in and store an access token."""
    config = ClientConfig.load()
    if server:
        config.api_url = server.rstrip("/")
        config.save()
    elif not config_path().exists() and not os.environ.get("CLOUDMORROW_API_URL"):
        # Nothing given and nothing configured: look on the home network.
        choose_cloud(config)
    username = username or input("Username: ").strip()
    password = getpass.getpass("Password: ")

    async def _login() -> None:
        async with CloudmorrowClient(config) as api:
            session = await api.login(username, password)
            StoredCredentials(
                api_url=config.api_url,
                username=session.username,
                access_token=session.access_token,
                expires_at=session.expires_at,
            ).save()
            console.print(
                f"[green]Signed in[/] as [b]{session.username}[/] on {config.api_url}\n"
                f"[dim]token stored in {credentials_path()}[/]"
            )
            if agent_setup:
                result = await ensure_agent(api)
                if result.enrolled and result.started:
                    console.print(f"[dim]this machine is registered as '{result.agent_name}'[/]")
                elif result.enrolled:
                    console.print(
                        f"[dim]registered as '{result.agent_name}', but it is not running: {result.detail}[/]"
                    )

    run(_login())


def choose_cloud(config: ClientConfig, found: list[discover.Found] | None = None) -> None:
    """List the clouds on this network and let the person pick one, or type an address."""
    if found is None:
        console.print("[dim]looking for clouds on this network…[/]")
        found = discover.browse()
    address = ""
    if found:
        for number, cloud in enumerate(found, 1):
            console.print(f"  [b]{number}[/]  {cloud.describe()}")
        answer = input(f"Which one? [1-{len(found)}, or an address]: ").strip() or "1"
        if answer.isdigit() and 1 <= int(answer) <= len(found):
            use_found(config, found[int(answer) - 1])
            return
        address = answer
    else:
        console.print("[dim]none found here[/]")
        address = input("Server address (https://…): ").strip()
    if not address:
        raise typer.Exit(code=1)
    if "://" not in address:
        address = f"https://{address}"
    config.api_url = address.rstrip("/")
    config.save()


def use_found(config: ClientConfig, cloud: discover.Found) -> None:
    """Point this computer at a cloud found on the network."""
    config.api_url = cloud.api_url
    if cloud.plain:
        # Picking a plain-http cloud from the list is saying it is meant to be plain.
        config.allow_insecure_http = True
        console.print("[yellow]note:[/] this cloud is plain http, which is for a home network only.")
    config.save()


@app.command()
def logout(
    agent_stop: Annotated[bool, typer.Option("--agent/--no-agent", help="Also stop this machine's agent.")] = True,
) -> None:
    """Forget the stored access token, and stop the local agent."""
    if agent_stop:
        stop_agent()
    if clear_credentials():
        console.print("[green]Signed out.[/]")
    else:
        console.print("[dim]No stored session.[/]")


@app.command()
def whoami() -> None:
    """Show the signed-in user, and where secrets commands go by default."""

    async def _whoami() -> None:
        config, api = client()
        async with api:
            user = await api.me()
        # A server from before roles existed sends only the flag.
        role = user.get("role") or ("administrator" if user["is_admin"] else "user")
        kind = user.get("user_type") or "human"
        badge = role if kind == "human" else f"{role}, {kind}"
        console.print(f"[b]{user['username']}[/] [cyan]({badge})[/] on {config.api_url}")
        console.print(f"[dim]vault:[/] {config.vault}")
        console.print(f"[dim]environment:[/] {config.environment}")

    run(_whoami())


@app.command()
def version() -> None:
    """Print the version, with the logo."""
    console.print(banner())
    # A version read off the nearest tag says nothing about running from
    # source, and in a checkout that is the thing you want to know.
    if root := dev.checkout():
        console.print(f"[dim] running from[/] {root}")


def main() -> None:
    # Before typer sees them: --dev is about which code parses the rest.
    sys.argv[1:] = dev.handle(sys.argv[1:])
    # The update that brings a new command is run by the old code, so the
    # new code links its own commands the first time it runs.
    ensure_commands_linked()
    # `cm tasks list`: a word that is not a command is an installed Quill's.
    sys.argv[1:] = quillrun.route(sys.argv[1:], _command_names())
    app()


def _command_names() -> set[str]:
    names = {info.name for info in app.registered_groups} | {"--help", "-h"}
    names |= {info.name or info.callback.__name__ for info in app.registered_commands}
    return {name for name in names if name}


if __name__ == "__main__":
    main()
