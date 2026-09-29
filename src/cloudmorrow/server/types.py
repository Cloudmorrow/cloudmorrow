"""The kinds of data the server itself keeps, and who reaches each.

Data is the person's, not an app's. Most of it is records of a datamodel
now — boards and tasks, calendars and events, notes, channels and messages
— kept in the record store (records.py) whichever Quill wrote them, and
listed at `/api/datamodels` with every other Quill's. Chat's own tables
were moved into records once, at boot (`quills.jobs.move_legacy_chat`),
as the tasks' and the calendar's were.

What is catalogued here is the rest: the **foundation**, the types the
server itself owns — users, secrets, files, shares, machines,
notifications. No Quill may switch these off; one that wants one says so
(`uses`, in features.py), and `/api/types` lists who does. Secrets, shares
and files are served through the record API as well, by a backend
(backends/), in the same envelope as every other record.

Everything here is metadata, for that listing. What a principal may reach
is decided by the gate (`principal.check`); `assistant` says the same thing
here for a person reading the list — secrets never.
"""

from __future__ import annotations

from dataclasses import dataclass

FOUNDATION = "foundation"

# What a field may be. Small on purpose: a vocabulary a manifest can be
# written against, and every client can draw.
FIELD_KINDS = frozenset(
    {"string", "text", "markdown", "bool", "int", "datetime", "date", "json", "file", "ref"}
)

# Who may see a record of the type: exactly one person, a named set of
# members, or everybody on the server: the three a space in the record
# store has, made the rule for everything.
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
    # FOUNDATION for the server's own, which every type is now; an app that
    # kept a type of its own would be named here by its feature key.
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
