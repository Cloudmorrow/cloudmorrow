"""`cloudmorrow role`, `approvals`, `approve`, `decline` and `flow` — who is
responsible for what, the yes-or-no questions asked of them, and the flows
that ask (docs/FLOWS.md).

    cloudmorrow role list
    cloudmorrow role add "Team lead"
    cloudmorrow role give team_lead alice [--circle Sales]
    cloudmorrow approvals                 what waits for you, and what you asked
    cloudmorrow approve <id> [--note …]
    cloudmorrow flow list
    cloudmorrow flow run <flow> [--on <model> <id>]

A role gives no access to data; `cloudmorrow circle` does that.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from cloudmorrow.cli.common import client, console, fail, out, run
from cloudmorrow.console import TITLE

app = typer.Typer(help="Roles: who is responsible for what.", no_args_is_help=True)
flow_app = typer.Typer(help="Flows: when something happens, do these steps.", no_args_is_help=True)

RoleArg = Annotated[str, typer.Argument(help="The role, by its id or its name.")]
CircleOpt = Annotated[str, typer.Option("--circle", help="Within this circle only.")]


def _holders(role: dict) -> str:
    if not role["holders"]:
        return "[dim]nobody yet[/]"
    return ", ".join(h["username"] + (f" ({h['circle']})" if h["circle"] else "") for h in role["holders"])


@app.command("list")
def list_roles() -> None:
    """Every role, who holds it, and which Quill asked for it."""

    async def _list() -> None:
        _, api = client()
        async with api:
            roles = await api.roles()
        if not roles:
            console.print('[dim]No roles yet. `cm role add "Team lead"` makes one.[/]')
            return
        table = Table(title="roles", title_style=TITLE)
        for column in ("role", "id", "held by", "asked for by"):
            table.add_column(column, overflow="fold")
        for role in roles:
            table.add_row(f"[b]{role['name']}[/]", role["id"], _holders(role), role["declared_by"] or "")
        out.print(table)

    run(_list())


@app.command("add")
def add(
    name: Annotated[str, typer.Argument(help="What it is called: Team lead, Expense Responsible.")],
    description: Annotated[str, typer.Option("--why", help="What the holder is responsible for.")] = "",
) -> None:
    """Make a role, held by nobody yet."""

    async def _add() -> None:
        _, api = client()
        async with api:
            role = await api.create_role(name, description)
        console.print(f"[green]Made[/] {role['name']}. [dim]Give it with `cm role give {role['id']} <user>`.[/]")

    run(_add())


@app.command("give")
def give(role: RoleArg, username: Annotated[str, typer.Argument(help="Who holds it.")], circle: CircleOpt = "") -> None:
    """Put the hat on somebody: everywhere, or within one circle."""

    async def _give() -> None:
        _, api = client()
        async with api:
            changed = await api.give_role(role, username, circle)
        where = f" in {circle}" if circle else ""
        console.print(f"[green]{username}[/] holds {changed['name']}{where}.")

    run(_give())


@app.command("take")
def take(
    role: RoleArg, username: Annotated[str, typer.Argument(help="Who stops holding it.")], circle: CircleOpt = ""
) -> None:
    """Take the hat off somebody."""

    async def _take() -> None:
        _, api = client()
        async with api:
            changed = await api.take_role(role, username, circle)
        console.print(f"[green]{username}[/] no longer holds {changed['name']}.")

    run(_take())


@app.command("delete")
def delete(role: RoleArg) -> None:
    """Delete a role. One a Quill declared comes back, empty, when the Quills are next read."""

    async def _delete() -> None:
        _, api = client()
        async with api:
            await api.delete_role(role)
        console.print(f"[green]Deleted[/] {role}.")

    run(_delete())


# -- approvals ---------------------------------------------------------------------------------
def _about(approval: dict) -> str:
    fields = approval["fields"]
    title = fields.get("about_title") or ""
    model = fields.get("about_model") or ""
    return f"{title} [dim]({model})[/]" if title and model else title or model or ""


def approvals() -> None:
    """What waits for your answer, and what you asked that is still open."""

    async def _list() -> None:
        _, api = client()
        async with api:
            found = await api.approvals()
        waiting, asked = found["waiting"], found["asked"]
        if not waiting and not asked:
            console.print("[dim]Nothing waits for you, and you have asked nothing that is open.[/]")
            return
        if waiting:
            table = Table(title="waiting for you", title_style=TITLE)
            for column in ("id", "question", "about", "asked by", "due"):
                table.add_column(column, overflow="fold")
            for a in waiting:
                f = a["fields"]
                table.add_row(a["id"], f["question"], _about(a), f.get("asked_by") or a["owner"], f.get("due") or "")
            out.print(table)
            console.print("[dim]`cm approve <id>` or `cm decline <id> --note …`.[/]")
        if asked:
            table = Table(title="asked by you", title_style=TITLE)
            for column in ("id", "question", "about", "of"):
                table.add_column(column, overflow="fold")
            for a in asked:
                f = a["fields"]
                table.add_row(
                    a["id"], f["question"], _about(a), f["role"] + (f" in {f['circle']}" if f.get("circle") else "")
                )
            out.print(table)

    run(_list())


NoteOpt = Annotated[str, typer.Option("--note", help="A word with the answer.")]


def _answer(approval_id: str, status: str, note: str) -> None:
    async def _do() -> None:
        _, api = client()
        async with api:
            changed = await api.answer_approval(approval_id, status, note)
        console.print(f"[green]{status.capitalize()}[/]: {changed['fields']['question']}")

    run(_do())


def approve(
    approval_id: Annotated[str, typer.Argument(help="The approval's id, from `cm approvals`.")], note: NoteOpt = ""
) -> None:
    """Say yes to something waiting for you."""
    _answer(approval_id, "approved", note)


def decline(
    approval_id: Annotated[str, typer.Argument(help="The approval's id, from `cm approvals`.")], note: NoteOpt = ""
) -> None:
    """Say no to something waiting for you."""
    _answer(approval_id, "declined", note)


# -- flows --------------------------------------------------------------------------------------
def _trigger_said(trigger: dict) -> str:
    kind = trigger.get("kind")
    if kind == "record":
        when = trigger.get("when", ["created"])
        when = when if isinstance(when, str) else " or ".join(when)
        said = f"when a {trigger.get('model')} is {when}"
        if trigger.get("field"):
            said += f" ({trigger['field']}" + (f" = {trigger['value']}" if "value" in trigger else "") + ")"
        return said
    if kind == "action":
        return f"when {trigger.get('quill')} {trigger.get('action')} is pressed"
    if kind == "schedule":
        return f"every {trigger.get('every')}"
    return "by hand"


@flow_app.command("list")
def list_flows() -> None:
    """Your flows: what starts each, and how many steps it has."""

    async def _list() -> None:
        _, api = client()
        async with api:
            flows = await api.records("flow")
        if not flows:
            console.print("[dim]No flows yet. Make one under Me, Flows.[/]")
            return
        table = Table(title="flows", title_style=TITLE)
        for column in ("flow", "id", "on", "starts", "steps"):
            table.add_column(column, overflow="fold")
        for flow in flows:
            f = flow["fields"]
            table.add_row(
                f"[b]{f['name']}[/]",
                flow["id"],
                "[green]yes[/]" if f.get("on", True) else "[dim]off[/]",
                _trigger_said(f.get("trigger") or {}),
                str(len(f.get("steps") or [])),
            )
        out.print(table)

    run(_list())


@flow_app.command("run")
def run_flow(
    flow: Annotated[str, typer.Argument(help="The flow's id, from `cm flow list`.")],
    on: Annotated[
        tuple[str, str] | None, typer.Option("--on", help="A record to run it on: its datamodel and its id.")
    ] = None,
) -> None:
    """Start a flow now and say how far it got."""

    async def _run() -> None:
        _, api = client()
        async with api:
            model, record = on if on else ("", "")
            done = await api.run_flow(flow, model=model, record=record)
        f = done["fields"]
        colour = {"done": "green", "waiting": "yellow", "failed": "red"}.get(f["status"], "cyan")
        console.print(
            f"[{colour}]{f['status']}[/] at step {f.get('step', 0)}" + (f": {f['error']}" if f.get("error") else "")
        )

    run(_run())


@flow_app.command("runs")
def runs(flow: Annotated[str, typer.Argument(help="The flow's id.")]) -> None:
    """The runs of one flow, newest last."""

    async def _runs() -> None:
        _, api = client()
        async with api:
            found = await api.records("flow_run", flow=flow)
        if not found:
            console.print("[dim]It has not run yet.[/]")
            return
        table = Table(title="runs", title_style=TITLE)
        for column in ("run", "status", "step", "started", "error"):
            table.add_column(column, overflow="fold")
        for r in found:
            f = r["fields"]
            table.add_row(
                r["id"], f["status"], str(f.get("step", 0)), (f.get("started_at") or "")[:16], f.get("error") or ""
            )
        out.print(table)

    run(_runs())


__all__ = ["app", "approvals", "approve", "decline", "fail", "flow_app"]
