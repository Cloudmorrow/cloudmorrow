"""Backups: everything this server holds, into an S3 bucket, every day — and back.

A home server is one disk, and one disk is one bad day away from nothing.
So an administrator names a bucket — Amazon's, Hetzner's, Backblaze's, a
MinIO of their own — under Administration, Backups, says what goes and
when, and from then on the clock puts a copy of it all there every day,
and throws away the ones older than it was told to keep. **Restore** reads
one back: all of it, or the parts chosen — the database, this drive, that
share — over what is on the server now.

What a backup is: one folder in the bucket, named by the moment it was
taken, with an object per part and a `manifest.json` that lists them, their
sizes and their digests. The parts:

- **database** — the accounts, circles, roles, every record of every Quill,
  the settings, the secrets, which Quills are installed: a copy of the
  SQLite file at one moment (`.sqlite.gz`), or a `pg_dump` (`.pgdump`).
  Sealed rows stay sealed: without the key the dump opens nothing, which is
  the point of keeping the key apart from the data.
- **drives** — everybody's own files, notes included, an archive per
  drive (`drives/<name>.tar.gz`), so one person's can be put back alone.
- **shares** — every share, an archive each, wherever its folder is.
- **quills** — the installed Quills, people's own, the datamodels and the
  runtimes fetched for them: the folders in the data directory.
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
extracted over what is there: what the backup has wins, what it does not
have is left alone.

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
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from cloudmorrow import __version__
from cloudmorrow.server import schema
from cloudmorrow.server.s3 import Bucket, S3Error, Uploader, read_chunks

if TYPE_CHECKING:
    from cloudmorrow.server.state import AppState

__all__ = ["BackupError", "Backups", "Choice", "FORMAT", "PARTS", "Settings"]

log = logging.getLogger("cloudmorrow.backups")

FORMAT = 1
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
# A folder with no manifest this old was a backup that never finished.
UNFINISHED_AFTER = dt.timedelta(days=1)
# How many copies of the database from before a restore stay on disk.
KEEP_BEFORE = 3
KEEP_DAYS_MOST = 3650

# The settings rows. The secret is sealed in its own row.
CONFIG = "backup.config"
SECRET = "backup.secret"
LAST = "backup.last"
LAST_RESTORE = "backup.last_restore"
LAST_DAY = "backup.last_day"


class BackupError(RuntimeError):
    """Something about the destination, the choice, or the run does not hold."""


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
    quills: bool = False
    keys: bool = False
    # Restart afterwards, when what was restored asks for it.
    restart: bool = True
    # Restore the database although it was sealed with another key.
    force: bool = False

    def anything(self) -> bool:
        return bool(self.database or self.drives or self.shares or self.quills or self.keys)


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


def _tar_filter(counter: dict[str, int]) -> Callable[[tarfile.TarInfo], tarfile.TarInfo | None]:
    def keep(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        # Pipes and devices are not files worth carrying; everything else is.
        if info.isfifo() or info.ischr() or info.isblk():
            return None
        if info.isfile():
            counter["files"] += 1
        return info

    return keep


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

    def backup(
        self,
        parts: Iterable[str] | None = None,
        *,
        settings: Settings | None = None,
        bucket: Bucket | None = None,
        by: str = "",
    ) -> dict:
        """One backup, now, on this thread. Answers the manifest; raises on failure.

        Called by `start_backup` on its thread, and directly by tests. When
        called directly it takes the running slot itself.
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
        folder = settings.root() + stamp + "/"
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
            "by": by,
        }
        try:
            if "database" in chosen:
                self._at("Backing up the database")
                manifest["database"] = self._backup_database(bucket, folder)
                self._say(f"Database: {_size(manifest['database']['size'])}")
            if "drives" in chosen:
                for name, path in self._drives():
                    self._at(f"Backing up {name}'s files")
                    told = self._backup_folder(bucket, folder + "drives/" + _safe_name(name) + ".tar.gz", path)
                    told["name"] = name
                    manifest["drives"].append(told)
                    self._say(f"{name}'s files: {_size(told['size'])}, {_count(told['files'], 'file')}")
            if "shares" in chosen:
                for share in self.state.shares.all():
                    if not Path(share.path).is_dir():
                        self._say(f"Share {share.name}: its folder {share.path} is not there; skipped")
                        continue
                    self._at(f"Backing up the share {share.name}")
                    told = self._backup_folder(
                        bucket, folder + "shares/" + _safe_name(share.name) + ".tar.gz", Path(share.path)
                    )
                    told["name"] = share.name
                    told["path"] = str(share.path)
                    manifest["shares"].append(told)
                    self._say(f"Share {share.name}: {_size(told['size'])}, {_count(told['files'], 'file')}")
            if "quills" in chosen:
                self._at("Backing up the Quills")
                manifest["quills"] = self._backup_quills(bucket, folder + "quills.tar.gz")
                self._say(f"Quills: {_size(manifest['quills']['size'])}, {_count(manifest['quills']['files'], 'file')}")
            if "keys" in chosen:
                self._at("Backing up the keys")
                manifest["keys"] = self._backup_keys(bucket, folder + "keys.tar.gz", with_sealing=settings.seal_key)
                self._say("Keys" + (", the sealing key among them" if manifest["keys"]["sealing_key"] else ""))
            manifest["size"] = sum(
                part["size"]
                for part in (
                    manifest["database"],
                    manifest["quills"],
                    manifest["keys"],
                    *manifest["drives"],
                    *manifest["shares"],
                )
                if part
            )
            finished = self.now()
            manifest["finished_at"] = _iso(finished)
            manifest["took"] = round((finished - started).total_seconds(), 1)
            self._at("Writing the manifest")
            bucket.put(
                folder + "manifest.json", json.dumps(manifest, indent=1, sort_keys=True).encode(), "application/json"
            )
            self._say(f"Done: {_size(manifest['size'])} in {manifest['took']} s, as {stamp}")
        except (S3Error, OSError, BackupError, subprocess.SubprocessError) as exc:
            self._say(f"Failed: {exc}")
            self._remember(LAST, stamp, started, ok=False, error=str(exc), by=by, parts=chosen)
            # A folder with no manifest is swept as unfinished; nothing hangs on it.
            raise BackupError(str(exc)) from exc
        finally:
            if own:
                self._end()
        self._remember(LAST, stamp, started, ok=True, by=by, parts=chosen, size=manifest["size"])
        try:
            self.sweep(bucket=bucket, settings=settings)
        except (S3Error, BackupError) as exc:
            log.warning("the sweep of old backups failed: %s", exc)
        return manifest

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

    def _backup_database(self, bucket: Bucket, folder: str) -> dict:
        db = self.state.db
        if db.engine.name == "sqlite":
            copy = self._tmp() / f"database-{os.getpid()}-{int(time.time())}.sqlite"
            try:
                self._copy_sqlite_out(copy)
                up = Uploader(bucket, folder + "database.sqlite.gz")
                try:
                    with gzip.GzipFile(fileobj=up, mode="wb", compresslevel=6) as packed, copy.open("rb") as source:
                        shutil.copyfileobj(source, packed, 1024 * 1024)
                    up.finish()
                except BaseException:
                    up.abandon()
                    raise
            finally:
                copy.unlink(missing_ok=True)
            return {"engine": "sqlite", "key": folder + "database.sqlite.gz", "size": up.size, "sha256": up.sha256}
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
        return {"engine": "postgres", "key": folder + "database.pgdump", "size": up.size, "sha256": up.sha256}

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

    def _backup_folder(self, bucket: Bucket, key: str, root: Path) -> dict:
        up = Uploader(bucket, key)
        counter = {"files": 0}
        try:
            with tarfile.open(fileobj=up, mode="w|gz", compresslevel=3) as tar:
                for child in sorted(root.iterdir()):
                    tar.add(child, arcname=child.name, filter=_tar_filter(counter))
            up.finish()
        except BaseException:
            up.abandon()
            raise
        return {"key": key, "size": up.size, "sha256": up.sha256, "files": counter["files"]}

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
        if not isinstance(manifest, dict) or manifest.get("cloudmorrow_backup") != FORMAT:
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
            "parts": manifest.get("parts", []),
            "size": manifest.get("size", 0),
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

    def delete_backup(self, stamp: str) -> int:
        if not STAMP_RE.match(stamp):
            raise BackupError(f"not a backup: {stamp}")
        settings = self.settings()
        try:
            return self.bucket(settings).delete_prefix(settings.root() + stamp + "/")
        except S3Error as exc:
            raise BackupError(str(exc)) from exc

    def sweep(self, *, bucket: Bucket | None = None, settings: Settings | None = None) -> list[str]:
        """Take away the backups older than the days kept, and folders left by
        backups that never finished. Answers what went."""
        settings = settings or self.settings()
        bucket = bucket or self.bucket(settings)
        now = self.now()
        gone: list[str] = []
        for stamp in self._stamps(bucket, settings):
            made = dt.datetime.strptime(stamp, STAMP).replace(tzinfo=dt.UTC)
            age = now - made
            finished = self._manifest(bucket, settings, stamp) is not None
            if (finished and age > dt.timedelta(days=settings.keep_days)) or (not finished and age > UNFINISHED_AFTER):
                try:
                    bucket.delete_prefix(settings.root() + stamp + "/")
                except S3Error as exc:
                    raise BackupError(str(exc)) from exc
                gone.append(stamp)
        return gone

    # -- restoring --------------------------------------------------------------------------
    def start_restore(self, stamp: str, choice: Choice, *, by: str = "") -> dict:
        settings = self.settings()
        bucket = self.bucket(settings)
        manifest = self.describe(stamp)
        self._check_choice(manifest, choice)
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
        brings_key = bool(choice.keys and (manifest.get("keys") or {}).get("sealing_key"))
        if choice.database and not manifest.get("key_matches") and not brings_key and not choice.force:
            raise BackupError(
                "this backup's database was sealed with another key than this server's, so its rows would not "
                "open here. Restore the sealing key with it (the keys part), put the right key file in place "
                "first, or force it."
            )

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
        done: dict = {"database": False, "drives": [], "shares": [], "quills": False, "keys": []}
        restart_needed = False
        try:
            if choice.database:
                self._at("Restoring the database")
                self._restore_database(bucket, manifest["database"])
                done["database"] = True
                restart_needed = True
                self._say("Database restored; the one from before is kept in before-restore/")
            for name in choice.drives:
                part = next(d for d in manifest["drives"] if d["name"] == name)
                self._at(f"Restoring {name}'s files")
                dest = self.state.config.notes_dir / _safe_name(name)
                files, skipped = self._restore_folder(bucket, part["key"], dest)
                done["drives"].append(name)
                self._say(
                    f"{name}'s files: {_count(files, 'file')} put back" + (f", {skipped} skipped" if skipped else "")
                )
            for name in choice.shares:
                part = next(s for s in manifest["shares"] if s["name"] == name)
                self._at(f"Restoring the share {name}")
                share = self.state.shares.get(name)
                dest = Path(share.path) if share is not None else self.state.config.shares_root() / _safe_name(name)
                files, skipped = self._restore_folder(bucket, part["key"], dest)
                done["shares"].append(name)
                where = "" if share is not None else f" into {dest}, since no share of that name is known"
                self._say(
                    f"Share {name}: {_count(files, 'file')} put back{where}"
                    + (f", {skipped} skipped" if skipped else "")
                )
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

    def _restore_database(self, bucket: Bucket, part: dict) -> None:
        db = self.state.db
        if part.get("engine") != db.engine.name:
            raise BackupError(f"this backup's database is {part.get('engine')}'s; this server runs {db.engine.name}")
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


def _size(count: int) -> str:
    size = float(count)
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if size < 1000 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1000
    return f"{count} B"


def _count(count: int, noun: str) -> str:
    return f"{count:,} {noun}{'' if count == 1 else 's'}"
