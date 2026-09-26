"""Records of every installed datamodel, at one address.

`/api/records/{model}` is the whole data API a Quill gets: list, create,
read, change, move and delete, the same for a task as for anything a Quill
introduces tomorrow. Every call goes through the gate as the person signed
in, and a record is only ever reached through its owner.

Listing a datamodel is also when its per-owner datasets are seeded — your
first board — and when its expire jobs sweep, so both hold without anything
having to run in between.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_current_user, get_state
from cloudmorrow.server.records import (
    Principal,
    RecordConflictError,
    RecordError,
    Refused,
    UnknownModelError,
    UnknownRecordError,
)

router = APIRouter(prefix="/api/records", tags=["records"])
models_router = APIRouter(prefix="/api/datamodels", tags=["records"])


class RecordIn(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict)
    # Where in its group it goes, for an ordered datamodel.
    index: int | None = None
    # For a space: personal, shared or public. Chosen when it is made.
    scope: str | None = None
    # For a shared space: the people in it besides you, from the start.
    members: list[str] = Field(default_factory=list)
    # For a space: find the one with exactly these people in it (and these
    # indexed fields) before making another — "write to somebody".
    unique: bool = False


class MemberIn(BaseModel):
    username: str


class RecordChange(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict)
    # The revision the caller had. Sent, a stale write is a 409, not a loss.
    # A counter for most records; a note's is a string.
    rev: int | str | None = None


class RecordMove(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict)
    index: int | None = None


def _refused(exc: Exception) -> HTTPException:
    if isinstance(exc, UnknownModelError):
        return HTTPException(status.HTTP_404_NOT_FOUND, f"no such datamodel: {exc}")
    if isinstance(exc, UnknownRecordError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "no such record")
    if isinstance(exc, Refused):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, RecordConflictError):
        return HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": "changed since you read it", "current": exc.current.to_dict()},
        )
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


ERRORS = (UnknownModelError, UnknownRecordError, Refused, RecordConflictError, RecordError)


def switched_on(state: AppState, model: str) -> None:
    """Refuse a datamodel whose every Quill an administrator has switched off.

    Off means off everywhere, as it always has for a feature: the tab goes
    and the door closes. The records are not touched, and a datamodel some
    other Quill that is still on uses stays open.
    """
    users = state.quills.users_of(model)
    if users and not any(state.features.enabled(quill) for quill in users):
        names = ", ".join(state.quills.quills[q].name for q in users)
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"{names} is switched off on this server")


def person(user: User) -> Principal:
    return Principal.person(user.username, admin=user.is_admin)


def seed(state: AppState, principal: Principal, model: str) -> None:
    """Write any dataset for *model* not written yet: per person, or once per server."""
    for manifest, dataset in state.quills.seeds_for(model):
        state.records.seed(
            principal, model, dataset["records"], writer=manifest.id,
            once=dataset["seed"] == "once", scope=dataset.get("scope"),
        )


@models_router.get("")
def list_datamodels(
    state: AppState = Depends(get_state), _: User = Depends(get_current_user)
) -> list[dict]:
    """Every datamodel on this server, foundational first, with who uses each."""
    return state.quills.catalogue_of_models()


@router.get("/{model}")
def list_records(
    model: str,
    request: Request,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Every record of *model* you have. Query parameters filter on indexed fields.

    Two are not fields, and start with `_` so no field can be called them:
    `_last=50` keeps the newest fifty, still in order — a conversation's
    first page — and `_since=<ISO time>` only what was made or changed at or
    after it, which is how an open screen asks what it has not got.
    """
    switched_on(state, model)
    principal = person(user)
    where = dict(request.query_params)
    last = where.pop("_last", None)
    since = where.pop("_since", None)
    try:
        seed(state, principal, model)
        records = state.records.list(
            principal, model, where, last=_whole(last), since=since or None
        )
    except ERRORS as exc:
        raise _refused(exc) from exc
    return [record.to_dict() for record in records]


def _whole(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "_last is a whole number") from None


@router.post("/{model}", status_code=status.HTTP_201_CREATED)
def create_record(
    model: str,
    payload: RecordIn,
    response: Response,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    """Make a record. A space may be made with its people in it, or found.

    With `unique`, a space with exactly you and `members` in it, and the same
    indexed fields, is answered (200) instead of a second one being made
    (201): the conversation between two people is one conversation from
    either side. Its people are not told they were added — the first thing
    written in it tells them.
    """
    switched_on(state, model)
    for username in payload.members:
        _known(state, username)
    principal = person(user)
    try:
        if payload.unique:
            found = state.records.find_space(
                principal, model, payload.fields, scope=payload.scope, members=payload.members
            )
            if found is not None:
                response.status_code = status.HTTP_200_OK
                return found.to_dict()
        record = state.records.create(
            principal,
            model,
            payload.fields,
            index=payload.index,
            scope=payload.scope,
            members=payload.members,
            announce=not payload.unique,
        )
    except ERRORS as exc:
        raise _refused(exc) from exc
    return record.to_dict()


@router.get("/{model}/{record_id}")
def get_record(
    model: str,
    record_id: str,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    switched_on(state, model)
    try:
        return state.records.get(person(user), model, record_id).to_dict()
    except ERRORS as exc:
        raise _refused(exc) from exc


@router.patch("/{model}/{record_id}")
def change_record(
    model: str,
    record_id: str,
    payload: RecordChange,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    switched_on(state, model)
    try:
        record = state.records.update(
            person(user), model, record_id, payload.fields, rev=payload.rev
        )
    except ERRORS as exc:
        raise _refused(exc) from exc
    return record.to_dict()


@router.post("/{model}/{record_id}/move")
def move_record(
    model: str,
    record_id: str,
    payload: RecordMove,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    """Change the fields that say which group, and the place in it: a dragged card."""
    switched_on(state, model)
    try:
        record = state.records.move(
            person(user), model, record_id, payload.fields, payload.index
        )
    except ERRORS as exc:
        raise _refused(exc) from exc
    return record.to_dict()


@router.delete("/{model}/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_record(
    model: str,
    record_id: str,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> None:
    switched_on(state, model)
    try:
        state.records.delete(person(user), model, record_id)
    except ERRORS as exc:
        raise _refused(exc) from exc


# -- the people in a space ---------------------------------------------------------
def _known(state: AppState, username: str) -> None:
    if state.users.get(username) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no such account: {username}")


@router.post("/{model}/{record_id}/members")
def add_member(
    model: str,
    record_id: str,
    payload: MemberIn,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    """Put somebody in a shared space. They are told; there is nothing to accept."""
    switched_on(state, model)
    _known(state, payload.username)
    try:
        return state.records.add_member(person(user), model, record_id, payload.username).to_dict()
    except ERRORS as exc:
        raise _refused(exc) from exc


@router.delete("/{model}/{record_id}/members/{username}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    model: str,
    record_id: str,
    username: str,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> None:
    """Take somebody out of a shared space, or, with your own name, leave it."""
    switched_on(state, model)
    try:
        state.records.remove_member(person(user), model, record_id, username)
    except ERRORS as exc:
        raise _refused(exc) from exc


@router.post("/{model}/{record_id}/seen", status_code=status.HTTP_204_NO_CONTENT)
def seen(
    model: str,
    record_id: str,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> None:
    """You have looked in this space: what is in it is not unread any more."""
    try:
        state.records.mark_seen(person(user), model, record_id)
    except ERRORS as exc:
        raise _refused(exc) from exc
