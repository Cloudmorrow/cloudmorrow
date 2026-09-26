"""The record store: every Quill's data, in one table, sealed, behind one gate.

A record is one piece of data of one datamodel — this task, that board. It
carries the same envelope whichever Quill wrote it (see docs/QUILLS.md), and
it is stored the same way: the fields the datamodel marks `indexed` plain in
a JSON column, so the server can filter and sort on them, and everything else
sealed in `body`, bound to the datamodel, the owner and the record's id so a
row moved in the database opens as nothing.

What the store does for every datamodel, so no Quill has to:

* checks and fills fields from the datamodel: kinds, required, defaults,
  enum values, links that point at a record of the right datamodel you own;
* keeps positions inside each group of `ordered_within` as 0..n-1, which is
  what a board's lanes and a list's order are;
* stamps a datetime when another field takes a value, and clears it when it
  leaves — how a task knows when it was finished;
* bumps `rev` on every write, and refuses a write that names an older one;
* cascades a delete along links that say `on_delete = "cascade"`, and clears
  those that say `clear`;
* sweeps records an `expire` job would take, when their datamodel is read;
* writes every change to `record_changes`, the feed sync and audit read.

The gate is `check`: who is asking, what they want to do, to which datamodel.
Then *which records*: a record of a plain datamodel is its owner's alone; a
record of a space (a calendar, a channel) is its owner's, its members' or
everybody's, by its scope; a record in a space (an event, a message) is for
whoever may see the space. Every read and write finds the row first and
asks `_visible` second, so there is one door and nothing reaches past it.

A record in a space is sealed to the space rather than to whoever wrote it,
so a message moved into another channel by editing the database opens as
nothing, and nobody's leaving takes the conversation with them.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import secrets
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from cloudmorrow.server.datamodels import Datamodel, Field, parse_duration
from cloudmorrow.server.db import Connection, connect

__all__ = [
    "Principal",
    "Record",
    "RecordConflictError",
    "RecordError",
    "RecordStore",
    "Refused",
    "UnknownModelError",
    "UnknownRecordError",
    "check",
    "parse_duration",
]

TABLE = """
CREATE TABLE IF NOT EXISTS records (
    id         TEXT    PRIMARY KEY,
    model      TEXT    NOT NULL,
    owner      TEXT    NOT NULL,
    scope      TEXT    NOT NULL DEFAULT 'personal',
    rev        INTEGER NOT NULL DEFAULT 1,
    -- 0..n-1 inside the record's group, for a datamodel that is ordered.
    position   INTEGER NOT NULL DEFAULT 0,
    -- The fields the datamodel marks indexed, plain, as JSON.
    indexed    TEXT    NOT NULL DEFAULT '{}',
    -- Every other field, as JSON, sealed.
    body       TEXT,
    -- Which Quill wrote it last: a fact for the audit line, not ownership.
    written_by TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS records_model_owner ON records (model, owner, position);
CREATE TABLE IF NOT EXISTS record_changes (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    model      TEXT    NOT NULL,
    record_id  TEXT    NOT NULL,
    owner      TEXT    NOT NULL,
    -- created, changed, moved, deleted, expired
    action     TEXT    NOT NULL,
    rev        INTEGER NOT NULL,
    by_kind    TEXT    NOT NULL,
    by_name    TEXT    NOT NULL,
    at         TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS record_changes_owner ON record_changes (owner, seq);
CREATE TABLE IF NOT EXISTS record_members (
    -- The people in a shared space, besides its owner.
    space_id   TEXT    NOT NULL,
    username   TEXT    NOT NULL,
    added_by   TEXT    NOT NULL DEFAULT '',
    joined_at  TEXT    NOT NULL,
    PRIMARY KEY (space_id, username)
);
CREATE INDEX IF NOT EXISTS record_members_user ON record_members (username);
CREATE TABLE IF NOT EXISTS record_seen (
    -- When somebody last looked in a space: what is newer is unread.
    space_id   TEXT    NOT NULL,
    username   TEXT    NOT NULL,
    seen_at    TEXT    NOT NULL,
    PRIMARY KEY (space_id, username)
);
"""


class RecordError(ValueError):
    """What was sent does not fit the datamodel."""


class UnknownModelError(LookupError):
    pass


class UnknownRecordError(LookupError):
    pass


class RecordConflictError(RuntimeError):
    """The record changed since the revision the caller had."""

    def __init__(self, current: Record) -> None:
        super().__init__(f"record is at rev {current.rev}")
        self.current = current


class Refused(PermissionError):
    """The gate said no."""


# -- who is asking -------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Principal:
    """A person, an assistant acting as one, or a Quill acting for one.

    Every principal acts for an account: the records it reaches are that
    account's. What differs is what it may reach of them.
    """

    kind: str  # person, assistant, quill
    username: str
    # For a Quill: its id, and the datamodels it declared or was granted.
    quill: str = ""
    models: frozenset[str] = field(default_factory=frozenset)
    # An administrator may manage any shared or public space, as on a server
    # they are responsible for; it lets them see no personal record.
    admin: bool = False

    @classmethod
    def person(cls, username: str, *, admin: bool = False) -> Principal:
        return cls("person", username, admin=admin)

    @classmethod
    def assistant(cls, username: str, *, admin: bool = False) -> Principal:
        return cls("assistant", username, admin=admin)

    @property
    def writer(self) -> str:
        return self.quill or self.kind


# Datamodels no assistant is ever let at, whatever the person allows.
NEVER_FOR_ASSISTANTS = frozenset({"secret"})

ACTIONS = frozenset({"read", "write"})


def check(principal: Principal, action: str, model: str) -> None:
    """The gate. Raises Refused, or returns having said yes.

    Personal scope means a principal only ever reaches its own account's
    records, and that is enforced by the store taking the owner from the
    principal rather than from the request. What is decided here is the
    rest: which datamodels each kind of principal may touch at all.
    """
    if action not in ACTIONS:
        raise Refused(f"no such action: {action}")
    if principal.kind == "assistant" and model in NEVER_FOR_ASSISTANTS:
        raise Refused(f"assistants never reach {model}")
    if principal.kind == "quill" and model not in principal.models:
        raise Refused(f"{principal.quill} did not ask for {model}")


# -- the envelope --------------------------------------------------------------
@dataclass(slots=True)
class Record:
    id: str
    model: str
    owner: str
    scope: str
    # A counter in the record store; whatever a backend versions by otherwise
    # (a note's is a hash of the file).
    rev: int | str
    position: int
    fields: dict
    written_by: str
    created_at: str
    updated_at: str
    expires_at: str | None = None
    # For a space: who is in it, whether the asker may manage it, and how
    # many things written in it they have not seen.
    members: list[str] | None = None
    can_manage: bool = False
    unread: int = 0

    def to_dict(self) -> dict:
        extra: dict = {}
        if self.members is not None:
            extra = {"members": list(self.members), "can_manage": self.can_manage, "unread": self.unread}
        return extra | {
            "id": self.id,
            "model": self.model,
            "owner": self.owner,
            "scope": self.scope,
            "rev": self.rev,
            "position": self.position,
            "fields": dict(self.fields),
            "written_by": self.written_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
        }


# -- time ----------------------------------------------------------------------
def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def _stamp(moment: dt.datetime | None = None) -> str:
    return (moment or _now()).isoformat(timespec="seconds")


def _parse_moment(value: str) -> dt.datetime | None:
    try:
        moment = dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)


# -- fields --------------------------------------------------------------------
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _coerce(model: Datamodel, f: Field, value: object) -> object:
    """One value, made the kind its field is, or RecordError."""
    if value is None:
        return None
    where = f"{model.id}.{f.name}"
    kind = f.kind
    if kind in ("string", "text", "markdown", "phone", "url", "link"):
        if not isinstance(value, str | int | float):
            raise RecordError(f"{where} is text")
        text = str(value)
        if kind == "string":
            text = text.strip()
        return text
    if kind == "email":
        text = str(value).strip()
        if text and not _EMAIL_RE.match(text):
            raise RecordError(f"{where} is not an email address")
        return text
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false", "1", "0", "yes", "no"):
            return value.lower() in ("true", "1", "yes")
        raise RecordError(f"{where} is true or false")
    if kind == "int":
        if isinstance(value, bool):
            raise RecordError(f"{where} is a whole number")
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise RecordError(f"{where} is a whole number") from None
    if kind == "decimal":
        try:
            return str(float(value)) if not isinstance(value, str) else str(float(value.strip()))
        except (TypeError, ValueError):
            raise RecordError(f"{where} is a number") from None
    if kind == "date":
        try:
            return dt.date.fromisoformat(str(value)).isoformat()
        except ValueError:
            raise RecordError(f"{where} is a date, YYYY-MM-DD") from None
    if kind == "datetime":
        return _wall_or_moment(where, str(value).strip())
    if kind == "enum":
        text = str(value).strip().lower()
        if text not in f.values:
            raise RecordError(f"{where} is one of {', '.join(f.values)}")
        return text
    if kind == "json":
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            raise RecordError(f"{where} is not JSON") from None
        return value
    raise RecordError(f"{where}: unknown kind {kind}")  # pragma: no cover


_BARE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _wall_or_moment(where: str, text: str) -> str:
    """A datetime field's value, kept the way it was meant.

    With a zone it is a moment, and is kept with its zone. Without one it is
    the time on the wall — "the dentist at ten" — and is kept as typed, to
    the minute, converting nothing: that is what a calendar needs, and a
    server guessing a zone for it would move the dentist twice a year. A
    bare date is a whole day, and stays one. ISO sorts the way time does, so
    all three compare as strings, which is what a range filter does.
    """
    if _BARE_DATE_RE.match(text):
        try:
            return dt.date.fromisoformat(text).isoformat()
        except ValueError:
            raise RecordError(f"{where} is a date, YYYY-MM-DD") from None
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        raise RecordError(f"{where} is a date and time, ISO 8601") from None
    if moment.tzinfo is None:
        exact = moment.second or moment.microsecond
        return moment.isoformat(timespec="seconds" if exact else "minutes")
    return moment.isoformat(timespec="seconds")


def _is(value: object, target: str) -> bool:
    """Does a field's value read as *target*? `false` is how TOML says a bool."""
    if isinstance(value, bool):
        return str(value).lower() == target.lower()
    return value is not None and str(value) == target


def _stored_indexed(model: Datamodel) -> set[str]:
    """Links are always plain: they are what cascades and filters find by."""
    return {f.name for f in model.fields if f.indexed or f.kind == "link"}


# `?starts_at__lt=2026-10-01`: a range on an indexed field, for anything
# that asks "between these two" — the events in a month, the invoices in a
# quarter. A field that is missing never matches a range.
RANGES = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">="}


def _filter(key: str) -> tuple[str, str]:
    """A filter's field and its comparison: `due` is equal, `due__gte` is at least."""
    name, sep, suffix = key.rpartition("__")
    if sep and suffix in RANGES:
        return name, RANGES[suffix]
    return key, "IS"


def _new_id() -> str:
    return "r_" + secrets.token_hex(5)


# -- the store -----------------------------------------------------------------
ModelLookup = Callable[[], dict[str, Datamodel]]


class RecordStore:
    """Records of every installed datamodel, in one table.

    *models* returns the datamodels installed right now, by id; the store asks
    it on every call, because installing a Quill changes the answer.
    *expiries* the same for the `expire` jobs: model -> (field, after).
    """

    def __init__(
        self,
        db_path: Path,
        models: ModelLookup,
        expiries: Callable[[], dict[str, tuple[str, dt.timedelta]]] | None = None,
    ) -> None:
        self.db_path = db_path
        self._models = models
        self._expiries = expiries or (lambda: {})
        # Told about a record written in a space whose datamodel notifies:
        # (record, rule, recipients). "*" in recipients means everybody.
        self.on_notify: list[Callable[[Record, dict, list[str]], None]] = []
        # Told when somebody is added to a space: (space, username, by).
        self.on_member_added: list[Callable[[Record, str, str], None]] = []
        # Datamodels served from elsewhere, by backend name (see backends.py).
        self.backends: dict[str, object] = {}
        with connect(self.db_path) as conn:
            conn.executescript(TABLE)
        conn.close()

    # -- lookups ---------------------------------------------------------------
    def model(self, model_id: str) -> Datamodel:
        found = self._models().get(model_id)
        if found is None:
            raise UnknownModelError(model_id)
        return found

    def _backend(self, model: Datamodel):
        """The backend a datamodel is served by, when it is not stored here."""
        found = self.backends.get(model.backend)
        if found is None:
            raise RecordError(f"{model.id} is kept by {model.backend}, which this server does not run")
        return found

    def _seal_scope(self, model: Datamodel, owner: str, record_id: str, indexed: dict) -> tuple:
        """What a record's content is sealed to: its space, or its owner."""
        if model.in_space:
            return (model.id, "space", str(indexed.get(model.in_space) or ""), record_id)
        return (model.id, owner, record_id)

    def _record(
        self, conn: Connection, model: Datamodel, row: sqlite3.Row, asker: Principal | None = None
    ) -> Record:
        fields = json.loads(row["indexed"] or "{}")
        scope = self._seal_scope(model, row["owner"], row["id"], fields)
        body = conn.unseal("records", "body", scope, row["body"])
        if body:
            fields.update(json.loads(body))
        # Fields the datamodel has now and the record predates read as their
        # default; fields the record has that the datamodel dropped are kept,
        # because data is never lost to a changed definition.
        for f in model.fields:
            fields.setdefault(f.name, f.default)
        record = Record(
            id=row["id"],
            model=row["model"],
            owner=row["owner"],
            scope=row["scope"],
            rev=row["rev"],
            position=row["position"],
            fields=fields,
            written_by=row["written_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        expiry = self._expiries().get(model.id)
        if expiry:
            since = _parse_moment(str(fields.get(expiry[0]) or ""))
            if since is not None:
                record.expires_at = _stamp(since + expiry[1])
        if model.space:
            record.members = self._members(conn, row["id"])
            if asker is not None:
                record.can_manage = self._may_manage(asker, row)
                record.unread = self._unread(conn, model, row["id"], asker.username)
        return record

    # -- who may see what --------------------------------------------------------
    def _members(self, conn: Connection, space_id: str) -> list[str]:
        return [
            r["username"]
            for r in conn.execute(
                "SELECT username FROM record_members WHERE space_id = ? ORDER BY joined_at, username",
                (space_id,),
            )
        ]

    @staticmethod
    def _may_manage(principal: Principal, space_row: sqlite3.Row) -> bool:
        if space_row["owner"] == principal.username:
            return True
        return principal.admin and space_row["scope"] != "personal"

    def _space_visible(self, conn: Connection, principal: Principal, space_row: sqlite3.Row) -> bool:
        if space_row["owner"] == principal.username or space_row["scope"] == "public":
            return True
        if space_row["scope"] != "shared":
            return False
        return (
            conn.execute(
                "SELECT 1 FROM record_members WHERE space_id = ? AND username = ?",
                (space_row["id"], principal.username),
            ).fetchone()
            is not None
        )

    def _space_of(self, conn: Connection, model: Datamodel, indexed: dict) -> sqlite3.Row | None:
        space_id = indexed.get(model.in_space)
        if not space_id:
            return None
        return conn.execute("SELECT * FROM records WHERE id = ?", (space_id,)).fetchone()

    def _visible(self, conn: Connection, principal: Principal, model: Datamodel, row: sqlite3.Row) -> bool:
        """The one question: may this principal see this record at all?"""
        if model.space:
            return self._space_visible(conn, principal, row)
        if model.in_space:
            space = self._space_of(conn, model, json.loads(row["indexed"] or "{}"))
            return space is not None and self._space_visible(conn, principal, space)
        return row["owner"] == principal.username

    def _row(
        self, conn: Connection, principal: Principal, model: Datamodel, record_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM records WHERE id = ? AND model = ?", (record_id, model.id)
        ).fetchone()
        # Not there, and there but not yours, are the same answer: a record
        # somebody cannot see is not one they can learn exists.
        if row is None or not self._visible(conn, principal, model, row):
            raise UnknownRecordError(record_id)
        return row

    def _writable(self, conn: Connection, principal: Principal, model: Datamodel, row: sqlite3.Row) -> None:
        """Seeing is not always changing: a space is its manager's, a message its author's."""
        if model.space and not self._may_manage(principal, row):
            raise Refused(f"only whoever made this {model.label.lower()} may change it")
        if model.authored and row["owner"] != principal.username:
            raise Refused(f"only whoever wrote this {model.label.lower()} may change it")

    def _visible_clause(self, model: Datamodel, username: str) -> tuple[str, list[object]]:
        """SQL that keeps the rows of *model* this person may see."""
        spaces = (
            "SELECT id FROM records WHERE model = ? AND (owner = ? OR scope = 'public'"
            " OR (scope = 'shared' AND id IN (SELECT space_id FROM record_members WHERE username = ?)))"
        )
        if model.space:
            return f"id IN ({spaces})", [model.id, username, username]
        if model.in_space:
            space_model = model.get_field(model.in_space).to
            return (
                f"json_extract(indexed, '$.\"{model.in_space}\"') IN ({spaces})",
                [space_model, username, username],
            )
        return "owner = ?", [username]

    def _unread(self, conn: Connection, space_model: Datamodel, space_id: str, username: str) -> int:
        """Things written in a space since this person last looked, by others."""
        count = 0
        for child in self._models().values():
            if child.in_space and child.get_field(child.in_space).to == space_model.id and any(
                rule.get("unread") for rule in child.notify
            ):
                seen = conn.execute(
                    "SELECT seen_at FROM record_seen WHERE space_id = ? AND username = ?",
                    (space_id, username),
                ).fetchone()
                row = conn.execute(
                    "SELECT COUNT(*) FROM records WHERE model = ? AND owner != ?"
                    f" AND json_extract(indexed, '$.\"{child.in_space}\"') = ? AND created_at > ?",
                    (child.id, username, space_id, seen["seen_at"] if seen else ""),
                ).fetchone()
                count += int(row[0])
        return count

    # -- reading ---------------------------------------------------------------
    def list(
        self, principal: Principal, model_id: str, where: dict[str, object] | None = None
    ) -> list[Record]:
        """Every record of *model_id* the principal may see, filtered, in order.

        Filters are on indexed fields and links only: those are what the server
        can see. `name` is equal to; `name__lt`, `__lte`, `__gt` and `__gte`
        are a range. Sweeps what an expire job would take first.
        """
        check(principal, "read", model_id)
        model = self.model(model_id)
        if model.backend:
            return self._backend(model).list(principal, model, dict(where or {}))
        self.sweep(model_id, owner=None if (model.space or model.in_space) else principal.username)
        plain = _stored_indexed(model)
        clause, clause_params = self._visible_clause(model, principal.username)
        query = f"SELECT * FROM records WHERE model = ? AND {clause}"
        params: list[object] = [model.id, *clause_params]
        for key, value in (where or {}).items():
            name, operator = _filter(key)
            if name not in plain:
                raise RecordError(f"{model.id} cannot be filtered by {name!r}: it is not indexed")
            coerced = _coerce(model, model.get_field(name), value)
            query += f" AND json_extract(indexed, ?) {operator} ?"
            params += [f'$."{name}"', coerced if not isinstance(coerced, bool) else int(coerced)]
        query += " ORDER BY position, created_at, id"
        with connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
            records = [self._record(conn, model, row, principal) for row in rows]
        conn.close()
        return records

    def get(self, principal: Principal, model_id: str, record_id: str) -> Record:
        check(principal, "read", model_id)
        model = self.model(model_id)
        if model.backend:
            return self._backend(model).get(principal, model, record_id)
        with connect(self.db_path) as conn:
            record = self._record(conn, model, self._row(conn, principal, model, record_id), principal)
        conn.close()
        return record

    def count(self, owner: str, model_id: str, *, scope: str | None = None) -> int:
        query = "SELECT COUNT(*) FROM records WHERE model = ? AND owner = ?"
        params: list[object] = [model_id, owner]
        if scope:
            query += " AND scope = ?"
            params.append(scope)
        with connect(self.db_path) as conn:
            row = conn.execute(query, params).fetchone()
        conn.close()
        return int(row[0])

    # -- the people in a space -----------------------------------------------------
    def add_member(self, principal: Principal, model_id: str, space_id: str, username: str) -> Record:
        """Put somebody in a shared space. Its manager's to do; no invitation to accept."""
        check(principal, "write", model_id)
        model = self.model(model_id)
        if not model.space:
            raise RecordError(f"a {model.label.lower()} has no members")
        with connect(self.db_path) as conn:
            row = self._row(conn, principal, model, space_id)
            if row["scope"] != "shared":
                raise RecordError(f"only a shared {model.label.lower()} has members")
            if not self._may_manage(principal, row) and not self._space_visible(conn, principal, row):
                raise Refused("only somebody in it may add people")
            added = conn.execute(
                "INSERT OR IGNORE INTO record_members (space_id, username, added_by, joined_at)"
                " VALUES (?, ?, ?, ?)",
                (space_id, username, principal.username, _stamp()),
            ).rowcount
            if username == row["owner"]:
                added = 0
        conn.close()
        space = self.get(principal, model_id, space_id)
        if added:
            for hook in self.on_member_added:
                hook(space, username, principal.username)
        return space

    def remove_member(self, principal: Principal, model_id: str, space_id: str, username: str) -> None:
        """Take somebody out of a shared space: its manager may, and anybody may leave."""
        check(principal, "write", model_id)
        model = self.model(model_id)
        with connect(self.db_path) as conn:
            row = self._row(conn, principal, model, space_id)
            if row["scope"] != "shared":
                raise RecordError(f"nobody leaves a {row['scope']} {model.label.lower()}")
            if username != principal.username and not self._may_manage(principal, row):
                raise Refused("only whoever made it may take somebody else out")
            if username == row["owner"]:
                raise RecordError("its owner cannot leave; delete it instead")
            conn.execute(
                "DELETE FROM record_members WHERE space_id = ? AND username = ?", (space_id, username)
            )
        conn.close()

    def mark_seen(self, principal: Principal, model_id: str, space_id: str) -> None:
        """Somebody has looked in a space: what is in it is no longer news to them."""
        model = self.model(model_id)
        with connect(self.db_path) as conn:
            self._row(conn, principal, model, space_id)
            conn.execute(
                "INSERT INTO record_seen (space_id, username, seen_at) VALUES (?, ?, ?)"
                " ON CONFLICT(space_id, username) DO UPDATE SET seen_at = excluded.seen_at",
                (space_id, principal.username, _stamp()),
            )
        conn.close()

    # -- writing ---------------------------------------------------------------
    def _clean(
        self,
        conn: Connection,
        model: Datamodel,
        principal: Principal,
        incoming: dict,
        *,
        current: dict | None,
    ) -> dict:
        """The record's fields after *incoming* is applied to *current*."""
        fields = dict(current or {})
        known = model.by_name
        for name in incoming:
            if name not in known:
                raise RecordError(f"{model.id} has no field {name!r}")
            if known[name].stamp_field:
                raise RecordError(f"{model.id}.{name} is set by the server")
        for name, value in incoming.items():
            fields[name] = _coerce(model, known[name], value)
        if current is None:
            for f in model.fields:
                if fields.get(f.name) is None and f.default is not None:
                    fields[f.name] = _coerce(model, f, f.default)
        for f in model.fields:
            value = fields.get(f.name)
            if f.required and (value is None or value == ""):
                raise RecordError(f"{model.id}.{f.name} is required")
            if f.kind == "link" and value:
                target = conn.execute(
                    "SELECT * FROM records WHERE id = ? AND model = ?", (value, f.to)
                ).fetchone()
                # A link only reaches what its writer may see: nobody puts a
                # task on somebody else's board, or a message in a channel
                # they are not in.
                if target is None or not self._visible(conn, principal, self.model(f.to), target):
                    raise RecordError(f"{model.id}.{f.name}: no {f.to} {value!r}")
        # Stamps: set on entering the value, kept while it stays, cleared on leaving.
        for f in model.fields:
            if not f.stamp_field:
                continue
            now_in = _is(fields.get(f.stamp_field), f.stamp_value)
            was_in = current is not None and _is(current.get(f.stamp_field), f.stamp_value)
            if now_in and not (was_in and fields.get(f.name)):
                fields[f.name] = _stamp()
            elif not now_in:
                fields[f.name] = None
        return fields

    def _split(self, model: Datamodel, fields: dict) -> tuple[dict, dict]:
        plain = _stored_indexed(model)
        return (
            {k: v for k, v in fields.items() if k in plain},
            {k: v for k, v in fields.items() if k not in plain},
        )

    def _group(self, model: Datamodel, fields: dict) -> tuple:
        return tuple(fields.get(name) for name in model.ordered_within)

    def _group_ids(self, conn: Connection, model: Datamodel, owner: str, group: tuple) -> list[str]:
        # A shared thing's order is everybody's, so only a personal one's
        # group is narrowed to its owner.
        if model.space or model.in_space:
            query, params = "SELECT id FROM records WHERE model = ?", [model.id]
        else:
            query = "SELECT id FROM records WHERE model = ? AND owner = ?"
            params = [model.id, owner]
        for name, value in zip(model.ordered_within, group, strict=True):
            query += " AND json_extract(indexed, ?) IS ?"
            params += [f'$."{name}"', value]
        query += " ORDER BY position, created_at, id"
        return [row["id"] for row in conn.execute(query, params)]

    def _renumber(
        self,
        conn: Connection,
        model: Datamodel,
        owner: str,
        group: tuple,
        *,
        moved: str | None = None,
        insert_at: int | None = None,
    ) -> None:
        ids = self._group_ids(conn, model, owner, group)
        if moved is not None and insert_at is not None and moved in ids:
            ids.remove(moved)
            ids.insert(max(0, min(insert_at, len(ids))), moved)
        for position, record_id in enumerate(ids):
            conn.execute("UPDATE records SET position = ? WHERE id = ?", (position, record_id))

    def _write_row(
        self, conn: Connection, model: Datamodel, owner: str, record_id: str, fields: dict
    ) -> tuple[str, str]:
        indexed, rest = self._split(model, fields)
        scope = self._seal_scope(model, owner, record_id, indexed)
        body = conn.seal("records", "body", scope, json.dumps(rest))
        return json.dumps(indexed), body or ""

    def _log(
        self,
        conn: Connection,
        principal: Principal,
        model: str,
        record_id: str,
        action: str,
        rev: int,
    ) -> None:
        conn.execute(
            "INSERT INTO record_changes (model, record_id, owner, action, rev, by_kind, by_name, at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                model,
                record_id,
                principal.username,
                action,
                rev,
                principal.kind,
                principal.quill or principal.username,
                _stamp(),
            ),
        )

    def create(
        self,
        principal: Principal,
        model_id: str,
        incoming: dict,
        *,
        index: int | None = None,
        scope: str | None = None,
    ) -> Record:
        check(principal, "write", model_id)
        model = self.model(model_id)
        if model.backend:
            return self._backend(model).create(principal, model, dict(incoming))
        owner = principal.username
        record_id = _new_id()
        now = _stamp()
        scope = self._scope_for(model, scope)
        with connect(self.db_path) as conn:
            fields = self._clean(conn, model, principal, incoming, current=None)
            indexed, body = self._write_row(conn, model, owner, record_id, fields)
            position = 0
            if model.ordered:
                position = len(self._group_ids(conn, model, owner, self._group(model, fields)))
            conn.execute(
                "INSERT INTO records (id, model, owner, scope, rev, position, indexed, body,"
                " written_by, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)",
                (record_id, model.id, owner, scope, position, indexed, body, principal.writer, now, now),
            )
            if model.ordered and index is not None:
                self._renumber(
                    conn, model, owner, self._group(model, fields), moved=record_id, insert_at=index
                )
            self._log(conn, principal, model.id, record_id, "created", 1)
            recipients = self._recipients(conn, model, fields, owner) if model.notify else []
        conn.close()
        made = self.get(principal, model.id, record_id)
        for rule in model.notify:
            for hook in self.on_notify:
                hook(made, rule, recipients)
        return made

    def _scope_for(self, model: Datamodel, asked: str | None) -> str:
        """A space's scope is chosen when it is made; everything else is personal."""
        if not model.space:
            if asked not in (None, "", "personal"):
                raise RecordError(f"a {model.label.lower()} is not a space; it has no scope to choose")
            return "personal"
        if asked in (None, ""):
            return "shared" if "shared" in model.scopes else model.scopes[0]
        if asked not in model.scopes:
            raise RecordError(f"a {model.label.lower()} is {', '.join(model.scopes)}")
        return asked

    def _recipients(self, conn: Connection, model: Datamodel, fields: dict, writer: str) -> list[str]:
        """Who a record written in a space is news to: its people, not its writer."""
        space = self._space_of(conn, model, fields)
        if space is None:
            return []
        if space["scope"] == "public":
            return ["*"]
        people = {space["owner"], *self._members(conn, space["id"])}
        people.discard(writer)
        return sorted(people)

    def update(
        self,
        principal: Principal,
        model_id: str,
        record_id: str,
        incoming: dict,
        *,
        rev: int | str | None = None,
        index: int | None = None,
        action: str = "changed",
    ) -> Record:
        """Change fields. With *index*, also where it sits in its group.

        A change to a field in `ordered_within` moves the record to the end of
        its new group unless *index* says where; its old group closes up.
        """
        check(principal, "write", model_id)
        model = self.model(model_id)
        if model.backend:
            return self._backend(model).update(principal, model, record_id, dict(incoming), rev)
        with connect(self.db_path) as conn:
            # Read and write under one lock, so two writers cannot both pass
            # the revision check. Anything raised below rolls the lot back.
            conn.execute("BEGIN IMMEDIATE")
            row = self._row(conn, principal, model, record_id)
            self._writable(conn, principal, model, row)
            owner = row["owner"]
            current = self._record(conn, model, row, principal)
            if rev is not None and rev != current.rev:
                raise RecordConflictError(current)
            fields = self._clean(conn, model, principal, incoming, current=current.fields)
            indexed, body = self._write_row(conn, model, owner, record_id, fields)
            old_group = self._group(model, current.fields)
            new_group = self._group(model, fields)
            position = current.position
            if model.ordered and old_group != new_group:
                position = len(self._group_ids(conn, model, owner, new_group))
            conn.execute(
                "UPDATE records SET indexed = ?, body = ?, rev = rev + 1, position = ?,"
                " written_by = ?, updated_at = ? WHERE id = ?",
                (indexed, body, position, principal.writer, _stamp(), record_id),
            )
            if model.ordered:
                if old_group != new_group:
                    self._renumber(conn, model, owner, old_group)
                if old_group != new_group or index is not None:
                    self._renumber(conn, model, owner, new_group, moved=record_id, insert_at=index)
            self._log(conn, principal, model.id, record_id, action, current.rev + 1)
            conn.commit()
        conn.close()
        return self.get(principal, model.id, record_id)

    def move(
        self, principal: Principal, model_id: str, record_id: str, incoming: dict, index: int | None
    ) -> Record:
        """Put a record in a group, at *index* in it: what dragging a card is."""
        return self.update(principal, model_id, record_id, incoming, index=index, action="moved")

    # -- content: the bytes beside a record, for a backend that keeps some ------
    def has_content(self, model_id: str) -> bool:
        """Whether records of *model_id* have bytes beside their fields: a file's."""
        model = self.model(model_id)
        return bool(model.backend) and callable(
            getattr(self.backends.get(model.backend), "content", None)
        )

    def _content_backend(self, model: Datamodel):
        backend = self._backend(model) if model.backend else None
        if backend is None or not callable(getattr(backend, "content", None)):
            raise RecordError(f"a {model.label.lower()} has no content beside its fields")
        return backend

    def content(self, principal: Principal, model_id: str, record_id: str):
        """(path, media type) of a record's bytes."""
        check(principal, "read", model_id)
        model = self.model(model_id)
        return self._content_backend(model).content(principal, model, record_id)

    def thumbnail(self, principal: Principal, model_id: str, record_id: str, size: int):
        """The path of a small copy of a record's picture."""
        check(principal, "read", model_id)
        model = self.model(model_id)
        return self._content_backend(model).thumbnail(principal, model, record_id, size)

    def put(self, principal: Principal, model_id: str, fields: dict, source) -> Record:
        """A new record from bytes that have arrived at *source*, and *fields* saying where."""
        check(principal, "write", model_id)
        model = self.model(model_id)
        return self._content_backend(model).put(principal, model, dict(fields), source)

    def delete(self, principal: Principal, model_id: str, record_id: str) -> int:
        """Delete a record, and follow links that cascade. Returns how many went."""
        check(principal, "write", model_id)
        model = self.model(model_id)
        if model.backend:
            return self._backend(model).delete(principal, model, record_id)
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._row(conn, principal, model, record_id)
            self._writable(conn, principal, model, row)
            gone = self._delete(conn, principal, model, record_id, "deleted")
            conn.commit()
        conn.close()
        return gone

    def _delete(
        self, conn: Connection, principal: Principal, model: Datamodel, record_id: str, action: str
    ) -> int:
        row = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            return 0
        owner = row["owner"]
        group = self._group(model, json.loads(row["indexed"] or "{}")) if model.ordered else ()
        conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
        if model.space:
            conn.execute("DELETE FROM record_members WHERE space_id = ?", (record_id,))
            conn.execute("DELETE FROM record_seen WHERE space_id = ?", (record_id,))
        self._log(conn, principal, model.id, record_id, action, row["rev"])
        gone = 1
        if model.ordered:
            self._renumber(conn, model, owner, group)
        for other in self._models().values():
            for f in other.fields:
                if f.kind != "link" or f.to != model.id or not f.on_delete:
                    continue
                # Whoever wrote them: a channel deleted takes everybody's
                # messages in it, not only its owner's.
                pointing = [
                    r["id"]
                    for r in conn.execute(
                        "SELECT id FROM records WHERE model = ? AND json_extract(indexed, ?) = ?",
                        (other.id, f'$."{f.name}"', record_id),
                    )
                ]
                for child in pointing:
                    if f.on_delete == "cascade":
                        gone += self._delete(conn, principal, other, child, action)
                    else:
                        child_row = conn.execute(
                            "SELECT indexed FROM records WHERE id = ?", (child,)
                        ).fetchone()
                        indexed = json.loads(child_row["indexed"] or "{}")
                        indexed[f.name] = None
                        conn.execute(
                            "UPDATE records SET indexed = ?, rev = rev + 1 WHERE id = ?",
                            (json.dumps(indexed), child),
                        )
        return gone

    # -- what runs by itself ---------------------------------------------------
    def sweep(self, model_id: str, *, owner: str | None = None) -> int:
        """Delete records an `expire` job would take. Returns how many went."""
        expiry = self._expiries().get(model_id)
        if not expiry:
            return 0
        field_name, after = expiry
        model = self.model(model_id)
        cutoff = _stamp(_now() - after)
        query = (
            "SELECT id, owner FROM records WHERE model = ?"
            " AND json_extract(indexed, ?) IS NOT NULL AND json_extract(indexed, ?) < ?"
        )
        params: list[object] = [model_id, f'$."{field_name}"', f'$."{field_name}"', cutoff]
        if owner is not None:
            query += " AND owner = ?"
            params.append(owner)
        gone = 0
        with connect(self.db_path) as conn:
            for row in conn.execute(query, params).fetchall():
                who = Principal("quill", row["owner"], quill="core")
                gone += self._delete(conn, who, model, row["id"], "expired")
        conn.close()
        return gone

    def seed(
        self,
        principal: Principal,
        model_id: str,
        records: Iterable[dict],
        writer: str,
        *,
        once: bool = False,
        scope: str | None = None,
    ) -> list[Record]:
        """Write *records* for *principal* if they have none of *model_id* yet.

        With *once*, if the server has none of it yet, from anybody: the public
        calendar, `#general`. With *scope*, of that scope, for a space.
        """
        if once:
            with connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT 1 FROM records WHERE model = ? AND scope = ? LIMIT 1",
                    (model_id, scope or "personal"),
                ).fetchone()
            conn.close()
            if row is not None:
                return []
        elif self.count(principal.username, model_id, scope=scope):
            return []
        who = Principal("quill", principal.username, quill=writer, models=frozenset({model_id}))
        made = []
        for fields in records:
            filled = {
                key: (
                    value.replace("{owner}", principal.username)
                    if isinstance(value, str)
                    else value
                )
                for key, value in fields.items()
            }
            made.append(self.create(who, model_id, filled, scope=scope))
        return made

    def changes(self, owner: str, since: int = 0, limit: int = 200) -> list[dict]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM record_changes WHERE owner = ? AND seq > ? ORDER BY seq LIMIT ?",
                (owner, since, limit),
            ).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def forget(self, owner: str) -> None:
        """Everything an account had, for when the account goes."""
        with connect(self.db_path) as conn:
            conn.execute("DELETE FROM records WHERE owner = ?", (owner,))
            conn.execute("DELETE FROM record_changes WHERE owner = ?", (owner,))
        conn.close()

    def import_row(
        self,
        owner: str,
        model_id: str,
        fields: dict,
        *,
        position: int,
        created_at: str,
        updated_at: str,
        writer: str,
        record_id: str | None = None,
        scope: str = "personal",
        members: Iterable[str] = (),
    ) -> str:
        """A record as it was elsewhere, times and position kept. For migrations."""
        model = self.model(model_id)
        record_id = record_id or _new_id()
        with connect(self.db_path) as conn:
            indexed, body = self._write_row(conn, model, owner, record_id, fields)
            for username in members:
                conn.execute(
                    "INSERT OR IGNORE INTO record_members (space_id, username, added_by, joined_at)"
                    " VALUES (?, ?, ?, ?)",
                    (record_id, username, owner, created_at),
                )
            conn.execute(
                "INSERT INTO records (id, model, owner, scope, rev, position, indexed, body,"
                " written_by, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)",
                (
                    record_id,
                    model.id,
                    owner,
                    scope,
                    position,
                    indexed,
                    body,
                    writer,
                    created_at,
                    updated_at,
                ),
            )
        conn.close()
        return record_id
