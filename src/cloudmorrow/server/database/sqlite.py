"""SQLite: the default engine. One file, a connection per call.

What is SQLite's alone lives here: write-ahead mode and the busy wait, the
log folded back on the clock (`checkpoint`), the version in
`PRAGMA user_version`, `rowid`, and `json_extract`.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path

from cloudmorrow.server.database import (
    DatabaseError,
    Dialect,
    Engine,
    IntegrityError,
    OperationalError,
)

# How long a connection waits for another's write to finish before giving
# up with "database is locked". Every call opens its own connection, so
# under load a few are always waiting on one that is writing.
BUSY_SECONDS = 10.0
# How big the write-ahead log may stay after a checkpoint, in bytes.
WAL_SIZE_LIMIT = 64 * 1024 * 1024


class SQLiteDialect(Dialect):
    name = "sqlite"
    row_address = "rowid"

    def ddl(self, sql: str) -> str:
        # The key SQLite hands out is its own word already.
        sql = re.sub(r"^(\s*\w+\s+)JSON\b", r"\1TEXT", sql, flags=re.MULTILINE)
        return re.sub(r"\bINTEGER AUTONUMBER\b", "INTEGER", sql)

    def json_text(self, column: str, field: str) -> str:
        # json_extract answers a number for a number and text for text;
        # both compare as themselves. NULL for a missing field and for null.
        return f"json_extract({column}, '$.\"{field}\"')"

    def json_compare(self, column: str, field: str, op: str, value: object) -> tuple[str, list[object]]:
        # A JSON true reads as 1 here.
        if isinstance(value, bool):
            value = int(value)
        return f"{self.json_text(column, field)} {op} ?", [value]

    def next_number(self, table: str, column: str) -> str:
        # One writer at a time, so the next number is the one after the last.
        return f"(SELECT COALESCE(MAX({column}), 0) + 1 FROM {table})"


class SQLiteEngine(Engine):
    name = "sqlite"
    dialect = SQLiteDialect()
    checks_every_connect = True

    def __init__(self, path: Path) -> None:
        self.path = path

    def acquire(self) -> sqlite3.Connection:
        raw = sqlite3.connect(self.path, timeout=BUSY_SECONDS)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys = ON")
        # Write-ahead logging: a write no longer blocks every read, which is
        # what lets the request threads overlap instead of queueing on one
        # writer. It is a property of the file, so setting it again is free.
        # NORMAL loses at most the last transactions to a power cut, never
        # the file's integrity, and makes each write a fraction of the cost.
        raw.execute("PRAGMA journal_mode = WAL")
        raw.execute("PRAGMA synchronous = NORMAL")
        # The log is folded back into the file as it goes (SQLite's own
        # checkpointing), but it can only be cut back when no connection is
        # reading, which under load is seldom: `checkpoint` below is called
        # on the clock for that. This keeps the file from staying large.
        raw.execute(f"PRAGMA journal_size_limit = {WAL_SIZE_LIMIT}")
        return raw

    def release(self, raw: sqlite3.Connection) -> None:
        # Closed at once, not left to the cyclic collector: the standard
        # connection's statement cache points back at it, so under load
        # hundreds sat open, each with its page cache, until a collection
        # ran — the server grew by the gigabyte. Closed, the native side goes.
        raw.close()

    def execute(self, raw: sqlite3.Connection, sql: str, params: Sequence[object]) -> sqlite3.Cursor:
        return raw.execute(sql, params)

    def executemany(self, raw: sqlite3.Connection, sql: str, rows: Iterable[Sequence[object]]) -> None:
        raw.executemany(sql, rows)

    def executescript(self, raw: sqlite3.Connection, script: str) -> None:
        raw.executescript(script)

    def insert(self, raw: sqlite3.Connection, sql: str, params: Sequence[object], key: str) -> int:
        return int(raw.execute(sql, params).lastrowid)

    def lock(self, raw: sqlite3.Connection) -> None:
        raw.execute("BEGIN IMMEDIATE")

    def schema_version(self, raw: sqlite3.Connection) -> int:
        return int(raw.execute("PRAGMA user_version").fetchone()[0])

    def set_schema_version(self, raw: sqlite3.Connection, version: int) -> None:
        # A pragma takes no parameters; the version is an int of ours.
        raw.execute(f"PRAGMA user_version = {int(version)}")

    def table_exists(self, raw: sqlite3.Connection, name: str) -> bool:
        row = raw.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone()
        return row is not None

    def columns(self, raw: sqlite3.Connection, table: str) -> set[str]:
        return {row["name"] for row in raw.execute(f"PRAGMA table_info({table})")}

    def in_transaction(self, raw: sqlite3.Connection) -> bool:
        return bool(raw.in_transaction)

    def translate(self, exc: BaseException) -> DatabaseError | None:
        if isinstance(exc, sqlite3.IntegrityError):
            return IntegrityError(str(exc))
        if isinstance(exc, sqlite3.OperationalError):
            return OperationalError(str(exc))
        if isinstance(exc, sqlite3.Error):
            return DatabaseError(str(exc))
        return None

    def checkpoint(self) -> bool:
        """Fold the write-ahead log into the database and cut it back to nothing.

        SQLite does this by itself every thousand pages, but can only
        truncate the log when nobody is reading, and a busy server always
        has somebody reading: left alone, the log grows and every read gets
        slower for it. Returns whether it got the lock in time; a miss is
        tried again next time.
        """
        try:
            raw = sqlite3.connect(self.path, timeout=2.0)
        except sqlite3.Error:
            return False
        try:
            busy, _log, _moved = raw.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            return busy == 0
        except sqlite3.OperationalError:
            return False
        finally:
            raw.close()
