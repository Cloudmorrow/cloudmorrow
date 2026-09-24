"""SQLite-backed user store.

Deliberately plain sqlite3: one server does not need an ORM, and keeping the
schema visible here makes it easy to add system-user linkage later.
"""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from cloudmorrow.server.sealed import Sealer, sealer_for
from cloudmorrow.server.sealed import migrate as migrate_sealing

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

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    display_name  TEXT    NOT NULL DEFAULT '',
    password_hash TEXT    NOT NULL,
    -- 'administrator', 'user' or 'dashboard_displayer'. is_admin is kept in
    -- step with it, so the flag every owner check already reads stays true.
    role          TEXT    NOT NULL DEFAULT 'user',
    -- 'human', 'agent' or 'systems_user'.
    user_type     TEXT    NOT NULL DEFAULT 'human',
    is_admin      INTEGER NOT NULL DEFAULT 0,
    is_active     INTEGER NOT NULL DEFAULT 1,
    -- Reserved for mapping a Cloudmorrow account onto a real system account.
    system_uid    INTEGER,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS agents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    owner        TEXT    NOT NULL,
    name         TEXT    NOT NULL,
    token_hash   TEXT    NOT NULL UNIQUE,
    hostname     TEXT    NOT NULL DEFAULT '',
    platform     TEXT    NOT NULL DEFAULT '',
    version      TEXT    NOT NULL DEFAULT '',
    -- Capabilities the agent reports at enrolment, comma separated.
    capabilities TEXT    NOT NULL DEFAULT '',
    -- Config bundles this machine keeps in step with the others, comma
    -- separated. Set from the TUI; the agent reads it off its heartbeat.
    sync_bundles TEXT    NOT NULL DEFAULT '',
    -- Where this agent serves its machine shares, from its last heartbeat.
    dav_base     TEXT    NOT NULL DEFAULT '',
    last_seen    TEXT,
    enrolled_at  TEXT    NOT NULL,
    UNIQUE (owner, name)
);
CREATE TABLE IF NOT EXISTS enrollment_tokens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner      TEXT    NOT NULL,
    token_hash TEXT    NOT NULL UNIQUE,
    label      TEXT    NOT NULL DEFAULT '',
    expires_at TEXT    NOT NULL,
    used_at    TEXT,
    created_at TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id     INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    owner        TEXT    NOT NULL,
    -- Kept from when a job could belong to a project. Always NULL now.
    project      TEXT,
    type         TEXT    NOT NULL,
    payload      TEXT    NOT NULL DEFAULT '{}',
    status       TEXT    NOT NULL DEFAULT 'queued',
    result       TEXT,
    created_at   TEXT    NOT NULL,
    started_at   TEXT,
    finished_at  TEXT
);
CREATE INDEX IF NOT EXISTS jobs_agent_status ON jobs (agent_id, status);
CREATE TABLE IF NOT EXISTS secrets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    owner        TEXT    NOT NULL,
    -- The vault the secret is in: `default` unless the person named one.
    -- Not NULL, because SQLite treats NULLs as distinct and the UNIQUE
    -- below would stop catching duplicates.
    vault        TEXT    NOT NULL DEFAULT 'default',
    environment  TEXT    NOT NULL,
    name         TEXT    NOT NULL,
    -- The value, encrypted. Everything else here is in the clear.
    sealed       TEXT    NOT NULL,
    -- Keyed digest of the value, so two of them can be compared without
    -- opening either, and value_length for showing something in a list.
    fingerprint  TEXT    NOT NULL DEFAULT '',
    value_length INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL,
    UNIQUE (owner, vault, environment, name)
);
CREATE INDEX IF NOT EXISTS secrets_scope ON secrets (owner, vault, environment);
CREATE TABLE IF NOT EXISTS shares (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    owner       TEXT    NOT NULL,
    -- The share's id: the last segment of its WebDAV URL, and what you mount.
    name        TEXT    NOT NULL,
    -- The directory on the server it publishes, absolute.
    path        TEXT    NOT NULL,
    -- 1 when the directory is the share's folder in the owner's Shares
    -- directory, and so may go with the share. 0 only for a share made
    -- before shares lived there, pointed at a directory elsewhere, which
    -- is never deleted from here.
    managed     INTEGER NOT NULL DEFAULT 1,
    -- 'server': the directory is on the server. 'machine': it is on one of
    -- the owner's machines, and agent_id says which agent serves it.
    kind        TEXT    NOT NULL DEFAULT 'server',
    agent_id    INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    description TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL,
    UNIQUE (owner, name)
);
CREATE TABLE IF NOT EXISTS boards (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner      TEXT    NOT NULL,
    slug       TEXT    NOT NULL,
    title      TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL,
    UNIQUE (owner, slug)
);
CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner      TEXT    NOT NULL,
    -- The board's slug. Not a foreign key on boards(id) because a board is
    -- addressed by (owner, slug) everywhere else, and one truth is enough.
    board      TEXT    NOT NULL,
    title      TEXT    NOT NULL,
    -- Markdown: the detail, and the `- [ ]` lines that are its subtasks.
    body       TEXT    NOT NULL DEFAULT '',
    lane       TEXT    NOT NULL DEFAULT 'todo',
    -- 0..n-1 within the lane, renumbered on every move.
    position   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL,
    -- When it entered Done, and so when its week starts. NULL anywhere else.
    done_at    TEXT
);
CREATE INDEX IF NOT EXISTS tasks_lane ON tasks (owner, board, lane, position);
CREATE TABLE IF NOT EXISTS config_bundles (
    owner      TEXT    NOT NULL,
    -- One synced set of dotfiles. "omarchy" is the only one so far.
    bundle     TEXT    NOT NULL,
    -- Bumped on every accepted push. 0 means nobody has claimed it yet.
    revision   INTEGER NOT NULL DEFAULT 0,
    -- The machine this revision came from.
    origin     TEXT    NOT NULL DEFAULT '',
    -- The machine that got here first, and so decided what the others adopt.
    claimed_by TEXT    NOT NULL DEFAULT '',
    claimed_at TEXT    NOT NULL DEFAULT '',
    updated_at TEXT    NOT NULL,
    PRIMARY KEY (owner, bundle)
);
CREATE TABLE IF NOT EXISTS config_files (
    owner      TEXT    NOT NULL,
    bundle     TEXT    NOT NULL,
    -- Relative to the bundle's root on the machine: hypr/hyprland.conf, say.
    path       TEXT    NOT NULL,
    sha256     TEXT    NOT NULL,
    -- Config files are text. Anything that is not is left where it is.
    content    TEXT    NOT NULL,
    -- The permission bits, so an executable script stays executable.
    mode       INTEGER NOT NULL DEFAULT 420,
    updated_at TEXT    NOT NULL,
    PRIMARY KEY (owner, bundle, path)
);
CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner      TEXT    NOT NULL,
    -- A dotted name: config.claimed, config.updated, config.applied, …
    kind       TEXT    NOT NULL DEFAULT 'info',
    -- The machine it happened on, or '' when it was the server itself.
    machine    TEXT    NOT NULL DEFAULT '',
    title      TEXT    NOT NULL,
    body       TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL,
    read_at    TEXT
);
CREATE INDEX IF NOT EXISTS notifications_owner ON notifications (owner, id DESC);
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


