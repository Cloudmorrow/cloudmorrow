"""Flows: running one by hand, and what a flow may be made of (flows.py, docs/FLOWS.md).

A flow and its runs are records (`flow`, `flow_run`), so making, changing
and listing them is the record API. What is here is the rest: starting a
run by hand, and the vocabulary a screen builds a flow from.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from cloudmorrow.server import flows
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_current_user, get_state
from cloudmorrow.server.routes.errors import ERRORS, http_error

router = APIRouter(prefix="/api/flows", tags=["flows"])


class RunIn(BaseModel):
    # A record to run it on, as if it had fired: its datamodel and id.
    model: str = ""
    record: str = ""


class CheckIn(BaseModel):
    trigger: dict
    steps: list


def _flows(state: AppState):
    if state.flows is None:  # pragma: no cover - every app has them
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "flows are not set up")
    return state.flows


@router.get("/kinds")
def kinds(_: User = Depends(get_current_user)) -> dict:
    """The kinds of trigger and step there are, for a screen that builds flows."""
    return {"triggers": list(flows.TRIGGER_KINDS), "steps": list(flows.STEP_KINDS), "when": list(flows.WHEN)}


@router.post("/check")
def check(payload: CheckIn, _: User = Depends(get_current_user)) -> dict:
    """Is this a flow the runner can run? The problem in words, or ok."""
    try:
        trigger = flows.check_trigger(payload.trigger)
        steps = flows.check_steps(payload.steps)
    except flows.FlowError as exc:
        return {"ok": False, "problem": str(exc)}
    return {"ok": True, "trigger": trigger, "steps": steps}


@router.post("/{flow_id}/run")
def run_now(
    flow_id: str,
    payload: RunIn,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    """Start one of your flows now and wait for it to go as far as it can: the run."""
    try:
        run = _flows(state).run_now(user.username, flow_id, model=payload.model, record=payload.record)
    except ERRORS as exc:
        raise http_error(exc) from exc
    except flows.FlowError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return run.to_dict()
