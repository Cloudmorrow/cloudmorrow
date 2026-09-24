"""What is in a server share, for the browser: a folder's listing, a file,
a small copy of a picture for the grid, and a file put there.

A machine mounts a share and looks with whatever it looks at files with.
The browser cannot mount anything, so the web app asks here instead: what
is in this folder, give me this file, take this one. Only a server share —
a machine share's files are on the machine, and this server never sees
them — and the caller's own drive, `my-files`, which is one in all but the
table it is not in.

The caller's own shares only, the same as the WebDAV side. Nothing hidden
is listed, no symlink is followed out of the share, and a path is checked
against the share's folder before anything is opened or written.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from cloudmorrow.paths import UnsafePathError, resolve_within
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_current_user, get_state
from cloudmorrow.server.drive import is_drive, user_drive
from cloudmorrow.server.shares import SERVER, Share, UnknownShareError

router = APIRouter(prefix="/api/shares", tags=["shares"])

# What a file put in a share is made readable as: whatever the server's
# umask says, the same as one made through the mount. The temporary file it
# arrives in is private, as temporary files are, so it is set on the way in.
_UMASK = os.umask(0)
os.umask(_UMASK)
FILE_MODE = 0o666 & ~_UMASK


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


def _server_share(state: AppState, user: User, name: str) -> Share:
    """The share *name* on the server — or the caller's own drive, which is
    served the same way and browsed the same way."""
    if is_drive(name):
        return user_drive(state.config, user.username)
    try:
        share = state.shares.require(user.username, name)
    except UnknownShareError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no such share: {name}"
        ) from exc
    if share.kind != SERVER:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{share.name} is on one of your machines, not the server — "
            "mount it to browse it",
        )
    return share


def _inside(share: Share, raw: str) -> Path:
    """The path *raw* names inside the share's folder, or a 400."""
    if not raw.strip("/ "):
        return share.path.resolve()
    try:
        return resolve_within(share.path, raw)
    except UnsafePathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _mime(path: Path) -> str:
    guessed, _encoding = mimetypes.guess_type(path.name)
    return guessed or ""


def _entry(path: Path) -> EntryOut:
    info = path.stat()
    is_dir = path.is_dir()
    return EntryOut(
        name=path.name,
        is_dir=is_dir,
        size=0 if is_dir else info.st_size,
        modified=info.st_mtime,
        mime="" if is_dir else _mime(path),
    )


_BAD_NAME = re.compile(r"[\x00-\x1f/\\]")


def _file_name(raw: str) -> str:
    """A name a file may be saved under: one segment, nothing hidden, not silly long."""
    name = raw.strip()
    if not name or name in {".", ".."} or name.startswith(".") or _BAD_NAME.search(name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="not a usable file name"
        )
    if len(name.encode("utf-8")) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="the file name is too long"
        )
    return name


def _free(folder: Path, name: str) -> Path:
    """*name* in *folder*, or "name 2", "name 3"… when that is taken — a
    phone calls every photo image.jpg, and nothing here is overwritten."""
    target = folder / name
    if not target.exists():
        return target
    stem, suffix = os.path.splitext(name)
    for n in range(2, 1000):
        candidate = folder / f"{stem} {n}{suffix}"
        if not candidate.exists():
            return candidate
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail=f"too many files called {name}"
    )


@router.get("/{name}/ls", response_model=ListingOut)
def list_folder(
    name: str,
    path: str = Query(default="", description="A folder inside the share; empty for the top"),
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> ListingOut:
    """What is in a folder of the share. Sorting is the browser's business."""
    share = _server_share(state, user, name)
    folder = _inside(share, path)
    if not folder.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such folder")
    entries: list[EntryOut] = []
    try:
        children = sorted(folder.iterdir(), key=lambda child: child.name.lower())
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="the server cannot read that folder"
        ) from exc
    for child in children:
        # Dotfiles are the folder's own business, and a symlink is not
        # followed — the same two rules the mount lives by.
        if child.name.startswith(".") or child.is_symlink():
            continue
        try:
            info = child.stat()
        except OSError:
            continue
        is_dir = child.is_dir()
        entries.append(
            EntryOut(
                name=child.name,
                is_dir=is_dir,
                size=0 if is_dir else info.st_size,
                modified=info.st_mtime,
                mime="" if is_dir else _mime(child),
            )
        )
    return ListingOut(share=share.name, path=path.strip("/ "), entries=entries)


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
        media_type=_mime(target) or "application/octet-stream",
        # Someone's files: not for a shared cache, and asked for again next time.
        headers={"Cache-Control": "private, no-cache"},
    )


