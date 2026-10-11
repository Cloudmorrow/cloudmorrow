"""A `thread`: spaces, and what is said in them.

    cm <quill> list                          the spaces, with what is unread
    cm <quill> show <space>                  the conversation, newest at the bottom
    cm <quill> say <space> "words"
    cm <quill> show <space> --thread <line>  one line and its replies   (a screen with reply_to)
    cm <quill> reply <space> <line> "words"                              (reply_to)
    cm <quill> react <space> <line> 👍        yours again takes it back  (reactions)
    cm <quill> pin <space> <line>            or unpin                     (pinned)

A line is named by the start of its id, as `show` prints it in the margin.
"""

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
from cloudmorrow.quill import screens

# How much of a conversation `show` prints.
PAGE = 50


def space_name(space: dict, me: str, screen: Screen) -> str:
    """What a space is called to *me*: its title, or, made between people, who else is in it."""
    target = screen.models[screen.fields[screen.spec["space"]]["to"]]
    return screens.space_name(space, target["title"], screen.spec, me)


def _find_space(spaces: list[dict], key: str, me: str, screen: Screen) -> dict:
    """A space by its id (or the start of it), its name, or the person it is with."""
    wanted = key.lstrip("#")
    by_id = [s for s in spaces if s["id"].startswith(wanted if wanted.startswith("r_") else f"r_{wanted}")]
    named = [s for s in spaces if space_name(s, me, screen).casefold() == wanted.casefold()]
    matches = named or by_id
    if len(matches) != 1:
        fail(f"{'no' if not matches else 'more than one'} {screen.fields[screen.spec['space']]['to']} matches {key!r}")
    return matches[0]


def _date_of(stamp: str) -> str:
    return (stamp or "")[:10]


def _find_line(lines: list[dict], key: str, screen: Screen) -> dict:
    """A line by its id, or the start of it."""
    wanted = key if key.startswith("r_") else f"r_{key}"
    matches = [line for line in lines if line["id"].startswith(wanted)]
    if len(matches) != 1:
        fail(f"{'no' if not matches else 'more than one'} {screen.model} matches {key!r}")
    return matches[0]


def _tally(reactions: list[dict], link: str, me: str) -> dict[str, str]:
    """Each line's reactions in a word: 👍 2 ❤️ 1, yours marked."""
    rows: dict[str, dict[str, list]] = {}
    for r in reactions:
        line, emoji = str(r["fields"].get(link) or ""), str(r["fields"].get("emoji") or "")
        if line and emoji:
            cell = rows.setdefault(line, {}).setdefault(emoji, [0, False])
            cell[0] += 1
            cell[1] = cell[1] or r.get("owner") == me
    return {
        line: "  ".join(f"{emoji} {n}{'*' if mine else ''}" for emoji, (n, mine) in cells.items())
        for line, cells in rows.items()
    }


