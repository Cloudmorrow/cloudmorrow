"""The kit's data, read the way the terminal needs it: no widgets in here.

A Quill never ships a screen of its own (docs/QUILLS.md), so everything the
terminal draws for one is decided from what the server hands over: the
screen's bindings, the datamodels behind them, the Quills' actions, and the
records. These are the readings of those that more than one pane, sheet or
dialog makes — what a field is called, what a record is called, what a value
says where it cannot be edited, what a link may point at, which actions are
on which datamodel — kept apart from Textual so they can be read, and
tested, as the plain functions they are.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
from typing import Any

from cloudmorrow.client.api import ApiError, ConflictError
from cloudmorrow.tui.dates import as_local

# A subtask is a checkbox line in the body, the same one the note editor ticks.
_SUBTASK_RE = re.compile(r"^\s*[-*+]\s+\[([ xX])\]\s", re.MULTILINE)


# -- reading a datamodel -----------------------------------------------------
def field_of(model: dict, name: str | None) -> dict | None:
    """The definition of *name* in *model*, or None when it has no such field."""
    if not name:
        return None
    return next((f for f in model.get("fields", []) if f["name"] == name), None)


def field_label(field: dict) -> str:
    return str(field.get("label") or field["name"].replace("_", " ").capitalize())


def enum_options(field: dict) -> list[tuple[str, str]]:
    """An enum's values with what each is called on screen, in declared order."""
    values = [str(v) for v in field.get("values") or []]
    labels = [str(v) for v in field.get("labels") or []]
    return [
        (value, labels[index] if index < len(labels) else value.replace("_", " ").capitalize())
        for index, value in enumerate(values)
    ]


def title_of(record: dict, model: dict | None) -> str:
    """What a record is called in a list: its model's title field, or its id."""
    name = (model or {}).get("title") or "title"
    value = (record.get("fields") or {}).get(name)
    return str(value) if value not in (None, "") else f"({record.get('id', '?')})"


def read_only(field: dict) -> bool:
    """A stamped field is the server's to set: shown, never typed into."""
    return bool(field.get("stamp"))


def can_write(model: dict | None) -> bool:
    """Whether the person may make, change and delete *model*'s records.

    The server fits every Quill to whoever asks (docs/CIRCLES.md): each
    datamodel comes with their `access`, and one they may only read is drawn
    as read — the same screen, without its writing. A datamodel that is not
    there at all is not theirs to write either. A server without circles
    sends no `access`, and there everybody has everything.
    """
    return bool(model) and model.get("access", "write") != "read"


def shown(field: dict, value: Any) -> str:
    """A value as the sheet writes it where it cannot be edited."""
    if value in (None, ""):
        return "—"
    kind = field.get("kind")
    if kind == "datetime":
        return as_local(str(value))
    if kind == "enum":
        return dict(enum_options(field)).get(str(value), str(value))
    if kind == "bool":
        return "yes" if value else "no"
    if kind == "json":
        return json.dumps(value)
    return str(value)


# -- what a link may point at --------------------------------------------------
async def link_rows(client: Any, to: str, cache: dict[str, list[dict]] | None = None) -> list[dict] | None:
    """The records of datamodel *to*, which a link to it may point at.

    None when they cannot be read. *cache*, when given, is where rows already
    read are kept by datamodel, so a screen whose links all point at one
    datamodel reads it once rather than once a link.
    """
    if cache is not None and to in cache:
        return cache[to]
    try:
        rows = await client.records(to)
    except ApiError:
        return None
    if cache is not None:
        cache[to] = rows
    return rows


async def link_choices(
    client: Any, models: dict, model: dict, *, cache: dict[str, list[dict]] | None = None
) -> dict[str, list[tuple[str, str]]]:
    """For every link field of *model*: the records it may point at, titled.

    Fetched before the sheet opens rather than by it, so the sheet has its
    drop-downs filled the moment it is on screen and never shows a link as
    empty while it waits.
    """
    cache = {} if cache is None else cache
    choices: dict[str, list[tuple[str, str]]] = {}
    for field in model.get("fields", []):
        if field.get("kind") != "link" or not field.get("to"):
            continue
        target = models.get(field["to"]) or {}
        rows = await link_rows(client, field["to"], cache) or []
        choices[field["name"]] = [(title_of(row, target), str(row["id"])) for row in rows]
    return choices


