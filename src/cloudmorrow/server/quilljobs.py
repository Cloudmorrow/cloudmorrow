"""What the core does for Quills without being asked: at boot, and on a clock.

At boot:

* A server that has never had a Quill installed gets the catalog's
  foundation Quills — the ones marked `foundation = true` — so a fresh
  install has Tasks the way it always had. Once; after that, what is
  installed is the administrator's business.
* A feature that was built in and is a Quill now (Notes) is installed from
  the catalog on a server that had it on, so nothing goes missing in the
  move. Its data never moved: notes are the files they were.
* Boards and tasks from before Tasks was a Quill move into the record store,
  under the `board` and `task` datamodels, keeping their titles, bodies,
  lanes, order and times. The old tables stay where they are, untouched.

Both reach the network for the catalog, so both run on a thread and neither
can stop the server starting. What fails is logged and tried again at the
next boot.

On the clock: every `expire` job, swept every few minutes. Reads sweep too,
so this is only for a server nobody is looking at.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from cloudmorrow.server.db import connect
from cloudmorrow.server.quills import QuillError, QuillRegistry, load_catalog
from cloudmorrow.server.records import RecordStore, UnknownModelError

log = logging.getLogger("cloudmorrow.quills")

SWEEP_EVERY = 10 * 60.0

# schema_meta keys: set once the thing is done, so it is done once.
SEEDED = "quills_seeded"
LEGACY_TASKS = "legacy_tasks_moved"

# Features that were built into the core and are catalog Quills now, under
# the same id as the feature's key. See `adopt_builtins`.
MOVED_BUILTINS: tuple[str, ...] = ("notes",)


def read_meta(db_path: Path, key: str) -> str | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT value FROM schema_meta WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row[0] if row else None


def write_meta(db_path: Path, key: str, value: str) -> None:
    with connect(db_path) as conn:
        conn.execute("INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)", (key, value))
    conn.close()


def _legacy_rows(db_path: Path) -> bool:
    with connect(db_path) as conn:
        try:
            row = conn.execute(
                "SELECT (SELECT COUNT(*) FROM boards) + (SELECT COUNT(*) FROM tasks)"
            ).fetchone()
        except sqlite3.OperationalError:
            return False
    conn.close()
    return bool(row and row[0])


def install_foundation(db_path: Path, registry: QuillRegistry) -> list[str]:
    """The catalog's foundation Quills, on a server that has never had any."""
    if read_meta(db_path, SEEDED) or registry.quills:
        return []
    catalog = load_catalog(registry.catalog_location)
    installed = []
    for entry in catalog.quills:
        if entry.get("foundation") and entry["id"] not in registry.quills:
            registry.install_from_catalog(entry["id"], catalog)
            installed.append(entry["id"])
    write_meta(db_path, SEEDED, ",".join(installed) or "-")
    return installed


def move_legacy_tasks(db_path: Path, registry: QuillRegistry, records: RecordStore) -> int:
    """Boards and tasks from the old tables into records. Returns how many moved."""
    if read_meta(db_path, LEGACY_TASKS) or not _legacy_rows(db_path):
        return 0
    if "tasks" not in registry.quills:
        registry.install_from_catalog("tasks")
    moved = 0
    with connect(db_path) as conn:
        boards = conn.execute("SELECT * FROM boards ORDER BY id").fetchall()
        tasks = conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
        board_ids: dict[tuple[str, str], str] = {}
        for row in boards:
            title = conn.unseal("boards", "title", (row["owner"],), row["title"])
            board_ids[(row["owner"], row["slug"])] = records.import_row(
                row["owner"],
                "board",
                {"title": title},
                position=0,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                writer="tasks",
            )
            moved += 1
        for row in tasks:
            board = board_ids.get((row["owner"], row["board"]))
            if board is None:
                continue
            scope = (row["owner"],)
            records.import_row(
                row["owner"],
                "task",
                {
                    "board": board,
                    "title": conn.unseal("tasks", "title", scope, row["title"]),
                    "body": conn.unseal("tasks", "body", scope, row["body"]) or "",
                    "lane": row["lane"],
                    "done_at": row["done_at"],
                },
                position=row["position"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                writer="tasks",
            )
            moved += 1
    conn.close()
    write_meta(db_path, LEGACY_TASKS, str(moved))
    log.info("moved %d boards and tasks into the record store", moved)
    return moved


def _switched_off(db_path: Path, key: str) -> bool:
    """Did an administrator switch the feature *key* off, back when it was built in?"""
    with connect(db_path) as conn:
        try:
            row = conn.execute("SELECT enabled FROM features WHERE key = ?", (key,)).fetchone()
        except sqlite3.OperationalError:
            row = None
    conn.close()
    return row is not None and not row["enabled"]


def adopted_key(quill_id: str) -> str:
    return f"builtin_adopted:{quill_id}"


def adopt_builtins(db_path: Path, registry: QuillRegistry) -> list[str]:
    """Features that were part of the core and are Quills now, installed where they were on.

    A server from before the move had Notes as a built-in feature, on
    unless an administrator had switched it off. It gets the Quill from the
    catalog, once, and keeps its data, which never moved (a note is still a
    file). One switched off stays without it: that is the choice it made.
    The switch keeps its meaning either way, because the Quill's id is the
    feature's key.

    Once per Quill: a server whose standard quills were chosen after the
    move (`standard.choose`, the first-boot page) is marked as having
    decided, and a fresh one gets them as foundation Quills instead.
    """
    adopted = []
    for quill_id in MOVED_BUILTINS:
        key = adopted_key(quill_id)
        if read_meta(db_path, key):
            continue
        if quill_id not in registry.quills and not _switched_off(db_path, quill_id):
            registry.install_from_catalog(quill_id)
            adopted.append(quill_id)
        write_meta(db_path, key, "installed" if quill_id in registry.quills else "left out")
    if adopted:
        log.info("installed %s, which were built in before", ", ".join(adopted))
    return adopted


def boot(db_path: Path, registry: QuillRegistry, records: RecordStore) -> None:
    """The boot work, in order. Each step logs its own failure and lets the next run."""
    try:
        install_foundation(db_path, registry)
    except QuillError as exc:
        log.warning("could not install the foundation Quills yet: %s", exc)
    try:
        adopt_builtins(db_path, registry)
    except QuillError as exc:
        log.warning("could not install the Quills that were built in yet: %s", exc)
    try:
        move_legacy_tasks(db_path, registry, records)
    except (QuillError, UnknownModelError) as exc:
        log.warning("could not move the old tasks into records yet: %s", exc)


def sweep_all(registry: QuillRegistry, records: RecordStore) -> int:
    gone = 0
    for model_id in registry.expiries():
        try:
            gone += records.sweep(model_id)
        except UnknownModelError:
            continue
    return gone


class Clock:
    """A daemon thread that sweeps, and does the boot work first."""

    def __init__(self, db_path: Path, registry: QuillRegistry, records: RecordStore) -> None:
        self.db_path = db_path
        self.registry = registry
        self.records = records
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="quill-clock", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        boot(self.db_path, self.registry, self.records)
        while not self._stop.wait(SWEEP_EVERY):
            try:
                sweep_all(self.registry, self.records)
            except Exception:  # a sweep that fails is tried again next time
                log.exception("sweep failed")
