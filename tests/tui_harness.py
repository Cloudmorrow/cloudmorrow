"""The fake server the TUI tests drive, and the waits that keep them honest.

Shared by every test that opens the app, so there is one fake to keep truthful
rather than one per module.
"""

from __future__ import annotations

import datetime as dt
import re

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.app import CloudmorrowApp
from cloudmorrow.tui.screens.workspace import WorkspaceScreen
from tests.tui_quills import FakeQuills

SECRETS = {
    ("verticore", "local"): [
        {
            "key": "API_URL",
            "environment": "local",
            "length": 21,
            "fingerprint": "a1b2",
            "updated_at": "2026-09-10T20:27:00",
            "value": None,
        }
    ],
    ("verticore", "production"): [
        {
            "key": "STRIPE_KEY",
            "environment": "production",
            "length": 41,
            "fingerprint": "beef",
            "updated_at": "2026-09-01T07:15:00",
            "value": None,
        }
    ],
    ("homelab", "local"): [
        {
            "key": "WIFI_PASSWORD",
            "environment": "local",
            "length": 12,
            "fingerprint": "c0de",
            "updated_at": "2026-09-05T18:00:00",
            "value": None,
        }
    ],
}

TREE = {
    "name": "notes",
    "path": "",
    "is_dir": True,
    "size": 0,
    "modified": 0,
    "children": [
        {
            "name": "architecture.md",
            "path": "architecture.md",
            "is_dir": False,
            "size": 12,
            "modified": 0,
        }
    ],
}


# The machine the tests are "sitting at", named the way agent setup would
# name it, so the settings screen finds it in the list.
def agent_row(name: str, **extra) -> dict:
    return {
        "id": extra.get("id", 1),
        "name": name,
        "hostname": f"{name}.local",
        "platform": extra.get("platform", "Linux-6.10-arch"),
        "version": "0.9.0",
        "capabilities": extra.get("capabilities", ["ping", "sysinfo", "omarchy"]),
        "last_seen": "2026-09-11T09:00:00",
        "enrolled_at": "2026-08-01T09:00:00",
        "online": extra.get("online", True),
        "sync_bundles": extra.get("sync_bundles", []),
    }


BUNDLE = {
    "bundle": "omarchy",
    "revision": 0,
    "origin": "",
    "claimed_by": "",
    "claimed_at": "",
    "updated_at": "",
    "files": [],
    "machines": [],
}

NOTIFICATIONS = [
    {
        "id": 2,
        "kind": "config.updated",
        "machine": "desktop",
        "title": "omarchy config changed on desktop",
        "body": "Revision 2, 4 files.",
        "created_at": "2026-09-11T08:30:00",
        "read_at": None,
        "unread": True,
    },
]


def user_row(username: str, **extra) -> dict:
    role = extra.get("role", "user")
    return {
        "username": username,
        "display_name": extra.get("display_name", ""),
        "role": role,
        "user_type": extra.get("user_type", "human"),
        "is_admin": role == "administrator",
        "is_active": extra.get("is_active", True),
        "system_uid": None,
        "created_at": "2026-08-01T09:00:00",
    }


def feature_row(key: str, label: str, enabled: bool = True) -> dict:
    return {
        "key": key,
        "label": label,
        "description": f"{label}, and what is in them",
        "enabled": enabled,
        "changed_by": "",
        "updated_at": "",
    }


FEATURES = [
    feature_row("notes", "Notes"),
    feature_row("tasks", "Tasks"),
    feature_row("secrets", "Secrets"),
    feature_row("files", "Files"),
    feature_row("chat", "Chat"),
    feature_row("calendar", "Calendar"),
]


CHANNELS = [
    {
        "slug": "general",
        "name": "general",
        "topic": "everything else",
        "kind": "public",
        "created_by": "bram",
        "created_at": "2026-09-01T09:00:00",
        "updated_at": "2026-09-19T14:03:00",
        "members": ["bram", "guest"],
        "other": "",
        "member": True,
        "unread": 0,
        "last_read": 2,
        "last_message": None,
    },
    {
        "slug": "dm-bram-guest",
        "name": "guest",
        "topic": "",
        "kind": "direct",
        "created_by": "guest",
        "created_at": "2026-09-18T08:00:00",
        "updated_at": "2026-09-18T08:30:00",
        "members": ["bram", "guest"],
        "other": "guest",
        "member": True,
        "unread": 2,
        "last_read": 0,
        "last_message": None,
    },
]

