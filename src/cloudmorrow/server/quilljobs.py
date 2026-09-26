"""What the core does for Quills without being asked: at boot, and on a clock.

At boot:

* A server that has never had a Quill installed gets the catalog's
  foundation Quills — the ones marked `foundation = true` — so a fresh
  install has Tasks the way it always had. Once; after that, what is
  installed is the administrator's business.
* Boards and tasks from before Tasks was a Quill move into the record store,
  under the `board` and `task` datamodels, keeping their titles, bodies,
  lanes, order and times. The old tables stay where they are, untouched.
* Channels and messages from before Chat was a Quill do the same, under
  `channel` and `message`: who made each, its kind, topic and people, who
  said what and when, and how far each person had read. A server that had
  Chat — anybody's server with accounts on it — gets the Quill installed,
  switched on or off as the feature was, since the switch has the same name.

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
LEGACY_CHAT = "legacy_chat_moved"


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


def _has_rows(db_path: Path, query: str) -> bool:
    with connect(db_path) as conn:
        try:
            row = conn.execute(query).fetchone()
        except sqlite3.OperationalError:
            row = None
    conn.close()
    return bool(row and row[0])


# Where each old kind of channel lands: its scope, and the `kind` it keeps.
CHAT_SCOPES = {"public": "public", "private": "shared", "direct": "shared"}


def move_legacy_chat(db_path: Path, registry: QuillRegistry, records: RecordStore) -> int:
    """Channels and messages from the old tables into records. Returns how many moved.

    Installs the Chat Quill first on a server that had Chat: one with old
    channels, or with accounts at all — a server nobody has signed in to yet
    is still being set up, and its choice of Quills is the installer's.
    """
    if read_meta(db_path, LEGACY_CHAT):
        return 0
    legacy = _has_rows(db_path, "SELECT COUNT(*) FROM chat_channels")
    if "chat" not in registry.quills:
        if not legacy and not _has_rows(db_path, "SELECT COUNT(*) FROM users"):
            write_meta(db_path, LEGACY_CHAT, "-")
            return 0
        registry.install_from_catalog("chat")
    moved = 0
    with connect(db_path) as conn:
        channels = conn.execute("SELECT * FROM chat_channels ORDER BY id").fetchall() if legacy else []
        for row in channels:
            people = conn.execute(
                "SELECT * FROM chat_members WHERE channel_id = ? ORDER BY joined_at, username",
                (row["id"],),
            ).fetchall()
            names = [p["username"] for p in people]
            kind = row["kind"] if row["kind"] in CHAT_SCOPES else "private"
            scope = CHAT_SCOPES[kind]
            # Whoever made it keeps it, while they are still in it; a private
            # channel its maker left is its longest member's.
            owner = row["created_by"]
            if scope == "shared" and owner not in names and names:
                owner = names[0]
            owner = owner or (names[0] if names else "")
            if not owner:
                continue
            topic = conn.unseal("chat_channels", "topic", (row["slug"],), row["topic"]) or ""
            name = row["name"] or row["slug"]
            if kind == "direct":
                name = " & ".join(sorted(names)) or name
            space = records.import_row(
                owner,
                "channel",
                {"name": name, "kind": kind, "topic": topic},
                position=0,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                writer="chat",
                scope=scope,
                members=[who for who in names if who != owner] if scope == "shared" else (),
            )
            moved += 1
            messages = conn.execute(
                "SELECT * FROM chat_messages WHERE channel_id = ? ORDER BY id", (row["id"],)
            ).fetchall()
            said_at: dict[int, str] = {}
            for message in messages:
                body = conn.unseal("chat_messages", "body", (row["id"],), message["body"]) or ""
                records.import_row(
                    message["author"],
                    "message",
                    {"channel": space, "body": body, "sent_at": message["created_at"]},
                    position=0,
                    created_at=message["created_at"],
                    updated_at=message["edited_at"] or message["created_at"],
                    writer="chat",
                )
                said_at[message["id"]] = message["created_at"]
                moved += 1
            # How far each person had read: the moment of the last message
            # they had seen, so what came after it is still unread.
            for person in people:
                if person["last_read"] and person["last_read"] in said_at:
                    records.import_seen(space, person["username"], said_at[person["last_read"]])
                elif person["last_read"] and said_at:
                    # Their mark is past a message since deleted: everything
                    # before it was read.
                    earlier = [at for mid, at in said_at.items() if mid <= person["last_read"]]
                    if earlier:
                        records.import_seen(space, person["username"], max(earlier))
    conn.close()
    write_meta(db_path, LEGACY_CHAT, str(moved))
    log.info("moved %d channels and messages into the record store", moved)
    return moved


def boot(db_path: Path, registry: QuillRegistry, records: RecordStore) -> None:
    """The boot work, in order. Each step logs its own failure and lets the next run."""
    try:
        install_foundation(db_path, registry)
    except QuillError as exc:
        log.warning("could not install the foundation Quills yet: %s", exc)
    try:
        move_legacy_tasks(db_path, registry, records)
    except (QuillError, UnknownModelError) as exc:
        log.warning("could not move the old tasks into records yet: %s", exc)
    try:
        move_legacy_chat(db_path, registry, records)
    except (QuillError, UnknownModelError) as exc:
        log.warning("could not move the old chat into records yet: %s", exc)


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
