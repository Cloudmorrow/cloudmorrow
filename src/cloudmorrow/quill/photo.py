"""The photo kit's arithmetic: what every surface works out the same way.

A photo edit (docs/PHOTO.md) is one picture from the drive and what is done
to it, in this order: turned by a quarter turn or more (`rotate`), mirrored
(`mirror`), with layers laid on it in their order (words, marker strokes,
and pieces copied out of the picture, each placed in percent of the turned
picture), cropped to a box in percent of the turned picture (`crop`), and
made another size (`out_width`, `out_height`). The terminal and the command line work on
those numbers with what is here, and the web app's kit_photo_rules.js does
the same sums in JavaScript: a change to a rule here is a change there.

Nothing here talks to a server or draws anything. An edit is its fields (a
dict with `width`, `height`, `rotate`, …), a text is its fields, a box is
`{"x", "y", "w", "h"}`, and every function answers with new values rather
than changing what it was given.

The rules:

- *Turning* is clockwise, by quarter turns: 90 swaps the width and the
  height (`turned`). Any other number is brought to the nearest quarter.
- *A box* — the crop — is in percent of the turned picture; the whole
  picture is `WHOLE`, and a crop is never smaller than a twentieth each way
  (`crop_of`, `box_from`, from the timeline kit, which keeps boxes the same way).
- *A layer* has a `kind`: `text` (words at `x`, `y`, their top left corner,
  `size` percent of the picture's height, a `colour`), `mark` (a marker
  stroke: `points` in percent, `width` percent of the height, a `colour`,
  an `opacity`) or `piece` (a rectangle `source` copied out of the turned
  picture and placed at `x`, `y`, `w`, `h`). Every place is in percent of
  the turned picture, before the crop, so cropping keeps a layer on the
  same part of the photo. Layers stack by `order`, lowest first, then by
  when they were made; a `hidden` layer is kept but not drawn (`layer_of`).
- *The export's size* is the cropped picture's unless `out_width` or
  `out_height` says: one given keeps the picture's shape, both given are
  taken as typed (`output_size`). A size is typed as `1920x1080`, one
  number (the width), or a percent (`size_from`).
"""

from __future__ import annotations

import re

from cloudmorrow.quill.timeline import BOX, WHOLE, box_from, box_said, seconds

__all__ = [
    "KINDS",
    "MARK_OPACITY",
    "MARK_WIDTH",
    "HIGHLIGHT_OPACITY",
    "layer_of",
    "layer_said",
    "layers_in_order",
    "groups_of",
    "layer_of_element",
    "elements_in_order",
    "drawn",
    "new_layer_id",
    "FIRST_LAYER",
    "points_of",
    "BOX",
    "LONGEST",
    "TEXT_AT",
    "TEXT_COLOUR",
    "TEXT_SIZE",
    "WHOLE",
    "box_from",
    "box_said",
    "colour_from",
    "crop_of",
    "cropped_size",
    "mirrored",
    "output_size",
    "picture_size",
    "rotation_of",
    "size_from",
    "size_said",
    "source_size",
    "text_of",
    "text_said",
    "turned",
]

# The most pixels an export is across or down: a photo, not a billboard.
LONGEST = 8192
# The words a text starts with: a corner, white, a twentieth of the picture tall.
TEXT_AT = {"x": 6.0, "y": 6.0}
TEXT_SIZE = 6.0
TEXT_COLOUR = "#ffffff"
# What a layer can be, and what a marker stroke starts as.
KINDS = ("text", "mark", "piece")
MARK_WIDTH = 1.5
MARK_OPACITY = 1.0
HIGHLIGHT_OPACITY = 0.4
# A few colours by name, for the command line and the terminal.
COLOURS = {
    "white": "#ffffff",
    "black": "#000000",
    "red": "#e0323c",
    "amber": "#f0a81e",
    "yellow": "#f5d90a",
    "green": "#3cb371",
    "sky": "#5aa6e0",
    "blue": "#1c70b1",
    "violet": "#8a5ce0",
    "rose": "#ff6b81",
}


