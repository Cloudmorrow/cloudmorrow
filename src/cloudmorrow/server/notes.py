"""Notes on disk.

Notes are markdown files in a directory tree; folders in the tree are
folders on disk. Each file is sealed (`cloudmorrow.server.sealed`): the
name on disk is the note's title, the bytes inside are ciphertext under
the server's key, and this store is the only thing that reads them. The
tree is still a tree — a folder is a folder, a note is a file, and a copy
of the directory is a backup — but it is not a place to open a file with
an editor any more.

They belong to the person, not to a project: one tree per user, at
`<base>/notes`.

Pictures live beside them, in `<base>/notes/img`: one flat folder, named by
when each arrived, that the tree never lists. A picture is something a note
shows — `![holiday](img/20260917-134501-ab12cd-holiday.jpg)` — not a thing to
find in the list, so the folder is there for the files and invisible
otherwise.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import secrets
import shutil
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from cloudmorrow.paths import UnsafePathError, normalise_rel_path, resolve_within
from cloudmorrow.server.sealed import Sealer, is_sealed_file, plain_size

NOTE_SUFFIX = ".md"
MAX_SEARCH_RESULTS = 200
MAX_SEARCH_FILE_BYTES = 2_000_000

# Where a user's pictures go, under their notes root, and what one may be.
IMAGE_DIR = "img"
MAX_IMAGE_BYTES = 25_000_000
IMAGE_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}
_IMAGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,160}$")
_IMAGE_STEM_RE = re.compile(r"[^a-z0-9]+")


class NoteNotFoundError(LookupError):
    pass


class NoteExistsError(FileExistsError):
    pass


class InvalidImageError(ValueError):
    """Not a picture we keep: empty, too big, or not PNG, JPEG, GIF or WebP."""


def sniff_image(data: bytes) -> str | None:
    """The media type the bytes say they are — never what the upload claimed."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@dataclass(slots=True)
class ImageInfo:
    """A picture in the img folder, as the API describes it."""

    name: str
    size: int
    content_type: str

    @property
    def path(self) -> str:
        """What a note writes: `img/<name>`, relative to the notes root."""
        return f"{IMAGE_DIR}/{self.name}"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "size": self.size,
            "content_type": self.content_type,
        }


class NoteConflictError(RuntimeError):
    """The file changed on disk since the client last read it."""

    def __init__(self, current_rev: str, current_content: str) -> None:
        super().__init__("note changed on the server")
        self.current_rev = current_rev
        self.current_content = current_content


@dataclass(slots=True)
class NoteNode:
    """One entry in the note tree."""

    name: str
    path: str
    is_dir: bool
    size: int = 0
    modified: float = 0.0
    children: list[NoteNode] = field(default_factory=list)
    # The first line or two of the body, for a list that shows what a note
    # says rather than only what it is called. Only filled in when asked for.
    preview: str | None = None

    def to_dict(self) -> dict:
        payload = {
            "name": self.name,
            "path": self.path,
            "is_dir": self.is_dir,
            "size": self.size,
            "modified": self.modified,
        }
        if self.is_dir:
            payload["children"] = [child.to_dict() for child in self.children]
        if self.preview is not None:
            payload["preview"] = self.preview
        return payload


@dataclass(slots=True)
class NoteContent:
    path: str
    content: str
    rev: str
    size: int
    modified: float


# What may sit beside `notes` under a user's base without being a stray
# note: `files`, the person's own drive (`cloudmorrow.server.drive`);
# `projects` from the old layout; `shares`, where server shares used to be
# kept per user; and `Shares`, where they all are now — which is a sibling
# of the user bases, or the base itself when there is one tree.
LAYOUT_DIRS = {"notes", "files", "projects", "shares", "Shares"}


