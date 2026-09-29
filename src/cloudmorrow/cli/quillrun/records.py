"""The kit's words on a screen of records: a board, a list or a calendar."""

from __future__ import annotations

import datetime as dt
import json

from rich.markup import escape

# quillrun.out, .console and .emit, looked up as they print: see screen.py.
from cloudmorrow.cli import quillrun
from cloudmorrow.cli.common import fail
from cloudmorrow.cli.quillrun.board import _group_of, _lane_named, _lanes, _show_board
from cloudmorrow.cli.quillrun.calendar import _day, _event_defaults, _show_calendar
from cloudmorrow.cli.quillrun.grouped import _show_list
from cloudmorrow.cli.quillrun.screen import (
    Screen,
    _find,
    _link_values,
    _pairs,
    _show_record,
)
from cloudmorrow.client.api import CloudmorrowClient


async def _group_id(api: CloudmorrowClient, screen: Screen, wanted: str) -> tuple[str | None, list[dict]]:
    """The group a board command is about: named, or the first there is."""
    if screen.group is None:
        return None, []
    groups = await api.records(screen.group["to"])
    if not groups:
        fail(f"there is no {screen.group['to']} yet")
    if not wanted:
        return groups[0]["id"], groups
    return _find(groups, wanted, screen.models[screen.group["to"]]["title"])["id"], groups


async def _act_records(
    api: CloudmorrowClient,
    screen: Screen,
    action: str,
    args: list[str],
    group: str,
    index: int | None,
    plain: bool,
    days: tuple[str, str] = ("", ""),
    reveal: bool = False,
) -> None:
    if action == "say":
        fail(f"{screen.quill['id']} is not a conversation; say is for a thread")
    if action in ("edit", "search"):
        fail(f"{action} is for an editor; {screen.quill['id']} is a {screen.kit}")
    group_id, groups = await _group_id(api, screen, group)
    where = {screen.group["name"]: group_id} if group_id else {}
    # A list picked by value: --group work, or work/production for the subgroup too.
    picked = [part for part in group.split("/") if part] if screen.levels else []
    if len(picked) > len(screen.levels):
        fail(f"--group is at most {'/'.join(f['name'] for f in screen.levels)}")
    where.update({field["name"]: value for field, value in zip(screen.levels, picked, strict=False)})

    if action == "groups" and screen.levels:
        found = await api.records(screen.model, **where)
        counts: dict[str, int] = {}
        for record in found:
            place = "/".join(str(record["fields"].get(f["name"])) for f in screen.levels)
            counts[place] = counts.get(place, 0) + 1
        if plain:
            quillrun.emit(json.dumps(counts, indent=2) + "\n")
            return
        for place, count in sorted(counts.items()):
            quillrun.out.print(f"{escape(place)}  [dim]{count}[/]")
        return
    spaces: list[dict] = []
    if screen.moments:
        # A calendar lists a range of days, across every space it can see.
        start = _day(days[0], "--from") if days[0] else dt.date.today().isoformat()
        end = _day(days[1], "--to") if days[1] else (dt.date.fromisoformat(start) + dt.timedelta(days=6)).isoformat()
        if end < start:
            fail("--to is before --from")
        where = {f"{screen.moments[0]}__lte": f"{end}T23:59", f"{screen.moments[1]}__gte": start}
        if screen.spec.get("space"):
            spaces = await api.records(screen.fields[screen.spec["space"]]["to"])

    if action == "groups":
        if screen.group is None:
            fail(f"{screen.quill['id']} has no groups")
        if plain:
            quillrun.emit(json.dumps(groups, indent=2) + "\n")
            return
        for record in groups:
            quillrun.out.print(f"{record['id'][2:6]}  {escape(screen.group_title(record))}")
        return

    records = await api.records(screen.model, **where)
    if action == "list":
        if plain:
            quillrun.emit(json.dumps(records, indent=2) + "\n")
            return
        heading = screen.spec.get("label") or screen.quill["name"]
        if group_id:
            heading += f" · {screen.group_title(next(g for g in groups if g['id'] == group_id))}"
        if picked:
            heading += " · " + " · ".join(picked)
        if screen.kit == "board":
            _show_board(screen, records, heading, (await _lanes(api, screen, group_id))[0])
        elif screen.moments:
            _show_calendar(screen, records, spaces, f"{heading} · {start} to {end}")
        else:
            _show_list(screen, records, heading, screen.levels[len(picked) :])
        return

    if action == "add":
        if not args:
            fail(f'add what? cm {screen.quill["id"]} add "<{screen.title}>" [name=value …]')
        if screen.moments:
            fields = await _link_values(api, screen, {screen.title: args[0], **_pairs(args[1:], screen)})
            fields = _event_defaults(screen, fields, spaces)
        else:
            fields = {screen.title: args[0], **_pairs(args[1:], screen), **where}
            if screen.lane is not None and screen.lane["name"] not in fields:
                lanes, _ = await _lanes(api, screen, group_id)
                if lanes:
                    fields[screen.lane["name"]] = lanes[0][0]
            elif screen.lane is not None and screen.lane.get("kind") == "link":
                lanes, _ = await _lanes(api, screen, group_id)
                fields[screen.lane["name"]] = _lane_named(lanes, fields[screen.lane["name"]])
        made = await api.create_record(screen.model, fields, index=index)
        quillrun.console.print(f"[green]Added[/] {escape(args[0])} [dim]{made['id'][2:6]}[/]")
        return

    if not args:
        fail(f"which one? cm {screen.quill['id']} {action} <id>")
    if screen.moments:
        # A record is found by id or title among all of them, not only this week's.
        records = await api.records(screen.model)
    record = _find(records if records else await api.records(screen.model), args[0], screen.title)
    rest = args[1:]
    if action == "show":
        if reveal:
            # A listing never carries a hidden field; the record itself does.
            record = await api.record(screen.model, record["id"])
        if plain:
            quillrun.emit(json.dumps(record, indent=2) + "\n")
        else:
            _show_record(screen, record, reveal=reveal)
    elif action == "set":
        changed = await api.update_record(
            screen.model,
            record["id"],
            await _link_values(api, screen, _pairs(rest, screen)),
            rev=record["rev"],
        )
        quillrun.console.print(f"[green]Saved[/] {escape(str(changed['fields'].get(screen.title, '')))}")
    elif action == "move":
        if screen.lane is None:
            fail("move takes a lane: this is not a board")
        lanes, _ = await _lanes(api, screen, _group_of(screen, record) or group_id)
        if not rest:
            fail(f"move takes a lane: {', '.join(label for _, label in lanes)}")
        await api.move_record(screen.model, record["id"], {screen.lane["name"]: _lane_named(lanes, rest[0])}, index)
        quillrun.console.print(f"[green]Moved[/] to {rest[0]}")
    elif action in ("done", "undone"):
        if screen.lane is not None:
            lanes, target = await _lanes(api, screen, _group_of(screen, record) or group_id)
            if not lanes:
                fail("this board has no lanes yet")
            lane = target if action == "done" else lanes[0][0]
            await api.move_record(screen.model, record["id"], {screen.lane["name"]: lane}, None)
        elif screen.spec.get("tick"):
            await api.update_record(screen.model, record["id"], {screen.spec["tick"]: action == "done"})
        else:
            fail(f"{screen.quill['id']} has nothing to tick")
        quillrun.console.print(f"[green]{'Done' if action == 'done' else 'Not done'}[/]")
    elif action == "delete":
        await api.delete_record(screen.model, record["id"])
        quillrun.console.print(f"[green]Deleted[/] {escape(str(record['fields'].get(screen.title, '')))}")
