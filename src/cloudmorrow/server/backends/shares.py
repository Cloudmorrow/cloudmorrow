"""Shares, and the files in them, as records: one backend serves both datamodels.

A share is a record of the share datamodel; a file or folder in one is a
record of the file datamodel, whose id is its share and path. A file has
content — its bytes, and a thumbnail when it is a picture — so this is a
`ContentBackend`. A text file's words are its `text` field as well, read a
file at a time and written back the same way, which is what the editor kit
draws: a note is a Markdown file in the Notes folder of a drive, and
nothing more (`server/pages.py`).
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path

from cloudmorrow.server import fileops, pages
from cloudmorrow.server.backends.base import AttachmentTooBig, ContentError, decode_id, encode_id, iso_stamp
from cloudmorrow.server.datamodels import Datamodel
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
    `?share=my-files&folder=Photos` lists a folder, and
    `?share=my-files&within=Notes` everything under one, folders and all
    (`suffix=.md` keeps only the files called so). Making one is a new
    folder, or a new text file when `text` is sent; the bytes of any other
    file are put with `put`, and read with `content` and `thumbnail`.
    Changing its `name`, `folder` or `path` renames or moves it inside its
    share; changing a text file's `text` writes it, with `rev` to refuse
    writing over somebody else's.

    The folders and attachments the editor kit asks for are answered within
    a root the query names (`share`, `within`): the folders under it, and
    the pictures in its `img` folder, which no listing shows.

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

    def list(
        self, principal: Principal, model: Datamodel, where: dict, *, q: str = "", previews: bool = False
    ) -> list[Record]:
        if not self._is_share(model):
            return self._list_files(principal, model, where, q=q, previews=previews)
        found = self._list_shares(principal, model, where)
        # A search among shares is by name.
        if q:
            needle = q.casefold()
            found = [
                r
                for r in found
                if needle in str(r.fields.get("name", "")).casefold()
                or needle in str(r.fields.get("label", "")).casefold()
            ]
        return found

    def get(self, principal: Principal, model: Datamodel, record_id: str) -> Record:
        if self._is_share(model):
            return self._share_record(model, principal.username, self._find_share(principal, record_id))
        share, path = self._locate(principal, record_id)
        target = fileops.inside(share, path)
        return self._file_record(model, share, path, target, text=self._text_of(target))

    def create(self, principal: Principal, model: Datamodel, fields: dict) -> Record:
        if self._is_share(model):
            return self._make_share(principal, model, fields)
        if "text" in fields and fields.get("kind", "file") != "folder":
            return self._write_new(principal, model, fields)
        return self._make_folder(principal, model, fields)

    def update(self, principal: Principal, model: Datamodel, record_id: str, fields: dict, rev: object) -> Record:
        if self._is_share(model):
            raise RecordError("a share is not changed once it is made: remove it and make it again")
        return self._change_file(principal, model, record_id, fields, rev)

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

    def _share_record(self, model: Datamodel, owner: str, share: Share, agents: dict | None = None) -> Record:
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
            self._share_record(model, principal.username, share, agents) for share in self._all_shares(principal)
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
                principal.username,
                name,
                kind=kind,
                path=path,
                agent_id=agent_id,
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
            raise RecordError(f"{share.name} is {record.fields['about'][0].lower()}{record.fields['about'][1:]}")
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
        if not target.exists() or target.is_symlink() or any(part.startswith(".") for part in Path(path).parts):
            raise UnknownRecordError(record_id)
        return target

    def _file_record(
        self,
        model: Datamodel,
        share: Share,
        path: str,
        target: Path,
        *,
        text: str | None = None,
        preview: str | None = None,
    ) -> Record:
        path = path.strip("/")
        if not target.exists() or target.is_symlink():
            raise UnknownRecordError(encode_id(self.FILE_PREFIX, f"{share.name}/{path}"))
        entry = fileops.entry(target)
        folder, _, name = path.rpartition("/")
        stamp = iso_stamp(entry.modified)
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
                "text": text,
            },
            written_by="files",
            created_at=stamp,
            updated_at=stamp,
            preview=preview,
        )

    @staticmethod
    def _is_text(target: Path) -> bool:
        return target.is_file() and pages.is_text(target, fileops.mime_of(target))

    def _text_of(self, target: Path) -> str | None:
        """A text file's words; nothing for a folder, a picture, or a text too big to read whole."""
        if not self._is_text(target) or target.stat().st_size > pages.MAX_TEXT_BYTES:
            return None
        try:
            return pages.read_text(target)
        except OSError:
            return None

    def _preview_of(self, target: Path) -> str:
        if not self._is_text(target) or target.stat().st_size > pages.MAX_TEXT_BYTES:
            return ""
        try:
            return pages.preview(pages.read_text(target), target.stem)
        except OSError:
            return ""

    @staticmethod
    def _hidden(folder: str) -> bool:
        return any(part.startswith(".") for part in Path(folder).parts)

    def _walk(self, rel: str, directory: Path, top: Path):
        """Everything under *directory*, folders and all, as (path, target) in
        folder order; the pictures beside the pages — `img` at the top — are
        seen in the pages, never listed."""
        for entry in fileops.entries(directory):
            if directory == top and entry.is_dir and entry.name == pages.IMAGE_DIR:
                continue
            path = _join(rel, entry.name)
            target = directory / entry.name
            yield path, target
            if entry.is_dir:
                yield from self._walk(path, target, top)

    def _list_files(
        self, principal: Principal, model: Datamodel, where: dict, *, q: str = "", previews: bool = False
    ) -> list[Record]:
        where = dict(where)
        name = str(where.pop("share", "") or "").strip()
        if not name:
            raise RecordError(
                f"files are listed a share at a time: share={DRIVE_NAME} for your own, and folder= for a folder in it"
            )
        share = self._server_side(principal, name)
        within = where.pop("within", None)
        suffix = str(where.pop("suffix", "") or "").strip().lower()
        folder = str(where.pop("folder", "") or "").strip("/ ")
        if "path" in where and not folder:
            folder = str(where["path"]).strip("/ ").rpartition("/")[0]
        unknown = set(where) - set(model.by_name)
        if unknown:
            raise RecordError(f"files have no field {', '.join(sorted(unknown))}")
        try:
            if within is not None:
                root = str(within or "").strip("/ ")
                if self._hidden(root):
                    raise RecordError("no such folder")
                found = list(self._walk(root, self._folder_in(share, root), self._folder_in(share, root)))
            else:
                if self._hidden(folder):
                    raise RecordError("no such folder")
                parent = fileops.inside(share, folder)
                found = [(_join(folder, e.name), parent / e.name) for e in fileops.entries(parent)]
        except fileops.FileOpError as exc:
            raise RecordError(str(exc)) from None
        if suffix:
            found = [(path, target) for path, target in found if target.is_file() and path.lower().endswith(suffix)]
        # A search is through names, and through the lines of the text files.
        hits = pages.search([(p, t, fileops.mime_of(t)) for p, t in found if t.is_file()], q) if q else None
        records = []
        for path, target in found:
            if hits is not None and path not in hits:
                continue
            preview = hits[path] if hits is not None else (self._preview_of(target) if previews else None)
            try:
                record = self._file_record(model, share, path, target, preview=preview)
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

    def _write_new(self, principal: Principal, model: Datamodel, fields: dict) -> Record:
        """A new text file from its `text`: a page. The folders on its way are made."""
        share, folder, name = self._destination(principal, fields)
        try:
            parent = fileops.inside(share, folder)
        except fileops.FileOpError as exc:
            raise RecordError(str(exc)) from None
        target = parent / name
        if target.exists():
            raise RecordError(f"there is already something called {name} there")
        if not pages.is_text(target, fileops.mime_of(target)):
            raise RecordError(f"{name} is not a text file's name; a file that is not text is put with its bytes")
        try:
            parent.mkdir(parents=True, exist_ok=True)
            pages.write_text(target, str(fields.get("text") or ""))
        except OSError as exc:
            raise RecordError(f"the server cannot write {name}: {exc.strerror or exc}") from None
        return self._file_record(model, share, _join(folder, name), target, text=self._text_of(target))

    def _change_file(self, principal: Principal, model: Datamodel, record_id: str, fields: dict, rev: object) -> Record:
        """Write a text file's `text`, and rename or move it, in one change."""
        unknown = set(fields) - {"name", "folder", "path", "share", "text"}
        if unknown:
            raise RecordError(f"a file's {', '.join(sorted(unknown))} is not written directly")
        current = self.get(principal, model, record_id)
        share, path = self._locate(principal, record_id)
        if rev not in (None, "") and str(rev) != str(current.rev):
            raise RecordConflictError(current)
        if fields.get("share") not in (None, "", share.name):
            raise RecordError("a file moves inside its share; to another, download it and put it there")
        if "text" in fields:
            target = self._existing(share, path, record_id)
            if not self._is_text(target):
                raise RecordError(f"{current.fields['name']} is not a text file")
            try:
                pages.write_text(target, str(fields["text"] or ""))
            except OSError as exc:
                raise RecordError(f"the server cannot write {path}: {exc.strerror or exc}") from None
        if fields.get("path"):
            new_path = str(fields["path"]).strip("/ ")
        else:
            folder = str(fields.get("folder", current.fields["folder"]) or "").strip("/ ")
            new_path = _join(folder, str(fields.get("name", current.fields["name"]) or ""))
        if new_path == path:
            return self.get(principal, model, record_id) if "text" in fields else current
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
        return self._file_record(model, share, _join(new_folder, new_name), target, text=self._text_of(target))

    # -- folders and pictures, within a root ------------------------------------------
    # The editor kit asks for these with `share` and `within` on the query:
    # the folders under a root, and the pictures kept in its `img` folder.
    def _root(self, principal: Principal, where: dict | None) -> tuple[Share, str, Path]:
        where = where or {}
        share = self._server_side(principal, str(where.get("share") or DRIVE_NAME))
        root = str(where.get("within") or "").strip("/ ")
        if self._hidden(root):
            raise RecordError("no such folder")
        return share, root, self._folder_in(share, root)

    def _folder_path(self, share: Share, raw: object) -> tuple[str, Path]:
        rel = str(raw or "").strip("/ ")
        if not rel or self._hidden(rel):
            raise RecordError("not a usable folder")
        try:
            fileops.file_name(rel.rsplit("/", 1)[-1])
            return rel, fileops.inside(share, rel)
        except fileops.FileOpError as exc:
            raise RecordError(str(exc)) from None

    def folders(self, principal: Principal, model: Datamodel, where: dict | None = None) -> list[dict]:
        """Every folder under the root, parents first, each with how many files
        it holds directly (of the `suffix`, when one is asked for)."""
        _share, root, top = self._root(principal, where)
        suffix = str((where or {}).get("suffix") or "").strip().lower()
        found: list[dict] = []

        def walk(rel: str, directory: Path) -> None:
            for entry in fileops.entries(directory):
                if not entry.is_dir or (directory == top and entry.name == pages.IMAGE_DIR):
                    continue
                path, here = _join(rel, entry.name), directory / entry.name
                count = sum(
                    1 for e in fileops.entries(here) if not e.is_dir and (not suffix or e.name.lower().endswith(suffix))
                )
                found.append({"path": path, "name": entry.name, "count": count})
                walk(path, here)

        walk(root, top)
        return found

    def make_folder(self, principal: Principal, model: Datamodel, path: str, where: dict | None = None) -> dict:
        share = self._server_side(principal, str((where or {}).get("share") or DRIVE_NAME))
        rel, target = self._folder_path(share, path)
        if target.exists():
            raise RecordError(f"there is already something called {rel}")
        try:
            target.mkdir(parents=True)
        except OSError as exc:
            raise RecordError(f"the server cannot make {rel}: {exc.strerror or exc}") from None
        return {"path": rel, "name": target.name}

    def move_folder(
        self, principal: Principal, model: Datamodel, path: str, to: str, where: dict | None = None
    ) -> dict:
        share = self._server_side(principal, str((where or {}).get("share") or DRIVE_NAME))
        source_rel, source = self._folder_path(share, path)
        target_rel, target = self._folder_path(share, to)
        if not source.is_dir() or source.is_symlink():
            raise RecordError(f"there is no folder called {source_rel}")
        if target.exists():
            raise RecordError(f"there is already something called {target_rel}")
        if (target_rel + "/").startswith(source_rel + "/"):
            raise RecordError("a folder cannot go inside itself")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.rename(source, target)
        except OSError as exc:
            raise RecordError(f"the server cannot move {source_rel}: {exc.strerror or exc}") from None
        return {"path": target_rel, "name": target.name}

    def delete_folder(self, principal: Principal, model: Datamodel, path: str, where: dict | None = None) -> None:
        share = self._server_side(principal, str((where or {}).get("share") or DRIVE_NAME))
        rel, target = self._folder_path(share, path)
        if not target.is_dir() or target.is_symlink():
            raise RecordError(f"there is no folder called {rel}")
        try:
            shutil.rmtree(target)
        except OSError as exc:
            raise RecordError(f"the server cannot delete {rel}: {exc.strerror or exc}") from None

    def attach(
        self, principal: Principal, model: Datamodel, data: bytes, filename: str, where: dict | None = None
    ) -> dict:
        """A picture kept in the root's `img` folder, under a name that says when it arrived."""
        _share, _root, top = self._root(principal, where)
        if not data:
            raise RecordError("the image is empty")
        if len(data) > pages.MAX_IMAGE_BYTES:
            raise AttachmentTooBig(f"the image is too big — {pages.MAX_IMAGE_BYTES // 1_000_000} MB at most")
        content_type = pages.sniff_image(data)
        if content_type is None:
            raise RecordError("not a PNG, JPEG, GIF or WebP image")
        name = pages.image_name(filename, content_type)
        img = top / pages.IMAGE_DIR
        try:
            img.mkdir(exist_ok=True)
            tmp = img / f".{name}.tmp"
            tmp.write_bytes(data)
            os.replace(tmp, img / name)
        except OSError as exc:
            raise RecordError(f"the server cannot keep the picture: {exc.strerror or exc}") from None
        return {"name": name, "path": f"{pages.IMAGE_DIR}/{name}", "size": len(data), "content_type": content_type}

    def attachment(
        self, principal: Principal, model: Datamodel, name: str, where: dict | None = None
    ) -> tuple[bytes, str]:
        _share, _root, top = self._root(principal, where)
        if not pages.is_image_name(name):
            raise UnknownRecordError(name)
        target = top / pages.IMAGE_DIR / name
        if not target.is_file() or target.is_symlink():
            raise UnknownRecordError(name)
        data = target.read_bytes()
        return data, pages.sniff_image(data) or "application/octet-stream"

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
    id="share",
    version=1,
    label="Share",
    description="",
    domain="files",
    scopes=("personal",),
    fields=(),
    title="label",
)
