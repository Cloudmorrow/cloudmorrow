"""User administration. Admin-only; the hook for system users lands here."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from cloudmorrow.server.db import (
    ROLE_ADMIN,
    InvalidRoleError,
    InvalidUsernameError,
    UnknownUserError,
    User,
    UserExistsError,
)
from cloudmorrow.server.deps import AppState, get_admin_user, get_state
from cloudmorrow.server.routes.auth import user_out
from cloudmorrow.server.schemas import UserCreate, UserOut, UserUpdate
from cloudmorrow.server.security import hash_password

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(
    state: AppState = Depends(get_state), _: User = Depends(get_admin_user)
) -> list[UserOut]:
    return [user_out(user) for user in state.users.list()]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    state: AppState = Depends(get_state),
    _: User = Depends(get_admin_user),
) -> UserOut:
    try:
        user = state.users.create(
            payload.username,
            hash_password(payload.password),
            display_name=payload.display_name,
            is_admin=payload.is_admin,
            role=payload.role,
            user_type=payload.user_type,
        )
    except UserExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="user exists") from exc
    except (InvalidUsernameError, InvalidRoleError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    state.note_store(user)
    return user_out(user)


@router.patch("/{username}", response_model=UserOut)
def update_user(
    username: str,
    payload: UserUpdate,
    state: AppState = Depends(get_state),
    admin: User = Depends(get_admin_user),
) -> UserOut:
    fields: dict[str, object] = payload.model_dump(exclude_none=True)
    password = fields.pop("password", None)
    if password is not None:
        fields["password_hash"] = hash_password(str(password))
    demoted = fields.get("is_admin") is False or (
        fields.get("role") is not None and fields["role"] != ROLE_ADMIN
    )
    if username == admin.username and demoted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="refusing to demote yourself"
        )
    try:
        return user_out(state.users.update(username, **fields))
    except UnknownUserError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such user") from exc
    except InvalidRoleError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{username}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    username: str,
    state: AppState = Depends(get_state),
    admin: User = Depends(get_admin_user),
) -> None:
    if username == admin.username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="refusing to delete yourself"
        )
    try:
        state.users.delete(username)
    except UnknownUserError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such user") from exc
    # Whatever they had switched off for themselves goes with them, so a
    # later account of the same name starts with the whole app.
    state.features.forget(username)
