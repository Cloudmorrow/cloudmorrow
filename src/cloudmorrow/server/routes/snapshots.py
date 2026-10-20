"""Snapshots and attestations over HTTP (snapshots.py, docs/ATTESTATIONS.md).

`/api/snapshots` is for people on the server: take one of a space, read it,
fetch its bundle, bring an attestation back, withdraw it, and give somebody
outside a link to it. `/api/guest/snapshots/{id}?token=` is what that link
opens: the one snapshot, its bundle, and a door to leave an attestation
through — nothing else on the server. `/api/attest` signs an attestation
with this server's own identity, for one of its own people validating a
snapshot somebody sent them; `/api/identity` is the public half of that key.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from cloudmorrow.server import crypto
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_current_user, get_principal, get_state
from cloudmorrow.server.records import Principal
from cloudmorrow.server.routes.errors import ERRORS, http_error
from cloudmorrow.server.snapshots import GUEST_DAYS, SnapshotStore, verify_attestation

router = APIRouter(prefix="/api/snapshots", tags=["snapshots"])
guest_router = APIRouter(prefix="/api/guest/snapshots", tags=["snapshots"])
attest_router = APIRouter(prefix="/api", tags=["snapshots"])


class TakeIn(BaseModel):
    # The space to copy: its datamodel and its id.
    space_model: str
    space_id: str
    title: str = ""
    series: str = ""
    # The datamodels in the space to copy; none is every one.
    models: list[str] = Field(default_factory=list)
    # {field, from, to}: only the records in that range, and what hangs off them.
    period: dict[str, Any] | None = None
    notes: str = ""
    # The snapshot's own scope, and who is in it when shared.
    scope: str | None = None
    members: list[str] = Field(default_factory=list)


class GuestIn(BaseModel):
    label: str = ""
    days: int = GUEST_DAYS


class SignIn(BaseModel):
    digest: str
    snapshot: str = ""
    series: str = ""
    version: int = 0
    verdict: str
    statement: str = ""


def _snapshots(state: AppState) -> SnapshotStore:
    if state.snapshots is None:  # pragma: no cover - every app has them
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "snapshots are not set up")
    return state.snapshots


def _filename(told: dict) -> str:
    return f"snapshot-{told['snapshot']['id']}.json"


# -- for people on the server --------------------------------------------------------
@router.post("", status_code=status.HTTP_201_CREATED)
def take(body: TakeIn, state: AppState = Depends(get_state), principal: Principal = Depends(get_principal)) -> dict:
    """Copy a space's records into a sealed snapshot, and say what was made."""
    store = _snapshots(state)
    try:
        made = store.take(
            principal,
            body.space_model,
            body.space_id,
            title=body.title,
            series=body.series,
            models=body.models,
            period=body.period,
            notes=body.notes,
            scope=body.scope,
            members=body.members,
        )
        return store.describe(principal, made.id)
    except ERRORS as exc:
        raise http_error(exc) from exc


@router.get("/{snapshot_id}")
def describe(
    snapshot_id: str, state: AppState = Depends(get_state), principal: Principal = Depends(get_principal)
) -> dict:
    """The snapshot, its attestations, whether its bundle is intact, and its guest links."""
    try:
        return _snapshots(state).describe(principal, snapshot_id)
    except ERRORS as exc:
        raise http_error(exc) from exc


@router.get("/{snapshot_id}/bundle")
def bundle(
    snapshot_id: str, state: AppState = Depends(get_state), principal: Principal = Depends(get_principal)
) -> Response:
    """The bundle's bytes, exactly as they were hashed."""
    try:
        data, digest = _snapshots(state).bundle(principal, snapshot_id)
    except ERRORS as exc:
        raise http_error(exc) from exc
    return _bundle_response(data, digest, snapshot_id)


def _bundle_response(data: bytes, digest: str, snapshot_id: str) -> Response:
    return Response(
        data,
        media_type="application/json",
        headers={
            "X-Snapshot-Digest": digest,
            "Content-Disposition": f'attachment; filename="snapshot-{snapshot_id}.json"',
        },
    )


@router.post("/{snapshot_id}/withdraw")
def withdraw(
    snapshot_id: str, state: AppState = Depends(get_state), principal: Principal = Depends(get_principal)
) -> dict:
    """Mark it as not to be relied on. It stays, locked, with its attestations."""
    store = _snapshots(state)
    try:
        store.withdraw(principal, snapshot_id)
        return store.describe(principal, snapshot_id)
    except ERRORS as exc:
        raise http_error(exc) from exc


