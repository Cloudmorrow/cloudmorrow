"""Quills of somebody's own, shared with others, asked for, and what the server allows.

Three small things that are not the registry's — the registry says what is
installed; this says who else may have it and who wants what:

* **Shares.** A personal Quill's owner offers it to people; each says yes or
  no, and may leave later. An offer is a row; so is the answer.
* **Requests.** Somebody asks an administrator for a Quill — from the
  catalog, from a source, or to have their own promoted — and the
  administrator answers. A row each, open until answered.
* **The policy.** Three settings an administrator sets: may people have
  Quills of their own (`on`, `ask`: only through a request, `off`), may those
  run code, may they be shared. Kept in the settings table, so a fresh
  server needs nothing: the defaults are on.

See docs/SHARING.md.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from cloudmorrow.server.database import Connection, Database
from cloudmorrow.server.database import open as open_database
from cloudmorrow.server.settings import SettingsStore

# Made by schema.py, step 5. A change to it is a new step there.
TABLES = """
CREATE TABLE IF NOT EXISTS quill_shares (
    -- One row per person a personal Quill was offered to, with their answer.
    owner       TEXT NOT NULL,
    quill       TEXT NOT NULL,
    username    TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'offered',   -- offered, accepted, declined
    offered_by  TEXT NOT NULL DEFAULT '',
    offered_at  TEXT NOT NULL,
    answered_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (owner, quill, username)
);
CREATE TABLE IF NOT EXISTS quill_requests (
    -- Somebody asking an administrator for a Quill, and the answer.
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL,
    kind        TEXT NOT NULL,                     -- install, promote
    quill       TEXT NOT NULL DEFAULT '',          -- a catalog id, or their own Quill's id
    source      TEXT NOT NULL DEFAULT '',          -- a repository or folder, instead of the catalog
    ref         TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',          -- why, in their words
    state       TEXT NOT NULL DEFAULT 'open',      -- open, approved, declined, withdrawn
    asked_at    TEXT NOT NULL,
    answered_by TEXT NOT NULL DEFAULT '',
    answered_at TEXT NOT NULL DEFAULT '',
    answer      TEXT NOT NULL DEFAULT ''           -- what the administrator said, or did (JSON)
);
"""

OFFERED, ACCEPTED, DECLINED = "offered", "accepted", "declined"
OPEN, APPROVED, WITHDRAWN = "open", "approved", "withdrawn"
KINDS = frozenset({"install", "promote"})

# The policy: three settings, their names and what each may be.
PERSONAL = "personal_quills"  # on, ask, off
CODE = "personal_quill_code"  # on, off
SHARING = "personal_quill_sharing"  # on, off
POLICY = {PERSONAL: ("on", "ask", "off"), CODE: ("on", "off"), SHARING: ("on", "off")}
DEFAULTS = {PERSONAL: "on", CODE: "on", SHARING: "on"}


class SharingError(ValueError):
    """Something about a share or a request that cannot be, in words for a person."""


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


class Policy:
    """What this server lets people do with Quills of their own."""

    def __init__(self, settings: SettingsStore) -> None:
        self.settings = settings

    def get(self) -> dict[str, str]:
        return {key: self.settings.get(key) or DEFAULTS[key] for key in POLICY}

    def set(self, key: str, value: str, *, changed_by: str = "") -> dict[str, str]:
        if key not in POLICY:
            raise SharingError(f"{key} is not a setting; they are {', '.join(POLICY)}")
        if value not in POLICY[key]:
            raise SharingError(f"{key} is one of {', '.join(POLICY[key])}")
        self.settings.set(key, value, changed_by=changed_by)
        return self.get()

    @property
    def personal(self) -> str:
        return self.get()[PERSONAL]

    def may_install(self) -> bool:
        """May a person install a Quill of their own, without asking?"""
        return self.personal == "on"

    def may_have(self) -> bool:
        """May people have Quills of their own at all, however they got them?"""
        return self.personal != "off"

    def may_code(self) -> bool:
        return self.get()[CODE] == "on"

    def may_share(self) -> bool:
        return self.get()[SHARING] == "on"


class SharingStore:
    """Who a personal Quill is shared with, and what people asked for."""

    def __init__(self, db: Database | Path) -> None:
        self.db = open_database(db)
        self._connect().close()

    def _connect(self) -> Connection:
        return self.db.connect()

    # -- shares ------------------------------------------------------------------------
    def offer(self, owner: str, quill: str, username: str, *, by: str = "") -> dict:
        """Offer *owner*'s *quill* to *username*; an earlier no is asked again."""
        if username == owner:
            raise SharingError("it is yours already")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO quill_shares (owner, quill, username, state, offered_by, offered_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(owner, quill, username) DO UPDATE SET"
                " state = CASE WHEN quill_shares.state = 'accepted' THEN 'accepted' ELSE 'offered' END,"
                " offered_by = excluded.offered_by, offered_at = excluded.offered_at",
                (owner, quill, username, OFFERED, by or owner, _now()),
            )
            conn.commit()
            return self._share(conn, owner, quill, username)

    def answer(self, owner: str, quill: str, username: str, accepted: bool) -> dict:
        """*username*'s yes or no to an offer."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state FROM quill_shares WHERE owner = ? AND quill = ? AND username = ?",
                (owner, quill, username),
            ).fetchone()
            if row is None:
                raise SharingError(f"{owner}'s {quill} was not offered to {username}")
            conn.execute(
                "UPDATE quill_shares SET state = ?, answered_at = ? WHERE owner = ? AND quill = ? AND username = ?",
                (ACCEPTED if accepted else DECLINED, _now(), owner, quill, username),
            )
            conn.commit()
            return self._share(conn, owner, quill, username)

    def revoke(self, owner: str, quill: str, username: str) -> None:
        """The owner takes it back, or the person leaves: the row goes."""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM quill_shares WHERE owner = ? AND quill = ? AND username = ?", (owner, quill, username)
            )
            conn.commit()

    def forget(self, owner: str, quill: str) -> None:
        """Every share of one Quill, gone with it."""
        with self._connect() as conn:
            conn.execute("DELETE FROM quill_shares WHERE owner = ? AND quill = ?", (owner, quill))
            conn.commit()

    def forget_person(self, username: str) -> None:
        """Everything about one account, when the account goes: what they were
        offered, and what they asked for. What they owned is the registry's."""
        with self._connect() as conn:
            conn.execute("DELETE FROM quill_shares WHERE username = ?", (username,))
            conn.execute("DELETE FROM quill_requests WHERE username = ?", (username,))
            conn.commit()

    def shared_with(self, owner: str, quill: str) -> list[dict]:
        """Everybody a Quill was offered to, with their answer."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM quill_shares WHERE owner = ? AND quill = ? ORDER BY username", (owner, quill)
            ).fetchall()
        return [_share_row(row) for row in rows]

    def accepted_by(self, owner: str, quill: str) -> list[str]:
        return [s["username"] for s in self.shared_with(owner, quill) if s["state"] == ACCEPTED]

    def of_person(self, username: str, state: str | None = None) -> list[dict]:
        """Every Quill offered to *username*, or only those in one *state*."""
        with self._connect() as conn:
            if state:
                rows = conn.execute(
                    "SELECT * FROM quill_shares WHERE username = ? AND state = ? ORDER BY owner, quill",
                    (username, state),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM quill_shares WHERE username = ? ORDER BY owner, quill", (username,)
                ).fetchall()
        return [_share_row(row) for row in rows]

    def accepted_for(self, username: str) -> set[tuple[str, str]]:
        return {(s["owner"], s["quill"]) for s in self.of_person(username, ACCEPTED)}

    @staticmethod
    def _share(conn: Connection, owner: str, quill: str, username: str) -> dict:
        row = conn.execute(
            "SELECT * FROM quill_shares WHERE owner = ? AND quill = ? AND username = ?", (owner, quill, username)
        ).fetchone()
        return _share_row(row)

    # -- requests ----------------------------------------------------------------------
    def ask(
        self, username: str, kind: str, *, quill: str = "", source: str = "", ref: str = "", note: str = ""
    ) -> dict:
        if kind not in KINDS:
            raise SharingError(f"a request is one of {', '.join(sorted(KINDS))}")
        if kind == "promote" and not quill:
            raise SharingError("which Quill of yours should be promoted?")
        if kind == "install" and bool(quill) == bool(source):
            raise SharingError("name a Quill from the catalog, or a source, one of them")
        with self._connect() as conn:
            open_already = conn.execute(
                "SELECT id FROM quill_requests WHERE username = ? AND kind = ? AND quill = ? AND source = ?"
                " AND state = 'open'",
                (username, kind, quill, source),
            ).fetchone()
            if open_already is not None:
                raise SharingError("you have asked for that already; it is waiting for an administrator")
            request_id = conn.insert(
                "INSERT INTO quill_requests (username, kind, quill, source, ref, note, state, asked_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (username, kind, quill, source, ref, note.strip()[:1000], OPEN, _now()),
            )
            conn.commit()
            return self._request(conn, int(request_id))

    def requests(self, *, username: str | None = None, open_only: bool = True) -> list[dict]:
        where, params = [], []
        if username is not None:
            where.append("username = ?")
            params.append(username)
        if open_only:
            where.append("state = 'open'")
        sql = "SELECT * FROM quill_requests" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_request_row(row) for row in rows]

    def request(self, request_id: int) -> dict:
        with self._connect() as conn:
            return self._request(conn, request_id)

    def settle(self, request_id: int, state: str, *, by: str, answer: dict | None = None) -> dict:
        """Close a request: approved or declined by an administrator, or withdrawn by its asker."""
        if state not in (APPROVED, DECLINED, WITHDRAWN):
            raise SharingError(f"a request ends {APPROVED}, {DECLINED} or {WITHDRAWN}")
        with self._connect() as conn:
            found = self._request(conn, request_id)
            if found["state"] != OPEN:
                raise SharingError(f"that request was {found['state']} already")
            conn.execute(
                "UPDATE quill_requests SET state = ?, answered_by = ?, answered_at = ?, answer = ? WHERE id = ?",
                (state, by, _now(), json.dumps(answer or {}), request_id),
            )
            conn.commit()
            return self._request(conn, request_id)

    @staticmethod
    def _request(conn: Connection, request_id: int) -> dict:
        row = conn.execute("SELECT * FROM quill_requests WHERE id = ?", (request_id,)).fetchone()
        if row is None:
            raise SharingError(f"there is no request {request_id}")
        return _request_row(row)


def _share_row(row) -> dict:
    return {
        "owner": row["owner"],
        "quill": row["quill"],
        "username": row["username"],
        "state": row["state"],
        "offered_by": row["offered_by"],
        "offered_at": row["offered_at"],
        "answered_at": row["answered_at"],
    }


def _request_row(row) -> dict:
    try:
        answer = json.loads(row["answer"] or "{}")
    except ValueError:
        answer = {}
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "kind": row["kind"],
        "quill": row["quill"],
        "source": row["source"],
        "ref": row["ref"],
        "note": row["note"],
        "state": row["state"],
        "asked_at": row["asked_at"],
        "answered_by": row["answered_by"],
        "answered_at": row["answered_at"],
        "answer": answer,
    }
