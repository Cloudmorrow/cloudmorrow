"""A `calendar`: a range of days, and an add that fills in the end and the space."""

from __future__ import annotations

import datetime as dt

from rich.markup import escape
from rich.table import Table

# quillrun.out, .console and .emit, looked up as they print: see screen.py.
from cloudmorrow.cli import quillrun
from cloudmorrow.cli.common import fail
from cloudmorrow.cli.quillrun.screen import (
    Screen,
)
from cloudmorrow.console import TITLE


def _day(value: str, what: str) -> str:
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        fail(f"{what} is a date, as 2026-10-01")
    return ""


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
    quillrun.out.print(table)
