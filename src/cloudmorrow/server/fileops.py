"""What can be done with the files in a server share, for whoever asks.

Two things ask: the share file routes (`/api/shares/<name>/ls`, `file`,
`thumb`, `upload` — the CLI and the old clients), and the
`shares` backend, which serves the same files as `file` records to the
Files Quill, `cm files` and an assistant. Both go through here, so both
keep the same rules: nothing hidden is listed, no symlink is followed out
of the share, a path is checked against the share's folder before anything
is opened or written, and nothing is overwritten by a file put there.

What is deleted goes to the share's Trash, and comes back from it, until a
sweep removes it for good (the Trash section, at the end).

A share on the server, and the caller's own drive: which of them a caller
has, and whether they may change what is in one, is the caller's business
(routes/sharefiles.py, backends/shares.py), not this module's.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cloudmorrow.runtimes import RUNTIMES_DIR
from cloudmorrow.server.paths import UnsafePathError, resolve_within
from cloudmorrow.server.shares import Share

__all__ = [
    "FILE_MODE",
    "NOT_SCALABLE",
    "THUMB_SIZES",
    "THUMB_TYPES",
    "TRASH",
    "TRASH_KEEP",
    "Entry",
    "FileOpError",
    "empty_trash",
    "entries",
    "entry",
    "file_name",
    "forget_trashed",
    "free_name",
    "in_trash",
    "inside",
    "mime_of",
    "moved",
    "place",
    "remove",
    "sweep_trash",
    "thumbnail",
    "trash",
    "trash_top",
    "trashed",
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


# -- a name with a suffix ------------------------------------------------------
# A phone's picker can hand a photo over as "1000001234" or "image", with no
# suffix at all. The name is what everything reads the type from, so without
# one the picture is a plain file to the grid, the thumbnails and the mount.
# The bytes say what it is; an uploaded name with no suffix gets one from them.
_FTYP_SUFFIX = {
    b"qt  ": ".mov",
    b"M4A ": ".m4a",
    b"avif": ".avif",
    b"heic": ".heic",
    b"heix": ".heic",
    b"heif": ".heic",
    b"mif1": ".heic",
    b"msf1": ".heic",
}
_PILLOW_SUFFIX = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "GIF": ".gif",
    "WEBP": ".webp",
    "BMP": ".bmp",
    "TIFF": ".tiff",
}


def sniffed_suffix(source: Path) -> str:
    """The suffix *source*'s bytes call for: a picture Pillow recognises, or an
    ISO media file (a phone's video, a HEIC) by its brand. "" for anything else."""
    try:
        with open(source, "rb") as handle:
            head = handle.read(12)
    except OSError:
        return ""
    if head[4:8] == b"ftyp":
        return _FTYP_SUFFIX.get(head[8:12], ".mp4")
    try:
        from PIL import Image

        with Image.open(source) as image:
            return _PILLOW_SUFFIX.get(image.format or "", "")
    except Exception:  # noqa: BLE001 - not a picture, or not one Pillow reads
        return ""


def with_suffix(name: str, source: Path) -> str:
    """*name* as given when it has a suffix, else with the one its bytes say."""
    return name if os.path.splitext(name)[1] else name + sniffed_suffix(source)


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
# A video's thumbnail is a frame from a second in, drawn with ffmpeg: the
# runtime a Quill brought (`[requires] runtimes = ["ffmpeg"]`), or one on
# the system. Without either, a video has no picture and the client shows
# its icon.
NO_FFMPEG = "no ffmpeg on the server to draw a video's picture with"
FRAME_TIMEOUT = 30


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
        handle = tempfile.NamedTemporaryFile(dir=out.parent, prefix=".thumb-", suffix=".jpg", delete=False)
        try:
            with handle:
                image.save(handle, "JPEG", quality=82, optimize=True)
            os.replace(handle.name, out)
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)
            raise


def ffmpeg_for(data_dir: Path) -> str | None:
    """The ffmpeg to draw a video's frame with: the server's runtime, or the system's."""
    own = data_dir / RUNTIMES_DIR / "ffmpeg" / "bin" / "ffmpeg"
    return str(own) if own.exists() else shutil.which("ffmpeg")


