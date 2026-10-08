"""The Notes half of the fake server the TUI tests drive.

The Notes Quill is installed, as `GET /api/quills` sends it — one `editor`
screen on the `file` datamodel, within the Notes folder of the person's own
drive, the `.md` files there being the pages — and a fake of what the
shares backend does for them (server/backends/shares.py): a file's id is
its share and path, so moving it changes it; a stale rev is a 409; a folder
exists before anything is in it, and takes everything in it when it goes.

The tests speak in tree paths — `Projects/Garden/beds` — the way the tree
shows them: the fake keeps `note_files` by those, and serves each as
`Notes/<path>.md`. A FakeClient mixes this in, ahead of FakeFiles, and
hands every other file, and every other datamodel, on.
"""

from __future__ import annotations

import base64
import copy

from cloudmorrow.client.api import ApiError

STAMP = "2026-09-01T09:00:00+00:00"
ROOT = "Notes"
SUFFIX = ".md"

FILE_MODEL = {
    "id": "file",
    "version": 2,
    "label": "File",
    "description": "A file or a folder in a share or in My Files.",
    "domain": "files",
    "scopes": ["personal"],
    "title": "name",
    "ordered_within": [],
    "source": "foundation",
    "backend": "shares",
    "can": ["search", "folders", "attachments", "content"],
    "fields": [
        {"name": "share", "kind": "link", "label": "Share", "to": "share", "required": True, "indexed": True},
        {"name": "path", "kind": "string", "label": "Path", "required": True, "indexed": True},
        {"name": "folder", "kind": "string", "label": "Folder", "indexed": True},
        {"name": "name", "kind": "string", "label": "Name", "required": True, "indexed": True},
        {
            "name": "kind",
            "kind": "enum",
            "label": "Kind",
            "values": ["file", "folder"],
            "labels": ["File", "Folder"],
            "default": "file",
            "indexed": True,
        },
        {"name": "size", "kind": "int", "label": "Size", "indexed": True},
        {"name": "modified", "kind": "datetime", "label": "Modified", "indexed": True},
        {"name": "mime", "kind": "string", "label": "Type", "indexed": True},
        {"name": "text", "kind": "text", "label": "Text"},
    ],
}

NOTES_QUILL = {
    "id": "notes",
    "name": "Notes",
    "version": "2.0.0",
    "summary": "Markdown notes in folders, with pictures.",
    "category": "personal",
    "icon": "notes",
    "publisher": "Cloudmorrow",
    "license": "AGPL-3.0-or-later",
    "uses": ["file"],
    "extends": {},
    "introduces": [],
    "grants": [],
    "screens": [
        {
            "id": "notes",
            "kit": "editor",
            "label": "Notes",
            "model": "file",
            "where": {"share": "my-files", "within": ROOT},
            "suffix": SUFFIX,
            "title": "name",
            "body": "text",
            "path": "path",
        },
    ],
    "jobs": [],
    "datasets": [{"id": "welcome", "model": "file", "seed": "per-owner", "count": 1}],
    "services": [],
    "webhooks": [],
    "apis": [],
    "data": [{"id": "file", "label": "File", "how": "uses", "foundation": True, "new": False}],
    "surfaces": ["phone", "web", "terminal", "command line", "assistant"],
    "installed_version": "2.0.0",
    "runs_code": [],
    "runs_as": "",
    "reach": [],
    "enabled": True,
    "models": {"file": FILE_MODEL},
}


def note_id(path: str) -> str:
    """A page's id, by its tree path: what the real store makes of `my-files/Notes/<path>.md`."""
    return "n_" + base64.urlsafe_b64encode(path.encode()).decode().rstrip("=")


def whole(path: str) -> str:
    return f"{ROOT}/{path}{SUFFIX}"


def tree_path(raw: str) -> str:
    """`Notes/ideas/garden.md` as the tree says it: `ideas/garden`."""
    path = str(raw or "").strip("/")
    if path.startswith(ROOT + "/"):
        path = path[len(ROOT) + 1 :]
    elif path == ROOT:
        path = ""
    return path[: -len(SUFFIX)] if path.endswith(SUFFIX) else path


def _is_page(record_id: str) -> bool:
    return str(record_id).startswith("n_")


