"""An `editor`: pages of Markdown, by path."""

from __future__ import annotations

import json
import sys

from rich.markup import escape
from rich.table import Table

# quillrun.out, .console and .emit, looked up as they print: see screen.py.
from cloudmorrow.cli import quillrun
from cloudmorrow.cli.common import edit_text, fail, stdin_is_a_terminal
from cloudmorrow.cli.quillrun.screen import (
    Screen,
    _pairs,
)
from cloudmorrow.client.api import ApiError, CloudmorrowClient
from cloudmorrow.console import TITLE
from cloudmorrow.quill.screens import editor_fields, listing_filters, page_fields, page_path


def _bound(screen: Screen) -> dict:
    return editor_fields(screen.spec, screen.models[screen.model])


def _page_key(screen: Screen, record: dict) -> str:
    """What a page is called on the command line: its path under the root,
    without the suffix, else its title."""
    return page_path(_bound(screen), record)


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


async def _act_editor(api: CloudmorrowClient, screen: Screen, action: str, args: list[str], plain: bool) -> None:
    bound = _bound(screen)
    body = bound["body"]
    path = bound["path"]
    filters = listing_filters(bound)
    if action == "search":
        if not args:
            fail(f"search for what? cm {screen.quill['id']} search <text>")
        found = await api.records(screen.model, q=" ".join(args), **filters)
        if plain:
            quillrun.emit(json.dumps(found, indent=2) + "\n")
            return
        for record in found:
            line = record.get("preview") or ""
            quillrun.out.print(f"{escape(_page_key(screen, record))}  [dim]{escape(line)}[/]")
        if not found:
            quillrun.console.print("[dim]nothing matches[/]")
        return
    records = await api.records(screen.model, **filters)
    if action == "list":
        if plain:
            quillrun.emit(json.dumps(records, indent=2) + "\n")
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
        quillrun.out.print(table)
        return
    if not args:
        fail(f"which page? cm {screen.quill['id']} {action} <path>")
    if action == "add":
        if any(_page_key(screen, r) == args[0].strip("/") for r in records):
            fail(f"there is already a page {args[0]!r}; edit it instead")
        text = " ".join(args[1:]) if len(args) > 1 else _text("", what="the page")
        fields = {**page_fields(bound, args[0].strip("/")), body: text}
        made = await api.create_record(screen.model, fields)
        quillrun.console.print(f"[green]Added[/] {escape(_page_key(screen, made))}")
        return
    found = await api.record(screen.model, _find_page(screen, records, args[0])["id"])
    if action == "show":
        quillrun.emit(json.dumps(found, indent=2) + "\n" if plain else str(found["fields"].get(body) or ""))
    elif action == "edit":
        before = str(found["fields"].get(body) or "")
        text = " ".join(args[1:]) if len(args) > 1 else _text(before, what="the page")
        if text == before:
            quillrun.console.print("[dim]unchanged[/]")
            return
        try:
            await api.update_record(screen.model, found["id"], {body: text}, rev=found["rev"])
        except ApiError as exc:
            if exc.status_code == 409:
                fail("it changed somewhere else while you were editing; nothing was saved")
            raise
        quillrun.console.print(f"[green]Saved[/] {escape(_page_key(screen, found))}")
    elif action == "delete":
        await api.delete_record(screen.model, found["id"])
        quillrun.console.print(f"[green]Deleted[/] {escape(_page_key(screen, found))}")
    elif action == "set":
        changed = await api.update_record(screen.model, found["id"], _pairs(args[1:], screen), rev=found["rev"])
        quillrun.console.print(f"[green]Saved[/] {escape(_page_key(screen, changed))}")
    else:
        fail(f"an editor has list, show, add, edit, set, delete and search, not {action}")
