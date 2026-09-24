"""Fileshares: make one, list them, forget one. The files themselves are at `/dav`
on the server, or at the machine that serves them.

The list opens with the caller's own drive, `my-files`: a share in every
way that matters to a client, and not one to this module — it is neither
made nor removed here (`cloudmorrow.server.drive`)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from cloudmorrow.server.agents import Agent
from cloudmorrow.server.dav import MOUNT_PATH
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_current_user, get_state
from cloudmorrow.server.drive import is_drive, user_drive
from cloudmorrow.server.routes.install import base_url
from cloudmorrow.server.schemas import ShareCreate, ShareFoldersOut, ShareOut
from cloudmorrow.server.shares import (
    MACHINE,
    SERVER,
    InvalidSlugError,
    Share,
    ShareExistsError,
    ShareKindError,
    SharePathError,
    UnknownShareError,
)

router = APIRouter(prefix="/api/shares", tags=["shares"])


def share_url(base: str, name: str) -> str:
    """Where a WebDAV client points: the share's own folder, trailing slash and all."""
    return f"{base.rstrip('/')}{MOUNT_PATH}/{name}/"


def _out(share: Share, base: str, agents: dict[int, Agent]) -> ShareOut:
    if share.kind == MACHINE:
        agent = agents.get(share.agent_id or -1)
        served_at = agent.dav_base if agent else ""
        return ShareOut(
            url=share_url(served_at, share.name) if served_at else "",
            machine=agent.name if agent else "",
            online=bool(agent and agent.online and served_at),
            **share.to_dict(),
        )
    return ShareOut(url=share_url(base, share.name), online=True, **share.to_dict())


def _agents_of(state: AppState, user: User) -> dict[int, Agent]:
    return {agent.id: agent for agent in state.agents.list(user.username)}


def _share_or_404(state: AppState, user: User, name: str) -> Share:
    if is_drive(name):
        return user_drive(state.config, user.username)
    try:
        return state.shares.require(user.username, name)
    except UnknownShareError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no such share: {name}"
        ) from exc


@router.get("", response_model=list[ShareOut])
def list_shares(
    request: Request,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> list[ShareOut]:
    base = base_url(request, state)
    agents = _agents_of(state, user)
    drive = user_drive(state.config, user.username)
    return [_out(share, base, agents) for share in (drive, *state.shares.shares(user.username))]


@router.post("", response_model=ShareOut, status_code=status.HTTP_201_CREATED)
def create_share(
    payload: ShareCreate,
    request: Request,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> ShareOut:
    """A new share.

    A server share puts files on the server, so it is an admin's call. It
    is the folder of that name in their Shares directory there — made if it
    is not there, used as it is if it is — and takes no path. A machine
    share is the caller's own disk, served by their own agent, and anyone
    may make one. The machine named must be one of theirs; which of
    them is the clients' rule — the CLI and the TUI only ever name the one
    they run on, since that is the only one whose paths the caller can see.
    """
    kind = (payload.kind or SERVER).strip().lower()
    path = (payload.path or "").strip() or None
    agent_id: int | None = None
    if kind == MACHINE:
        machine = (payload.machine or "").strip()
        if not machine:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="a machine share needs the machine that serves it",
            )
        agent = next(
            (a for a in state.agents.list(user.username) if a.name == machine), None
        )
        if agent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"no such machine: {machine}"
            )
        agent_id = agent.id
    elif kind == SERVER and not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only an admin can make a share on the server — "
            "a machine share serves a directory on one of your own machines",
        )
    try:
        share = state.shares.create(
            user.username,
            payload.name,
            kind=kind,
            path=path,
            agent_id=agent_id,
            description=payload.description,
        )
    except ShareExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="a share with that name exists"
        ) from exc
    except (InvalidSlugError, SharePathError, ShareKindError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _out(share, base_url(request, state), _agents_of(state, user))


@router.get("/folders", response_model=ShareFoldersOut)
def share_folders(
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> ShareFoldersOut:
    """The caller's Shares directory on the server, and the folders in it
    that are not shares yet — what the new-share dialog offers. Admins
    only, since only they make server shares."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only an admin makes a share on the server",
        )
    directory, folders = state.shares.folders(user.username)
    return ShareFoldersOut(directory=str(directory), folders=folders)


@router.get("/{name}", response_model=ShareOut)
def get_share(
    name: str,
    request: Request,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> ShareOut:
    share = _share_or_404(state, user, name)
    return _out(share, base_url(request, state), _agents_of(state, user))


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_share(
    name: str,
    remove_files: bool = Query(
        default=False,
        description="also delete its folder in the Shares directory",
    ),
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> None:
    """Forget the share. Its folder on the server goes only if asked; a
    directory on a machine is never deleted from here. The drive is nobody's
    to remove: it is there because the account is."""
    if is_drive(name):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{name} is your own drive on the server — it cannot be removed",
        )
    _share_or_404(state, user, name)
    state.shares.delete(user.username, name, remove_files=remove_files)
