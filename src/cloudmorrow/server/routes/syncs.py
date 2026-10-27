"""Local backups: the folders a person's machines copy into My Files.

`/api/syncs` is the person's: what is set up, setting one up, taking one
off, asking for a pass now. `/api/agent/syncs` is the machine's: its own
rows, what the drive holds under each, the files it sends and takes away,
and how the pass went. A machine reaches its owner's drive through these
alone, under the folder the row names.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from cloudmorrow.server import syncs
from cloudmorrow.server.agents import Agent, UnknownAgentError
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_current_agent, get_current_user, get_state
from cloudmorrow.server.drive import user_drive

router = APIRouter(prefix="/api/syncs", tags=["syncs"])
agent_router = APIRouter(prefix="/api/agent/syncs", tags=["agent"])


class SyncIn(BaseModel):
    agent_id: int
    path: str
    into: str = ""
    every_minutes: int = syncs.DEFAULT_EVERY_MINUTES


class SyncDone(BaseModel):
    ok: bool
    said: str = ""
    files: int = 0
    bytes: int = 0


def _with_agent(state: AppState, owner: str, sync: syncs.Sync) -> dict:
    agent = state.agents.get(owner, sync.agent_id)
    out = sync.to_dict()
    out["agent"] = agent.to_dict() if agent else None
    return out


def _sync_of(state: AppState, user: User, sync_id: int) -> syncs.Sync:
    try:
        return state.syncs.get(user.username, sync_id)
    except syncs.UnknownSyncError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such backup") from exc


# -- the person's ------------------------------------------------------------------
@router.get("")
def list_syncs(state: AppState = Depends(get_state), user: User = Depends(get_current_user)) -> list[dict]:
    return [_with_agent(state, user.username, s) for s in state.syncs.list(user.username)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_sync(payload: SyncIn, state: AppState = Depends(get_state), user: User = Depends(get_current_user)) -> dict:
    """A folder on one of your machines, backed up into My Files from now on."""
    try:
        agent = state.agents.require(user.username, payload.agent_id)
    except UnknownAgentError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such machine of yours") from exc
    into = payload.into or syncs.default_into(agent.name, payload.path)
    try:
        sync = state.syncs.create(user.username, agent.id, payload.path, into, payload.every_minutes)
    except syncs.SyncError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _with_agent(state, user.username, sync)


@router.delete("/{sync_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sync(sync_id: int, state: AppState = Depends(get_state), user: User = Depends(get_current_user)) -> None:
    """Off the list; what was copied stays in My Files."""
    try:
        state.syncs.delete(user.username, sync_id)
    except syncs.UnknownSyncError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such backup") from exc


@router.post("/{sync_id}/run")
def run_sync(sync_id: int, state: AppState = Depends(get_state), user: User = Depends(get_current_user)) -> dict:
    """A pass on the machine's next tick, rather than when it is due."""
    _sync_of(state, user, sync_id)
    return _with_agent(state, user.username, state.syncs.ask(user.username, sync_id))


# -- the machine's ---------------------------------------------------------------
def _mine(state: AppState, agent: Agent, sync_id: int) -> syncs.Sync:
    try:
        return state.syncs.of_agent(agent.id, sync_id)
    except syncs.UnknownSyncError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such backup for this machine") from exc


@agent_router.get("")
def agent_syncs(state: AppState = Depends(get_state), agent: Agent = Depends(get_current_agent)) -> list[dict]:
    """This machine's folders to back up, with when each last ran."""
    return [s.to_dict() for s in state.syncs.for_agent(agent.id)]


@agent_router.get("/{sync_id}/files")
def agent_sync_files(
    sync_id: int, state: AppState = Depends(get_state), agent: Agent = Depends(get_current_agent)
) -> dict:
    """What the drive holds under this backup's folder: {path: {size, modified}}."""
    sync = _mine(state, agent, sync_id)
    try:
        return syncs.listing(user_drive(state.config, agent.owner), sync)
    except syncs.SyncError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@agent_router.put("/{sync_id}/file")
async def agent_sync_put(
    sync_id: int,
    request: Request,
    path: str = Query(...),
    modified: float | None = Query(default=None),
    state: AppState = Depends(get_state),
    agent: Agent = Depends(get_current_agent),
) -> dict:
    """One file, the body its bytes, written over what was there under the backup's folder."""
    sync = _mine(state, agent, sync_id)
    spool = state.config.data_dir / "uploads"
    spool.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(dir=spool, prefix=".sync-", delete=False)
    part = Path(handle.name)
    try:
        with handle:
            async for chunk in request.stream():
                handle.write(chunk)
        try:
            return syncs.put(user_drive(state.config, agent.owner), sync, path, part, modified)
        except syncs.SyncError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        part.unlink(missing_ok=True)


@agent_router.delete("/{sync_id}/file")
def agent_sync_remove(
    sync_id: int,
    path: str = Query(...),
    state: AppState = Depends(get_state),
    agent: Agent = Depends(get_current_agent),
) -> dict:
    """A file gone from the machine: to the drive's Trash."""
    sync = _mine(state, agent, sync_id)
    try:
        return {"removed": syncs.remove(user_drive(state.config, agent.owner), sync, path)}
    except syncs.SyncError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@agent_router.post("/{sync_id}/done")
def agent_sync_done(
    sync_id: int, payload: SyncDone, state: AppState = Depends(get_state), agent: Agent = Depends(get_current_agent)
) -> dict:
    """How the pass went: kept on the row, for the page."""
    _mine(state, agent, sync_id)
    return state.syncs.finished(
        agent.id, sync_id, ok=payload.ok, said=payload.said, files=payload.files, size=payload.bytes
    ).to_dict()
