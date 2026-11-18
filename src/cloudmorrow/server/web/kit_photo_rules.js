/* The photo kit's arithmetic, the same sums as cloudmorrow/quill/photo.py:
   what an edit does to a picture, in order — turned by quarter turns,
   mirrored, words laid on it, cropped to a box, made another size — and
   what each of those is in numbers. Pure: nothing here draws or writes.
   The terminal and the command line do these sums in Python; a change to a
   rule there is a change here (docs/PHOTO.md). */

import { clamp, fitBox, wholeFrame } from "./kit_timeline_rules.js";

export { clamp, fitBox, wholeFrame };

// The most pixels an export is across or down.
export const LONGEST = 8192;
// Where words start on a picture, how tall, and in what colour.
export const TEXT_AT = { x: 6, y: 6 };
export const TEXT_SIZE = 6;
export const TEXT_COLOUR = "#ffffff";
// A few colours to pick from; the same names the command line takes.
export const COLOURS = [
  ["white", "#ffffff"], ["black", "#000000"], ["red", "#e0323c"], ["amber", "#f0a81e"], ["yellow", "#f5d90a"],
  ["green", "#3cb371"], ["sky", "#5aa6e0"], ["blue", "#1c70b1"], ["violet", "#8a5ce0"], ["rose", "#ff6b81"],
];
// The shapes a crop can be held to; "" is free.
export const RATIOS = [["", "Free"], ["1:1", "Square"], ["4:3", "4 : 3"], ["3:2", "3 : 2"], ["16:9", "16 : 9"], ["9:16", "Tall"]];
// The sizes an export is offered at; "" keeps the picture's own.
export const SIZES = [["", "As it is"], ["50%", "Half"], ["25%", "A quarter"], ["1920", "1920 wide"], ["1280", "1280 wide"], ["800", "800 wide"]];
const PHOTO = ["jpg", "jpeg", "png", "gif", "webp", "bmp", "tif", "tiff", "heic", "heif", "avif"];

const num = (value, fallback = 0) => (value !== null && value !== "" && Number.isFinite(Number(value)) ? Number(value) : fallback);
const int = (value, fallback = 0) => Math.trunc(num(value, fallback));

/** Where the screen's pictures API answers: `/api/q/<quill>/<prefix>`, or "" without one. */
export function picturesPath(quill, screen) {
  const found = (quill.apis || []).find((a) => a.id === screen.pictures);
  if (!screen.pictures || !found) return "";
  const prefix = String(found.prefix || "").replace(/^\/+|\/+$/g, "");
  return `/api/q/${quill.id}/${prefix}`.replace(/\/+$/, "");
}

