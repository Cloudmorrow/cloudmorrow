"""Backups: everything this server holds, into an S3 bucket, every day — and back.

A home server is one disk, and one disk is one bad day away from nothing.
So an administrator names a bucket — Amazon's, Hetzner's, Backblaze's, a
MinIO of their own — under Administration, Backups, says what goes and
when, and from then on the clock puts a copy of it all there every day,
and throws away the ones older than it was told to keep. **Restore** reads
one back: all of it, or the parts chosen — the database, this drive, that
share, this one file as it was on that day — over what is on the server now.

What a backup is: a snapshot folder in the bucket, named by the moment it
was taken, beside one content store shared by every snapshot:

    <folder>/objects/ab/abcdef…          one object per distinct content, by its SHA-256
    <folder>/20261027T030000Z/manifest.json
    <folder>/20261027T030000Z/drives/<name>.index.gz    path → digest, size, mtime, mode
    <folder>/20261027T030000Z/shares/<name>.index.gz
    <folder>/20261027T030000Z/database.index.gz         the SQLite copy, in 4 MiB pieces
    <folder>/20261027T030000Z/database.pgdump           or pg_dump's, whole
    <folder>/20261027T030000Z/quills.tar.gz
    <folder>/20261027T030000Z/keys.tar.gz

Every file goes into the store once, under its digest, and each day's
index says which files there were and which digest each had. A file whose
size and mtime are what the last index saw is not read again; one that
changed is hashed, and uploaded only if the store does not have that
content yet. So a renamed or copied file costs nothing, the first backup
is the full one and every later one carries the day's changes — while
every snapshot is a complete picture of its day, and a file edited on
Monday and again on Thursday is there both ways, each from its day's
index. Once a month every file is read in full again, in case a change
kept its mtime. When a snapshot is older than the days kept, it goes, and
with it every object no remaining snapshot names: the indexes say exactly
which, so the store is never listed.

The database is cut into 4 MiB pieces of the copy and stored the same way:
SQLite rewrites only the pages that changed, in place, so the pieces that
hold untouched pages have the digest they had yesterday and are not sent
again. A PostgreSQL dump is a compressed stream with no such stability and
goes up whole each day; it is small.

The parts:

- **database** — the accounts, circles, roles, every record of every Quill,
  the settings, the secrets, which Quills are installed: a copy of the
  SQLite file at one moment, or a `pg_dump`. Sealed rows stay sealed:
  without the key the dump opens nothing, which is the point of keeping
  the key apart from the data.
- **drives** — everybody's own files, notes included, an index per drive,
  so one person's can be put back alone, or one file of theirs.
- **shares** — every share, an index each, wherever its folder is.
- **quills** — the installed Quills, people's own, the datamodels and the
  runtimes fetched for them: the folders in the data directory, as one
  archive, since they are small and change rarely.
- **keys** — the token signing key, the identity key and the push key. The
  sealing key only when asked for, since a bucket holding it and the
  database holds everything in the clear; off, it is yours to keep apart.

The manifest carries a fingerprint of the key the database was sealed
with, so a restore onto a server with another key is refused before it
does harm — unless the backup brings the key and is asked to put it back.

Restoring the database puts the copy back under the running server (the
SQLite backup API into the live file; `pg_restore --clean` into the
database) after keeping a copy of what was there in
`<data_dir>/before-restore/`, and then the server restarts itself the way
an update does, so nothing in memory remembers the old rows. Files are
written over what is there, each checked against its digest as it comes
down: what the backup has wins, what it does not have is left alone, and
a file already there with the same size and mtime is left as it is.

Backups made before the store (format 1: an archive per drive) are still
listed and restored, whole drives only, until they age out.

A backup or a restore runs on a thread of its own and is watched through
`status()`; the clock asks `tick()` every half minute whether today's is
due. Nothing here needs an SDK: `s3.py` speaks to the bucket.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import tarfile
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from cloudmorrow import __version__
from cloudmorrow.server import schema
from cloudmorrow.server.s3 import PART_SIZE, Bucket, S3Error, Uploader, read_chunks

if TYPE_CHECKING:
    from cloudmorrow.server.state import AppState

__all__ = ["BackupError", "Backups", "Choice", "FORMAT", "PARTS", "Settings", "Store"]

log = logging.getLogger("cloudmorrow.backups")

# 1: an archive per drive. 2: the content store and an index per drive.
FORMAT = 2
FORMATS = (1, 2)
PARTS: tuple[str, ...] = ("database", "drives", "shares", "quills", "keys")
PART_NAMES = {
    "database": "the database",
    "drives": "everybody's files",
    "shares": "the shares",
    "quills": "the Quills",
    "keys": "the keys",
}
# The folders in the data directory the quills part carries.
QUILL_FOLDERS = ("quills", "quills-personal", "datamodels", "runtimes")
# The keys part: what in the data directory, by file name.
KEY_FILES = ("secret.key", "identity.key", "vapid.key")
SEALING_KEY = "sealing.key"
# A backup's folder in the bucket is named by its moment, UTC.
STAMP = "%Y%m%dT%H%M%SZ"
STAMP_RE = re.compile(r"^\d{8}T\d{6}Z$")
# The content store, beside the snapshot folders.
OBJECTS = "objects/"
# The database copy goes up in pieces this big; SQLite's pages are 4 KiB,
# so a piece holds a thousand of them, and a day's writes touch few pieces.
CHUNK_SIZE = 4 * 1024 * 1024
# A file up to this size is read once, into memory, hashed and sent;
# larger ones are read twice: hashed, then streamed up in parts.
IN_MEMORY = PART_SIZE
# Every file is read in full again this often, whatever its mtime says.
REHASH_DAYS = 30
# A folder with no manifest this old was a backup that never finished.
UNFINISHED_AFTER = dt.timedelta(days=1)
# How many copies of the database from before a restore stay on disk.
KEEP_BEFORE = 3
KEEP_DAYS_MOST = 3650
# Indexes read from the bucket, kept in memory for browsing: a snapshot's
# index never changes, so a key names its contents for good.
INDEX_CACHE = 16
# Restores write beside the target under this name, then move into place.
TEMP_PREFIX = ".cloudmorrow-restore-"

# The settings rows. The secret is sealed in its own row.
CONFIG = "backup.config"
SECRET = "backup.secret"
LAST = "backup.last"
LAST_RESTORE = "backup.last_restore"
LAST_DAY = "backup.last_day"
LAST_REHASH = "backup.last_rehash"
STORE = "backup.store"


class BackupError(RuntimeError):
    """Something about the destination, the choice, or the run does not hold."""


class _Unstable(RuntimeError):
    """A file changed every time it was read: it is skipped this round."""


@dataclass(slots=True)
class Settings:
    """Where backups go and when, as the administrator set them."""

    endpoint: str = ""
    bucket: str = ""
    region: str = ""
    # A folder in the bucket; empty for its top.
    prefix: str = ""
    access_key: str = ""
    # Every day at this local time, HH:MM, when enabled.
    time: str = "03:00"
    keep_days: int = 30
    parts: list[str] = field(default_factory=lambda: list(PARTS))
    # Whether the keys part carries the sealing key too.
    seal_key: bool = False
    enabled: bool = False

    def configured(self) -> bool:
        return bool(self.endpoint and self.bucket and self.access_key)

    def root(self) -> str:
        folder = self.prefix.strip().strip("/")
        return folder + "/" if folder else ""


@dataclass(slots=True)
class Choice:
    """What a restore puts back."""

    database: bool = False
    drives: list[str] = field(default_factory=list)
    shares: list[str] = field(default_factory=list)
    # Single files or folders: `drives/<name>/<path>`, `shares/<name>/<path>`;
    # a path ending in a slash is a folder with everything under it.
    paths: list[str] = field(default_factory=list)
    quills: bool = False
    keys: bool = False
    # Restart afterwards, when what was restored asks for it.
    restart: bool = True
    # Restore the database although it was sealed with another key.
    force: bool = False

    def anything(self) -> bool:
        return bool(self.database or self.drives or self.shares or self.paths or self.quills or self.keys)


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def _iso(moment: dt.datetime) -> str:
    return moment.isoformat(timespec="seconds")


def key_fingerprint(master: bytes) -> str:
    """What names a sealing key without giving it away."""
    return hashlib.sha256(b"cloudmorrow-sealing-key:" + master).hexdigest()[:16]


def validate_time(text: str) -> str:
    found = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", text or "")
    if not found or int(found.group(1)) > 23 or int(found.group(2)) > 59:
        raise BackupError("the time is HH:MM, on a 24-hour clock: 03:00")
    return f"{int(found.group(1)):02d}:{found.group(2)}"


def _safe_name(name: str) -> str:
    """A drive's or share's name as it goes in an object key and comes back as a folder."""
    cleaned = str(name).replace("/", "_").replace("\\", "_").strip()
    if not cleaned or cleaned in (".", "..") or "\x00" in cleaned:
        raise BackupError(f"not a name a backup can carry: {name!r}")
    return cleaned


def _safe_rel(rel: str) -> bool:
    """A path from an index, fit to be joined under a folder: relative, no climbing."""
    if not rel or "\x00" in rel or rel.startswith("/"):
        return False
    return all(part not in ("", ".", "..") for part in rel.split("/"))


def _in(rel: str, chosen: Iterable[str] | None) -> bool:
    """Whether *rel* is one of the chosen paths, or under a chosen folder. None chooses all."""
    if chosen is None:
        return True
    for path in chosen:
        folder = path.rstrip("/")
        if rel == folder or rel.startswith(folder + "/"):
            return True
    return False


def split_path(path: str) -> tuple[str, str, str]:
    """`drives/bram/Notes/a.md` → ("drives", "bram", "Notes/a.md"). Raises on anything else."""
    parts = str(path).strip().lstrip("/").split("/", 2)
    if len(parts) < 2 or parts[0] not in ("drives", "shares") or not parts[1]:
        raise BackupError(f"a path is drives/<name>/<path> or shares/<name>/<path>, not {path!r}")
    rel = parts[2] if len(parts) == 3 else ""
    if rel.strip("/") and not _safe_rel(rel.rstrip("/")):
        raise BackupError(f"not a path a backup can hold: {path!r}")
    return parts[0], parts[1], rel


def _tar_filter(counter: dict[str, int]) -> Callable[[tarfile.TarInfo], tarfile.TarInfo | None]:
    def keep(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        # Pipes and devices are not files worth carrying; everything else is.
        if info.isfifo() or info.ischr() or info.isblk():
            return None
        if info.isfile():
            counter["files"] += 1
        return info

    return keep


def _gz_json(data: dict) -> bytes:
    return gzip.compress(json.dumps(data, separators=(",", ":"), sort_keys=True).encode(), compresslevel=6, mtime=0)


def _ungz_json(data: bytes) -> dict:
    try:
        found = json.loads(gzip.decompress(data))
    except (OSError, ValueError) as exc:
        raise BackupError(f"an index in the bucket could not be read: {exc}") from exc
    if not isinstance(found, dict):
        raise BackupError("an index in the bucket is not what it should be")
    return found


class Store:
    """The content store of one bucket folder: an object per distinct content, by its SHA-256.

    `known` is what the store already holds, as the latest indexes say;
    nothing in it is sent again. What this run adds is kept in `uploaded`,
    so a run that fails can take its own objects away.
    """

    def __init__(self, bucket: Bucket, root: str, known: set[str] | None = None) -> None:
        self.bucket = bucket
        self.root = root
        self.known: set[str] = set(known or ())
        self.uploaded: list[str] = []
        self.added_bytes = 0

    def key(self, digest: str) -> str:
        return f"{self.root}{OBJECTS}{digest[:2]}/{digest}"

    def has(self, digest: str) -> bool:
        return digest in self.known

    def _added(self, digest: str, stored: int) -> None:
        self.known.add(digest)
        self.uploaded.append(digest)
        self.added_bytes += stored

    def put_bytes(self, digest: str, data: bytes) -> int:
        """Store *data* under *digest* (which the caller computed, over the
        content the digest is of). Answers the bytes sent: none when known."""
        if self.has(digest):
            return 0
        self.bucket.put(self.key(digest), data)
        self._added(digest, len(data))
        return len(data)

    def add_file(self, path: Path) -> tuple[str, int]:
        """The file's content into the store, unless it is there. Answers its digest and size."""
        size = path.stat().st_size
        if size <= IN_MEMORY:
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            self.put_bytes(digest, data)
            return digest, len(data)
        # Too big to hold: hashed in one pass, streamed up in the next, and
        # the two must agree, or the object would carry the wrong content.
        for _attempt in range(3):
            digest, read = _hash_file(path)
            if self.has(digest):
                return digest, read
            up = Uploader(self.bucket, self.key(digest), part_size=PART_SIZE)
            try:
                with path.open("rb") as source:
                    shutil.copyfileobj(source, up, 1024 * 1024)
                up.finish()
            except BaseException:
                up.abandon()
                raise
            if up.sha256 == digest:
                self._added(digest, up.size)
                return digest, up.size
            try:
                self.bucket.delete(self.key(digest))
            except S3Error:
                pass
        raise _Unstable(f"{path.name} changed every time it was read")

    def open(self, digest: str):
        try:
            return self.bucket.open(self.key(digest))
        except S3Error as exc:
            raise BackupError(f"the object {digest[:12]}… {exc}") from exc

    def delete(self, digest: str) -> None:
        self.bucket.delete(self.key(digest))


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    read = 0
    with path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            read += len(chunk)
    return digest.hexdigest(), read


