"""A `list`: rows, grouped and subgrouped by a link or by value."""

from __future__ import annotations

from rich.markup import escape
from rich.table import Table

# quillrun.out, .console and .emit, looked up as they print: see screen.py.
from cloudmorrow.cli import quillrun
from cloudmorrow.cli.quillrun.screen import (
    MASK,
    Screen,
    _short,
)
from cloudmorrow.console import TITLE


def _show_list(screen: Screen, records: list[dict], heading: str, shown_levels=()) -> None:
    table = Table(title=heading, title_style=TITLE)
    tick = screen.spec.get("tick")
    if tick:
        table.add_column("")
    table.add_column("id", style="dim")
    # The levels not picked with --group are columns, so every row says where it is.
    for level in shown_levels:
        table.add_column(level.get("label", level["name"]), style="dim")
    table.add_column(screen.fields[screen.title].get("label", screen.title))
    subtitle = screen.spec.get("subtitle")
    if subtitle:
        table.add_column(screen.fields[subtitle].get("label", subtitle))
    for record in records:
        row = []
        if tick:
            row.append("●" if record["fields"].get(tick) else "○")
        row.append(_short(record["id"]))
        row += [escape(str(record["fields"].get(level["name"]) or "")) for level in shown_levels]
        row.append(escape(str(record["fields"].get(screen.title, ""))))
        if subtitle:
            if screen.secret(subtitle):
                row.append(f"[dim]{MASK}[/]")
            else:
                row.append(escape(str(record["fields"].get(subtitle) or "")))
        table.add_row(*row)
    quillrun.out.print(table)
