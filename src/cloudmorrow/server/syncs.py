"""Local backups: folders on a person's machines, copied into their My Files
by that machine's agent and kept up to date.

One row per folder: which agent, the folder on that machine, where under
the drive it goes (`Backups/<machine>/<folder>` unless said), how often,
and what the last pass found. The agent asks for its rows each tick
(`for_agent`), runs the ones that are due, and says how it went
(`finished`). The files themselves arrive through routes/syncs.py's
agent-facing calls, straight into the drive — the record API is a
person's, and a machine has only its own token.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cloudmorrow.server import fileops
from cloudmorrow.server.database import Database, Row
from cloudmorrow.server.database import open as open_database
from cloudmorrow.server.shares import Share

DEFAULT_EVERY_MINUTES = 60
BACKUPS_FOLDER = "Backups"


class SyncError(ValueError):
    """What cannot be set up or done, in words to show."""


class UnknownSyncError(LookupError):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def _stamp() -> str:
    return _now().isoformat(timespec="seconds")


@dataclass(slots=True)
class Sync:
    id: int
    owner: str
    agent_id: int
    path: str
    into: str
    every_minutes: int
    run_now: bool
    last_run: str | None
    last_ok: bool | None
    last_said: str
    files: int
    bytes: int
    created_at: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "path": self.path,
            "into": self.into,
            "every_minutes": self.every_minutes,
            "run_now": self.run_now,
            "last_run": self.last_run,
            "last_ok": self.last_ok,
            "last_said": self.last_said,
            "files": self.files,
            "bytes": self.bytes,
            "created_at": self.created_at,
        }

    def due(self, now: dt.datetime | None = None) -> bool:
        """Whether a pass is wanted: asked for, never run, or run long enough ago."""
        if self.run_now or not self.last_run:
            return True
        last = dt.datetime.fromisoformat(self.last_run)
        return (now or _now()) - last >= dt.timedelta(minutes=self.every_minutes)


def _sync(row: Row) -> Sync:
    return Sync(
        id=row["id"],
        owner=row["owner"],
        agent_id=row["agent_id"],
        path=row["path"],
        into=row["into_folder"],
        every_minutes=row["every_minutes"],
        run_now=bool(row["run_now"]),
        last_run=row["last_run"],
        last_ok=None if row["last_ok"] is None else bool(row["last_ok"]),
        last_said=row["last_said"] or "",
        files=row["files"] or 0,
        bytes=row["bytes"] or 0,
        created_at=row["created_at"],
    )


def into_folder(raw: str) -> str:
    """A folder under the drive, as typed, checked: no hidden parts, no Trash."""
    folder = str(raw or "").strip().strip("/")
    parts = [p for p in folder.split("/") if p]
    if any(p.startswith(".") or p in (".", "..") for p in parts):
        raise SyncError("not a usable folder")
    if parts and parts[0] == fileops.TRASH:
        raise SyncError("a backup does not go into the Trash")
    return "/".join(parts)


def default_into(machine: str, path: str) -> str:
    """Where a folder lands unless said: Backups/<machine>/<the folder's name>."""
    # The last part of the path as the machine wrote it, whichever way its slashes go.
    name = re.split(r"[\\/]", path.rstrip("/\\"))[-1] or "root"
    return f"{BACKUPS_FOLDER}/{machine}/{name}"


