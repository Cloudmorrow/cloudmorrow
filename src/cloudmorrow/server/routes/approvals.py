"""Approvals: what is waiting for you, and answering it (approvals.py, docs/FLOWS.md)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_current_user, get_state
from cloudmorrow.server.routes.errors import ERRORS, http_error
from cloudmorrow.server.routes.records import person

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class AskIn(BaseModel):
    role: str
    question: str
    about_model: str = ""
    about: str = ""
    about_title: str = ""
    circle: str = ""
    due: str | None = None


class AnswerIn(BaseModel):
    # approved, declined — or withdrawn, by whoever asked.
    status: str
    note: str = ""


def _approvals(state: AppState):
    if state.approvals is None:  # pragma: no cover - every app has them
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "approvals are not set up")
    return state.approvals


@router.get("")
def my_approvals(state: AppState = Depends(get_state), user: User = Depends(get_current_user)) -> dict:
    """What waits for your answer, and what you asked that is still open."""
    approvals = _approvals(state)
    return {
        "waiting": [r.to_dict() for r in approvals.waiting_for(user.username)],
        "asked": [r.to_dict() for r in approvals.asked_by(user.username)],
    }


@router.get("/count")
def waiting_count(state: AppState = Depends(get_state), user: User = Depends(get_current_user)) -> dict:
    return {"waiting": _approvals(state).waiting_count(user.username)}


@router.post("", status_code=status.HTTP_201_CREATED)
def ask(payload: AskIn, state: AppState = Depends(get_state), user: User = Depends(get_current_user)) -> dict:
    """Ask the holders of a role yourself, about a record or about nothing in particular."""
    try:
        made = _approvals(state).ask(
            person(user),
            role=payload.role,
            question=payload.question,
            about_model=payload.about_model,
            about=payload.about,
            about_title=payload.about_title,
            circle=payload.circle,
            due=payload.due,
        )
    except ERRORS as exc:
        raise http_error(exc) from exc
    return made.to_dict()


@router.post("/{approval_id}/answer")
def answer(
    approval_id: str,
    payload: AnswerIn,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    """Approve or decline, as a holder of the role; withdraw, as whoever asked."""
    try:
        changed = _approvals(state).answer(user.username, approval_id, payload.status, payload.note)
    except ERRORS as exc:
        raise http_error(exc) from exc
    return changed.to_dict()
