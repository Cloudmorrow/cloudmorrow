"""Deploying the server from git, over the API. Admin accounts only.

The pull and the reinstall need no privilege: the service user owns the
checkout and the venv it runs from, and it owns the deploy key the pull uses —
it is already the identity `cloudmorrow-update` drops to over ssh. The restart
is the part the service cannot do, so it does not try: it stops itself and
systemd starts it again on the new code.

What this endpoint can deploy is bounded by git, not by the caller: it
moves to a commit that is already on the configured remote and branch.
It cannot run code that was not pushed there first.
"""

from __future__ import annotations

import datetime as dt
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_admin_user, get_current_user, get_state
from cloudmorrow.server.schemas import (
    ServerReleaseOut,
    ServerSettingsOut,
    ServerSettingsUpdate,
    ServerUpdateOut,
    ServerUpdateRequest,
    ServerUpdatesOut,
)
from cloudmorrow.server.settings import InvalidNameError
from cloudmorrow.server.update import (
    UpdateError,
    build_wheel,
    describe,
    releases_ahead,
    self_restart,
    self_restart_blocker,
    update,
    validate_branch,
)

router = APIRouter(prefix="/api/server", tags=["server"])


def _settings(state: AppState) -> ServerSettingsOut:
    return ServerSettingsOut(name=state.cloud_name(), weather_place=state.weather_place())


@router.get("/settings", response_model=ServerSettingsOut)
def read_settings(state: AppState = Depends(get_state), _: User = Depends(get_current_user)) -> ServerSettingsOut:
    return _settings(state)


@router.patch("/settings", response_model=ServerSettingsOut)
def change_settings(
    payload: ServerSettingsUpdate,
    state: AppState = Depends(get_state),
    admin: User = Depends(get_admin_user),
) -> ServerSettingsOut:
    """Rename the cloud, or say where the weather is for. Each is in effect at once.

    The name is on every screen the moment it is reloaded; the weather is the
    new place's on the front page's next ask.
    """
    try:
        if payload.name is not None:
            state.settings.set_name(payload.name, changed_by=admin.username)
        if payload.weather_place is not None:
            place = state.settings.set_weather_place(payload.weather_place, changed_by=admin.username)
            state.weather.set_place(place)
    except InvalidNameError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _settings(state)


# How long a look at the remote stands before the next one: a page opened
# twice in a row asks git once.
CHECK_TTL = 15 * 60


@router.get("/updates", response_model=ServerUpdatesOut)
def newer_releases(
    refresh: bool = Query(False),
    state: AppState = Depends(get_state),
    _: User = Depends(get_admin_user),
) -> ServerUpdatesOut:
    """Whether a newer release is out, and the notes from the running one to it.

    The look fetches the remote, so it is kept for a quarter of an hour;
    `?refresh=1` looks again now. A server that is not a checkout, or cannot
    reach its remote, says so in `error` rather than failing: the page still
    has a Server to show.
    """
    kept = state.update_check
    if kept is not None and not refresh and time.monotonic() - kept[0] < CHECK_TTL:
        return kept[1]
    checked_at = dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")
    try:
        found = releases_ahead()
        out = ServerUpdatesOut(
            running_version=found.running_version,
            running_commit=found.running_commit,
            latest_version=found.latest_version,
            available=found.available,
            releases=[
                ServerReleaseOut(tag=r.tag, version=r.version, date=r.date, notes=r.notes, changes=list(r.changes))
                for r in found.releases
            ],
            checked_at=checked_at,
        )
    except UpdateError as exc:
        out = ServerUpdatesOut(checked_at=checked_at, error=str(exc))
    state.update_check = (time.monotonic(), out)
    return out


@router.post("/update", response_model=ServerUpdateOut)
def update_server(
    payload: ServerUpdateRequest,
    background: BackgroundTasks,
    state: AppState = Depends(get_state),
    _: User = Depends(get_admin_user),
) -> ServerUpdateOut:
    """Fast-forward the checkout, reinstall, republish the client wheel, restart.

    A sync def on purpose: FastAPI runs it in a worker thread, so the git and
    pip subprocesses do not block the event loop while they run.
    """
    config = state.config
    if not config.allow_api_update:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "this server does not deploy over the API "
                "(allow_api_update = false) — use `cloudmorrow update server --ssh`"
            ),
        )
    try:
        branch = validate_branch(payload.branch) if payload.branch else None
        result = update(
            branch=branch,
            service=config.service_name,
            # Never from here: this process has no way to restart anything but
            # itself, and that happens below, after the response.
            restart=False,
            force=payload.force,
        )
    except UpdateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    # Whatever the page knew about newer releases, it has just moved onto them.
    state.update_check = None
    published = ""
    if result.changed or payload.force:
        try:
            published = build_wheel(result.source, config.dist_dir).name
        except (UpdateError, OSError) as exc:
            # The deploy itself worked; clients just cannot follow it yet.
            published = f"failed: {exc}"

    out = ServerUpdateOut(
        source=str(result.source),
        branch=result.branch,
        old_commit=result.old_commit,
        new_commit=result.new_commit,
        old_version=result.old_version,
        new_version=result.new_version,
        commit_subject=_subject(result.source, result.new_commit),
        changed_files=result.changed_files,
        changed=result.changed,
        discarded=result.discarded,
        reinstalled=result.reinstalled,
        published_wheel=published,
        commands_unlinked=result.unlinked,
    )
    if payload.restart and (result.changed or payload.force):
        blocker = self_restart_blocker(config.service_name)
        if blocker:
            out.restart_blocked = blocker
        else:
            out.restarting = True
            # After the response, not before it: this is the process answering.
            background.add_task(self_restart)
    return out


def _subject(source, commit: str) -> str:
    try:
        return describe(source, commit)
    except UpdateError:
        return ""
