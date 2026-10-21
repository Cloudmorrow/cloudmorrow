/* The timeline's rules: what a cut is, as arithmetic, with nothing on the page.

   kit_timeline.js draws and plays; everything here is a pure function of
   records' fields — which piece is on top at a moment, where a blur's box
   is between two keyframes, what a split or a trim does to a piece and to
   its effects' keyframes — so the terminal's kit (quill/screens.py, which
   this mirrors) and the tests can hold it to the same answers. Times are
   seconds, boxes are percent of the frame, as docs/TIMELINE.md has them. */

// The kit's tracks when a project names none: two of each, top to bottom.
export const TRACKS = [
  { id: "V2", kind: "video", name: "Video 2" },
  { id: "V1", kind: "video", name: "Video 1" },
  { id: "A1", kind: "audio", name: "Audio 1" },
  { id: "A2", kind: "audio", name: "Audio 2" },
];

/** A project's tracks, top to bottom; the kit's four when it says none. */
export function tracksOf(fields) {
  const tracks = fields && fields.tracks;
  if (Array.isArray(tracks) && tracks.length && tracks.every((t) => t && typeof t === "object" && t.id)) {
    return tracks.map((t) => ({ kind: "video", name: t.id, ...t }));
  }
  return TRACKS.map((t) => ({ ...t }));
}

/** Where a Quill's frames API answers, or "" when the screen binds none. */
export function framesPath(quill, screen) {
  const found = (quill.apis || []).find((a) => a.id === screen.frames);
  if (!screen.frames || !found) return "";
  const prefix = String(found.prefix || "").replace(/^\/+|\/+$/g, "");
  return `/api/q/${quill.id}/${prefix}`.replace(/\/+$/, "");
}

// -- numbers -----------------------------------------------------------------------
export const clamp = (n, low, high) => Math.min(high, Math.max(low, n));
/** A time kept to the millisecond: what is written, so 0.1 + 0.2 is 0.3. */
export const ms = (t) => Math.round(Number(t) * 1000) / 1000;
const num = (value, fallback = 0) => (Number.isFinite(Number(value)) && value !== null && value !== "" ? Number(value) : fallback);

/** A piece's fields as numbers: start, offset, length, volume and muted. */
export function partsOf(fields) {
  return {
    start: num(fields.start),
    offset: num(fields.offset),
    length: Math.max(0, num(fields.length)),
    volume: clamp(num(fields.volume, 1), 0, 2),
    muted: !!fields.muted,
  };
}

