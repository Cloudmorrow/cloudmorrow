"""`cm <quill> history <record>`: who did what to a record, newest first; never a value."""

from __future__ import annotations

import json

from rich.markup import escape

from cloudmorrow.cli import quillrun
from cloudmorrow.cli.common import fail
from cloudmorrow.cli.quillrun.screen import Screen, _find
from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.quill.screens import editor_fields, history_said, listing_filters


async def _history(api: CloudmorrowClient, screen: Screen, args: list[str], plain: bool) -> None:
    if not args:
        fail(f"which record? cm {screen.quill['id']} history <id or title>")
    model = screen.models[screen.model]
    filters = listing_filters(editor_fields(screen.spec, model)) if screen.kit == "editor" else {}
    record = _find(await api.records(screen.model, **filters), args[0], screen.title)
    lines = await api.record_history(screen.model, record["id"])
    if plain:
        quillrun.emit(json.dumps(lines, indent=2) + "\n")
        return
    if not lines:
        quillrun.console.print("[dim]no history is kept for it[/]")
        return
    for line in lines:
        when = str(line.get("at") or "")[:16].replace("T", " ")
        quillrun.out.print(f"{escape(history_said(line, model))}  [dim]{escape(when)}[/]")
