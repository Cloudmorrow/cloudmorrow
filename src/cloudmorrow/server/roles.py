"""Roles: who is responsible for what, by name.

A role is a hat somebody wears — Expense Responsible, Product owner, Team
lead — and nothing more: it gives no access to any data (that is a circle's
business, circles.py) and answers one question, *who holds it*. A Quill asks
`ctx.people(role="team_lead")` and gets usernames; an approval asks the
holders of a role for a yes or a no (approvals.py); a flow asks a role
rather than a person, so the flow outlives whoever held the hat last week.

A role is held server-wide, or within one circle: the same Team lead role
is held by one person in Sales and another in Warehouse. Asked for a
circle, a role answers with the people who hold it there and the people
who hold it everywhere.

A Quill declares the roles it expects in its manifest (`[[roles]]`, with a
line of why), and they are made here, empty, the moment it is installed;
an administrator picks who holds each. Administrators make roles of their
own too. See docs/FLOWS.md.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from cloudmorrow.server.database import Connection, Database, IntegrityError, Row
from cloudmorrow.server.database import open as open_database

# Made by schema.py, step 6. A change to it is a new step there.
TABLES = """
CREATE TABLE IF NOT EXISTS roles (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    -- The Quill whose manifest declared it, or '' for one an administrator made.
    declared_by TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS role_holders (
    role_id   TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    username  TEXT NOT NULL,
    -- The circle the hat is worn in, or '' for everywhere.
    circle_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (role_id, username, circle_id)
);
"""

# `team_lead`, `expense-responsible`: what a manifest may name, and what a
# name is made into.
ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")


class RoleError(ValueError):
    pass


class UnknownRoleError(LookupError):
    pass


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


def role_id(name: str) -> str:
    """`Team lead` is `team_lead`; a manifest's `team_lead` stays as it is."""
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")[:48]


@dataclass(frozen=True, slots=True)
class Role:
    id: str
    name: str
    description: str
    declared_by: str
    # Who holds it: (username, circle id or "").
    holders: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "declared_by": self.declared_by,
            "holders": [{"username": who, "circle": circle} for who, circle in self.holders],
        }


