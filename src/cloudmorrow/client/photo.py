"""A photo editor's writes, as the terminal and the command line make them.

The sums are cloudmorrow.quill.photo's; this is what turns one of them into
records: an edit started from a photo in the drive, a turn, a crop, a size,
the words laid on the picture. Both surfaces edit through a `Photo`, so a
crop typed with `cm retouch crop` is the crop `c` makes in the terminal.
"""

from __future__ import annotations

import json

from cloudmorrow.client.api import ApiError
from cloudmorrow.quill import photo as ph
from cloudmorrow.quill.screens import photo_fields, pictures_path

# What a photo is, by its name or its type: the same list the web app has.
PHOTO_EXT = frozenset({"jpg", "jpeg", "png", "gif", "webp", "bmp", "tif", "tiff", "heic", "heif", "avif"})


def is_photo(name: str, mime: str = "") -> bool:
    if str(mime).startswith("image/"):
        return True
    ext = str(name).rsplit(".", 1)[-1].lower() if "." in str(name) else ""
    return ext in PHOTO_EXT


class Photo:
    """One photo screen's datamodels and pictures API, and the writes made on them."""

    def __init__(self, api, quill: dict, screen: dict) -> None:
        self.api = api
        self.quill = quill
        self.spec = screen
        models = quill.get("models") or {}
        self.model: dict = models.get(screen["model"]) or {"id": screen["model"], "fields": []}
        self.bound = photo_fields(screen, self.model, models)
        self.edit_model: str = self.bound["edit"]
        self.text_model: str = self.bound["texts"]
        self.title: str = self.bound["title"]
        self.media: dict = self.bound["media"]
        self.pictures: str | None = pictures_path(quill, screen)
        export = self.bound["export"]
        self.export: dict | None = next((a for a in quill.get("actions", []) if a.get("id") == export), None)

    # -- reading -----------------------------------------------------------------
    async def edits(self) -> list[dict]:
        """Every edit, newest first."""
        found = await self.api.records(self.edit_model)
        return sorted(reversed(found), key=lambda r: str(r.get("created_at") or ""), reverse=True)

    async def texts(self, edit_id: str) -> list[dict]:
        """The words on one edit, oldest first."""
        if not self.text_model:
            return []
        found = await self.api.records(self.text_model, **{self.bound["text_edit"]: edit_id})
        return sorted(found, key=lambda r: str(r.get("created_at") or ""))

    async def material(self) -> list[dict]:
        """The photos under `media`, by folder and name."""
        found = await self.api.records("file", **self.media)
        photos = []
        for record in found:
            f = record.get("fields") or {}
            if f.get("kind") == "folder" or not is_photo(str(f.get("name") or ""), str(f.get("mime") or "")):
                continue
            photos.append(record)
        return sorted(photos, key=lambda r: (str(r["fields"].get("folder") or ""), str(r["fields"].get("name") or "")))

    async def info(self, file_id: str) -> dict | None:
        """What the pictures API says of a photo — its width and height — or None without one."""
        if not self.pictures:
            return None
        response = await self.api.quill_api(self.pictures + "/info", {"file": file_id})
        try:
            answer = response.json()
        except (ValueError, json.JSONDecodeError):
            return None
        return answer if isinstance(answer, dict) else None

    async def picture(self, edit_id: str, width: int) -> bytes:
        """The edit as it would export, as a JPEG *width* pixels wide. Only with a pictures API."""
        if not self.pictures:
            raise ApiError("this editor has no pictures API to draw the picture", status_code=404)
        response = await self.api.quill_api(self.pictures + "/picture", {"edit": edit_id, "w": int(width)})
        return response.content

    # -- writing -----------------------------------------------------------------
    async def new_edit(self, file: dict, name: str = "") -> dict:
        """An edit of *file* (a file record), called *name* or the file's name without its suffix."""
        f = file.get("fields") or {}
        stem = str(f.get("name") or "").rsplit(".", 1)[0] or "Photo"
        fields = {self.title: name.strip() or stem, "source": file["id"]}
        info = await self.info(file["id"])
        if info and int(info.get("width") or 0) > 0 and int(info.get("height") or 0) > 0:
            fields.update(width=int(info["width"]), height=int(info["height"]))
        return await self.api.create_record(self.edit_model, fields)

    async def update(self, edit: dict, fields: dict) -> dict:
        return await self.api.update_record(self.edit_model, edit["id"], fields)

    async def rotate(self, edit: dict, by: int) -> dict:
        """The edit turned *by* degrees more, clockwise; -90 is a quarter turn the other way."""
        now = ph.rotation_of(edit.get("fields") or {})
        return await self.update(edit, {"rotate": (now + by) % 360})

    async def mirror(self, edit: dict) -> dict:
        return await self.update(edit, {"mirror": not ph.mirrored(edit.get("fields") or {})})

    async def crop(self, edit: dict, box: dict | None) -> dict:
        """The edit's crop set to *box*; None keeps the whole picture."""
        whole = box is None or box == ph.WHOLE
        return await self.update(edit, {"crop": None if whole else box})

    async def resize(self, edit: dict, size: dict) -> dict:
        """The export's size: `out_width` and `out_height`, as photo.size_from answers."""
        return await self.update(edit, {"out_width": size.get("out_width"), "out_height": size.get("out_height")})

    async def add_text(self, edit: dict, words: str, **where) -> dict:
        """Words on the picture: at `x`, `y`, `size` and `colour` when given, else the kit's start."""
        if not self.text_model:
            raise ApiError("this editor has no texts: nothing to write on the picture", status_code=404)
        fields = {
            self.bound["text_edit"]: edit["id"],
            "text": words,
            **ph.TEXT_AT,
            "size": ph.TEXT_SIZE,
            "colour": ph.TEXT_COLOUR,
        }
        fields.update({k: v for k, v in where.items() if v is not None})
        return await self.api.create_record(self.text_model, fields)

    async def set_text(self, text: dict, fields: dict) -> dict:
        return await self.api.update_record(self.text_model, text["id"], fields)

    async def remove_text(self, text: dict) -> None:
        await self.api.delete_record(self.text_model, text["id"])


__all__ = ["Photo", "is_photo"]