/** "1:04.20" — minutes, seconds and hundredths; hours when there are any. */
export function clockOf(t) {
  const whole = Math.max(0, t);
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const s = whole % 60;
  const sec = s.toFixed(2).padStart(5, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

/** A length as it is said beside a file: "8.0 s", "2:05". */
export function lengthOf(t) {
  if (!Number.isFinite(t) || t <= 0) return "";
  if (t < 60) return `${t.toFixed(1)} s`;
  return `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
}

// -- what the material is -------------------------------------------------------------
const VIDEO = ["mp4", "m4v", "mov", "mkv", "webm", "avi", "ogv"];
const AUDIO = ["mp3", "m4a", "aac", "flac", "wav", "ogg", "oga", "opus", "weba"];

/** "video", "audio" or "": by the file's type, else by its name's ending. */
export function mediaKind(name, mime = "") {
  if (/^video\//.test(mime)) return "video";
  if (/^audio\//.test(mime)) return "audio";
  const ext = String(name).includes(".") ? String(name).split(".").pop().toLowerCase() : "";
  if (VIDEO.includes(ext)) return "video";
  if (AUDIO.includes(ext)) return "audio";
  return "";
}

/** The track a new piece of *kind* goes on: the one chosen when it can carry
    it (a video goes on any track, an audio track playing only its sound; a
    sound only on an audio track), else the first of its kind counted out
    from the middle — Video 1, the last video track listed, and Audio 1, the
    first audio one: the tracks nearest the line between the two (the
    terminal's quill/timeline.py `first_track`). */
export function trackFor(tracks, kind, chosen = "") {
  const picked = tracks.find((t) => t.id === chosen);
  if (picked && (kind === "video" || picked.kind === "audio")) return picked;
  const same = tracks.filter((t) => t.kind === kind);
  if (!same.length) return null;
  return kind === "video" ? same[same.length - 1] : same[0];
}

// -- what is on at a moment -------------------------------------------------------------
const covers = (p, t) => t >= p.start && t < p.start + p.length;

/** The piece whose picture is shown at *t*: on the highest video track that
    has one there; on one track, the one that starts last. Pieces are
    {id, track, start, length, …}; null in a gap. */
export function pictureAt(pieces, tracks, t) {
  for (const track of tracks) {
    if (track.kind !== "video") continue;
    const here = pieces.filter((p) => p.track === track.id && covers(p, t));
    if (here.length) return here.reduce((a, b) => (b.start >= a.start ? b : a));
  }
  return null;
}

/** Every piece heard at *t*: on a video or an audio track, not muted, not silent. */
export function soundsAt(pieces, tracks, t) {
  const kinds = new Map(tracks.map((tr) => [tr.id, tr.kind]));
  return pieces.filter((p) => kinds.has(p.track) && covers(p, t) && !p.muted && p.volume > 0);
}

/** Where the cut ends: the last piece's end. */
export const lengthOfCut = (pieces) => pieces.reduce((end, p) => Math.max(end, p.start + p.length), 0);

// -- keyframes --------------------------------------------------------------------------
/** Keyframes as numbers, sorted by t. */
export function keyframesOf(list) {
  return (Array.isArray(list) ? list : [])
    .filter((k) => k && Number.isFinite(Number(k.t)))
    .map((k) => ({ t: Number(k.t), x: num(k.x), y: num(k.y), w: num(k.w), h: num(k.h) }))
    .sort((a, b) => a.t - b.t);
}

/** Whether an effect is on at *t* (seconds from its piece's start): from its
    first keyframe to its last, or the whole piece with one. */
export function effectOn(keyframes, t) {
  if (!keyframes.length) return false;
  if (keyframes.length === 1) return true;
  return t >= keyframes[0].t - 1e-6 && t <= keyframes[keyframes.length - 1].t + 1e-6;
}

/** The box at *t*: a straight line between the two keyframes either side,
    the nearest one's before the first and after the last. */
export function boxAt(keyframes, t) {
  if (!keyframes.length) return null;
  const first = keyframes[0];
  const last = keyframes[keyframes.length - 1];
  const box = (k) => ({ x: k.x, y: k.y, w: k.w, h: k.h });
  if (t <= first.t) return box(first);
  if (t >= last.t) return box(last);
  for (let i = 1; i < keyframes.length; i += 1) {
    const b = keyframes[i];
    if (t > b.t) continue;
    const a = keyframes[i - 1];
    const f = b.t === a.t ? 0 : (t - a.t) / (b.t - a.t);
    return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f, w: a.w + (b.w - a.w) * f, h: a.h + (b.h - a.h) * f };
  }
  return box(last);
}

const rounded = (box) => ({
  x: Math.round(box.x * 100) / 100, y: Math.round(box.y * 100) / 100,
  w: Math.round(box.w * 100) / 100, h: Math.round(box.h * 100) / 100,
});

/** The keyframes with *box* at *t*: the one within half a frame changed,
    or a new one made — sorted, as they are stored. */
export function setKeyframe(keyframes, t, box, fps = 30) {
  const half = 0.5 / (fps || 30);
  const out = keyframes.filter((k) => Math.abs(k.t - t) > half);
  out.push({ t: ms(t), ...rounded(box) });
  return out.sort((a, b) => a.t - b.t);
}

/** The keyframes without the one at *t* (within half a frame). */
export const dropKeyframe = (keyframes, t, fps = 30) =>
  keyframes.filter((k) => Math.abs(k.t - t) > 0.5 / (fps || 30));

/** Every keyframe moved by *by* seconds: a trimmed start shifts nothing on screen. */
export const shiftKeyframes = (keyframes, by) => keyframes.map((k) => ({ ...k, t: ms(k.t + by) }));

/** A box kept inside the frame and no smaller than *least* percent. */
export function fitBox(box, least = 2) {
  const w = clamp(box.w, least, 100);
  const h = clamp(box.h, least, 100);
  return { x: clamp(box.x, 0, 100 - w), y: clamp(box.y, 0, 100 - h), w, h };
}

// -- cutting ------------------------------------------------------------------------------
/** The two pieces a split at *at* (timeline seconds) makes, or null when it
    is not inside the piece: the first keeps its start, the second starts
    where it was cut, further into the source by as much. */
export function splitPiece(piece, at, least = 1 / 30) {
  const cut = at - piece.start;
  if (cut < least || piece.length - cut < least) return null;
  return [
    { start: ms(piece.start), offset: ms(piece.offset), length: ms(cut) },
    { start: ms(at), offset: ms(piece.offset + cut), length: ms(piece.length - cut) },
  ];
}

/** An effect's keyframes either side of a cut *cut* seconds into its piece:
    [first half's, second half's], t counted from each half's start. One
    that runs across the cut gets a keyframe at it on both sides, where its
    box was, so nothing on screen moves; a half it is not on gets null. */
export function splitKeyframes(keyframes, cut) {
  if (!keyframes.length) return [null, null];
  if (keyframes.length === 1) return [keyframes.map((k) => ({ ...k })), [{ ...keyframes[0], t: 0 }]];
  const first = keyframes[0].t;
  const last = keyframes[keyframes.length - 1].t;
  const at = { t: 0, ...rounded(boxAt(keyframes, cut)) };
  let left = null;
  let right = null;
  if (first < cut) {
    left = keyframes.filter((k) => k.t < cut).map((k) => ({ ...k }));
    if (last > cut) left.push({ ...at, t: ms(cut) });
  }
  if (last > cut) {
    right = keyframes.filter((k) => k.t > cut).map((k) => ({ ...k, t: ms(k.t - cut) }));
    if (first < cut) right.unshift({ ...at, t: 0 });
  }
  // A keyframe exactly on the cut ends the first half and starts the second.
  const on = keyframes.find((k) => Math.abs(k.t - cut) < 1e-6);
  if (on && left && !left.some((k) => Math.abs(k.t - cut) < 1e-6)) left.push({ ...on, t: ms(cut) });
  if (on && right && !right.some((k) => k.t === 0)) right.unshift({ ...on, t: 0 });
  return [left, right];
}

/** A trim of the start to *start*: the piece begins later (or earlier) on the
    timeline and in the source alike, so its end stays put. Kept to what the
    source has before it and to *least* long. Answers the new parts and by
    how much every keyframe's t moves. */
export function trimStart(piece, start, least = 1 / 30) {
  const end = piece.start + piece.length;
  const begin = clamp(start, piece.start - piece.offset, end - least);
  const by = begin - piece.start;
  return { start: ms(begin), offset: ms(piece.offset + by), length: ms(end - begin), shift: ms(-by) };
}

/** A trim of the end to *end*: kept to *least* long, and to the source's
    *duration* when it is known. */
export function trimEnd(piece, end, duration = Infinity, least = 1 / 30) {
  const most = Number.isFinite(duration) && duration > 0 ? duration - piece.offset : Infinity;
  return { length: ms(clamp(end - piece.start, least, most)) };
}

/** *t* moved onto the nearest of *edges* within *reach* seconds; as it was otherwise. */
export function snapTo(t, edges, reach) {
  let best = t;
  let gap = reach;
  for (const edge of edges) {
    const d = Math.abs(edge - t);
    if (d < gap) { gap = d; best = edge; }
  }
  return best;
}

/** Where a piece of *length* dragged to *start* lands: its start or its end
    snapped, whichever is nearer an edge, and never before 0. */
export function snapMove(start, length, edges, reach) {
  const byStart = snapTo(start, edges, reach);
  const byEnd = snapTo(start + length, edges, reach) - length;
  const dStart = Math.abs(byStart - start);
  const dEnd = Math.abs(byEnd - start);
  let out = start;
  if (byStart !== start && (byEnd === start || dStart <= dEnd)) out = byStart;
  else if (byEnd !== start) out = byEnd;
  return Math.max(0, out);
}

// -- the crop -------------------------------------------------------------------------------
/** The project's crop, kept inside the frame; all of it when blank. */
export function cropOf(value) {
  if (!value || typeof value !== "object") return { x: 0, y: 0, w: 100, h: 100 };
  return fitBox({ x: num(value.x), y: num(value.y), w: num(value.w, 100), h: num(value.h, 100) }, 5);
}

export const wholeFrame = (crop) => crop.x === 0 && crop.y === 0 && crop.w === 100 && crop.h === 100;
