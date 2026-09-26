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
Personal scope only, for now; a datamodel that wants more is refused at
install by the Quill loader.
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

    @classmethod
    def person(cls, username: str) -> Principal:
        return cls("person", username)

    @classmethod
    def assistant(cls, username: str) -> Principal:
        return cls("assistant", username)

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
    rev: int
    position: int
    fields: dict
    written_by: str
    created_at: str
    updated_at: str
    expires_at: str | None = None

    def to_dict(self) -> dict:
        return {
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
        moment = _parse_moment(str(value))
        if moment is None:
            raise RecordError(f"{where} is a date and time, ISO 8601")
        return moment.isoformat(timespec="seconds")
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


def _is(value: object, target: str) -> bool:
    """Does a field's value read as *target*? `false` is how TOML says a bool."""
    if isinstance(value, bool):
        return str(value).lower() == target.lower()
    return value is not None and str(value) == target


def _stored_indexed(model: Datamodel) -> set[str]:
    """Links are always plain: they are what cascades and filters find by."""
    return {f.name for f in model.fields if f.indexed or f.kind == "link"}


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
        with connect(self.db_path) as conn:
            conn.executescript(TABLE)
        conn.close()

    # -- lookups ---------------------------------------------------------------
    def model(self, model_id: str) -> Datamodel:
        found = self._models().get(model_id)
        if found is None:
            raise UnknownModelError(model_id)
        return found

    def _record(self, conn: Connection, model: Datamodel, row: sqlite3.Row) -> Record:
        fields = json.loads(row["indexed"] or "{}")
        body = conn.unseal("records", "body", (row["model"], row["owner"], row["id"]), row["body"])
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
        return record

    def _row(self, conn: Connection, owner: str, model: str, record_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM records WHERE id = ? AND model = ? AND owner = ?",
            (record_id, model, owner),
        ).fetchone()
        if row is None:
            raise UnknownRecordError(record_id)
        return row

    # -- reading ---------------------------------------------------------------
    def list(
        self, principal: Principal, model_id: str, where: dict[str, object] | None = None
    ) -> list[Record]:
        """Every record of *model_id* the principal owns, filtered, in order.

        Filters are on indexed fields and links only: those are what the server
        can see. Sweeps what an expire job would take first.
        """
        check(principal, "read", model_id)
        model = self.model(model_id)
        self.sweep(model_id, owner=principal.username)
        plain = _stored_indexed(model)
        query = "SELECT * FROM records WHERE model = ? AND owner = ?"
        params: list[object] = [model.id, principal.username]
        for name, value in (where or {}).items():
            if name not in plain:
                raise RecordError(f"{model.id} cannot be filtered by {name!r}: it is not indexed")
            coerced = _coerce(model, model.get_field(name), value)
            query += " AND json_extract(indexed, ?) IS ?"
            params += [f'$."{name}"', coerced if not isinstance(coerced, bool) else int(coerced)]
        query += " ORDER BY position, created_at, id"
        with connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
            records = [self._record(conn, model, row) for row in rows]
        conn.close()
        return records

    def get(self, principal: Principal, model_id: str, record_id: str) -> Record:
        check(principal, "read", model_id)
        model = self.model(model_id)
        with connect(self.db_path) as conn:
            record = self._record(
                conn, model, self._row(conn, principal.username, model.id, record_id)
            )
        conn.close()
        return record

    def count(self, owner: str, model_id: str) -> int:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM records WHERE model = ? AND owner = ?", (model_id, owner)
            ).fetchone()
        conn.close()
        return int(row[0])

    # -- writing ---------------------------------------------------------------
    def _clean(
        self,
        conn: Connection,
        model: Datamodel,
        owner: str,
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
                    "SELECT 1 FROM records WHERE id = ? AND model = ? AND owner = ?",
                    (value, f.to, owner),
                ).fetchone()
                if target is None:
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
        query = "SELECT id FROM records WHERE model = ? AND owner = ?"
        params: list[object] = [model.id, owner]
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
        body = conn.seal("records", "body", (model.id, owner, record_id), json.dumps(rest))
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
        self, principal: Principal, model_id: str, incoming: dict, *, index: int | None = None
    ) -> Record:
        check(principal, "write", model_id)
        model = self.model(model_id)
        owner = principal.username
        record_id = _new_id()
        now = _stamp()
        with connect(self.db_path) as conn:
            fields = self._clean(conn, model, owner, incoming, current=None)
            indexed, body = self._write_row(conn, model, owner, record_id, fields)
            position = 0
            if model.ordered:
                position = len(self._group_ids(conn, model, owner, self._group(model, fields)))
            conn.execute(
                "INSERT INTO records (id, model, owner, scope, rev, position, indexed, body,"
                " written_by, created_at, updated_at) VALUES (?, ?, ?, 'personal', 1, ?, ?, ?, ?, ?, ?)",
                (record_id, model.id, owner, position, indexed, body, principal.writer, now, now),
            )
            if model.ordered and index is not None:
                self._renumber(
                    conn, model, owner, self._group(model, fields), moved=record_id, insert_at=index
                )
            self._log(conn, principal, model.id, record_id, "created", 1)
        conn.close()
        return self.get(principal, model.id, record_id)

    def update(
        self,
        principal: Principal,
        model_id: str,
        record_id: str,
        incoming: dict,
        *,
        rev: int | None = None,
        index: int | None = None,
        action: str = "changed",
    ) -> Record:
        """Change fields. With *index*, also where it sits in its group.

        A change to a field in `ordered_within` moves the record to the end of
        its new group unless *index* says where; its old group closes up.
        """
        check(principal, "write", model_id)
        model = self.model(model_id)
        owner = principal.username
        with connect(self.db_path) as conn:
            # Read and write under one lock, so two writers cannot both pass
            # the revision check. Anything raised below rolls the lot back.
            conn.execute("BEGIN IMMEDIATE")
            row = self._row(conn, owner, model.id, record_id)
            current = self._record(conn, model, row)
            if rev is not None and rev != current.rev:
                raise RecordConflictError(current)
            fields = self._clean(conn, model, owner, incoming, current=current.fields)
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

    def delete(self, principal: Principal, model_id: str, record_id: str) -> int:
        """Delete a record, and follow links that cascade. Returns how many went."""
        check(principal, "write", model_id)
        model = self.model(model_id)
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._row(conn, principal.username, model.id, record_id)
            gone = self._delete(conn, principal, model, record_id, "deleted")
            conn.commit()
        conn.close()
        return gone

    def _delete(
        self, conn: Connection, principal: Principal, model: Datamodel, record_id: str, action: str
    ) -> int:
        owner = principal.username
        row = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            return 0
        group = self._group(model, json.loads(row["indexed"] or "{}")) if model.ordered else ()
        conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
        self._log(conn, principal, model.id, record_id, action, row["rev"])
        gone = 1
        if model.ordered:
            self._renumber(conn, model, owner, group)
        for other in self._models().values():
            for f in other.fields:
                if f.kind != "link" or f.to != model.id or not f.on_delete:
                    continue
                pointing = [
                    r["id"]
                    for r in conn.execute(
                        "SELECT id FROM records WHERE model = ? AND owner = ?"
                        " AND json_extract(indexed, ?) = ?",
                        (other.id, owner, f'$."{f.name}"', record_id),
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
        self, principal: Principal, model_id: str, records: Iterable[dict], writer: str
    ) -> list[Record]:
        """Write *records* for *principal* if they have none of *model_id* yet."""
        if self.count(principal.username, model_id):
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
            made.append(self.create(who, model_id, filled))
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
    ) -> str:
        """A record as it was elsewhere, times and position kept. For migrations."""
        model = self.model(model_id)
        record_id = record_id or _new_id()
        with connect(self.db_path) as conn:
            indexed, body = self._write_row(conn, model, owner, record_id, fields)
            conn.execute(
                "INSERT INTO records (id, model, owner, scope, rev, position, indexed, body,"
                " written_by, created_at, updated_at) VALUES (?, ?, ?, 'personal', 1, ?, ?, ?, ?, ?, ?)",
                (
                    record_id,
                    model.id,
                    owner,
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
