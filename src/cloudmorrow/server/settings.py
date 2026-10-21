"""What this server has been told about itself from the app, kept in the
database.

The config file is the operator's, and on an installed server the service
cannot write it (`ProtectSystem=strict`). A person setting a cloud up from
the browser — a tenant somebody bought — has no file to edit, so what
they answer goes here, and wins over the file: the file is the default,
this is the decision.

Only the name lives here for now. The table is a key/value one so the next
thing does not need a migration.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from cloudmorrow.server.database import Connection, Database
from cloudmorrow.server.database import open as open_database

# Made by schema.py, step 1. A change to it is a new step there.
TABLE = """
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    changed_by TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
"""

NAME = "name"
# Where the front page's weather is for: a place name, or "latitude,longitude".
# Set under Administration, Server; the server config's weather_place is only
# what it starts as, on a server nobody has told yet.
WEATHER_PLACE = "weather_place"
WEATHER_PLACE_MAX_LENGTH = 120
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
    def __init__(self, db: Database | Path) -> None:
        self.db = open_database(db)
        self._connect().close()

    def _connect(self) -> Connection:
        return self.db.connect()

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

    def weather_place(self, default: str) -> str:
        """Where the weather is for: what an administrator set, else *default* from the config.

        Set to nothing in the app and it is nothing, whatever the config says:
        a row with an empty value is an answer, a missing row is not.
        """
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (WEATHER_PLACE,)).fetchone()
        return default.strip() if row is None else str(row["value"])

    def set_weather_place(self, place: str, *, changed_by: str = "") -> str:
        cleaned = " ".join(place.split())
        if len(cleaned) > WEATHER_PLACE_MAX_LENGTH:
            raise InvalidNameError(f"a place is at most {WEATHER_PLACE_MAX_LENGTH} characters")
        self.set(WEATHER_PLACE, cleaned, changed_by=changed_by)
        return cleaned
