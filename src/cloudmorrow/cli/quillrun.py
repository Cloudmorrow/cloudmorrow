"""`cloudmorrow <quill> ACTION` — every installed Quill, on the command line.

The command-line surface of the kit. Nobody writes it per Quill: the words
come from the Quill's first screen (or `--screen`) and its datamodel.

    cm tasks list                      # the board, lane by lane
    cm tasks add "Repot the fig"       # into the first lane
    cm tasks move 8f2c doing           # a record by the start of its id
    cm tasks done 8f2c
    cm tasks show 8f2c
    cm tasks set 8f2c due=2026-10-01
    cm tasks delete 8f2c
    cm tasks groups                    # the boards, for a board with groups
    cm tasks list --group Garden       # another board, by name or id

A `calendar` screen lists a range of days, and adds with its two moments:

    cm calendar list --from 2026-10-01 --to 2026-10-31
    cm calendar add "Dentist" starts=2026-10-01T10:00 ends=2026-10-01T11:00
    cm calendar add "Holiday" starts=2026-10-12 ends=2026-10-16 calendar=House

A field may be named by what the screen binds it as (`starts=` for the
calendar's `starts_at`), and a link field (`calendar=House`) takes the
linked record's name or id.

An `editor` screen is pages of Markdown, found by their path:

    cm notes list                      # every page, folders and all
    cm notes show ideas/garden         # the Markdown, as it is: pipe it on
    cm notes add ideas/garden          # from stdin, or $EDITOR
    cm notes edit ideas/garden         # $EDITOR, or the new text from stdin
    cm notes search tomatoes           # names and every line
A `grid` (files) takes its group and folder as words instead:

    cm files list                      # the groups: My Files, the shares
    cm files list my-files Photos      # a folder in one
    cm files get my-files Photos/cat.jpg [out]
    cm files put my-files Photos ./dog.jpg [more…]
    cm files add my-files Photos/2026  # a new folder
    cm files delete my-files Photos/old.jpg
A `thread` screen is spaces and what is said in them:

    cm chat list                       # the channels, with what is unread
    cm chat show general               # the conversation, newest at the bottom
    cm chat say general "on my way"    # a channel by name, id, or the person

`main` sends a first word that is not one of the built-in commands here, so
`cm tasks` works without the CLI knowing, when it starts, what is installed.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape
from rich.table import Table

from cloudmorrow.cli.common import (
    client,
    console,
    edit_text,
    emit,
    fail,
    out,
    run,
    stdin_is_a_terminal,
)
from cloudmorrow.client.api import ApiError, CloudmorrowClient
from cloudmorrow.console import TITLE

ACTIONS = (
    "list", "add", "show", "set", "move", "done", "undone", "delete", "groups", "get", "put",
    "edit", "search", "say",
)
# How much of a conversation `show` prints.
PAGE = 50


def route(argv: list[str], commands: set[str]) -> list[str]:
    """`tasks list` → `run-quill tasks list`, when `tasks` is not a command of ours."""
    if argv and not argv[0].startswith("-") and argv[0] not in commands:
        return ["run-quill", *argv]
    return argv


class Screen:
    """One Quill screen and the datamodels it needs, with the questions a command asks."""

    def __init__(self, quill: dict, screen: dict) -> None:
        self.quill = quill
        self.spec = screen
        self.models = quill["models"]
        self.model = screen["model"]
        self.fields = {f["name"]: f for f in self.models[self.model]["fields"]}
        self.title = screen.get("title") or self.models[self.model]["title"]
        self.kit = screen["kit"]

    @property
    def lane(self) -> dict | None:
        return self.fields.get(self.spec.get("lane", "")) if self.kit == "board" else None

    @property
    def group(self) -> dict | None:
        return self.fields.get(self.spec.get("group", "")) if self.spec.get("group") else None

    @property
    def moments(self) -> tuple[str, str] | None:
        """A calendar's two moment fields, which a list asks for a range of."""
        if self.kit != "calendar":
            return None
        return self.spec["starts"], self.spec["ends"]

    def group_title(self, record: dict) -> str:
        target = self.models[self.group["to"]]
        return str(record["fields"].get(target["title"], record["id"]))


