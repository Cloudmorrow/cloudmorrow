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
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from cloudmorrow.paths import UnsafePathError, normalise_rel_path
from cloudmorrow.server import fileops
from cloudmorrow.server.datamodels import Datamodel
from cloudmorrow.server.notes import (
    IMAGE_DIR,
    NOTE_SUFFIX,
    InvalidImageError,
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
    Refused,
    UnknownRecordError,
)
from cloudmorrow.server.shares import (
    DRIVE,
    DRIVE_NAME,
    MACHINE,
    SERVER,
    InvalidSlugError,
    Share,
    ShareExistsError,
    ShareKindError,
    SharePathError,
    ShareStore,
)

__all__ = ["Backend", "ContentError", "NotesBackend", "SharesBackend"]


class Backend(Protocol):
    def list(
        self, principal: Principal, model: Datamodel, where: dict, *, q: str = "",
        previews: bool = False,
    ) -> list[Record]: ...

    def get(self, principal: Principal, model: Datamodel, record_id: str) -> Record: ...

    def create(self, principal: Principal, model: Datamodel, fields: dict) -> Record: ...

    def update(
        self, principal: Principal, model: Datamodel, record_id: str, fields: dict, rev: object
    ) -> Record: ...

    def delete(self, principal: Principal, model: Datamodel, record_id: str) -> int: ...


class ContentBackend(Backend, Protocol):
    """A backend whose records have bytes beside their fields: a file's.

    Three more methods, and the record API has them for every datamodel
    such a backend serves — `GET …/{id}/content`, `GET …/{id}/thumb` and
    `POST …/upload` — so a kit element that shows files needs to know no
    more than that the datamodel has content.
    """

    def content(self, principal: Principal, model: Datamodel, record_id: str) -> tuple[Path, str]: ...

    def thumbnail(
        self, principal: Principal, model: Datamodel, record_id: str, size: int
    ) -> Path: ...

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
    raw = record_id[len(prefix):]
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise UnknownRecordError(record_id) from None


def _stamp(seconds: float) -> str:
    return dt.datetime.fromtimestamp(seconds, tz=dt.UTC).isoformat(timespec="seconds")


class AttachmentTooBig(RecordError):
    """A file bigger than a backend keeps: the API says 413, not 400."""