def _int(value: object, fallback: int = 0) -> int:
    try:
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


# -- turning ----------------------------------------------------------------------
def rotation_of(fields: dict) -> int:
    """The edit's turn, clockwise: 0, 90, 180 or 270."""
    return (round(_int(fields.get("rotate")) / 90) * 90) % 360


def mirrored(fields: dict) -> bool:
    return bool(fields.get("mirror"))


def turned(width: int, height: int, rotate: int) -> tuple[int, int]:
    """The size of a picture *rotate* degrees round: a quarter turn swaps the sides."""
    return (height, width) if rotate % 180 == 90 else (width, height)


# -- sizes ------------------------------------------------------------------------
def source_size(fields: dict) -> tuple[int, int] | None:
    """The source's size in pixels, when the edit knows it."""
    width, height = _int(fields.get("width")), _int(fields.get("height"))
    return (width, height) if width > 0 and height > 0 else None


def picture_size(fields: dict) -> tuple[int, int] | None:
    """The picture as it is worked on: the source, turned."""
    size = source_size(fields)
    return turned(*size, rotation_of(fields)) if size else None


def crop_of(fields: dict) -> dict:
    """The part of the turned picture kept: all of it when the edit says nothing."""
    crop = fields.get("crop")
    if not isinstance(crop, dict):
        return dict(WHOLE)
    x = min(max(seconds(crop.get("x"), 0.0), 0.0), 95.0)
    y = min(max(seconds(crop.get("y"), 0.0), 0.0), 95.0)
    w = min(max(seconds(crop.get("w"), 100.0), 5.0), 100.0 - x)
    h = min(max(seconds(crop.get("h"), 100.0), 5.0), 100.0 - y)
    return {"x": x, "y": y, "w": w, "h": h}


def cropped_size(fields: dict) -> tuple[int, int] | None:
    """The picture after the turn and the crop, in pixels."""
    size = picture_size(fields)
    if not size:
        return None
    crop = crop_of(fields)
    return max(1, round(size[0] * crop["w"] / 100)), max(1, round(size[1] * crop["h"] / 100))


def output_size(fields: dict) -> tuple[int, int] | None:
    """What the export is: the cropped picture's size, or what `out_width` and
    `out_height` say — one of them keeps the shape, both are taken as typed."""
    cropped = cropped_size(fields)
    wanted_w, wanted_h = _int(fields.get("out_width")), _int(fields.get("out_height"))
    if wanted_w > 0 and wanted_h > 0:
        return min(wanted_w, LONGEST), min(wanted_h, LONGEST)
    if not cropped:
        return None
    w, h = cropped
    if wanted_w > 0:
        return min(wanted_w, LONGEST), max(1, round(h * min(wanted_w, LONGEST) / w))
    if wanted_h > 0:
        return max(1, round(w * min(wanted_h, LONGEST) / h)), min(wanted_h, LONGEST)
    return w, h


def size_from(text: str, cropped: tuple[int, int] | None = None) -> dict:
    """A size as typed — `1920x1080`, `1920` (the width), `50%`, or `as is` —
    as the fields that say it. ValueError when it is none of those."""
    said = str(text or "").strip().lower().replace("×", "x")
    if said in ("", "as is", "asis", "same", "none", "reset"):
        return {"out_width": None, "out_height": None}
    if m := re.fullmatch(r"(\d+)\s*(?:x|\*|by)\s*(\d+)", said):
        w, h = int(m.group(1)), int(m.group(2))
        if not (0 < w <= LONGEST and 0 < h <= LONGEST):
            raise ValueError(f"a size is 1 to {LONGEST} pixels each way")
        return {"out_width": w, "out_height": h}
    if m := re.fullmatch(r"(\d+(?:\.\d+)?)\s*%", said):
        if not cropped:
            raise ValueError("a percent needs the picture's size, which is not known yet")
        share = float(m.group(1)) / 100
        if not 0 < share <= 10:
            raise ValueError("a percent is above 0 and at most 1000")
        return {"out_width": max(1, round(cropped[0] * share)), "out_height": max(1, round(cropped[1] * share))}
    if m := re.fullmatch(r"(\d+)(?:\s*(?:px|wide))?", said):
        w = int(m.group(1))
        if not 0 < w <= LONGEST:
            raise ValueError(f"a width is 1 to {LONGEST} pixels")
        return {"out_width": w, "out_height": None}
    raise ValueError("a size is width x height (1920x1080), a width (1920), a percent (50%), or `as is`")