class RoleStore:
    """The roles, and who holds each where."""

    def __init__(self, db: Database | Path) -> None:
        self.db = open_database(db)
        self.db.connect().close()

    # -- reading ---------------------------------------------------------------------
    def _load(self, conn: Connection, row: Row) -> Role:
        holders = tuple(
            (r["username"], r["circle_id"])
            for r in conn.execute(
                "SELECT username, circle_id FROM role_holders WHERE role_id = ? ORDER BY circle_id, username",
                (row["id"],),
            )
        )
        return Role(row["id"], row["name"], row["description"], row["declared_by"], holders)

    def _find(self, conn: Connection, key: str) -> Row:
        key = key.strip()
        row = conn.execute("SELECT * FROM roles WHERE id = ? OR lower(name) = lower(?)", (role_id(key), key)).fetchone()
        if row is None:
            raise UnknownRoleError(key)
        return row

    def list(self) -> list[Role]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM roles ORDER BY lower(name)").fetchall()
            return [self._load(conn, row) for row in rows]

    def get(self, key: str) -> Role:
        with self.db.connect() as conn:
            return self._load(conn, self._find(conn, key))

    def people(self, role: str, circle: str = "") -> list[str]:
        """Who holds *role*: everywhere, and in *circle* when one is named.
        A role nobody has heard of is held by nobody."""
        with self.db.connect() as conn:
            try:
                found = self._find(conn, role)["id"]
            except UnknownRoleError:
                return []
            circle_id = self._circle(conn, circle) if circle else ""
            rows = conn.execute(
                "SELECT DISTINCT username FROM role_holders WHERE role_id = ? AND circle_id IN ('', ?)"
                " ORDER BY username",
                (found, circle_id),
            ).fetchall()
        return [r["username"] for r in rows]

    def holds(self, username: str, role: str, circle: str = "") -> bool:
        return username.strip().lower() in self.people(role, circle)

    def roles_of(self, username: str) -> list[dict]:
        """The hats one person wears: `[{"id": "team_lead", "name": "Team lead", "circle": ""}]`."""
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT r.id, r.name, h.circle_id FROM role_holders h JOIN roles r ON r.id = h.role_id"
                " WHERE h.username = ? ORDER BY lower(r.name), h.circle_id",
                (username.strip().lower(),),
            ).fetchall()
        return [{"id": r["id"], "name": r["name"], "circle": r["circle_id"]} for r in rows]

    # -- changing --------------------------------------------------------------------
    def create(self, name: str, description: str = "", *, declared_by: str = "", id: str = "") -> Role:  # noqa: A002
        name = name.strip()
        found_id = (id or role_id(name)).strip()
        if not name or not ID_RE.match(found_id):
            raise RoleError("a role needs a name with a letter or a digit in it")
        try:
            with self.db.connect() as conn:
                conn.execute(
                    "INSERT INTO roles (id, name, description, declared_by, created_at) VALUES (?, ?, ?, ?, ?)",
                    (found_id, name, description.strip(), declared_by, _now()),
                )
        except IntegrityError as exc:
            raise RoleError(f"there is already a role called {name}") from exc
        return self.get(found_id)

    def update(self, key: str, *, name: str | None = None, description: str | None = None) -> Role:
        with self.db.connect() as conn:
            found = self._find(conn, key)["id"]
            if name is not None and name.strip():
                try:
                    conn.execute("UPDATE roles SET name = ? WHERE id = ?", (name.strip(), found))
                except IntegrityError as exc:
                    raise RoleError(f"there is already a role called {name}") from exc
            if description is not None:
                conn.execute("UPDATE roles SET description = ? WHERE id = ?", (description.strip(), found))
        return self.get(found)

    def delete(self, key: str) -> None:
        with self.db.connect() as conn:
            found = self._find(conn, key)["id"]
            conn.execute("DELETE FROM role_holders WHERE role_id = ?", (found,))
            conn.execute("DELETE FROM roles WHERE id = ?", (found,))

    @staticmethod
    def _circle(conn: Connection, circle: str) -> str:
        circle = circle.strip()
        if not circle:
            return ""
        row = conn.execute(
            "SELECT id FROM circles WHERE id = ? OR lower(name) = lower(?)", (circle.lower(), circle)
        ).fetchone()
        if row is None:
            raise RoleError(f"there is no circle called {circle}")
        return row["id"]

    def give(self, key: str, username: str, circle: str = "") -> Role:
        """Put the hat on somebody: everywhere, or within one circle."""
        username = username.strip().lower()
        with self.db.connect() as conn:
            found = self._find(conn, key)["id"]
            if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone() is None:
                raise RoleError(f"there is nobody called {username} on this server")
            circle_id = self._circle(conn, circle)
            conn.execute(
                "INSERT INTO role_holders (role_id, username, circle_id) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                (found, username, circle_id),
            )
        return self.get(found)

    def take(self, key: str, username: str, circle: str = "") -> Role:
        """Take the hat off somebody, where they wore it."""
        with self.db.connect() as conn:
            found = self._find(conn, key)["id"]
            circle_id = self._circle(conn, circle) if circle else ""
            conn.execute(
                "DELETE FROM role_holders WHERE role_id = ? AND username = ? AND circle_id = ?",
                (found, username.strip().lower(), circle_id),
            )
        return self.get(found)

    def forget(self, username: str) -> None:
        """An account that is gone wears no hats."""
        with self.db.connect() as conn:
            conn.execute("DELETE FROM role_holders WHERE username = ?", (username.strip().lower(),))

    def forget_circle(self, circle_id: str) -> None:
        """A circle that is gone: the hats worn in it come off."""
        with self.db.connect() as conn:
            conn.execute("DELETE FROM role_holders WHERE circle_id = ?", (circle_id,))

    # -- what Quills declare ---------------------------------------------------------------
    def declare(self, manifests: Iterable) -> list[str]:
        """The roles the installed Quills' manifests name, made where missing,
        with nobody in them yet. Returns the ids made."""
        made = []
        with self.db.connect() as conn:
            for manifest in manifests:
                for spec in getattr(manifest, "roles", ()):
                    if conn.execute("SELECT 1 FROM roles WHERE id = ?", (spec["id"],)).fetchone() is not None:
                        continue
                    name = spec.get("label") or spec["id"].replace("_", " ").capitalize()
                    if conn.execute("SELECT 1 FROM roles WHERE lower(name) = lower(?)", (name,)).fetchone():
                        name = f"{name} ({manifest.id})"
                    conn.execute(
                        "INSERT INTO roles (id, name, description, declared_by, created_at) VALUES (?, ?, ?, ?, ?)",
                        (spec["id"], name, str(spec.get("why", "")), manifest.id, _now()),
                    )
                    made.append(spec["id"])
        return made
