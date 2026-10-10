"""What is in a server share, over HTTP: a folder's listing, a file, a small
copy of a picture, and a file put there.

A machine mounts a share and looks with whatever it looks at files with.
Anything that cannot mount asks here instead — the CLI, the agent, and
any client from before the Files Quill, which reaches the same files as
`file` records through the `shares` backend. Both sides do the work in
`server/fileops.py`, so both keep the same rules.

The caller's own drive, `my-files`, which is a share in all but the table
it is not in, and every share the caller has — theirs and the ones shared
with them — the same as the WebDAV side. Putting a file in one takes
`write` on it.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from cloudmorrow.server import fileops
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_current_user, get_state
from cloudmorrow.server.drive import is_drive, user_drive
from cloudmorrow.server.fileops import FILE_MODE, FileOpError
from cloudmorrow.server.shares import WRITE, Share

__all__ = ["FILE_MODE", "router"]

router = APIRouter(prefix="/api/shares", tags=["shares"])


class EntryOut(BaseModel):
    name: str
    is_dir: bool
    # Bytes; 0 for a folder.
    size: int
    # Seconds since the epoch, the way the notes tree says it.
    modified: float
    # A guess from the name, "" when there is none — the browser sorts by
    # kind with it and knows a picture by it.
    mime: str = ""


class ListingOut(BaseModel):
    share: str
    # The folder listed, relative to the share; "" is the share itself.
    path: str
    entries: list[EntryOut]


def _http(exc: FileOpError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


def _out(entry: fileops.Entry) -> EntryOut:
    return EntryOut(
        name=entry.name,
        is_dir=entry.is_dir,
        size=entry.size,
        modified=entry.modified,
        mime=entry.mime,
    )


def _server_share(state: AppState, user: User, name: str, *, write: bool = False) -> Share:
    """The share *name* on the server, if the caller has it — or their own
    drive, which is served the same way and browsed the same way. With
    *write*, only if they may change what is in it."""
    if is_drive(name):
        return user_drive(state.config, user.username)
    share = state.shares.for_user(user.username, name)
    if share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no such share: {name}")
    if write and state.shares.access_of(share, user.username) != WRITE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{share.name} is shared with you to read, not to change",
        )
    return share


def _inside(share: Share, raw: str) -> Path:
    try:
        return fileops.inside(share, raw)
    except FileOpError as exc:
        raise _http(exc) from exc


@router.get("/{name}/ls", response_model=ListingOut)
def list_folder(
    name: str,
    path: str = Query(default="", description="A folder inside the share; empty for the top"),
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> ListingOut:
    """What is in a folder of the share. Sorting is the client's business."""
    share = _server_share(state, user, name)
    try:
        found = fileops.entries(_inside(share, path))
    except FileOpError as exc:
        raise _http(exc) from exc
    return ListingOut(share=share.name, path=path.strip("/ "), entries=[_out(e) for e in found])


@router.get("/{name}/file")
def read_file(
    name: str,
    path: str = Query(description="The file inside the share"),
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> FileResponse:
    """One file, as itself, for a picture to be shown or a file to be saved."""
    share = _server_share(state, user, name)
    target = _inside(share, path)
    if not target.is_file() or os.path.islink(target):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such file")
    return FileResponse(
        target,
        media_type=fileops.mime_of(target) or "application/octet-stream",
        # Someone's files: not for a shared cache, and asked for again next time.
        headers={"Cache-Control": "private, no-cache"},
    )


@router.get("/{name}/thumb")
def read_thumb(
    name: str,
    path: str = Query(description="The picture inside the share"),
    size: int = Query(default=256, ge=1, description="The long edge wanted, in pixels"),
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> FileResponse:
    """A small copy of a picture, for a grid. Not a picture, or not one the
    server can read: a 415, and the client shows the icon instead."""
    share = _server_share(state, user, name)
    try:
        out = fileops.thumbnail(state.config.data_dir, share, _inside(share, path), size)
    except FileOpError as exc:
        raise _http(exc) from exc
    return FileResponse(
        out,
        media_type="image/jpeg",
        # The same as the file itself: nobody's cache but the browser's own,
        # and asked about again next time — a cheap 304 when nothing changed.
        headers={"Cache-Control": "private, no-cache"},
    )


@router.post("/{name}/upload", response_model=EntryOut, status_code=status.HTTP_201_CREATED)
async def upload_file(
    name: str,
    request: Request,
    filename: str = Query(description="What to call it"),
    path: str = Query(default="", description="The folder inside the share to put it in"),
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> EntryOut:
    """Put a file in a folder of the share. The body is the file itself.

    Streamed to disk beside where it will sit, and named into place only
    once the whole of it has arrived, so a dropped connection leaves no
    half a photo with a photo's name. A name already taken gets a number.
    """
    share = _server_share(state, user, name, write=True)
    folder = _inside(share, path)
    if not folder.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such folder")
    try:
        target = fileops.free_name(folder, fileops.file_name(filename))
    except FileOpError as exc:
        raise _http(exc) from exc
    try:
        handle = tempfile.NamedTemporaryFile(dir=folder, prefix=".upload-", delete=False)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="the server cannot write to that folder"
        ) from exc
    part = Path(handle.name)
    try:
        with handle:
            async for chunk in request.stream():
                handle.write(chunk)
        os.chmod(part, FILE_MODE)
        os.replace(part, target)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return _out(fileops.entry(target))
