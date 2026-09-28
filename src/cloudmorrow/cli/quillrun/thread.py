"""A `thread`: spaces, and what is said in them."""

from __future__ import annotations

import json

from rich.markup import escape
from rich.table import Table

# quillrun.out, .console and .emit, looked up as they print: see screen.py.
from cloudmorrow.cli import quillrun
from cloudmorrow.cli.common import fail
from cloudmorrow.cli.quillrun.screen import (
    Screen,
)
from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.console import TITLE

# How much of a conversation `show` prints.
PAGE = 50


def space_name(space: dict, me: str, screen: Screen) -> str:
    """What a space is called to *me*: its title, or, made between people, who else is in it."""
    marks = (screen.spec.get("made_as") or {}).get("direct") or {}
    if marks and all(space["fields"].get(k) == v for k, v in marks.items()):
        others = [who for who in [space["owner"], *(space.get("members") or [])] if who != me]
        return ", ".join(others) or me
    target = screen.models[screen.fields[screen.spec["space"]]["to"]]
    return str(space["fields"].get(target["title"]) or space["id"])


def _find_space(spaces: list[dict], key: str, me: str, screen: Screen) -> dict:
    """A space by its id (or the start of it), its name, or the person it is with."""
    wanted = key.lstrip("#")
    by_id = [s for s in spaces if s["id"].startswith(wanted if wanted.startswith("r_") else f"r_{wanted}")]
    named = [s for s in spaces if space_name(s, me, screen).casefold() == wanted.casefold()]
    matches = named or by_id
    if len(matches) != 1:
        fail(f"{'no' if not matches else 'more than one'} {screen.fields[screen.spec['space']]['to']}"
             f" matches {key!r}")
    return matches[0]


def _date_of(stamp: str) -> str:
    return (stamp or "")[:10]


def _show_thread(screen: Screen, name: str, lines: list[dict], me: str) -> None:
    """A conversation as a terminal prints one: a rule per day, a name per run."""
    quillrun.out.print(f"[{TITLE}]{escape(name)}[/]")
    if not lines:
        quillrun.out.print("[dim]Nothing said here yet.[/]")
        return
    body = screen.spec["body"]
    day = author = ""
    for line in lines:
        if _date_of(line["created_at"]) != day:
            day = _date_of(line["created_at"])
            author = ""
            quillrun.out.print(f"[dim]── {day} ──[/]")
        if line["owner"] != author:
            author = line["owner"]
            who = "you" if author == me else author
            quillrun.out.print(f"[bold]{escape(who)}[/] [dim]{line['created_at'][11:16]}[/]")
        edited = " [dim](edited)[/]" if line.get("updated_at") != line.get("created_at") else ""
        for text in str(line["fields"].get(body) or "").splitlines() or [""]:
            quillrun.out.print(f"  {escape(text)}{edited}")
            edited = ""


async def _thread(api: CloudmorrowClient, screen: Screen, action: str, args: list[str], plain: bool) -> None:
    link = screen.fields[screen.spec["space"]]
    space_model = link["to"]
    me = str((await api.me()).get("username", ""))
    spaces = await api.records(space_model)
    if action == "list":
        if plain:
            quillrun.emit(json.dumps(spaces, indent=2) + "\n")
            return
        table = Table(title=screen.spec.get("label") or screen.quill["name"], title_style=TITLE)
        table.add_column("id", style="dim")
        table.add_column(screen.models[space_model]["label"])
        table.add_column("new", justify="right")
        table.add_column("last")
        ordered = sorted(spaces, key=lambda s: (s.get("last") or {}).get("created_at") or s["created_at"],
                         reverse=True)
        for space in ordered:
            last = space.get("last") or {}
            said = f"{last.get('owner', '')}: {last.get('title', '')}" if last else ""
            unread = space.get("unread") or 0
            table.add_row(
                space["id"][2:6],
                f"[bold]{escape(space_name(space, me, screen))}[/]" if unread else escape(space_name(space, me, screen)),
                f"[bold]{unread}[/]" if unread else "",
                escape(said[:60]),
            )
        quillrun.out.print(table)
        return
    if action not in ("show", "say"):
        fail(f"a {screen.kit} is list, show and say")
    if not args:
        fail(f"which one? cm {screen.quill['id']} {action} <{space_model}>")
    space = _find_space(spaces, args[0], me, screen)
    if action == "say":
        text = " ".join(args[1:]).strip()
        if not text:
            fail(f'say what? cm {screen.quill["id"]} say {args[0]} "<words>"')
        await api.create_record(screen.model, {link["name"]: space["id"], screen.spec["body"]: text})
        quillrun.console.print(f"[green]Said[/] in {escape(space_name(space, me, screen))}")
        return
    lines = await api.records(screen.model, last=PAGE, **{link["name"]: space["id"]})
    await api.mark_seen(space_model, space["id"])
    if plain:
        quillrun.emit(json.dumps(lines, indent=2) + "\n")
        return
    _show_thread(screen, space_name(space, me, screen), lines, me)
