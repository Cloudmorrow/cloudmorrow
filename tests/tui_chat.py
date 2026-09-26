"""The spaces half of the fake server the TUI tests drive: Chat, as a Quill.

Chat is installed beside Tasks, exactly as `GET /api/quills` sends it, and
the record store behind the fake keeps the promises the real one makes for
spaces (server/records.py): a space carries its members, whether you may
manage it, what is unread in it and the last thing said; `mark_seen` clears
the count; `unique` finds the space between the same people rather than
making a second; `last` and `since` page a conversation. A FakeClient mixes
this in before FakeQuills.
"""

from __future__ import annotations

import copy

from cloudmorrow.client.api import ApiError
from tests.tui_quills import record_row

CHAT_MODELS = {
    "channel": {
        "id": "channel",
        "version": 1,
        "label": "Channel",
        "description": "A room people talk in: public, private, or between two people.",
        "domain": "messaging",
        "scopes": ["shared", "public"],
        "title": "name",
        "ordered_within": [],
        "source": "foundation",
        "space": True,
        "in_space": "",
        "authored": False,
        "notify": [],
        "fields": [
            {"name": "name", "kind": "string", "label": "Name", "required": True},
            {"name": "kind", "kind": "enum", "label": "Kind", "indexed": True, "default": "public",
             "values": ["public", "private", "direct"], "labels": ["Public", "Private", "Direct"]},
            {"name": "topic", "kind": "text", "label": "Topic"},
        ],
    },
    "message": {
        "id": "message",
        "version": 1,
        "label": "Message",
        "description": "What somebody said in a channel.",
        "domain": "messaging",
        "scopes": ["shared", "public"],
        "title": "body",
        "ordered_within": [],
        "source": "foundation",
        "space": False,
        "in_space": "channel",
        "authored": True,
        "notify": [{"when": "created", "to": "members", "push": True, "unread": True}],
        "fields": [
            {"name": "channel", "kind": "link", "label": "Channel", "required": True,
             "indexed": True, "to": "channel", "on_delete": "cascade"},
            {"name": "body", "kind": "text", "label": "Body", "required": True},
            {"name": "sent_at", "kind": "datetime", "label": "Sent at", "indexed": True},
        ],
    },
}

CHAT_SCREEN = {
    "id": "chat", "kit": "thread", "label": "Chat", "model": "message", "space": "channel",
    "body": "body", "about": "topic",
    "made_as": {"public": {"kind": "public"}, "shared": {"kind": "private"}, "direct": {"kind": "direct"}},
}

CHAT_QUILL = {
    "id": "chat",
    "name": "Chat",
    "version": "1.0.0",
    "summary": "Channels, direct messages, and the count on the icon.",
    "category": "home",
    "icon": "chat",
    "publisher": "Cloudmorrow",
    "license": "AGPL-3.0-or-later",
    "uses": ["channel", "message"],
    "extends": {},
    "introduces": [],
    "grants": [],
    "screens": [CHAT_SCREEN],
    "jobs": [],
    "datasets": [{"id": "general", "model": "channel", "seed": "once", "scope": "public", "count": 1}],
    "services": [],
    "webhooks": [],
    "apis": [],
    "data": [
        {"id": "channel", "label": "Channel", "how": "uses", "foundation": True, "new": False},
        {"id": "message", "label": "Message", "how": "uses", "foundation": True, "new": False},
    ],
    "surfaces": ["phone", "web", "terminal", "command line", "assistant"],
    "installed_version": "1.0.0",
    "not_running_yet": [],
    "enabled": True,
    "models": CHAT_MODELS,
}


def space_row(record_id: str, name: str, kind: str, *, owner: str = "bram", scope: str = "",
              members: list[str] | None = None, topic: str = "", at: str = "2026-09-01T09:00:00+00:00") -> dict:
    row = record_row("channel", record_id, 0, name=name, kind=kind, topic=topic)
    row.update(owner=owner, scope=scope or ("public" if kind == "public" else "shared"),
               members=list(members or []), created_at=at, updated_at=at)
    return row


def line_row(record_id: str, space: str, owner: str, body: str, at: str, *, edited: str = "") -> dict:
    row = record_row("message", record_id, 0, channel=space, body=body, sent_at=at)
    row.update(owner=owner, created_at=at, updated_at=edited or at)
    return row


def seed_chat() -> dict[str, list[dict]]:
    """#general, where all is read, and a direct line from the guest with two unread."""
    return {
        "channel": [
            space_row("r_general", "general", "public", topic="everything else"),
            space_row("r_dm", "bram & guest", "direct", owner="guest", members=["bram"],
                      at="2026-09-18T08:00:00+00:00"),
        ],
        "message": [
            line_row("r_m1", "r_general", "bram", "the fans are loud again", "2026-09-19T14:02:00+00:00"),
            line_row("r_m2", "r_general", "guest", "I turned the fan curve down", "2026-09-19T14:03:00+00:00"),
            line_row("r_m3", "r_dm", "guest", "are you up", "2026-09-18T08:30:00+00:00"),
            line_row("r_m4", "r_dm", "guest", "the NAS is beeping", "2026-09-18T08:31:00+00:00"),
        ],
    }


