"""Administration → Access, and Me → Add a device.

An administrator sees how the cloud is reached and links it to a
cloudmorrow.com account (a code to enter on the website) or unlinks it.
Everybody signed in can see how the cloud is reached and, once it is on its
mesh, invite a device, get a key for one of their computers, and see and
remove their own devices. Whose a device is comes from the box's own labels
(`access_labels`), never from the relay, so a person sees theirs and an
administrator sees all of them.

Every handler is a plain def: they call the relay and tailscale, and
FastAPI runs them on a worker thread, off the event loop.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from cloudmorrow.server.access_ways import Access, AccessError
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_admin_user, get_current_user, get_state

router = APIRouter(prefix="/api/access", tags=["access"])


class MineRequest(BaseModel):
    # The computer's address on the mesh, which tailscale on it knows.
    address: str = Field(min_length=1, max_length=64)
    # What the person calls it: "laptop", "Anna's desktop".
    device: str = Field(default="", max_length=60)


class PublicRequest(BaseModel):
    public: bool


class LabelRequest(BaseModel):
    owner: str = Field(default="", max_length=64)
    device: str = Field(default="", max_length=60)


def _access(state: AppState) -> Access:
    access = state.access
    if access is None:  # pragma: no cover - create_app always makes one
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "access is not set up")
    return access


def _fail(exc: AccessError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("")
def read_access(state: AppState = Depends(get_state), user: User = Depends(get_current_user)) -> dict:
    """How this cloud is reached. Administrators see the link, the mesh and Caddy too."""
    return _access(state).status(admin=user.is_admin)


@router.post("/link")
def start_link(state: AppState = Depends(get_state), _: User = Depends(get_admin_user)) -> dict:
    """A code to enter at cloudmorrow.com/link. The box waits for it on its own."""
    access = _access(state)
    try:
        access.link()
    except AccessError as exc:
        raise _fail(exc) from exc
    return access.status(admin=True)


@router.delete("/link")
def cancel_link(state: AppState = Depends(get_state), _: User = Depends(get_admin_user)) -> dict:
    """Stop waiting for a code nobody entered."""
    access = _access(state)
    access.cancel_link()
    return access.status(admin=True)


@router.post("/unlink")
def unlink(state: AppState = Depends(get_state), _: User = Depends(get_admin_user)) -> dict:
    """Give the name back: the mesh and every device on it go too. The home network stays."""
    access = _access(state)
    try:
        access.unlink()
    except AccessError as exc:
        raise _fail(exc) from exc
    return access.status(admin=True)


@router.post("/setup")
def set_up(state: AppState = Depends(get_state), _: User = Depends(get_admin_user)) -> dict:
    """Try again to put a linked box on its mesh, after fixing what stopped it."""
    access = _access(state)
    try:
        access.set_up()
    except AccessError as exc:
        raise _fail(exc) from exc
    return access.status(admin=True)


@router.put("/public")
def set_public(
    payload: PublicRequest,
    state: AppState = Depends(get_state),
    user: User = Depends(get_admin_user),
) -> dict:
    """Reachable from anywhere, through the relay, or only at home and on the mesh."""
    return _access(state).set_reachable(payload.public, changed_by=user.username)


@router.post("/mesh/key")
def mesh_key(state: AppState = Depends(get_state), _: User = Depends(get_current_user)) -> dict:
    """A one-time key for one of the signed-in person's computers, and the name it joins as."""
    try:
        return _access(state).mesh_key()
    except AccessError as exc:
        raise _fail(exc) from exc


@router.post("/mesh/invite")
def mesh_invite(state: AppState = Depends(get_state), _: User = Depends(get_current_user)) -> dict:
    """A six-character code, good once, for ten minutes: for a computer's installer or a phone."""
    try:
        return _access(state).invite()
    except AccessError as exc:
        raise _fail(exc) from exc


@router.post("/mesh/mine")
def claim_device(
    payload: MineRequest,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    """The computer at this mesh address is the signed-in person's: the box labels it so."""
    try:
        return _access(state).claim_device(user.username, payload.address, payload.device)
    except AccessError as exc:
        raise _fail(exc) from exc


@router.get("/mesh/devices")
def mesh_devices(
    everyone: bool = False,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    """The person's devices; an administrator's `?everyone=true` is all of them."""
    whose = None if (everyone and user.is_admin) else user.username
    try:
        return {"devices": _access(state).devices(whose)}
    except AccessError as exc:
        raise _fail(exc) from exc


@router.put("/mesh/devices/{device_id}")
def label_device(
    device_id: str,
    payload: LabelRequest,
    state: AppState = Depends(get_state),
    _: User = Depends(get_admin_user),
) -> dict:
    """Say whose a device is, and what it is called. Kept on the box, never sent to the relay."""
    try:
        return _access(state).label_device(device_id, payload.owner, payload.device)
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