class Backups:
    """The server's backups: their settings, the runs, and what is in the bucket."""

    def __init__(self, state: AppState, *, now: Callable[[], dt.datetime] = _now) -> None:
        self.state = state
        self.now = now
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        # What is going on, for the admin page to watch.
        self._running: str | None = None
        self._started_at = ""
        self._by = ""
        self._step = ""
        self._lines: list[str] = []
        # The last backup's stamp: the next is later, whatever the clock says.
        self._last_stamp = ""
        self._indexes: OrderedDict[str, dict] = OrderedDict()

    # -- settings ------------------------------------------------------------------
    def settings(self) -> Settings:
        raw = self.state.settings.get(CONFIG)
        found = Settings()
        if raw:
            try:
                data = json.loads(raw)
            except ValueError:
                data = {}
            for key in ("endpoint", "bucket", "region", "prefix", "access_key", "time"):
                if isinstance(data.get(key), str):
                    setattr(found, key, data[key])
            if isinstance(data.get("keep_days"), int):
                found.keep_days = data["keep_days"]
            if isinstance(data.get("parts"), list):
                found.parts = [p for p in PARTS if p in data["parts"]]
            found.seal_key = bool(data.get("seal_key", False))
            found.enabled = bool(data.get("enabled", False))
        return found

    def has_secret(self) -> bool:
        return bool(self.state.settings.get(SECRET))

    def _secret(self) -> str:
        blob = self.state.settings.get(SECRET)
        if not blob:
            return ""
        return self.state.sealer.unseal("settings", "value", (SECRET,), blob) or ""

    def save_settings(self, changes: dict, *, changed_by: str = "") -> Settings:
        """Change what is given; a field left out is left alone. The secret key
        is stored sealed, and only when one is given: blank keeps the old."""
        current = self.settings()
        for key in ("endpoint", "bucket", "region", "prefix", "access_key"):
            if changes.get(key) is not None:
                setattr(current, key, str(changes[key]).strip())
        if changes.get("time") is not None:
            current.time = validate_time(str(changes["time"]))
        if changes.get("keep_days") is not None:
            days = int(changes["keep_days"])
            if not 1 <= days <= KEEP_DAYS_MOST:
                raise BackupError(f"keep between 1 and {KEEP_DAYS_MOST} days")
            current.keep_days = days
        if changes.get("parts") is not None:
            wanted = [str(p) for p in changes["parts"]]
            unknown = sorted(set(wanted) - set(PARTS))
            if unknown:
                raise BackupError(f"no such part: {', '.join(unknown)}; the parts are {', '.join(PARTS)}")
            current.parts = [p for p in PARTS if p in wanted]
        if changes.get("seal_key") is not None:
            current.seal_key = bool(changes["seal_key"])
        if changes.get("enabled") is not None:
            current.enabled = bool(changes["enabled"])
        if current.enabled and not current.configured():
            raise BackupError("say where backups go — the endpoint, the bucket and the keys — before switching them on")
        if current.enabled and not current.parts:
            raise BackupError("choose at least one part to back up")
        if current.endpoint or current.bucket:
            # Said now rather than at three in the morning.
            try:
                Bucket(
                    current.endpoint or "https://unset.invalid",
                    current.bucket or "unset",
                    "k",
                    "s",
                    region=current.region,
                )
            except S3Error as exc:
                raise BackupError(str(exc)) from exc
        if changes.get("secret_key"):
            sealed = self.state.sealer.seal("settings", "value", (SECRET,), str(changes["secret_key"]))
            self.state.settings.set(SECRET, sealed or "", changed_by=changed_by)
        data = asdict(current)
        self.state.settings.set(CONFIG, json.dumps(data, sort_keys=True), changed_by=changed_by)
        return current

    def bucket(self, settings: Settings | None = None) -> Bucket:
        settings = settings or self.settings()
        if not settings.configured() or not self.has_secret():
            raise BackupError("backups are not set up: say where they go under Administration, Backups")
        try:
            return Bucket(
                settings.endpoint, settings.bucket, settings.access_key, self._secret(), region=settings.region
            )
        except S3Error as exc:
            raise BackupError(str(exc)) from exc

    def test(self) -> dict:
        """Reach the bucket: list it, write a probe, take the probe away."""
        settings = self.settings()
        bucket = self.bucket(settings)
        probe = settings.root() + ".cloudmorrow-probe"
        try:
            listed = bucket.list(settings.root(), delimiter="/", limit=1000)
            bucket.put(probe, b"cloudmorrow can write here\n", "text/plain")
            bucket.delete(probe)
        except S3Error as exc:
            raise BackupError(str(exc)) from exc
        stamps = [p for p in listed.prefixes if STAMP_RE.match(p[len(settings.root()) :].strip("/"))]
        return {"ok": True, "backups": len(stamps), "where": repr(bucket)}

    # -- what is going on ------------------------------------------------------------
    def _read_json(self, key: str) -> dict | None:
        raw = self.state.settings.get(key)
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def status(self) -> dict:
        with self._lock:
            return {
                "running": self._running,
                "started_at": self._started_at,
                "by": self._by,
                "step": self._step,
                "lines": list(self._lines),
                "last": self._read_json(LAST),
                "last_restore": self._read_json(LAST_RESTORE),
                "store": self._read_json(STORE),
            }

    def _say(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)
        log.info("%s", line)

    def _at(self, step: str) -> None:
        with self._lock:
            self._step = step

    def _begin(self, what: str, by: str) -> None:
        with self._lock:
            if self._running:
                raise BackupError(f"a {self._running} is running already; wait for it")
            self._running = what
            self._started_at = _iso(self.now())
            self._by = by
            self._step = ""
            self._lines = []

    def _end(self) -> None:
        with self._lock:
            self._running = None
            self._step = ""

    def _run_on_thread(self, what: str, by: str, work: Callable[[], None]) -> dict:
        self._begin(what, by)

        def run() -> None:
            try:
                work()
            except Exception:
                log.exception("%s failed", what)
            finally:
                self._end()

        self._thread = threading.Thread(target=run, name=f"backup-{what}", daemon=True)
        self._thread.start()
        return self.status()

    def wait(self, timeout: float = 600.0) -> None:
        """Until the running backup or restore is done. For tests and the command line."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    # -- the clock -----------------------------------------------------------------
    def tick(self, now: dt.datetime | None = None) -> bool:
        """Start today's backup if its time has come and it has not run. True when started."""
        settings = self.settings()
        if not settings.enabled or not settings.configured() or not self.has_secret():
            return False
        moment = (now or self.now()).astimezone()
        today = moment.date().isoformat()
        if self.state.settings.get(LAST_DAY) == today:
            return False
        hour, minute = (int(x) for x in settings.time.split(":"))
        if (moment.hour, moment.minute) < (hour, minute):
            return False
        with self._lock:
            if self._running:
                return False
        # Once a day, whatever comes of it: a failure is on the page, and
        # Back up now is the retry.
        self.state.settings.set(LAST_DAY, today, changed_by="clock")
        try:
            self.start_backup(by="the clock")
        except BackupError as exc:
            log.warning("today's backup did not start: %s", exc)
            return False
        return True

    # -- backing up ------------------------------------------------------------------
    def start_backup(self, parts: Iterable[str] | None = None, *, by: str = "") -> dict:
        settings = self.settings()
        chosen = [p for p in PARTS if p in set(parts)] if parts is not None else list(settings.parts)
        if not chosen:
            raise BackupError("choose at least one part to back up")
        bucket = self.bucket(settings)
        return self._run_on_thread("backup", by, lambda: self.backup(chosen, settings=settings, bucket=bucket, by=by))

    def _rehash_due(self) -> bool:
        """Whether every file is to be read in full this time. Never before the
        first backup has been taken: that one reads everything anyway."""
        last = self.state.settings.get(LAST_REHASH) or ""
        try:
            since = dt.date.fromisoformat(last)
        except ValueError:
            return False
        return (self.now().date() - since).days >= REHASH_DAYS

    def backup(
        self,
        parts: Iterable[str] | None = None,
        *,
        settings: Settings | None = None,
        bucket: Bucket | None = None,
        by: str = "",
        rehash: bool | None = None,
    ) -> dict:
        """One backup, now, on this thread. Answers the manifest; raises on failure.

        Called by `start_backup` on its thread, and directly by tests. When
        called directly it takes the running slot itself. *rehash* reads
        every file in full whatever its mtime says; left None, it is so
        once every REHASH_DAYS.
        """
        settings = settings or self.settings()
        chosen = [p for p in PARTS if p in set(parts)] if parts is not None else list(settings.parts)
        bucket = bucket or self.bucket(settings)
        own = self._running != "backup"
        if own:
            self._begin("backup", by)
        started = self.now()
        # Two in one second — Back up now twice — must not share a folder.
        while started.strftime(STAMP) <= self._last_stamp:
            started += dt.timedelta(seconds=1)
        stamp = self._last_stamp = started.strftime(STAMP)
        root = settings.root()
        folder = root + stamp + "/"
        rehash = self._rehash_due() if rehash is None else rehash
        manifest: dict = {
            "cloudmorrow_backup": FORMAT,
            "stamp": stamp,
            "made_at": _iso(started),
            "cloud": self.state.cloud_name(),
            "version": __version__,
            "schema": schema.VERSION,
            "sealed_with": key_fingerprint(self.state.sealer.master),
            "parts": chosen,
            "database": None,
            "drives": [],
            "shares": [],
            "quills": None,
            "keys": None,
            "size": 0,
            "added": 0,
            "files": 0,
            "rehash": rehash,
            "by": by,
        }
        store = Store(bucket, root)
        try:
            self._at("Reading the last backup's indexes")
            previous = self._previous(bucket, settings, store)
            if rehash:
                self._say("Every file is read in full this time, the monthly check")
            if "database" in chosen:
                self._at("Backing up the database")
                manifest["database"] = self._backup_database(bucket, folder, store)
                told = manifest["database"]
                self._say(f"Database: {_size(told['size'])}" + _added(told))
            if "drives" in chosen:
                for name, path in self._drives():
                    self._at(f"Backing up {name}'s files")
                    safe = _safe_name(name)
                    told = self._backup_folder(
                        store, folder + "drives/" + safe + ".index.gz", path, previous.get("drives/" + safe), rehash
                    )
                    told["name"] = name
                    manifest["drives"].append(told)
                    self._say(f"{name}'s files: {_size(told['size'])}, {_count(told['files'], 'file')}" + _added(told))
            if "shares" in chosen:
                for share in self.state.shares.all():
                    if not Path(share.path).is_dir():
                        self._say(f"Share {share.name}: its folder {share.path} is not there; skipped")
                        continue
                    self._at(f"Backing up the share {share.name}")
                    safe = _safe_name(share.name)
                    told = self._backup_folder(
                        store,
                        folder + "shares/" + safe + ".index.gz",
                        Path(share.path),
                        previous.get("shares/" + safe),
                        rehash,
                    )
                    told["name"] = share.name
                    told["path"] = str(share.path)
                    manifest["shares"].append(told)
                    self._say(
                        f"Share {share.name}: {_size(told['size'])}, {_count(told['files'], 'file')}" + _added(told)
                    )
            if "quills" in chosen:
                self._at("Backing up the Quills")
                manifest["quills"] = self._backup_quills(bucket, folder + "quills.tar.gz")
                self._say(f"Quills: {_size(manifest['quills']['size'])}, {_count(manifest['quills']['files'], 'file')}")
            if "keys" in chosen:
                self._at("Backing up the keys")
                manifest["keys"] = self._backup_keys(bucket, folder + "keys.tar.gz", with_sealing=settings.seal_key)
                self._say("Keys" + (", the sealing key among them" if manifest["keys"]["sealing_key"] else ""))
            parts_made = [
                part
                for part in (
                    manifest["database"],
                    manifest["quills"],
                    manifest["keys"],
                    *manifest["drives"],
                    *manifest["shares"],
                )
                if part
            ]
            manifest["size"] = sum(part["size"] for part in parts_made)
            manifest["files"] = sum(part.get("files", 0) for part in manifest["drives"] + manifest["shares"])
            # What went up: the store's new objects, and the archives and indexes.
            manifest["added"] = (
                store.added_bytes
                + sum(part.get("index_size", 0) for part in parts_made)
                + sum(part["size"] for part in (manifest["quills"], manifest["keys"]) if part)
            )
            finished = self.now()
            manifest["finished_at"] = _iso(finished)
            manifest["took"] = round((finished - started).total_seconds(), 1)
            self._at("Writing the manifest")
            bucket.put(
                folder + "manifest.json", json.dumps(manifest, indent=1, sort_keys=True).encode(), "application/json"
            )
            self._say(
                f"Done: {_size(manifest['size'])}, {_size(manifest['added'])} new, in {manifest['took']} s, as {stamp}"
            )
        except (S3Error, OSError, BackupError, subprocess.SubprocessError) as exc:
            self._say(f"Failed: {exc}")
            self._remember(LAST, stamp, started, ok=False, error=str(exc), by=by, parts=chosen)
            # A folder with no manifest is swept as unfinished; what this run
            # put in the store and nothing names goes now.
            self._take_back(bucket, settings, store)
            raise BackupError(str(exc)) from exc
        finally:
            if own:
                self._end()
        if rehash or not previous:
            self.state.settings.set(LAST_REHASH, self.now().date().isoformat(), changed_by="backup")
        # What the store holds: the count so far plus this run's new objects,
        # exact again whenever the sweep has to read every index anyway.
        totals = self._read_json(STORE) or {"objects": 0, "bytes": 0}
        totals = self._set_totals(
            int(totals.get("objects", 0)) + len(store.uploaded), int(totals.get("bytes", 0)) + store.added_bytes
        )
        try:
            swept = self.sweep(bucket=bucket, settings=settings)
            if swept.get("totals") is not None:
                totals = swept["totals"]
        except (S3Error, BackupError) as exc:
            log.warning("the sweep of old backups failed: %s", exc)
        self._remember(
            LAST,
            stamp,
            started,
            ok=True,
            by=by,
            parts=chosen,
            size=manifest["size"],
            added=manifest["added"],
            files=manifest["files"],
            store=totals,
        )
        return manifest

    def _set_totals(self, objects: int, size: int) -> dict:
        totals = {"objects": objects, "bytes": size, "at": _iso(self.now())}
        self.state.settings.set(STORE, json.dumps(totals), changed_by="backup")
        return totals

    def _remember(self, key: str, stamp: str, started: dt.datetime, *, ok: bool, error: str = "", **more) -> None:
        with self._lock:
            lines = list(self._lines)
        told = {
            "stamp": stamp,
            "started_at": _iso(started),
            "finished_at": _iso(self.now()),
            "ok": ok,
            "error": error,
            "lines": lines,
            **more,
        }
        self.state.settings.set(key, json.dumps(told), changed_by=str(more.get("by") or ""))

    def _tmp(self) -> Path:
        """Where a copy of the database stands while it goes up or comes down:
        in the data directory, which is the one place the service may write
        and the one place with room for it."""
        folder = self.state.config.data_dir / "tmp"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _drives(self) -> list[tuple[str, Path]]:
        """Every drive on the server: each folder in the files directory but
        the Shares folder — the accounts', and those of accounts since
        deleted, whose files stay. With one shared tree, the one drive."""
        config = self.state.config
        shares = config.shares_root().resolve()
        found: list[tuple[str, Path]] = []
        if not config.notes_dir.is_dir():
            return found
        for child in sorted(config.notes_dir.iterdir()):
            if not child.is_dir() or child.resolve() == shares or child.name.startswith("."):
                continue
            found.append((child.name, child))
        return found

    # -- the store: what it holds ----------------------------------------------------
    def _previous(self, bucket: Bucket, settings: Settings, store: Store) -> dict[str, dict]:
        """The latest index of each part, from the newest snapshots that have
        one, and into *store* every digest they name: what need not go again.
        Keyed `drives/<safe name>`, `shares/<safe name>`, `database`."""
        found: dict[str, dict] = {}
        looked = 0
        for stamp in self._stamps(bucket, settings):
            manifest = self._manifest(bucket, settings, stamp)
            if manifest is None or manifest.get("cloudmorrow_backup") != 2:
                continue
            for name, key in self._index_keys(manifest):
                if name in found:
                    continue
                index = self._index(bucket, key)
                found[name] = index
                store.known.update(_digests(index))
            looked += 1
            # The newest answers for most; a part that was off for a few days
            # is still found. Beyond that, a read of its files is cheaper.
            if looked >= 5:
                break
        return found

    @staticmethod
    def _index_keys(manifest: dict) -> list[tuple[str, str]]:
        """The indexes a format-2 manifest names, as (part name, object key)."""
        keys: list[tuple[str, str]] = []
        for kind in ("drives", "shares"):
            for part in manifest.get(kind) or []:
                if part.get("key", "").endswith(".index.gz"):
                    keys.append((f"{kind}/{_safe_name(part['name'])}", part["key"]))
        database = manifest.get("database")
        if database and database.get("chunked"):
            keys.append(("database", database["key"]))
        return keys

    def _index(self, bucket: Bucket, key: str) -> dict:
        """One index, from the bucket or the cache."""
        with self._lock:
            found = self._indexes.get(key)
            if found is not None:
                self._indexes.move_to_end(key)
                return found
        try:
            data = bucket.get(key)
        except S3Error as exc:
            raise BackupError(f"the index {key} {exc}") from exc
        index = _ungz_json(data)
        with self._lock:
            self._indexes[key] = index
            while len(self._indexes) > INDEX_CACHE:
                self._indexes.popitem(last=False)
        return index

    def _references(self, bucket: Bucket, settings: Settings, manifests: Iterable[dict]) -> dict[str, int]:
        """Every digest the given snapshots name, with its stored size."""
        needed: dict[str, int] = {}
        for manifest in manifests:
            for _name, key in self._index_keys(manifest):
                needed.update(_sizes(self._index(bucket, key)))
        return needed

    def _take_back(self, bucket: Bucket, settings: Settings, store: Store) -> None:
        """After a failed run: its new objects, unless some snapshot names them, go."""
        if not store.uploaded:
            return
        try:
            finished = [m for m in (self._manifest(bucket, settings, s) for s in self._stamps(bucket, settings)) if m]
            needed = self._references(bucket, settings, finished)
            for digest in store.uploaded:
                if digest not in needed:
                    store.delete(digest)
        except (S3Error, BackupError) as exc:
            log.warning("could not take a failed backup's objects away: %s", exc)

    # -- the parts, up ---------------------------------------------------------------------
    def _backup_database(self, bucket: Bucket, folder: str, store: Store) -> dict:
        db = self.state.db
        if db.engine.name == "sqlite":
            copy = self._tmp() / f"database-{os.getpid()}-{int(time.time())}.sqlite"
            before = store.added_bytes
            try:
                self._copy_sqlite_out(copy)
                chunks: list[list] = []
                total = 0
                with copy.open("rb") as source:
                    while True:
                        data = source.read(CHUNK_SIZE)
                        if not data:
                            break
                        digest = hashlib.sha256(data).hexdigest()
                        stored = len(data)
                        if not store.has(digest):
                            packed = gzip.compress(data, compresslevel=6, mtime=0)
                            store.put_bytes(digest, packed)
                            stored = len(packed)
                        chunks.append([digest, len(data), stored])
                        total += len(data)
            finally:
                copy.unlink(missing_ok=True)
            index = {"engine": "sqlite", "size": total, "chunk_size": CHUNK_SIZE, "gzip": True, "chunks": chunks}
            key = folder + "database.index.gz"
            packed_index = _gz_json(index)
            bucket.put(key, packed_index)
            return {
                "engine": "sqlite",
                "key": key,
                "chunked": True,
                "size": total,
                "chunks": len(chunks),
                "added": store.added_bytes - before,
                "index_size": len(packed_index),
            }
        # PostgreSQL: pg_dump's custom format, straight into the bucket.
        tool = shutil.which("pg_dump")
        if not tool:
            raise BackupError("pg_dump is not installed on this server: apt install postgresql-client")
        up = Uploader(bucket, folder + "database.pgdump")
        try:
            with subprocess.Popen(
                [tool, "--format=custom", "--no-owner", "--no-privileges", "--dbname", db.url],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ) as proc:
                assert proc.stdout is not None
                shutil.copyfileobj(proc.stdout, up, 1024 * 1024)
                _, err = proc.communicate()
            if proc.returncode != 0:
                raise BackupError(f"pg_dump failed: {err.decode(errors='replace').strip()}")
            up.finish()
        except BaseException:
            up.abandon()
            raise
        return {
            "engine": "postgres",
            "key": folder + "database.pgdump",
            "size": up.size,
            "sha256": up.sha256,
            "added": up.size,
        }

    def _copy_sqlite_out(self, copy: Path) -> None:
        """The live SQLite database at one moment, into *copy*: the backup API
        folds the write-ahead log in as it goes, so the file is whole."""
        engine = self.state.db.engine
        raw = engine.acquire()
        try:
            dest = sqlite3.connect(copy)
            try:
                raw.backup(dest)
            finally:
                dest.close()
        finally:
            engine.release(raw)

    def _backup_folder(self, store: Store, key: str, root: Path, previous: dict | None, rehash: bool) -> dict:
        """One tree into the store, and its index at *key*.

        A file whose size and mtime are what *previous* saw keeps its
        digest unread, unless *rehash*. Links are not followed and not
        carried; pipes and sockets neither.
        """
        before_bytes, before_count = store.added_bytes, len(store.uploaded)
        old = (previous or {}).get("files") or {}
        files: dict[str, list] = {}
        dirs: list[str] = []
        total = unchanged = skipped = 0
        for dirpath, dirnames, filenames in os.walk(root):
            here = Path(dirpath)
            rel_dir = here.relative_to(root).as_posix() if here != root else ""
            dirnames[:] = sorted(d for d in dirnames if not (here / d).is_symlink())
            if rel_dir:
                dirs.append(rel_dir)
            for name in sorted(filenames):
                if name.startswith(TEMP_PREFIX):
                    continue
                full = here / name
                try:
                    st = full.lstat()
                except OSError:
                    skipped += 1
                    continue
                if not stat.S_ISREG(st.st_mode):
                    skipped += 1
                    continue
                rel = f"{rel_dir}/{name}" if rel_dir else name
                was = old.get(rel)
                if (
                    not rehash
                    and isinstance(was, list)
                    and len(was) >= 3
                    and was[1] == st.st_size
                    and was[2] == st.st_mtime_ns
                    and store.has(was[0])
                ):
                    digest, size = was[0], was[1]
                    unchanged += 1
                else:
                    try:
                        digest, size = store.add_file(full)
                    except (OSError, _Unstable) as exc:
                        log.warning("skipped %s: %s", full, exc)
                        self._say(f"Skipped {rel}: {exc}")
                        skipped += 1
                        continue
                files[rel] = [digest, size, st.st_mtime_ns, stat.S_IMODE(st.st_mode)]
                total += size
        index = {"files": files, "dirs": dirs}
        packed = _gz_json(index)
        store.bucket.put(key, packed)
        return {
            "key": key,
            "size": total,
            "files": len(files),
            "unchanged": unchanged,
            "skipped": skipped,
            "added": store.added_bytes - before_bytes,
            "added_files": len(store.uploaded) - before_count,
            "index_size": len(packed),
        }

    def _backup_quills(self, bucket: Bucket, key: str) -> dict:
        up = Uploader(bucket, key)
        counter = {"files": 0}
        data_dir = self.state.config.data_dir
        try:
            with tarfile.open(fileobj=up, mode="w|gz", compresslevel=3) as tar:
                for name in QUILL_FOLDERS:
                    folder = data_dir / name
                    if folder.is_dir():
                        tar.add(folder, arcname=name, filter=_tar_filter(counter))
            up.finish()
        except BaseException:
            up.abandon()
            raise
        return {"key": key, "size": up.size, "sha256": up.sha256, "files": counter["files"]}

    def _backup_keys(self, bucket: Bucket, key: str, *, with_sealing: bool) -> dict:
        config = self.state.config
        up = Uploader(bucket, key)
        carried: list[str] = []
        try:
            with tarfile.open(fileobj=up, mode="w|gz") as tar:
                for name in KEY_FILES:
                    path = config.data_dir / name
                    if path.is_file():
                        tar.add(path, arcname=name)
                        carried.append(name)
                if with_sealing and config.secrets_key_path.is_file():
                    tar.add(config.secrets_key_path, arcname=SEALING_KEY)
                    carried.append(SEALING_KEY)
            up.finish()
        except BaseException:
            up.abandon()
            raise
        return {
            "key": key,
            "size": up.size,
            "sha256": up.sha256,
            "files": carried,
            "sealing_key": SEALING_KEY in carried,
        }

    # -- what is in the bucket -----------------------------------------------------------
    def _stamps(self, bucket: Bucket, settings: Settings) -> list[str]:
        root = settings.root()
        try:
            listed = bucket.list(root, delimiter="/", limit=100000)
        except S3Error as exc:
            raise BackupError(str(exc)) from exc
        stamps = [p[len(root) :].strip("/") for p in listed.prefixes]
        return sorted((s for s in stamps if STAMP_RE.match(s)), reverse=True)

    def list_backups(self, *, limit: int = 200) -> list[dict]:
        """Every finished backup in the bucket, newest first, as its manifest says."""
        settings = self.settings()
        bucket = self.bucket(settings)
        found: list[dict] = []
        for stamp in self._stamps(bucket, settings)[:limit]:
            manifest = self._manifest(bucket, settings, stamp)
            if manifest is not None:
                found.append(self._summary(manifest))
        return found

    def _manifest(self, bucket: Bucket, settings: Settings, stamp: str) -> dict | None:
        try:
            data = bucket.get(settings.root() + stamp + "/manifest.json")
        except S3Error as exc:
            if exc.status == 404:
                return None
            raise BackupError(str(exc)) from exc
        try:
            manifest = json.loads(data)
        except ValueError:
            return None
        if not isinstance(manifest, dict) or manifest.get("cloudmorrow_backup") not in FORMATS:
            return None
        # The folder names the backup; the manifest only repeats it.
        manifest["stamp"] = stamp
        manifest["key_matches"] = manifest.get("sealed_with") == key_fingerprint(self.state.sealer.master)
        return manifest

    @staticmethod
    def _summary(manifest: dict) -> dict:
        return {
            "stamp": manifest["stamp"],
            "made_at": manifest.get("made_at", ""),
            "cloud": manifest.get("cloud", ""),
            "version": manifest.get("version", ""),
            "format": manifest.get("cloudmorrow_backup", 1),
            "parts": manifest.get("parts", []),
            "size": manifest.get("size", 0),
            "added": manifest.get("added", 0),
            "files": manifest.get("files", 0),
            "took": manifest.get("took", 0),
            "drives": len(manifest.get("drives") or []),
            "shares": len(manifest.get("shares") or []),
            "key_matches": manifest.get("key_matches", False),
            "by": manifest.get("by", ""),
        }

    def describe(self, stamp: str) -> dict:
        """One backup's manifest, with whether its database would open here."""
        if not STAMP_RE.match(stamp):
            raise BackupError(f"not a backup: {stamp}")
        settings = self.settings()
        manifest = self._manifest(self.bucket(settings), settings, stamp)
        if manifest is None:
            raise BackupError(f"there is no finished backup {stamp} in the bucket")
        return manifest

    def _part_index(self, bucket: Bucket, manifest: dict, kind: str, name: str) -> dict:
        """The index of one drive or share in a format-2 backup."""
        if manifest.get("cloudmorrow_backup") != 2:
            raise BackupError("this backup is from before single files could be looked at; restore the whole drive")
        part = next((p for p in manifest.get(kind) or [] if p["name"] == name), None)
        if part is None:
            what = "files of" if kind == "drives" else "share called"
            raise BackupError(f"this backup has no {what} {name}")
        return self._index(bucket, part["key"])

    def files(self, stamp: str, where: str, path: str = "") -> dict:
        """What a backup holds under one folder of a drive or a share: for browsing.

        *where* is `drives/<name>` or `shares/<name>`; *path* a folder in
        it, blank for its top. Folders come with how many files and bytes
        are under them; files with their size and when they were changed.
        """
        kind, name, rest = split_path(where)
        if rest.strip("/"):
            raise BackupError(f"where is drives/<name> or shares/<name>, not {where!r}")
        folder = path.strip("/")
        if folder and not _safe_rel(folder):
            raise BackupError(f"not a folder a backup can hold: {path!r}")
        settings = self.settings()
        bucket = self.bucket(settings)
        index = self._part_index(bucket, self.describe(stamp), kind, name)
        prefix = folder + "/" if folder else ""
        folders: dict[str, dict] = {}
        files: list[dict] = []
        for rel in index.get("dirs") or []:
            if rel.startswith(prefix) and "/" not in rel[len(prefix) :] and rel != folder:
                folders.setdefault(rel[len(prefix) :], {"name": rel[len(prefix) :], "files": 0, "size": 0})
        for rel, entry in (index.get("files") or {}).items():
            if not rel.startswith(prefix):
                continue
            rest = rel[len(prefix) :]
            if "/" in rest:
                top = rest.split("/", 1)[0]
                told = folders.setdefault(top, {"name": top, "files": 0, "size": 0})
                told["files"] += 1
                told["size"] += int(entry[1])
            else:
                files.append(
                    {
                        "name": rest,
                        "size": int(entry[1]),
                        "modified": _iso(dt.datetime.fromtimestamp(int(entry[2]) / 1e9, tz=dt.UTC)),
                    }
                )
        if folder and not folders and not files and folder not in (index.get("dirs") or []):
            raise BackupError(f"this backup has no folder {folder} in {where}")
        return {
            "stamp": stamp,
            "where": f"{kind}/{name}",
            "path": folder,
            "folders": sorted(folders.values(), key=lambda f: f["name"].lower()),
            "files": sorted(files, key=lambda f: f["name"].lower()),
        }

    def open_file(self, stamp: str, path: str):
        """One file as it was in a backup: its open body, its size and its name, to stream out."""
        kind, name, rel = split_path(path)
        rel = rel.rstrip("/")
        if not rel:
            raise BackupError("name a file, not a drive")
        settings = self.settings()
        bucket = self.bucket(settings)
        index = self._part_index(bucket, self.describe(stamp), kind, name)
        entry = (index.get("files") or {}).get(rel)
        if entry is None:
            raise BackupError(f"this backup has no file {rel} in {kind}/{name}")
        store = Store(bucket, settings.root())
        return store.open(entry[0]), int(entry[1]), rel.rsplit("/", 1)[-1]

    def delete_backup(self, stamp: str) -> int:
        """One backup out of the bucket, and with it the objects only it named."""
        if not STAMP_RE.match(stamp):
            raise BackupError(f"not a backup: {stamp}")
        settings = self.settings()
        bucket = self.bucket(settings)
        manifest = self._manifest(bucket, settings, stamp)
        gone = 0
        try:
            if manifest is not None and manifest.get("cloudmorrow_backup") == 2:
                others = [
                    m
                    for m in (self._manifest(bucket, settings, s) for s in self._stamps(bucket, settings) if s != stamp)
                    if m
                ]
                gone += self._drop_objects(bucket, settings, [manifest], self._references(bucket, settings, others))
            gone += bucket.delete_prefix(settings.root() + stamp + "/")
        except S3Error as exc:
            raise BackupError(str(exc)) from exc
        return gone

    def _drop_objects(self, bucket: Bucket, settings: Settings, going: list[dict], needed: dict[str, int]) -> int:
        """The objects the *going* snapshots name and nobody in *needed* does: deleted."""
        store = Store(bucket, settings.root())
        dropped: set[str] = set()
        for digest in self._references(bucket, settings, going):
            if digest not in needed and digest not in dropped:
                store.delete(digest)
                dropped.add(digest)
        return len(dropped)

    def sweep(self, *, bucket: Bucket | None = None, settings: Settings | None = None) -> dict:
        """Take away the backups older than the days kept, folders left by
        backups that never finished, and the objects no remaining backup
        names. Answers what went, and when something went, what the store
        now holds (`totals`: objects and bytes)."""
        settings = settings or self.settings()
        bucket = bucket or self.bucket(settings)
        now = self.now()
        gone: list[str] = []
        going: list[dict] = []
        kept: list[dict] = []
        for stamp in self._stamps(bucket, settings):
            made = dt.datetime.strptime(stamp, STAMP).replace(tzinfo=dt.UTC)
            age = now - made
            manifest = self._manifest(bucket, settings, stamp)
            finished = manifest is not None
            if (finished and age > dt.timedelta(days=settings.keep_days)) or (not finished and age > UNFINISHED_AFTER):
                gone.append(stamp)
                if manifest is not None:
                    going.append(manifest)
            elif manifest is not None:
                kept.append(manifest)
        told: dict = {"backups": gone, "objects": 0, "totals": None}
        if not gone:
            return told
        try:
            needed = self._references(bucket, settings, kept)
            told["objects"] = self._drop_objects(bucket, settings, going, needed)
            for stamp in gone:
                bucket.delete_prefix(settings.root() + stamp + "/")
        except S3Error as exc:
            raise BackupError(str(exc)) from exc
        told["totals"] = self._set_totals(len(needed), sum(needed.values()))
        return told

    # -- restoring --------------------------------------------------------------------------
    def start_restore(self, stamp: str, choice: Choice, *, by: str = "") -> dict:
        settings = self.settings()
        bucket = self.bucket(settings)
        manifest = self.describe(stamp)
        self._check_choice(manifest, choice)
        self._check_paths(bucket, manifest, choice)
        return self._run_on_thread(
            "restore",
            by,
            lambda: self.restore(stamp, choice, settings=settings, bucket=bucket, manifest=manifest, by=by),
        )

    def _check_choice(self, manifest: dict, choice: Choice) -> None:
        if not choice.anything():
            raise BackupError("choose what to restore")
        if choice.database and not manifest.get("database"):
            raise BackupError("this backup has no database in it")
        if choice.quills and not manifest.get("quills"):
            raise BackupError("this backup has no Quills in it")
        if choice.keys and not manifest.get("keys"):
            raise BackupError("this backup has no keys in it")
        drives = {d["name"] for d in manifest.get("drives") or []}
        missing = [d for d in choice.drives if d not in drives]
        if missing:
            raise BackupError(f"this backup has no files of {', '.join(missing)}")
        shares = {s["name"] for s in manifest.get("shares") or []}
        missing = [s for s in choice.shares if s not in shares]
        if missing:
            raise BackupError(f"this backup has no share called {', '.join(missing)}")
        for path in choice.paths:
            kind, name, rel = split_path(path)
            if not rel.strip("/"):
                raise BackupError(f"{path} names a whole {kind[:-1]}: tick it as one instead")
            if manifest.get("cloudmorrow_backup") != 2:
                raise BackupError(
                    "this backup is from before single files could be restored; restore the whole drive or share"
                )
            if name not in (drives if kind == "drives" else shares):
                what = "files of" if kind == "drives" else "share called"
                raise BackupError(f"this backup has no {what} {name}")
        brings_key = bool(choice.keys and (manifest.get("keys") or {}).get("sealing_key"))
        if choice.database and not manifest.get("key_matches") and not brings_key and not choice.force:
            raise BackupError(
                "this backup's database was sealed with another key than this server's, so its rows would not "
                "open here. Restore the sealing key with it (the keys part), put the right key file in place "
                "first, or force it."
            )

    def _check_paths(self, bucket: Bucket, manifest: dict, choice: Choice) -> None:
        """Every chosen path is in its index, as a file or a folder."""
        for path in choice.paths:
            kind, name, rel = split_path(path)
            index = self._part_index(bucket, manifest, kind, name)
            folder = rel.rstrip("/")
            files = index.get("files") or {}
            if folder in files or folder in (index.get("dirs") or []):
                continue
            if any(f.startswith(folder + "/") for f in files):
                continue
            raise BackupError(f"this backup has no {rel} in {kind}/{name}")

    def restore(
        self,
        stamp: str,
        choice: Choice,
        *,
        settings: Settings | None = None,
        bucket: Bucket | None = None,
        manifest: dict | None = None,
        by: str = "",
    ) -> dict:
        """Put the chosen parts of backup *stamp* back. Answers what was done."""
        settings = settings or self.settings()
        bucket = bucket or self.bucket(settings)
        manifest = manifest or self.describe(stamp)
        self._check_choice(manifest, choice)
        own = self._running != "restore"
        if own:
            self._begin("restore", by)
        started = self.now()
        done: dict = {"database": False, "drives": [], "shares": [], "paths": [], "quills": False, "keys": []}
        restart_needed = False
        store = Store(bucket, settings.root())
        # Single paths, by the drive or share they are in; one restored whole needs none of them.
        chosen_paths: dict[tuple[str, str], list[str]] = {}
        for path in choice.paths:
            kind, name, rel = split_path(path)
            if name in (choice.drives if kind == "drives" else choice.shares):
                continue
            chosen_paths.setdefault((kind, name), []).append(rel.rstrip("/"))
        try:
            if choice.database:
                self._at("Restoring the database")
                self._restore_database(bucket, store, manifest["database"])
                done["database"] = True
                restart_needed = True
                self._say("Database restored; the one from before is kept in before-restore/")
            for name in choice.drives:
                part = next(d for d in manifest["drives"] if d["name"] == name)
                self._at(f"Restoring {name}'s files")
                dest = self.state.config.notes_dir / _safe_name(name)
                told = self._restore_part(bucket, store, part, dest)
                done["drives"].append(name)
                self._say(f"{name}'s files: " + _put_back(told))
            for name in choice.shares:
                part = next(s for s in manifest["shares"] if s["name"] == name)
                self._at(f"Restoring the share {name}")
                dest = self._share_dest(name)
                told = self._restore_part(bucket, store, part, dest)
                done["shares"].append(name)
                where = "" if self.state.shares.get(name) else f" into {dest}, since no share of that name is known"
                self._say(f"Share {name}: " + _put_back(told) + where)
            for (kind, name), rels in chosen_paths.items():
                part = next(p for p in manifest[kind] if p["name"] == name)
                said = f"{name}'s files" if kind == "drives" else f"the share {name}"
                self._at(f"Restoring {_count(len(rels), 'path')} of {said}")
                dest = self.state.config.notes_dir / _safe_name(name) if kind == "drives" else self._share_dest(name)
                told = self._restore_index(store, part["key"], dest, only=rels)
                done["paths"].extend(f"{kind}/{name}/{rel}" for rel in rels)
                self._say(f"From {said}, {', '.join(rels)}: " + _put_back(told))
            if choice.quills:
                self._at("Restoring the Quills")
                files, skipped = self._restore_quills(bucket, manifest["quills"]["key"])
                done["quills"] = True
                restart_needed = True
                self._say(f"Quills: {_count(files, 'file')} put back")
            if choice.keys:
                self._at("Restoring the keys")
                done["keys"] = self._restore_keys(bucket, manifest["keys"]["key"], with_database=choice.database)
                restart_needed = True
                self._say("Keys put back: " + ", ".join(done["keys"]) if done["keys"] else "Keys: nothing to put back")
        except (S3Error, OSError, BackupError, subprocess.SubprocessError, tarfile.TarError) as exc:
            self._say(f"Failed: {exc}")
            self._remember(LAST_RESTORE, stamp, started, ok=False, error=str(exc), by=by, **done)
            raise BackupError(str(exc)) from exc
        finally:
            if own:
                self._end()
        done["restart_needed"] = restart_needed
        done["restarting"] = False
        done["restart_blocked"] = ""
        if restart_needed:
            from cloudmorrow.server.update import self_restart, self_restart_blocker

            if not choice.restart:
                done["restart_blocked"] = "not asked to; restart the server to be sure nothing remembers the old rows"
            else:
                blocker = self_restart_blocker(self.state.config.service_name)
                if blocker:
                    done["restart_blocked"] = blocker
                else:
                    done["restarting"] = True
            self._say("Restarting the server" if done["restarting"] else f"Not restarted: {done['restart_blocked']}")
        self._remember(LAST_RESTORE, stamp, started, ok=True, by=by, **done)
        if done["restarting"]:
            self_restart()
        return {"stamp": stamp, **done}

    def _share_dest(self, name: str) -> Path:
        share = self.state.shares.get(name)
        return Path(share.path) if share is not None else self.state.config.shares_root() / _safe_name(name)

    def _restore_part(self, bucket: Bucket, store: Store, part: dict, dest: Path) -> dict:
        """A whole drive or share back, from an index (format 2) or an archive (format 1)."""
        if part.get("key", "").endswith(".index.gz"):
            return self._restore_index(store, part["key"], dest)
        files, skipped = self._restore_folder(bucket, part["key"], dest)
        return {"files": files, "skipped": skipped, "unchanged": 0}

    def _download(self, bucket: Bucket, key: str, *, gunzip: bool) -> Path:
        copy = self._tmp() / f"restore-{os.getpid()}-{int(time.time())}{'.sqlite' if gunzip else '.pgdump'}"
        try:
            response = bucket.open(key)
        except S3Error as exc:
            raise BackupError(str(exc)) from exc
        with copy.open("wb") as out:
            if gunzip:
                with gzip.GzipFile(fileobj=response, mode="rb") as packed:
                    shutil.copyfileobj(packed, out, 1024 * 1024)
                response.close()
            else:
                for chunk in read_chunks(response):
                    out.write(chunk)
        return copy

    def _download_chunks(self, bucket: Bucket, store: Store, index_key: str) -> Path:
        """The database copy, piece by piece out of the store, each checked."""
        index = self._index(bucket, index_key)
        copy = self._tmp() / f"restore-{os.getpid()}-{int(time.time())}.sqlite"
        with copy.open("wb") as out:
            for entry in index.get("chunks") or []:
                digest = str(entry[0])
                data = b"".join(read_chunks(store.open(digest)))
                if index.get("gzip", True):
                    try:
                        data = gzip.decompress(data)
                    except OSError as exc:
                        raise BackupError(f"a piece of the database in the bucket could not be read: {exc}") from exc
                if hashlib.sha256(data).hexdigest() != digest:
                    raise BackupError("a piece of the database in the bucket is not what the index says")
                out.write(data)
        return copy

    def _restore_database(self, bucket: Bucket, store: Store, part: dict) -> None:
        db = self.state.db
        if part.get("engine") != db.engine.name:
            raise BackupError(f"this backup's database is {part.get('engine')}'s; this server runs {db.engine.name}")
        if part.get("chunked"):
            copy = self._download_chunks(bucket, store, part["key"])
        else:
            copy = self._download(bucket, part["key"], gunzip=db.engine.name == "sqlite")
        try:
            if db.engine.name == "sqlite":
                check = sqlite3.connect(copy)
                try:
                    verdict = check.execute("PRAGMA quick_check").fetchone()[0]
                    if verdict != "ok":
                        raise BackupError(f"the database in the backup does not check out: {verdict}")
                    if check.execute("PRAGMA user_version").fetchone()[0] > schema.VERSION:
                        raise BackupError(
                            "the database in the backup is from a newer Cloudmorrow than this server runs"
                        )
                finally:
                    check.close()
                self._keep_before_restore()
                engine = db.engine
                source = sqlite3.connect(copy)
                raw = engine.acquire()
                try:
                    source.backup(raw)
                finally:
                    engine.release(raw)
                    source.close()
            else:
                tool = shutil.which("pg_restore")
                if not tool:
                    raise BackupError("pg_restore is not installed on this server: apt install postgresql-client")
                self._keep_before_restore()
                result = subprocess.run(
                    [tool, "--clean", "--if-exists", "--no-owner", "--no-privileges", "--dbname", db.url, str(copy)],
                    capture_output=True,
                    check=False,
                )
                if result.returncode != 0:
                    raise BackupError(f"pg_restore failed: {result.stderr.decode(errors='replace').strip()}")
        finally:
            copy.unlink(missing_ok=True)
        # The next connection brings an older schema up to date, and forgets
        # what it knew about which tables were there.
        db.recheck()

    def _keep_before_restore(self) -> None:
        """What the database is now, kept on disk before the backup goes over it."""
        folder = self.state.config.data_dir / "before-restore"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = self.now().strftime(STAMP)
        db = self.state.db
        if db.engine.name == "sqlite":
            self._copy_sqlite_out(folder / f"{stamp}.sqlite")
        else:
            tool = shutil.which("pg_dump")
            if tool:
                with (folder / f"{stamp}.pgdump").open("wb") as out:
                    subprocess.run(
                        [tool, "--format=custom", "--no-owner", "--no-privileges", "--dbname", db.url],
                        stdout=out,
                        check=True,
                    )
        kept = sorted(p for p in folder.iterdir() if p.is_file())
        for old in kept[:-KEEP_BEFORE]:
            old.unlink(missing_ok=True)

    def _restore_index(self, store: Store, index_key: str, dest: Path, *, only: list[str] | None = None) -> dict:
        """The files an index names, out of the store and into *dest* — all of
        them, or those under *only*. Each is written beside its place and
        moved in once its digest checks out. One already there with the same
        size and mtime is left alone. Nothing may land outside *dest*."""
        index = self._index(store.bucket, index_key)
        dest.mkdir(parents=True, exist_ok=True)
        files = unchanged = skipped = 0
        for rel in index.get("dirs") or []:
            if _safe_rel(rel) and _in(rel, only):
                (dest / rel).mkdir(parents=True, exist_ok=True)
        for rel, entry in (index.get("files") or {}).items():
            if not _in(rel, only):
                continue
            if not _safe_rel(rel) or not isinstance(entry, list) or len(entry) < 4:
                skipped += 1
                continue
            digest, size, mtime_ns, mode = str(entry[0]), int(entry[1]), int(entry[2]), int(entry[3])
            target = dest / rel
            try:
                st = target.lstat()
                if stat.S_ISREG(st.st_mode) and st.st_size == size and st.st_mtime_ns == mtime_ns:
                    unchanged += 1
                    continue
            except FileNotFoundError:
                pass
            try:
                self._write_object(store, digest, target, size, mtime_ns, mode)
            except (OSError, BackupError) as exc:
                log.warning("skipped %s: %s", rel, exc)
                self._say(f"Skipped {rel}: {exc}")
                skipped += 1
                continue
            files += 1
        return {"files": files, "unchanged": unchanged, "skipped": skipped}

    def _write_object(self, store: Store, digest: str, target: Path, size: int, mtime_ns: int, mode: int) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.parent / f"{TEMP_PREFIX}{digest[:16]}"
        check = hashlib.sha256()
        written = 0
        try:
            with temp.open("wb") as out:
                for chunk in read_chunks(store.open(digest)):
                    check.update(chunk)
                    written += len(chunk)
                    out.write(chunk)
            if check.hexdigest() != digest:
                raise BackupError(f"the object {digest[:12]}… in the bucket is not what the index says")
            os.chmod(temp, (mode & 0o777) or 0o644)
            os.utime(temp, ns=(mtime_ns, mtime_ns))
            if target.is_dir() and not target.is_symlink():
                raise BackupError("a folder stands where the file was")
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)

    def _restore_folder(
        self, bucket: Bucket, key: str, dest: Path, *, allowed_tops: Iterable[str] | None = None
    ) -> tuple[int, int]:
        """Extract the archive at *key* into *dest*, member by member as it
        streams down. Nothing may land outside *dest*; what tries is skipped."""
        dest.mkdir(parents=True, exist_ok=True)
        root = dest.resolve()
        tops = set(allowed_tops) if allowed_tops is not None else None
        files = skipped = 0
        try:
            response = bucket.open(key)
        except S3Error as exc:
            raise BackupError(str(exc)) from exc
        with response, tarfile.open(fileobj=response, mode="r|gz") as tar:
            for member in tar:
                name = member.name.lstrip("./")
                parts = Path(name).parts
                if (
                    not parts
                    or ".." in parts
                    or Path(name).is_absolute()
                    or (tops is not None and parts[0] not in tops)
                ):
                    skipped += 1
                    continue
                try:
                    tar.extract(member, path=root, filter="data")
                except (tarfile.FilterError, OSError) as exc:
                    log.warning("skipped %s: %s", member.name, exc)
                    skipped += 1
                    continue
                if member.isfile():
                    files += 1
        return files, skipped

    def _restore_quills(self, bucket: Bucket, key: str) -> tuple[int, int]:
        files, skipped = self._restore_folder(bucket, key, self.state.config.data_dir, allowed_tops=QUILL_FOLDERS)
        self.state.quills.reload()
        return files, skipped

    def _restore_keys(self, bucket: Bucket, key: str, *, with_database: bool) -> list[str]:
        config = self.state.config
        put: list[str] = []
        try:
            response = bucket.open(key)
        except S3Error as exc:
            raise BackupError(str(exc)) from exc
        with response, tarfile.open(fileobj=response, mode="r|gz") as tar:
            for member in tar:
                if not member.isfile():
                    continue
                handle = tar.extractfile(member)
                if handle is None:
                    continue
                data = handle.read()
                name = Path(member.name).name
                if name in KEY_FILES:
                    target = config.data_dir / name
                elif name == SEALING_KEY:
                    target = config.secrets_key_path
                    # The sealing key goes back only with the database it
                    # seals, or where there is none: over a key in use on its
                    # own, it would lock every row the server has.
                    if target.exists() and not with_database:
                        self._say("The sealing key stays as it is: it goes back only with the database")
                        continue
                else:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "wb") as out:
                    out.write(data)
                os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
                put.append(name)
        return put


