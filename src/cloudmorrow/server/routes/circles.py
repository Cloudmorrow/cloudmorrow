"""Circles: who may use which data. Administrators change them; everybody reads their own.

See docs/CIRCLES.md. The gate itself is in records.py and asks
`CircleStore.access_for`; what is here is the managing of circles, a
person's own access, and `require_data` for the routes that reach a
datamodel's data without the record store (notes, secrets, shares).
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from cloudmorrow.server.circles import CircleError, UnknownCircleError
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_admin_user, get_current_user, get_state

router = APIRouter(prefix="/api/circles", tags=["circles"])
mine_router = APIRouter(prefix="/api/me/access", tags=["circles"])
# One person's access, for an administrator: their own rules beside their circles.
person_router = APIRouter(prefix="/api/access", tags=["circles"])

READING = frozenset({"GET", "HEAD", "OPTIONS"})


class CircleIn(BaseModel):
    name: str
    rules: dict[str, str] = Field(default_factory=dict)
    members: list[str] = Field(default_factory=list)
    default: bool = False


class RuleIn(BaseModel):
    access: str


class CircleChange(BaseModel):
    name: str | None = None
    # Replaced whole when given.
    rules: dict[str, str] | None = None
    default: bool | None = None


def _circles(state: AppState):
    if state.circles is None:  # pragma: no cover - every app has them
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "circles are not set up")
    return state.circles


def _failed(exc: Exception) -> HTTPException:
    if isinstance(exc, UnknownCircleError):
        return HTTPException(status.HTTP_404_NOT_FOUND, f"no circle called {exc}")
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


def require_data(model: str) -> Callable[..., None]:
    """Refuse a route over *model*'s data to whoever's circles do not give it:
    reading needs read, anything else needs write. What the gate does for the
    record API, for the routes that came before it."""

    def guard(
        request: Request,
        state: AppState = Depends(get_state),
        user: User = Depends(get_current_user),
    ) -> None:
        if state.circles is None:
            return
        access = (state.shelf or state.circles).access_for(user.username)
        if not access.may("read", model):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
        if request.method not in READING and not access.may("write", model):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"you may read {model} records here, not change them")

    return guard


def _access_of(state: AppState, username: str) -> dict:
    circles = _circles(state)
    access = (state.shelf or circles).access_for(username)
    return {
        "username": username,
        "access": access.of(sorted(state.quills.datamodels)),
        "circles": [c.name for c in circles.circles_of(username)],
        # Their own rules, beside what their circles give; the most of all of it is `access`.
        "own": dict(access.own),
    }


@mine_router.get("")
def my_access(state: AppState = Depends(get_state), user: User = Depends(get_current_user)) -> dict:
    """What you may do with each datamodel on this server, and the circles — and
    rules of your own — that say so."""
    return _access_of(state, user.username)


@person_router.get("/{username}")
def access_of(username: str, state: AppState = Depends(get_state), _: User = Depends(get_admin_user)) -> dict:
    """One person's access: what their circles give, their own rules, and the most of both."""
    if state.users.get(username.strip().lower()) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"there is nobody called {username}")
    return _access_of(state, username.strip().lower())


class RulesIn(BaseModel):
    rules: dict[str, str] = Field(default_factory=dict)


@person_router.put("/{username}")
def set_person_rules(
    username: str,
    payload: RulesIn,
    state: AppState = Depends(get_state),
    _: User = Depends(get_admin_user),
) -> dict:
    """A person's own rules, replaced whole: what the accounts screen saves."""
    try:
        _circles(state).set_person_rules(username, payload.rules)
    except CircleError as exc:
        raise _failed(exc) from exc
    return _access_of(state, username.strip().lower())


@person_router.put("/{username}/{model}")
def set_person_rule(
    username: str,
    model: str,
    payload: RuleIn,
    state: AppState = Depends(get_state),
    _: User = Depends(get_admin_user),
) -> dict:
    """One rule of a person's own, the others kept: the three words circles use.
    `none` on `*` takes their `*` line away; a named `none` stays, since it
    beats a `*` of their own."""
    try:
        _circles(state).set_person_rule(username, model, payload.access)
    except CircleError as exc:
        raise _failed(exc) from exc
    return _access_of(state, username.strip().lower())


@person_router.delete("/{username}/{model}")
def clear_person_rule(
    username: str,
    model: str,
    state: AppState = Depends(get_state),
    _: User = Depends(get_admin_user),
) -> dict:
    """Take one of a person's own rules away: that datamodel follows their circles again."""
    _circles(state).clear_person_rule(username, model)
    return _access_of(state, username.strip().lower())


@router.get("")
def list_circles(state: AppState = Depends(get_state), _: User = Depends(get_admin_user)) -> list[dict]:
    return [circle.to_dict() for circle in _circles(state).list()]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_circle(payload: CircleIn, state: AppState = Depends(get_state), _: User = Depends(get_admin_user)) -> dict:
    try:
        circle = _circles(state).create(payload.name, payload.rules, payload.members, default=payload.default)
    except CircleError as exc:
        raise _failed(exc) from exc
    return circle.to_dict()


@router.get("/{circle_id}")
def get_circle(circle_id: str, state: AppState = Depends(get_state), _: User = Depends(get_admin_user)) -> dict:
    try:
        return _circles(state).get(circle_id).to_dict()
    except UnknownCircleError as exc:
        raise _failed(exc) from exc


@router.patch("/{circle_id}")
def update_circle(
    circle_id: str,
    payload: CircleChange,
    state: AppState = Depends(get_state),
    _: User = Depends(get_admin_user),
) -> dict:
    try:
        circle = _circles(state).update(circle_id, name=payload.name, rules=payload.rules, default=payload.default)
    except (CircleError, UnknownCircleError) as exc:
        raise _failed(exc) from exc
    return circle.to_dict()


@router.put("/{circle_id}/rules/{model}")
def set_rule(
    circle_id: str,
    model: str,
    payload: RuleIn,
    state: AppState = Depends(get_state),
    _: User = Depends(get_admin_user),
) -> dict:
    """One line of a circle, the others left as they are: what `cm circle rule`
    and an install sheet's ticks send. `none` on `*` takes the `*` line away."""
    try:
        return _circles(state).set_rule(circle_id, model, payload.access).to_dict()
    except (CircleError, UnknownCircleError) as exc:
        raise _failed(exc) from exc


@router.delete("/{circle_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_circle(circle_id: str, state: AppState = Depends(get_state), _: User = Depends(get_admin_user)) -> None:
    try:
        circle = _circles(state).get(circle_id)
        _circles(state).delete(circle.id)
    except UnknownCircleError as exc:
        raise _failed(exc) from exc
    # The shares that were shared with it are not any more.
    state.shares.forget_circle(circle.id)


@router.put("/{circle_id}/members/{username}")
def join_circle(
    circle_id: str,
    username: str,
    state: AppState = Depends(get_state),
    _: User = Depends(get_admin_user),
) -> dict:
    try:
        return _circles(state).join(circle_id, username).to_dict()
    except (CircleError, UnknownCircleError) as exc:
        raise _failed(exc) from exc


@router.delete("/{circle_id}/members/{username}")
def leave_circle(
    circle_id: str,
    username: str,
    state: AppState = Depends(get_state),
    _: User = Depends(get_admin_user),
) -> dict:
    try:
        return _circles(state).leave(circle_id, username).to_dict()
    except UnknownCircleError as exc:
        raise _failed(exc) from exc