def size_said(fields: dict) -> str:
    """`1920 × 1080`, or `` when the edit's size is not known yet."""
    size = output_size(fields)
    return f"{size[0]} × {size[1]}" if size else ""


# -- texts ------------------------------------------------------------------------
def colour_from(text: object) -> str | None:
    """A colour as `#rrggbb`, from `#rgb`, `#rrggbb` or one of a few names; None otherwise."""
    said = str(text or "").strip().lower()
    if said in COLOURS:
        return COLOURS[said]
    if m := re.fullmatch(r"#?([0-9a-f]{3})", said):
        return "#" + "".join(ch * 2 for ch in m.group(1))
    if m := re.fullmatch(r"#?([0-9a-f]{6})", said):
        return "#" + m.group(1)
    return None


def text_of(fields: dict) -> dict:
    """A text's fields as the kit draws them: its words, where, how big, which colour."""
    return {
        "text": str(fields.get("text") or ""),
        "x": min(max(seconds(fields.get("x"), TEXT_AT["x"]), 0.0), 100.0),
        "y": min(max(seconds(fields.get("y"), TEXT_AT["y"]), 0.0), 100.0),
        "size": min(max(seconds(fields.get("size"), TEXT_SIZE), 0.5), 100.0),
        "colour": colour_from(fields.get("colour")) or TEXT_COLOUR,
    }


def text_said(fields: dict) -> str:
    """`"Hello" at 6 6, 6% tall, #ffffff`."""
    t = text_of(fields)
    words = t["text"].replace("\n", " / ")
    return f"{words!r} at {t['x']:g} {t['y']:g}, {t['size']:g}% tall, {t['colour']}"


# -- layers -----------------------------------------------------------------------
def points_of(value: object) -> list[list[float]]:
    """A mark's points, `[[x, y], …]` in percent, kept inside the picture; what is not a point is dropped."""
    out: list[list[float]] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            try:
                x, y = float(item[0]), float(item[1])
            except (TypeError, ValueError):
                continue
            out.append([min(max(x, 0.0), 100.0), min(max(y, 0.0), 100.0)])
    return out


def _box(value: object, fallback: dict | None = None) -> dict | None:
    if not isinstance(value, dict):
        return dict(fallback) if fallback else None
    x = min(max(seconds(value.get("x")), 0.0), 100.0)
    y = min(max(seconds(value.get("y")), 0.0), 100.0)
    w = min(max(seconds(value.get("w"), 10.0), 0.5), 100.0 - x)
    h = min(max(seconds(value.get("h"), 10.0), 0.5), 100.0 - y)
    return {"x": x, "y": y, "w": w, "h": h}


def layer_of(fields: dict) -> dict:
    """A layer's fields as the kit draws them, by its kind: a text, a mark, or a piece."""
    kind = str(fields.get("kind") or "text")
    kind = kind if kind in KINDS else "text"
    layer = {
        "kind": kind,
        "x": min(max(seconds(fields.get("x"), TEXT_AT["x"]), 0.0), 100.0),
        "y": min(max(seconds(fields.get("y"), TEXT_AT["y"]), 0.0), 100.0),
        "hidden": bool(fields.get("hidden")),
        "order": _int(fields.get("order")),
        "colour": colour_from(fields.get("colour")) or TEXT_COLOUR,
    }
    if kind == "text":
        layer["text"] = str(fields.get("text") or "")
        layer["size"] = min(max(seconds(fields.get("size"), TEXT_SIZE), 0.5), 100.0)
    elif kind == "mark":
        layer["points"] = points_of(fields.get("points"))
        layer["width"] = min(max(seconds(fields.get("width"), MARK_WIDTH), 0.1), 25.0)
        layer["opacity"] = min(max(seconds(fields.get("opacity"), MARK_OPACITY), 0.05), 1.0)
    else:
        layer["source"] = _box(fields.get("source"), {"x": 0, "y": 0, "w": 25, "h": 25})
        layer["w"] = min(max(seconds(fields.get("w"), layer["source"]["w"]), 0.5), 100.0)
        layer["h"] = min(max(seconds(fields.get("h"), layer["source"]["h"]), 0.5), 100.0)
    return layer


