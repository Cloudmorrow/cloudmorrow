"""The database's tables, and how an older database is brought up to them.

Every store keeps its rows in the one SQLite file, and every connection is
opened through `db.connect`, which calls `upgrade` here. The file carries
its version in `PRAGMA user_version`; `upgrade` runs each step above it, in
order, and writes the new number after each. Opening a database that is
already current costs one pragma read.

To change the tables, add a step at the end of STEPS. Do not edit what an
earlier step does, or a table a step creates: a database that has run that
step will never run it again, so the change would only reach new servers.

Step 1 is everything from before there were versions: the tables, each
store's own, the columns added and renamed since, and the first circle. It
is written to be safe on a database from any earlier release, which is what
a database at version 0 is.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass

# What an account is allowed to do, as the role column says it. db.py has
# the full list; the migration needs only this one.
ROLE_ADMIN = "administrator"

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
-- Chat, from before it was a Quill. Nothing writes here any more: at boot
-- the rows move into the record store once (quills/jobs.py, move_legacy_chat),
-- and the tables stay, untouched, because data is never dropped.
CREATE TABLE IF NOT EXISTS chat_channels (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    slug       TEXT    NOT NULL UNIQUE,
    name       TEXT    NOT NULL DEFAULT '',
    topic      TEXT    NOT NULL DEFAULT '',
    -- 'public', 'private' or 'direct'.
    kind       TEXT    NOT NULL DEFAULT 'private',
    created_by TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_members (
    channel_id INTEGER NOT NULL REFERENCES chat_channels(id) ON DELETE CASCADE,
    username   TEXT    NOT NULL,
    added_by   TEXT    NOT NULL DEFAULT '',
    joined_at  TEXT    NOT NULL,
    -- The id of the last message this member had read.
    last_read  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (channel_id, username)
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL REFERENCES chat_channels(id) ON DELETE CASCADE,
    author     TEXT    NOT NULL,
    body       TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    edited_at  TEXT
);
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


def _columns(conn: sqlite3.Connection) -> None:
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
                conn.execute("UPDATE users SET role = ? WHERE is_admin = 1", (ROLE_ADMIN,))
    conn.commit()


def _store_tables() -> tuple[str, ...]:
    """The tables each store declares next to its code, for step 1 to make."""
    from cloudmorrow.server import features, mcp, records, settings, webpush
    from cloudmorrow.server.quills import code, services, tokens

    return (
        records.TABLE,
        mcp.TABLES,
        settings.TABLE,
        features.TABLE,
        webpush.SCHEMA,
        tokens.TABLES,
        services.TABLE,
        code.TABLE,
    )


def _baseline(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table in _store_tables():
        conn.executescript(table)
    _columns(conn)
    # Who may use which data (circles.py): its tables, and Members with
    # everybody in it, the first time.
    from cloudmorrow.server.circles import ensure as ensure_circles

    ensure_circles(conn)


@dataclass(frozen=True)
class Step:
    version: int
    what: str
    run: Callable[[sqlite3.Connection], None]


STEPS: tuple[Step, ...] = (Step(1, "the tables as they stood before they were versioned", _baseline),)

VERSION = STEPS[-1].version

# Two connections opened at once on a database behind the times would both
# run the steps. A step is not one transaction (executescript commits as it
# goes), so the process runs them one connection at a time instead.
_upgrading = threading.Lock()


def version_of(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def upgrade(conn: sqlite3.Connection) -> None:
    """Run every step this database has not run yet."""
    if version_of(conn) >= VERSION:
        return
    with _upgrading:
        for step in STEPS:
            if step.version <= version_of(conn):
                continue
            step.run(conn)
            # A pragma takes no parameters; the version is an int of ours.
            conn.execute(f"PRAGMA user_version = {int(step.version)}")
            # `connect` is called for reads as well as writes, and a read
            # closes the connection without committing. A step has to
            # survive that.
            conn.commit()
