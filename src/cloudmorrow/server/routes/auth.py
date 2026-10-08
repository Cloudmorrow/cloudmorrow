"""Login and self-service account endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_current_user, get_state
from cloudmorrow.server.schemas import LoginRequest, PasswordChange, TokenResponse, UserOut
from cloudmorrow.server.security import (
    create_access_token,
    hash_password,
    needs_rehash,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def user_out(user: User) -> UserOut:
    return UserOut(
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        user_type=user.user_type,
        is_admin=user.is_admin,
        is_active=user.is_active,
        system_uid=user.system_uid,
        created_at=user.created_at,
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, state: AppState = Depends(get_state)) -> TokenResponse:
    # Too many wrong passwords from here, or for this account (signin_limits).
    limits = request.app.state.signin_limits
    address = request.client.host if request.client else ""
    wait = limits.retry_after(address, payload.username)
    if wait:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"too many wrong passwords; try again in {max(1, round(wait / 60))} minutes",
            headers={"Retry-After": str(wait)},
        )
    user = state.users.get(payload.username)
    invalid = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid username or password")
    if user is None or not user.is_active:
        # Spend the time anyway so a missing user is not obviously faster.
        hash_password("not-a-real-password")
        limits.failed(address, payload.username)
        raise invalid
    if not verify_password(payload.password, user.password_hash):
        limits.failed(address, payload.username)
        raise invalid
    if needs_rehash(user.password_hash):
        state.users.update(user.username, password_hash=hash_password(payload.password))
    # Make sure the user's drive exists the moment they log in.
    state.ensure_drive(user.username)
    issued = create_access_token(user.username, state.config.ensure_secret_key(), state.config.token_ttl_hours)
    return TokenResponse(access_token=issued.token, expires_at=issued.expires_at, user=user_out(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return user_out(user)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChange,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> None:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="current password is wrong")
    state.users.update(user.username, password_hash=hash_password(payload.new_password))
