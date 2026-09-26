"""Which parts of Cloudmorrow this server offers, and which of them you want.

A feature is one whole area of the app — Secrets, and every installed
Quill (Notes, Tasks, Files, Calendar, Chat) — and there are two switches on
each, which are not the same kind of thing:

* **The server's**, an administrator's to throw. Off means off everywhere:
  the tab goes from every client, for everybody, and the API answers 403 to
  anything that belongs to it. It is a statement about what this server is.
* **Yours**, in your own settings. Off means the tab goes from *your*
  clients. It is a preference, so it hides rather than forbids: the API
  still answers you, because a preference that closed the door would lock
  you out of your own notes from the phone you had not told.

The two only ever narrow. A feature the server has switched off is not in
your settings at all — it is not a thing you can have an opinion about, and
offering a tick box that does nothing would be the least honest screen in
the app. So `list_for` shows what the server offers, with your answer on
each, and `enabled_for` is the two of them and'ed together.

The catalogue lives here rather than in the database: the features are
whatever this version of the code has, and the tables only remember what
somebody turned off. A feature nobody has touched is on, at either level.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from cloudmorrow.server.db import connect

TABLE = """
CREATE TABLE IF NOT EXISTS features (
    -- One row per feature somebody has switched off or on again. A feature
    -- with no row here is on: that is what a fresh server looks like.
    key        TEXT PRIMARY KEY,
    enabled    INTEGER NOT NULL DEFAULT 1,
    -- Who turned it, and when, so the panel can say so.
    changed_by TEXT    NOT NULL DEFAULT '',
    updated_at TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS user_features (
    -- The same, per person: one row per feature somebody has switched off
    -- for themselves. No row is on, so a new account has everything.
    username   TEXT    NOT NULL,
    key        TEXT    NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT    NOT NULL,
    PRIMARY KEY (username, key)
);
"""


@dataclass(frozen=True, slots=True)
class Feature:
    """One switchable area of the app."""

    key: str
    label: str
    # What goes dark when it is off, said plainly.
    description: str
    # The kinds of data it reads and writes, by key in `types.TYPES`. What
    # it provides itself is implied; what it borrows from elsewhere is the
    # thing worth declaring, because that is what the person is told.
    uses: tuple[str, ...] = ()


FEATURES: tuple[Feature, ...] = (
    Feature("secrets", "Secrets", "Vaults of keys and passwords, encrypted", ("secret",)),
)

# What each app declared, for the types catalogue to say who reaches what.
USES: dict[str, tuple[str, ...]] = {feature.key: feature.uses for feature in FEATURES}

FEATURE_KEYS: tuple[str, ...] = tuple(feature.key for feature in FEATURES)

BY_KEY: dict[str, Feature] = {feature.key: feature for feature in FEATURES}


class UnknownFeatureError(LookupError):
    pass


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


class FeatureStore:
    """What is switched on, and the switching of it."""

    def __init__(self, db_path: Path, quills: Callable[[], Iterable[Feature]] | None = None) -> None:
        self.db_path = db_path
        # The installed Quills, each one more thing to switch. Asked on every
        # call, because installing one changes the answer.
        self._quills = quills or (lambda: ())
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(TABLE)

    def _connect(self) -> sqlite3.Connection:
        return connect(self.db_path)

    def catalogue(self) -> tuple[Feature, ...]:
        """The built-in features, then every installed Quill."""
        return FEATURES + tuple(self._quills())

    def known(self, key: str) -> bool:
        return any(feature.key == key for feature in self.catalogue())

    def _switched(self) -> dict[str, sqlite3.Row]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM features").fetchall()
        return {row["key"]: row for row in rows}

    def enabled(self, key: str) -> bool:
        """Is *key* on? An unknown key is not a feature, so it is not off."""
        if not self.known(key):
            return True
        row = self._switched().get(key)
        return True if row is None else bool(row["enabled"])

    def enabled_keys(self) -> list[str]:
        switched = self._switched()
        return [
            key
            for key in (feature.key for feature in self.catalogue())
            if key not in switched or bool(switched[key]["enabled"])
        ]

    def list(self) -> list[dict]:
        """Every feature there is, in catalogue order, with its state."""
        switched = self._switched()
        listed = []
        for feature in self.catalogue():
            row = switched.get(feature.key)
            listed.append(
                {
                    "key": feature.key,
                    "label": feature.label,
                    "description": feature.description,
                    "types": list(feature.uses),
                    "enabled": True if row is None else bool(row["enabled"]),
                    "changed_by": row["changed_by"] if row else "",
                    "updated_at": row["updated_at"] if row else "",
                }
            )
        return listed

    def set(self, key: str, enabled: bool, *, changed_by: str = "") -> dict:
        if not self.known(key):
            raise UnknownFeatureError(key)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO features (key, enabled, changed_by, updated_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET"
                " enabled = excluded.enabled,"
                " changed_by = excluded.changed_by,"
                " updated_at = excluded.updated_at",
                (key, int(bool(enabled)), changed_by, _now()),
            )
        return next(row for row in self.list() if row["key"] == key)

    # -- and what each person wants of it --------------------------------------
    # The same three questions again, asked for one account. Every one of
    # them starts from the server's answer, because a feature this server
    # does not offer is not a choice anybody has.

    def _switched_off_by(self, username: str) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key FROM user_features WHERE username = ? AND enabled = 0",
                (username,),
            ).fetchall()
        return {row["key"] for row in rows}

    def enabled_for(self, username: str, key: str) -> bool:
        """Is *key* on for this person? The server's answer, then theirs."""
        if not self.enabled(key):
            return False
        return key not in self._switched_off_by(username)

    def enabled_keys_for(self, username: str) -> list[str]:
        """What this person's clients should draw a tab for."""
        off = self._switched_off_by(username)
        return [key for key in self.enabled_keys() if key not in off]

    def list_for(self, username: str) -> list[dict]:
        """What this person may switch, with their own answer on each.

        Only what the server offers: a feature an administrator has switched
        off is left out entirely rather than shown greyed, because a client
        that never hears of it cannot draw it and cannot ask about it.
        """
        off = self._switched_off_by(username)
        return [
            {
                "key": feature["key"],
                "label": feature["label"],
                "description": feature["description"],
                "enabled": feature["key"] not in off,
            }
            for feature in self.list()
            if feature["enabled"]
        ]

    def set_for(self, username: str, key: str, enabled: bool) -> dict:
        """Switch a feature for one person. Unknown, or off here, is unknown."""
        if not self.known(key) or not self.enabled(key):
            raise UnknownFeatureError(key)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO user_features (username, key, enabled, updated_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(username, key) DO UPDATE SET"
                " enabled = excluded.enabled,"
                " updated_at = excluded.updated_at",
                (username, key, int(bool(enabled)), _now()),
            )
        return next(row for row in self.list_for(username) if row["key"] == key)

    def forget(self, username: str) -> None:
        """Drop one account's answers, for when the account goes."""
        with self._connect() as conn:
            conn.execute("DELETE FROM user_features WHERE username = ?", (username,))
