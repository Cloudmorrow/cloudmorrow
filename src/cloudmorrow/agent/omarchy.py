"""What "my Omarchy config" means on disk.

Omarchy is Hyprland with opinions, and its opinions live in `~/.config`. This
is the definition of which parts of that travel between machines, and the
reading and writing of them.

It starts at `hypr`, which is the part I actually edit — keybinds, monitors,
autostart. The rest of `~/.config` is deliberately left alone: plenty of it is
machine-specific (monitor layouts that only make sense on one screen, caches
some app decided to keep next to its settings), and a sync that overwrites
those is worse than no sync at all. Adding to `PATHS` is how that grows, one
directory at a time, once a directory has earned it.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from cloudmorrow.bundles import digest, validate_path

BUNDLE = "omarchy"

# Relative to the bundle root (`~/.config`). Files, directories, or both.
PATHS: tuple[str, ...] = ("hypr",)

# What this leaves behind when it overwrites or replaces a file. These must
# never be scanned back in: a backup that got synced would land on every
# machine, and then be backed up again on the next one.
BACKUP_SUFFIX = ".cloudmorrow-backup"
SCRATCH_SUFFIX = ".cloudmorrow-tmp"

# Those, editor droppings, and the things a compositor writes for itself.
# Matched against the file name, not the path.
SKIP_SUFFIXES = (
    BACKUP_SUFFIX,
    SCRATCH_SUFFIX,
    ".swp",
    ".swo",
    ".tmp",
    ".bak",
    ".orig",
    ".rej",
    "~",
)
SKIP_NAMES = frozenset({".DS_Store", ".git", ".gitignore"})
SKIP_DIRS = frozenset({".git", "__pycache__", "cache", ".cache"})

# A config file that is bigger than this is not a config file.
MAX_FILE_BYTES = 512 * 1024


class BundleError(RuntimeError):
    """The bundle could not be read or written."""


@dataclass(slots=True)
class LocalFile:
    path: str
    content: str
    sha256: str
    mode: int

    def to_payload(self) -> dict:
        return {
            "path": self.path,
            "content": self.content,
            "sha256": self.sha256,
            "mode": self.mode,
        }


@dataclass(slots=True)
class Applied:
    """What writing a revision onto this machine actually did."""

    written: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    # Files that were not ours to overwrite, kept as `<name>.cloudmorrow-backup`
    # — which `scan` skips, so a backup never becomes part of the bundle.
    backed_up: list[str] = field(default_factory=list)
    unchanged: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.written or self.removed)

    def summary(self) -> str:
        parts = []
        if self.written:
            parts.append(f"{len(self.written)} written")
        if self.removed:
            parts.append(f"{len(self.removed)} removed")
        if self.backed_up:
            parts.append(f"{len(self.backed_up)} backed up")
        return ", ".join(parts) or "nothing to do"


def config_root() -> Path:
    """`~/.config`, or wherever XDG says it is."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")).expanduser()


def is_omarchy(root: Path | None = None) -> bool:
    """Whether this machine is an Omarchy box.

    Omarchy's own directory is the honest answer. A Hyprland box that is not
    Omarchy counts too — the bundle is Hyprland config either way, and being
    strict about the distribution would exclude the machine I am most likely
    to want it on next.
    """
    root = root or config_root()
    if (root / "omarchy").is_dir() or Path("/etc/omarchy-release").exists():
        return True
    return (root / "hypr").is_dir() and bool(shutil.which("hyprctl"))


def describe(root: Path | None = None) -> str:
    """One line for the settings screen, whichever way the answer went."""
    root = root or config_root()
    if (root / "omarchy").is_dir():
        return f"Omarchy — {root / 'omarchy'}"
    if Path("/etc/omarchy-release").exists():
        return "Omarchy — /etc/omarchy-release"
    if (root / "hypr").is_dir() and shutil.which("hyprctl"):
        return f"Hyprland — {root / 'hypr'}"
    if (root / "hypr").is_dir():
        return f"{root / 'hypr'} exists, but hyprctl is not installed"
    return f"no {root / 'hypr'} on this machine"


def _skip(name: str) -> bool:
    return name in SKIP_NAMES or name.endswith(SKIP_SUFFIXES)