def _digests(index: dict) -> Iterator[str]:
    """Every digest an index names: a drive's files, or the database's pieces."""
    for entry in (index.get("files") or {}).values():
        if isinstance(entry, list) and entry:
            yield str(entry[0])
    for entry in index.get("chunks") or []:
        if isinstance(entry, list) and entry:
            yield str(entry[0])


def _sizes(index: dict) -> dict[str, int]:
    """Every digest an index names, with the bytes its object takes in the store."""
    found: dict[str, int] = {}
    for entry in (index.get("files") or {}).values():
        if isinstance(entry, list) and len(entry) >= 2:
            found[str(entry[0])] = int(entry[1])
    for entry in index.get("chunks") or []:
        if isinstance(entry, list) and len(entry) >= 2:
            found[str(entry[0])] = int(entry[2] if len(entry) >= 3 else entry[1])
    return found


def _added(told: dict) -> str:
    return f", {_size(told['added'])} new" if told.get("added") else ", nothing new"


def _put_back(told: dict) -> str:
    said = f"{_count(told['files'], 'file')} put back"
    if told.get("unchanged"):
        said += f", {_count(told['unchanged'], 'file')} already there"
    if told.get("skipped"):
        said += f", {told['skipped']} skipped"
    return said


def _size(count: int) -> str:
    size = float(count)
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if size < 1000 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1000
    return f"{count} B"


def _count(count: int, noun: str) -> str:
    return f"{count:,} {noun}{'' if count == 1 else 's'}"
