"""`cloudmorrow circle` — who on this server may use which data.

A circle is a named set of people and, per datamodel, what they may do with
it: write, read, or nothing. Your access is the most any of your circles
gives. See docs/CIRCLES.md.

    cloudmorrow circle list
    cloudmorrow circle add Kids
    cloudmorrow circle rule Kids task write
    cloudmorrow circle join Kids alice

Only administrators change circles; `cloudmorrow access` is anybody's own.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from cloudmorrow.cli.common import client, console, fail, out, run
from cloudmorrow.console import TITLE

app = typer.Typer(help="Circles: who may use which data.", no_args_is_help=True)

ACCESS = ("write", "read", "none")
COLOURS = {"write": "green", "read": "cyan", "none": "red"}

CircleArg = Annotated[str, typer.Argument(help="The circle, by its name or its id.")]


def said(rules: dict[str, str]) -> str:
    """A circle's rules on one line, `*` first: `* write, task read`."""
    if not rules:
        return "[dim]nothing[/]"
    order = sorted(rules, key=lambda model: (model != "*", model))
    return ", ".join(
        f"{model} [{COLOURS.get(rules[model], 'dim')}]{rules[model]}[/]" for model in order
    )


@app.command("list")
def list_circles() -> None:
    """Every circle, with its rules and its people."""

    async def _list() -> None:
        _, api = client()
        async with api:
            circles = await api.circles()
            users = await api.users()
        table = Table(title="circles", title_style=TITLE)
        for column in ("circle", "default", "rules", "people"):
            table.add_column(column, overflow="fold")
        for circle in circles:
            table.add_row(
                f"[b]{circle['name']}[/]",
                "[green]yes[/]" if circle["default"] else "",
                said(circle["rules"]),
                ", ".join(circle["members"]) or "[dim]nobody[/]",
            )
        out.print(table)
        # Rule 3: in no circle is no data, and that is worth a line of its own.
        placed = {name for circle in circles for name in circle["members"]}
        adrift = [user["username"] for user in users if user["username"] not in placed]
        if adrift:
            console.print(
                f"[yellow]![/] [dim]in no circle, so reaching no data:[/] {', '.join(adrift)}"
            )

    run(_list())


@app.command("add")
def add(
    name: Annotated[str, typer.Argument(help="What it is called: Parents, Kids, Sales.")],
) -> None:
    """Make a circle, with nobody in it and no data yet."""

    async def _add() -> None:
        _, api = client()
        async with api:
            circle = await api.create_circle(name)
        console.print(
            f"[green]Made[/] {circle['name']}. [dim]Give it data with "
            f"`cm circle rule {circle['id']} <datamodel> write`, and people with "
            f"`cm circle join {circle['id']} <user>`.[/]"
        )

    run(_add())


@app.command("rule")
def rule(
    circle: CircleArg,
    model: Annotated[str, typer.Argument(help="A datamodel id, or * for every one.")],
    access: Annotated[str, typer.Argument(help="write, read or none.")],
) -> None:
    """Say what a circle may do with one datamodel. Its other rules stay."""
    access = access.strip().lower()
    if access not in ACCESS:
        fail(f"access is write, read or none, not {access!r}")

    async def _rule() -> None:
        _, api = client()
        async with api:
            changed = await api.set_circle_rule(circle, model, access)
        console.print(f"[green]{changed['name']}[/]: {said(changed['rules'])}")

    run(_rule())


@app.command("join")
def join(
    circle: CircleArg, username: Annotated[str, typer.Argument(help="Who to put in it.")]
) -> None:
    """Put somebody in a circle."""

    async def _join() -> None:
        _, api = client()
        async with api:
            changed = await api.join_circle(circle, username)
        console.print(f"[green]{username}[/] is in {changed['name']}.")

    run(_join())


@app.command("leave")
def leave(
    circle: CircleArg, username: Annotated[str, typer.Argument(help="Who to take out.")]
) -> None:
    """Take somebody out of a circle. Their other circles stay."""

    async def _leave() -> None:
        _, api = client()
        async with api:
            changed = await api.leave_circle(circle, username)
            circles = await api.circles()
        console.print(f"[green]{username}[/] is out of {changed['name']}.")
        if not any(username in c["members"] for c in circles):
            console.print(f"[yellow]![/] [dim]{username} is in no circle now: no data at all.[/]")

    run(_leave())


@app.command("default")
def default(
    circle: CircleArg,
    off: Annotated[
        bool, typer.Option("--off", help="Stop new accounts going into it.")
    ] = False,
) -> None:
    """Make a circle where new accounts go. More than one may be."""

    async def _default() -> None:
        _, api = client()
        async with api:
            changed = await api.update_circle(circle, default=not off)
        if off:
            console.print(f"New accounts no longer go into {changed['name']}.")
        else:
            console.print(f"[green]New accounts go into {changed['name']}.[/]")

    run(_default())


@app.command("delete")
def delete(circle: CircleArg) -> None:
    """Delete a circle. Its people keep their other circles."""

    async def _delete() -> None:
        _, api = client()
        async with api:
            await api.delete_circle(circle)
        console.print(f"[green]Deleted[/] {circle}.")

    run(_delete())


def access() -> None:
    """What you may do with each datamodel, and the circles that say so."""

    async def _access() -> None:
        _, api = client()
        async with api:
            mine = await api.my_access()
        circles = mine.get("circles") or []
        if not circles:
            console.print("[yellow]You are in no circle, so you reach no data.[/]")
            return
        console.print(f"[dim]your circles:[/] {', '.join(circles)}")
        table = Table(title="your access", title_style=TITLE)
        table.add_column("datamodel")
        table.add_column("access")
        for model, level in sorted(mine["access"].items()):
            table.add_row(model, f"[{COLOURS.get(level, 'dim')}]{level}[/]")
        out.print(table)

    run(_access())
