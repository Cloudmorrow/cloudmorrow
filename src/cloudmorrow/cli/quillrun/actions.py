"""A Quill's code: its actions, which are commands, and its views, which print as text."""

from __future__ import annotations

import json

import typer
from rich.markup import escape

# quillrun.out, .console and .emit, looked up as they print: see screen.py.
from cloudmorrow.cli import quillrun
from cloudmorrow.cli.common import fail, stdin_is_a_terminal
from cloudmorrow.cli.quillrun.screen import (
    _find,
)
from cloudmorrow.client.api import CloudmorrowClient


def _labels(quill: dict) -> dict[str, str]:
    return {a["id"]: a["label"] for a in quill.get("actions", [])}


def _list_actions(quill: dict, plain: bool) -> None:
    actions = quill.get("actions", [])
    if plain:
        quillrun.emit(json.dumps(actions, indent=2) + "\n")
        return
    if not actions:
        quillrun.out.print(f"[dim]{escape(quill['name'])} has no actions of its own[/]")
        return
    for action in actions:
        on = f" <{action['on']}>" if action.get("on") else ""
        takes = " ".join(f"{f['name']}=…" if f.get("required") else f"[{f['name']}=…]" for f in action["fields"])
        quillrun.out.print(
            f"[bold]{escape(action['id'])}[/]{escape(on)} {escape(takes)}  [dim]{escape(action['label'])}[/]"
        )


async def _view(api: CloudmorrowClient, quill: dict, screen: dict, args: list[str], plain: bool) -> None:
    from cloudmorrow.quill.text import render

    params = _plain_pairs(args)
    record = params.pop("record", "")
    answer = await api.quill_view(quill["id"], screen["id"], record=record, **params)
    if plain:
        quillrun.emit(json.dumps(answer["tree"], indent=2) + "\n")
        return
    quillrun.out.print(escape(render(answer["tree"], actions=_labels(quill)).rstrip()))


def _plain_pairs(values: list[str]) -> dict:
    pairs = {}
    for pair in values:
        name, sep, value = pair.partition("=")
        if not sep:
            fail(f"{pair!r}: give it as name=value")
        pairs[name] = value
    return pairs


async def _press(api: CloudmorrowClient, quill: dict, action: dict, args: list[str], plain: bool) -> None:
    """Run one of a Quill's actions: on which record first, if it is on one, then its form."""
    record = ""
    if action.get("on"):
        if not args or "=" in args[0]:
            fail(f"{action['id']} is done to a {action['on']}: cm {quill['id']} {action['id']} <which> [name=value …]")
        model = quill["models"].get(action["on"])
        if model is None:
            fail(f"{action['on']} is not yours to reach here")
        record = _find(await api.records(action["on"]), args[0], model["title"])["id"]
        args = args[1:]
    fields = {f["name"]: f for f in action["fields"]}
    given: dict = {}
    for name, value in _plain_pairs(args).items():
        if name not in fields:
            takes = ", ".join(fields) or "nothing"
            fail(f"{action['id']} has no field {name!r}; it takes {takes}")
        kind = fields[name]["kind"]
        if kind == "json":
            try:
                value = json.loads(value)
            except ValueError:
                fail(f"{name} is JSON")
        elif kind == "link":
            linked = quill["models"].get(fields[name]["to"], {})
            value = _find(await api.records(fields[name]["to"]), value, linked.get("title", "name"))["id"]
        given[name] = value
    if action.get("confirm") and not plain and stdin_is_a_terminal():
        if not typer.confirm(action["confirm"]):
            return
    effects = await api.quill_action(quill["id"], action["id"], record=record, fields=given)
    await _effects(api, quill, effects, record, plain)


async def _effects(api: CloudmorrowClient, quill: dict, effects: list[dict], record: str, plain: bool) -> None:
    if plain:
        quillrun.emit(json.dumps(effects, indent=2) + "\n")
        return
    for effect in effects:
        kind = effect.get("effect")
        if kind == "toast":
            quillrun.console.print(f"[green]{escape(effect['text'])}[/]")
        elif kind == "error":
            fail(effect["text"])
        elif kind == "open":
            quillrun.console.print(f"[dim]→ {escape(effect['model'])} {escape(effect['id'])}[/]")
        elif kind == "go":
            quillrun.console.print(f"[dim]→ cm {quill['id']} --screen {escape(effect['screen'])}[/]")
        elif kind == "confirm":
            if not stdin_is_a_terminal() or not typer.confirm(effect["text"]):
                quillrun.console.print("[dim]Left as it was[/]")
                continue
            then = next((a for a in quill.get("actions", []) if a["id"] == effect["then"]), None)
            if then is None:
                fail(f"{effect['then']} is not one of {quill['id']}'s actions")
            more = await api.quill_action(
                quill["id"], then["id"], record=record if then.get("on") else "", fields=effect.get("args") or {}
            )
            await _effects(api, quill, more, record, plain)