class FakeSpaces:
    """Spaces on top of the fake record store: members, unread, seen, the last line."""

    def setup_quills(self) -> None:
        super().setup_quills()  # type: ignore[misc]
        self.quill_list.append(copy.deepcopy(CHAT_QUILL))
        self.record_store.update(seed_chat())
        # When bram last looked in each space; everything after, by others, is unread.
        self.seen: dict[str, str] = {"r_general": "2026-09-19T14:03:00+00:00"}
        self.space_calls: list[tuple] = []
        self.seen_calls: list[str] = []
        self.person_list: list[dict] = [
            {"username": "guest", "display_name": "Guest"},
            {"username": "ada", "display_name": ""},
        ]

    # -- what a space carries --------------------------------------------------
    def _space_extras(self, row: dict) -> dict:
        lines = sorted(
            (m for m in self.record_store.get("message", []) if m["fields"].get("channel") == row["id"]),
            key=lambda m: m["created_at"],
        )
        since = self.seen.get(row["id"], "")
        last = lines[-1] if lines else None
        return {
            **row,
            "can_manage": row["owner"] == "bram",
            "unread": sum(1 for m in lines if m["owner"] != "bram" and m["created_at"] > since),
            "last": {"id": last["id"], "model": "message", "owner": last["owner"],
                     "created_at": last["created_at"], "title": last["fields"]["body"]} if last else None,
        }

    def _visible(self, model: str, row: dict) -> bool:
        definition = self._model(model)  # type: ignore[attr-defined]
        if definition.get("space"):
            return row["scope"] == "public" or "bram" in [row["owner"], *row.get("members", [])]
        return True

    async def records(self, model: str, *, last: int | None = None, since: str | None = None,
                      **where: object) -> list[dict]:
        rows = await super().records(model, **where)  # type: ignore[misc]
        rows = [r for r in rows if self._visible(model, r)]
        if self._model(model).get("in_space"):  # type: ignore[attr-defined]
            rows.sort(key=lambda r: r["created_at"])
        if since:
            rows = [r for r in rows if r["updated_at"] >= since]
        if last is not None:
            rows = rows[-last:]
        if self._model(model).get("space"):  # type: ignore[attr-defined]
            rows = [self._space_extras(r) for r in rows]
        return rows

    async def create_record(self, model: str, fields: dict, *, index: int | None = None,
                            scope: str | None = None, members: list[str] | None = None,
                            unique: bool = False) -> dict:
        definition = self._model(model)  # type: ignore[attr-defined]
        if definition.get("space"):
            people = {"bram", *(members or [])}
            if unique:
                for row in self.record_store.get(model, []):
                    same = all(row["fields"].get(k) == v for k, v in fields.items() if k == "kind")
                    if same and {row["owner"], *row.get("members", [])} == people and row["scope"] == scope:
                        self.space_calls.append(("found", row["id"]))
                        return self._space_extras(copy.deepcopy(row))
            made = await super().create_record(model, fields, index=index)  # type: ignore[misc]
            stored = self._find(model, made["id"])  # type: ignore[attr-defined]
            stored.update(scope=scope or "shared", members=list(members or []))
            self.space_calls.append(("made", stored["id"], scope, list(members or []), dict(fields)))
            return self._space_extras(copy.deepcopy(stored))
        made = await super().create_record(model, fields, index=index)  # type: ignore[misc]
        stored = self._find(model, made["id"])  # type: ignore[attr-defined]
        stamp = "2026-09-20T10:00:00+00:00"
        stored.update(created_at=stamp, updated_at=stamp)
        if definition.get("in_space"):
            self.seen[fields[definition["in_space"]]] = stamp
        return copy.deepcopy(stored)

    # -- the people in a space ---------------------------------------------------
    async def add_member(self, model: str, space_id: str, username: str) -> dict:
        row = self._find(model, space_id)  # type: ignore[attr-defined]
        if row["scope"] != "shared":
            raise ApiError("only a shared channel has members", status_code=400)
        self.space_calls.append(("add", space_id, username))
        if username not in row["members"]:
            row["members"].append(username)
        return self._space_extras(copy.deepcopy(row))

    async def remove_member(self, model: str, space_id: str, username: str) -> None:
        row = self._find(model, space_id)  # type: ignore[attr-defined]
        self.space_calls.append(("remove", space_id, username))
        row["members"] = [m for m in row["members"] if m != username]

    async def mark_seen(self, model: str, space_id: str) -> None:
        self.seen_calls.append(space_id)
        self.seen[space_id] = "9999"

    async def people(self) -> list[dict]:
        return [dict(p) for p in self.person_list]