def _screen(quills: list[dict], quill_id: str, screen_id: str) -> Screen:
    quill = next((q for q in quills if q["id"] == quill_id), None)
    if quill is None:
        names = ", ".join(sorted(q["id"] for q in quills)) or "none"
        fail(f"'{quill_id}' is not a command, nor an installed Quill (installed: {names})")
    if not quill["screens"]:
        fail(f"{quill_id} has no screens")
    screen = quill["screens"][0]
    if screen_id:
        screen = next((s for s in quill["screens"] if s["id"] == screen_id), None)
        if screen is None:
            fail(
                f"{quill_id} has no screen {screen_id!r}: {', '.join(s['id'] for s in quill['screens'])}"
            )
    return Screen(quill, screen)


def _pairs(values: list[str], screen: Screen) -> dict:
    fields: dict = {}
    for pair in values:
        name, sep, value = pair.partition("=")
        if not sep:
            fail(f"{pair!r}: set fields as name=value")
        # What the screen calls a field is a name for it too: a calendar's
        # `starts=` is whichever field its screen binds as the start.
        bound = screen.spec.get(name)
        if name not in screen.fields and isinstance(bound, str) and bound in screen.fields:
            name = bound
        if name not in screen.fields:
            fail(f"{screen.model} has no field {name!r}: {', '.join(screen.fields)}")
        kind = screen.fields[name]["kind"]
        if kind == "json":
            try:
                fields[name] = json.loads(value)
            except ValueError:
                fail(f"{name} is JSON")
        else:
            fields[name] = value
    return fields


def _find(records: list[dict], key: str, title: str) -> dict:
    """A record by its id, the start of its id (with or without `r_`), or its exact title."""
    wanted = key if key.startswith("r_") else f"r_{key}"
    matches = [r for r in records if r["id"].startswith(wanted)]
    if not matches:
        matches = [
            r for r in records if str(r["fields"].get(title, "")).casefold() == key.casefold()
        ]
    if len(matches) != 1:
        fail(f"{'no record' if not matches else 'more than one record'} matches {key!r}")
    return matches[0]


async def _group_id(
    api: CloudmorrowClient, screen: Screen, wanted: str
) -> tuple[str | None, list[dict]]:
    """The group a board command is about: named, or the first there is."""
    if screen.group is None:
        return None, []
    groups = await api.records(screen.group["to"])
    if not groups:
        fail(f"there is no {screen.group['to']} yet")
    if not wanted:
        return groups[0]["id"], groups
    return _find(groups, wanted, screen.models[screen.group["to"]]["title"])["id"], groups


def _show_board(screen: Screen, records: list[dict], heading: str) -> None:
    lane = screen.lane
    labels = dict(zip(lane["values"], lane.get("labels") or lane["values"], strict=True))
    table = Table(title=heading, title_style=TITLE)
    for value in lane["values"]:
        table.add_column(labels[value])
    columns = [
        [r for r in records if r["fields"].get(lane["name"]) == value] for value in lane["values"]
    ]
    for row in range(max((len(c) for c in columns), default=0)):
        cells = []
        for column in columns:
            if row < len(column):
                record = column[row]
                left = ""
                if record.get("expires_at"):
                    left = f" [dim](goes {record['expires_at'][:10]})[/]"
                cells.append(
                    f"{escape(str(record['fields'].get(screen.title, '')))} [dim]{record['id'][2:6]}[/]{left}"
                )
            else:
                cells.append("")
        table.add_row(*cells)
    out.print(table)


