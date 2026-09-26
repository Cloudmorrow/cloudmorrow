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

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from cloudmorrow.server.backends import AttachmentTooBig
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
people_router = APIRouter(prefix="/api/people", tags=["records"])


class RecordIn(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict)
    # Where in its group it goes, for an ordered datamodel.
    index: int | None = None
    # For a space: personal, shared or public. Chosen when it is made.
    scope: str | None = None


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
    if isinstance(getattr(exc, "status", None), int):
        return HTTPException(exc.status, str(exc))
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

    Two are not filters: `q` keeps the records whose text holds it (a
    backend searches its own way), and `previews=true` puts a line of each
    record's text on it as `preview`. With `q`, the preview is the line
    that matched.
    """
    switched_on(state, model)
    principal = person(user)
    try:
        seed(state, principal, model)
        records = state.records.list(principal, model, dict(request.query_params))
    except ERRORS as exc:
        raise _refused(exc) from exc
    return [record.to_dict() for record in records]


# -- folders and attachments, for a datamodel whose backend has them -------------------
# Before the record routes: `_folders` is not a record id (none starts with
# an underscore), and the first route that matches is the one that answers.
class FolderIn(BaseModel):
    path: str


class FolderMove(BaseModel):
    path: str
    to: str


@router.get("/{model}/_folders")
def list_folders(
    model: str, state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> list[dict]:
    """Every folder, empty ones too, parents before what is in them."""
    switched_on(state, model)
    try:
        return state.records.folders(person(user), model)
    except ERRORS as exc:
        raise _refused(exc) from exc


@router.post("/{model}/_folders", status_code=status.HTTP_201_CREATED)
def make_folder(
    model: str,
    payload: FolderIn,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    switched_on(state, model)
    try:
        return state.records.make_folder(person(user), model, payload.path)
    except ERRORS as exc:
        raise _refused(exc) from exc


@router.patch("/{model}/_folders")
def move_folder(
    model: str,
    payload: FolderMove,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    """Rename a folder, or move it into another: what is in it goes along."""
    switched_on(state, model)
    try:
        return state.records.move_folder(person(user), model, payload.path, payload.to)
    except ERRORS as exc:
        raise _refused(exc) from exc


@router.delete("/{model}/_folders", status_code=status.HTTP_204_NO_CONTENT)
def delete_folder(
    model: str,
    path: str,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> None:
    """A folder, and everything in it."""
    switched_on(state, model)
    try:
        state.records.delete_folder(person(user), model, path)
    except ERRORS as exc:
        raise _refused(exc) from exc


@router.post("/{model}/_attachments", status_code=status.HTTP_201_CREATED)
async def attach(
    model: str,
    request: Request,
    filename: str = "",
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    """Keep a file beside the records. The body is the file, not a form around it.

    Answers `{name, path, size, content_type}`; `path` is what Markdown
    writes to show it — a note's `![alt](img/<name>)`.
    """
    switched_on(state, model)
    data = await request.body()
    try:
        return state.records.attach(person(user), model, data, filename)
    except AttachmentTooBig as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)) from exc
    except ERRORS as exc:
        raise _refused(exc) from exc


@router.get("/{model}/_attachments/{name}")
def attachment(
    model: str,
    name: str,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> Response:
    switched_on(state, model)
    try:
        data, content_type = state.records.attachment(person(user), model, name)
    except UnknownRecordError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such attachment") from exc
    except ERRORS as exc:
        raise _refused(exc) from exc
    # A name is never reused for another file, so it may be kept for good.
    return Response(
        data, media_type=content_type,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


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
            person(user), model, payload.fields, index=payload.index, scope=payload.scope
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


# -- content: the bytes beside a record -------------------------------------------
# For a datamodel whose backend keeps bytes beside the fields — a file's. The
# same three calls for any such datamodel, so the kit that shows files asks
# for a record's bytes the way it asks for its fields.
PRIVATE = {"Cache-Control": "private, no-cache"}


@router.get("/{model}/{record_id}/content")
def record_content(
    model: str,
    record_id: str,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> FileResponse:
    """The record's bytes: a file, as itself."""
    switched_on(state, model)
    try:
        path, media_type = state.records.content(person(user), model, record_id)
    except ERRORS as exc:
        raise _refused(exc) from exc
    # Someone's files: nobody's cache but the browser's own, and asked about
    # again next time — a cheap 304 when nothing changed.
    return FileResponse(path, media_type=media_type, headers=PRIVATE)


@router.get("/{model}/{record_id}/thumb")
def record_thumb(
    model: str,
    record_id: str,
    size: int = Query(default=256, ge=1, description="The long edge wanted, in pixels"),
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> FileResponse:
    """A small copy of the record's picture, as a JPEG. A 415 for one that is not
    a picture the server can make small, and the client shows an icon instead."""
    switched_on(state, model)
    try:
        path = state.records.thumbnail(person(user), model, record_id, size)
    except ERRORS as exc:
        raise _refused(exc) from exc
    return FileResponse(path, media_type="image/jpeg", headers=PRIVATE)


@router.post("/{model}/upload", status_code=status.HTTP_201_CREATED)
async def upload_record(
    model: str,
    request: Request,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    """A new record from bytes: the body is the file, the query says where it
    goes and what it is called (`?share=my-files&folder=Photos&name=cat.jpg`).

    Streamed to disk first and handed over whole, so a dropped connection
    leaves nothing behind with the file's name.
    """
    switched_on(state, model)
    try:
        if not state.records.has_content(model):
            raise RecordError(f"{model} records are not made from bytes")
    except ERRORS as exc:
        raise _refused(exc) from exc
    spool = state.config.data_dir / "uploads"
    spool.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(dir=spool, prefix=".upload-", delete=False)
    part = Path(handle.name)
    try:
        with handle:
            async for chunk in request.stream():
                handle.write(chunk)
        try:
            record = state.records.put(person(user), model, dict(request.query_params), part)
        except ERRORS as exc:
            raise _refused(exc) from exc
    finally:
        part.unlink(missing_ok=True)
    return record.to_dict()


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


# -- who a space could be shared with ------------------------------------------------
@people_router.get("")
def list_people(
    state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> list[dict]:
    """Everybody a space could be shared with: the people on this server, not you.

    What a "Share with" list is drawn from — for a calendar, a channel, any
    space a Quill has. Machines and service accounts are not people.
    """
    return [
        {"username": u.username, "display_name": u.display_name or u.username}
        for u in state.users.list()
        if u.is_active and u.user_type == "human" and u.username != user.username
    ]
