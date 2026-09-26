"""Backends: datamodels whose records live somewhere other than the record store.

Three foundational datamodels keep living where they always have, because
other things reach them there — WebDAV, the notes MCP tools, `cm secret run`,
the desktop app's mounts. A backend serves one of them through the record
API all the same, in the same envelope, so a Quill, `cm <quill>` and an
assistant cannot tell the difference, and the Notes, Files and Secrets
Quills carry nothing but their screens.

A backend is five methods — list, get, create, update, delete — each given
the principal asking. It enforces its own ownership (a note is its owner's,
because it is in their folder), and the record store's gate has already
said which kinds of principal may reach its datamodel at all.

A record's id in a backend is something the backend can find it by again,
made safe for a URL: a note's is its path, base64url-encoded.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
from collections.abc import Callable
from typing import Protocol

from cloudmorrow.paths import UnsafePathError
from cloudmorrow.server.datamodels import Datamodel
from cloudmorrow.server.notes import (
    NOTE_SUFFIX,
    NoteConflictError,
    NoteExistsError,
    NoteNode,
    NoteNotFoundError,
    NoteStore,
)
from cloudmorrow.server.records import (
    Principal,
    Record,
    RecordConflictError,
    RecordError,
    UnknownRecordError,
)
from cloudmorrow.server.secrets import (
    DEFAULT_ENVIRONMENT,
    DEFAULT_VAULT,
    InvalidEnvironmentError,
    InvalidSecretNameError,
    InvalidVaultError,
    Secret,
    SecretStore,
    UnknownSecretError,
    validate_environment,
    validate_key,
    validate_vault,
)

__all__ = ["Backend", "NotesBackend", "VaultsBackend"]


class Backend(Protocol):
    def list(self, principal: Principal, model: Datamodel, where: dict) -> list[Record]: ...

    def get(self, principal: Principal, model: Datamodel, record_id: str) -> Record: ...

    def create(self, principal: Principal, model: Datamodel, fields: dict) -> Record: ...

    def update(
        self, principal: Principal, model: Datamodel, record_id: str, fields: dict, rev: object
    ) -> Record: ...

    def delete(self, principal: Principal, model: Datamodel, record_id: str) -> int: ...


def encode_id(prefix: str, key: str) -> str:
    return prefix + base64.urlsafe_b64encode(key.encode("utf-8")).decode("ascii").rstrip("=")


def decode_id(prefix: str, record_id: str) -> str:
    if not record_id.startswith(prefix):
        raise UnknownRecordError(record_id)
    raw = record_id[len(prefix):]
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise UnknownRecordError(record_id) from None


def _stamp(seconds: float) -> str:
    return dt.datetime.fromtimestamp(seconds, tz=dt.UTC).isoformat(timespec="seconds")


# -- notes -----------------------------------------------------------------------------
class NotesBackend:
    """Notes as records: each Markdown file in a person's notes folder is one.

    Fields: `path` (the note's title as a path, folders and all, without
    `.md`), `folder` and `title` (the two halves of it, for grouping and
    lists), `body` (the Markdown), and `modified`. A listing leaves `body`
    out — a folder of long notes is a lot to send for a list of titles — and
    reading one note puts it in. Moving a note is changing its `path`.
    """

    PREFIX = "n_"

    def __init__(self, store_for: Callable[[str], NoteStore]) -> None:
        self._store_for = store_for

    def _record(self, model: Datamodel, owner: str, path: str, *, body: str | None,
                rev: str, modified: float) -> Record:
        title_path = path[: -len(NOTE_SUFFIX)] if path.endswith(NOTE_SUFFIX) else path
        folder, _, title = title_path.rpartition("/")
        return Record(
            id=encode_id(self.PREFIX, title_path),
            model=model.id,
            owner=owner,
            scope="personal",
            rev=rev,
            position=0,
            fields={"path": title_path, "folder": folder, "title": title, "body": body,
                    "modified": _stamp(modified)},
            written_by="notes",
            created_at=_stamp(modified),
            updated_at=_stamp(modified),
        )

    def _walk(self, node: NoteNode, into: list[NoteNode]) -> None:
        for child in node.children:
            if child.is_dir:
                self._walk(child, into)
            else:
                into.append(child)

    def list(self, principal: Principal, model: Datamodel, where: dict) -> list[Record]:
        store = self._store_for(principal.username)
        found: list[NoteNode] = []
        self._walk(store.tree(), found)
        folder = where.get("folder")
        records = []
        for node in sorted(found, key=lambda n: n.path.casefold()):
            record = self._record(model, principal.username, node.path, body=None,
                                  rev="", modified=node.modified or 0)
            if folder is not None and record.fields["folder"] != folder:
                continue
            records.append(record)
        unknown = set(where) - {"folder"}
        if unknown:
            raise RecordError(f"notes are filtered by folder only, not {', '.join(sorted(unknown))}")
        return records

    def get(self, principal: Principal, model: Datamodel, record_id: str) -> Record:
        path = decode_id(self.PREFIX, record_id)
        store = self._store_for(principal.username)
        try:
            note = store.read(store.with_suffix(path))
        except (NoteNotFoundError, UnsafePathError, IsADirectoryError):
            raise UnknownRecordError(record_id) from None
        return self._record(model, principal.username, note.path, body=note.content,
                            rev=note.rev, modified=note.modified)

    def create(self, principal: Principal, model: Datamodel, fields: dict) -> Record:
        path = str(fields.get("path") or fields.get("title") or "").strip().strip("/")
        if not path:
            raise RecordError("a note needs a path: its title, with folders if you like")
        store = self._store_for(principal.username)
        try:
            note = store.create_note(store.with_suffix(path), str(fields.get("body") or ""))
        except NoteExistsError:
            raise RecordError(f"there is already a note called {path}") from None
        except UnsafePathError as exc:
            raise RecordError(str(exc)) from None
        return self.get(principal, model, encode_id(self.PREFIX, note.path.removesuffix(NOTE_SUFFIX)))

    def update(self, principal: Principal, model: Datamodel, record_id: str, fields: dict,
               rev: object) -> Record:
        unknown = set(fields) - {"path", "body"}
        if unknown:
            raise RecordError(f"a note's {', '.join(sorted(unknown))} is not written directly")
        current = self.get(principal, model, record_id)
        store = self._store_for(principal.username)
        path = current.fields["path"]
        if "body" in fields:
            try:
                store.write(store.with_suffix(path), str(fields["body"] or ""),
                            rev=str(rev) if rev else None)
            except NoteConflictError:
                raise RecordConflictError(self.get(principal, model, record_id)) from None
        new_path = str(fields.get("path") or path).strip().strip("/")
        if new_path != path:
            try:
                moved = store.move(store.with_suffix(path), store.with_suffix(new_path))
            except (NoteExistsError, FileExistsError):
                raise RecordError(f"there is already a note called {new_path}") from None
            except UnsafePathError as exc:
                raise RecordError(str(exc)) from None
            path = moved.removesuffix(NOTE_SUFFIX)
        return self.get(principal, model, encode_id(self.PREFIX, path))

    def delete(self, principal: Principal, model: Datamodel, record_id: str) -> int:
        current = self.get(principal, model, record_id)
        store = self._store_for(principal.username)
        store.delete(store.with_suffix(current.fields["path"]))
        return 1


# -- secrets ---------------------------------------------------------------------------
_BAD_NAME = (InvalidVaultError, InvalidEnvironmentError, InvalidSecretNameError)


class VaultsBackend:
    """Secrets as records: one per key, in a vault and an environment.

    Fields: `vault`, `environment` and `key` — which together are the id —
    `value`, and `length`. The value is a `secret` field: it is never in a
    listing, where it is null, and only reading one secret puts it in. The
    store is the one `cm secret` and `/api/secrets` have always used, sealed
    under the key itself; nothing here seals or opens anything of its own.

    Changing `vault`, `environment` or `key` moves the secret, value and all;
    `length` is the store's to say. No assistant ever gets this far: the
    record store's gate refuses the `secret` datamodel to every assistant
    before a backend is asked.
    """

    PREFIX = "s_"
    WRITABLE = frozenset({"vault", "environment", "key", "value"})
    FILTERS = frozenset({"vault", "environment", "key"})

    def __init__(self, store: SecretStore) -> None:
        self._store = store

    @staticmethod
    def _rev(secret: Secret) -> str:
        # The keyed fingerprint moves with the value and says nothing about it.
        return secret.fingerprint[:16]

    def _record(self, model: Datamodel, owner: str, secret: Secret) -> Record:
        return Record(
            id=encode_id(self.PREFIX, f"{secret.vault}/{secret.environment}/{secret.key}"),
            model=model.id,
            owner=owner,
            scope="personal",
            rev=self._rev(secret),
            position=0,
            fields={
                "vault": secret.vault,
                "environment": secret.environment,
                "key": secret.key,
                "value": secret.value,
                "length": secret.length,
            },
            written_by="secrets",
            created_at=secret.created_at,
            updated_at=secret.updated_at,
        )

    def _where(self, record_id: str) -> tuple[str, str, str]:
        vault, _, rest = decode_id(self.PREFIX, record_id).partition("/")
        environment, _, key = rest.partition("/")
        if not (vault and environment and key):
            raise UnknownRecordError(record_id)
        return vault, environment, key

    def _find(self, owner: str, where: tuple[str, str, str], record_id: str) -> Secret:
        try:
            secret = self._store.get(owner, *where, reveal=True)
        except _BAD_NAME:
            raise UnknownRecordError(record_id) from None
        if secret is None:
            raise UnknownRecordError(record_id)
        return secret

    def _taken(self, owner: str, where: tuple[str, str, str]) -> None:
        """Refuse to write over another secret: that is `cm secret set`'s job, not a record's."""
        try:
            there = self._store.get(owner, *where, reveal=False)
        except _BAD_NAME as exc:
            raise RecordError(str(exc)) from None
        if there is not None:
            raise RecordError(f"{there.key} is already in {there.vault} · {there.environment}")

    @staticmethod
    def _target(fields: dict, vault: str, environment: str, key: str) -> tuple[str, str, str]:
        return (
            str(fields.get("vault") or vault).strip().lower(),
            str(fields.get("environment") or environment).strip().lower(),
            str(fields.get("key") or key).strip(),
        )

    def list(self, principal: Principal, model: Datamodel, where: dict) -> list[Record]:
        unknown = set(where) - self.FILTERS
        if unknown:
            raise RecordError(
                "secrets are filtered by vault, environment and key, not "
                + ", ".join(sorted(unknown))
            )
        owner = principal.username
        try:
            vaults = (
                [str(where["vault"])] if "vault" in where
                else [v.vault for v in self._store.vaults(owner)]
            )
            found = [
                secret
                for vault in vaults
                for secret in self._store.list(owner, vault, where.get("environment"))
            ]
        except _BAD_NAME as exc:
            raise RecordError(str(exc)) from None
        if "key" in where:
            found = [s for s in found if s.key == str(where["key"])]
        # Never the value, whatever was asked: a listing describes, it does not hand over.
        return [self._record(model, owner, secret) for secret in found]

    def get(self, principal: Principal, model: Datamodel, record_id: str) -> Record:
        where = self._where(record_id)
        return self._record(model, principal.username, self._find(principal.username, where, record_id))

    def _write(self, owner: str, where: tuple[str, str, str], value: object) -> None:
        if value is not None and not isinstance(value, str):
            raise RecordError("a secret's value is text")
        try:
            self._store.set(owner, *where, value or "")
        except _BAD_NAME as exc:
            raise RecordError(str(exc)) from None

    def _check_fields(self, fields: dict) -> None:
        unknown = set(fields) - self.WRITABLE
        if unknown:
            raise RecordError(f"a secret's {', '.join(sorted(unknown))} is not written directly")

    def create(self, principal: Principal, model: Datamodel, fields: dict) -> Record:
        self._check_fields(fields)
        if not str(fields.get("key") or "").strip():
            raise RecordError("a secret needs a key: the variable name, like DATABASE_URL")
        owner = principal.username
        where = self._target(fields, DEFAULT_VAULT, DEFAULT_ENVIRONMENT, "")
        self._taken(owner, where)
        self._write(owner, where, fields.get("value"))
        return self.get(principal, model, encode_id(self.PREFIX, "/".join(self._stored(where))))

    @staticmethod
    def _stored(where: tuple[str, str, str]) -> tuple[str, str, str]:
        """The names as the store keeps them, once it has checked them."""
        return validate_vault(where[0]), validate_environment(where[1]), validate_key(where[2])

    def update(self, principal: Principal, model: Datamodel, record_id: str, fields: dict,
               rev: object) -> Record:
        self._check_fields(fields)
        owner = principal.username
        here = self._where(record_id)
        current = self._find(owner, here, record_id)
        if rev not in (None, "") and str(rev) != self._rev(current):
            raise RecordConflictError(self._record(model, owner, current))
        target = self._target(fields, *here)
        moving = target != here
        if moving:
            self._taken(owner, target)
        self._write(owner, target, fields["value"] if "value" in fields else current.value)
        target = self._stored(target)
        if moving:
            self._store.delete(owner, *here)
        return self.get(principal, model, encode_id(self.PREFIX, "/".join(target)))

    def delete(self, principal: Principal, model: Datamodel, record_id: str) -> int:
        where = self._where(record_id)
        try:
            self._store.delete(principal.username, *where)
        except (UnknownSecretError, *_BAD_NAME):
            raise UnknownRecordError(record_id) from None
        return 1
