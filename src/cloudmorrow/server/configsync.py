"""One machine's dotfiles, made everybody's.

A *bundle* is a named set of files under one root — `omarchy` is `~/.config`
and, for now, the `hypr` directory inside it. The server holds exactly one
copy of it per user, at a revision that goes up by one every time a machine
pushes.

Nothing here merges. The first machine to tick the box claims the bundle and
its copy becomes revision 1; every other machine adopts that instead of
arguing with it. After that a push has to name the revision it was working
from, so two machines editing at once cannot silently overwrite each other —
the second one is told it is stale and pulls first.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from cloudmorrow.bundles import digest, validate_path
from cloudmorrow.server.db import connect

# What a machine may be asked to sync. The agent has the matching definition of
# which paths each one covers; the server only ever sees relative paths.
KNOWN_BUNDLES = ("omarchy",)

# A bundle is config, not a file server: enough for dotfiles and no more.
MAX_FILE_BYTES = 512 * 1024
MAX_FILES = 400


class UnknownBundleError(LookupError):
    """Not a bundle this server syncs."""


class BundleTooBigError(ValueError):
    pass


class StaleRevisionError(RuntimeError):
    """The bundle moved on while this machine was working from an older copy."""

    def __init__(self, current: int, base: int | None) -> None:
        super().__init__(
            f"bundle is at revision {current}, not {base if base is not None else 'unclaimed'}"
        )
        self.current = current
        self.base = base


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


def validate_bundle(name: str) -> str:
    name = name.strip().lower()
    if name not in KNOWN_BUNDLES:
        raise UnknownBundleError(name)
    return name


@dataclass(slots=True)
class ConfigFile:
    path: str
    content: str
    sha256: str = ""
    mode: int = 0o644

    def __post_init__(self) -> None:
        self.path = validate_path(self.path)
        if not self.sha256:
            self.sha256 = digest(self.content)
        # Ownership and the setuid bits are the machine's business, not the
        # bundle's: only the permission bits travel.
        self.mode = int(self.mode) & 0o777

    def meta(self) -> dict:
        return {"path": self.path, "sha256": self.sha256, "mode": self.mode}

    def to_dict(self) -> dict:
        return {**self.meta(), "content": self.content}


@dataclass(slots=True)
class BundleState:
    """What a machine needs to decide whether it is behind, ahead or level."""

    bundle: str
    revision: int = 0
    origin: str = ""
    claimed_by: str = ""
    claimed_at: str = ""
    updated_at: str = ""
    files: list[dict] = field(default_factory=list)

    @property
    def claimed(self) -> bool:
        return self.revision > 0

    def to_dict(self) -> dict:
        return {
            "bundle": self.bundle,
            "revision": self.revision,
            "origin": self.origin,
            "claimed_by": self.claimed_by,
            "claimed_at": self.claimed_at,
            "updated_at": self.updated_at,
            "files": self.files,
        }


class ConfigStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        connect(self.db_path).close()

    # -- reading -----------------------------------------------------------
    def state(self, owner: str, bundle: str) -> BundleState:
        """The bundle's manifest: every file's name and hash, no contents."""
        bundle = validate_bundle(bundle)
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM config_bundles WHERE owner = ? AND bundle = ?", (owner, bundle)
            ).fetchone()
            files = conn.execute(
                "SELECT path, sha256, mode FROM config_files"
                " WHERE owner = ? AND bundle = ? ORDER BY path",
                (owner, bundle),
            ).fetchall()
        if row is None:
            return BundleState(bundle=bundle)
        return BundleState(
            bundle=bundle,
            revision=row["revision"],
            origin=row["origin"],
            claimed_by=row["claimed_by"],
            claimed_at=row["claimed_at"],
            updated_at=row["updated_at"],
            files=[dict(f) for f in files],
        )

    def states(self, owner: str) -> list[BundleState]:
        return [self.state(owner, bundle) for bundle in KNOWN_BUNDLES]

    def files(self, owner: str, bundle: str) -> list[ConfigFile]:
        bundle = validate_bundle(bundle)
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT path, content, sha256, mode FROM config_files"
                " WHERE owner = ? AND bundle = ? ORDER BY path",
                (owner, bundle),
            ).fetchall()
        return [
            ConfigFile(
                path=row["path"],
                content=conn.unseal("config_files", "content", (owner, bundle), row["content"]),
                sha256=row["sha256"],
                mode=row["mode"],
            )
            for row in rows
        ]

    # -- writing -----------------------------------------------------------
    def push(
        self,
        owner: str,
        bundle: str,
        *,
        machine: str,
        files: list[ConfigFile],
        base_revision: int | None,
    ) -> BundleState:
        """Replace the bundle with *files*, if the pusher is up to date.

        *base_revision* is the revision the machine last had in its hands.
        None means "I believe nobody has claimed this yet", which is only true
        once — the first machine to say it wins, and the rest get told the
        current revision and go and fetch it.
        """
        bundle = validate_bundle(bundle)
        if len(files) > MAX_FILES:
            raise BundleTooBigError(f"a bundle holds at most {MAX_FILES} files, not {len(files)}")
        oversized = [f.path for f in files if len(f.content.encode("utf-8")) > MAX_FILE_BYTES]
        if oversized:
            raise BundleTooBigError(
                f"too big for a config bundle ({MAX_FILE_BYTES // 1024} KiB max): "
                + ", ".join(sorted(oversized)[:3])
            )

        stamp = _now()
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM config_bundles WHERE owner = ? AND bundle = ?", (owner, bundle)
            ).fetchone()
            current = row["revision"] if row else 0
            # None is how a machine says "I think nobody has claimed this",
            # which is the same claim as "it is at revision 0".
            if (base_revision if base_revision is not None else 0) != current:
                raise StaleRevisionError(current, base_revision)

            revision = current + 1
            if row is None:
                conn.execute(
                    "INSERT INTO config_bundles (owner, bundle, revision, origin, claimed_by,"
                    " claimed_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (owner, bundle, revision, machine, machine, stamp, stamp),
                )
            else:
                conn.execute(
                    "UPDATE config_bundles SET revision = ?, origin = ?, updated_at = ?"
                    " WHERE owner = ? AND bundle = ?",
                    (revision, machine, stamp, owner, bundle),
                )
            # The push is the whole bundle, so what it does not mention is gone.
            conn.execute(
                "DELETE FROM config_files WHERE owner = ? AND bundle = ?", (owner, bundle)
            )
            conn.executemany(
                "INSERT INTO config_files (owner, bundle, path, sha256, content, mode,"
                " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        owner,
                        bundle,
                        f.path,
                        f.sha256,
                        conn.seal("config_files", "content", (owner, bundle), f.content),
                        f.mode,
                        stamp,
                    )
                    for f in files
                ],
            )
        return self.state(owner, bundle)

    def forget(self, owner: str, bundle: str) -> None:
        """Throw the bundle away, so the next machine to tick the box claims it."""
        bundle = validate_bundle(bundle)
        with connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM config_files WHERE owner = ? AND bundle = ?", (owner, bundle)
            )
            conn.execute(
                "DELETE FROM config_bundles WHERE owner = ? AND bundle = ?", (owner, bundle)
            )
