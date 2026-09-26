"""The Notes half of the fake server the TUI tests drive.

The Notes Quill is installed, as `GET /api/quills` sends it — one `editor`
screen on the `note` datamodel, which can search, keep folders and keep
attachments — and a note backend that keeps the promises the real one
makes (server/backends.py): a note's id is its path, so moving it changes
it; a stale rev is a 409; a folder exists before anything is in it, and
takes everything in it when it goes. A FakeClient mixes this in, ahead of
FakeQuills, and hands every other datamodel on.
"""

from __future__ import annotations

import base64
import copy

from cloudmorrow.client.api import ApiError

STAMP = "2026-09-01T09:00:00+00:00"

NOTE_MODEL = {
    "id": "note",
    "version": 1,
    "label": "Note",
    "description": "Markdown in a folder, with pictures.",
    "domain": "notes",
    "scopes": ["personal"],
    "title": "title",
    "ordered_within": [],
    "source": "foundation",
    "backend": "notes",
    "can": ["search", "folders", "attachments"],
    "fields": [
        {"name": "path", "kind": "string", "label": "Path", "required": True, "indexed": True},
        {"name": "folder", "kind": "string", "label": "Folder", "indexed": True},
        {"name": "title", "kind": "string", "label": "Title", "indexed": True},
        {"name": "body", "kind": "markdown", "label": "Body"},
        {"name": "modified", "kind": "datetime", "label": "Modified", "indexed": True},
    ],
}

NOTES_QUILL = {
    "id": "notes",
    "name": "Notes",
    "version": "1.0.0",
    "summary": "Markdown notes in folders, with pictures.",
    "category": "personal",
    "icon": "notes",
    "publisher": "Cloudmorrow",
    "license": "AGPL-3.0-or-later",
    "uses": ["note"],
    "extends": {},
    "introduces": [],
    "grants": [],
    "screens": [
        {"id": "notes", "kit": "editor", "label": "Notes", "model": "note", "title": "title",
         "body": "body", "path": "path"},
    ],
    "jobs": [],
    "datasets": [{"id": "welcome", "model": "note", "seed": "per-owner", "count": 1}],
    "services": [],
    "webhooks": [],
    "apis": [],
    "data": [{"id": "note", "label": "Note", "how": "uses", "foundation": True, "new": False}],
    "surfaces": ["phone", "web", "terminal", "command line", "assistant"],
    "installed_version": "1.0.0",
    "not_running_yet": [],
    "enabled": True,
    "models": {"note": NOTE_MODEL},
}


def note_id(path: str) -> str:
    return "n_" + base64.urlsafe_b64encode(path.encode()).decode().rstrip("=")


class FakeNotes:
    """Notes as the record API serves them — mixed into FakeClient before FakeQuills."""

    def setup_notes(self) -> None:
        self.quill_list.insert(0, copy.deepcopy(NOTES_QUILL))
        # path (no .md) -> [body, rev]
        self.note_files: dict[str, list] = {"architecture": ["# Architecture\n", 1]}
        self.note_folders: set[str] = set()
        self.note_calls: list[tuple] = []

    # -- the envelope -------------------------------------------------------------
    def _note(self, path: str, *, body: bool = True, preview: str | None = None) -> dict:
        text, rev = self.note_files[path]
        folder, _, title = path.rpartition("/")
        row = {
            "id": note_id(path), "model": "note", "owner": "bram", "scope": "personal",
            "rev": f"{rev}-x", "position": 0,
            "fields": {"path": path, "folder": folder, "title": title,
                       "body": text if body else None, "modified": STAMP},
            "written_by": "notes", "created_at": STAMP, "updated_at": STAMP, "expires_at": None,
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
            return str(fields["path"]).strip("/")
        folder, _, title = current.rpartition("/")
        folder = str(fields.get("folder", folder) or "")
        title = str(fields.get("title", title) or "")
        return f"{folder}/{title}" if folder else title

    # -- the five calls, for notes; everything else to the record store --------------
    async def records(self, model: str, **where: object) -> list[dict]:
        if model != "note":
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
        if model != "note":
            return await super().record(model, record_id)
        return self._note(self._path_of(record_id))

    async def create_record(
        self, model: str, fields: dict, *, index: int | None = None, scope: str | None = None
    ) -> dict:
        if model != "note":
            return await super().create_record(model, fields, index=index, scope=scope)
        path = self._new_path(fields)
        if path in self.note_files:
            raise ApiError(f"there is already a note called {path}", status_code=400)
        self.note_calls.append(("create", path))
        self.note_files[path] = [str(fields.get("body") or ""), 1]
        return self._note(path)

    async def update_record(
        self, model: str, record_id: str, fields: dict, *, rev: object = None
    ) -> dict:
        if model != "note":
            return await super().update_record(model, record_id, fields, rev=rev)
        path = self._path_of(record_id)
        self.note_calls.append(("update", path, dict(fields)))
        if "body" in fields:
            if rev is not None and rev != self._note(path)["rev"]:
                raise ApiError("changed since you read it", status_code=409)
            self.note_files[path][0] = str(fields["body"])
            self.note_files[path][1] += 1
        moved = self._new_path({k: v for k, v in fields.items() if k != "body"}, path)
        if moved and moved != path:
            if moved in self.note_files:
                raise ApiError(f"there is already a note called {moved}", status_code=400)
            self.note_files[moved] = self.note_files.pop(path)
            path = moved
        return self._note(path)

    async def delete_record(self, model: str, record_id: str) -> None:
        if model != "note":
            return await super().delete_record(model, record_id)
        path = self._path_of(record_id)
        self.note_calls.append(("delete", path))
        del self.note_files[path]

    # -- folders and attachments ------------------------------------------------------
    async def record_folders(self, model: str) -> list[dict]:
        found = set(self.note_folders)
        for path in self.note_files:
            folder = path.rpartition("/")[0]
            while folder:
                found.add(folder)
                folder = folder.rpartition("/")[0]
        return [{"path": f, "name": f.rsplit("/", 1)[-1], "count": 0} for f in sorted(found)]

    async def make_record_folder(self, model: str, path: str) -> dict:
        self.note_calls.append(("mkdir", path))
        self.note_folders.add(path)
        return {"path": path, "name": path.rsplit("/", 1)[-1]}

    async def move_record_folder(self, model: str, path: str, to: str) -> dict:
        self.note_calls.append(("mvdir", path, to))
        self.note_folders = {to + f[len(path):] if f == path or f.startswith(path + "/") else f
                             for f in self.note_folders}
        for old in [p for p in self.note_files if p.startswith(path + "/")]:
            self.note_files[to + old[len(path):]] = self.note_files.pop(old)
        return {"path": to, "name": to.rsplit("/", 1)[-1]}

    async def delete_record_folder(self, model: str, path: str) -> None:
        self.note_calls.append(("rmdir", path))
        self.note_folders = {f for f in self.note_folders if f != path and not f.startswith(path + "/")}
        for old in [p for p in self.note_files if p.startswith(path + "/")]:
            del self.note_files[old]

    async def attach(self, model: str, data: bytes, *, filename: str = "") -> dict:
        return await self.upload_image(data, filename=filename)

    async def attachment(self, model: str, name: str) -> bytes:
        return await self.image(name)
