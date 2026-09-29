"""The database's version, and what an older one is brought up to."""

from __future__ import annotations

import sqlite3

from cloudmorrow.server import schema
from cloudmorrow.server.db import connect


def tables(conn) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_a_new_database_is_made_at_the_current_version_with_every_stores_tables(tmp_path):
    conn = connect(tmp_path / "cloud.db")
    assert schema.version_of(conn) == schema.VERSION
    # Tables from db's own schema, from stores, and the first circle.
    assert {
        "users",
        "records",
        "mcp_tokens",
        "settings",
        "features",
        "push_subscriptions",
        "quill_tokens",
        "quill_job_runs",
        "quill_call_runs",
        "circles",
    } <= tables(conn)
    assert conn.execute("SELECT COUNT(*) FROM circles WHERE is_default = 1").fetchone()[0] == 1
    conn.close()


def test_a_database_from_before_versions_gets_its_columns_and_keeps_its_admins(tmp_path):
    path = tmp_path / "cloud.db"
    old = sqlite3.connect(path)
    # An account table from before roles, and secrets from before vaults.
    old.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        );
        INSERT INTO users (username, password_hash, is_admin, created_at)
            VALUES ('bram', 'x', 1, '2025-01-01'), ('guest', 'x', 0, '2025-01-01');
        """
    )
    old.commit()
    old.close()

    conn = connect(path)
    assert schema.version_of(conn) == schema.VERSION
    roles = dict(conn.execute("SELECT username, role FROM users"))
    assert roles == {"bram": "administrator", "guest": "user"}
    # Everybody who was there is in the first circle.
    members = {row[0] for row in conn.execute("SELECT username FROM circle_members")}
    assert members == {"bram", "guest"}
    conn.close()


def test_a_current_database_runs_no_step_again(tmp_path, monkeypatch):
    connect(tmp_path / "cloud.db").close()
    ran = []
    monkeypatch.setattr(schema, "STEPS", tuple(schema.Step(s.version, s.what, ran.append) for s in schema.STEPS))
    connect(tmp_path / "cloud.db").close()
    assert ran == []


def test_steps_are_numbered_in_order_from_one():
    assert [step.version for step in schema.STEPS] == list(range(1, len(schema.STEPS) + 1))