def _show_list(screen: Screen, records: list[dict], heading: str) -> None:
    table = Table(title=heading, title_style=TITLE)
    tick = screen.spec.get("tick")
    if tick:
        table.add_column("")
    table.add_column("id", style="dim")
    table.add_column(screen.fields[screen.title].get("label", screen.title))
    subtitle = screen.spec.get("subtitle")
    if subtitle:
        table.add_column(screen.fields[subtitle].get("label", subtitle))
    for record in records:
        row = []
        if tick:
            row.append("●" if record["fields"].get(tick) else "○")
        row += [record["id"][2:6], escape(str(record["fields"].get(screen.title, "")))]
        if subtitle:
            row.append(escape(str(record["fields"].get(subtitle) or "")))
        table.add_row(*row)
    out.print(table)


def _day(value: str, what: str) -> str:
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        fail(f"{what} is a date, as 2026-10-01")
    return ""


async def _link_values(api: CloudmorrowClient, screen: Screen, fields: dict) -> dict:
    """A link given by the linked record's name, made its id."""
    for name, value in list(fields.items()):
        field = screen.fields[name]
        if field["kind"] != "link" or not value or str(value).startswith("r_"):
            continue
        target = screen.models.get(field["to"]) or {"title": "title"}
        fields[name] = _find(await api.records(field["to"]), str(value), target["title"])["id"]
    return fields


def _event_defaults(screen: Screen, fields: dict, spaces: list[dict]) -> dict:
    """What a calendar's add fills in: the end, whole days, and your own space."""
    starts, ends = screen.moments
    all_day = screen.spec.get("all_day")
    space = screen.spec.get("space")
    start = str(fields.get(starts) or "")
    if not start:
        fail(f"when? {starts}=2026-10-01T10:00, or a date for the whole day")
    if all_day and all_day not in fields:
        fields[all_day] = len(start) == 10
    if not fields.get(ends):
        # Something with no end is an hour long, or the day it is on.
        if len(start) == 10:
            fields[ends] = start
        else:
            moment = dt.datetime.fromisoformat(start) + dt.timedelta(hours=1)
            fields[ends] = moment.strftime("%Y-%m-%dT%H:%M")
    if space and not fields.get(space):
        mine = next((s for s in spaces if s.get("scope") == "personal"), None) or (
            spaces[0] if spaces else None
        )
        if mine is None:
            fail(f"there is nothing to put it in: {space}=<name>")
        fields[space] = mine["id"]
    return fields


def _show_calendar(screen: Screen, records: list[dict], spaces: list[dict], heading: str) -> None:
    starts, ends = screen.moments
    space_field = screen.spec.get("space")
    space_model = screen.models[screen.fields[space_field]["to"]] if space_field else None
    names = {s["id"]: str(s["fields"].get(space_model["title"], "")) for s in spaces} if space_model else {}
    table = Table(title=heading, title_style=TITLE)
    table.add_column("day")
    table.add_column("when")
    table.add_column("id", style="dim")
    table.add_column(screen.fields[screen.title].get("label", screen.title))
    if space_model:
        table.add_column(space_model["label"])
    for record in sorted(records, key=lambda r: str(r["fields"].get(starts) or "")):
        start = str(record["fields"].get(starts) or "")
        end = str(record["fields"].get(ends) or start)
        if len(start) == 10:
            when = "all day" if end[:10] == start else f"to {end[:10]}"
        else:
            when = f"{start[11:16]}–{end[11:16]}" if end[:10] == start[:10] else f"{start[11:16]} → {end[:16]}"
        row = [start[:10], when, record["id"][2:6], escape(str(record["fields"].get(screen.title, "")))]
        if space_model:
            row.append(escape(names.get(record["fields"].get(space_field), "")))
        table.add_row(*row)
    out.print(table)


def _show_record(screen: Screen, record: dict) -> None:
    table = Table(
        title=f"{screen.models[screen.model]['label']} {record['id']}",
        title_style=TITLE,
        show_header=False,
    )
    table.add_column("field", style="dim")
    table.add_column("value")
    for name, field in screen.fields.items():
        value = record["fields"].get(name)
        if field["kind"] == "enum" and value in field.get("values", []):
            value = (field.get("labels") or field["values"])[field["values"].index(value)]
        table.add_row(field.get("label", name), escape("" if value is None else str(value)))
    table.add_row("rev", str(record["rev"]))
    out.print(table)