# -- thumbnails ---------------------------------------------------------------
# The browser's grid shows a folder of pictures as pictures. A phone's photo
# is a few megabytes, and a folder holds hundreds, so it asks for a small
# one: the long edge at one of a few sizes, made once and kept under the
# data dir. What the cache is keyed by includes when the file changed, so a
# re-uploaded picture gets a fresh one and the stale one is just never
# asked for again.
THUMB_SIZES = (128, 256, 512, 1024)
# What Pillow reads reliably. HEIC and SVG are not in it: a phone's HEIC
# needs a plugin the server may not have, and a drawing has no pixels to
# scale until it is drawn. Those show as their icon in the grid.
THUMB_TYPES = frozenset({
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "image/tiff",
})
NOT_SCALABLE = "not a picture the server can scale"


def _thumb_size(size: int) -> int:
    """The smallest of the sizes on offer that is at least *size*."""
    for edge in THUMB_SIZES:
        if size <= edge:
            return edge
    return THUMB_SIZES[-1]


def _thumb_path(state: AppState, share: Share, target: Path, edge: int) -> Path:
    info = target.stat()
    inside = target.relative_to(share.path.resolve())
    key = f"{share.owner}|{share.name}|{inside}|{info.st_mtime_ns}|{info.st_size}|{edge}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return state.config.data_dir / "thumbs" / digest[:2] / f"{digest[2:]}.jpg"


def _make_thumb(source: Path, out: Path, edge: int) -> None:
    """Write *source* scaled so its long edge is *edge*, as a JPEG, at *out*.

    Turned the way the camera says it was held, then drawn onto a plain
    ground when it has holes — a JPEG has no alpha, and the grid is one
    colour anyway.
    """
    from PIL import Image, ImageOps

    with Image.open(source) as image:
        # A JPEG can be decoded at a fraction of its size when only a small
        # picture is wanted: much less work for the same thumbnail.
        image.draft("RGB", (edge * 2, edge * 2))
        image = ImageOps.exif_transpose(image) or image
        image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        if image.mode in ("RGBA", "LA", "P"):
            rgba = image.convert("RGBA")
            ground = Image.new("RGBA", rgba.size, (31, 36, 46, 255))
            image = Image.alpha_composite(ground, rgba)
        image = image.convert("RGB")
        out.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            dir=out.parent, prefix=".thumb-", suffix=".jpg", delete=False
        )
        try:
            with handle:
                image.save(handle, "JPEG", quality=82, optimize=True)
            os.replace(handle.name, out)
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)
            raise


@router.get("/{name}/thumb")
def read_thumb(
    name: str,
    path: str = Query(description="The picture inside the share"),
    size: int = Query(default=256, ge=1, description="The long edge wanted, in pixels"),
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> FileResponse:
    """A small copy of a picture, for the grid. Not a picture, or not one
    the server can read: a 415, and the browser shows the icon instead."""
    share = _server_share(state, user, name)
    target = _inside(share, path)
    if not target.is_file() or os.path.islink(target):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such file")
    if _mime(target) not in THUMB_TYPES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=NOT_SCALABLE)
    edge = _thumb_size(size)
    out = _thumb_path(state, share, target, edge)
    if not out.is_file():
        try:
            _make_thumb(target, out, edge)
        except ImportError as exc:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Pillow is not installed on the server",
            ) from exc
        except Exception as exc:  # a picture Pillow cannot read, or one too big to try
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=NOT_SCALABLE
            ) from exc
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
    share = _server_share(state, user, name)
    folder = _inside(share, path)
    if not folder.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such folder")
    target = _free(folder, _file_name(filename))
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
    return _entry(target)
