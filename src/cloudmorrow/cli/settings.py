"""`cloudmorrow config` — the client's own settings."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from cloudmorrow.cli.common import console, fail, out
from cloudmorrow.client.config import (
    ClientConfig,
    StoredCredentials,
    config_path,
)
from cloudmorrow.console import TITLE

app = typer.Typer(help="Read and write client settings.", no_args_is_help=True)

SETTINGS = (
    "api_url",
    "autosave_seconds",
    "verify_tls",
    "allow_insecure_http",
    "vault",
    "environment",
    "server_host",
)


@app.command("show")
def show() -> None:
    """Show the effective client configuration."""
    from cloudmorrow.cli.update import ssh_target

    config = ClientConfig.load()
    credentials = StoredCredentials.load()
    table = Table(title="cloudmorrow client config", title_style=TITLE)
    table.add_column("key", style="dim")
    table.add_column("value")
    table.add_row("config file", str(config_path()))
    table.add_row("api_url", config.api_url)
    table.add_row("autosave_seconds", str(config.autosave_seconds))
    table.add_row("verify_tls", str(config.verify_tls))
    table.add_row("vault", config.vault)
    table.add_row("environment", config.environment)
    table.add_row("server_host", config.server_host or f"{ssh_target(config)} [dim](derived)[/]")
    table.add_row("signed in as", credentials.username if credentials else "—")
    out.print(table)


@app.command("set")
def set_value(
    key: Annotated[str, typer.Argument(help=f"One of: {', '.join(SETTINGS)}.")],
    value: Annotated[str, typer.Argument(help="The new value.")],
) -> None:
    """Change a setting."""
    config = ClientConfig.load()
    if key == "server_host":
        config.server_host = value.strip()
    elif key == "environment":
        config.environment = value.strip().lower()
    elif key == "vault":
        config.vault = value.strip().lower() or "default"
    elif key == "api_url":
        config.api_url = value.rstrip("/")
    elif key == "autosave_seconds":
        config.autosave_seconds = float(value)
    elif key == "verify_tls":
        config.verify_tls = value.strip().lower() in {"1", "true", "yes", "on"}
    elif key == "allow_insecure_http":
        config.allow_insecure_http = value.strip().lower() in {"1", "true", "yes", "on"}
    else:
        fail(f"unknown setting: {key} (try {', '.join(SETTINGS)})")
    console.print(f"[green]Saved[/] {key} = {getattr(config, key)} → {config.save()}")