def layers_in_order(records: list[dict]) -> list[dict]:
    """Records of elements, lowest first: by `order`, then by when they were made."""
    return sorted(
        records,
        key=lambda r: (
            _int((r.get("fields") or {}).get("order")),
            str(r.get("created_at") or ""),
            str(r.get("id") or ""),
        ),
    )


# -- the layers: groups the elements are on ---------------------------------------
# An edit's `layers` is a list, the lowest first: `[{"id": "1", "name": "Layer 1",
# "hidden": false}, …]`. Every element names its layer by id (`layer`); one that
# names none, or one that is gone, is on the first. An edit that says nothing has
# one layer.
FIRST_LAYER = {"id": "1", "name": "Layer 1", "hidden": False}


def groups_of(fields: dict) -> list[dict]:
    """The edit's layers, lowest first; at least one."""
    out: list[dict] = []
    seen: set[str] = set()
    for i, item in enumerate(fields.get("layers") if isinstance(fields.get("layers"), list) else []):
        if not isinstance(item, dict):
            continue
        ident = str(item.get("id") or i + 1)
        if ident in seen:
            continue
        seen.add(ident)
        out.append(
            {"id": ident, "name": str(item.get("name") or f"Layer {len(out) + 1}"), "hidden": bool(item.get("hidden"))}
        )
    return out or [dict(FIRST_LAYER)]


def layer_of_element(fields: dict, groups: list[dict]) -> str:
    """Which layer an element is on: its `layer`, when that is one of the edit's; else the first."""
    said = str(fields.get("layer") or "")
    return said if any(g["id"] == said for g in groups) else groups[0]["id"]


def elements_in_order(records: list[dict], groups: list[dict]) -> list[dict]:
    """Records of elements as they are drawn: by their layer, lowest first, then as `layers_in_order`."""
    place = {g["id"]: i for i, g in enumerate(groups)}
    return sorted(layers_in_order(records), key=lambda r: place[layer_of_element(r.get("fields") or {}, groups)])


def drawn(records: list[dict], groups: list[dict]) -> list[dict]:
    """The elements that are seen, in drawing order: not hidden, and on a layer that is not hidden."""
    hidden = {g["id"] for g in groups if g["hidden"]}
    return [
        r
        for r in elements_in_order(records, groups)
        if not (r.get("fields") or {}).get("hidden") and layer_of_element(r.get("fields") or {}, groups) not in hidden
    ]


def new_layer_id(groups: list[dict]) -> str:
    """An id no layer of the edit has."""
    taken = {g["id"] for g in groups}
    n = len(groups) + 1
    while str(n) in taken:
        n += 1
    return str(n)


def layer_said(fields: dict) -> str:
    """`'Hello' at 6 6, 6% tall, #ffffff`; `a #e0323c mark, 12 points, 1.5% wide`; `a piece 25 × 25 at 10 10`."""
    layer = layer_of(fields)
    hidden = ", hidden" if layer["hidden"] else ""
    if layer["kind"] == "text":
        words = layer["text"].replace("\n", " / ")
        return f"{words!r} at {layer['x']:g} {layer['y']:g}, {layer['size']:g}% tall, {layer['colour']}{hidden}"
    if layer["kind"] == "mark":
        return f"a {layer['colour']} mark, {len(layer['points'])} points, {layer['width']:g}% wide{hidden}"
    return f"a piece {layer['w']:g} × {layer['h']:g} at {layer['x']:g} {layer['y']:g}{hidden}"
