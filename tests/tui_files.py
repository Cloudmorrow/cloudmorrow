"""The Files half of the fake server the TUI tests drive.

The Files Quill, as `GET /api/quills` sends it, and the `shares` backend
behind it: `share` records made from the fake's share list and `file`
records from its share tree, with their bytes and thumbnails, a folder made,
a file put, renamed, moved and deleted — the promises server/backends.py
keeps. A FakeClient mixes this in before the Quill half, so every other
datamodel still goes to the fake record store.
"""

from __future__ import annotations

import copy
import datetime as dt

from cloudmorrow.client.api import ApiError

FILES_MODELS = {
    "share": {
        "id": "share",
        "version": 1,
        "label": "Share",
        "domain": "files",
        "scopes": ["personal"],
        "title": "label",
        "ordered_within": [],
        "source": "foundation",
        "backend": "shares",
        "fields": [
            {"name": "name", "kind": "string", "label": "Name", "required": True, "indexed": True},
            {"name": "label", "kind": "string", "label": "Shown as", "indexed": True},
            {
                "name": "kind",
                "kind": "enum",
                "label": "Kind",
                "indexed": True,
                "default": "server",
                "values": ["drive", "server", "machine"],
                "labels": ["My Files", "On the server", "On a machine"],
            },
            {"name": "description", "kind": "text", "label": "Description"},
            {"name": "machine", "kind": "string", "label": "Machine", "indexed": True},
            {"name": "path", "kind": "string", "label": "Path"},
            {"name": "online", "kind": "bool", "label": "Online", "indexed": True},
            {"name": "browsable", "kind": "bool", "label": "Browsable", "indexed": True},
            {"name": "about", "kind": "string", "label": "About"},
            {"name": "url", "kind": "url", "label": "Url"},
        ],
    },
    "file": {
        "id": "file",
        "version": 1,
        "label": "File",
        "domain": "files",
        "scopes": ["personal"],
        "title": "name",
        "ordered_within": [],
        "source": "foundation",
        "backend": "shares",
        "fields": [
            {
                "name": "share",
                "kind": "link",
                "label": "Share",
                "required": True,
                "indexed": True,
                "to": "share",
            },
            {"name": "path", "kind": "string", "label": "Path", "required": True, "indexed": True},
            {"name": "folder", "kind": "string", "label": "Folder", "indexed": True},
            {"name": "name", "kind": "string", "label": "Name", "required": True, "indexed": True},
            {
                "name": "kind",
                "kind": "enum",
                "label": "Kind",
                "indexed": True,
                "default": "file",
                "values": ["file", "folder"],
                "labels": ["File", "Folder"],
            },
            {"name": "size", "kind": "int", "label": "Size", "indexed": True},
            {"name": "modified", "kind": "datetime", "label": "Modified", "indexed": True},
            {"name": "mime", "kind": "string", "label": "Type", "indexed": True},
        ],
    },
}

FILES_QUILL = {
    "id": "files",
    "name": "Files",
    "version": "1.0.0",
    "summary": "Your own drive on the server, your fileshares, and what is in them.",
    "category": "personal",
    "icon": "files",
    "publisher": "Cloudmorrow",
    "license": "AGPL-3.0-or-later",
    "uses": ["share", "file"],
    "extends": {},
    "introduces": [],
    "grants": [],
    "screens": [
        {
            "id": "files",
            "kit": "grid",
            "label": "Files",
            "model": "file",
            "title": "name",
            "group": "share",
            "group_subtitle": "about",
            "group_open": "browsable",
            "folder": "folder",
            "kind": "kind",
            "size": "size",
            "modified": "modified",
            "mime": "mime",
        },
    ],
    "jobs": [],
    "datasets": [],
    "services": [],
    "webhooks": [],
    "apis": [],
    "data": [
        {"id": "file", "label": "File", "how": "uses", "foundation": True, "new": False},
        {"id": "share", "label": "Share", "how": "uses", "foundation": True, "new": False},
    ],
    "surfaces": ["phone", "web", "terminal", "command line", "assistant"],
    "installed_version": "1.0.0",
    "runs_code": [],
    "runs_as": "",
    "reach": [],
    "enabled": True,
    "models": FILES_MODELS,
}


def _stamp(seconds: float) -> str:
    return dt.datetime.fromtimestamp(seconds, tz=dt.UTC).isoformat(timespec="seconds")


