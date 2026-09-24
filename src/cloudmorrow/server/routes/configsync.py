"""The config bundle: what the machines read, and what they write back.

Two doors onto the same rows. The operator's door is read-only — the TUI shows
you which machine claimed the bundle and when it last moved — and the agents'
door is the one that pushes. Nothing here decides what a bundle covers; the
agent knows that, and only ever sends paths relative to the bundle's root.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from cloudmorrow.bundles import InvalidPathError
from cloudmorrow.server.agents import Agent
from cloudmorrow.server.configsync import (
    BundleTooBigError,
    ConfigFile,
    StaleRevisionError,
    UnknownBundleError,
    validate_bundle,
)
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_current_agent, get_current_user, get_state
from cloudmorrow.server.schemas import (
    BundleFilesOut,
    BundleOut,
    BundlePush,
    BundleStatusOut,
)

router = APIRouter(prefix="/api/config", tags=["config"])
agent_router = APIRouter(prefix="/api/agent/config", tags=["agent"])


def _bundle(name: str) -> str:
    try:
        return validate_bundle(name)
    except UnknownBundleError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no such config bundle: {name}"
        ) from exc


# -- operator-facing ---------------------------------------------------------
@router.get("", response_model=list[BundleStatusOut])
def list_bundles(
    state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> list[BundleStatusOut]:
    return [
        _status(state, user.username, bundle.to_dict())
        for bundle in state.config_sync.states(user.username)
    ]


@router.get("/{bundle}", response_model=BundleStatusOut)
def get_bundle(
    bundle: str,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> BundleStatusOut:
    payload = state.config_sync.state(user.username, _bundle(bundle)).to_dict()
    return _status(state, user.username, payload)


@router.delete("/{bundle}", response_model=BundleStatusOut)
def forget_bundle(
    bundle: str,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> BundleStatusOut:
    """Unclaim the bundle: the next machine to tick the box decides again.

    The machines keep the files they already have — this throws away the
    server's copy, not theirs.
    """
    name = _bundle(bundle)
    state.config_sync.forget(user.username, name)
    state.notifications.add(
        user.username,
        kind="config.forgotten",
        title=f"{name} config unclaimed",
        body="The next machine to switch syncing on decides the configuration.",
    )
    return _status(state, user.username, state.config_sync.state(user.username, name).to_dict())


def _status(state: AppState, owner: str, payload: dict) -> BundleStatusOut:
    machines = [agent.name for agent in state.agents.syncing(owner, payload["bundle"])]
    return BundleStatusOut(**payload, machines=machines)


# -- agent-facing ------------------------------------------------------------
@agent_router.get("/{bundle}", response_model=BundleOut)
def agent_bundle_state(
    bundle: str,
    state: AppState = Depends(get_state),
    agent: Agent = Depends(get_current_agent),
) -> BundleOut:
    """The manifest, so a machine can tell whether it has anything to do."""
    return BundleOut(**state.config_sync.state(agent.owner, _bundle(bundle)).to_dict())


@agent_router.get("/{bundle}/files", response_model=BundleFilesOut)
def agent_bundle_files(
    bundle: str,
    state: AppState = Depends(get_state),
    agent: Agent = Depends(get_current_agent),
) -> BundleFilesOut:
    name = _bundle(bundle)
    current = state.config_sync.state(agent.owner, name)
    files = state.config_sync.files(agent.owner, name)
    return BundleFilesOut(
        bundle=name,
        revision=current.revision,
        origin=current.origin,
        files=[file.to_dict() for file in files],
    )


@agent_router.post("/{bundle}", response_model=BundleOut)
def agent_push_bundle(
    bundle: str,
    payload: BundlePush,
    state: AppState = Depends(get_state),
    agent: Agent = Depends(get_current_agent),
) -> BundleOut:
    """Take this machine's copy as the new revision, if it is not stale.

    409 means somebody else got there first — with the current revision in the
    detail, so the agent knows to fetch that and try again from it.
    """
    name = _bundle(bundle)
    if name not in agent.sync_bundles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{agent.name} is not syncing {name}",
        )
    try:
        files = [
            ConfigFile(path=f.path, content=f.content, sha256=f.sha256, mode=f.mode)
            for f in payload.files
        ]
    except InvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="refusing to store an empty bundle — that would wipe every machine",
        )

    first_claim = payload.base_revision is None
    try:
        result = state.config_sync.push(
            agent.owner,
            name,
            machine=agent.name,
            files=files,
            base_revision=payload.base_revision,
        )
    except StaleRevisionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "stale",
                "message": str(exc),
                "revision": exc.current,
                "bundle": name,
            },
        ) from exc
    except BundleTooBigError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc

    if first_claim:
        state.notifications.add(
            agent.owner,
            kind="config.claimed",
            machine=agent.name,
            title=f"{agent.name} claimed the {name} config",
            body=(
                f"{len(files)} files at revision {result.revision}. Every other machine "
                f"syncing {name} adopts this copy."
            ),
        )
    else:
        state.notifications.add(
            agent.owner,
            kind="config.updated",
            machine=agent.name,
            title=f"{name} config changed on {agent.name}",
            body=f"Revision {result.revision}, {len(files)} files.",
        )
    return BundleOut(**result.to_dict())