class SyncStore:
    def __init__(self, db: Database | Path) -> None:
        self.db = open_database(db)
        self.db.connect().close()

    def list(self, owner: str) -> list[Sync]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM local_syncs WHERE owner = ? ORDER BY id", (owner,)).fetchall()
        return [_sync(row) for row in rows]

    def get(self, owner: str, sync_id: int) -> Sync:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM local_syncs WHERE owner = ? AND id = ?", (owner, sync_id)).fetchone()
        if row is None:
            raise UnknownSyncError(str(sync_id))
        return _sync(row)

    def create(
        self, owner: str, agent_id: int, path: str, into: str, every_minutes: int = DEFAULT_EVERY_MINUTES
    ) -> Sync:
        path = str(path or "").strip()
        if not path:
            raise SyncError("which folder on that machine?")
        into = into_folder(into)
        if not into:
            raise SyncError("where in My Files?")
        every = max(1, int(every_minutes or DEFAULT_EVERY_MINUTES))
        with self.db.connect() as conn:
            taken = conn.execute(
                "SELECT id FROM local_syncs WHERE owner = ? AND agent_id = ? AND path = ?", (owner, agent_id, path)
            ).fetchone()
            if taken:
                raise SyncError("that folder is backed up from that machine already")
            sync_id = conn.insert(
                "INSERT INTO local_syncs (owner, agent_id, path, into_folder, every_minutes, run_now, created_at)"
                " VALUES (?, ?, ?, ?, ?, 1, ?)",
                (owner, agent_id, path, into, every, _stamp()),
            )
        return self.get(owner, sync_id)

    def delete(self, owner: str, sync_id: int) -> None:
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM local_syncs WHERE owner = ? AND id = ?", (owner, sync_id))
        if cursor.rowcount == 0:
            raise UnknownSyncError(str(sync_id))

    def ask(self, owner: str, sync_id: int) -> Sync:
        """Have the agent run it on its next tick."""
        self.get(owner, sync_id)
        with self.db.connect() as conn:
            conn.execute("UPDATE local_syncs SET run_now = 1 WHERE owner = ? AND id = ?", (owner, sync_id))
        return self.get(owner, sync_id)

    # -- the agent's side -----------------------------------------------------------
    def for_agent(self, agent_id: int) -> list[Sync]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM local_syncs WHERE agent_id = ? ORDER BY id", (agent_id,)).fetchall()
        return [_sync(row) for row in rows]

    def of_agent(self, agent_id: int, sync_id: int) -> Sync:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM local_syncs WHERE agent_id = ? AND id = ?", (agent_id, sync_id)
            ).fetchone()
        if row is None:
            raise UnknownSyncError(str(sync_id))
        return _sync(row)

    def finished(self, agent_id: int, sync_id: int, *, ok: bool, said: str = "", files: int = 0, size: int = 0) -> Sync:
        self.of_agent(agent_id, sync_id)
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE local_syncs SET run_now = 0, last_run = ?, last_ok = ?, last_said = ?, files = ?, bytes = ?"
                " WHERE agent_id = ? AND id = ?",
                (_stamp(), 1 if ok else 0, said[:500], files, size, agent_id, sync_id),
            )
        return self.of_agent(agent_id, sync_id)


# -- the files, in the drive -------------------------------------------------------
def _target(drive: Share, sync: Sync, rel: str) -> tuple[str, Path]:
    rel = str(rel or "").strip().strip("/")
    if not rel or any(part in (".", "..") or part.startswith(".") for part in rel.split("/")):
        raise SyncError("not a usable path")
    path = f"{sync.into}/{rel}"
    try:
        return path, fileops.inside(drive, path)
    except fileops.FileOpError as exc:
        raise SyncError(str(exc)) from None


def listing(drive: Share, sync: Sync) -> dict[str, dict]:
    """Every file under the sync's folder in the drive: {path: {size, modified}}, the path relative to it."""
    try:
        top = fileops.inside(drive, sync.into)
    except fileops.FileOpError as exc:
        raise SyncError(str(exc)) from None
    if not top.is_dir():
        return {}
    found: dict[str, dict] = {}
    for root, dirs, files in os.walk(top):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if name.startswith("."):
                continue
            target = Path(root) / name
            if target.is_symlink():
                continue
            stat = target.stat()
            found[str(target.relative_to(top)).replace(os.sep, "/")] = {"size": stat.st_size, "modified": stat.st_mtime}
    return found


def put(drive: Share, sync: Sync, rel: str, source: Path, modified: float | None = None) -> dict:
    """The file at *source*, as *rel* under the sync's folder, written over whatever was there."""
    path, target = _target(drive, sync, rel)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(dir=target.parent, prefix=".sync-", delete=False)
        part = Path(handle.name)
        try:
            with handle, open(source, "rb") as src:
                while chunk := src.read(1024 * 1024):
                    handle.write(chunk)
            os.chmod(part, fileops.FILE_MODE)
            if modified is not None:
                os.utime(part, (modified, modified))
            os.replace(part, target)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
    except OSError as exc:
        raise SyncError(f"the server cannot write {path}: {exc.strerror or exc}") from None
    stat = target.stat()
    return {"path": path, "size": stat.st_size, "modified": stat.st_mtime}


def remove(drive: Share, sync: Sync, rel: str) -> bool:
    """A file gone from the machine goes to the drive's Trash. False when it was not there."""
    path, target = _target(drive, sync, rel)
    if not target.exists() or target.is_symlink():
        return False
    try:
        fileops.trash(drive, path, target)
    except fileops.FileOpError as exc:
        raise SyncError(str(exc)) from None
    return True