def scan(root: Path | None = None, paths: tuple[str, ...] = PATHS) -> list[LocalFile]:
    """Read the bundle off this machine.

    Text only, and quietly: a binary blob or an unreadable file is left out
    rather than failing the sync. Symlinks are not followed — a link into a
    dotfiles repo is that machine's arrangement, not something to copy onto
    everyone else.
    """
    root = (root or config_root()).expanduser()
    found: list[LocalFile] = []
    for entry in paths:
        target = root / entry
        if target.is_file():
            candidates = [target]
        elif target.is_dir():
            candidates = sorted(p for p in target.rglob("*") if p.is_file())
        else:
            continue
        for candidate in candidates:
            if candidate.is_symlink() or _skip(candidate.name):
                continue
            if any(part in SKIP_DIRS for part in candidate.relative_to(root).parts):
                continue
            try:
                stat = candidate.stat()
                if stat.st_size > MAX_FILE_BYTES:
                    continue
                content = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                # Binary, or not ours to read. Either way, not config we sync.
                continue
            found.append(
                LocalFile(
                    path=validate_path(candidate.relative_to(root).as_posix()),
                    content=content,
                    sha256=digest(content),
                    mode=stat.st_mode & 0o777,
                )
            )
    return sorted(found, key=lambda f: f.path)


def manifest(files: list[LocalFile]) -> dict[str, str]:
    """path → hash, which is the whole of what "has this changed" needs."""
    return {file.path: file.sha256 for file in files}


def apply(
    files: list[dict],
    *,
    root: Path | None = None,
    known: dict[str, str] | None = None,
) -> Applied:
    """Write a revision onto this machine.

    *known* is the manifest this machine last applied, and it is what makes
    this safe. A file matching it is a copy we put there, so writing over it
    loses nothing. A file that does not — never seen, or edited here since —
    is somebody's work, and it is copied to `<name>.cloudmorrow-backup` before
    the new one lands. The same manifest tells an upstream deletion (was in
    the bundle, is gone) from a local file that was never in it at all, which
    is left exactly where it is.
    """
    root = (root or config_root()).expanduser()
    known = known or {}
    result = Applied()
    incoming = {}
    for entry in files:
        # The server validated these on the way in; this machine does not take
        # that on trust, because it is the one doing the writing.
        incoming[validate_path(str(entry["path"]))] = entry

    for path, entry in sorted(incoming.items()):
        target = root / path
        content = str(entry.get("content", ""))
        mode = int(entry.get("mode", 0o644)) & 0o777
        try:
            existing = target.read_text(encoding="utf-8") if target.is_file() else None
        except (OSError, UnicodeDecodeError):
            existing = None
        if existing == content:
            if target.is_file() and (target.stat().st_mode & 0o777) != mode:
                target.chmod(mode)
            result.unchanged += 1
            continue
        if existing is not None and known.get(path) != digest(existing):
            # Not the copy we left here — either new to us, or edited since.
            # Whichever it is, it is not ours to throw away.
            backup = target.with_name(target.name + BACKUP_SUFFIX)
            try:
                shutil.copy2(target, backup)
                result.backed_up.append(path)
            except OSError as exc:
                raise BundleError(f"could not back up {target}: {exc}") from exc
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Write beside it and move it into place, so a reader never sees
            # half a config file.
            scratch = target.with_name(f".{target.name}{SCRATCH_SUFFIX}")
            scratch.write_text(content, encoding="utf-8")
            scratch.chmod(mode)
            scratch.replace(target)
        except OSError as exc:
            raise BundleError(f"could not write {target}: {exc}") from exc
        result.written.append(path)

    for path in sorted(set(known) - set(incoming)):
        target = root / path
        if not target.is_file():
            continue
        try:
            if digest(target.read_text(encoding="utf-8")) != known[path]:
                # Edited here since we wrote it, and deleted upstream. Two
                # people disagreeing is not something to settle by deleting.
                continue
            target.unlink()
        except (OSError, UnicodeDecodeError):
            continue
        result.removed.append(path)
        _prune_empty(target.parent, root)
    return result


def _prune_empty(directory: Path, root: Path) -> None:
    """Tidy up directories a removal emptied, never past the bundle root."""
    while directory != root and root in directory.parents:
        try:
            next(directory.iterdir())
            return
        except StopIteration:
            pass
        except OSError:
            return
        try:
            directory.rmdir()
        except OSError:
            return
        directory = directory.parent