/** Whether a file is a photo, by its type or its name. */
export function isPhoto(name, mime = "") {
  if (/^image\//.test(String(mime))) return true;
  const ext = String(name).includes(".") ? String(name).split(".").pop().toLowerCase() : "";
  return PHOTO.includes(ext);
}

// -- turning ---------------------------------------------------------------------------
/** The edit's turn, clockwise: 0, 90, 180 or 270. */
export const rotationOf = (fields) => ((Math.round(int(fields.rotate) / 90) * 90) % 360 + 360) % 360;
export const mirrored = (fields) => !!fields.mirror;
/** A picture `rotate` degrees round: a quarter turn swaps the sides. */
export const turned = (w, h, rotate) => (rotate % 180 === 90 ? { w: h, h: w } : { w, h });

// -- sizes -----------------------------------------------------------------------------
/** The source's size in pixels, when the edit knows it. */
export function sourceSize(fields) {
  const w = int(fields.width);
  const h = int(fields.height);
  return w > 0 && h > 0 ? { w, h } : null;
}

/** The picture as it is worked on: the source, turned. */
export function pictureSize(fields) {
  const size = sourceSize(fields);
  return size ? turned(size.w, size.h, rotationOf(fields)) : null;
}

/** The part of the turned picture kept, never less than a twentieth each way. */
export function cropOf(value) {
  if (!value || typeof value !== "object") return { x: 0, y: 0, w: 100, h: 100 };
  return fitBox({ x: num(value.x), y: num(value.y), w: num(value.w, 100), h: num(value.h, 100) }, 5);
}

/** The picture after the turn and the crop, in pixels. */
export function croppedSize(fields) {
  const size = pictureSize(fields);
  if (!size) return null;
  const crop = cropOf(fields.crop);
  return { w: Math.max(1, Math.round(size.w * crop.w / 100)), h: Math.max(1, Math.round(size.h * crop.h / 100)) };
}

/** What the export is: the cropped size, or what out_width and out_height
    say — one keeps the shape, both are taken as typed. */
export function outputSize(fields) {
  const cropped = croppedSize(fields);
  const ww = Math.min(int(fields.out_width), LONGEST);
  const wh = Math.min(int(fields.out_height), LONGEST);
  if (ww > 0 && wh > 0) return { w: ww, h: wh };
  if (!cropped) return null;
  if (ww > 0) return { w: ww, h: Math.max(1, Math.round(cropped.h * ww / cropped.w)) };
  if (wh > 0) return { w: Math.max(1, Math.round(cropped.w * wh / cropped.h)), h: wh };
  return cropped;
}

/** A size as typed — `1920x1080`, `1920` (a width), `50%`, or nothing (as it
    is) — as the fields that say it; null when it is none of those. */
export function sizeFrom(text, cropped = null) {
  const said = String(text || "").trim().toLowerCase().replace("×", "x");
  if (!said || ["as is", "asis", "same", "none", "reset"].includes(said)) return { out_width: null, out_height: null };
  let m = said.match(/^(\d+)\s*(?:x|\*|by)\s*(\d+)$/);
  if (m) {
    const w = Number(m[1]);
    const h = Number(m[2]);
    return w > 0 && h > 0 && w <= LONGEST && h <= LONGEST ? { out_width: w, out_height: h } : null;
  }
  m = said.match(/^(\d+(?:\.\d+)?)\s*%$/);
  if (m) {
    if (!cropped) return null;
    const share = Number(m[1]) / 100;
    if (!(share > 0 && share <= 10)) return null;
    return { out_width: Math.max(1, Math.round(cropped.w * share)), out_height: Math.max(1, Math.round(cropped.h * share)) };
  }
  m = said.match(/^(\d+)(?:\s*(?:px|wide))?$/);
  if (m) {
    const w = Number(m[1]);
    return w > 0 && w <= LONGEST ? { out_width: w, out_height: null } : null;
  }
  return null;
}

/** The ratio `w:h` as a number, or 0 for free. */
export function ratioOf(text) {
  const m = String(text || "").match(/^(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)$/);
  return m && Number(m[2]) > 0 ? Number(m[1]) / Number(m[2]) : 0;
}

/** *box* (percent of a picture `size` pixels big) held to *ratio* (width over
    height): the height follows the width, unless `fromHeight`; what will not
    fit is shrunk, and the box is kept inside the picture. */
export function boxWithRatio(box, ratio, size, fromHeight = false) {
  if (!ratio || !size) return fitBox(box, 5);
  let w = box.w;
  let h = box.h;
  if (fromHeight) w = h * size.h / 100 * ratio / size.w * 100;
  else h = w * size.w / 100 / ratio / size.h * 100;
  if (w > 100) { w = 100; h = w * size.w / 100 / ratio / size.h * 100; }
  if (h > 100) { h = 100; w = h * size.h / 100 * ratio / size.w * 100; }
  return fitBox({ x: box.x, y: box.y, w, h }, 1);
}

// -- texts -----------------------------------------------------------------------------
/** A colour as `#rrggbb`, from `#rgb`, `#rrggbb` or one of the names; null otherwise. */
export function colourFrom(text) {
  const said = String(text || "").trim().toLowerCase();
  const named = COLOURS.find(([name]) => name === said);
  if (named) return named[1];
  let m = said.match(/^#?([0-9a-f]{3})$/);
  if (m) return "#" + [...m[1]].map((c) => c + c).join("");
  m = said.match(/^#?([0-9a-f]{6})$/);
  return m ? "#" + m[1] : null;
}

/** A text's fields as the kit draws them. */
export function textOf(fields) {
  return {
    text: String(fields.text || ""),
    x: clamp(num(fields.x, TEXT_AT.x), 0, 100),
    y: clamp(num(fields.y, TEXT_AT.y), 0, 100),
    size: clamp(num(fields.size, TEXT_SIZE), 0.5, 100),
    colour: colourFrom(fields.colour) || TEXT_COLOUR,
  };
}

/** The lines of a text, and how tall each is in pixels on a picture *height* tall. */
export function textLines(text, height) {
  const px = Math.max(1, text.size / 100 * height);
  return { lines: text.text.split("\n"), px, lineHeight: px * 1.2 };
}
