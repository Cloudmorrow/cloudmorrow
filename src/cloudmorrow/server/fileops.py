"""What can be done with the files in a server share, for whoever asks.

Two things ask: the share file routes (`/api/shares/<name>/ls`, `file`,
`thumb`, `upload` — the CLI, the agent and the old clients), and the
`shares` backend, which serves the same files as `file` records to the
Files Quill, `cm files` and an assistant. Both go through here, so both
keep the same rules: nothing hidden is listed, no symlink is followed out
of the share, a path is checked against the share's folder before anything
is opened or written, and nothing is overwritten by a file put there.

Only a server share, and the caller's own drive. A machine share's files
are on the machine, and this server never sees them.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cloudmorrow.paths import UnsafePathError, resolve_within
from cloudmorrow.server.shares import Share

__all__ = [
    "FILE_MODE",
    "NOT_SCALABLE",
    "THUMB_SIZES",
    "THUMB_TYPES",
    "Entry",
    "FileOpError",
    "entries",
    "entry",
    "file_name",
    "free_name",
    "inside",
    "mime_of",
    "place",
    "thumbnail",
]

# What a file put in a share is made readable as: whatever the server's
# umask says, the same as one made through the mount. The temporary file it
# arrives in is private, as temporary files are, so it is set on the way in.
_UMASK = os.umask(0)
os.umask(_UMASK)
FILE_MODE = 0o666 & ~_UMASK


class FileOpError(Exception):
    """Something asked of a share's files that cannot be done, and why.

    *status* is the HTTP status it answers as: 400 a bad name or path, 403
    the server cannot read or write there, 404 not there, 409 taken, 415
    not a picture it can scale, 501 no Pillow.
    """

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(slots=True)
class Entry:
    name: str
    is_dir: bool
    # Bytes; 0 for a folder.
    size: int
    # Seconds since the epoch.
    modified: float
    # Nanoseconds, for a version that changes whenever the file does.
    modified_ns: int
    # A guess from the name, "" when there is none.
    mime: str = ""


def mime_of(path: Path | str) -> str:
    guessed, _encoding = mimetypes.guess_type(Path(path).name)
    return guessed or ""


def inside(share: Share, raw: str) -> Path:
    """The path *raw* names inside the share's folder."""
    if not str(raw or "").strip("/ "):
        return share.path.resolve()
    try:
        return resolve_within(share.path, raw)
    except UnsafePathError as exc:
        raise FileOpError(400, str(exc)) from exc


def entry(path: Path) -> Entry:
    info = path.stat()
    is_dir = path.is_dir()
    return Entry(
        name=path.name,
        is_dir=is_dir,
        size=0 if is_dir else info.st_size,
        modified=info.st_mtime,
        modified_ns=info.st_mtime_ns,
        mime="" if is_dir else mime_of(path),
    )


def entries(folder: Path) -> list[Entry]:
    """What is in *folder*, by name. Dotfiles are the folder's own business,
    and a symlink is not followed — the same two rules the mount lives by."""
    if not folder.is_dir():
        raise FileOpError(404, "no such folder")
    try:
        children = sorted(folder.iterdir(), key=lambda child: child.name.lower())
    except OSError as exc:
        raise FileOpError(403, "the server cannot read that folder") from exc
    found: list[Entry] = []
    for child in children:
        if child.name.startswith(".") or child.is_symlink():
            continue
        try:
            found.append(entry(child))
        except OSError:
            continue
    return found


_BAD_NAME = re.compile(r"[\x00-\x1f/\\]")


def file_name(raw: str) -> str:
    """A name a file may be saved under: one segment, nothing hidden, not silly long."""
    name = str(raw or "").strip()
    if not name or name in {".", ".."} or name.startswith(".") or _BAD_NAME.search(name):
        raise FileOpError(400, "not a usable file name")
    if len(name.encode("utf-8")) > 255:
        raise FileOpError(400, "the file name is too long")
    return name


def free_name(folder: Path, name: str) -> Path:
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
    raise FileOpError(409, f"too many files called {name}")


def place(source: Path, folder: Path, name: str) -> Path:
    """Put the whole of *source* in *folder* as *name* (or a free name like it).

    Named into place only once all of it is there, so a copy that fails half
    way leaves no half a photo with a photo's name. Returns where it went.
    """
    if not folder.is_dir():
        raise FileOpError(404, "no such folder")
    target = free_name(folder, file_name(name))
    try:
        handle = tempfile.NamedTemporaryFile(dir=folder, prefix=".upload-", delete=False)
    except OSError as exc:
        raise FileOpError(403, "the server cannot write to that folder") from exc
    part = Path(handle.name)
    try:
        with handle, open(source, "rb") as src:
            shutil.copyfileobj(src, handle, 1024 * 1024)
        os.chmod(part, FILE_MODE)
        os.replace(part, target)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return target


# -- thumbnails ---------------------------------------------------------------
# A grid shows a folder of pictures as pictures. A phone's photo is a few
# megabytes, and a folder holds hundreds, so it asks for a small one: the
# long edge at one of a few sizes, made once and kept under the data dir.
# What the cache is keyed by includes when the file changed, so a
# re-uploaded picture gets a fresh one and the stale one is just never
# asked for again.
THUMB_SIZES = (128, 256, 512, 1024)
# What Pillow reads reliably. HEIC and SVG are not in it: a phone's HEIC
# needs a plugin the server may not have, and a drawing has no pixels to
# scale until it is drawn. Those show as their icon in the grid.
THUMB_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/bmp",
        "image/tiff",
    }
)
NOT_SCALABLE = "not a picture the server can scale"


def _thumb_size(size: int) -> int:
    """The smallest of the sizes on offer that is at least *size*."""
    for edge in THUMB_SIZES:
        if size <= edge:
            return edge
    return THUMB_SIZES[-1]


def _thumb_path(data_dir: Path, share: Share, target: Path, edge: int) -> Path:
    info = target.stat()
    within = target.relative_to(share.path.resolve())
    key = f"{share.owner}|{share.name}|{within}|{info.st_mtime_ns}|{info.st_size}|{edge}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return data_dir / "thumbs" / digest[:2] / f"{digest[2:]}.jpg"


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


def thumbnail(data_dir: Path, share: Share, target: Path, size: int) -> Path:
    """A small copy of the picture at *target*, made if it is not made yet."""
    if not target.is_file() or os.path.islink(target):
        raise FileOpError(404, "no such file")
    if mime_of(target) not in THUMB_TYPES:
        raise FileOpError(415, NOT_SCALABLE)
    edge = _thumb_size(size)
    out = _thumb_path(data_dir, share, target, edge)
    if not out.is_file():
        try:
            _make_thumb(target, out, edge)
        except ImportError as exc:
            raise FileOpError(501, "Pillow is not installed on the server") from exc
        except Exception as exc:  # a picture Pillow cannot read, or one too big to try
            raise FileOpError(415, NOT_SCALABLE) from exc
    return out