def main(
    quill: Annotated[str, typer.Argument(help="The Quill's id.")],
    action: Annotated[str, typer.Argument(help=" | ".join(ACTIONS))] = "list",
    args: Annotated[list[str] | None, typer.Argument(help="What the action needs.")] = None,
    screen_id: Annotated[
        str, typer.Option("--screen", help="Another of the Quill's screens.")
    ] = "",
    group: Annotated[
        str, typer.Option("--group", "-g", help="Which board (or other group), by name or id.")
    ] = "",
    index: Annotated[
        int | None, typer.Option("--index", help="Where in the lane, 0 for the top.")
    ] = None,
    plain: Annotated[bool, typer.Option("--plain", help="JSON, for scripts.")] = False,
    first: Annotated[
        str, typer.Option("--from", help="A calendar: the first day, as 2026-10-01 (today).")
    ] = "",
    last: Annotated[
        str, typer.Option("--to", help="A calendar: the last day (a week after --from).")
    ] = "",
) -> None:
    """Run ACTION on an installed Quill."""
    args = list(args or [])
    if action not in ACTIONS:
        fail(f"{action!r}: the actions are {', '.join(ACTIONS)}")

    async def _run() -> None:
        _, api = client()
        try:
            screen = _screen(await api.quills(), quill, screen_id)
            await _act(api, screen, action, args, group, index, plain, (first, last))
        finally:
            await api.aclose()

    run(_run())


