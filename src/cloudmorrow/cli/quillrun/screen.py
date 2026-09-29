"""What every kind of screen shares: the screen itself, and finding a record on it."""

from __future__ import annotations

import json

from rich.markup import escape
from rich.table import Table

# Printing goes through the package's own `out`, `console` and `emit`,
# looked up as it happens: pointing them somewhere else (a test does)
# points every kind of screen there at once.
from cloudmorrow.cli import quillrun
from cloudmorrow.cli.common import fail
from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.console import TITLE

# What a secret field says until it is asked for.
MASK = "••••••••"


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
        """A board's group, or a list's: a link, whose records are the groups."""
        field = self.fields.get(self.spec.get("group", "")) if self.spec.get("group") else None
        return field if field and field.get("kind") == "link" else None

    @property
    def levels(self) -> list[dict]:
        """A list's group and subgroup when they are values, not links: picked by value."""
        if self.kit != "list" or self.group is not None:
            return []
        return [self.fields[self.spec[n]] for n in ("group", "subgroup")
                if self.spec.get(n) in self.fields]

    def secret(self, name: str) -> bool:
        return bool(self.fields.get(name, {}).get("secret"))

    @property
    def moments(self) -> tuple[str, str] | None:
        """A calendar's two moment fields, which a list asks for a range of."""
        if self.kit != "calendar":
            return None
        return self.spec["starts"], self.spec["ends"]

    def group_title(self, record: dict) -> str:
        target = self.models[self.group["to"]]
        return str(record["fields"].get(target["title"], record["id"]))


def _quill(quills: list[dict], quill_id: str) -> dict:
    quill = next((q for q in quills if q["id"] == quill_id), None)
    if quill is None:
        names = ", ".join(sorted(q["id"] for q in quills)) or "none"
        fail(f"'{quill_id}' is not a command, nor an installed Quill (installed: {names})")
    return quill


def _screen_spec(quill: dict, screen_id: str) -> dict:
    if not quill["screens"]:
        fail(f"{quill['id']} has no screens")
    screen = quill["screens"][0]
    if screen_id:
        screen = next((s for s in quill["screens"] if s["id"] == screen_id), None)
        if screen is None:
            fail(
                f"{quill['id']} has no screen {screen_id!r}: {', '.join(s['id'] for s in quill['screens'])}"
            )
    return screen


def _screen(quills: list[dict], quill_id: str, screen_id: str) -> Screen:
    quill = _quill(quills, quill_id)
    return Screen(quill, _screen_spec(quill, screen_id))


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
    matches = [r for r in records if r["id"].startswith(key) or r["id"].startswith(wanted)]
    if not matches:
        matches = [
            r for r in records if str(r["fields"].get(title, "")).casefold() == key.casefold()
        ]
    if len(matches) != 1:
        fail(f"{'no record' if not matches else 'more than one record'} matches {key!r}")
    return matches[0]


def _short(record_id: str) -> str:
    """Enough of an id to pick a record by: a record store id's first four after `r_`."""
    return record_id[2:6] if record_id.startswith("r_") else record_id[:10]


async def _link_values(api: CloudmorrowClient, screen: Screen, fields: dict) -> dict:
    """A link given by the linked record's name, made its id."""
    for name, value in list(fields.items()):
        field = screen.fields[name]
        if field["kind"] != "link" or not value or str(value).startswith("r_"):
            continue
        target = screen.models.get(field["to"]) or {"title": "title"}
        fields[name] = _find(await api.records(field["to"]), str(value), target["title"])["id"]
    return fields


def _show_record(screen: Screen, record: dict, *, reveal: bool = False) -> None:
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
        if field.get("secret") and not reveal:
            table.add_row(field.get("label", name), f"[dim]{MASK}  (--reveal shows it)[/]")
            continue
        table.add_row(field.get("label", name), escape("" if value is None else str(value)))
    table.add_row("rev", str(record["rev"]))
    quillrun.out.print(table)
