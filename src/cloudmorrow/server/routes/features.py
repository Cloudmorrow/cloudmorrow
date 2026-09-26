"""Reading and switching features, at both levels.

`/api/server/features` is the server's own list: everybody signed in may
read it — a client has to know what this server is — and only an
administrator may switch one. `require_feature` is the other half of that:
hung on the routers that belong to a feature, so switching it off closes its
API rather than only hiding its buttons.

`/api/me/features` is the same catalogue narrowed to one person: only what
the server offers, with their own answer on each, and theirs to switch. That
one is a preference and hides rather than forbids — see the module docstring
in `features.py` for why the two switches are not the same kind of thing.
A client that draws tabs wants this list, not the other one.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, status

from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_admin_user, get_current_user, get_state
from cloudmorrow.server.features import BY_KEY, USES, UnknownFeatureError
from cloudmorrow.server.schemas import FeatureOut, FeatureUpdate, MyFeatureOut, TypeOut
from cloudmorrow.server.types import catalogue

router = APIRouter(prefix="/api/server/features", tags=["features"])
# Your own answers, under your own address: nothing here is an admin call.
mine_router = APIRouter(prefix="/api/me/features", tags=["features"])
# The kinds of data there are, which app provides each, and who reaches it.
types_router = APIRouter(prefix="/api/types", tags=["types"])


@types_router.get("", response_model=list[TypeOut])
def list_types(_: User = Depends(get_current_user)) -> list[TypeOut]:
    """Every kind of data on this server, foundation first, with who uses it."""
    return [TypeOut(**row) for row in catalogue(USES)]


def require_feature(key: str) -> Callable[..., None]:
    """A dependency that refuses every call when feature *key* is switched off."""

    def guard(state: AppState = Depends(get_state)) -> None:
        if not state.features.enabled(key):
            quill = state.quills.quills.get(key)
            label = BY_KEY[key].label if key in BY_KEY else quill.name if quill else key
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{label} is switched off on this server",
            )

    return guard


@router.get("", response_model=list[FeatureOut])
def list_features(
    state: AppState = Depends(get_state), _: User = Depends(get_current_user)
) -> list[FeatureOut]:
    return [FeatureOut(**row) for row in state.features.list()]


@router.patch("/{key}", response_model=FeatureOut)
def set_feature(
    key: str,
    payload: FeatureUpdate,
    state: AppState = Depends(get_state),
    admin: User = Depends(get_admin_user),
) -> FeatureOut:
    try:
        row = state.features.set(key, payload.enabled, changed_by=admin.username)
    except UnknownFeatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no such feature: {key}"
        ) from exc
    return FeatureOut(**row)


@mine_router.get("", response_model=list[MyFeatureOut])
def my_features(
    state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> list[MyFeatureOut]:
    """What you may switch, and what you have. Tabs are drawn from this."""
    return [MyFeatureOut(**row) for row in state.features.list_for(user.username)]


@mine_router.patch("/{key}", response_model=MyFeatureOut)
def set_my_feature(
    key: str,
    payload: FeatureUpdate,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> MyFeatureOut:
    """Switch one for yourself. A feature the server has off is not yours to switch."""
    try:
        row = state.features.set_for(user.username, key, payload.enabled)
    except UnknownFeatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no such feature: {key}"
        ) from exc
    return MyFeatureOut(**row)