async def _act(
    api: CloudmorrowClient,
    screen: Screen,
    action: str,
    args: list[str],
    group: str,
    index: int | None,
    plain: bool,
    days: tuple[str, str] = ("", ""),
) -> None:
    if screen.kit == "editor":
        await _act_editor(api, screen, action, args, plain)
        return
    if screen.kit == "grid":
        await _act_grid(api, screen, action, args, plain)
        return
    if screen.kit == "thread":
        await _thread(api, screen, action, args, plain)
        return
    if action == "say":
        fail(f"{screen.quill['id']} is not a conversation; say is for a thread")
    if action in ("edit", "search"):
        fail(f"{action} is for an editor; {screen.quill['id']} is a {screen.kit}")
    group_id, groups = await _group_id(api, screen, group)
    where = {screen.group["name"]: group_id} if group_id else {}
    spaces: list[dict] = []
    if screen.moments:
        # A calendar lists a range of days, across every space it can see.
        start = _day(days[0], "--from") if days[0] else dt.date.today().isoformat()
        end = _day(days[1], "--to") if days[1] else (
            dt.date.fromisoformat(start) + dt.timedelta(days=6)
        ).isoformat()
        if end < start:
            fail("--to is before --from")
        where = {f"{screen.moments[0]}__lte": f"{end}T23:59", f"{screen.moments[1]}__gte": start}
        if screen.spec.get("space"):
            spaces = await api.records(screen.fields[screen.spec["space"]]["to"])

    if action == "groups":
        if screen.group is None:
            fail(f"{screen.quill['id']} has no groups")
        if plain:
            emit(json.dumps(groups, indent=2) + "\n")
            return
        for record in groups:
            out.print(f"{record['id'][2:6]}  {escape(screen.group_title(record))}")
        return

    records = await api.records(screen.model, **where)
    if action == "list":
        if plain:
            emit(json.dumps(records, indent=2) + "\n")
            return
        heading = screen.spec.get("label") or screen.quill["name"]
        if group_id:
            heading += f" · {screen.group_title(next(g for g in groups if g['id'] == group_id))}"
        if screen.kit == "board":
            _show_board(screen, records, heading)
        elif screen.moments:
            _show_calendar(screen, records, spaces, f"{heading} · {start} to {end}")
        else:
            _show_list(screen, records, heading)
        return

    if action == "add":
        if not args:
            fail(f'add what? cm {screen.quill["id"]} add "<{screen.title}>" [name=value …]')
        if screen.moments:
            fields = await _link_values(api, screen, {screen.title: args[0], **_pairs(args[1:], screen)})
            fields = _event_defaults(screen, fields, spaces)
        else:
            fields = {screen.title: args[0], **_pairs(args[1:], screen), **where}
        try:
            made = await api.create_record(screen.model, fields, index=index)
        except ApiError as exc:
            fail(str(exc))
        console.print(f"[green]Added[/] {escape(args[0])} [dim]{made['id'][2:6]}[/]")
        return

    if not args:
        fail(f"which one? cm {screen.quill['id']} {action} <id>")
    if screen.moments:
        # A record is found by id or title among all of them, not only this week's.
        records = await api.records(screen.model)
    record = _find(records if records else await api.records(screen.model), args[0], screen.title)
    rest = args[1:]
    try:
        if action == "show":
            if plain:
                emit(json.dumps(record, indent=2) + "\n")
            else:
                _show_record(screen, record)
        elif action == "set":
            changed = await api.update_record(
                screen.model, record["id"], await _link_values(api, screen, _pairs(rest, screen)),
                rev=record["rev"],
            )
            console.print(f"[green]Saved[/] {escape(str(changed['fields'].get(screen.title, '')))}")
        elif action == "move":
            if screen.lane is None or not rest:
                fail(
                    f"move takes a lane: {', '.join(screen.lane['values']) if screen.lane else 'this is not a board'}"
                )
            await api.move_record(screen.model, record["id"], {screen.lane["name"]: rest[0]}, index)
            console.print(f"[green]Moved[/] to {rest[0]}")
        elif action in ("done", "undone"):
            if screen.lane is not None:
                target = screen.spec.get("done") or screen.lane["values"][-1]
                lane = target if action == "done" else screen.lane["values"][0]
                await api.move_record(screen.model, record["id"], {screen.lane["name"]: lane}, None)
            elif screen.spec.get("tick"):
                await api.update_record(
                    screen.model, record["id"], {screen.spec["tick"]: action == "done"}
                )
            else:
                fail(f"{screen.quill['id']} has nothing to tick")
            console.print(f"[green]{'Done' if action == 'done' else 'Not done'}[/]")
        elif action == "delete":
            await api.delete_record(screen.model, record["id"])
            console.print(
                f"[green]Deleted[/] {escape(str(record['fields'].get(screen.title, '')))}"
            )
    except ApiError as exc:
        fail(str(exc))


# -- an editor: pages of Markdown, by path ------------------------------------------------
def _page_key(screen: Screen, record: dict) -> str:
    """What a page is called on the command line: its path, else its title."""
    fields = record["fields"]
    return str(fields.get(screen.spec.get("path") or screen.title) or fields.get(screen.title) or "")


