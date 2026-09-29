"""Circles: who on this server may use which kinds of data.

A circle is a named set of people — Parents, Kids, Sales — and, per
datamodel, what they may do with it: `write`, `read`, or `none`. Your access
to a datamodel is the most any of your circles gives; inside one circle a
named rule beats `*`. There is no deny, so "why can't I see this?" always
has one answer: none of your circles has it. See docs/CIRCLES.md.

This decides which *kinds* of data somebody reaches. Which *records* of
them is the scope's business, as it always was (records.py): a circle with
`write` on `expense` does not open anybody's personal expenses.

A fresh database gets one circle, Members, with `* = write`, as the
default, with every account there is in it — so a server that has never
heard of circles behaves as it always did until an administrator says
otherwise.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from cloudmorrow.server.db import connect
from cloudmorrow.server.slugs import slugify

WRITE = "write"
READ = "read"
NONE = "none"
ACCESS: tuple[str, ...] = (WRITE, READ, NONE)
EVERY = "*"
_RANK = {NONE: 0, READ: 1, WRITE: 2}

DEFAULT_NAME = "Members"

TABLE = """
CREATE TABLE IF NOT EXISTS circles (
    id         TEXT PRIMARY KEY,
    name       TEXT    NOT NULL UNIQUE,
    -- Where a new account goes. More than one may be.
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS circle_members (
    circle_id TEXT NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
    username  TEXT NOT NULL,
    PRIMARY KEY (circle_id, username)
);
CREATE TABLE IF NOT EXISTS circle_rules (
    circle_id TEXT NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
    -- A datamodel id, or '*' for every datamodel, later ones too.
    model     TEXT NOT NULL,
    -- 'write', 'read' or 'none'. 'none' only means something beside a '*'.
    access    TEXT NOT NULL,
    PRIMARY KEY (circle_id, model)
);
"""


class CircleError(ValueError):
    pass


class UnknownCircleError(LookupError):
    pass


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


def validate_access(access: str) -> str:
    access = str(access).strip().lower()
    if access not in ACCESS:
        raise CircleError(f"access is write, read or none, not {access!r}")
    return access


def _rank(access: str | None) -> int:
    return _RANK.get(access or NONE, 0)


def level(rules: Mapping[str, str], model: str) -> str:
    """What one circle's *rules* give on *model*: its own line, else `*`, else none."""
    return rules.get(model) or rules.get(EVERY) or NONE


@dataclass(frozen=True, slots=True)
class Access:
    """What one person may do with each datamodel: the most any of their circles gives."""

    username: str
    # Each of their circles' rules, by circle name.
    circles: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

    def level(self, model: str) -> str:
        best = NONE
        for rules in self.circles.values():
            found = level(rules, model)
            if _rank(found) > _rank(best):
                best = found
        return best

    def may(self, action: str, model: str) -> bool:
        """*action* is `read` or `write`; write needs write, read needs either."""
        return _rank(self.level(model)) >= _rank(action)

    def of(self, models: Iterable[str]) -> dict[str, str]:
        """{model: access} for every one of *models* reached at all."""
        out = {}
        for model in models:
            found = self.level(model)
            if found != NONE:
                out[model] = found
        return out


# Nobody in any circle, or somebody the store has never heard of.
NOBODY = Access("")


@dataclass(frozen=True, slots=True)
class Circle:
    id: str
    name: str
    is_default: bool
    rules: dict[str, str]
    members: list[str]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "default": self.is_default,
            "rules": dict(self.rules),
            "members": list(self.members),
        }


def ensure(conn: sqlite3.Connection) -> None:
    """The tables, and — the first time they are made — Members, with everybody in it."""
    present = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'circles'").fetchone()
    if present:
        return
    conn.executescript(TABLE)
    circle_id = slugify(DEFAULT_NAME)
    conn.execute(
        "INSERT INTO circles (id, name, is_default, created_at) VALUES (?, ?, 1, ?)",
        (circle_id, DEFAULT_NAME, _now()),
    )
    conn.execute(
        "INSERT INTO circle_rules (circle_id, model, access) VALUES (?, ?, ?)",
        (circle_id, EVERY, WRITE),
    )
    has_users = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users'").fetchone()
    if has_users:
        conn.execute(
            "INSERT INTO circle_members (circle_id, username) SELECT ?, username FROM users",
            (circle_id,),
        )
    conn.commit()


