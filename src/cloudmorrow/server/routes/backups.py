"""Backups over the API: where they go, running one, what is in the bucket, and restoring. Admin accounts only.

A backup or a restore runs on a thread and may take a while, so starting
one answers 202 at once with the status, and `GET /api/server/backup` is
what a page polls until `running` is null. The settings and the status
come together, since the page needs both at once.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from cloudmorrow.server.backups import BackupError, Backups, Choice
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_admin_user, get_state
from cloudmorrow.server.schemas import (
    BackupRestoreRequest,
    BackupRunRequest,
    BackupSettingsOut,
    BackupSettingsUpdate,
    BackupStatusOut,
    BackupSummaryOut,
    BackupTestOut,
)

router = APIRouter(prefix="/api/server", tags=["backups"])


def _backups(state: AppState) -> Backups:
    if state.backups is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="backups are not set up on this server"
        )
    return state.backups


def _settings_out(backups: Backups) -> BackupSettingsOut:
    found = backups.settings()
    return BackupSettingsOut(
        endpoint=found.endpoint,
        bucket=found.bucket,
        region=found.region,
        prefix=found.prefix,
        access_key=found.access_key,
        has_secret=backups.has_secret(),
        time=found.time,
        keep_days=found.keep_days,
        parts=list(found.parts),
        seal_key=found.seal_key,
        enabled=found.enabled,
        configured=found.configured() and backups.has_secret(),
    )


def _status_out(backups: Backups) -> BackupStatusOut:
    told = backups.status()
    return BackupStatusOut(settings=_settings_out(backups), **told)


def _refused(exc: BackupError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/backup", response_model=BackupStatusOut)
def backup_status(state: AppState = Depends(get_state), _: User = Depends(get_admin_user)) -> BackupStatusOut:
    return _status_out(_backups(state))


@router.patch("/backup", response_model=BackupStatusOut)
def change_backup_settings(
    payload: BackupSettingsUpdate, state: AppState = Depends(get_state), admin: User = Depends(get_admin_user)
) -> BackupStatusOut:
    backups = _backups(state)
    try:
        backups.save_settings(payload.model_dump(exclude_unset=True), changed_by=admin.username)
    except (BackupError, ValueError) as exc:
        raise _refused(BackupError(str(exc))) from exc
    return _status_out(backups)


@router.post("/backup/test", response_model=BackupTestOut)
def test_backup_destination(state: AppState = Depends(get_state), _: User = Depends(get_admin_user)) -> BackupTestOut:
    """Reach the bucket with what is set: list it, write a probe, take it away.

    A sync def: the calls to the store happen off the event loop.
    """
    try:
        return BackupTestOut(**_backups(state).test())
    except BackupError as exc:
        raise _refused(exc) from exc


@router.post("/backup/run", response_model=BackupStatusOut, status_code=status.HTTP_202_ACCEPTED)
def run_backup(
    payload: BackupRunRequest, state: AppState = Depends(get_state), admin: User = Depends(get_admin_user)
) -> BackupStatusOut:
    backups = _backups(state)
    try:
        backups.start_backup(payload.parts, by=admin.username)
    except BackupError as exc:
        raise _refused(exc) from exc
    return _status_out(backups)


@router.get("/backups", response_model=list[BackupSummaryOut])
def list_backups(state: AppState = Depends(get_state), _: User = Depends(get_admin_user)) -> list[BackupSummaryOut]:
    """Every finished backup in the bucket, newest first. A sync def: it reads the bucket."""
    try:
        return [BackupSummaryOut(**found) for found in _backups(state).list_backups()]
    except BackupError as exc:
        raise _refused(exc) from exc


@router.get("/backups/{stamp}")
def describe_backup(stamp: str, state: AppState = Depends(get_state), _: User = Depends(get_admin_user)) -> dict:
    """One backup's manifest: every part, with its size, and whether its
    database was sealed with this server's key (`key_matches`)."""
    try:
        return _backups(state).describe(stamp)
    except BackupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/backups/{stamp}", status_code=status.HTTP_204_NO_CONTENT)
def delete_backup(stamp: str, state: AppState = Depends(get_state), _: User = Depends(get_admin_user)) -> None:
    try:
        _backups(state).delete_backup(stamp)
    except BackupError as exc:
        raise _refused(exc) from exc


@router.post("/backups/{stamp}/restore", response_model=BackupStatusOut, status_code=status.HTTP_202_ACCEPTED)
def restore_backup(
    stamp: str,
    payload: BackupRestoreRequest,
    state: AppState = Depends(get_state),
    admin: User = Depends(get_admin_user),
) -> BackupStatusOut:
    """Put the chosen parts of one backup back, on a thread. When the database,
    the Quills or the keys are among them the server restarts itself afterwards,
    as an update does — `last_restore` says `restarting`, or why not."""
    backups = _backups(state)
    choice = Choice(
        database=payload.database,
        drives=list(payload.drives),
        shares=list(payload.shares),
        quills=payload.quills,
        keys=payload.keys,
        restart=payload.restart,
        force=payload.force,
    )
    try:
        backups.start_restore(stamp, choice, by=admin.username)
    except BackupError as exc:
        raise _refused(exc) from exc
    return _status_out(backups)
