"""What this server has been told about itself from the app, kept in the
database.

The config file is the operator's, and on an installed server the service
cannot write it (`ProtectSystem=strict`). A person setting a cloud up from
the browser — on a Pi image, or a tenant somebody bought — has no file to
edit, so what they answer goes here, and wins over the file: the file is
the default, this is the decision.

Only the name lives here for now. The table is a key/value one so the next
thing does not need a migration.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from cloudmorrow.server.db import connect

TABLE = """
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    changed_by TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
"""

NAME = "name"
# Long enough for "The Larsens' cloud", short enough for a home-screen label
# and a page title. A name is text, never markup: it is escaped where shown.
NAME_MAX_LENGTH = 64


class InvalidNameError(ValueError):
    pass


def validate_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise InvalidNameError("a cloud needs a name")
    if len(cleaned) > NAME_MAX_LENGTH:
        raise InvalidNameError(f"a name is at most {NAME_MAX_LENGTH} characters")
    return cleaned


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


class SettingsStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(TABLE)

    def _connect(self) -> sqlite3.Connection:
        return connect(self.db_path)

    def get(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return default if row is None else str(row["value"])

    def set(self, key: str, value: str, *, changed_by: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO settings (key, value, changed_by, updated_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET"
                " value = excluded.value,"
                " changed_by = excluded.changed_by,"
                " updated_at = excluded.updated_at",
                (key, value, changed_by, _now()),
            )

    def name(self, default: str) -> str:
        """What this cloud is called: what somebody set in the app, else *default*."""
        return self.get(NAME) or default

    def set_name(self, name: str, *, changed_by: str = "") -> str:
        cleaned = validate_name(name)
        self.set(NAME, cleaned, changed_by=changed_by)
        return cleaned