def _show_thread(
    screen: Screen,
    name: str,
    lines: list[dict],
    me: str,
    *,
    reactions: dict[str, str] | None = None,
    thread: bool = False,
) -> None:
    """A conversation as a terminal prints one: a rule per day, a name per run.

    With a `reply_to` on the screen, a reply is printed under its parent,
    indented; the margin carries the start of each line's id, which `reply`,
    `react` and `pin` take.
    """
    quillrun.out.print(f"[{TITLE}]{escape(name)}[/]")
    if not lines:
        quillrun.out.print("[dim]Nothing said here yet.[/]")
        return
    body = screen.spec["body"]
    reply_to = screen.spec.get("reply_to") or ""
    pinned = screen.spec.get("pinned") or ""
    team = bool(reply_to or pinned or reactions is not None or screen.spec.get("mentions"))
    replies: dict[str, list[dict]] = {}
    tops = lines
    if reply_to and not thread:
        tops = [line for line in lines if not line["fields"].get(reply_to)]
        shown = {line["id"] for line in tops}
        for line in lines:
            parent = line["fields"].get(reply_to)
            if parent and parent in shown:
                replies.setdefault(parent, []).append(line)
            elif parent:
                tops.append(line)
        tops.sort(key=lambda line: line["created_at"])

    def words(line: dict, indent: str) -> None:
        edited = " [dim](edited)[/]" if line.get("updated_at") != line.get("created_at") else ""
        mark = "[yellow]📌[/] " if pinned and line["fields"].get(pinned) else ""
        margin = f"[dim]{line['id'][2:6]}[/] " if team else ""
        for text in str(line["fields"].get(body) or "").splitlines() or [""]:
            quillrun.out.print(f"{margin}{indent}{mark}{escape(text)}{edited}")
            edited = mark = ""
            margin = "     " if team else ""
        if reactions and line["id"] in reactions:
            quillrun.out.print(f"{'     ' if team else ''}{indent}[dim]{reactions[line['id']]}[/]")

    day = author = ""
    for line in tops:
        if _date_of(line["created_at"]) != day:
            day = _date_of(line["created_at"])
            author = ""
            quillrun.out.print(f"[dim]── {day} ──[/]")
        if line["owner"] != author:
            author = line["owner"]
            who = "you" if author == me else author
            quillrun.out.print(f"{'     ' if team else ''}[bold]{escape(who)}[/] [dim]{line['created_at'][11:16]}[/]")
        words(line, "  ")
        for reply in replies.get(line["id"], []):
            who = "you" if reply["owner"] == me else reply["owner"]
            at = reply["created_at"][11:16]
            quillrun.out.print(f"{'     ' if team else ''}    [dim]↳[/] [bold]{escape(who)}[/] [dim]{at}[/]")
            words(reply, "      ")
            author = ""


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
        ordered = sorted(spaces, key=lambda s: (s.get("last") or {}).get("created_at") or s["created_at"], reverse=True)
        for space in ordered:
            last = space.get("last") or {}
            said = f"{last.get('owner', '')}: {last.get('title', '')}" if last else ""
            unread = space.get("unread") or 0
            table.add_row(
                space["id"][2:6],
                f"[bold]{escape(space_name(space, me, screen))}[/]"
                if unread
                else escape(space_name(space, me, screen)),
                f"[bold]{unread}[/]" if unread else "",
                escape(said[:60]),
            )
        quillrun.out.print(table)
        return
    reply_to = screen.spec.get("reply_to") or ""
    pinned = screen.spec.get("pinned") or ""
    reactions_model = screen.spec.get("reactions") or ""
    does = ["list", "show", "say"] + (["reply"] if reply_to else []) + (["react"] if reactions_model else []) + (
        ["pin"] if pinned else []
    )
    if action not in does:
        fail(f"a {screen.kit} is {', '.join(does)}")
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
    if action in ("reply", "react", "pin"):
        if len(args) < 2:
            fail(f"which line? cm {screen.quill['id']} {action} {args[0]} <line>")
        lines = await api.records(screen.model, **{link["name"]: space["id"]})
        line = _find_line(lines, args[1], screen)
        if action == "reply":
            text = " ".join(args[2:]).strip()
            if not text:
                fail(f'reply what? cm {screen.quill["id"]} reply {args[0]} {args[1]} "<words>"')
            parent = line["fields"].get(reply_to) or line["id"]
            await api.create_record(
                screen.model, {link["name"]: space["id"], screen.spec["body"]: text, reply_to: parent}
            )
            where = escape(space_name(space, me, screen))
            quillrun.console.print(f"[green]Replied[/] to {escape(line['owner'])} in {where}")
            return
        if action == "pin":
            now = not line["fields"].get(pinned)
            await api.update_record(screen.model, line["id"], {pinned: now})
            quillrun.console.print(f"[green]{'Pinned' if now else 'Unpinned'}[/] {escape(line['owner'])}'s line")
            return
        emoji = " ".join(args[2:]).strip()
        if not emoji:
            fail(f"react with what? cm {screen.quill['id']} react {args[0]} {args[1]} 👍")
        model = screen.models[reactions_model]
        to_line = next(f["name"] for f in model["fields"] if f.get("kind") == "link" and f.get("to") == screen.model)
        mine = [
            r
            for r in await api.records(reactions_model, **{model["in_space"]: space["id"]})
            if r["owner"] == me and r["fields"].get(to_line) == line["id"] and r["fields"].get("emoji") == emoji
        ]
        if mine:
            await api.delete_record(reactions_model, mine[0]["id"])
            quillrun.console.print(f"[green]Took back[/] {emoji}")
        else:
            await api.create_record(
                reactions_model, {model["in_space"]: space["id"], to_line: line["id"], "emoji": emoji}
            )
            quillrun.console.print(f"[green]Reacted[/] {emoji}")
        return
    # show: the conversation, or one line's thread.
    thread_of = ""
    rest = list(args[1:])
    if "--thread" in rest:
        at = rest.index("--thread")
        if not reply_to:
            fail(f"{screen.spec['id']} has no threads")
        if at + 1 >= len(rest):
            fail(f"which line? cm {screen.quill['id']} show {args[0]} --thread <line>")
        thread_of = rest[at + 1]
    if thread_of:
        everything = await api.records(screen.model, **{link["name"]: space["id"]})
        parent = _find_line(everything, thread_of, screen)
        parent = _find_line(everything, parent["fields"].get(reply_to) or parent["id"], screen)
        lines = [parent] + [line for line in everything if line["fields"].get(reply_to) == parent["id"]]
    else:
        lines = await api.records(screen.model, last=PAGE, **{link["name"]: space["id"]})
    await api.mark_seen(space_model, space["id"])
    if plain:
        quillrun.emit(json.dumps(lines, indent=2) + "\n")
        return
    tally = None
    if reactions_model:
        model = screen.models[reactions_model]
        to_line = next(f["name"] for f in model["fields"] if f.get("kind") == "link" and f.get("to") == screen.model)
        tally = _tally(await api.records(reactions_model, **{model["in_space"]: space["id"]}), to_line, me)
    title = space_name(space, me, screen) + (f" · thread of {thread_of}" if thread_of else "")
    _show_thread(screen, title, lines, me, reactions=tally, thread=bool(thread_of))
