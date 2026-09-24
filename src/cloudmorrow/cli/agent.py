"""`cloudmorrow agent` — the machines running Cloudmorrow's local agent."""

from __future__ import annotations

import json
from typing import Annotated

import typer
from rich.table import Table

from cloudmorrow.cli.common import client, console, out, run
from cloudmorrow.console import TITLE

app = typer.Typer(help="Machines running the local agent.", no_args_is_help=True)


@app.command("list")
def list_agents() -> None:
    """List enrolled machines."""

    async def _list() -> None:
        _, api = client()
        try:
            agents = await api.agents()
        finally:
            await api.aclose()
        table = Table(title="agents", title_style=TITLE)
        for column in ("", "id", "name", "host", "platform", "last seen", "can"):
            table.add_column(column)
        for agent in agents:
            table.add_row(
                "[green]●[/]" if agent["online"] else "[dim]○[/]",
                str(agent["id"]),
                agent["name"],
                agent["hostname"],
                agent["platform"][:24],
                (agent["last_seen"] or "never").replace("T", " "),
                ",".join(agent["capabilities"]),
            )
        out.print(table)

    run(_list())


@app.command("enroll-token")
def enroll_token(
    label: Annotated[str, typer.Option(help="A note about the machine.")] = "",
) -> None:
    """Mint a single-use token and print the install command for a new machine."""

    async def _token() -> None:
        config, api = client()
        try:
            token = await api.enroll_token(label)
        finally:
            await api.aclose()
        console.print(
            f"\n  [dim]run this on the new machine (expires "
            f"{token['expires_at'].replace('T', ' ')}):[/]\n\n"
            f"  [#7dd3fc]curl -fsSL {config.api_url}/install.sh | sh -s -- "
            f"--agent-token {token['enrollment_token']}[/]\n\n"
            f"  [dim]add --allow-shell to let that machine run commands[/]\n"
        )

    run(_token())


@app.command("run")
def run_job(
    agent_id: Annotated[int, typer.Argument(help="Which machine, from `agent list`.")],
    job_type: Annotated[str, typer.Argument(help="ping, sysinfo, backup or shell.")],
    payload: Annotated[str, typer.Option(help="JSON payload for the job.")] = "{}",
) -> None:
    """Queue a job for a machine."""

    async def _run_job() -> None:
        _, api = client()
        try:
            job = await api.create_job(agent_id, job_type, json.loads(payload))
        finally:
            await api.aclose()
        console.print(f"[green]Queued[/] {job['type']} #{job['id']}")

    run(_run_job())


@app.command("jobs")
def jobs(
    agent_id: Annotated[int, typer.Argument(help="Which machine, from `agent list`.")],
    limit: Annotated[int, typer.Option(help="How many jobs to show.")] = 20,
) -> None:
    """Show recent jobs for a machine."""

    async def _jobs() -> None:
        _, api = client()
        try:
            found = await api.jobs(agent_id, limit)
        finally:
            await api.aclose()
        table = Table(title=f"jobs · agent {agent_id}", title_style=TITLE)
        for column in ("id", "type", "status", "created", "result"):
            table.add_column(column)
        colours = {"done": "green", "failed": "red", "running": "yellow"}
        for job in found:
            result = json.dumps(job["result"] or {}, separators=(",", ":"))
            table.add_row(
                str(job["id"]),
                job["type"],
                f"[{colours.get(job['status'], 'dim')}]{job['status']}[/]",
                job["created_at"].replace("T", " "),
                result[:70],
            )
        out.print(table)

    run(_jobs())