def _find_page(screen: Screen, records: list[dict], key: str) -> dict:
    """A page by its path, its title, or its id — whole, or the start of one."""
    wanted = key.strip().strip("/").removesuffix(".md")
    for test in (
        lambda r: _page_key(screen, r) == wanted,
        lambda r: r["id"] == key,
        lambda r: _page_key(screen, r).casefold() == wanted.casefold(),
        lambda r: str(r["fields"].get(screen.title, "")).casefold() == wanted.casefold(),
    ):
        matches = [r for r in records if test(r)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            fail(f"more than one page matches {key!r}: {', '.join(_page_key(screen, r) for r in matches)}")
    fail(f"no page matches {key!r}")


def _text(initial: str, *, what: str) -> str:
    """The new text: what is piped in, else what $EDITOR saves."""
    if not stdin_is_a_terminal():
        return sys.stdin.read()
    text = edit_text(initial)
    if not text.strip():
        fail(f"{what} is empty — nothing was saved")
    return text


async def _act_editor(
    api: CloudmorrowClient, screen: Screen, action: str, args: list[str], plain: bool
) -> None:
    body = screen.spec.get("body") or "body"
    path = screen.spec.get("path")
    if action == "search":
        if not args:
            fail(f"search for what? cm {screen.quill['id']} search <text>")
        found = await api.records(screen.model, q=" ".join(args))
        if plain:
            emit(json.dumps(found, indent=2) + "\n")
            return
        for record in found:
            line = record.get("preview") or ""
            out.print(f"{escape(_page_key(screen, record))}  [dim]{escape(line)}[/]")
        if not found:
            console.print("[dim]nothing matches[/]")
        return
    records = await api.records(screen.model)
    if action == "list":
        if plain:
            emit(json.dumps(records, indent=2) + "\n")
            return
        table = Table(title=screen.spec.get("label") or screen.quill["name"], title_style=TITLE)
        table.add_column(screen.fields[path]["label"] if path else screen.fields[screen.title].get("label", "Title"))
        stamp = next((n for n, f in screen.fields.items() if f["kind"] == "datetime"), None)
        if stamp:
            table.add_column(screen.fields[stamp].get("label", stamp), style="dim")
        for record in sorted(records, key=lambda r: _page_key(screen, r).casefold()):
            row = [escape(_page_key(screen, record))]
            if stamp:
                row.append(str(record["fields"].get(stamp) or "")[:16].replace("T", " "))
            table.add_row(*row)
        out.print(table)
        return
    if not args:
        fail(f"which page? cm {screen.quill['id']} {action} <path>")
    try:
        if action == "add":
            if any(_page_key(screen, r) == args[0].strip("/") for r in records):
                fail(f"there is already a page {args[0]!r}; edit it instead")
            text = " ".join(args[1:]) if len(args) > 1 else _text("", what="the page")
            fields = {(path or screen.title): args[0].strip("/"), body: text}
            made = await api.create_record(screen.model, fields)
            console.print(f"[green]Added[/] {escape(_page_key(screen, made))}")
            return
        found = await api.record(screen.model, _find_page(screen, records, args[0])["id"])
        if action == "show":
            emit(json.dumps(found, indent=2) + "\n" if plain else str(found["fields"].get(body) or ""))
        elif action == "edit":
            before = str(found["fields"].get(body) or "")
            text = " ".join(args[1:]) if len(args) > 1 else _text(before, what="the page")
            if text == before:
                console.print("[dim]unchanged[/]")
                return
            try:
                await api.update_record(screen.model, found["id"], {body: text}, rev=found["rev"])
            except ApiError as exc:
                if exc.status_code == 409:
                    fail("it changed somewhere else while you were editing; nothing was saved")
                raise
            console.print(f"[green]Saved[/] {escape(_page_key(screen, found))}")
        elif action == "delete":
            await api.delete_record(screen.model, found["id"])
            console.print(f"[green]Deleted[/] {escape(_page_key(screen, found))}")
        elif action == "set":
            changed = await api.update_record(
                screen.model, found["id"], _pairs(args[1:], screen), rev=found["rev"]
            )
            console.print(f"[green]Saved[/] {escape(_page_key(screen, changed))}")
        else:
            fail(f"an editor has list, show, add, edit, set, delete and search, not {action}")
    except ApiError as exc:
        fail(str(exc))


# -- a grid: groups, folders, and the bytes of what is in them ---------------------
def _size(value: object) -> str:
    size = int(value or 0)
    if size < 1024:
        return f"{size} B"
    number = size / 1024
    for unit in ("KB", "MB", "GB", "TB"):
        if number < 1024 or unit == "TB":
            return f"{number:.0f} {unit}" if number >= 10 else f"{number:.1f} {unit}"
        number /= 1024
    return f"{number:.1f} TB"


class _Grid:
    """What a grid screen binds, read once."""

    def __init__(self, screen: Screen) -> None:
        spec = screen.spec
        self.screen = screen
        self.group = spec["group"]
        self.group_model = screen.models[screen.fields[self.group]["to"]]
        self.folder = spec["folder"]
        self.kind = spec["kind"]
        self.name = screen.title
        self.size = spec.get("size") or ""
        self.modified = spec.get("modified") or ""
        self.subtitle = spec.get("group_subtitle") or ""

    def where(self, group: str, folder: str) -> dict:
        return {self.group: group, self.folder: folder.strip("/")}


async def _entry(api: CloudmorrowClient, grid: _Grid, group: str, path: str) -> dict:
    folder, _, name = path.strip("/").rpartition("/")
    found = await api.records(grid.screen.model, **grid.where(group, folder))
    for record in found:
        if record["fields"].get(grid.name) == name:
            return record
    fail(f"there is nothing called {path!r} in {group}")


async def _act_grid(
    api: CloudmorrowClient, screen: Screen, action: str, args: list[str], plain: bool
) -> None:
    grid = _Grid(screen)
    command = f"cm {screen.quill['id']}"
    try:
        if action in ("list", "groups") and not args:
            groups = await api.records(grid.group_model["id"])
            if plain:
                emit(json.dumps(groups, indent=2) + "\n")
                return
            table = Table(title=screen.spec.get("label") or screen.quill["name"], title_style=TITLE)
            table.add_column("id", style="dim")
            table.add_column(grid.group_model["label"])
            if grid.subtitle:
                table.add_column("")
            for record in groups:
                row = [record["id"], escape(str(record["fields"].get(grid.group_model["title"], "")))]
                if grid.subtitle:
                    row.append(escape(str(record["fields"].get(grid.subtitle) or "")))
                table.add_row(*row)
            out.print(table)
            return
        if not args:
            fail(f"which {grid.group_model['label'].lower()}? {command} {action} <id> …")
        group, rest = args[0], args[1:]
        if action == "list":
            folder = rest[0] if rest else ""
            found = await api.records(screen.model, **grid.where(group, folder))
            if plain:
                emit(json.dumps(found, indent=2) + "\n")
                return
            table = Table(title=f"{group}/{folder.strip('/')}", title_style=TITLE)
            for column in ("name", "size", "modified"):
                table.add_column(column)
            folders = [r for r in found if r["fields"].get(grid.kind) == "folder"]
            others = [r for r in found if r["fields"].get(grid.kind) != "folder"]
            for record in sorted(folders, key=lambda r: str(r["fields"].get(grid.name, "")).casefold()) + \
                    sorted(others, key=lambda r: str(r["fields"].get(grid.name, "")).casefold()):
                fields = record["fields"]
                is_dir = fields.get(grid.kind) == "folder"
                table.add_row(
                    escape(str(fields.get(grid.name, ""))) + ("/" if is_dir else ""),
                    "" if is_dir or not grid.size else _size(fields.get(grid.size)),
                    str(fields.get(grid.modified) or "")[:16].replace("T", " ") if grid.modified else "",
                )
            out.print(table)
        elif action == "get":
            if not rest:
                fail(f"get what? {command} get {group} <path> [out]")
            record = await _entry(api, grid, group, rest[0])
            data = await api.record_content(screen.model, record["id"])
            target = rest[1] if len(rest) > 1 else str(record["fields"].get(grid.name))
            if target == "-":
                import sys

                sys.stdout.buffer.write(data)
                return
            path = Path(target).expanduser()
            if path.is_dir():
                path = path / str(record["fields"].get(grid.name))
            if path.exists():
                fail(f"{path} is there already")
            path.write_bytes(data)
            console.print(f"[green]Saved[/] {escape(str(path))} [dim]{_size(len(data))}[/]")
        elif action == "put":
            if len(rest) < 2:
                fail(f"put what, where? {command} put {group} <folder> <file> [file…]")
            folder, files = rest[0], rest[1:]
            for name in files:
                source = Path(name).expanduser()
                if not source.is_file():
                    fail(f"there is no file at {source}")
                made = await api.upload_record(
                    screen.model, {**grid.where(group, folder), grid.name: source.name},
                    source.read_bytes(),
                )
                console.print(f"[green]Put[/] {escape(str(made['fields'].get(grid.name)))} "
                              f"in {escape(group)}/{escape(folder.strip('/'))}")
        elif action == "add":
            if not rest:
                fail(f"add what? {command} add {group} <folder/new folder>")
            folder, _, name = rest[0].strip("/").rpartition("/")
            await api.create_record(
                screen.model, {**grid.where(group, folder), grid.name: name, grid.kind: "folder"}
            )
            console.print(f"[green]Made[/] {escape(rest[0].strip('/'))}/")
        elif action in ("show", "delete", "set"):
            if not rest:
                fail(f"which one? {command} {action} {group} <path>")
            record = await _entry(api, grid, group, rest[0])
            if action == "show":
                if plain:
                    emit(json.dumps(record, indent=2) + "\n")
                else:
                    _show_record(screen, record)
            elif action == "set":
                changed = await api.update_record(
                    screen.model, record["id"], _pairs(rest[1:], screen), rev=record["rev"]
                )
                console.print(f"[green]Saved[/] {escape(str(changed['fields'].get(grid.name, '')))}")
            else:
                await api.delete_record(screen.model, record["id"])
                console.print(f"[green]Deleted[/] {escape(rest[0])}")
        else:
            fail(f"a {screen.kit} has list, get, put, add, show, set and delete, not {action}")
    except ApiError as exc:
        fail(str(exc))
# -- a thread: spaces, and what is said in them ------------------------------------
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
    out.print(f"[{TITLE}]{escape(name)}[/]")
    if not lines:
        out.print("[dim]Nothing said here yet.[/]")
        return
    body = screen.spec["body"]
    day = author = ""
    for line in lines:
        if _date_of(line["created_at"]) != day:
            day = _date_of(line["created_at"])
            author = ""
            out.print(f"[dim]── {day} ──[/]")
        if line["owner"] != author:
            author = line["owner"]
            who = "you" if author == me else author
            out.print(f"[bold]{escape(who)}[/] [dim]{line['created_at'][11:16]}[/]")
        edited = " [dim](edited)[/]" if line.get("updated_at") != line.get("created_at") else ""
        for text in str(line["fields"].get(body) or "").splitlines() or [""]:
            out.print(f"  {escape(text)}{edited}")
            edited = ""


async def _thread(api: CloudmorrowClient, screen: Screen, action: str, args: list[str], plain: bool) -> None:
    link = screen.fields[screen.spec["space"]]
    space_model = link["to"]
    me = str((await api.me()).get("username", ""))
    spaces = await api.records(space_model)
    if action == "list":
        if plain:
            emit(json.dumps(spaces, indent=2) + "\n")
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
        out.print(table)
        return
    if action not in ("show", "say"):
        fail(f"a {screen.kit} is list, show and say")
    if not args:
        fail(f"which one? cm {screen.quill['id']} {action} <{space_model}>")
    space = _find_space(spaces, args[0], me, screen)
    try:
        if action == "say":
            text = " ".join(args[1:]).strip()
            if not text:
                fail(f'say what? cm {screen.quill["id"]} say {args[0]} "<words>"')
            await api.create_record(screen.model, {link["name"]: space["id"], screen.spec["body"]: text})
            console.print(f"[green]Said[/] in {escape(space_name(space, me, screen))}")
            return
        lines = await api.records(screen.model, last=PAGE, **{link["name"]: space["id"]})
        await api.mark_seen(space_model, space["id"])
    except ApiError as exc:
        fail(str(exc))
    if plain:
        emit(json.dumps(lines, indent=2) + "\n")
        return
    _show_thread(screen, space_name(space, me, screen), lines, me)