def ensure_notes_layout(base: Path) -> bool:
    """Make sure `<base>/notes` exists, and holds everything that is a note.

    Two older layouts get folded in: notes kept directly in `<base>`, from
    before there was a `notes` directory at all; and notes kept per project in
    `<base>/projects/<slug>/notes`, from when a project had its own. A
    project's notes become a folder of that name, because a project no longer
    holds notes — the person does.

    Returns True when something actually moved, so the caller can log it.
    """
    base.mkdir(parents=True, exist_ok=True)
    notes = base / "notes"
    moved = False
    if not notes.exists():
        strays = [entry for entry in base.iterdir() if entry.name not in LAYOUT_DIRS]
        notes.mkdir()
        for stray in strays:
            shutil.move(str(stray), str(notes / stray.name))
        moved = bool(strays)
    projects = base / "projects"
    if not projects.is_dir():
        return moved
    for project in sorted(projects.iterdir()):
        if not project.is_dir():
            continue
        source = project / "notes"
        if source.is_dir():
            if any(source.iterdir()):
                shutil.move(str(source), str(_free_name(notes, project.name)))
                moved = True
            else:
                source.rmdir()
                moved = True
        # Only what is empty is removed. Anything else in there was put there
        # by someone, and this is not the place to decide it can go.
        if not any(project.iterdir()):
            project.rmdir()
            moved = True
    if not any(projects.iterdir()):
        projects.rmdir()
        moved = True
    return moved


def _free_name(parent: Path, stem: str) -> Path:
    """`parent/stem`, or `parent/stem-2`… — whichever is not taken."""
    candidate = parent / stem
    counter = 2
    while candidate.exists():
        candidate = parent / f"{stem}-{counter}"
        counter += 1
    return candidate


PREVIEW_CHARS = 120
PREVIEW_BYTES = 4096


def note_preview(text: str, name: str, *, chars: int = PREVIEW_CHARS) -> str:
    """The first couple of lines of a note, as a list would show them.

    The heading the TUI writes on every new note repeats the file name, so it
    is skipped; so are blank lines and the markdown markers a phone does not
    need to see. Only the head of the text is looked at, since a list does
    this for every note it shows.
    """
    head = text[:PREVIEW_BYTES]
    stem = name[: -len(NOTE_SUFFIX)] if name.endswith(NOTE_SUFFIX) else name
    lines: list[str] = []
    for raw in head.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.lstrip("#").strip() == stem and line.startswith("#"):
            continue
        # A picture on a line of its own is shown in the note, not said in a list.
        if line.startswith("![") and line.endswith(")"):
            continue
        line = line.lstrip("#").strip()
        for marker in ("- [ ] ", "- [x] ", "- ", "* "):
            line = line.removeprefix(marker)
        lines.append(line)
        if len(" ".join(lines)) >= chars or len(lines) >= 2:
            break
    text = " ".join(lines)
    return text[: chars - 1] + "…" if len(text) > chars else text


def file_rev(path: Path) -> str:
    """A cheap revision marker used for optimistic concurrency."""
    stat = path.stat()
    return f"{stat.st_mtime_ns}-{stat.st_size}"