MESSAGES = {
    "general": [
        {"id": 1, "author": "bram", "body": "the fans are loud again",
         "created_at": "2026-09-19T14:02:00", "edited_at": None},
        {"id": 2, "author": "guest", "body": "I turned the fan curve down",
         "created_at": "2026-09-19T14:03:00", "edited_at": None},
    ],
    "dm-bram-guest": [
        {"id": 3, "author": "guest", "body": "are you up",
         "created_at": "2026-09-18T08:30:00", "edited_at": None},
    ],
}


# The calendar, hung on today rather than on a date in the past: the pane
# opens on the month it is, so a fixture from last September would leave
# every one of these tests looking at an empty grid.
TODAY = dt.date.today()
TOMORROW = TODAY + dt.timedelta(days=1)


def calendar_row(slug: str, name: str, kind: str, colour: str, **extra) -> dict:
    members = extra.get("members", ["bram"])
    return {
        "slug": slug,
        "name": name,
        "kind": kind,
        "colour": colour,
        "owner": extra.get("owner", "bram"),
        "created_at": "2026-09-01T09:00:00",
        "updated_at": "2026-09-01T09:00:00",
        "members": members,
        "member": True,
        "mine": extra.get("owner", "bram") == "bram",
        "events": extra.get("events", 0),
    }


CALENDARS = [
    calendar_row("my-bram", "Jimmi", "personal", "cyan"),
    calendar_row("household", "Household", "shared", "violet", members=["bram", "guest"]),
    calendar_row("holidays", "Holidays", "public", "green", members=["bram", "guest"]),
]


def event_row(event_id: int, title: str, calendar: str, starts_at: str, ends_at: str,
              **extra) -> dict:
    colour = next(c["colour"] for c in CALENDARS if c["slug"] == calendar)
    return {
        "id": event_id,
        "calendar": calendar,
        "calendar_name": next(c["name"] for c in CALENDARS if c["slug"] == calendar),
        "colour": colour,
        "title": title,
        "notes": extra.get("notes", ""),
        "location": extra.get("location", ""),
        "starts_at": starts_at,
        "ends_at": ends_at,
        "all_day": extra.get("all_day", False),
        "created_by": extra.get("created_by", "bram"),
        "created_at": "2026-09-01T09:00:00",
        "updated_at": "2026-09-01T09:00:00",
    }


EVENTS = [
    event_row(1, "Dentist", "my-bram", f"{TODAY}T10:00", f"{TODAY}T11:00",
              location="High Street"),
    event_row(2, "Bins out", "household", str(TODAY), str(TODAY), all_day=True,
              created_by="guest"),
    event_row(3, "Boiler service", "household", f"{TOMORROW}T09:00", f"{TOMORROW}T10:00"),
]


def share_row(name: str, **extra) -> dict:
    return {
        "name": name,
        "path": extra.get("path", f"/srv/cloudmorrow/notes/Shares/{name}"),
        "managed": extra.get("managed", True),
        "description": extra.get("description", ""),
        "url": f"https://test.invalid/dav/{name}/",
        "created_at": "2026-09-01T09:00:00",
        "updated_at": "2026-09-01T09:00:00",
    }


def entry_row(name: str, **extra) -> dict:
    """One line of a share's listing, the way the server says it."""
    is_dir = bool(extra.get("is_dir", False))
    return {
        "name": name,
        "is_dir": is_dir,
        "size": 0 if is_dir else int(extra.get("size", 0)),
        "modified": float(extra.get("modified", 0)),
        "mime": "" if is_dir else str(extra.get("mime", "")),
    }


def _one_pixel_png() -> bytes:
    """A real PNG, so the picture widget has something it can open."""
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (1, 1), (22, 111, 128)).save(buffer, "PNG")
    return buffer.getvalue()


PNG_1PX = _one_pixel_png()


