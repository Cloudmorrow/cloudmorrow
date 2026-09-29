"""A `board`: records in lanes, an enum's values or the records of a link."""

from __future__ import annotations

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
from cloudmorrow.quill.screens import done_lane, in_order, lane_filter


async def _lanes(api: CloudmorrowClient, screen: Screen, group_id: str | None) -> tuple[list[tuple[str, str]], str | None]:
    """A board's lanes as (value, label), and the one `done` moves to.

    An enum's values, or — when the lane is a link — the linked records, in
    their order, and on a board with groups only the group's own.
    """
    lane = screen.lane
    if lane.get("kind") != "link":
        values = lane["values"]
        lanes = list(zip(values, lane.get("labels") or values, strict=True))
        return lanes, done_lane(screen.spec, lanes)
    target = screen.models[lane["to"]]
    where = lane_filter(target, (screen.group or {}).get("to", ""), group_id)
    rows = in_order(await api.records(target["id"], **where))
    lanes = [(r["id"], str(r["fields"].get(target["title"]) or r["id"])) for r in rows]
    return lanes, done_lane(screen.spec, lanes, rows)


def _lane_named(lanes: list[tuple[str, str]], wanted: str) -> str:
    """A lane by its value, or by what it is called: `move 3f2a Proposal`."""
    for value, label in lanes:
        if wanted in (value, value[2:]) or wanted.casefold() == label.casefold():
            return value
    fail(f"no lane {wanted!r}: {', '.join(label for _, label in lanes)}")


def _group_of(screen: Screen, record: dict) -> str | None:
    return record["fields"].get(screen.group["name"]) if screen.group else None


def _show_board(screen: Screen, records: list[dict], heading: str, lanes: list[tuple[str, str]]) -> None:
    lane = screen.lane
    values = [value for value, _ in lanes]
    table = Table(title=heading, title_style=TITLE)
    for _, label in lanes:
        table.add_column(label)
    # A record in no lane there is — none yet, or one since deleted — is in the first.
    columns = [
        [r for r in records if (r["fields"].get(lane["name"]) if r["fields"].get(lane["name"]) in values
                                else values[0]) == value] for value in values
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
    quillrun.out.print(table)
