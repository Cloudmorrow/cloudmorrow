"""Telling people about what happens in the spaces they are in.

The record store says *that* something was written in a space and to whom
it is news (`RecordStore.on_notify`), and *that* somebody was added to one
(`on_member_added`). This module is what that means on a phone: a push with
the space's name and the first line of what was said, and, for being added,
a line behind the bell as well — the way chat and calendar always did it.

Pushes go out on a thread, after the write has answered: nobody waits on a
phone's push service to hear that their message was sent.
"""

from __future__ import annotations

import threading

from cloudmorrow.server.deps import AppState
from cloudmorrow.server.records import Principal, Record
from cloudmorrow.server.routes.push import notify_message


def _where(state: AppState, model: str) -> tuple[str, str]:
    """The Quill and screen a record of *model* is looked at in, for the push to open."""
    for quill in state.quills.quills.values():
        for screen in quill.screens:
            if screen.get("model") == model or screen.get("space") == model:
                return quill.id, screen["id"]
    return "", ""


def _space_name(state: AppState, record: Record) -> tuple[str, str, str]:
    """(space model, space id, space name) for a record that is in one."""
    model = state.quills.datamodels.get(record.model)
    if model is None or not model.in_space:
        return "", "", ""
    space_model = state.quills.datamodels.get(model.get_field(model.in_space).to)
    space_id = str(record.fields.get(model.in_space) or "")
    if space_model is None or not space_id:
        return "", space_id, ""
    try:
        space = state.records.get(Principal.person(record.owner), space_model.id, space_id)
    except LookupError:
        return space_model.id, space_id, ""
    return space_model.id, space_id, str(space.fields.get(space_model.title) or "")


def _later(work) -> None:
    threading.Thread(target=work, name="space-notify", daemon=True).start()


def install(state: AppState) -> None:
    """Hang the telling on the record store of a running server."""

    def written(record: Record, rule: dict, people: list[str]) -> None:
        if not rule.get("push") or not people:
            return
        if people == ["*"]:
            people = [u.username for u in state.users.list() if u.username != record.owner]
        model = state.quills.datamodels.get(record.model)
        line = str(record.fields.get(model.title) if model else "") or "Something new"
        space_model, space_id, name = _space_name(state, record)
        quill, screen = _where(state, record.model)
        url = f"#/q/{quill}/{screen}/{space_id}" if quill else ""
        title = f"{record.owner} in {name}" if name else record.owner
        _later(lambda: notify_message(state, people, title=title, body=line, url=url,
                                      tag=f"{space_model}-{space_id}"))

    def added(space: Record, username: str, by: str) -> None:
        model = state.quills.datamodels.get(space.model)
        name = str(space.fields.get(model.title) if model else "") or space.id
        label = model.label.lower() if model else "space"
        said = f"{by} added you to the {label} {name}"
        state.notifications.add(username, kind=f"{space.model}.added", title=said, body="")
        quill, screen = _where(state, space.model)
        url = f"#/q/{quill}/{screen}/{space.id}" if quill else ""
        _later(lambda: notify_message(state, [username], title=name, body=said, url=url,
                                      tag=f"{space.model}-added-{space.id}"))

    state.records.on_notify.append(written)
    state.records.on_member_added.append(added)