def _video_thumb(data_dir: Path, source: Path, out: Path, edge: int) -> None:
    """A frame of the video at *source*, a second in (the first, for one
    shorter), scaled as a picture's thumbnail is."""
    ffmpeg = ffmpeg_for(data_dir)
    if ffmpeg is None:
        raise FileOpError(415, NO_FFMPEG)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent, prefix=".frame-") as tmp:
        frame = Path(tmp) / "frame.png"
        for at in ("1", "0"):
            try:
                subprocess.run(
                    [
                        ffmpeg,
                        "-nostdin",
                        "-v",
                        "error",
                        "-ss",
                        at,
                        "-i",
                        str(source),
                        "-frames:v",
                        "1",
                        "-y",
                        str(frame),
                    ],
                    capture_output=True,
                    timeout=FRAME_TIMEOUT,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                break
            if frame.is_file() and frame.stat().st_size:
                _make_thumb(frame, out, edge)
                return
    raise FileOpError(415, NOT_SCALABLE)


def thumbnail(data_dir: Path, share: Share, target: Path, size: int) -> Path:
    """A small copy of the picture at *target*, made if it is not made yet."""
    if not target.is_file() or os.path.islink(target):
        raise FileOpError(404, "no such file")
    mime = mime_of(target) or ""
    video = mime.startswith("video/")
    if mime not in THUMB_TYPES and not video:
        raise FileOpError(415, NOT_SCALABLE)
    edge = _thumb_size(size)
    out = _thumb_path(data_dir, share, target, edge)
    if not out.is_file():
        try:
            if video:
                _video_thumb(data_dir, target, out, edge)
            else:
                _make_thumb(target, out, edge)
        except FileOpError:
            raise
        except ImportError as exc:
            raise FileOpError(501, "Pillow is not installed on the server") from exc
        except Exception as exc:  # a picture Pillow cannot read, or one too big to try
            raise FileOpError(415, NOT_SCALABLE) from exc
    return out


# -- the Trash ----------------------------------------------------------------
# What is deleted from a share is not gone: it goes to a Trash folder at the
# top of the share, the way a desktop's does, and is put back from there —
# where it was, or wherever it is moved to — until a sweep removes what has
# been there TRASH_KEEP. Deleting something that is in the Trash already
# removes it for good, and so does deleting the Trash itself.
#
# Beside each thing in the Trash a line says where it came from and when,
# in a hidden folder nothing lists, keyed by the thing's name in the Trash.
# Something put in the Trash another way — over a mount, with no line — is
# adopted the first time the server sees it: dated then, from the top of
# the share, so it too is restored and swept.
TRASH = "Trash"
TRASH_KEEP = dt.timedelta(days=30)
_TRASH_INFO = ".info"


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


def in_trash(path: str) -> bool:
    """Whether *path* (relative to the share) is the Trash or something in it."""
    path = path.strip("/")
    return path == TRASH or path.startswith(TRASH + "/")


def trash_top(path: str) -> str | None:
    """The name of the thing directly in the Trash that *path* is, or is
    under: "Trash/Tax/2025.pdf" is under "Tax". None outside the Trash, and
    for the Trash itself."""
    parts = path.strip("/").split("/")
    if len(parts) < 2 or parts[0] != TRASH:
        return None
    return parts[1]


def _trash_dir(share: Share) -> Path:
    return share.path.resolve() / TRASH


def _info_path(share: Share, name: str) -> Path:
    return _trash_dir(share) / _TRASH_INFO / f"{name}.json"


def _read_info(share: Share, name: str) -> dict | None:
    try:
        data = json.loads(_info_path(share, name).read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("at"), str) or not data["at"]:
        return None
    return {"from": str(data.get("from") or "").strip("/"), "at": data["at"]}


def _write_info(share: Share, name: str, origin: str, at: str) -> None:
    path = _info_path(share, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f".{path.name}.tmp")
    part.write_text(json.dumps({"from": origin.strip("/"), "at": at}), "utf-8")
    os.replace(part, path)


def forget_trashed(share: Share, name: str) -> None:
    """The line beside *name* in the Trash, gone with it."""
    _info_path(share, name).unlink(missing_ok=True)


def _adopt(share: Share, name: str) -> dict:
    info = _read_info(share, name)
    if info is None:
        info = {"from": "", "at": _now()}
        try:
            _write_info(share, name, "", info["at"])
        except OSError:
            pass
    return info


def trashed(share: Share, path: str) -> tuple[str, str] | None:
    """For something in the Trash: when it was put there, and where it came
    from — the path it had, folders and all; for something inside a folder
    that was deleted, its path inside that folder's old place. None for
    anything not in the Trash, and for the Trash itself."""
    top = trash_top(path)
    if top is None:
        return None
    info = _adopt(share, top)
    rest = path.strip("/").split("/", 2)[2:]
    origin = info["from"] or top
    return info["at"], "/".join([origin, *rest])


def remove(target: Path) -> None:
    """*target* gone for good, whatever it is."""
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
    else:
        target.unlink()


def trash(share: Share, path: str, target: Path) -> Path:
    """Move *target*, at *path* in the share, into the Trash. Returns where it
    is now: its own name, or "name 2" when that is taken."""
    folder = _trash_dir(share)
    try:
        folder.mkdir(exist_ok=True)
    except OSError as exc:
        raise FileOpError(403, "the server cannot make the Trash") from exc
    dest = free_name(folder, target.name)
    try:
        os.rename(target, dest)
    except OSError as exc:
        raise FileOpError(403, f"the server cannot move {path} to the Trash: {exc.strerror or exc}") from exc
    try:
        _write_info(share, dest.name, path, _now())
    except OSError:
        pass  # adopted at the next look: dated then, from the top
    return dest


def empty_trash(share: Share) -> None:
    """The Trash and everything in it, gone for good."""
    folder = _trash_dir(share)
    if folder.is_dir() and not folder.is_symlink():
        shutil.rmtree(folder)


def _direct(path: str) -> str | None:
    """The name of *path* when it is directly in the Trash, else None."""
    top = trash_top(path)
    return top if top is not None and path.strip("/") == f"{TRASH}/{top}" else None


def moved(share: Share, old_path: str, new_path: str) -> None:
    """Keep the Trash's lines true after a rename or move from *old_path*
    to *new_path*: renamed in the Trash, the line follows; moved out, it is
    restored and the line goes; moved in by hand, it is deleted, from where
    it was."""
    old, new = _direct(old_path), _direct(new_path)
    try:
        if old is not None and new is not None:
            info = _read_info(share, old)
            forget_trashed(share, old)
            if info is not None:
                _write_info(share, new, info["from"], info["at"])
        elif old is not None:
            forget_trashed(share, old)
        elif new is not None and not in_trash(old_path):
            _write_info(share, new, old_path, _now())
    except OSError:
        pass


def sweep_trash(share: Share, now: dt.datetime | None = None) -> int:
    """Remove what has been in the share's Trash for TRASH_KEEP, and the
    lines of things no longer there. Returns how many went."""
    folder = _trash_dir(share)
    if not folder.is_dir() or folder.is_symlink():
        return 0
    now = now or dt.datetime.now(tz=dt.UTC)
    gone = 0
    names: set[str] = set()
    for child in list(folder.iterdir()):
        if child.name.startswith("."):
            continue
        names.add(child.name)
        info = _adopt(share, child.name)
        try:
            at = dt.datetime.fromisoformat(info["at"])
        except ValueError:
            # A line nothing can read: the thing is as good as just arrived.
            try:
                _write_info(share, child.name, info["from"], _now())
            except OSError:
                pass
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=dt.UTC)
        if now - at >= TRASH_KEEP:
            try:
                remove(child)
            except OSError:
                continue
            forget_trashed(share, child.name)
            gone += 1
    lines = folder / _TRASH_INFO
    if lines.is_dir():
        for line in list(lines.iterdir()):
            if line.suffix == ".json" and line.stem not in names:
                line.unlink(missing_ok=True)
    return gone
