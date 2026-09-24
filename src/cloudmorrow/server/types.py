"""The kinds of data there are, and who provides and reaches each.

This is the foundation the platform is being built on: data is the
person's, not an app's. A note is a *note* whichever app wrote it; a
contact an app introduces tomorrow is a *contact*, there for every other
app the person lets at it. So the kinds are catalogued here, in one place,
with their fields, their scopes, and which app stores them today —
because until the record store exists, each is still kept by the app that
grew it, and the catalogue is the truth about that.

Two kinds of entry:

* **Foundation** types the server itself owns: users, secrets, files,
  machines, notifications. No app may switch these off; every app that
  wants one asks for it.
* **App** types an included app provides — notes, boards and tasks,
  calendars and events, channels and messages. Switching the app off takes
  its type with it, for now. When the same type is stored by the platform
  rather than by the app, that stops being true, and this catalogue is
  where the change shows.

Everything here is metadata. Nothing enforces yet; `used_by` and
`assistant` say what reaches what, so that when the gate arrives it has
something to be checked against.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FOUNDATION = "foundation"

# What a field may be. Small on purpose: a vocabulary a manifest can be
# written against, and every client can draw.
FIELD_KINDS = frozenset(
    {"string", "text", "markdown", "bool", "int", "datetime", "date", "json", "file", "ref"}
)

# Who may see a record of the type: exactly one person, a named set of
# members, or everybody on the server. The three that chat and calendar
# already use, made the rule for everything.
SCOPES = frozenset({"personal", "shared", "public"})


@dataclass(frozen=True, slots=True)
class Field:
    name: str
    kind: str
    description: str = ""
    # `ref` fields point at another type: an event's calendar, a task's board.
    ref: str = ""

    def to_dict(self) -> dict:
        row = {"name": self.name, "kind": self.kind, "description": self.description}
        if self.ref:
            row["ref"] = self.ref
        return row


@dataclass(frozen=True, slots=True)
class DataType:
    key: str
    label: str
    description: str
    # Which app stores it today, by feature key, or FOUNDATION for the
    # server's own.
    provided_by: str
    scopes: tuple[str, ...]
    fields: tuple[Field, ...]
    # The fields that are ciphertext at rest. What is not here is what the
    # server needs in the clear to find, sort or list by.
    sealed: tuple[str, ...] = ()
    # Whether an assistant let in over MCP can reach records of this type,
    # as the person. Secrets never; that is the point of the flag.
    assistant: bool = False

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "provided_by": self.provided_by,
            "foundation": self.provided_by == FOUNDATION,
            "scopes": list(self.scopes),
            "fields": [f.to_dict() for f in self.fields],
            "sealed": list(self.sealed),
            "assistant": self.assistant,
        }


def _f(name: str, kind: str, description: str = "", ref: str = "") -> Field:
    return Field(name, kind, description, ref)


TYPES: tuple[DataType, ...] = (
    # -- the foundation -----------------------------------------------------
    DataType(
        "user",
        "User",
        "An account on this server: a person, an agent, or the machinery itself.",
        FOUNDATION,
        ("public",),
        (
            _f("username", "string"),
            _f("display_name", "string"),
            _f("role", "string", "administrator, user or dashboard_displayer"),
            _f("user_type", "string", "human, agent or systems_user"),
            _f("is_active", "bool"),
        ),
    ),
    DataType(
        "secret",
        "Secret",
        "A key or password, in a vault and an environment, sealed at rest.",
        FOUNDATION,
        ("personal",),
        (
            _f("vault", "string", "The vault it is in; `default` unless named."),
            _f("environment", "string", "local, production, or whatever it is called."),
            _f("key", "string", "The variable name."),
            _f("value", "string", "The secret itself. Never in a listing."),
        ),
        sealed=("value",),
        assistant=False,
    ),
    DataType(
        "file",
        "File",
        "A file in the person's own drive, or in a share.",
        FOUNDATION,
        ("personal", "shared"),
        (
            _f("path", "string"),
            _f("size", "int"),
            _f("modified", "datetime"),
            _f("mime", "string"),
        ),
    ),
    DataType(
        "share",
        "Share",
        "A named folder served over WebDAV, on the server or on one of your machines.",
        FOUNDATION,
        ("personal",),
        (
            _f("name", "string"),
            _f("kind", "string", "server or machine"),
            _f("url", "string"),
        ),
    ),
    DataType(
        "machine",
        "Machine",
        "One of your machines, running the local agent.",
        FOUNDATION,
        ("personal",),
        (
            _f("name", "string"),
            _f("hostname", "string"),
            _f("platform", "string"),
            _f("last_seen", "datetime"),
        ),
    ),
    DataType(
        "notification",
        "Notification",
        "Something that happened, kept until you have read it.",
        FOUNDATION,
        ("personal",),
        (
            _f("kind", "string"),
            _f("title", "string"),
            _f("body", "text"),
            _f("read", "bool"),
        ),
        sealed=("title", "body"),
    ),
    # -- what the included apps keep ----------------------------------------
    DataType(
        "note",
        "Note",
        "Markdown, in a folder, with pictures. A file on the server.",
        "notes",
        ("personal",),
        (
            _f("path", "string", "The title, as a file name; slashes are folders."),
            _f("content", "markdown"),
            _f("modified", "datetime"),
        ),
        sealed=("content",),
        assistant=True,
    ),
    DataType(
        "board",
        "Board",
        "A set of tasks with three lanes: todo, doing, done.",
        "tasks",
        ("personal",),
        (_f("slug", "string"), _f("title", "string")),
        sealed=("title",),
        assistant=True,
    ),
    DataType(
        "task",
        "Task",
        "One thing to do, on a board, in a lane.",
        "tasks",
        ("personal",),
        (
            _f("board", "ref", ref="board"),
            _f("title", "string"),
            _f("body", "markdown", "Detail, and `- [ ]` subtasks."),
            _f("lane", "string", "todo, doing or done"),
            _f("position", "int"),
        ),
        sealed=("title", "body"),
        assistant=True,
    ),
    DataType(
        "calendar",
        "Calendar",
        "Your own, one you share, or everybody's.",
        "calendar",
        ("personal", "shared", "public"),
        (_f("slug", "string"), _f("name", "string"), _f("colour", "string")),
    ),
    DataType(
        "event",
        "Event",
        "A title and two moments, on a calendar. Times are wall-clock times.",
        "calendar",
        ("personal", "shared", "public"),
        (
            _f("calendar", "ref", ref="calendar"),
            _f("title", "string"),
            _f("starts_at", "datetime"),
            _f("ends_at", "datetime"),
            _f("all_day", "bool"),
            _f("location", "string"),
            _f("notes", "text"),
        ),
        sealed=("title", "notes", "location"),
    ),
    DataType(
        "channel",
        "Channel",
        "A public room, a private one, or the line between two people.",
        "chat",
        ("shared", "public"),
        (_f("slug", "string"), _f("name", "string"), _f("kind", "string"), _f("topic", "string")),
        sealed=("topic",),
    ),
    DataType(
        "message",
        "Message",
        "What somebody said in a channel.",
        "chat",
        ("shared", "public"),
        (
            _f("channel", "ref", ref="channel"),
            _f("author", "ref", ref="user"),
            _f("body", "text"),
            _f("sent_at", "datetime"),
        ),
        sealed=("body",),
    ),
)

BY_KEY: dict[str, DataType] = {t.key: t for t in TYPES}
TYPE_KEYS: tuple[str, ...] = tuple(t.key for t in TYPES)


def _check() -> None:
    """The catalogue is code, so it is checked when it is imported."""
    for t in TYPES:
        assert t.scopes and set(t.scopes) <= SCOPES, t.key
        names = [f.name for f in t.fields]
        assert len(names) == len(set(names)), t.key
        for f in t.fields:
            assert f.kind in FIELD_KINDS, (t.key, f.name, f.kind)
            assert (f.kind == "ref") == bool(f.ref), (t.key, f.name)
            assert not f.ref or f.ref in BY_KEY, (t.key, f.name, f.ref)
        assert set(t.sealed) <= set(names), t.key
    assert not BY_KEY["secret"].assistant


_check()


@dataclass(frozen=True, slots=True)
class Access:
    """Who reaches a type today: the apps that use it, and the assistant."""

    used_by: tuple[str, ...] = field(default_factory=tuple)


def catalogue(uses: dict[str, tuple[str, ...]]) -> list[dict]:
    """Every type, with which apps use it.

    *uses* is each app's declared types, by feature key — what
    `features.FEATURES` says. An app that provides a type uses it too, so
    it is on the list whether or not it said so.
    """
    listed = []
    for t in TYPES:
        by = sorted(
            {app for app, wanted in uses.items() if t.key in wanted}
            | ({t.provided_by} if t.provided_by != FOUNDATION else set())
        )
        row = t.to_dict()
        row["used_by"] = by
        listed.append(row)
    return listed
