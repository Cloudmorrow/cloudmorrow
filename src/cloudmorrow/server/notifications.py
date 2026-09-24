"""What happened while you were not looking.

The machines do things on their own — adopt a config, push one, fail to write
one — and the only place all of them can leave a note is the server. So that
is where the notes live, and the TUI reads them back.

A notification is a fact, not a message: who it was about, what happened, and
when. Nothing here delivers anything; a channel that pushes these out as they
land can sit on top of the same rows later.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from cloudmorrow.server.db import Connection, connect

# Anything longer is a log line, not a notification.
MAX_BODY_CHARS = 2000
# Per owner. Old ones are dropped as new ones arrive.
KEEP = 200


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


@dataclass(slots=True)
class Notification:
    id: int
    owner: str
    kind: str
    machine: str
    title: str
    body: str
    created_at: str
    read_at: str | None

    @property
    def unread(self) -> bool:
        return self.read_at is None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "machine": self.machine,
            "title": self.title,
            "body": self.body,
            "created_at": self.created_at,
            "read_at": self.read_at,
            "unread": self.unread,
        }


def _row(conn: Connection, row) -> Notification:
    scope = (row["owner"],)
    return Notification(
        id=row["id"],
        owner=row["owner"],
        kind=row["kind"],
        machine=row["machine"],
        title=conn.unseal("notifications", "title", scope, row["title"]),
        body=conn.unseal("notifications", "body", scope, row["body"]),
        created_at=row["created_at"],
        read_at=row["read_at"],
    )


class NotificationStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        connect(self.db_path).close()

    def add(
        self,
        owner: str,
        *,
        title: str,
        kind: str = "info",
        machine: str = "",
        body: str = "",
    ) -> Notification:
        title = title.strip()[:200] or "(untitled)"
        with connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO notifications (owner, kind, machine, title, body, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (owner, kind.strip()[:64] or "info", machine[:64],
                 conn.seal("notifications", "title", (owner,), title),
                 conn.seal("notifications", "body", (owner,), body[:MAX_BODY_CHARS]), _now()),
            )
            # Keep the tail bounded without a cron job for it.
            conn.execute(
                "DELETE FROM notifications WHERE owner = ? AND id <="
                " (SELECT id FROM notifications WHERE owner = ? ORDER BY id DESC"
                "  LIMIT 1 OFFSET ?)",
                (owner, owner, KEEP),
            )
            row = conn.execute(
                "SELECT * FROM notifications WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return _row(conn, row)

    def list(self, owner: str, *, limit: int = 50, unread_only: bool = False) -> list[Notification]:
        query = "SELECT * FROM notifications WHERE owner = ?"
        if unread_only:
            query += " AND read_at IS NULL"
        query += " ORDER BY id DESC LIMIT ?"
        with connect(self.db_path) as conn:
            rows = conn.execute(query, (owner, limit)).fetchall()
        return [_row(conn, row) for row in rows]

    def unread_count(self, owner: str) -> int:
        with connect(self.db_path) as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM notifications WHERE owner = ? AND read_at IS NULL",
                    (owner,),
                ).fetchone()["n"]
            )

    def mark_read(self, owner: str, ids: list[int] | None = None) -> int:
        """Mark some of them read, or all of them when *ids* is None."""
        with connect(self.db_path) as conn:
            if ids is None:
                cursor = conn.execute(
                    "UPDATE notifications SET read_at = ? WHERE owner = ? AND read_at IS NULL",
                    (_now(), owner),
                )
            else:
                if not ids:
                    return 0
                marks = ", ".join("?" for _ in ids)
                cursor = conn.execute(
                    f"UPDATE notifications SET read_at = ? WHERE owner = ? AND read_at IS NULL"
                    f" AND id IN ({marks})",
                    (_now(), owner, *ids),
                )
            return cursor.rowcount
