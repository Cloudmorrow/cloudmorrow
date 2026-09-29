"""Whose each device on the mesh is: the box's own labels, never the relay's.

The relay lists a cloud's devices as `{id, address, online, last_seen}` and
nothing more: it is never told whose a device is or what somebody calls it.
The box keeps that here, one row per device id — the owner's username and
what they call it ("laptop") — and joins it to the relay's list by id when a
screen asks (`access_ways.Access.devices`). A device nobody labelled yet is
shown as such, and an administrator can say whose it is.

A device gets its label when the person who joined it tells the cloud,
signed in: `cm access join` and the client installer do that once the
computer is on the mesh (`POST /api/access/mesh/mine`, with its mesh
address, which the box finds in the relay's list).
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from cloudmorrow.server.db import connect

TABLE = """
CREATE TABLE IF NOT EXISTS access_labels (
    device_id   TEXT PRIMARY KEY,
    owner       TEXT NOT NULL DEFAULT '',
    device      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
"""


@dataclass(slots=True)
class Label:
    device_id: str
    owner: str
    device: str

    @property
    def text(self) -> str:
        """ "jimmi: laptop", the way a list shows it."""
        if self.owner and self.device:
            return f"{self.owner}: {self.device}"
        return self.owner or self.device


def clean_device(device: str) -> str:
    """What somebody calls a device, on one line and not too long."""
    return " ".join((device or "").split())[:60]


class LabelStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        with self._connect() as conn:
            conn.executescript(TABLE)
        conn.close()

    def _connect(self) -> sqlite3.Connection:
        return connect(self.db_path)

    def all(self) -> dict[str, Label]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT device_id, owner, device FROM access_labels").fetchall()
        finally:
            conn.close()
        return {row["device_id"]: Label(row["device_id"], row["owner"], row["device"]) for row in rows}

    def set(self, device_id: str, owner: str, device: str) -> Label:
        label = Label(device_id, owner, clean_device(device))
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO access_labels (device_id, owner, device, created_at) VALUES (?, ?, ?, ?)",
                (device_id, owner, label.device, dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")),
            )
        conn.close()
        return label

    def remove(self, device_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM access_labels WHERE device_id = ?", (device_id,))
        conn.close()

    def clear(self) -> None:
        """Every label: an unlinked cloud has no mesh, so no devices on it."""
        with self._connect() as conn:
            conn.execute("DELETE FROM access_labels")
        conn.close()
