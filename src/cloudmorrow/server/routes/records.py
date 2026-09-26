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

from fastapi import APIRouter, Depends, HTTPException, Request, status
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


class RecordChange(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict)
    # The revision the caller had. Sent, a stale write is a 409, not a loss.
    rev: int | None = None


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


def seed(state: AppState, principal: Principal, model: str) -> None:
    """Write any per-owner dataset for *model* this person has not had yet."""
    for manifest, dataset in state.quills.seeds_for(model):
        state.records.seed(principal, model, dataset["records"], writer=manifest.id)


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
    """Every record of *model* you have. Query parameters filter on indexed fields."""
    switched_on(state, model)
    principal = Principal.person(user.username)
    try:
        seed(state, principal, model)
        records = state.records.list(principal, model, dict(request.query_params))
    except ERRORS as exc:
        raise _refused(exc) from exc
    return [record.to_dict() for record in records]


@router.post("/{model}", status_code=status.HTTP_201_CREATED)
def create_record(
    model: str,
    payload: RecordIn,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    switched_on(state, model)
    try:
        record = state.records.create(
            Principal.person(user.username), model, payload.fields, index=payload.index
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
        return state.records.get(Principal.person(user.username), model, record_id).to_dict()
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
            Principal.person(user.username), model, record_id, payload.fields, rev=payload.rev
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
            Principal.person(user.username), model, record_id, payload.fields, payload.index
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
        state.records.delete(Principal.person(user.username), model, record_id)
    except ERRORS as exc:
        raise _refused(exc) from exc