class FakeNotes:
    """Notes as the record API serves them — mixed into FakeClient before FakeFiles."""

    def setup_notes(self) -> None:
        self.quill_list.insert(0, copy.deepcopy(NOTES_QUILL))
        # tree path (no root, no .md) -> [text, rev]
        self.note_files: dict[str, list] = {"architecture": ["# Architecture\n", 1]}
        self.note_folders: set[str] = set()
        self.note_calls: list[tuple] = []

    # -- the envelope -------------------------------------------------------------
    def _note(self, path: str, *, body: bool = True, preview: str | None = None) -> dict:
        text, rev = self.note_files[path]
        folder, _, title = path.rpartition("/")
        row = {
            "id": note_id(path),
            "model": "file",
            "owner": "bram",
            "scope": "personal",
            "rev": f"{rev}-x",
            "position": 0,
            "fields": {
                "share": "my-files",
                "path": whole(path),
                "folder": f"{ROOT}/{folder}" if folder else ROOT,
                "name": title + SUFFIX,
                "kind": "file",
                "size": len(text.encode()),
                "modified": STAMP,
                "mime": "text/markdown",
                "text": text if body else None,
            },
            "written_by": "files",
            "created_at": STAMP,
            "updated_at": STAMP,
            "expires_at": None,
        }
        if preview is not None:
            row["preview"] = preview
        return row

    def _path_of(self, record_id: str) -> str:
        for path in self.note_files:
            if note_id(path) == record_id:
                return path
        raise ApiError("no such record", status_code=404)

    def _new_path(self, fields: dict, current: str = "") -> str:
        if fields.get("path"):
            return tree_path(str(fields["path"]))
        folder, _, title = current.rpartition("/")
        if "folder" in fields:
            folder = tree_path(str(fields.get("folder") or ""))
        if "name" in fields:
            title = tree_path(str(fields.get("name") or ""))
        return f"{folder}/{title}" if folder else title

    # -- the five calls, for the pages; everything else on ----------------------------
    async def records(self, model: str, **where: object) -> list[dict]:
        if model != "file" or "within" not in where:
            return await super().records(model, **where)
        self.note_calls.append(("list", dict(where)))
        query = str(where.pop("q", "") or "").lower()
        rows = []
        for path in sorted(self.note_files, key=str.casefold):
            if query:
                lines = [ln for ln in self.note_files[path][0].splitlines() if query in ln.lower()]
                if not lines and query not in path.lower():
                    continue
                rows.append(self._note(path, body=False, preview=lines[0] if lines else ""))
            else:
                rows.append(self._note(path, body=False))
        return rows

    async def record(self, model: str, record_id: str) -> dict:
        if model != "file" or not _is_page(record_id):
            return await super().record(model, record_id)
        return self._note(self._path_of(record_id))

    async def create_record(
        self, model: str, fields: dict, *, index: int | None = None, scope: str | None = None
    ) -> dict:
        if model != "file" or "text" not in fields:
            return await super().create_record(model, fields, index=index, scope=scope)
        path = self._new_path(fields)
        if path in self.note_files:
            raise ApiError(f"there is already something called {path}", status_code=400)
        self.note_calls.append(("create", path))
        self.note_files[path] = [str(fields.get("text") or ""), 1]
        return self._note(path)

    async def update_record(self, model: str, record_id: str, fields: dict, *, rev: object = None) -> dict:
        if model != "file" or not _is_page(record_id):
            return await super().update_record(model, record_id, fields, rev=rev)
        path = self._path_of(record_id)
        self.note_calls.append(("update", path, dict(fields)))
        if "text" in fields:
            if rev is not None and rev != self._note(path)["rev"]:
                raise ApiError("changed since you read it", status_code=409)
            self.note_files[path][0] = str(fields["text"])
            self.note_files[path][1] += 1
        moved = self._new_path({k: v for k, v in fields.items() if k != "text"}, path)
        if moved and moved != path:
            if moved in self.note_files:
                raise ApiError(f"there is already something called {moved}", status_code=400)
            self.note_files[moved] = self.note_files.pop(path)
            path = moved
        return self._note(path)

    async def delete_record(self, model: str, record_id: str) -> None:
        if model != "file" or not _is_page(record_id):
            return await super().delete_record(model, record_id)
        path = self._path_of(record_id)
        self.note_calls.append(("delete", path))
        del self.note_files[path]

    # -- folders and attachments, within the root -----------------------------------------
    async def record_folders(self, model: str, **where: object) -> list[dict]:
        found = set(self.note_folders)
        for path in self.note_files:
            folder = path.rpartition("/")[0]
            while folder:
                found.add(folder)
                folder = folder.rpartition("/")[0]
        return [{"path": f"{ROOT}/{f}", "name": f.rsplit("/", 1)[-1], "count": 0} for f in sorted(found)]

    async def make_record_folder(self, model: str, path: str, **where: object) -> dict:
        path = tree_path(path)
        self.note_calls.append(("mkdir", path))
        self.note_folders.add(path)
        return {"path": f"{ROOT}/{path}", "name": path.rsplit("/", 1)[-1]}

    async def move_record_folder(self, model: str, path: str, to: str, **where: object) -> dict:
        path, to = tree_path(path), tree_path(to)
        self.note_calls.append(("mvdir", path, to))
        self.note_folders = {
            to + f[len(path) :] if f == path or f.startswith(path + "/") else f for f in self.note_folders
        }
        for old in [p for p in self.note_files if p.startswith(path + "/")]:
            self.note_files[to + old[len(path) :]] = self.note_files.pop(old)
        return {"path": f"{ROOT}/{to}", "name": to.rsplit("/", 1)[-1]}

    async def delete_record_folder(self, model: str, path: str, **where: object) -> None:
        path = tree_path(path)
        self.note_calls.append(("rmdir", path))
        self.note_folders = {f for f in self.note_folders if f != path and not f.startswith(path + "/")}
        for old in [p for p in self.note_files if p.startswith(path + "/")]:
            del self.note_files[old]

    async def attach(self, model: str, data: bytes, *, filename: str = "", **where: object) -> dict:
        return await self.upload_image(data, filename=filename)

    async def attachment(self, model: str, name: str, **where: object) -> bytes:
        return await self.image(name)