class FakeClient(FakeQuills):
    """Enough of the API for the workspace, with a record of what was asked.

    The Quills and the record store behind them are in tui_quills.py.
    """

    # What a mount signs in with.
    token = "test-token"

    def __init__(self) -> None:
        # None, the way a TUI session leaves it: the app is not in a vault,
        # so a call that wants one names it itself.
        self.vault: str | None = None
        self.setup_quills()
        self.share_list: list[dict] = [share_row("media"), share_row("photos")]
        self.share_calls: list[tuple] = []
        # What is in the server shares the Browse view opens: by share, then
        # by folder. What was asked for, and which files were fetched.
        self.share_tree: dict[str, dict[str, list[dict]]] = {
            "media": {
                "": [
                    entry_row("Holiday", is_dir=True, modified=1_756_800_000),
                    entry_row("readme.txt", size=5, mime="text/plain", modified=1_756_700_000),
                    entry_row("song.mp3", size=4200000, mime="audio/mpeg", modified=1_756_600_000),
                ],
                "Holiday": [
                    entry_row("beach.jpg", size=1234567, mime="image/jpeg", modified=1_756_500_000),
                    entry_row("dunes.png", size=654_321, mime="image/png", modified=1_756_400_000),
                    entry_row("where.txt", size=40, mime="text/plain", modified=1_756_300_000),
                ],
            },
            "photos": {"": []},
        }
        self.listing_calls: list[tuple[str, str]] = []
        self.share_fetches: list[str] = []
        self.uploads: list[tuple[str, bytes]] = []
        self.fetched: list[str] = []
        self.read_keys: list[tuple[str, str]] = []
        # Machines, the config bundle and the notifications the settings
        # screen reads. A test that cares reshapes these before opening it.
        self.agent_list: list[dict] = []
        # The accounts and the features the administration panel shows, and
        # what it was asked to change about them.
        self.user_list: list[dict] = [
            user_row("bram", role="administrator", display_name="Jimmi"),
            user_row("guest"),
        ]
        self.user_calls: list[tuple] = []
        self.feature_list: list[dict] = [dict(row) for row in FEATURES]
        self.feature_calls: list[tuple[str, bool]] = []
        # What this account has switched off for itself, which is a
        # different thing from what the server has switched off.
        self.features_off: set[str] = set()
        self.my_feature_calls: list[tuple[str, bool]] = []
        self.bundle: dict = dict(BUNDLE)
        self.notes: list[dict] = [dict(note) for note in NOTIFICATIONS]
        self.sync_calls: list[tuple[int, list[str]]] = []
        # Chat: the channels the pane lists, what is in them, and
        # what it was asked to do to them.
        self.channel_list: list[dict] = [dict(row) for row in CHANNELS]
        self.channel_messages: dict[str, list[dict]] = {
            slug: [dict(m) for m in rows] for slug, rows in MESSAGES.items()
        }
        self.sent_messages: list[tuple[str, str]] = []
        self.read_marks: list[tuple[str, int | None]] = []
        self.channel_calls: list[tuple] = []
        # The calendar: what it lists, and what it was asked to change.
        self.calendar_list: list[dict] = [dict(row) for row in CALENDARS]
        self.event_list: list[dict] = [dict(row) for row in EVENTS]
        self.event_calls: list[tuple] = []
        self.calendar_calls: list[tuple] = []

    async def aclose(self) -> None: ...

    async def me(self) -> dict:
        return {"username": "bram", "is_admin": True}

    # What the account signs in with, and what a password change was asked for.
    password = "supersecret1"
    password_calls: list[tuple[str, str]]

    async def change_password(self, current: str, new: str) -> None:
        from cloudmorrow.client.api import ApiError

        self.__dict__.setdefault("password_calls", []).append((current, new))
        if current != self.password:
            raise ApiError("current password is wrong", status_code=403)
        self.password = new

    # -- administration ----------------------------------------------------
    async def users(self) -> list[dict]:
        return list(self.user_list)

    async def create_user(
        self,
        username: str,
        password: str,
        *,
        display_name: str = "",
        role: str = "user",
        user_type: str = "human",
    ) -> dict:
        self.user_calls.append(("create", username, role, user_type))
        fresh = user_row(
            username, role=role, user_type=user_type, display_name=display_name
        )
        self.user_list.append(fresh)
        return fresh

    async def update_user(self, username: str, **fields: object) -> dict:
        self.user_calls.append(("update", username, fields))
        for user in self.user_list:
            if user["username"] == username:
                user.update({k: v for k, v in fields.items() if k != "password"})
                user["is_admin"] = user["role"] == "administrator"
                return user
        raise AssertionError(f"no such user: {username}")

    async def delete_user(self, username: str) -> None:
        self.user_calls.append(("delete", username))
        self.user_list = [u for u in self.user_list if u["username"] != username]

    async def features(self) -> list[dict]:
        return [dict(row) for row in self.feature_list]

    async def my_features(self) -> list[dict]:
        """What this account may switch: what the server offers, and its answer.

        The same narrowing the server does — a feature an administrator has
        switched off is not in the list at all, so a client cannot draw a
        tick box for it.
        """
        return [
            {
                "key": row["key"],
                "label": row["label"],
                "description": row["description"],
                "enabled": row["key"] not in self.features_off,
            }
            for row in self.feature_list
            if row["enabled"]
        ]

    async def set_my_feature(self, key: str, enabled: bool) -> dict:
        self.my_feature_calls.append((key, enabled))
        if enabled:
            self.features_off.discard(key)
        else:
            self.features_off.add(key)
        return next(row for row in await self.my_features() if row["key"] == key)

    async def set_feature(self, key: str, enabled: bool) -> dict:
        self.feature_calls.append((key, enabled))
        for row in self.feature_list:
            if row["key"] == key:
                row["enabled"] = enabled
                row["changed_by"] = "bram"
                return dict(row)
        raise AssertionError(f"no such feature: {key}")

    async def secret_vaults(self) -> list[dict]:
        """Every vault that holds something, the way the server lists them."""
        counts: dict[str, set[str]] = {}
        totals: dict[str, int] = {}
        for (vault, environment), secrets in SECRETS.items():
            if secrets:
                counts.setdefault(vault, set()).add(environment)
                totals[vault] = totals.get(vault, 0) + len(secrets)
        return [
            {
                "vault": vault,
                "secrets": totals[vault],
                "environments": len(environments),
                "updated_at": "2026-09-10T20:27:00",
            }
            for vault, environments in sorted(counts.items())
        ]

    async def secret_environments(self, *, vault: str | None = None) -> list[dict]:
        wanted = vault or self.vault
        return [
            {
                "environment": environment,
                "secrets": len(secrets),
                "updated_at": "2026-09-10T20:27:00",
            }
            for (owner, environment), secrets in sorted(SECRETS.items())
            if owner == wanted and secrets
        ]

    async def secrets(self, environment=None, *, reveal=False, vault=None) -> list[dict]:
        return SECRETS.get((vault or self.vault, environment), [])

    async def read_secret(self, key: str, environment: str, *, vault=None) -> dict:
        self.read_keys.append((key, environment, vault or self.vault))
        return {"key": key, "environment": environment, "value": "the-actual-value"}

    async def tree(self) -> dict:
        """One tree per user — the selected vault does not come into it."""
        return TREE

    async def read(self, path: str) -> dict:
        return {"path": path, "content": "# Architecture\n", "rev": "1-1", "size": 0, "modified": 0}

    async def write(self, path: str, content: str, rev: str | None = None) -> dict:
        return {"path": path, "content": content, "rev": "1-2", "size": 0, "modified": 0}

    async def create_note(self, path: str, content: str = "") -> dict:
        return await self.write(path, content)

    async def upload_image(self, data: bytes, *, filename: str = "") -> dict:
        self.uploads.append((filename, data))
        # Named the way the server names them: the moment, a token, the stem as a slug.
        stem = re.sub(r"[^a-z0-9]+", "-", filename.rsplit(".", 1)[0].lower()).strip("-")
        name = "-".join(part for part in ("20260917-120000-abc123", stem) if part) + ".png"
        return {"name": name, "path": f"img/{name}", "size": len(data), "content_type": "image/png"}

    async def image(self, name: str) -> bytes:
        self.fetched.append(name)
        return PNG_1PX

    async def shares(self) -> list[dict]:
        return list(self.share_list)

    async def get_share(self, name: str) -> dict:
        return next(share for share in self.share_list if share["name"] == name)

    async def share_folders(self) -> dict:
        return {"directory": "/srv/cloudmorrow/notes/Shares", "folders": ["Pictures"]}

    async def create_share(
        self, name: str, *, kind: str = "server", path=None, machine=None, description: str = ""
    ) -> dict:
        self.share_calls.append(("create", name, path, description))
        share = share_row(name, path=path or None, managed=not path, description=description)
        share["kind"] = kind
        share["machine"] = machine or ""
        share["online"] = kind != "machine"
        if kind == "machine":
            share["url"] = ""
        elif path is None:
            share["path"] = f"/srv/cloudmorrow/notes/Shares/{name}"
        self.share_list.append(share)
        return share

    async def delete_share(self, name: str, *, remove_files: bool = False) -> None:
        self.share_calls.append(("delete", name, remove_files))
        self.share_list = [share for share in self.share_list if share["name"] != name]

    async def share_listing(self, name: str, path: str = "") -> dict:
        self.listing_calls.append((name, path))
        folders = self.share_tree.get(name)
        if folders is None or path not in folders:
            raise ApiError("no such folder", status_code=404)
        return {"share": name, "path": path, "entries": [dict(row) for row in folders[path]]}

    async def share_file(self, name: str, path: str) -> bytes:
        self.share_fetches.append(f"{name}/{path}")
        return PNG_1PX

    async def share_thumb(self, name: str, path: str, *, size: int = 256) -> bytes:
        self.share_fetches.append(f"thumb:{name}/{path}@{size}")
        return PNG_1PX

    async def agents(self) -> list[dict]:
        return list(self.agent_list)

    async def jobs(self, agent_id: int, limit: int = 25) -> list[dict]:
        return []

    async def set_agent_sync(self, agent_id: int, bundles: list[str]) -> dict:
        self.sync_calls.append((agent_id, list(bundles)))
        for agent in self.agent_list:
            if agent["id"] == agent_id:
                agent["sync_bundles"] = list(bundles)
                return agent
        raise AssertionError(f"no such agent: {agent_id}")

    async def config_bundle(self, bundle: str) -> dict:
        return dict(self.bundle)

    async def notifications(self, *, limit: int = 50, unread: bool = False) -> list[dict]:
        # The bell asks for the unread ones only, so the fake filters like the
        # server rather than handing back everything either way.
        rows = [note for note in self.notes if note["unread"]] if unread else list(self.notes)
        return rows[:limit]

    async def mark_notifications_read(self, ids: list[int] | None = None) -> dict:
        for note in self.notes:
            note["unread"] = False
        return {"marked": len(self.notes), "unread": 0}

    # -- chat ---------------------------------------------------------------
    async def channels(self) -> list[dict]:
        return [dict(row) for row in self.channel_list]

    async def messages(
        self, slug: str, *, limit: int = 50, before: int | None = None,
        after: int | None = None,
    ) -> list[dict]:
        rows = [dict(m) for m in self.channel_messages.get(slug, [])]
        if after is not None:
            rows = [m for m in rows if m["id"] > after]
        return rows[-limit:]

    async def send_message(self, slug: str, body: str) -> dict:
        sent = {
            "id": 100 + len(self.sent_messages),
            "author": "bram",
            "body": body,
            "created_at": "2026-09-19T15:00:00",
            "edited_at": None,
        }
        self.sent_messages.append((slug, body))
        self.channel_messages.setdefault(slug, []).append(sent)
        return sent

    async def mark_channel_read(self, slug: str, upto: int | None = None) -> dict:
        self.read_marks.append((slug, upto))
        for channel in self.channel_list:
            if channel["slug"] == slug:
                channel["unread"] = 0
        return {"last_read": upto or 0, "unread": 0, "total": 0}

    async def chat_unread(self) -> dict:
        waiting = {c["slug"]: c["unread"] for c in self.channel_list if c["unread"]}
        return {"channels": waiting, "total": sum(waiting.values())}

    async def create_channel(self, name, *, kind="private", topic="", members=None) -> dict:
        made = dict(
            CHANNELS[0], slug=name.strip().lower().replace(" ", "-"), name=name.strip(),
            kind=kind, topic=topic, unread=0, members=["bram", *(members or [])],
        )
        self.channel_calls.append(("create", made["slug"], kind, list(members or [])))
        self.channel_list.append(made)
        self.channel_messages[made["slug"]] = []
        return made

    async def direct_channel(self, username: str) -> dict:
        slug = "dm-" + "-".join(sorted(("bram", username)))
        self.channel_calls.append(("direct", slug, username))
        found = next((c for c in self.channel_list if c["slug"] == slug), None)
        if found:
            return found
        made = dict(CHANNELS[1], slug=slug, name=username, other=username, unread=0)
        self.channel_list.append(made)
        self.channel_messages[slug] = []
        return made

    async def chat_people(self) -> list[dict]:
        return [
            {"username": "guest", "display_name": "Guest"},
            {"username": "ada", "display_name": ""},
        ]

    async def add_channel_members(self, slug: str, usernames: list[str]) -> dict:
        self.channel_calls.append(("add", slug, usernames))
        return {"added": usernames, "members": ["bram", *usernames]}

    async def leave_channel(self, slug: str) -> None:
        self.channel_calls.append(("leave", slug, None))
        self.channel_list = [c for c in self.channel_list if c["slug"] != slug]

    # -- the calendar --------------------------------------------------------
    async def calendars(self) -> list[dict]:
        return [dict(row) for row in self.calendar_list]

    async def calendar(self, slug: str) -> dict:
        return next(dict(c) for c in self.calendar_list if c["slug"] == slug)

    async def events(self, *, start: str, end: str, calendar: str | None = None) -> list[dict]:
        """Filtered the way the server filters: whatever overlaps the window."""
        last = f"{end}T23:59"
        rows = [
            dict(event)
            for event in self.event_list
            if event["starts_at"] <= last
            and event["ends_at"] >= start
            and (calendar is None or event["calendar"] == calendar)
        ]
        return sorted(rows, key=lambda e: e["starts_at"])

    async def create_event(self, slug: str, **fields: object) -> dict:
        self.event_calls.append(("create", slug, fields))
        made = event_row(
            max((e["id"] for e in self.event_list), default=0) + 1,
            str(fields["title"]),
            slug,
            str(fields["starts_at"]),
            str(fields.get("ends_at") or fields["starts_at"]),
            all_day=bool(fields.get("all_day")),
            location=str(fields.get("location") or ""),
            notes=str(fields.get("notes") or ""),
        )
        self.event_list.append(made)
        return made

    async def edit_event(self, event_id: int, **fields: object) -> dict:
        self.event_calls.append(("edit", event_id, fields))
        for event in self.event_list:
            if event["id"] == event_id:
                event.update({k: v for k, v in fields.items() if v is not None})
                return dict(event)
        raise AssertionError(f"no such event: {event_id}")

    async def delete_event(self, event_id: int) -> None:
        self.event_calls.append(("delete", event_id, None))
        self.event_list = [e for e in self.event_list if e["id"] != event_id]

    async def create_calendar(self, name: str, *, kind: str = "shared", colour: str = "",
                              members: list[str] | None = None) -> dict:
        slug = name.strip().lower().replace(" ", "-")
        self.calendar_calls.append(("create", slug, kind))
        made = calendar_row(slug, name.strip(), kind, colour or "amber")
        self.calendar_list.append(made)
        return made

    async def update_calendar(self, slug: str, **fields: object) -> dict:
        self.calendar_calls.append(("update", slug, fields))
        for calendar in self.calendar_list:
            if calendar["slug"] == slug:
                calendar.update({k: v for k, v in fields.items() if v is not None})
                return dict(calendar)
        raise AssertionError(f"no such calendar: {slug}")

    async def add_calendar_members(self, slug: str, usernames: list[str]) -> dict:
        self.calendar_calls.append(("share", slug, usernames))
        return {"added": usernames, "members": ["bram", *usernames]}

    async def leave_calendar(self, slug: str) -> None:
        self.calendar_calls.append(("leave", slug, None))
        self.calendar_list = [c for c in self.calendar_list if c["slug"] != slug]

    async def delete_calendar(self, slug: str) -> None:
        self.calendar_calls.append(("delete", slug, None))
        self.calendar_list = [c for c in self.calendar_list if c["slug"] != slug]
        self.event_list = [e for e in self.event_list if e["calendar"] != slug]

    async def calendar_people(self) -> list[dict]:
        return [{"username": "guest", "display_name": ""}]


# A Button ignores a second click while its press animation is running, so
# clicking the same button twice has to wait that out.
PRESS_ANIMATION = 0.3


async def settle(app: CloudmorrowApp, pilot, *, delay: float = 0) -> None:
    """Let the click land, and let the workers it started finish."""
    await pilot.pause(delay) if delay else await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def start(app: CloudmorrowApp, pilot) -> WorkspaceScreen:
    await app.switch_screen(WorkspaceScreen())
    await settle(app, pilot)
    return app.screen


async def open_secrets(app: CloudmorrowApp, pilot) -> WorkspaceScreen:
    """Start, then click over to Secrets — the app lands on Notes."""
    screen = await start(app, pilot)
    await pilot.click("#nav-secrets")
    await settle(app, pilot)
    return screen




def said(screen) -> str:
    """Everything the workspace has said: the log along the bottom, and the
    note at the right of the pane on show — where a message lands, once."""
    from cloudmorrow.tui.widgets.logstrip import LogStrip

    lines = [line.text for line in screen.query_one(LogStrip).lines]
    pane = screen.active_pane
    if screen.admin_showing:
        pane = screen.query_one("#admin-view").active_view
    if pane is not None and pane.note:
        lines.append(pane.note)
    return "\n".join(lines)