# -- notes -----------------------------------------------------------------------------
class NotesBackend:
    """Notes as records: each Markdown file in a person's notes folder is one.

    Fields: `path` (the note's title as a path, folders and all, without
    `.md`), `folder` and `title` (the two halves of it, for grouping and
    lists), `body` (the Markdown), and `modified`. A listing leaves `body`
    out — a folder of long notes is a lot to send for a list of titles — and
    reading one note puts it in. Moving a note is changing its `path`, or
    its `folder` or `title`, which is the same thing said in halves.

    Folders are the folders on disk; attachments are the pictures in
    `img/`, which a note points at as `![alt](img/<name>)`.
    """

    PREFIX = "n_"

    def __init__(self, store_for: Callable[[str], NoteStore]) -> None:
        self._store_for = store_for

    def _record(self, model: Datamodel, owner: str, path: str, *, body: str | None,
                rev: str, modified: float, preview: str | None = None) -> Record:
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
            preview=preview,
        )

    def _walk(self, node: NoteNode, into: list[NoteNode]) -> None:
        for child in node.children:
            if child.is_dir:
                self._walk(child, into)
            else:
                into.append(child)

    def list(self, principal: Principal, model: Datamodel, where: dict, *, q: str = "",
             previews: bool = False) -> list[Record]:
        unknown = set(where) - {"folder"}
        if unknown:
            raise RecordError(f"notes are filtered by folder only, not {', '.join(sorted(unknown))}")
        store = self._store_for(principal.username)
        found: list[NoteNode] = []
        self._walk(store.tree(previews=previews and not q), found)
        # A search is the notes' own: names and every line, the files read
        # one by one. Its first line that matched is the preview.
        hits: dict[str, str] | None = None
        if q:
            hits = {}
            for result in store.search(q):
                lines = [m["text"] for m in result["matches"] if m["line"] > 0]
                hits[result["path"]] = lines[0].strip() if lines else ""
        folder = where.get("folder")
        records = []
        for node in sorted(found, key=lambda n: n.path.casefold()):
            if hits is not None and node.path not in hits:
                continue
            preview = hits[node.path] if hits is not None else node.preview
            record = self._record(model, principal.username, node.path, body=None,
                                  rev="", modified=node.modified or 0, preview=preview)
            if folder is not None and record.fields["folder"] != folder:
                continue
            records.append(record)
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

    @staticmethod
    def _path_from(fields: dict, *, folder: str = "", title: str = "") -> str:
        """A note's path from what was sent: `path`, or `folder` and `title`."""
        if fields.get("path"):
            return str(fields["path"]).strip().strip("/")
        folder = str(fields.get("folder", folder) or "").strip().strip("/")
        title = str(fields.get("title", title) or "").strip().replace("/", "-")
        return f"{folder}/{title}" if folder and title else title

    def create(self, principal: Principal, model: Datamodel, fields: dict) -> Record:
        path = self._path_from(fields)
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
        unknown = set(fields) - {"path", "folder", "title", "body"}
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
        new_path = self._path_from(
            fields, folder=current.fields["folder"], title=current.fields["title"]
        ) or path
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

    # -- folders ---------------------------------------------------------------------
    @staticmethod
    def _folder_path(path: str) -> str:
        try:
            rel = normalise_rel_path(str(path or "")).as_posix()
        except UnsafePathError as exc:
            raise RecordError(str(exc)) from None
        if rel.split("/", 1)[0] == IMAGE_DIR:
            raise RecordError(f"{IMAGE_DIR} is where the pictures are kept; call the folder something else")
        return rel

    def folders(self, principal: Principal, model: Datamodel) -> list[dict]:
        store = self._store_for(principal.username)
        found: list[dict] = []

        def walk(node: NoteNode) -> None:
            for child in node.children:
                if child.is_dir:
                    notes = sum(1 for c in child.children if not c.is_dir)
                    found.append({"path": child.path, "name": child.name, "count": notes})
                    walk(child)

        walk(store.tree())
        return found

    def make_folder(self, principal: Principal, model: Datamodel, path: str) -> dict:
        store = self._store_for(principal.username)
        rel = self._folder_path(path)
        try:
            made = store.create_dir(rel)
        except NoteExistsError:
            raise RecordError(f"there is already a folder called {rel}") from None
        except UnsafePathError as exc:
            raise RecordError(str(exc)) from None
        return {"path": made, "name": made.rsplit("/", 1)[-1]}

    def move_folder(self, principal: Principal, model: Datamodel, path: str, to: str) -> dict:
        store = self._store_for(principal.username)
        source, target = self._folder_path(path), self._folder_path(to)
        if not (store.root / source).is_dir():
            raise RecordError(f"there is no folder called {source}")
        try:
            moved = store.move(source, target)
        except (NoteExistsError, FileExistsError):
            raise RecordError(f"there is already something called {target}") from None
        except (NoteNotFoundError, UnsafePathError) as exc:
            raise RecordError(str(exc)) from None
        return {"path": moved, "name": moved.rsplit("/", 1)[-1]}

    def delete_folder(self, principal: Principal, model: Datamodel, path: str) -> None:
        store = self._store_for(principal.username)
        rel = self._folder_path(path)
        if not (store.root / rel).is_dir():
            raise RecordError(f"there is no folder called {rel}")
        try:
            store.delete(rel, recursive=True)
        except (NoteNotFoundError, UnsafePathError) as exc:
            raise RecordError(str(exc)) from None

    # -- attachments: the pictures -------------------------------------------------------
    def attach(self, principal: Principal, model: Datamodel, data: bytes, filename: str) -> dict:
        store = self._store_for(principal.username)
        try:
            info = store.save_image(data, filename=filename)
        except InvalidImageError as exc:
            if "too big" in str(exc):
                raise AttachmentTooBig(str(exc)) from None
            raise RecordError(str(exc)) from None
        return info.to_dict()

    def attachment(self, principal: Principal, model: Datamodel, name: str) -> tuple[bytes, str]:
        store = self._store_for(principal.username)
        try:
            return store.image(name)
        except (NoteNotFoundError, UnsafePathError):
            raise UnknownRecordError(name) from None

