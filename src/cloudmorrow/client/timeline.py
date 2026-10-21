"""A timeline's writes, as the terminal and the command line make them.

The sums are cloudmorrow.quill.timeline's; this is what turns one of them
into records: a trim that rewrites the piece's effects with it, a split that
makes the second piece and shares the effects out, a piece added from a
file with its length and the project's size. Both surfaces edit through a
`Timeline`, so a cut made with `cm cutter cut` is the cut `s` makes.
"""

from __future__ import annotations

import json

from cloudmorrow.client.api import ApiError
from cloudmorrow.quill import timeline as tl
from cloudmorrow.quill.screens import frames_path, timeline_fields, tracks_of


class Timeline:
    """One timeline screen's datamodels and frames API, and the writes made on them."""

    def __init__(self, api, quill: dict, screen: dict) -> None:
        self.api = api
        self.quill = quill
        self.spec = screen
        models = quill.get("models") or {}
        self.model: dict = models.get(screen["model"]) or {"id": screen["model"], "fields": []}
        self.bound = timeline_fields(screen, self.model, models)
        self.project_model: str = self.bound["project"]
        self.piece_model: str = self.bound["pieces"]
        self.effect_model: str = self.bound["effects"]
        self.title: str = self.bound["title"]
        self.media: dict = self.bound["media"]
        self.frames: str | None = frames_path(quill, screen)
        export = self.bound["export"]
        self.export: dict | None = next((a for a in quill.get("actions", []) if a.get("id") == export), None)

    # -- reading -----------------------------------------------------------------
    async def projects(self) -> list[dict]:
        """Every project, newest first."""
        found = await self.api.records(self.project_model)
        # Listed in the order they were made; two made in the same second keep it, turned round.
        return sorted(reversed(found), key=lambda r: str(r.get("created_at") or ""), reverse=True)

    async def pieces(self, project_id: str) -> list[dict]:
        return await self.api.records(self.piece_model, **{self.bound["piece_project"]: project_id})

    async def effects(self, pieces: list[dict]) -> dict[str, list[dict]]:
        """The effects of *pieces*, by piece id: one listing, kept to these pieces."""
        if not self.effect_model:
            return {}
        link = self.bound["effect_piece"]
        ids = {p["id"] for p in pieces}
        by_piece: dict[str, list[dict]] = {i: [] for i in ids}
        if not ids:
            return by_piece
        for effect in await self.api.records(self.effect_model):
            piece = str((effect.get("fields") or {}).get(link) or "")
            if piece in by_piece:
                by_piece[piece].append(effect)
        return by_piece

    async def material(self) -> list[dict]:
        """The videos and sounds under `media`, by folder and name, each with its `kind`."""
        found = await self.api.records("file", **self.media)
        material = []
        for record in found:
            f = record.get("fields") or {}
            if f.get("kind") == "folder":
                continue
            kind = tl.media_kind(str(f.get("name") or ""), str(f.get("mime") or ""))
            if kind:
                material.append({**record, "kind": kind})
        return sorted(
            material,
            key=lambda r: (str(r["fields"].get("folder") or ""), str(r["fields"].get("name") or "").casefold()),
        )

    async def info(self, file_id: str) -> dict | None:
        """What the frames API says of a file — duration, size, fps — or None without one."""
        if not self.frames:
            return None
        response = await self.api.quill_api(self.frames + "/info", {"file": file_id})
        try:
            answer = response.json()
        except (ValueError, json.JSONDecodeError):
            return None
        return answer if isinstance(answer, dict) else None

    async def frame(self, project_id: str, t: float, width: int) -> bytes:
        """The cut at *t* as a JPEG, *width* pixels wide. Only with a frames API."""
        if not self.frames:
            raise ApiError("this timeline has no frames API to draw a frame", status_code=404)
        response = await self.api.quill_api(
            self.frames + "/frame", {"project": project_id, "t": f"{t:.3f}", "w": int(width)}
        )
        return response.content

    # -- writing -----------------------------------------------------------------
    @property
    def keeps_size(self) -> bool:
        """Whether a project here keeps a size of its own (width and height)."""
        return {"width", "height"} <= set(self.bound["fields"])

    async def new_project(self, name: str, size: dict | None = None) -> dict:
        """A project called *name*, *size* (width and height) when one is given;
        otherwise the first clip added gives it its own."""
        fields = {self.title: name}
        if size and self.keeps_size:
            fields.update(width=size["width"], height=size["height"])
        return await self.api.create_record(self.project_model, fields)

    async def add(
        self,
        project: dict,
        file: dict,
        *,
        at: float,
        length: float,
        track: str = "",
        info: dict | None = None,
    ) -> dict:
        """*file* on the timeline at *at*, all *length* of it, on *track* or the first
        track of its kind; the project gets its size and fps from *info* when it has none."""
        tracks = tracks_of(project.get("fields") or {})
        if not track:
            first = tl.first_track(tracks, file.get("kind") or "video")
            if first is None:
                raise ApiError(f"the project has no {file.get('kind')} track", status_code=400)
            track = first["id"]
        elif track not in {t["id"] for t in tracks}:
            raise ApiError(f"the project has no track {track}: {', '.join(t['id'] for t in tracks)}", status_code=400)
        name = str((file.get("fields") or {}).get("name") or file["id"])
        fields = {
            self.bound["piece_project"]: project["id"],
            "track": track,
            "source": file["id"],
            "name": name,
            "start": round(max(at, 0.0), 6),
            "offset": 0,
            "length": round(max(length, tl.SHORTEST), 6),
        }
        made = await self.api.create_record(self.piece_model, fields)
        await self.sized(project, info)
        return made

    async def sized(self, project: dict, info: dict | None) -> dict | None:
        """The project's width, height and fps from *info*, where it has none yet."""
        if not info:
            return None
        have = project.get("fields") or {}
        changes = {}
        for name in ("width", "height", "fps"):
            if name in self.bound["fields"] and have.get(name) in (None, "", 0) and info.get(name):
                changes[name] = info[name]
        if not changes:
            return None
        return await self.api.update_record(self.project_model, project["id"], changes)

    async def update(self, piece: dict, fields: dict) -> dict:
        return await self.api.update_record(self.piece_model, piece["id"], fields)

    async def trim(
        self,
        piece: dict,
        effects: list[dict],
        *,
        start: float | None = None,
        end: float | None = None,
        source_length: float | None = None,
    ) -> dict:
        """*piece* begun at *start* or ended at *end*; a new start rewrites its effects' times."""
        fields = piece.get("fields") or {}
        if start is not None:
            changes, change = tl.trim_start(fields, start)
            if change:
                for effect in effects:
                    kfs = (effect.get("fields") or {}).get("keyframes")
                    await self.api.update_record(
                        self.effect_model, effect["id"], {"keyframes": tl.shift_keyframes(kfs, change)}
                    )
        else:
            changes = tl.trim_end(fields, end if end is not None else tl.end_of(fields), source_length)
        return await self.update(piece, changes)

    async def cut(self, piece: dict, effects: list[dict], at: float) -> dict | None:
        """*piece* split at *at*: the new second piece, or None when *at* is not inside it.

        Each effect stays with the half it is on, moves to the second, or is
        copied to both (`split_keyframes`).
        """
        fields = piece.get("fields") or {}
        halves = tl.split(fields, at)
        if halves is None:
            return None
        first, second = halves
        second = {k: v for k, v in second.items() if v is not None}
        cut = at - tl.seconds(fields.get("start"))
        await self.update(piece, first)
        made = await self.api.create_record(self.piece_model, second)
        link = self.bound["effect_piece"]
        for effect in effects:
            ef = effect.get("fields") or {}
            before, after = tl.split_keyframes(ef.get("keyframes"), cut)
            if after is not None:
                copy = {k: v for k, v in ef.items() if v is not None}
                await self.api.create_record(self.effect_model, {**copy, link: made["id"], "keyframes": after})
            if before is None:
                await self.api.delete_record(self.effect_model, effect["id"])
            elif before != tl.keyframes_of(ef.get("keyframes")):
                await self.api.update_record(self.effect_model, effect["id"], {"keyframes": before})
        return made

    async def remove(self, piece: dict) -> None:
        await self.api.delete_record(self.piece_model, piece["id"])

    async def add_blur(self, piece: dict, t: float, label: str = "Blur") -> dict:
        """A blur on *piece* with its box in the middle, keyframed *t* seconds into the piece."""
        return await self.api.create_record(
            self.effect_model,
            {
                self.bound["effect_piece"]: piece["id"],
                "kind": "blur",
                "label": label,
                "strength": 20,
                "keyframes": [{"t": round(max(t, 0.0), 4), **tl.MIDDLE}],
            },
        )

    async def keyframe(self, effect: dict, t: float, box: dict, fps: float) -> dict:
        kfs = tl.set_keyframe((effect.get("fields") or {}).get("keyframes"), t, box, fps)
        return await self.api.update_record(self.effect_model, effect["id"], {"keyframes": kfs})

    async def unkeyframe(self, effect: dict, index: int) -> dict:
        kfs = tl.keyframes_of((effect.get("fields") or {}).get("keyframes"))
        del kfs[index]
        return await self.api.update_record(self.effect_model, effect["id"], {"keyframes": kfs})

    async def crop(self, project: dict, box: dict | None) -> dict:
        """The project's crop set to *box*; None keeps the whole picture."""
        whole = box is None or box == tl.WHOLE
        return await self.api.update_record(self.project_model, project["id"], {"crop": None if whole else box})


__all__ = ["Timeline"]