# -- what a card says ----------------------------------------------------------
def subtask_progress(body: str) -> tuple[int, int]:
    """How many of a body's `- [ ]` lines are ticked, and how many there are."""
    marks = _SUBTASK_RE.findall(body or "")
    return sum(1 for mark in marks if mark.lower() == "x"), len(marks)


def days_left(expires_at: str | None) -> int | None:
    """Days before a record is swept by its Quill's expire job, or None.

    Rounded up, because part of a day is still a day you have: something
    that goes in a day and a half has two days left, and saying "1d left"
    would be the truncation talking rather than the truth.
    """
    if not expires_at:
        return None
    try:
        expiry = dt.datetime.fromisoformat(expires_at)
    except (TypeError, ValueError):
        return None
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=dt.UTC)
    remaining = (expiry - dt.datetime.now(tz=dt.UTC)).total_seconds()
    if remaining <= 0:
        return 0
    return math.ceil(remaining / 86400)


def how_long(after: str) -> str:
    """An expire job's `after` ("7d", "12h") as a person would say it."""
    match = re.fullmatch(r"(\d+)([mhdw])", (after or "").strip())
    if not match:
        return after
    count, unit = int(match.group(1)), match.group(2)
    if unit == "d" and count == 7:
        return "a week"
    names = {"m": "minute", "h": "hour", "d": "day", "w": "week"}
    word = names[unit]
    return f"{count} {word}" + ("" if count == 1 else "s")


# -- a Quill's actions -----------------------------------------------------------
def installed(app: Any) -> list[dict]:
    """The Quills as the server last said, fitted to this person (see the workspace)."""
    return [q for q in (getattr(app, "quills", None) or []) if q.get("enabled", True)]


def actions_on(quills: list[dict], model_id: str) -> list[tuple[dict, dict]]:
    """Every (Quill, action) `on` *model_id*, in the Quills' order: the sheet's buttons."""
    return [
        (quill, action) for quill in quills for action in quill.get("actions") or [] if action.get("on") == model_id
    ]


def loose_actions(quills: list[dict]) -> list[tuple[dict, dict]]:
    """Every (Quill, action) not on a record: the palette's."""
    return [(quill, action) for quill in quills for action in quill.get("actions") or [] if not action.get("on")]


def find_action(quill: dict, action_id: str) -> dict | None:
    return next((a for a in quill.get("actions") or [] if a.get("id") == action_id), None)


def all_models(app: Any, quill: dict | None = None) -> dict:
    """Every datamodel any installed Quill brought, *quill*'s own winning."""
    models: dict = {}
    for other in installed(app):
        models.update(other.get("models") or {})
    if quill is not None:
        models.update(quill.get("models") or {})
    return models


def failure(effects: list[dict]) -> str | None:
    """What an `error` effect says, if the action answered with one."""
    for effect in effects:
        if effect.get("effect") == "error":
            return str(effect.get("text") or "That did not work.")
    return None


# -- what the server said no with ------------------------------------------------
# Said when the stored session is no longer good, on the way to signing in.
SESSION_EXPIRED = "Session expired — sign in again."
# Said when a write carried a revision and somebody else's got there first.
CONFLICT = "That changed somewhere else — here it is as it is now."


def is_conflict(exc: Exception, *, stale: bool = False) -> bool:
    """Whether *exc* is somebody else's change winning over this one.

    A note's conflict always is. A plain 409 only is when the call carried a
    revision (*stale*): elsewhere the same status means a name is taken, and
    saying "that changed somewhere else" about that would be a lie.
    """
    if isinstance(exc, ConflictError):
        return True
    return stale and isinstance(exc, ApiError) and exc.status_code == 409
