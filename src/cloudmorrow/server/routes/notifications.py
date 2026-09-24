"""Reading what the machines left behind, and letting them leave it."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from cloudmorrow.server.agents import Agent
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_current_agent, get_current_user, get_state
from cloudmorrow.server.schemas import (
    NotificationCreate,
    NotificationOut,
    NotificationsRead,
    NotificationsReadOut,
)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])
agent_router = APIRouter(prefix="/api/agent/notifications", tags=["agent"])


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    unread: bool = Query(default=False, description="Only the ones not yet read."),
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> list[NotificationOut]:
    return [
        NotificationOut(**note.to_dict())
        for note in state.notifications.list(user.username, limit=limit, unread_only=unread)
    ]


@router.post("/read", response_model=NotificationsReadOut)
def mark_read(
    payload: NotificationsRead,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> NotificationsReadOut:
    marked = state.notifications.mark_read(user.username, payload.ids)
    return NotificationsReadOut(
        marked=marked, unread=state.notifications.unread_count(user.username)
    )


@agent_router.post("", response_model=NotificationOut)
def agent_notify(
    payload: NotificationCreate,
    state: AppState = Depends(get_state),
    agent: Agent = Depends(get_current_agent),
) -> NotificationOut:
    """A machine saying what it just did. It signs itself; it cannot pretend."""
    note = state.notifications.add(
        agent.owner,
        kind=payload.kind,
        machine=agent.name,
        title=payload.title,
        body=payload.body,
    )
    return NotificationOut(**note.to_dict())
