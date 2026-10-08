"""A Quill's credentials: the token its services carry, and its webhooks' secrets.

**The token.** A service talks to the record API as the clients do, with a
bearer token — its own, never a person's. It is a random string with a
`cmq_` prefix, kept here only as a hash, as MCP tokens are: the database
never holds one that works. A request bearing it is the Quill's principal,
`Principal("quill", <runs as>, quill=<id>, models=<what it declared>)`, and
the one door that takes it is the record API (and the Quill's own APIs);
every other route asks for a person's token, which this is not.

Because only the hash is kept, the token that works exists in two places:
the server's memory and the environment of the Quill's processes. So the
supervisor issues a fresh one each time it takes a Quill up — at boot, at
install — and an administrator's rotate is the same thing, followed by a
restart of the Quill's services. Uninstalling deletes the row, and with it
the only thing a token could match.

**Runs as.** In this first version a Quill's code acts for one account: the
administrator who installed it, written into its `.origin.json` by the
install routes. A Quill installed with nobody signed in — the foundation
Quills at first boot, `cloudmorrow-server quill add` — runs as the oldest
active administrator. One whose installer is gone or switched off runs as
nobody: its services are not started until somebody reinstalls it. Services
that run for each person separately are the next step (docs/QUILLS.md).

**Webhook secrets.** A webhook's secret has to be shown to an administrator
again whenever they want to paste it into the sender's settings, so it is
kept sealed rather than hashed: bound to the Quill and the webhook, opened
only by the server's key.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from pathlib import Path

from cloudmorrow.server.database import Connection, Database
from cloudmorrow.server.database import open as open_database
from cloudmorrow.server.db import UserStore

__all__ = ["PREFIX", "QuillTokenStore", "runs_as"]

PREFIX = "cmq_"

# Made by schema.py, step 1. A change to it is a new step there.
TABLES = """
CREATE TABLE IF NOT EXISTS quill_tokens (
    -- One live token per installed Quill that runs code. Only the hash:
    -- the token itself is in the server's memory and its services' env.
    quill       TEXT PRIMARY KEY,
    token_hash  TEXT NOT NULL UNIQUE,
    issued_at   TEXT NOT NULL,
    last_used_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS quill_webhooks (
    -- A webhook's secret, sealed to the Quill and the webhook, so an
    -- administrator can be shown it again.
    quill      TEXT NOT NULL,
    hook       TEXT NOT NULL,
    secret     TEXT NOT NULL,
    issued_at  TEXT NOT NULL,
    PRIMARY KEY (quill, hook)
);
"""


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def runs_as(users: UserStore, origin: dict) -> str:
    """The account a Quill's code acts for, or "" when there is none to act for."""
    named = str(origin.get("installed_by") or "")
    if named:
        user = users.get(named)
        return named if user is not None and user.is_active and user.is_admin else ""
    admins = [u for u in users.list() if u.is_admin and u.is_active]
    admins.sort(key=lambda u: u.id)
    return admins[0].username if admins else ""


class QuillTokenStore:
    """Tokens and webhook secrets, per Quill."""

    def __init__(self, db: Database | Path) -> None:
        self.db = open_database(db)
        self._connect().close()

    def _connect(self) -> Connection:
        return self.db.connect()

    # -- the token -------------------------------------------------------------
    def issue(self, quill: str) -> str:
        """A new token for *quill*; the one before stops working now."""
        token = PREFIX + secrets.token_urlsafe(32)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO quill_tokens (quill, token_hash, issued_at) VALUES (?, ?, ?)"
                " ON CONFLICT(quill) DO UPDATE SET token_hash = excluded.token_hash,"
                " issued_at = excluded.issued_at, last_used_at = ''",
                (quill, _hash(token), _now()),
            )
        conn.close()
        return token

    def quill_for(self, token: str) -> str | None:
        """The Quill a token is, or None. Anything without the prefix is not one."""
        if not token or not token.startswith(PREFIX):
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT quill FROM quill_tokens WHERE token_hash = ?", (_hash(token),)).fetchone()
            if row is not None:
                conn.execute(
                    "UPDATE quill_tokens SET last_used_at = ? WHERE quill = ?",
                    (_now(), row["quill"]),
                )
        conn.close()
        return row["quill"] if row else None

    def info(self, quill: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT issued_at, last_used_at FROM quill_tokens WHERE quill = ?", (quill,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def holders(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT quill FROM quill_tokens").fetchall()
            rows += conn.execute("SELECT DISTINCT quill FROM quill_webhooks").fetchall()
        conn.close()
        return sorted({row["quill"] for row in rows})

    def revoke(self, quill: str) -> None:
        """The token and every webhook secret of *quill*: gone, so nothing matches them."""
        with self._connect() as conn:
            conn.execute("DELETE FROM quill_tokens WHERE quill = ?", (quill,))
            conn.execute("DELETE FROM quill_webhooks WHERE quill = ?", (quill,))
        conn.close()

    # -- webhook secrets --------------------------------------------------------
    def webhook_secret(self, quill: str, hook: str) -> str:
        """The secret of one webhook, made the first time it is asked for.

        Made under the write lock: the supervisor handing a service its
        secrets and a request checking one ask at the same moment on a
        fresh install, and both finding nothing and both making one would
        leave one of them holding a secret that no longer is.
        """
        with self._connect() as conn:
            conn.lock()
            row = conn.execute(
                "SELECT secret FROM quill_webhooks WHERE quill = ? AND hook = ?", (quill, hook)
            ).fetchone()
            value = conn.unseal("quill_webhooks", "secret", (quill, hook), row["secret"]) if row is not None else None
            if value is None:
                value = self._write_webhook(conn, quill, hook)
        conn.close()
        return value

    @staticmethod
    def _write_webhook(conn: Connection, quill: str, hook: str) -> str:
        secret = secrets.token_urlsafe(24)
        conn.execute(
            "INSERT INTO quill_webhooks (quill, hook, secret, issued_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (quill, hook) DO UPDATE SET secret = excluded.secret, issued_at = excluded.issued_at",
            (quill, hook, conn.seal("quill_webhooks", "secret", (quill, hook), secret), _now()),
        )
        return secret

    def rotate_webhook(self, quill: str, hook: str) -> str:
        with self._connect() as conn:
            secret = self._write_webhook(conn, quill, hook)
        conn.close()
        return secret

    def forget_webhooks(self, quill: str, keep: set[str]) -> None:
        """Secrets of webhooks *quill* no longer declares: an update took them away."""
        with self._connect() as conn:
            for row in conn.execute("SELECT hook FROM quill_webhooks WHERE quill = ?", (quill,)).fetchall():
                if row["hook"] not in keep:
                    conn.execute(
                        "DELETE FROM quill_webhooks WHERE quill = ? AND hook = ?",
                        (quill, row["hook"]),
                    )
        conn.close()