class NoteStore:
    """All note operations for a single user's root directory.

    Every file under it goes through *sealer* on the way in and out.
    """

    def __init__(self, root: Path, sealer: Sealer) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = self.root.resolve()
        self.sealer = sealer

    # -- helpers -----------------------------------------------------------
    def _resolve(self, rel_path: str) -> Path:
        return resolve_within(self.root, rel_path)

    def _read_bytes(self, path: Path) -> bytes:
        return self.sealer.unseal_file(path.read_bytes())

    def _read_text(self, path: Path, *, errors: str = "strict") -> str:
        return self._read_bytes(path).decode("utf-8", errors=errors)

    def _write_bytes(self, path: Path, data: bytes) -> None:
        """Seal and write atomically: the file is whole or it is not there."""
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_bytes(self.sealer.seal_file(data))
        os.replace(tmp, path)

    @staticmethod
    def _content_size(path: Path, stored: int) -> int:
        """How long the note is, not how long its ciphertext is."""
        try:
            with path.open("rb") as handle:
                sealed = is_sealed_file(handle.read(8))
        except OSError:
            return stored
        return plain_size(stored) if sealed else stored

    def _rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    @staticmethod
    def _is_hidden(name: str) -> bool:
        return name.startswith(".")

    @staticmethod
    def with_suffix(rel_path: str) -> str:
        """Ensure a note path ends in .md (folders are handled separately)."""
        rel = normalise_rel_path(rel_path)
        if rel.suffix.lower() != NOTE_SUFFIX:
            rel = rel.with_name(rel.name + NOTE_SUFFIX)
        return rel.as_posix()

    # -- reads -------------------------------------------------------------
    def tree(self, *, previews: bool = False) -> NoteNode:
        root_node = NoteNode(name="notes", path="", is_dir=True)
        self._walk(self.root, root_node, previews=previews)
        return root_node

    def _walk(self, directory: Path, node: NoteNode, *, previews: bool = False) -> None:
        try:
            entries = sorted(
                os.scandir(directory), key=lambda e: (not e.is_dir(), e.name.lower())
            )
        except FileNotFoundError:
            return
        for entry in entries:
            if self._is_hidden(entry.name):
                continue
            if directory == self.root and entry.name == IMAGE_DIR and entry.is_dir():
                # The pictures. Seen inside a note, never in the list.
                continue
            entry_path = Path(entry.path)
            if entry.is_dir(follow_symlinks=False):
                child = NoteNode(
                    name=entry.name,
                    path=self._rel(entry_path),
                    is_dir=True,
                    modified=entry.stat().st_mtime,
                )
                self._walk(entry_path, child, previews=previews)
                node.children.append(child)
            elif entry.is_file(follow_symlinks=False) and entry.name.endswith(NOTE_SUFFIX):
                stat = entry.stat()
                node.children.append(
                    NoteNode(
                        name=entry.name,
                        path=self._rel(entry_path),
                        is_dir=False,
                        size=self._content_size(entry_path, stat.st_size),
                        modified=stat.st_mtime,
                        preview=self._preview(entry_path, stat.st_size) if previews else None,
                    )
                )

    def _preview(self, path: Path, stored: int) -> str:
        # A sealed file has to be opened whole to read its head; a note
        # too big to search is too big to preview, and gets none.
        if stored > MAX_SEARCH_FILE_BYTES:
            return ""
        try:
            return note_preview(self._read_text(path, errors="replace"), path.name)
        except OSError:
            return ""

    def read(self, rel_path: str) -> NoteContent:
        path = self._resolve(self.with_suffix(rel_path))
        if not path.is_file():
            raise NoteNotFoundError(rel_path)
        stat = path.stat()
        content = self._read_text(path)
        return NoteContent(
            path=self._rel(path),
            content=content,
            rev=file_rev(path),
            size=len(content.encode("utf-8")),
            modified=stat.st_mtime,
        )

    def search(self, query: str, *, limit: int = MAX_SEARCH_RESULTS) -> list[dict]:
        """Case-insensitive substring search across note bodies and names."""
        needle = query.strip().lower()
        if not needle:
            return []
        results: list[dict] = []
        for path in sorted(self.root.rglob(f"*{NOTE_SUFFIX}")):
            if any(self._is_hidden(part) for part in path.relative_to(self.root).parts):
                continue
            rel = self._rel(path)
            hits: list[dict] = []
            if needle in path.name.lower():
                hits.append({"line": 0, "text": path.name})
            try:
                if path.stat().st_size <= MAX_SEARCH_FILE_BYTES:
                    lines = self._read_text(path, errors="replace").splitlines()
                    for line_no, line in enumerate(lines, start=1):
                        if needle in line.lower():
                            hits.append({"line": line_no, "text": line.rstrip()[:200]})
                            if len(hits) >= 5:
                                break
            except OSError:
                continue
            if hits:
                results.append({"path": rel, "name": path.name, "matches": hits})
            if len(results) >= limit:
                break
        return results

    # -- pictures ----------------------------------------------------------
    @property
    def image_dir(self) -> Path:
        return self.root / IMAGE_DIR

    def save_image(self, data: bytes, *, filename: str = "") -> ImageInfo:
        """Keep a picture, under a name that says when it arrived.

        `20260917-134501-ab12cd-holiday.jpg`: the moment, six random hex so two
        pastes in one second cannot collide, and what the file was called if
        it was called anything, so `ls img/` still means something. The type
        comes from the bytes, not the name it arrived under.
        """
        if not data:
            raise InvalidImageError("the image is empty")
        if len(data) > MAX_IMAGE_BYTES:
            limit = MAX_IMAGE_BYTES // 1_000_000
            raise InvalidImageError(f"the image is too big — {limit} MB at most")
        content_type = sniff_image(data)
        if content_type is None:
            raise InvalidImageError("not a PNG, JPEG, GIF or WebP image")
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        stem = _IMAGE_STEM_RE.sub("-", Path(filename).stem.lower()).strip("-")[:40]
        name = "-".join(part for part in (stamp, secrets.token_hex(3), stem) if part)
        name = f"{name}.{IMAGE_TYPES[content_type]}"
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self._write_bytes(self.image_dir / name, data)
        return ImageInfo(name=name, size=len(data), content_type=content_type)

    def image(self, name: str) -> tuple[bytes, str]:
        """A picture's bytes, and its media type."""
        if not _IMAGE_NAME_RE.match(name or ""):
            raise UnsafePathError("that is not an image name")
        path = self.image_dir / name
        if not path.is_file():
            raise NoteNotFoundError(name)
        data = self._read_bytes(path)
        return data, sniff_image(data) or "application/octet-stream"

    # -- writes ------------------------------------------------------------
    def write(self, rel_path: str, content: str, *, rev: str | None = None) -> NoteContent:
        """Write a note atomically. Pass *rev* to refuse clobbering a newer file."""
        path = self._resolve(self.with_suffix(rel_path))
        if rev is not None and path.exists():
            current = file_rev(path)
            if current != rev:
                raise NoteConflictError(current, self._read_text(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_bytes(path, content.encode("utf-8"))
        return self.read(self._rel(path))

    def create_note(self, rel_path: str, content: str = "") -> NoteContent:
        path = self._resolve(self.with_suffix(rel_path))
        if path.exists():
            raise NoteExistsError(rel_path)
        return self.write(self._rel_or_raw(path, rel_path), content)

    def _rel_or_raw(self, path: Path, fallback: str) -> str:
        """Relative path for a file that may not exist yet."""
        try:
            return self._rel(path)
        except (ValueError, OSError):
            return fallback

    def create_dir(self, rel_path: str) -> str:
        path = self._resolve(rel_path)
        if path.exists():
            raise NoteExistsError(rel_path)
        path.mkdir(parents=True)
        return self._rel(path)

    def delete(self, rel_path: str, *, recursive: bool = False) -> None:
        path = self._resolve(rel_path)
        if not path.exists():
            # A note path may have been given without its .md suffix.
            path = self._resolve(self.with_suffix(rel_path))
        if not path.exists():
            raise NoteNotFoundError(rel_path)
        if path == self.root:
            raise UnsafePathError("refusing to delete the notes root")
        if path.is_dir():
            if not recursive and any(path.iterdir()):
                raise NoteExistsError(f"{rel_path} is not empty")
            shutil.rmtree(path)
        else:
            path.unlink()

    def move(self, src: str, dest: str) -> str:
        source = self._resolve(src)
        if not source.exists():
            source = self._resolve(self.with_suffix(src))
        if not source.exists():
            raise NoteNotFoundError(src)
        target = self._resolve(self.with_suffix(dest) if source.is_file() else dest)
        if target.exists():
            raise NoteExistsError(dest)
        if source.is_dir() and (source == target or source in target.parents):
            raise UnsafePathError("cannot move a folder inside itself")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        return self._rel(target)


def unique_path(store: NoteStore, parent: str, stem: str, suffix: str = NOTE_SUFFIX) -> str:
    """Find `parent/stem.md`, `parent/stem-2.md`, … that does not exist yet."""
    base = PurePosixPath(parent) if parent else PurePosixPath()
    candidate = (base / f"{stem}{suffix}").as_posix()
    counter = 2
    while (store.root / candidate).exists():
        candidate = (base / f"{stem}-{counter}{suffix}").as_posix()
        counter += 1
    return candidate
