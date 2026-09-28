"""What a handler returns: what the surface does next, or what an API answers.

An action or a view's button returns nothing (the screen is drawn again), one
effect, or a list of them:

    toast("Logged")                 a line that goes away
    open(record)                    the record's sheet
    go("garage", van="r_…")         another screen of this Quill
    confirm("Delete all?", then="clear_all")   ask, then run another action
    error("That van is sold")       the form stays open, with this under it

An API or a webhook returns `respond(...)`, or nothing for a 204.
"""

from __future__ import annotations

import json as _json


def toast(text: str) -> dict:
    return {"effect": "toast", "text": str(text)}


def open(record=None, *, model: str = "", id: str = "") -> dict:  # noqa: A001 - the word is right
    """Open a record's sheet: a Record, or a model and an id."""
    if record is not None:
        model, id = record.model, record.id
    if not model or not id:
        raise ValueError("open() takes a record, or model= and id=")
    return {"effect": "open", "model": model, "id": id}


def go(screen: str, **params) -> dict:
    return {"effect": "go", "screen": screen, "params": _plain(params)}


def confirm(text: str, *, then: str, **args) -> dict:
    """Ask first; on yes, run the action *then* with *args*."""
    return {"effect": "confirm", "text": str(text), "then": then, "args": _plain(args)}


def error(text: str) -> dict:
    return {"effect": "error", "text": str(text)}


def redraw() -> dict:
    return {"effect": "redraw"}


def respond(
    body=None,
    *,
    status: int = 200,
    json=None,  # noqa: A002 - the word callers expect
    text: str | None = None,
    headers: dict | None = None,
) -> dict:
    """An API's or a webhook's answer. `json=` is sent as JSON; `text=` as text."""
    content_type = ""
    if json is not None:
        payload, content_type = _json.dumps(json), "application/json"
    elif text is not None:
        payload, content_type = str(text), "text/plain; charset=utf-8"
    elif body is not None:
        payload = body if isinstance(body, str) else _json.dumps(body)
        content_type = "text/plain; charset=utf-8" if isinstance(body, str) else "application/json"
    else:
        payload = ""
    head = {str(k): str(v) for k, v in (headers or {}).items()}
    if content_type and not any(k.lower() == "content-type" for k in head):
        head["Content-Type"] = content_type
    return {"effect": "respond", "status": int(status), "body": payload, "headers": head}


def _plain(value):
    """Records become their ids, so effects are JSON."""
    if hasattr(value, "id") and hasattr(value, "model"):
        return value.id
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    return value


def normalise(result) -> list[dict]:
    """A handler's return value, as the list of effects the surface gets."""
    if result is None:
        return []
    if isinstance(result, dict):
        result = [result]
    if not isinstance(result, list | tuple):
        raise TypeError("an action returns an effect, a list of effects, or nothing")
    effects = []
    for item in result:
        if not isinstance(item, dict) or "effect" not in item:
            raise TypeError(f"{item!r} is not an effect: use toast(), open(), go(), confirm(), error()")
        effects.append(item)
    return effects