class FakeFiles:
    """Shares and their files as records — mixed into FakeClient."""

    # -- shares -----------------------------------------------------------------
    def _share_record(self, share: dict) -> dict:
        kind = share.get("kind") or "server"
        online = bool(share.get("online", True))
        if kind == "machine":
            about = f"On {share.get('machine') or 'a machine'}" + ("" if online else ", offline")
            about += " — mount it to browse it"
        elif kind == "drive":
            about = share.get("description") or "Your own files on the server"
        else:
            about = share.get("description") or "On the server"
        return {
            "id": share["name"],
            "model": "share",
            "owner": "bram",
            "scope": "personal",
            "rev": share.get("updated_at", ""),
            "position": 0,
            "written_by": "files",
            "created_at": share.get("created_at", ""),
            "updated_at": share.get("updated_at", ""),
            "expires_at": None,
            "fields": {
                "name": share["name"],
                "label": "My Files" if kind == "drive" else share["name"],
                "kind": kind,
                "description": share.get("description", ""),
                "machine": share.get("machine", ""),
                "path": share.get("path", ""),
                "online": online,
                "browsable": kind != "machine",
                "about": about,
                "url": share.get("url", ""),
            },
        }

    # -- files --------------------------------------------------------------------
    def _file_id(self, share: str, path: str) -> str:
        return f"f_{share}:{path}"

    def _file_record(self, share: str, folder: str, entry: dict) -> dict:
        path = f"{folder}/{entry['name']}" if folder else entry["name"]
        stamp = _stamp(entry.get("modified", 0))
        return {
            "id": self._file_id(share, path),
            "model": "file",
            "owner": "bram",
            "scope": "personal",
            "rev": f"{entry.get('modified', 0)}-{entry.get('size', 0)}",
            "position": 0,
            "written_by": "files",
            "created_at": stamp,
            "updated_at": stamp,
            "expires_at": None,
            "fields": {
                "share": share,
                "path": path,
                "folder": folder,
                "name": entry["name"],
                "kind": "folder" if entry.get("is_dir") else "file",
                "size": entry.get("size", 0),
                "modified": stamp,
                "mime": entry.get("mime", ""),
            },
        }

    def _folder(self, share: str, folder: str) -> list[dict]:
        found = next((s for s in self.share_list if s["name"] == share), None)
        if found is not None and (found.get("kind") == "machine"):
            raise ApiError(
                f"{share} is {self._share_record(found)['fields']['about'].lower()}",
                status_code=400,
            )
        folders = self.share_tree.get(share)
        if folders is None or folder not in folders:
            raise ApiError("no such folder", status_code=400)
        return folders[folder]

    def _locate(self, record_id: str) -> tuple[str, str, str, dict]:
        if not record_id.startswith("f_") or ":" not in record_id:
            raise ApiError("no such record", status_code=404)
        share, path = record_id[2:].split(":", 1)
        folder, _, name = path.rpartition("/")
        for entry in self.share_tree.get(share, {}).get(folder, []):
            if entry["name"] == name:
                return share, folder, name, entry
        raise ApiError("no such record", status_code=404)

    # -- the record API, for these two ------------------------------------------------
    async def records(self, model: str, **where: object) -> list[dict]:
        if model == "share":
            self.record_calls.append((model, dict(where)))
            return [self._share_record(s) for s in self.share_list]
        if model == "file":
            self.record_calls.append((model, dict(where)))
            share, folder = str(where.get("share", "")), str(where.get("folder", ""))
            self.listing_calls.append((share, folder))
            return [
                self._file_record(share, folder, e)
                for e in copy.deepcopy(self._folder(share, folder))
            ]
        return await super().records(model, **where)

    async def record(self, model: str, record_id: str) -> dict:
        if model == "file":
            share, folder, _name, entry = self._locate(record_id)
            return self._file_record(share, folder, entry)
        if model == "share":
            share = next((s for s in self.share_list if s["name"] == record_id), None)
            if share is None:
                raise ApiError("no such record", status_code=404)
            return self._share_record(share)
        return await super().record(model, record_id)

    async def create_record(
        self, model: str, fields: dict, *, index: int | None = None, scope: str | None = None
    ) -> dict:
        if model == "file":
            share, folder, name = fields["share"], fields.get("folder", ""), fields["name"]
            self.file_calls.append(("mkdir", share, folder, name))
            listing = self._folder(share, folder)
            if any(e["name"] == name for e in listing):
                raise ApiError(f"there is already something called {name} there", status_code=400)
            entry = {
                "name": name,
                "is_dir": True,
                "size": 0,
                "modified": 1_756_900_000.0,
                "mime": "",
            }
            listing.append(entry)
            path = f"{folder}/{name}" if folder else name
            self.share_tree[share][path] = []
            return self._file_record(share, folder, entry)
        return await super().create_record(model, fields, index=index, scope=scope)

    async def update_record(self, model: str, record_id: str, fields: dict, *, rev=None) -> dict:
        if model == "file":
            share, folder, name, entry = self._locate(record_id)
            self.file_calls.append(("change", record_id, dict(fields)))
            self.share_tree[share][folder].remove(entry)
            entry = dict(entry, name=fields.get("name", name))
            target = fields.get("folder", folder)
            self.share_tree[share].setdefault(target, []).append(entry)
            return self._file_record(share, target, entry)
        return await super().update_record(model, record_id, fields, rev=rev)

    async def delete_record(self, model: str, record_id: str) -> None:
        if model == "file":
            share, folder, _name, entry = self._locate(record_id)
            self.file_calls.append(("delete", record_id))
            self.share_tree[share][folder].remove(entry)
            return None
        return await super().delete_record(model, record_id)

    async def record_content(self, model: str, record_id: str) -> bytes:
        share, folder, name, _entry = self._locate(record_id)
        path = f"{folder}/{name}" if folder else name
        self.share_fetches.append(f"{share}/{path}")
        from tests.tui_harness import PNG_1PX

        return PNG_1PX

    async def record_thumb(self, model: str, record_id: str, *, size: int = 256) -> bytes:
        share, folder, name, _entry = self._locate(record_id)
        path = f"{folder}/{name}" if folder else name
        self.share_fetches.append(f"thumb:{share}/{path}@{size}")
        from tests.tui_harness import PNG_1PX

        return PNG_1PX

    async def upload_record(self, model: str, fields: dict, data: bytes) -> dict:
        share, folder, name = fields["share"], fields.get("folder", ""), fields["name"]
        self.file_calls.append(("put", share, folder, name, data))
        entry = {
            "name": name,
            "is_dir": False,
            "size": len(data),
            "modified": 1_756_900_000.0,
            "mime": "",
        }
        self._folder(share, folder).append(entry)
        return self._file_record(share, folder, entry)
