"""`cloudmorrow-agent` — enrol a machine, then run the agent on it."""

from __future__ import annotations

import json
import logging
import platform
import socket
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from cloudmorrow import __version__
from cloudmorrow.agent import omarchy
from cloudmorrow.agent.client import AgentApiError, AgentClient
from cloudmorrow.agent.config import AgentConfig, default_config_path
from cloudmorrow.agent.runner import AgentRunner
from cloudmorrow.agent.sync import BUNDLES, SyncState, state_dir, sync_all
from cloudmorrow.agent.tasks import TaskError, run_task
from cloudmorrow.console import TITLE
from cloudmorrow.console import console as make_console
from cloudmorrow.links import ensure_commands_linked

app = typer.Typer(help="Cloudmorrow local agent.", no_args_is_help=True)
console = make_console()

ConfigOption = Annotated[
    Path | None, typer.Option("--config", "-c", help="Path to agent.toml.")
]


def _load(config_path: Path | None) -> AgentConfig:
    return AgentConfig.load(config_path)


@app.command()
def enroll(
    server: Annotated[str, typer.Option("--server", "-s", help="Cloudmorrow base URL.")],
    token: Annotated[str, typer.Option("--token", "-t", help="Single-use enrolment token.")],
    name: Annotated[str | None, typer.Option(help="Agent name (default: hostname).")] = None,
    config_path: ConfigOption = None,
    allow_shell: Annotated[
        bool, typer.Option(help="Let this machine run shell jobs.")
    ] = False,
    backup_root: Annotated[
        list[str] | None,
        typer.Option("--backup-root", help="A directory backups may read (repeatable)."),
    ] = None,
) -> None:
    """Trade an enrolment token for this machine's agent token."""
    config = _load(config_path)
    config.server_url = server.rstrip("/")
    config.name = name or socket.gethostname()
    config.allow_shell = allow_shell
    if backup_root:
        config.backup_roots = backup_root

    with AgentClient(config) as client:
        try:
            result = client.enroll(
                token, config.name, socket.gethostname(), platform.platform()
            )
        except AgentApiError as exc:
            console.print(f"[red]Enrolment failed:[/] {exc}")
            raise typer.Exit(code=1) from None

    config.agent_token = result["agent_token"]
    path = config.save(config_path)
    console.print(
        f"[green]Enrolled[/] as [b]{result['name']}[/] (agent {result['agent_id']})\n"
        f"[dim]config written to {path}[/]\n"
        f"[dim]capabilities: {', '.join(config.capabilities)}[/]"
    )
    if not config.allow_shell:
        console.print("[dim]shell jobs are disabled; re-run with --allow-shell to permit them[/]")


@app.command()
def run(
    config_path: ConfigOption = None,
    once: Annotated[bool, typer.Option(help="Do a single pass and exit.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Run the agent loop."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )
    config = _load(config_path)
    if not config.server_url or not config.agent_token:
        console.print("[red]This agent is not enrolled.[/] Run `cloudmorrow-agent enroll` first.")
        raise typer.Exit(code=1)
    # An update restarts the agent onto the new code before anyone types
    # anything, so this is the earliest a new command can be put on the PATH.
    ensure_commands_linked()
    runner = AgentRunner(config)
    runner.install_signal_handlers()
    stats = runner.run_forever(max_ticks=1 if once else None)
    console.print(
        f"[dim]{stats.heartbeats} heartbeats, {stats.jobs_done} jobs done, "
        f"{stats.jobs_failed} failed[/]"
    )


@app.command()
def status(config_path: ConfigOption = None) -> None:
    """Show this machine's agent configuration."""
    config = _load(config_path)
    table = Table(title="cloudmorrow agent", title_style=TITLE)
    table.add_column("key", style="dim")
    table.add_column("value")
    table.add_row("config file", str(config.path or default_config_path()))
    table.add_row("server", config.server_url or "—")
    table.add_row("name", config.name)
    table.add_row("enrolled", "yes" if config.agent_token else "no")
    table.add_row("capabilities", ", ".join(config.capabilities))
    table.add_row("poll seconds", str(config.poll_seconds))
    table.add_row("backup roots", ", ".join(config.backup_roots))
    table.add_row("backup dir", config.backup_dir)
    table.add_row("backup retention", str(config.backup_retention))
    table.add_row("allow shell", str(config.allow_shell))
    table.add_row("allow config sync", str(config.allow_config_sync))
    table.add_row(
        "machine shares",
        f"served on port {config.share_port}" if config.allow_shares else "off",
    )
    table.add_row("omarchy", omarchy.describe())
    for bundle in sorted(BUNDLES):
        state = SyncState.load(bundle)
        held = (
            f"revision {state.revision} from {state.origin or '?'}"
            f" ({len(state.files)} files)"
            if state.revision
            else "never synced here"
        )
        table.add_row(f"config: {bundle}", held)
    console.print(table)


@app.command("try")
def try_task(
    job_type: Annotated[str, typer.Argument(help="ping, sysinfo, backup or shell.")],
    payload: Annotated[str, typer.Option(help="JSON payload for the task.")] = "{}",
    config_path: ConfigOption = None,
) -> None:
    """Run a task locally, without the server. Useful for checking a backup job."""
    config = _load(config_path)
    try:
        result = run_task(job_type, json.loads(payload), config)
    except (TaskError, ValueError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from None
    console.print_json(json.dumps(result))


@app.command()
def sync(
    bundle: Annotated[
        list[str] | None,
        typer.Option("--bundle", "-b", help=f"Which bundle ({', '.join(sorted(BUNDLES))})."),
    ] = None,
    config_path: ConfigOption = None,
    reset: Annotated[
        bool,
        typer.Option(help="Forget what this machine holds, so it adopts the server's copy."),
    ] = False,
) -> None:
    """Sync this machine's config now, instead of waiting for the next poll.

    The agent does this on its own every poll. This is for when you have just
    changed something and would rather not wait, or want to see why it is not
    doing what you expected.
    """
    config = _load(config_path)
    if not config.server_url or not config.agent_token:
        console.print("[red]This agent is not enrolled.[/] Run `cloudmorrow-agent enroll` first.")
        raise typer.Exit(code=1)
    bundles = list(bundle) if bundle else sorted(BUNDLES)
    if reset:
        for name in bundles:
            SyncState.load(name).clear()
        console.print(f"[dim]forgot what this machine held; state in {state_dir()}[/]")

    with AgentClient(config) as client:
        try:
            outcomes = sync_all(client, config, bundles)
        except AgentApiError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(code=1) from None

    for outcome in outcomes:
        colour = {
            "failed": "red",
            "refused": "yellow",
            "stale": "yellow",
            "idle": "dim",
            "skipped": "dim",
        }.get(outcome.action, "green")
        revision = f" rev {outcome.revision}" if outcome.revision else ""
        console.print(
            f"[{colour}]{outcome.action}[/] {outcome.bundle}{revision}"
            + (f"  [dim]{outcome.detail}[/]" if outcome.detail else "")
        )
    if any(outcome.action == "failed" for outcome in outcomes):
        raise typer.Exit(code=1)


@app.command()
def version() -> None:
    """Print the version."""
    console.print(f"cloudmorrow-agent {__version__}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
