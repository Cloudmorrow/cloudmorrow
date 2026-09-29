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
said which kinds of principal may reach its datamodel at all. `list` also
takes the two things a listing may ask besides filters: `q`, a text search,
and `previews`, a line of each record's text on it.

A backend may do more, and says so by having the methods (the record store
lists them as the datamodel's capabilities, and the record API serves them
under `/api/records/{model}/_folders` and `…/_attachments`):

* **folders** — `folders`, `make_folder`, `move_folder`, `delete_folder`:
  the folders a record's path is in, which exist before anything is put in
  them and go with everything in them. Not records: a folder has no fields,
  no rev, nothing to seal, and a listing of notes that had folders in it
  would be a listing of two things.
* **attachments** — `attach`, `attachment`: files kept beside the records,
  that the records' Markdown points at. A note's pictures.

A record's id in a backend is something the backend can find it by again,
made safe for a URL: a note's is its path, base64url-encoded.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
from pathlib import Path
from typing import Protocol

from cloudmorrow.server.datamodels import Datamodel
from cloudmorrow.server.records import (
    Principal,
    Record,
    RecordError,
    UnknownRecordError,
)


class Backend(Protocol):
    def list(
        self,
        principal: Principal,
        model: Datamodel,
        where: dict,
        *,
        q: str = "",
        previews: bool = False,
    ) -> list[Record]: ...

    def get(self, principal: Principal, model: Datamodel, record_id: str) -> Record: ...

    def create(self, principal: Principal, model: Datamodel, fields: dict) -> Record: ...

    def update(self, principal: Principal, model: Datamodel, record_id: str, fields: dict, rev: object) -> Record: ...

    def delete(self, principal: Principal, model: Datamodel, record_id: str) -> int: ...


class ContentBackend(Backend, Protocol):
    """A backend whose records have bytes beside their fields: a file's.

    Three more methods, and the record API has them for every datamodel
    such a backend serves — `GET …/{id}/content`, `GET …/{id}/thumb` and
    `POST …/upload` — so a kit element that shows files needs to know no
    more than that the datamodel has content.
    """

    def content(self, principal: Principal, model: Datamodel, record_id: str) -> tuple[Path, str]: ...

    def thumbnail(self, principal: Principal, model: Datamodel, record_id: str, size: int) -> Path: ...

    def put(self, principal: Principal, model: Datamodel, fields: dict, source: Path) -> Record: ...


class ContentError(RecordError):
    """Content that cannot be given, with the HTTP status that says why:
    404 none, 415 not a picture the server can make small, 501 it cannot
    make pictures small at all."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def encode_id(prefix: str, key: str) -> str:
    return prefix + base64.urlsafe_b64encode(key.encode("utf-8")).decode("ascii").rstrip("=")


def decode_id(prefix: str, record_id: str) -> str:
    if not record_id.startswith(prefix):
        raise UnknownRecordError(record_id)
    raw = record_id[len(prefix) :]
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise UnknownRecordError(record_id) from None


def iso_stamp(seconds: float) -> str:
    return dt.datetime.fromtimestamp(seconds, tz=dt.UTC).isoformat(timespec="seconds")


class AttachmentTooBig(RecordError):
    """A file bigger than a backend keeps: the API says 413, not 400."""