class CircleStore:
    """The circles, their rules and their people, and what that adds up to per person."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        with self._connect():
            pass

    def _connect(self) -> sqlite3.Connection:
        # `connect` makes the tables (and Members) through `ensure`.
        return connect(self.db_path)

    # -- reading ---------------------------------------------------------------
    def _load(self, conn: sqlite3.Connection, row: sqlite3.Row) -> Circle:
        rules = {
            r["model"]: r["access"]
            for r in conn.execute(
                "SELECT model, access FROM circle_rules WHERE circle_id = ? ORDER BY model",
                (row["id"],),
            )
        }
        members = [
            r["username"]
            for r in conn.execute(
                "SELECT username FROM circle_members WHERE circle_id = ? ORDER BY username",
                (row["id"],),
            )
        ]
        return Circle(row["id"], row["name"], bool(row["is_default"]), rules, members)

    def list(self) -> list[Circle]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM circles ORDER BY name COLLATE NOCASE").fetchall()
            return [self._load(conn, row) for row in rows]

    def _find(self, conn: sqlite3.Connection, key: str) -> sqlite3.Row:
        """A circle by its id or its name, either case."""
        key = key.strip()
        row = conn.execute(
            "SELECT * FROM circles WHERE id = ? OR name = ? COLLATE NOCASE",
            (key.lower(), key),
        ).fetchone()
        if row is None:
            raise UnknownCircleError(key)
        return row

    def get(self, key: str) -> Circle:
        with self._connect() as conn:
            return self._load(conn, self._find(conn, key))

    def circles_of(self, username: str) -> list[Circle]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT c.* FROM circles c JOIN circle_members m ON m.circle_id = c.id"
                " WHERE m.username = ? ORDER BY c.name COLLATE NOCASE",
                (username,),
            ).fetchall()
            return [self._load(conn, row) for row in rows]

    def access_for(self, username: str) -> Access:
        """What *username* may do with each datamodel. Asked on every read and write."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT c.name, r.model, r.access FROM circle_members m"
                " JOIN circles c ON c.id = m.circle_id"
                " LEFT JOIN circle_rules r ON r.circle_id = c.id"
                " WHERE m.username = ?",
                (username,),
            ).fetchall()
        circles: dict[str, dict[str, str]] = {}
        for row in rows:
            rules = circles.setdefault(row["name"], {})
            if row["model"] is not None:
                rules[row["model"]] = row["access"]
        return Access(username, circles)

    # -- changing --------------------------------------------------------------
    def create(
        self,
        name: str,
        rules: Mapping[str, str] | None = None,
        members: Iterable[str] = (),
        *,
        default: bool = False,
    ) -> Circle:
        name = name.strip()
        circle_id = slugify(name)
        if not circle_id:
            raise CircleError("a circle needs a name with a letter or a digit in it")
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO circles (id, name, is_default, created_at) VALUES (?, ?, ?, ?)",
                    (circle_id, name, int(default), _now()),
                )
                self._set_rules(conn, circle_id, rules or {})
                for username in members:
                    self._join(conn, circle_id, username)
        except sqlite3.IntegrityError as exc:
            raise CircleError(f"there is already a circle called {name}") from exc
        return self.get(circle_id)

    @staticmethod
    def _set_rules(conn: sqlite3.Connection, circle_id: str, rules: Mapping[str, str]) -> None:
        conn.execute("DELETE FROM circle_rules WHERE circle_id = ?", (circle_id,))
        for model, access in rules.items():
            model = str(model).strip()
            if not model:
                raise CircleError("a rule needs a datamodel, or * for every one")
            conn.execute(
                "INSERT INTO circle_rules (circle_id, model, access) VALUES (?, ?, ?)",
                (circle_id, model, validate_access(access)),
            )

    @staticmethod
    def _join(conn: sqlite3.Connection, circle_id: str, username: str) -> None:
        user = conn.execute("SELECT 1 FROM users WHERE username = ?", (username.strip().lower(),)).fetchone()
        if user is None:
            raise CircleError(f"there is nobody called {username} on this server")
        conn.execute(
            "INSERT OR IGNORE INTO circle_members (circle_id, username) VALUES (?, ?)",
            (circle_id, username.strip().lower()),
        )

    def update(
        self,
        key: str,
        *,
        name: str | None = None,
        rules: Mapping[str, str] | None = None,
        default: bool | None = None,
    ) -> Circle:
        with self._connect() as conn:
            circle_id = self._find(conn, key)["id"]
            if name is not None and name.strip():
                try:
                    conn.execute("UPDATE circles SET name = ? WHERE id = ?", (name.strip(), circle_id))
                except sqlite3.IntegrityError as exc:
                    raise CircleError(f"there is already a circle called {name}") from exc
            if rules is not None:
                self._set_rules(conn, circle_id, rules)
            if default is not None:
                conn.execute("UPDATE circles SET is_default = ? WHERE id = ?", (int(default), circle_id))
        return self.get(circle_id)

    def set_rule(self, key: str, model: str, access: str) -> Circle:
        """One line of a circle. `none` on a named datamodel stays, because it beats a `*`;
        `none` on `*` is the same as no `*` line, so it goes."""
        access = validate_access(access)
        model = model.strip()
        if not model:
            raise CircleError("a rule needs a datamodel, or * for every one")
        with self._connect() as conn:
            circle_id = self._find(conn, key)["id"]
            if model == EVERY and access == NONE:
                conn.execute(
                    "DELETE FROM circle_rules WHERE circle_id = ? AND model = ?",
                    (circle_id, model),
                )
            else:
                conn.execute(
                    "INSERT INTO circle_rules (circle_id, model, access) VALUES (?, ?, ?)"
                    " ON CONFLICT (circle_id, model) DO UPDATE SET access = excluded.access",
                    (circle_id, model, access),
                )
        return self.get(circle_id)

    def delete(self, key: str) -> None:
        with self._connect() as conn:
            circle_id = self._find(conn, key)["id"]
            conn.execute("DELETE FROM circles WHERE id = ?", (circle_id,))

    def join(self, key: str, username: str) -> Circle:
        with self._connect() as conn:
            circle_id = self._find(conn, key)["id"]
            self._join(conn, circle_id, username)
        return self.get(circle_id)

    def leave(self, key: str, username: str) -> Circle:
        with self._connect() as conn:
            circle_id = self._find(conn, key)["id"]
            conn.execute(
                "DELETE FROM circle_members WHERE circle_id = ? AND username = ?",
                (circle_id, username.strip().lower()),
            )
        return self.get(circle_id)