# Columns added after a table first shipped. CREATE TABLE IF NOT EXISTS will
# not add them to a database that already exists, so they go on by hand.
ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    # Accounts had a flag before they had a role; the flag is still written,
    # and `_migrate` gives every account that had it the matching role.
    ("users", "role", "TEXT NOT NULL DEFAULT 'user'"),
    ("users", "user_type", "TEXT NOT NULL DEFAULT 'human'"),
    ("agents", "sync_bundles", "TEXT NOT NULL DEFAULT ''"),
    # Where an agent serves its machine shares, reported on its heartbeat:
    # `http://192.168.1.10:8788`. Empty while it serves nothing.
    ("agents", "dav_base", "TEXT NOT NULL DEFAULT ''"),
    # 'server' for a directory on the server, 'machine' for one an agent
    # serves; a database from before the split holds only server shares.
    ("shares", "kind", "TEXT NOT NULL DEFAULT 'server'"),
    ("shares", "agent_id", "INTEGER"),
)


# Columns that changed their name. A rename keeps the values, and the seals
# on them: a secret's seal is bound to the vault's *value*, which is the
# project slug it always was.
RENAMED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    # Secrets belonged to a project; now they are in a vault of that name.
    ("secrets", "project", "vault"),
)


def _migrate(conn: sqlite3.Connection) -> None:
    for table, old, new in RENAMED_COLUMNS:
        present = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if old in present and new not in present:
            conn.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
    for table, column, definition in ADDED_COLUMNS:
        present = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            if (table, column) == ("users", "role"):
                # Everyone who was an admin before roles existed is one now.
                conn.execute(
                    "UPDATE users SET role = ? WHERE is_admin = 1", (ROLE_ADMIN,)
                )
    # `connect` is called for reads as well as writes, and a read closes the
    # connection without committing. The migration has to survive that.
    conn.commit()


class Connection(sqlite3.Connection):
    """A connection that can seal content on the way in and open it on the way out.

    Content columns (`sealed.SEALED`) hold ciphertext, so a store writes
    `conn.seal("tasks", "body", (owner,), body)` and reads with the matching
    `conn.unseal`. The scope is what the value is bound to; the same tuple
    has to come back at read time.
    """

    sealer: Sealer

    def seal(
        self, table: str, column: str, scope: Iterable[object], text: str | None
    ) -> str | None:
        return self.sealer.seal(table, column, scope, text)

    def unseal(
        self, table: str, column: str, scope: Iterable[object], blob: str | None
    ) -> str | None:
        return self.sealer.unseal(table, column, scope, blob)


def connect(db_path: Path) -> Connection:
    """Open a connection with the schema applied, sane pragmas, and the key."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, factory=Connection)
    conn.sealer = sealer_for(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    # Rows from before content was sealed. Nothing to do on a database that
    # has been through it once.
    migrate_sealing(conn, conn.sealer)
    return conn


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


def _row_to_user(row: sqlite3.Row) -> User:
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
            "username must be 1-32 chars: lowercase letters, digits, '_' or '-', "
            "starting with a letter or '_'"
        )
    return username


class UserStore:
    """Thin repository over the users table."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connect().close()

    def _connect(self) -> sqlite3.Connection:
        return connect(self.db_path)

    def count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"])

    def get(self, username: str) -> User | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username.strip().lower(),)
            ).fetchone()
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
        role = validate_role(role) if role is not None else (
            ROLE_ADMIN if is_admin else ROLE_USER
        )
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
        except sqlite3.IntegrityError as exc:
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
            cursor = conn.execute(
                "DELETE FROM users WHERE username = ?", (username.strip().lower(),)
            )
            if cursor.rowcount == 0:
                raise UnknownUserError(username)
