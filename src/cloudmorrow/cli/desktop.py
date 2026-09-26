"""`cloudmorrow app` — the desktop app: the web app in a window, with this computer behind it.

    cloudmorrow app                      open it
    cloudmorrow app --print-url          the address it opens, and nothing else
    cloudmorrow app --dry-run            what it would open, and whether it could
    cloudmorrow app --install-launcher   put it in the applications menu

The window is `cloudmorrow.desktop`; this is only the way in. It is its own
file, beside the others, so the command line knows nothing about windows
and a machine without the `desktop` extra never imports one.
"""

from __future__ import annotations

from typing import Annotated

import typer

from cloudmorrow.cli.common import console, emit, fail
from cloudmorrow.client.config import ClientConfig


def app_command(
    print_url: Annotated[
        bool, typer.Option("--print-url", help="Print the address the window opens, and stop.")
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Say what would be opened, and whether it could be."),
    ] = False,
    install_launcher: Annotated[
        bool,
        typer.Option(
            "--install-launcher",
            help="Put the desktop app in the applications menu (Linux), and stop.",
        ),
    ] = False,
    remove_launcher: Annotated[
        bool,
        typer.Option("--remove-launcher", help="Take it out of the applications menu again."),
    ] = False,
    debug: Annotated[
        bool, typer.Option("--debug", help="Open the web inspector beside the window.")
    ] = False,
) -> None:
    """Open the desktop app: the web app in a window, mounting shares on this computer."""
    # Imported here: `cm note list` should not pay for any of this.
    from cloudmorrow.desktop import app, launcher

    config = ClientConfig.load()
    if print_url:
        emit(app.app_url(config) + "\n")
        return
    if remove_launcher:
        removed = launcher.remove()
        for path in removed:
            console.print(f"[green]Removed[/] {path}")
        if not removed:
            console.print("[dim]No launcher on this machine.[/]")
        return
    if install_launcher:
        try:
            written = launcher.install(app.cloud_name(config))
        except (launcher.LauncherError, OSError) as exc:
            fail(str(exc))
        for path in written:
            console.print(f"[green]Wrote[/] {path}")
        return
    if dry_run:
        for label, value in app.plan(config).lines():
            console.print(f"[dim]{label + ':':<11}[/] {value}", soft_wrap=True)
        return
    try:
        app.launch(config, debug=debug)
    except app.DesktopError as exc:
        fail(str(exc))
