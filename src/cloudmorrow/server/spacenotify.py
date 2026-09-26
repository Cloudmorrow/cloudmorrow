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


def _screen_of(state: AppState, model: str) -> tuple[str, dict]:
    """The Quill and screen a record of *model* is looked at in, for the push to open.

    A screen of the model itself, or one whose `space` link leads to it —
    being added to a channel opens the conversation screen the channel is in.
    """
    for quill in state.quills.quills.values():
        for screen in quill.screens:
            if screen.get("model") == model:
                return quill.id, screen
            child = state.quills.datamodels.get(str(screen.get("model", "")))
            space = screen.get("space")
            if child is not None and space in child.by_name and child.by_name[space].to == model:
                return quill.id, screen
    return "", {}


def _where(state: AppState, model: str) -> tuple[str, str]:
    quill, screen = _screen_of(state, model)
    return quill, str(screen.get("id", ""))


def between_people(screen: dict, space: Record | None) -> bool:
    """Is *space* one a screen makes between people — a direct conversation?

    A thread screen says which fields mark one in `made_as.direct`; such a
    space has no name worth saying, because its name is whoever is in it.
    """
    marks = (screen.get("made_as") or {}).get("direct") or {}
    return bool(marks) and space is not None and all(
        space.fields.get(name) == value for name, value in marks.items()
    )


def _space_of(state: AppState, record: Record) -> tuple[str, str, Record | None]:
    """(space model, space id, the space) for a record that is in one."""
    model = state.quills.datamodels.get(record.model)
    if model is None or not model.in_space:
        return "", "", None
    space_model = state.quills.datamodels.get(model.get_field(model.in_space).to)
    space_id = str(record.fields.get(model.in_space) or "")
    if space_model is None or not space_id:
        return "", space_id, None
    try:
        space = state.records.get(Principal.person(record.owner), space_model.id, space_id)
    except LookupError:
        return space_model.id, space_id, None
    return space_model.id, space_id, space


def _later(work) -> None:
    threading.Thread(target=work, name="space-notify", daemon=True).start()


def install(state: AppState) -> None:
    """Hang the telling on the record store of a running server."""

    def written(record: Record, rule: dict, people: list[str]) -> None:
        if not rule.get("push") or not people:
            return
        if people == ["*"]:
            # Everybody is the people, not the agents and screens acting for them.
            people = [
                u.username
                for u in state.users.list()
                if u.username != record.owner and u.is_active and u.user_type == "human"
            ]
        model = state.quills.datamodels.get(record.model)
        line = str(record.fields.get(model.title) if model else "") or "Something new"
        space_model, space_id, space = _space_of(state, record)
        quill, screen = _screen_of(state, record.model)
        url = f"#/q/{quill}/{screen['id']}/{space_id}" if quill else ""
        name = str(space.fields.get(state.quills.datamodels[space_model].title) or "") if space else ""
        # Between two people the name is the writer: the phone says who, then
        # what. Anywhere else, who and where.
        if between_people(screen, space):
            title = record.owner
        else:
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