@router.post("/{snapshot_id}/attestations", status_code=status.HTTP_201_CREATED)
def attest(
    snapshot_id: str,
    document: dict[str, Any],
    state: AppState = Depends(get_state),
    principal: Principal = Depends(get_principal),
) -> dict:
    """Bring an attestation back: checked against the digest, then kept."""
    try:
        return _snapshots(state).attest(principal, snapshot_id, document).to_dict()
    except ERRORS as exc:
        raise http_error(exc) from exc


@router.post("/{snapshot_id}/guests", status_code=status.HTTP_201_CREATED)
def invite(
    snapshot_id: str,
    body: GuestIn,
    state: AppState = Depends(get_state),
    principal: Principal = Depends(get_principal),
) -> dict:
    """A link that opens this one snapshot to somebody outside. Shown once."""
    try:
        return _snapshots(state).invite(principal, snapshot_id, label=body.label, days=body.days)
    except ERRORS as exc:
        raise http_error(exc) from exc


@router.get("/{snapshot_id}/guests")
def guests(
    snapshot_id: str, state: AppState = Depends(get_state), principal: Principal = Depends(get_principal)
) -> list[dict]:
    try:
        return _snapshots(state).guests(principal, snapshot_id)
    except ERRORS as exc:
        raise http_error(exc) from exc


@router.delete("/{snapshot_id}/guests/{guest_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke(
    snapshot_id: str,
    guest_id: int,
    state: AppState = Depends(get_state),
    principal: Principal = Depends(get_principal),
) -> None:
    try:
        _snapshots(state).revoke(principal, snapshot_id, guest_id)
    except ERRORS as exc:
        raise http_error(exc) from exc


# -- for somebody outside, with a link -------------------------------------------------
def get_guest(
    snapshot_id: str,
    token: str = Query(default=""),
    request: Request = None,  # type: ignore[assignment]
    state: AppState = Depends(get_state),
) -> Principal:
    """Who a guest link's bearer is: the snapshot owner's guest, at that snapshot."""
    bearer = token or _bearer(request)
    guest = _snapshots(state).guest_for(snapshot_id, bearer)
    if guest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such snapshot, or the link is spent")
    return guest


def _bearer(request: Request | None) -> str:
    header = request.headers.get("authorization", "") if request is not None else ""
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


@guest_router.get("/{snapshot_id}")
def guest_describe(
    snapshot_id: str, state: AppState = Depends(get_state), guest: Principal = Depends(get_guest)
) -> dict:
    """The snapshot and its attestations, as the link shows them."""
    try:
        return _snapshots(state).describe(guest, snapshot_id, guests=False)
    except ERRORS as exc:
        raise http_error(exc) from exc


@guest_router.get("/{snapshot_id}/bundle")
def guest_bundle(
    snapshot_id: str, state: AppState = Depends(get_state), guest: Principal = Depends(get_guest)
) -> Response:
    try:
        data, digest = _snapshots(state).bundle(guest, snapshot_id)
    except ERRORS as exc:
        raise http_error(exc) from exc
    return _bundle_response(data, digest, snapshot_id)


@guest_router.post("/{snapshot_id}/attestations", status_code=status.HTTP_201_CREATED)
def guest_attest(
    snapshot_id: str,
    document: dict[str, Any],
    state: AppState = Depends(get_state),
    guest: Principal = Depends(get_guest),
) -> dict:
    """Leave an attestation through the link: checked against the digest, then kept."""
    try:
        return _snapshots(state).attest(guest, snapshot_id, document).to_dict()
    except ERRORS as exc:
        raise http_error(exc) from exc


# -- signing with this server's identity ---------------------------------------------
@attest_router.get("/identity")
def identity(state: AppState = Depends(get_state), _: User = Depends(get_current_user)) -> dict:
    """This server's signing key, public half, and the name a stamp given under it carries."""
    key = _snapshots(state).identity_key()
    return {"key": key, "fingerprint": crypto.key_fingerprint(key), "name": state.cloud_name()}


@attest_router.post("/attest")
def sign(body: SignIn, state: AppState = Depends(get_state), user: User = Depends(get_current_user)) -> dict:
    """An attestation on a digest, signed with this server's identity in your name.

    For validating a snapshot somebody sent you, without a key of your own:
    the signer is you, the organisation is this cloud's name. The document
    comes back to send on, or to hand `cm attest send`.
    """
    try:
        document = _snapshots(state).sign(
            user.username,
            user.display_name,
            state.cloud_name(),
            digest=body.digest,
            snapshot=body.snapshot,
            series=body.series,
            version=body.version,
            verdict=body.verdict,
            statement=body.statement,
        )
        return verify_attestation(document)
    except ERRORS as exc:
        raise http_error(exc) from exc
