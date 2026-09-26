"""Subscribing a device to pushes, and the number on the icon.

The browser does the hard part: it asks its vendor's push service for an
endpoint, and hands back that endpoint with two keys. All this has to do is
remember them against the account, and hand out the server's public key so
the browser has something to ask with.

The badge is here rather than in any Quill because it is nobody's in
particular: it is the one number on the home-screen icon, and it has to mean
everything waiting — what was written in your spaces since you last looked
(a channel's messages, whichever Quill declared them `unread`), plus
notifications you have not read. The record store counts the one, the
notifications the other, and this adds them up. One number, one place it is
worked out, so the page, the service worker and the push payload can never
disagree about it.

The service worker is served from here too, at `/app/sw.js`. A service
worker may only control pages at or below its own path, so it cannot live
under `/app/<deploy>/` with the other assets — it has to sit at the root of
the app's scope, and it is served with no-cache because a worker that the
browser keeps is a deploy that never lands.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_current_user, get_state
from cloudmorrow.server.records import Principal

WEB = Path(__file__).resolve().parent.parent / "web"

router = APIRouter(prefix="/api/push", tags=["push"])
# The worker is not under /api, so it gets a router of its own. It must be
# included before the web router, whose /app/{filename} would otherwise
# match first and serve it with a year of caching.
worker_router = APIRouter(tags=["web"])


class KeyOut(BaseModel):
    """What the browser needs to subscribe with."""

    public_key: str
    subject: str = ""


class Keys(BaseModel):
    p256dh: str
    auth: str


class SubscribeIn(BaseModel):
    """A `PushSubscription`, as `JSON.stringify` gives it."""

    endpoint: str
    keys: Keys
    label: str = ""


class EndpointIn(BaseModel):
    endpoint: str


class DeviceOut(BaseModel):
    id: int
    label: str = ""
    endpoint: str


class BadgeOut(BaseModel):
    """The number on the icon, and the two halves it is made of."""

    messages: int = 0
    notifications: int = 0
    badge: int = 0


# -- the count ------------------------------------------------------------------
def unread_models(state: AppState, username: str) -> list[str]:
    """The space datamodels whose unread counts for this person.

    Their own switch counts here as well: a number on the icon for a tab
    they have turned off is a count of something they cannot go and read.
    So a space counts when some Quill that uses it is on for them.
    """
    return [
        model.id
        for model in state.quills.datamodels.values()
        if model.space
        and any(state.features.enabled_for(username, quill) for quill in state.quills.users_of(model.id))
    ]


def badge_for(state: AppState, username: str) -> dict:
    """Everything waiting for one person, as the icon would say it."""
    wanted = unread_models(state, username)
    messages = (
        state.records.unread_total(Principal.person(username), models=wanted) if wanted else 0
    )
    notifications = state.notifications.unread_count(username)
    return {
        "messages": messages,
        "notifications": notifications,
        "badge": messages + notifications,
    }


def notify_message(
    state: AppState,
    usernames: list[str],
    *,
    title: str,
    body: str,
    url: str = "",
    tag: str = "",
) -> int:
    """Push a line to everyone named, each with their own badge number.

    The badge differs per person — it is what *they* have waiting — so this
    cannot be one payload sent to a list. It is a handful of requests to a
    handful of devices, run as a background task after the response has
    gone, so nobody waits on Apple to answer.
    """
    landed = 0
    for who in dict.fromkeys(usernames):
        counts = badge_for(state, who)
        landed += state.push.send(
            [who],
            {
                "title": title,
                "body": body[:200],
                "url": url,
                "tag": tag,
                "badge": counts["badge"],
            },
        )
    return landed


# -- subscribing -----------------------------------------------------------------
@router.get("/key", response_model=KeyOut)
def push_key(
    state: AppState = Depends(get_state), _: User = Depends(get_current_user)
) -> KeyOut:
    return KeyOut(public_key=state.push.public_key, subject=state.push.subject)


@router.post("/subscribe", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
def subscribe(
    payload: SubscribeIn,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> DeviceOut:
    try:
        subscription = state.push.subscribe(
            user.username,
            endpoint=payload.endpoint,
            p256dh=payload.keys.p256dh,
            auth=payload.keys.auth,
            label=payload.label,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return DeviceOut(**subscription.to_dict())


@router.post("/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe(
    payload: EndpointIn,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> None:
    state.push.unsubscribe(user.username, payload.endpoint)


@router.get("/devices", response_model=list[DeviceOut])
def devices(
    state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> list[DeviceOut]:
    return [DeviceOut(**s.to_dict()) for s in state.push.list(user.username)]


@router.get("/badge", response_model=BadgeOut)
def badge(
    state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> BadgeOut:
    """What the page sets the icon to while it is open."""
    return BadgeOut(**badge_for(state, user.username))


@router.post("/test", response_model=BadgeOut)
def send_test(
    state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> BadgeOut:
    """Push yourself, to find out whether this phone is actually wired up.

    Worth having: everything between here and the notification — the
    permission, the subscription, the keys, Apple — fails silently, and
    without this the only test is to ask somebody to message you.
    """
    counts = badge_for(state, user.username)
    state.push.send(
        [user.username],
        {
            "title": "Cloudmorrow",
            "body": "Push works on this device.",
            "url": "#/",
            "tag": "push-test",
            "badge": counts["badge"],
        },
    )
    return BadgeOut(**counts)


# -- the worker ---------------------------------------------------------------------
@worker_router.get("/app/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(
        WEB / "sw.js",
        media_type="text/javascript; charset=utf-8",
        # Never cached. The browser checks this file to find out whether the
        # worker has changed, so a cached copy is a worker frozen at the
        # deploy it was first installed on.
        headers={"Cache-Control": "no-cache"},
    )
