"""The user store.

Deliberately plain SQL through the database layer (database/): one server
does not need an ORM, and keeping the schema visible (schema.py) makes it
easy to add system-user linkage later.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

from cloudmorrow.server.database import Connection, Database, IntegrityError, Row
from cloudmorrow.server.database import open as open_database

USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

# What an account is allowed to do. The column is text rather than a flag
# because the next role is always a matter of time.
ROLE_ADMIN = "administrator"
ROLE_USER = "user"
# A screen on a shared wall: it may show dashboards, and nothing else.
ROLE_DASHBOARD = "dashboard_displayer"
ROLES: tuple[str, ...] = (ROLE_ADMIN, ROLE_USER, ROLE_DASHBOARD)

# What kind of thing is behind the account, which is not the same question as
# what it may do. A human signs in and types; an agent is a program acting for
# someone; a systems user is the machinery itself — a screen in the hallway, a
# service — with nobody behind it.
TYPE_HUMAN = "human"
TYPE_AGENT = "agent"
TYPE_SYSTEM = "systems_user"
USER_TYPES: tuple[str, ...] = (TYPE_HUMAN, TYPE_AGENT, TYPE_SYSTEM)


class UserExistsError(ValueError):
    pass


class UnknownUserError(LookupError):
    pass


class InvalidUsernameError(ValueError):
    pass


class InvalidRoleError(ValueError):
    pass


@dataclass(slots=True)
class User:
    id: int
    username: str
    display_name: str
    password_hash: str
    # What the account may do, and what is behind it.
    role: str
    user_type: str
    # role == ROLE_ADMIN, kept as a column so the checks that read it need
    # not know about roles at all.
    is_admin: bool
    is_active: bool
    system_uid: int | None
    created_at: str
    updated_at: str


def _row_to_user(row: Row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        password_hash=row["password_hash"],
        role=row["role"],
        user_type=row["user_type"],
        is_admin=bool(row["is_admin"]),
        is_active=bool(row["is_active"]),
        system_uid=row["system_uid"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


def validate_role(role: str) -> str:
    role = str(role).strip().lower()
    if role not in ROLES:
        raise InvalidRoleError(f"role must be one of: {', '.join(ROLES)}")
    return role


def validate_user_type(user_type: str) -> str:
    user_type = str(user_type).strip().lower()
    if user_type not in USER_TYPES:
        raise InvalidRoleError(f"user type must be one of: {', '.join(USER_TYPES)}")
    return user_type


def validate_username(username: str) -> str:
    username = username.strip().lower()
    if not USERNAME_RE.match(username):
        raise InvalidUsernameError(
            "username must be 1-32 chars: lowercase letters, digits, '_' or '-', starting with a letter or '_'"
        )
    return username


class UserStore:
    """Thin repository over the users table."""

    def __init__(self, db: Database | Path) -> None:
        self.db = open_database(db)
        self._connect().close()

    def _connect(self) -> Connection:
        return self.db.connect()

    def count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"])

    def get(self, username: str) -> User | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip().lower(),)).fetchone()
        return _row_to_user(row) if row else None

    def require(self, username: str) -> User:
        user = self.get(username)
        if user is None:
            raise UnknownUserError(username)
        return user

    def list(self) -> list[User]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY username").fetchall()
        return [_row_to_user(row) for row in rows]

    def create(
        self,
        username: str,
        password_hash: str,
        *,
        display_name: str = "",
        is_admin: bool = False,
        role: str | None = None,
        user_type: str = TYPE_HUMAN,
        system_uid: int | None = None,
    ) -> User:
        """Make an account. *role* wins over *is_admin* when both are given."""
        username = validate_username(username)
        role = validate_role(role) if role is not None else (ROLE_ADMIN if is_admin else ROLE_USER)
        user_type = validate_user_type(user_type)
        now = _now()
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO users (username, display_name, password_hash, role,"
                    " user_type, is_admin, is_active, system_uid, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                    (
                        username,
                        display_name,
                        password_hash,
                        role,
                        user_type,
                        int(role == ROLE_ADMIN),
                        system_uid,
                        now,
                        now,
                    ),
                )
                # Into the default circles, so a new account has what they give.
                conn.execute(
                    "INSERT INTO circle_members (circle_id, username)"
                    " SELECT id, ? FROM circles WHERE is_default = 1 ON CONFLICT DO NOTHING",
                    (username,),
                )
        except IntegrityError as exc:
            raise UserExistsError(username) from exc
        return self.require(username)

    def update(self, username: str, **fields: object) -> User:
        allowed = {
            "display_name",
            "password_hash",
            "role",
            "user_type",
            "is_admin",
            "is_active",
            "system_uid",
        }
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return self.require(username)
        if "role" in updates:
            updates["role"] = validate_role(str(updates["role"]))
            # The flag follows the role, never the other way round.
            updates["is_admin"] = updates["role"] == ROLE_ADMIN
        elif "is_admin" in updates:
            updates["role"] = ROLE_ADMIN if updates["is_admin"] else ROLE_USER
        if "user_type" in updates:
            updates["user_type"] = validate_user_type(str(updates["user_type"]))
        for flag in ("is_admin", "is_active"):
            if flag in updates:
                updates[flag] = int(bool(updates[flag]))
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE users SET {assignments}, updated_at = ? WHERE username = ?",
                (*updates.values(), _now(), username.strip().lower()),
            )
            if cursor.rowcount == 0:
                raise UnknownUserError(username)
        return self.require(username)

    def delete(self, username: str) -> None:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM users WHERE username = ?", (username.strip().lower(),))
            if cursor.rowcount == 0:
                raise UnknownUserError(username)
            conn.execute("DELETE FROM circle_members WHERE username = ?", (username.strip().lower(),))
