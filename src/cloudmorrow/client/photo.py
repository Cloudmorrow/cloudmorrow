"""A photo editor's writes, as the terminal and the command line make them.

The sums are cloudmorrow.quill.photo's; this is what turns one of them into
records: an edit started from a photo in the drive, a turn, a crop, a size,
the layers laid on the picture (words, marker strokes, pieces), and a save
over the photo or beside it. Both surfaces edit through a `Photo`, so a
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
        self.layer_model: str = self.bound["layers"]
        self.title: str = self.bound["title"]
        self.media: dict = self.bound["media"]
        self.pictures: str | None = pictures_path(quill, screen)
        actions = quill.get("actions", [])
        self.export: dict | None = next((a for a in actions if a.get("id") == self.bound["export"]), None)
        self.save_action: dict | None = next((a for a in actions if a.get("id") == self.bound["save"]), None)

    # -- reading -----------------------------------------------------------------
    async def edits(self) -> list[dict]:
        """Every edit, newest first."""
        found = await self.api.records(self.edit_model)
        return sorted(reversed(found), key=lambda r: str(r.get("created_at") or ""), reverse=True)

    async def layers(self, edit_id: str) -> list[dict]:
        """The layers on one edit, lowest first."""
        if not self.layer_model:
            return []
        found = await self.api.records(self.layer_model, **{self.bound["layer_edit"]: edit_id})
        return ph.layers_in_order(found)

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
        """The edit as it would save, as a JPEG *width* pixels wide. Only with a pictures API."""
        if not self.pictures:
            raise ApiError("this editor has no pictures API to draw the picture", status_code=404)
        response = await self.api.quill_api(self.pictures + "/picture", {"edit": edit_id, "w": int(width)})
        return response.content

    async def source_file(self, edit: dict) -> dict | None:
        """The photo's file record, for its name; None when it is gone."""
        source = str((edit.get("fields") or {}).get("source") or "")
        if not source:
            return None
        try:
            return await self.api.record("file", source)
        except ApiError:
            return None

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
        """The save's size: `out_width` and `out_height`, as photo.size_from answers."""
        return await self.update(edit, {"out_width": size.get("out_width"), "out_height": size.get("out_height")})

    async def add_layer(self, edit: dict, kind: str, **fields) -> dict:
        """A layer on top of the others: words (`text=`), a mark (`points=`), or a piece (`source=`)."""
        if not self.layer_model:
            raise ApiError("this editor has no layers: nothing to put on the picture", status_code=404)
        if kind not in ph.KINDS:
            raise ApiError(f"a layer is one of {', '.join(ph.KINDS)}, not {kind}", status_code=422)
        on = await self.layers(edit["id"])
        top = max((int(float((r.get("fields") or {}).get("order") or 0)) for r in on), default=-1) + 1
        record = {self.bound["layer_edit"]: edit["id"], "kind": kind, "order": top, **ph.TEXT_AT}
        if kind == "text":
            record.update(size=ph.TEXT_SIZE, colour=ph.TEXT_COLOUR)
        elif kind == "mark":
            record.update(width=ph.MARK_WIDTH, opacity=ph.MARK_OPACITY, colour="#e0323c")
        record.update({k: v for k, v in fields.items() if v is not None})
        return await self.api.create_record(self.layer_model, record)

    async def add_text(self, edit: dict, words: str, **where) -> dict:
        return await self.add_layer(edit, "text", text=words, **where)

    async def set_layer(self, layer: dict, fields: dict) -> dict:
        return await self.api.update_record(self.layer_model, layer["id"], fields)

    async def remove_layer(self, layer: dict) -> None:
        await self.api.delete_record(self.layer_model, layer["id"])

    async def save(self, edit: dict, *, overwrite: bool, name: str = "") -> list[dict]:
        """The save action pressed: over the photo, or as *name* beside it. The effects."""
        if self.save_action is None:
            raise ApiError("this editor has no save", status_code=404)
        if not overwrite and not name.strip():
            raise ApiError("saving as a new file needs a name", status_code=422)
        source = await self.source_file(edit)
        fields = {
            "overwrite": overwrite,
            "name": name.strip() or str(((source or {}).get("fields") or {}).get("name") or ""),
        }
        return await self.api.quill_action(self.quill["id"], self.save_action["id"], record=edit["id"], fields=fields)


__all__ = ["Photo", "is_photo"]
