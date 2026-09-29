"""Administration → Access, and Me → Pair a device.

An administrator sees the three ways in and changes them: claims, renames
or gives back the name, turns public and private access on and off.
Everybody signed in can see how the cloud is reached, and — while private
access is on — get a key for a computer or a pairing code for a phone, and
see and remove their own enrolled devices. Whose a device is comes from
the label its key was minted with (`<username>: <device>`), so a person
sees theirs and an administrator sees all of them.

Every handler is a plain def: they call the control server and tailscale,
and FastAPI runs them on a worker thread, off the event loop.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from cloudmorrow.server.access_ways import Access, AccessError
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_admin_user, get_current_user, get_state

router = APIRouter(prefix="/api/access", tags=["access"])


class ClaimRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    # Claimed from Administration, a name is for public access unless said.
    public: bool = True
    private: bool = False


class SwitchRequest(BaseModel):
    on: bool


class RenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class DeviceRequest(BaseModel):
    # What the person calls the device: "laptop", "Anna's phone".
    device: str = Field(default="", max_length=60)


def _access(state: AppState) -> Access:
    access = state.access
    if access is None:  # pragma: no cover - create_app always makes one
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "access is not set up")
    return access


def _fail(exc: AccessError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("")
def read_access(
    state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> dict:
    """How this cloud is reached. Administrators see the tunnel, the mesh and Caddy too."""
    return _access(state).status(admin=user.is_admin)


@router.post("/name")
def claim_name(
    payload: ClaimRequest, state: AppState = Depends(get_state), _: User = Depends(get_admin_user)
) -> dict:
    """Claim a name at the control server (enrolling the cloud), or move to another."""
    access = _access(state)
    try:
        access.claim(payload.name, public=payload.public, private=payload.private)
    except AccessError as exc:
        raise _fail(exc) from exc
    return access.status(admin=True)


@router.patch("/name")
def rename(
    payload: RenameRequest, state: AppState = Depends(get_state), _: User = Depends(get_admin_user)
) -> dict:
    access = _access(state)
    try:
        access.rename(payload.name)
    except AccessError as exc:
        raise _fail(exc) from exc
    return access.status(admin=True)


@router.delete("/name")
def release_name(
    state: AppState = Depends(get_state), _: User = Depends(get_admin_user)
) -> dict:
    """Give the name back: public and private access end, and the devices are forgotten."""
    access = _access(state)
    try:
        access.release()
    except AccessError as exc:
        raise _fail(exc) from exc
    return access.status(admin=True)


@router.put("/public")
def switch_public(
    payload: SwitchRequest, state: AppState = Depends(get_state), _: User = Depends(get_admin_user)
) -> dict:
    access = _access(state)
    try:
        access.set_public(payload.on)
    except AccessError as exc:
        raise _fail(exc) from exc
    return access.status(admin=True)


@router.put("/private")
def switch_private(
    payload: SwitchRequest, state: AppState = Depends(get_state), _: User = Depends(get_admin_user)
) -> dict:
    access = _access(state)
    try:
        access.set_private(payload.on)
    except AccessError as exc:
        raise _fail(exc) from exc
    return access.status(admin=True)


@router.post("/mesh/key")
def mesh_key(
    payload: DeviceRequest,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    """A one-time key for one of the signed-in person's computers to join with."""
    try:
        return _access(state).mesh_key(user.username, payload.device or "a computer")
    except AccessError as exc:
        raise _fail(exc) from exc


@router.post("/mesh/pair")
def mesh_pair(
    payload: DeviceRequest,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    """A six-character code for a phone's Tailscale app, good once, for ten minutes."""
    try:
        return _access(state).pair(user.username, payload.device or "a phone")
    except AccessError as exc:
        raise _fail(exc) from exc


@router.get("/mesh/devices")
def mesh_devices(
    everyone: bool = False,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    """The person's enrolled devices; an administrator's `?everyone=true` is all of them."""
    whose = None if (everyone and user.is_admin) else user.username
    try:
        return {"devices": _access(state).devices(whose)}
    except AccessError as exc:
        raise _fail(exc) from exc


@router.delete("/mesh/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_device(
    device_id: str,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> Response:
    try:
        _access(state).remove_device(device_id, None if user.is_admin else user.username)
    except AccessError as exc:
        raise _fail(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