# -- shares, and the files in them -------------------------------------------------
def _matches(fields: dict, where: dict) -> bool:
    """A backend's own filter: each value as the query string says it."""
    for name, wanted in where.items():
        value = fields.get(name)
        if isinstance(value, bool):
            value = "true" if value else "false"
        if str("" if value is None else value) != str(wanted):
            return False
    return True


def _join(folder: str, name: str) -> str:
    return f"{folder}/{name}" if folder else name


class SharesBackend:
    """Shares and their files as records: `share` and `file`.

    A **share** record is one of the places files are kept: the person's own
    drive first (`my-files`, shown as My Files), then their shares, on the
    server or on one of their machines. Its id is its name, which is what a
    share is mounted by. It is made — a server share by an administrator, a
    machine share by anyone, on one of their own machines — and forgotten
    (its files stay), and never changed: the same rules `/api/shares` has.

    A **file** record is a file or a folder in one of them. Its id is the
    share and the path in it, encoded; its `share` is the share's id, so
    `?share=my-files&folder=Photos` lists a folder. Making one is a new
    folder; the bytes of a file are put with `put`, and read with
    `content` and `thumbnail`. Changing its `name`, `folder` or `path`
    renames or moves it inside its share.

    A machine share is listed, and says whether its machine is serving it,
    but its files are on that machine and the server has nothing to show.
    """

    FILE_PREFIX = "f_"

    def __init__(
        self,
        shares: ShareStore,
        drive_of: Callable[[str], Share],
        agents_of: Callable[[str], list],
        *,
        data_dir: Path,
        base_url: Callable[[], str] = lambda: "",
    ) -> None:
        self._shares = shares
        self._drive_of = drive_of
        self._agents_of = agents_of
        self._data_dir = data_dir
        self._base_url = base_url

    # -- which datamodel -------------------------------------------------------------
    @staticmethod
    def _is_share(model: Datamodel) -> bool:
        return model.id == "share"

    def list(self, principal: Principal, model: Datamodel, where: dict, *, q: str = "",
             previews: bool = False) -> list[Record]:
        if self._is_share(model):
            found = self._list_shares(principal, model, where)
        else:
            found = self._list_files(principal, model, where)
        # A search here is by name, in what is listed: a folder at a time.
        if q:
            needle = q.casefold()
            found = [r for r in found if needle in str(r.fields.get("name", "")).casefold()
                     or needle in str(r.fields.get("label", "")).casefold()]
        return found

    def get(self, principal: Principal, model: Datamodel, record_id: str) -> Record:
        if self._is_share(model):
            return self._share_record(model, principal.username, self._find_share(principal, record_id))
        share, path = self._locate(principal, record_id)
        return self._file_record(model, share, path, fileops.inside(share, path))

    def create(self, principal: Principal, model: Datamodel, fields: dict) -> Record:
        if self._is_share(model):
            return self._make_share(principal, model, fields)
        return self._make_folder(principal, model, fields)

    def update(self, principal: Principal, model: Datamodel, record_id: str, fields: dict,
               rev: object) -> Record:
        if self._is_share(model):
            raise RecordError(
                "a share is not changed once it is made: remove it and make it again"
            )
        return self._move_file(principal, model, record_id, fields, rev)

    def delete(self, principal: Principal, model: Datamodel, record_id: str) -> int:
        if self._is_share(model):
            share = self._find_share(principal, record_id)
            if share.kind == DRIVE:
                raise Refused(f"{DRIVE_NAME} is your own drive on the server — it cannot be removed")
            self._shares.delete(principal.username, share.name)
            return 1
        share, path = self._locate(principal, record_id)
        target = self._existing(share, path, record_id)
        try:
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
        except OSError as exc:
            raise RecordError(f"the server cannot delete {path}: {exc.strerror or exc}") from None
        return 1

    # -- shares ----------------------------------------------------------------------
    def _all_shares(self, principal: Principal) -> list[Share]:
        return [self._drive_of(principal.username), *self._shares.shares(principal.username)]

    def _find_share(self, principal: Principal, name: str) -> Share:
        name = (name or "").strip().lower()
        if name == DRIVE_NAME:
            return self._drive_of(principal.username)
        share = self._shares.get(principal.username, name)
        if share is None:
            raise UnknownRecordError(name)
        return share

    def _agents(self, username: str) -> dict:
        return {agent.id: agent for agent in self._agents_of(username)}

    def _share_record(self, model: Datamodel, owner: str, share: Share,
                      agents: dict | None = None) -> Record:
        base = self._base_url().rstrip("/")
        url = f"{base}/dav/{share.name}/" if base else ""
        online = True
        machine = ""
        if share.kind == MACHINE:
            agent = (agents if agents is not None else self._agents(owner)).get(share.agent_id or -1)
            machine = agent.name if agent else ""
            served_at = agent.dav_base.rstrip("/") if agent else ""
            online = bool(agent and agent.online and served_at)
            url = f"{served_at}/dav/{share.name}/" if served_at else ""
            where = f"On {machine or 'a machine'}" + ("" if online else ", offline")
            about = f"{where} — mount it to browse it"
        elif share.kind == DRIVE:
            about = share.description or "Your own files on the server"
        else:
            about = share.description or "On the server"
        stamp = share.updated_at or share.created_at or ""
        return Record(
            id=share.name,
            model=model.id,
            owner=owner,
            scope="personal",
            rev=stamp,
            position=0,
            fields={
                "name": share.name,
                "label": "My Files" if share.kind == DRIVE else share.name,
                "kind": share.kind,
                "description": share.description,
                "machine": machine,
                "path": str(share.path),
                "online": online,
                "browsable": share.kind != MACHINE,
                "about": about,
                "url": url,
            },
            written_by="files",
            created_at=share.created_at,
            updated_at=stamp,
        )

    def _list_shares(self, principal: Principal, model: Datamodel, where: dict) -> list[Record]:
        unknown = set(where) - set(model.by_name)
        if unknown:
            raise RecordError(f"shares have no field {', '.join(sorted(unknown))}")
        agents = self._agents(principal.username)
        records = [
            self._share_record(model, principal.username, share, agents)
            for share in self._all_shares(principal)
        ]
        return [r for r in records if _matches(r.fields, where)]

    def _make_share(self, principal: Principal, model: Datamodel, fields: dict) -> Record:
        """A share, made as `/api/shares` makes one, with the same rules."""
        name = str(fields.get("name") or fields.get("label") or "").strip()
        kind = str(fields.get("kind") or SERVER).strip().lower()
        agent_id = None
        path = str(fields.get("path") or "").strip() or None
        if kind == MACHINE:
            machine = str(fields.get("machine") or "").strip()
            if not machine:
                raise RecordError("a machine share needs the machine that serves it")
            agent = next((a for a in self._agents_of(principal.username) if a.name == machine), None)
            if agent is None:
                raise RecordError(f"no such machine: {machine}")
            agent_id = agent.id
        elif kind == SERVER and not principal.admin:
            raise Refused(
                "only an admin can make a share on the server — "
                "a machine share serves a directory on one of your own machines"
            )
        try:
            share = self._shares.create(
                principal.username, name, kind=kind, path=path, agent_id=agent_id,
                description=str(fields.get("description") or ""),
            )
        except ShareExistsError:
            raise RecordError("a share with that name exists") from None
        except (InvalidSlugError, SharePathError, ShareKindError) as exc:
            raise RecordError(str(exc)) from None
        return self._share_record(model, principal.username, share)

    def _server_side(self, principal: Principal, name: str) -> Share:
        """A share whose files the server has: the drive, or a server share."""
        try:
            share = self._find_share(principal, name)
        except UnknownRecordError:
            raise RecordError(f"no such share: {name}") from None
        if share.kind == MACHINE:
            record = self._share_record(_SHARE_ONLY, principal.username, share)
            raise RecordError(f"{share.name} is {record.fields['about'][0].lower()}"
                              f"{record.fields['about'][1:]}")
        return share

    # -- files ---------------------------------------------------------------------
    def _locate(self, principal: Principal, record_id: str) -> tuple[Share, str]:
        key = decode_id(self.FILE_PREFIX, record_id)
        name, _, path = key.partition("/")
        if not path:
            raise UnknownRecordError(record_id)
        try:
            share = self._server_side(principal, name)
        except RecordError:
            raise UnknownRecordError(record_id) from None
        return share, path

    def _existing(self, share: Share, path: str, record_id: str) -> Path:
        try:
            target = fileops.inside(share, path)
        except fileops.FileOpError:
            raise UnknownRecordError(record_id) from None
        if not target.exists() or target.is_symlink() or any(
            part.startswith(".") for part in Path(path).parts
        ):
            raise UnknownRecordError(record_id)
        return target

    def _file_record(self, model: Datamodel, share: Share, path: str, target: Path) -> Record:
        path = path.strip("/")
        if not target.exists() or target.is_symlink():
            raise UnknownRecordError(encode_id(self.FILE_PREFIX, f"{share.name}/{path}"))
        entry = fileops.entry(target)
        folder, _, name = path.rpartition("/")
        stamp = _stamp(entry.modified)
        return Record(
            id=encode_id(self.FILE_PREFIX, f"{share.name}/{path}"),
            model=model.id,
            owner=share.owner,
            scope="personal",
            rev=f"{entry.modified_ns:x}-{entry.size:x}",
            position=0,
            fields={
                "share": share.name,
                "path": path,
                "folder": folder,
                "name": name,
                "kind": "folder" if entry.is_dir else "file",
                "size": entry.size,
                "modified": stamp,
                "mime": entry.mime,
            },
            written_by="files",
            created_at=stamp,
            updated_at=stamp,
        )

    def _list_files(self, principal: Principal, model: Datamodel, where: dict) -> list[Record]:
        where = dict(where)
        name = str(where.pop("share", "") or "").strip()
        if not name:
            raise RecordError(
                f"files are listed a share at a time: share={DRIVE_NAME} for your own, "
                "and folder= for a folder in it"
            )
        share = self._server_side(principal, name)
        folder = str(where.pop("folder", "") or "").strip("/ ")
        if "path" in where and not folder:
            folder = str(where["path"]).strip("/ ").rpartition("/")[0]
        unknown = set(where) - set(model.by_name)
        if unknown:
            raise RecordError(f"files have no field {', '.join(sorted(unknown))}")
        if any(part.startswith(".") for part in Path(folder).parts):
            raise RecordError("no such folder")
        try:
            found = fileops.entries(fileops.inside(share, folder))
        except fileops.FileOpError as exc:
            raise RecordError(str(exc)) from None
        records = []
        for entry in found:
            path = _join(folder, entry.name)
            try:
                record = self._file_record(model, share, path, fileops.inside(share, path))
            except (UnknownRecordError, fileops.FileOpError, OSError):
                continue
            if _matches(record.fields, where):
                records.append(record)
        return records

    def _destination(self, principal: Principal, fields: dict) -> tuple[Share, str, str]:
        """The share, folder and name a new file or folder goes to."""
        share = self._server_side(principal, str(fields.get("share") or DRIVE_NAME))
        path = str(fields.get("path") or "").strip("/ ")
        if path:
            folder, _, name = path.rpartition("/")
        else:
            folder = str(fields.get("folder") or "").strip("/ ")
            name = str(fields.get("name") or "")
        try:
            name = fileops.file_name(name)
        except fileops.FileOpError as exc:
            raise RecordError(str(exc)) from None
        if any(part.startswith(".") for part in Path(folder).parts):
            raise RecordError("not a usable folder")
        return share, folder, name

    def _folder_in(self, share: Share, folder: str) -> Path:
        try:
            where = fileops.inside(share, folder)
        except fileops.FileOpError as exc:
            raise RecordError(str(exc)) from None
        if not where.is_dir():
            raise RecordError(f"there is no folder {folder or '(top)'} in {share.name}")
        return where

    def _make_folder(self, principal: Principal, model: Datamodel, fields: dict) -> Record:
        kind = str(fields.get("kind") or "folder")
        if kind != "folder":
            raise RecordError(
                "a file is put with its bytes: POST /api/records/file/upload"
                "?share=…&folder=…&name=…, the file as the body"
            )
        share, folder, name = self._destination(principal, fields)
        parent = self._folder_in(share, folder)
        target = parent / name
        if target.exists():
            raise RecordError(f"there is already something called {name} there")
        try:
            target.mkdir()
        except OSError as exc:
            raise RecordError(f"the server cannot make {name}: {exc.strerror or exc}") from None
        return self._file_record(model, share, _join(folder, name), target)

    def _move_file(self, principal: Principal, model: Datamodel, record_id: str, fields: dict,
                   rev: object) -> Record:
        unknown = set(fields) - {"name", "folder", "path", "share"}
        if unknown:
            raise RecordError(f"a file's {', '.join(sorted(unknown))} is not written directly")
        current = self.get(principal, model, record_id)
        share, path = self._locate(principal, record_id)
        if rev not in (None, "") and str(rev) != str(current.rev):
            raise RecordConflictError(current)
        if fields.get("share") not in (None, "", share.name):
            raise RecordError("a file moves inside its share; to another, download it and put it there")
        if fields.get("path"):
            new_path = str(fields["path"]).strip("/ ")
        else:
            folder = str(fields.get("folder", current.fields["folder"]) or "").strip("/ ")
            new_path = _join(folder, str(fields.get("name", current.fields["name"]) or ""))
        if new_path == path:
            return current
        new_folder, _, new_name = new_path.rpartition("/")
        try:
            new_name = fileops.file_name(new_name)
        except fileops.FileOpError as exc:
            raise RecordError(str(exc)) from None
        if any(part.startswith(".") for part in Path(new_folder).parts):
            raise RecordError("not a usable folder")
        if (new_path + "/").startswith(path + "/"):
            raise RecordError("a folder cannot go inside itself")
        source = self._existing(share, path, record_id)
        target = self._folder_in(share, new_folder) / new_name
        if target.exists() and target.resolve() != source.resolve():
            raise RecordError(f"there is already something called {new_name} there")
        try:
            os.rename(source, target)
        except OSError as exc:
            raise RecordError(f"the server cannot move {path}: {exc.strerror or exc}") from None
        return self._file_record(model, share, _join(new_folder, new_name), target)

    # -- the bytes -------------------------------------------------------------------
    def content(self, principal: Principal, model: Datamodel, record_id: str) -> tuple[Path, str]:
        if self._is_share(model):
            raise ContentError(404, "a share has no content of its own; its files do")
        share, path = self._locate(principal, record_id)
        target = self._existing(share, path, record_id)
        if not target.is_file():
            raise ContentError(404, f"{path} is a folder")
        return target, fileops.mime_of(target) or "application/octet-stream"

    def thumbnail(self, principal: Principal, model: Datamodel, record_id: str, size: int) -> Path:
        target, _mime = self.content(principal, model, record_id)
        share, _path = self._locate(principal, record_id)
        try:
            return fileops.thumbnail(self._data_dir, share, target, size)
        except fileops.FileOpError as exc:
            raise ContentError(exc.status, str(exc)) from None

    def put(self, principal: Principal, model: Datamodel, fields: dict, source: Path) -> Record:
        """A file put in a folder: *source* is all of it, already here.
        A name that is taken gets a number, as it does over the mount."""
        if self._is_share(model):
            raise RecordError("a share is made, not put")
        share, folder, name = self._destination(principal, fields)
        parent = self._folder_in(share, folder)
        try:
            target = fileops.place(source, parent, name)
        except fileops.FileOpError as exc:
            raise ContentError(exc.status, str(exc)) from None
        return self._file_record(model, share, _join(folder, target.name), target)


# A stand-in datamodel, for saying where a share is when no record is wanted.
_SHARE_ONLY = Datamodel(
    id="share", version=1, label="Share", description="", domain="files",
    scopes=("personal",), fields=(), title="label",
)
