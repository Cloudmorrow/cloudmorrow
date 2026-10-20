"""Roles: who is responsible for what (roles.py, docs/FLOWS.md).

Everybody may see the roles and who holds them — a Quill's screen says
who the Product owner is — and administrators change them. A role gives
no access to any data; circles do that, next door.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_admin_user, get_current_user, get_state
from cloudmorrow.server.roles import RoleError, UnknownRoleError

router = APIRouter(prefix="/api/roles", tags=["roles"])
mine_router = APIRouter(prefix="/api/me/roles", tags=["roles"])


class RoleIn(BaseModel):
    name: str
    description: str = ""


class RoleChange(BaseModel):
    name: str | None = None
    description: str | None = None


def _roles(state: AppState):
    if state.roles is None:  # pragma: no cover - every app has them
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "roles are not set up")
    return state.roles


def _failed(exc: Exception) -> HTTPException:
    if isinstance(exc, UnknownRoleError):
        return HTTPException(status.HTTP_404_NOT_FOUND, f"no role called {exc}")
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@mine_router.get("")
def my_roles(state: AppState = Depends(get_state), user: User = Depends(get_current_user)) -> dict:
    """The hats you wear, and where."""
    return {"username": user.username, "roles": _roles(state).roles_of(user.username)}


@router.get("")
def list_roles(state: AppState = Depends(get_state), _: User = Depends(get_current_user)) -> list[dict]:
    """Every role, with who holds it. The Quill that declared one is named."""
    return [role.to_dict() for role in _roles(state).list()]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_role(payload: RoleIn, state: AppState = Depends(get_state), _: User = Depends(get_admin_user)) -> dict:
    try:
        return _roles(state).create(payload.name, payload.description).to_dict()
    except RoleError as exc:
        raise _failed(exc) from exc


@router.get("/{role_id}")
def get_role(role_id: str, state: AppState = Depends(get_state), _: User = Depends(get_current_user)) -> dict:
    try:
        return _roles(state).get(role_id).to_dict()
    except UnknownRoleError as exc:
        raise _failed(exc) from exc


@router.patch("/{role_id}")
def update_role(
    role_id: str, payload: RoleChange, state: AppState = Depends(get_state), _: User = Depends(get_admin_user)
) -> dict:
    try:
        return _roles(state).update(role_id, name=payload.name, description=payload.description).to_dict()
    except (RoleError, UnknownRoleError) as exc:
        raise _failed(exc) from exc


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(role_id: str, state: AppState = Depends(get_state), _: User = Depends(get_admin_user)) -> None:
    """Delete a role. One a Quill declared comes back, empty, the next time the Quills are read."""
    try:
        _roles(state).delete(role_id)
    except UnknownRoleError as exc:
        raise _failed(exc) from exc


@router.put("/{role_id}/holders/{username}")
def give_role(
    role_id: str,
    username: str,
    circle: str = Query(default="", description="Hold it within this circle only; empty is everywhere."),
    state: AppState = Depends(get_state),
    _: User = Depends(get_admin_user),
) -> dict:
    try:
        return _roles(state).give(role_id, username, circle).to_dict()
    except (RoleError, UnknownRoleError) as exc:
        raise _failed(exc) from exc


@router.delete("/{role_id}/holders/{username}")
def take_role(
    role_id: str,
    username: str,
    circle: str = Query(default="", description="Where they held it; empty is everywhere."),
    state: AppState = Depends(get_state),
    _: User = Depends(get_admin_user),
) -> dict:
    try:
        return _roles(state).take(role_id, username, circle).to_dict()
    except (RoleError, UnknownRoleError) as exc:
        raise _failed(exc) from exc
