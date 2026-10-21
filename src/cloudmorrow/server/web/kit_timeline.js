/* The kit's `timeline`: a video editor, drawn from the screen's bindings alone.

   A timeline screen names three datamodels with the kit's own field names
   (docs/TIMELINE.md): the project (`model`), the pieces on its tracks
   (`pieces`) and, optionally, what is done to a piece over time
   (`effects`); where the material is (`media`, a filter on the drive's
   file records); and, optionally, a frames API and an export action.

     #/q/<quill>/<screen>          the projects, newest first, with New
     #/q/<quill>/<screen>/<id>     one project in the editor
     #/q/<quill>/<screen>/project=<id>   the same, as a Quill's `go` says it

   The editor is five things around one clock. The material, by folder,
   with Add. The viewer: a canvas the top piece's picture is drawn on each
   frame from a <video>, every blur drawn over it as a blurred copy of its
   box, and the crop either shown (as a box to move, outside it dimmed) or
   kept to. The tracks, a row each, with the pieces to scale, to choose,
   drag, trim, split, mute and delete. The selected piece's effects, with
   their keyframes. And the header's export, which says how it is going.

   Sound is every audible piece at the playhead, each through its own
   hidden element, kept within a sixth of a second of the clock. A <video>
   cannot send the app's token, so each file is played from a media link
   the server makes for it (`POST …/media`), kept per file and asked for
   again before its six hours are up.

   What changes is written as it changes, on the records API, and drawn
   before the answer comes; when the server says no, the project is read
   again and drawn as it is. The arithmetic — which piece is on top, where
   a box is between two keyframes, what a split or a trim does to the
   keyframes — is kit_timeline_rules.js, the same rules the terminal has. */

import {
  api, apiRaw, app, esc, formatDate, go, heading, icons, mount, nav, occupy, recordsUrl, replace,
  renderRoute, seconds, tabs, toast, vacate, wireShell,
} from "./core.js";
import { aOr, mayWrite, plural, sheetHash } from "./kit.js";
import { press, said } from "./actions.js";
import {
  boxAt, clamp, clockOf, cropOf, dropKeyframe, effectOn, fitBox, framesPath, keyframesOf, lengthOf,
  lengthOfCut, mediaKind, ms, partsOf, pictureAt, setKeyframe, shiftKeyframes, snapMove, snapTo,
  soundsAt, splitKeyframes, splitPiece, trackFor, tracksOf, trimEnd, trimStart, wholeFrame,
} from "./kit_timeline_rules.js";

const glyphs = {
  first: '<svg width="18" height="18" viewBox="0 0 18 18" fill="currentColor"><rect x="2" y="3" width="2.2" height="12" rx="1"/><path d="M15 3.8v10.4a.8.8 0 0 1-1.2.7L6 9.7a.8.8 0 0 1 0-1.4l7.8-5.2a.8.8 0 0 1 1.2.7z"/></svg>',
  back: '<svg width="18" height="18" viewBox="0 0 18 18" fill="currentColor"><rect x="12.5" y="3" width="2.2" height="12" rx="1"/><path d="M10.5 3.8v10.4a.8.8 0 0 1-1.2.7L3 9.7a.8.8 0 0 1 0-1.4l6.3-5.2a.8.8 0 0 1 1.2.7z"/></svg>',
  play: '<svg width="22" height="22" viewBox="0 0 22 22" fill="currentColor"><path d="M6 3.6v14.8a1 1 0 0 0 1.5.9l12-7.4a1 1 0 0 0 0-1.8l-12-7.4A1 1 0 0 0 6 3.6z"/></svg>',
  pause: '<svg width="22" height="22" viewBox="0 0 22 22" fill="currentColor"><rect x="5" y="3.5" width="4.2" height="15" rx="1.2"/><rect x="12.8" y="3.5" width="4.2" height="15" rx="1.2"/></svg>',
  on: '<svg width="18" height="18" viewBox="0 0 18 18" fill="currentColor"><rect x="3.3" y="3" width="2.2" height="12" rx="1"/><path d="M7.5 3.8v10.4a.8.8 0 0 0 1.2.7L15 9.7a.8.8 0 0 0 0-1.4L8.7 3.1a.8.8 0 0 0-1.2.7z"/></svg>',
  last: '<svg width="18" height="18" viewBox="0 0 18 18" fill="currentColor"><rect x="13.8" y="3" width="2.2" height="12" rx="1"/><path d="M3 3.8v10.4a.8.8 0 0 0 1.2.7L12 9.7a.8.8 0 0 0 0-1.4L4.2 3.1A.8.8 0 0 0 3 3.8z"/></svg>',
  crop: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M5 1.5V15h13.5M1.5 5H15v13.5"/></svg>',
  material: '<svg width="20" height="20" viewBox="0 0 22 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="1.5" y="3" width="13" height="14" rx="2"/><path d="m14.5 8 6-3v10l-6-3z"/></svg>',
  plus: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M9 3.5v11M3.5 9h11"/></svg>',
  minus: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M3.5 9h11"/></svg>',
  split: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 1.5v15"/><rect x="1.5" y="5" width="5" height="8" rx="1.2"/><rect x="11.5" y="5" width="5" height="8" rx="1.2"/></svg>',
  mute: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 7h3l4-3.5v11l-4-3.5h-3z"/><path d="m12.5 7 4 4M16.5 7l-4 4"/></svg>',
  sound: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 7h3l4-3.5v11l-4-3.5h-3z"/><path d="M12.5 6.5a3.5 3.5 0 0 1 0 5M14.5 4.5a6.5 6.5 0 0 1 0 9"/></svg>',
  video: '<svg width="20" height="18" viewBox="0 0 22 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="1.5" y="3" width="13" height="14" rx="2"/><path d="m14.5 8 6-3v10l-6-3z"/></svg>',
  audio: '<svg width="18" height="20" viewBox="0 0 20 22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7 16.5V5l10-2v11.5"/><circle cx="4.5" cy="16.5" r="2.5"/><circle cx="14.5" cy="14.5" r="2.5"/></svg>',
  close: '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m2.5 2.5 7 7M9.5 2.5l-7 7"/></svg>',
  more: '<svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
};

// How a project's status is toned beside Export; anything else is said plainly.
const TONES = { queued: "info", rendering: "info", done: "good", failed: "bad" };
const BUSY = new Set(["queued", "rendering"]);
const POLL = 3000;               // how often a project being exported is asked about
const LINK_SPARE = 20 * 60e3;    // a media link is asked for again this long before it runs out
const DRIFT = 0.15;              // how far a sound may stray from the clock before it is put back
const SETTLE = 400;              // and how long it is given to start before it is checked again
const FRAME = { width: 1280, height: 720 };   // the picture's size until a piece gives it one
const WIDEST = 1600;             // the most pixels across the viewer draws

// -- the screen's bindings ---------------------------------------------------------------
const linkTo = (model, to) => {
  const links = (model ? model.fields : []).filter((f) => f.kind === "link" && f.to === to);
  return links.length === 1 ? links[0].name : "";
};

/** What a timeline is drawn from, read out of its bindings once. */
export function bindingsOf(at) {
  const { quill, screen } = at;
  const model = quill.models[screen.model];
  const pieces = quill.models[screen.pieces];
  const effects = screen.effects ? quill.models[screen.effects] || null : null;
  // The material is the drive's files: the kit's word is `file`, as the spec's `source` is.
  const files = quill.models.file || null;
  return {
    model,
    title: screen.title || model.title,
    has: new Set(model.fields.map((f) => f.name)),
    pieces,
    effects,
    files,
    pieceProject: linkTo(pieces, model.id),
    effectPiece: effects ? linkTo(effects, pieces.id) : "",
    media: screen.media || {},
    frames: framesPath(quill, screen),
    exportAction: screen.export ? (quill.actions || []).find((a) => a.id === screen.export) || null : null,
  };
}

/** What the record sheet does for a project: back to its editor, not to the list. */
export function timelineSheet(at, model) {
  if (model.id !== at.screen.model) return null;
  return { parent: (record) => `${at.base}/${encodeURIComponent(record.id)}` };
}

// -- records as the editor holds them -------------------------------------------------
const pieceOf = (record) => ({
  id: record.id,
  record,
  track: String(record.fields.track || ""),
  source: String(record.fields.source || ""),
  name: String(record.fields.name || ""),
  ...partsOf(record.fields),
});

const effectOf = (b, record) => ({
  id: record.id,
  record,
  piece: String(record.fields[b.effectPiece] || ""),
  kind: String(record.fields.kind || ""),
  label: String(record.fields.label || ""),
  strength: clamp(Number(record.fields.strength) || 20, 1, 100),
  keyframes: keyframesOf(record.fields.keyframes),
});

// -- the screen ----------------------------------------------------------------------------
let live = null;   // the editor on the page, while there is one

export async function renderTimeline(at, arg) {
  const b = bindingsOf(at);
  // A Quill's `go("editor", project=<id>)` arrives as parameters: the editor
  // of that project, at its own address.
  if (arg && arg.includes("=")) {
    const project = new URLSearchParams(arg).get("project");
    replace(project ? `${at.base}/${encodeURIComponent(project)}` : at.base);
    arg = project || "";
  }
  if (!arg) return renderProjects(at, b);
  return renderEditorFor(at, b, arg);
}

// -- the projects -----------------------------------------------------------------------------
async function renderProjects(at, b) {
  const { screen } = at;
  const records = await api("GET", recordsUrl(b.model.id));
  records.sort((x, y) => String(y.created_at || "").localeCompare(String(x.created_at || "")));
  const writes = mayWrite(b.model);
  const row = (r) => {
    const f = r.fields;
    const status = b.has.has("status") && f.status && f.status !== "editing" ? String(f.status) : "";
    const line = [status && status[0].toUpperCase() + status.slice(1), f.message].filter(Boolean).join(" · ");
    const changed = seconds(r.updated_at || r.created_at);
    return `<a class="row tl-project" href="${at.base}/${encodeURIComponent(r.id)}">
      <span class="icon">${glyphs.video}</span>
      <span class="main"><span class="title">${esc(String(f[b.title] || "").trim() || "Untitled")}</span>
        <span class="meta">${changed ? `<span class="date">${esc(formatDate(changed))}</span>` : ""}${
          line ? `<span class="preview">${esc(line)}</span>` : ""}</span></span>${icons.chevronRight}</a>`;
  };
  const label = b.model.label.toLowerCase();
  mount(nav({ title: screen.label }) + `
    <main class="kit-timeline-list">
      ${heading(screen.label, writes ? `<button class="compose" aria-label="New ${esc(label)}">${icons.compose}</button>` : "")}
      ${writes ? `<form class="add kit-add"><input placeholder="New ${esc(label)} — its name" autocapitalize="sentences" enterkeyhint="go"></form>` : ""}
      <div class="listing">${records.length
        ? `<div class="group">${records.map(row).join("")}</div>`
        : `<p class="empty"><b>No ${esc(plural(label))} yet</b>${writes ? `Name ${aOr(b.model.label)} above to start cutting.` : ""}</p>`}</div>
    </main>` + tabs(at.tab));
  wireShell();
  const form = app.querySelector("form.kit-add");
  if (!form) return;
  const input = form.querySelector("input");
  app.querySelector(".heading .compose").addEventListener("click", () => input.focus());
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = input.value.trim() || `${b.model.label} ${new Date().toLocaleDateString()}`;
    input.disabled = true;
    try {
      const made = await api("POST", recordsUrl(b.model.id), { fields: { [b.title]: name } });
      go(`${at.base}/${encodeURIComponent(made.id)}`);
    } catch (err) {
      input.disabled = false;
      toast(said(err));
    }
  });
}

// -- the editor --------------------------------------------------------------------------------
async function loadProject(b, id) {
  const [project, pieces, effects] = await Promise.all([
    api("GET", recordsUrl(b.model.id, id)),
    api("GET", recordsUrl(b.pieces.id) + `?${encodeURIComponent(b.pieceProject)}=${encodeURIComponent(id)}`),
    b.effects ? api("GET", recordsUrl(b.effects.id)) : Promise.resolve([]),
  ]);
  const ours = new Set(pieces.map((p) => p.id));
  return {
    project,
    pieces: pieces.map(pieceOf),
    effects: effects.map((e) => effectOf(b, e)).filter((e) => ours.has(e.piece)),
  };
}

async function renderEditorFor(at, b, id) {
  let loaded;
  try {
    loaded = await loadProject(b, id);
  } catch (err) {
    if (err.status !== 404) throw err;
    toast(`That ${b.model.label.toLowerCase()} is gone`);
    replace(at.base);
    return renderRoute();
  }
  const ed = {
    at, b, id,
    ...loaded,
    tracks: tracksOf(loaded.project.fields),
    files: new Map(),            // the material: file id → {id, name, folder, kind, modified}
    info: new Map(),             // what is known of a source: file id → {duration, width, height}
    links: new Map(),            // media links: file id → {url, expires, asking}
    pictures: new Map(),         // a muted <video> per file, for the picture
    sounds: new Map(),           // an element per piece, for its sound
    thumbs: new Map(),           // with a frames API: a picture per piece's first frame
    t: 0, playing: false, from: 0, since: 0,
    zoom: 0,                     // pixels a second on the tracks; 0 until they are measured
    selected: "", effect: "", cropping: false, target: "",
    dirty: true, alive: true, writing: Promise.resolve(),
    writes: mayWrite(b.pieces),
    writesEffects: !!b.effects && mayWrite(b.effects),
    writesProject: mayWrite(b.model),
  };
  if (live) live.stop();
  live = ed;
  ed.stop = () => stopEditor(ed);
  const hold = { stays: () => false, leave: async () => { ed.stop(); vacate(hold); }, flush: () => {} };
  occupy(hold);

  const title = String(ed.project.fields[b.title] || "").trim() || "Untitled";
  mount(nav({ back: at.base, backLabel: at.screen.label, title }) + `
    <main class="kit-timeline">
      ${heading(title, `<span class="tl-head-actions"></span><a class="button" href="${sheetHash(at, b.model.id, id)}" aria-label="${esc(b.model.label)}">${glyphs.more}</a>`)}
      <div class="tl-headbar" role="status"></div>
      <div class="tl-desk">
        <section class="tl-material" aria-label="Material"></section>
        <section class="tl-viewer">
          <div class="tl-stage-box"><div class="tl-stage">
            <canvas aria-label="The cut at the playhead"></canvas><div class="tl-over"></div>
          </div></div>
          <div class="tl-transport">
            <button type="button" class="tl-material-open" aria-label="Material">${glyphs.material}</button>
            <button type="button" data-go="first" aria-label="To the start">${glyphs.first}</button>
            <button type="button" data-go="back" aria-label="A frame back">${glyphs.back}</button>
            <button type="button" class="tl-play" aria-label="Play">${glyphs.play}</button>
            <button type="button" data-go="on" aria-label="A frame on">${glyphs.on}</button>
            <button type="button" data-go="last" aria-label="To the end">${glyphs.last}</button>
            <span class="tl-time"><b>0:00.00</b> / 0:00.00</span>
            <button type="button" class="tl-crop-toggle" aria-pressed="false" aria-label="Crop">${glyphs.crop}<span>Crop</span></button>
          </div>
        </section>
        <section class="tl-side" aria-label="The selected piece"></section>
      </div>
      <section class="tl-tracks" aria-label="Tracks">
        <div class="tl-tools">
          <button type="button" data-zoom="-1" aria-label="Zoom out">${glyphs.minus}</button>
          <button type="button" data-zoom="1" aria-label="Zoom in">${glyphs.plus}</button>
          <span class="tl-tools-gap"></span>
          <button type="button" class="tl-split" disabled>${glyphs.split}<span>Split</span></button>
          <button type="button" class="tl-delete" disabled>${icons.trash}<span>Delete</span></button>
        </div>
        <div class="tl-body">
          <div class="tl-heads"></div>
          <div class="tl-lanes"><div class="tl-inner"></div></div>
        </div>
      </section>
      <div class="tl-media" aria-hidden="true"></div>
    </main>` + tabs(at.tab));
  wireShell();

  ed.root = app.querySelector("main.kit-timeline");
  ed.canvas = ed.root.querySelector("canvas");
  ed.ctx = ed.canvas.getContext("2d");
  ed.stage = ed.root.querySelector(".tl-stage");
  ed.over = ed.root.querySelector(".tl-over");
  ed.lanes = ed.root.querySelector(".tl-lanes");
  ed.inner = ed.root.querySelector(".tl-inner");
  ed.timeEl = ed.root.querySelector(".tl-time");

  drawHeader(ed);
  drawTracks(ed);
  drawSide(ed);
  wireTransport(ed);
  wireTracks(ed);
  wireOverlay(ed);
  wireKeys(ed);
  fitStage(ed);
  ed.resize = new ResizeObserver(() => { fitStage(ed); placeOverlay(ed); });
  ed.resize.observe(ed.root.querySelector(".tl-stage-box"));
  // A link that is about to run out is asked for again before it does.
  ed.linkTimer = setInterval(() => { for (const id of ed.links.keys()) linkFor(ed, id); }, 60e3);
  for (const p of ed.pieces) prepare(ed, p);
  ed.raf = requestAnimationFrame(() => tick(ed));
  watchExport(ed);
  loadMaterial(ed);
  fillBlanks(ed);
}

/** A piece a Quill made without a length (it could not read the source) gets
    its source's, read the way Add reads it; and the project its size. */
async function fillBlanks(ed) {
  const blank = ed.pieces.filter((p) => !(p.length > 0) && p.source);
  if (!blank.length || !ed.writes) return;
  for (const piece of blank) {
    const info = await lengthFor(ed, { id: piece.source, name: piece.name, kind: "video" });
    if (!ed.alive || !info || !(info.duration > 0)) continue;
    know(ed, piece.source, info);
    const length = ms(Math.max(0, info.duration - piece.offset));
    await write(ed, async () => {
      await patch(ed.b.pieces.id, piece.id, { length });
      piece.length = length;
      const f = ed.project.fields;
      if (info.width && info.height && !(Number(f.width) > 0 && Number(f.height) > 0)) {
        const size = { width: info.width, height: info.height };
        if (!(Number(f.fps) > 0)) size.fps = info.fps || 30;
        Object.assign(f, size);
        await patch(ed.b.model.id, ed.id, size);
      }
    });
  }
  fitZoom(ed);
  fitStage(ed);
  drawTracks(ed);
  drawSide(ed);
  showTime(ed, ed.t);
  ed.dirty = true;
}

function stopEditor(ed) {
  if (!ed.alive) return;
  ed.alive = false;
  cancelAnimationFrame(ed.raf);
  clearInterval(ed.linkTimer);
  clearTimeout(ed.pollTimer);
  if (ed.resize) ed.resize.disconnect();
  if (ed.onKey) removeEventListener("keydown", ed.onKey);
  for (const el of [...ed.pictures.values(), ...ed.sounds.values()]) {
    el.pause();
    el.removeAttribute("src");
    el.load();
  }
  if (ed.audio) ed.audio.close().catch(() => {});
  for (const url of ed.thumbs.values()) if (url) URL.revokeObjectURL(url);
  closeMaterialSheet();
  if (live === ed) live = null;
}

// -- what is where ------------------------------------------------------------------------------
const pieceById = (ed, id) => ed.pieces.find((p) => p.id === id) || null;
const effectsOn = (ed, piece) => ed.effects.filter((e) => e.piece === piece.id);
const trackById = (ed, id) => ed.tracks.find((t) => t.id === id) || null;
const fps = (ed) => Number(ed.project.fields.fps) || 30;
const total = (ed) => lengthOfCut(ed.pieces);
const frameSize = (ed) => {
  const w = Number(ed.project.fields.width);
  const h = Number(ed.project.fields.height);
  return w > 0 && h > 0 ? { width: w, height: h } : FRAME;
};
const crop = (ed) => cropOf(ed.project.fields.crop);
/** The part of the frame the viewer shows: all of it while cropping, else the crop. */
const viewOf = (ed) => (ed.cropping ? { x: 0, y: 0, w: 100, h: 100 } : crop(ed));
/** Whether a source is a sound only: by the material's type, else by its name. */
const soundOnly = (ed, piece) => {
  const file = ed.files.get(piece.source);
  return (file ? file.kind : mediaKind(piece.name)) === "audio";
};
const now = (ed) => (ed.playing ? ed.from + (performance.now() - ed.since) / 1000 : ed.t);

// -- writing ----------------------------------------------------------------------------------------
/** One write after another, in the order they were made; a refusal is said,
    and the project read again, so what is drawn is what is stored. */
function write(ed, work) {
  ed.writing = ed.writing.then(work).catch(async (err) => {
    if (!ed.alive) return;
    toast(said(err));
    await reload(ed);
  });
  return ed.writing;
}

const patch = (model, id, fields) => api("PATCH", recordsUrl(model, id), { fields });

async function reload(ed) {
  try {
    Object.assign(ed, await loadProject(ed.b, ed.id));
  } catch (err) {
    toast(said(err));
    return;
  }
  ed.tracks = tracksOf(ed.project.fields);
  if (!pieceById(ed, ed.selected)) ed.selected = "";
  if (!ed.effects.some((e) => e.id === ed.effect)) ed.effect = "";
  for (const [id, el] of ed.sounds) {
    if (!pieceById(ed, id)) { el.pause(); ed.sounds.delete(id); }
  }
  for (const p of ed.pieces) prepare(ed, p);
  ed.dirty = true;
  drawHeader(ed);
  drawTracks(ed);
  drawSide(ed);
  fitStage(ed);
}

// -- media links and elements ---------------------------------------------------------------------
/** The file's media link, when there is a good one; asks for one (again) when
    there is not, or when it runs out within LINK_SPARE. */
function linkFor(ed, fileId) {
  const link = ed.links.get(fileId) || { url: "", expires: 0, asking: false };
  ed.links.set(fileId, link);
  const left = link.expires - Date.now();
  if (left < LINK_SPARE && !link.asking && ed.alive) {
    link.asking = true;
    api("POST", recordsUrl("file", fileId, "/media")).then((made) => {
      link.url = made.url;
      link.expires = Date.parse(made.expires) || Date.now() + 6 * 3600e3;
      ed.dirty = true;
    }).catch((err) => {
      // Asked again a minute later, by the timer; said once.
      if (!link.said) toast(said(err));
      link.said = true;
    }).finally(() => { link.asking = false; });
  }
  return left > 0 ? link.url : "";
}

/** Point *el* at the file's current link; false while there is none yet. */
function fed(ed, el, fileId) {
  const url = linkFor(ed, fileId);
  if (!url) return false;
  if (el.dataset.url !== url) {
    // A fresh link for the same bytes: where it was is where it goes on.
    const at = el.currentTime;
    el.dataset.url = url;
    el.src = url;
    if (at) el.currentTime = at;
    el.wanted = null;
  }
  return true;
}

function pictureOf(ed, fileId) {
  let el = ed.pictures.get(fileId);
  if (el) return el;
  el = document.createElement("video");
  el.muted = true;
  el.playsInline = true;
  el.preload = "auto";
  el.setAttribute("playsinline", "");
  const fresh = () => { ed.dirty = true; };
  el.addEventListener("loadeddata", fresh);
  el.addEventListener("seeked", fresh);
  el.addEventListener("loadedmetadata", () => {
    know(ed, fileId, { duration: el.duration, width: el.videoWidth, height: el.videoHeight });
    ed.dirty = true;
  });
  ed.root.querySelector(".tl-media").append(el);
  ed.pictures.set(fileId, el);
  return el;
}

function soundOf(ed, piece) {
  let el = ed.sounds.get(piece.id);
  if (el) return el;
  el = document.createElement("audio");
  el.preload = "auto";
  el.settled = 0;
  ed.root.querySelector(".tl-media").append(el);
  ed.sounds.set(piece.id, el);
  return el;
}

/** What a source is: its length and size, as the media element or the frames API said. */
function know(ed, fileId, info) {
  if (!Number.isFinite(info.duration) || info.duration <= 0) return;
  const had = ed.info.get(fileId) || {};
  ed.info.set(fileId, { ...had, ...info });
  known.set(fileId, { ...had, ...info });
}

/** Get a piece's elements going, so its first frame is there before it is played. */
function prepare(ed, piece) {
  if (!soundOnly(ed, piece)) {
    const el = pictureOf(ed, piece.source);
    fed(ed, el, piece.source);
  }
  fed(ed, soundOf(ed, piece), piece.source);
  if (ed.b.frames && !ed.thumbs.has(piece.id)) thumbFor(ed, piece);
}

// With a frames API, a piece shows its first frame on the tracks.
async function thumbFor(ed, piece) {
  ed.thumbs.set(piece.id, "");
  try {
    const res = await apiRaw("GET", `${ed.b.frames}/source?file=${encodeURIComponent(piece.source)}&t=${piece.offset}&w=160`);
    const url = URL.createObjectURL(await res.blob());
    if (!ed.alive) { URL.revokeObjectURL(url); return; }
    ed.thumbs.set(piece.id, url);
    const el = ed.inner.querySelector(`.tl-piece[data-id="${CSS.escape(piece.id)}"]`);
    if (el) el.style.backgroundImage = `url("${url}")`;
  } catch { /* the piece is drawn without one */ }
}

// -- the clock and the picture --------------------------------------------------------------------
function play(ed) {
  if (ed.playing) return;
  const end = total(ed);
  if (!end) return;
  if (ed.t >= end - 1e-3) ed.t = 0;
  // Made in the tap that asked for it, as a phone wants: the sound of each
  // piece goes through a gain, so a volume up to twice what was recorded.
  if (!ed.audio) {
    try { ed.audio = new (window.AudioContext || window.webkitAudioContext)(); } catch { ed.audio = null; }
  }
  if (ed.audio && ed.audio.state === "suspended") ed.audio.resume().catch(() => {});
  ed.playing = true;
  ed.from = ed.t;
  ed.since = performance.now();
  drive(ed, ed.t);
  drawPlay(ed);
}

function pause(ed) {
  if (!ed.playing) return;
  ed.t = Math.min(now(ed), total(ed));
  ed.playing = false;
  for (const el of [...ed.pictures.values(), ...ed.sounds.values()]) el.pause();
  ed.dirty = true;
  drawPlay(ed);
  placeOverlay(ed);
  drawTools(ed);
  drawSide(ed);
}

function seek(ed, t) {
  ed.t = clamp(t, 0, Math.max(total(ed), 0));
  if (ed.playing) { ed.from = ed.t; ed.since = performance.now(); }
  ed.dirty = true;
  showTime(ed, ed.t);
  placeOverlay(ed);
  drawTools(ed);
  if (!ed.playing) drawSide(ed);
}

const drawPlay = (ed) => {
  const button = ed.root.querySelector(".tl-play");
  button.innerHTML = ed.playing ? glyphs.pause : glyphs.play;
  button.setAttribute("aria-label", ed.playing ? "Pause" : "Play");
};

function tick(ed) {
  if (!ed.alive) return;
  ed.raf = requestAnimationFrame(() => tick(ed));
  let t = now(ed);
  const end = total(ed);
  if (ed.playing && t >= end) {
    t = end;
    pause(ed);
  }
  const shown = drive(ed, t);
  if (ed.playing) {
    ed.t = t;
    showTime(ed, t);
    followPlayhead(ed, t);
    if (ed.drag && ed.drag.box) ed.drag.box(ed.drag.last);
    placeOverlay(ed);
  }
  if (ed.playing || ed.dirty) {
    ed.dirty = false;
    paint(ed, shown, t);
  }
}

/** Put every element where the clock says: the picture's <video> at its
    frame, each audible piece's sound at its moment, the rest stopped.
    Answers the piece whose picture is shown, and its element. */
function drive(ed, t) {
  const pictures = ed.pieces.filter((p) => !soundOnly(ed, p));
  const top = pictureAt(pictures, ed.tracks, t);
  let shown = null;
  for (const [fileId, el] of ed.pictures) {
    if (top && fileId === top.source) continue;
    if (!el.paused) el.pause();
  }
  if (top) {
    const el = pictureOf(ed, top.source);
    shown = { piece: top, el };
    if (fed(ed, el, top.source)) {
      const want = top.offset + (t - top.start);
      if (ed.playing) {
        // Waiting for the picture holds the clock rather than running ahead of it.
        if (el.seeking || el.readyState < 3) { ed.from = t; ed.since = performance.now(); }
        if (Math.abs(el.currentTime - want) > 0.3 && !el.seeking) el.currentTime = want;
        if (el.paused) el.play().catch(() => {});
      } else {
        if (!el.paused) el.pause();
        if (el.wanted !== want) { el.wanted = want; el.currentTime = want; }
      }
    }
    // The next piece's picture, seeked ahead, so the cut to it is a cut.
    if (ed.playing) {
      const next = pictureAt(pictures, ed.tracks, t + 0.6);
      if (next && next.source !== top.source) {
        const other = pictureOf(ed, next.source);
        const at = next.offset + Math.max(0, t + 0.6 - next.start);
        if (fed(ed, other, next.source) && other.paused && !other.seeking && Math.abs(other.currentTime - at) > 0.3) other.currentTime = at;
      }
    }
  }
  const heard = ed.playing ? new Set(soundsAt(ed.pieces, ed.tracks, t).map((p) => p.id)) : new Set();
  for (const piece of ed.pieces) {
    const el = ed.sounds.get(piece.id);
    if (!heard.has(piece.id)) {
      if (el && !el.paused) el.pause();
      continue;
    }
    const sound = soundOf(ed, piece);
    if (!fed(ed, sound, piece.source)) continue;
    loudness(ed, sound, piece.volume);
    const want = piece.offset + (t - piece.start);
    if (sound.paused) {
      sound.currentTime = want;
      sound.settled = performance.now() + SETTLE;
      sound.play().catch(() => {});
    } else if (performance.now() > sound.settled && Math.abs(sound.currentTime - want) > DRIFT) {
      sound.currentTime = want;
      sound.settled = performance.now() + SETTLE;
    }
  }
  return shown;
}

/** A piece's volume: through a gain when the page has one (up to twice as
    loud as recorded), else the element's own, which stops at as recorded. */
function loudness(ed, el, volume) {
  if (ed.audio && !el.gain && !el.ungained) {
    try {
      const source = ed.audio.createMediaElementSource(el);
      el.gain = ed.audio.createGain();
      source.connect(el.gain).connect(ed.audio.destination);
    } catch {
      el.ungained = true;
    }
  }
  if (el.gain) el.gain.gain.value = volume;
  else el.volume = clamp(volume, 0, 1);
}

// -- the viewer --------------------------------------------------------------------------------------
/** Size the stage to the picture it shows, as large as the viewer has room for. */
function fitStage(ed) {
  if (!ed.alive) return;
  const box = ed.root.querySelector(".tl-stage-box");
  const frame = frameSize(ed);
  const view = viewOf(ed);
  const ratio = (frame.width * view.w) / (frame.height * view.h);
  const room = box.clientWidth;
  const tall = matchMedia("(min-width: 900px) and (min-height: 600px)").matches
    ? Math.min(innerHeight * 0.42, 560) : Math.min(innerHeight * 0.36, 360);
  const width = Math.max(1, Math.min(room, tall * ratio));
  ed.stage.style.width = `${Math.round(width)}px`;
  ed.stage.style.height = `${Math.round(width / ratio)}px`;
  const across = Math.min(WIDEST, Math.round(width * (devicePixelRatio || 1)), Math.round(frame.width * view.w / 100) || 1);
  const canvasW = Math.max(16, across);
  const canvasH = Math.max(9, Math.round(canvasW / ratio));
  if (ed.canvas.width !== canvasW || ed.canvas.height !== canvasH) {
    ed.canvas.width = canvasW;
    ed.canvas.height = canvasH;
  }
  ed.dirty = true;
}

/** One frame of the cut: the picture, its blurs, and the crop kept to. */
function paint(ed, shown, t) {
  const { ctx, canvas } = ed;
  const frame = frameSize(ed);
  const view = viewOf(ed);
  // Canvas pixels per frame pixel, and where the view starts in the frame.
  const s = canvas.width / (frame.width * view.w / 100);
  const ox = frame.width * view.x / 100;
  const oy = frame.height * view.y / 100;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.filter = "none";
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  if (!shown || shown.el.readyState < 2) return;
  const { el, piece } = shown;
  // The source fitted inside the frame, as the export puts it.
  const sw = el.videoWidth || frame.width;
  const sh = el.videoHeight || frame.height;
  const fit = Math.min(frame.width / sw, frame.height / sh);
  const dw = sw * fit;
  const dh = sh * fit;
  ctx.setTransform(s, 0, 0, s, -ox * s, -oy * s);
  ctx.drawImage(el, (frame.width - dw) / 2, (frame.height - dh) / 2, dw, dh);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  for (const effect of effectsOn(ed, piece)) {
    if (effect.kind !== "blur" || !effectOn(effect.keyframes, t - piece.start)) continue;
    const box = boxAt(effect.keyframes, t - piece.start);
    const x = (box.x / 100 * frame.width - ox) * s;
    const y = (box.y / 100 * frame.height - oy) * s;
    const w = box.w / 100 * frame.width * s;
    const h = box.h / 100 * frame.height * s;
    const radius = Math.max(2, effect.strength / 100 * 0.15 * Math.min(frame.width, frame.height) * s);
    blur(ctx, x, y, w, h, radius);
  }
}

// Whether the canvas can blur by itself; where it cannot, a box is made
// small and drawn back large, which smudges it as much.
const FILTERS = typeof CanvasRenderingContext2D !== "undefined" && "filter" in CanvasRenderingContext2D.prototype;
let scratch = null;

/** A blurred copy of what is in the box, over it, and nothing outside it. */
function blur(ctx, x, y, w, h, radius) {
  const { canvas } = ctx;
  const pad = radius * 2;
  const mx = Math.max(0, Math.floor(x - pad));
  const my = Math.max(0, Math.floor(y - pad));
  const mw = Math.min(canvas.width, Math.ceil(x + w + pad)) - mx;
  const mh = Math.min(canvas.height, Math.ceil(y + h + pad)) - my;
  if (mw <= 0 || mh <= 0) return;
  ctx.save();
  ctx.beginPath();
  ctx.rect(x, y, w, h);
  ctx.clip();
  if (FILTERS) {
    ctx.filter = `blur(${radius.toFixed(1)}px)`;
    ctx.drawImage(canvas, mx, my, mw, mh, mx, my, mw, mh);
  } else {
    scratch = scratch || document.createElement("canvas");
    const k = Math.max(2, radius / 2);
    scratch.width = Math.max(1, Math.round(mw / k));
    scratch.height = Math.max(1, Math.round(mh / k));
    const small = scratch.getContext("2d");
    small.drawImage(canvas, mx, my, mw, mh, 0, 0, scratch.width, scratch.height);
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(scratch, 0, 0, scratch.width, scratch.height, mx, my, mw, mh);
  }
  ctx.restore();
}

function showTime(ed, t) {
  const text = `<b>${clockOf(t)}</b> / ${clockOf(total(ed))}`;
  if (ed.timeText !== text) { ed.timeText = text; ed.timeEl.innerHTML = text; }
  const head = ed.inner.querySelector(".tl-playhead");
  if (head) head.style.transform = `translateX(${t * ed.zoom}px)`;
}

// -- the box on the viewer: a blur's, or the crop --------------------------------------------------
/** The box drawn over the picture, if any: the crop while cropping, else the
    chosen blur of the chosen piece while the playhead is on that piece. */
function overlayBox(ed) {
  if (ed.cropping) return { what: "crop", box: crop(ed) };
  const piece = pieceById(ed, ed.selected);
  const effect = ed.effects.find((e) => e.id === ed.effect && e.kind === "blur");
  if (!piece || !effect || !effect.keyframes.length) return null;
  const t = now(ed);
  if (t < piece.start || t >= piece.start + piece.length) return null;
  const local = t - piece.start;
  return { what: "blur", box: boxAt(effect.keyframes, local), on: effectOn(effect.keyframes, local), effect, piece };
}

const HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

function placeOverlay(ed) {
  if (!ed.alive) return;
  const shown = overlayBox(ed);
  if (!shown) {
    if (ed.over.firstChild) ed.over.innerHTML = "";
    return;
  }
  const view = viewOf(ed);
  const { box } = shown;
  let el = ed.over.querySelector(".tl-box");
  if (!el || el.dataset.what !== shown.what) {
    const writes = shown.what === "crop" ? ed.writesProject : ed.writesEffects;
    ed.over.innerHTML = `<div class="tl-box ${shown.what}" data-what="${shown.what}">` +
      (writes ? HANDLES.map((h) => `<i data-h="${h}"></i>`).join("") : "") + `</div>`;
    el = ed.over.firstChild;
  }
  el.classList.toggle("off", shown.what === "blur" && !shown.on);
  el.style.left = `${(box.x - view.x) / view.w * 100}%`;
  el.style.top = `${(box.y - view.y) / view.h * 100}%`;
  el.style.width = `${box.w / view.w * 100}%`;
  el.style.height = `${box.h / view.h * 100}%`;
}

function wireOverlay(ed) {
  ed.over.addEventListener("pointerdown", (event) => {
    const el = event.target.closest(".tl-box");
    if (!el || event.button > 0) return;
    const shown = overlayBox(ed);
    if (!shown || (shown.what === "crop" ? !ed.writesProject : !ed.writesEffects)) return;
    event.preventDefault();
    el.setPointerCapture(event.pointerId);
    const handle = event.target.dataset.h || "";
    const rect = ed.stage.getBoundingClientRect();
    const view = viewOf(ed);
    const start = { ...shown.box };
    const x0 = event.clientX;
    const y0 = event.clientY;
    // While it plays, dragging the box draws its path: a keyframe every fifth of a second.
    const drag = { last: null, lastT: null };
    ed.drag = drag;
    drag.box = (moved) => {
      if (!moved) return;
      if (shown.what === "crop") {
        ed.project.fields.crop = moved;
      } else {
        const piece = pieceById(ed, shown.piece.id);
        const effect = ed.effects.find((e) => e.id === shown.effect.id);
        if (!piece || !effect) return;
        let t = clamp(now(ed) - piece.start, 0, piece.length);
        if (ed.playing && drag.lastT !== null && t - drag.lastT < 0.2) t = drag.lastT;
        drag.lastT = t;
        effect.keyframes = setKeyframe(effect.keyframes, t, moved, fps(ed));
      }
      ed.dirty = true;
      placeOverlay(ed);
    };
    const move = (e) => {
      const dx = (e.clientX - x0) / rect.width * view.w;
      const dy = (e.clientY - y0) / rect.height * view.h;
      let b = { ...start };
      if (!handle) { b.x += dx; b.y += dy; }
      if (handle.includes("w")) { b.x += dx; b.w -= dx; }
      if (handle.includes("e")) b.w += dx;
      if (handle.includes("n")) { b.y += dy; b.h -= dy; }
      if (handle.includes("s")) b.h += dy;
      // Dragged past its other edge, a box turns over rather than going negative.
      if (b.w < 0) { b.x += b.w; b.w = -b.w; }
      if (b.h < 0) { b.y += b.h; b.h = -b.h; }
      if (!handle) b = { ...b, x: clamp(b.x, 0, 100 - b.w), y: clamp(b.y, 0, 100 - b.h) };
      drag.last = fitBox(b, shown.what === "crop" ? 5 : 2);
      drag.box(drag.last);
    };
    const up = () => {
      for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) el.removeEventListener(type, up);
      el.removeEventListener("pointermove", move);
      ed.drag = null;
      if (!drag.last) return;
      if (shown.what === "crop") {
        saveCrop(ed, drag.last);
      } else {
        const effect = ed.effects.find((e) => e.id === shown.effect.id);
        if (effect) saveKeyframes(ed, effect);
      }
    };
    el.addEventListener("pointermove", move);
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) el.addEventListener(type, up);
  });
}

function saveKeyframes(ed, effect) {
  drawSide(ed);
  drawTracks(ed);
  const keyframes = effect.keyframes.map((k) => ({ ...k }));
  write(ed, () => patch(ed.b.effects.id, effect.id, { keyframes }));
}

function saveCrop(ed, box) {
  const r = (n) => Math.round(n * 100) / 100;
  const value = wholeFrame(box) ? null : { x: r(box.x), y: r(box.y), w: r(box.w), h: r(box.h) };
  ed.project.fields.crop = value;
  ed.dirty = true;
  placeOverlay(ed);
  drawSide(ed);
  write(ed, () => patch(ed.b.model.id, ed.id, { crop: value }));
}

function setCropping(ed, on) {
  ed.cropping = on;
  const toggle = ed.root.querySelector(".tl-crop-toggle");
  toggle.classList.toggle("on", on);
  toggle.setAttribute("aria-pressed", String(on));
  fitStage(ed);
  placeOverlay(ed);
  drawSide(ed);
}

// -- the transport ---------------------------------------------------------------------------------
function wireTransport(ed) {
  ed.root.querySelector(".tl-play").addEventListener("click", () => (ed.playing ? pause(ed) : play(ed)));
  for (const button of ed.root.querySelectorAll("[data-go]")) {
    button.addEventListener("click", () => step(ed, button.dataset.go));
  }
  ed.root.querySelector(".tl-crop-toggle").addEventListener("click", () => setCropping(ed, !ed.cropping));
  ed.root.querySelector(".tl-material-open").addEventListener("click", () => openMaterialSheet(ed));
  ed.root.querySelector(".tl-split").addEventListener("click", () => split(ed));
  ed.root.querySelector(".tl-delete").addEventListener("click", () => remove(ed));
  for (const button of ed.root.querySelectorAll("[data-zoom]")) {
    button.addEventListener("click", () => zoomBy(ed, Number(button.dataset.zoom) > 0 ? 1.5 : 1 / 1.5));
  }
}

function step(ed, where) {
  const frame = 1 / fps(ed);
  if (where === "first") seek(ed, 0);
  if (where === "last") seek(ed, total(ed));
  if (where === "back") { pause(ed); seek(ed, Math.round((ed.t - frame) * fps(ed)) / fps(ed)); }
  if (where === "on") { pause(ed); seek(ed, Math.round((ed.t + frame) * fps(ed)) / fps(ed)); }
  followPlayhead(ed, ed.t);
}

function wireKeys(ed) {
  ed.onKey = (event) => {
    if (!ed.alive || event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
    const target = event.target;
    if (target.closest && target.closest("input, textarea, select, [contenteditable]")) return;
    if (document.querySelector(".sheet-backdrop")) return;
    const second = event.shiftKey ? 1 : 1 / fps(ed);
    const piece = pieceById(ed, ed.selected);
    const keys = {
      " ": () => (ed.playing ? pause(ed) : play(ed)),
      ArrowLeft: () => { pause(ed); seek(ed, ed.t - second); },
      ArrowRight: () => { pause(ed); seek(ed, ed.t + second); },
      Home: () => seek(ed, 0),
      End: () => seek(ed, total(ed)),
      s: () => split(ed),
      Delete: () => remove(ed),
      Backspace: () => remove(ed),
      m: () => piece && setPiece(ed, piece, { muted: !piece.muted }),
      "[": () => piece && trimTo(ed, piece, "start", ed.t),
      "]": () => piece && trimTo(ed, piece, "end", ed.t),
      b: () => piece && addBlur(ed),
      c: () => setCropping(ed, !ed.cropping),
      Escape: () => { if (ed.cropping) setCropping(ed, false); else choose(ed, ""); },
      "+": () => zoomBy(ed, 1.5),
      "=": () => zoomBy(ed, 1.5),
      "-": () => zoomBy(ed, 1 / 1.5),
    };
    const run = keys[event.key];
    if (!run) return;
    event.preventDefault();
    run();
  };
  addEventListener("keydown", ed.onKey);
}

// -- the header: export, and how it is going --------------------------------------------------------
function drawHeader(ed) {
  const bar = ed.root.querySelector(".tl-headbar");
  const buttons = ed.root.querySelector(".tl-head-actions");
  const f = ed.project.fields;
  const status = ed.b.has.has("status") ? String(f.status || "") : "";
  const tone = TONES[status] || "";
  const message = ed.b.has.has("message") ? String(f.message || "") : "";
  const shownStatus = status && status !== "editing" ? status[0].toUpperCase() + status.slice(1) : "";
  const exportable = ed.b.exportAction;
  const output = ed.b.has.has("output") && f.output ? String(f.output) : "";
  bar.innerHTML =
    `<span class="tl-status${tone ? " tone-" + tone : ""}">${BUSY.has(status) ? '<i class="tl-spin"></i>' : ""}` +
    `${esc(shownStatus)}${shownStatus && message ? " · " : ""}${esc(message)}</span>`;
  bar.hidden = !(shownStatus || message);
  buttons.innerHTML =
    (output ? `<button type="button" class="tl-open">Open</button>` : "") +
    (exportable ? `<button type="button" class="act-button primary tl-export"${BUSY.has(status) ? " disabled" : ""}>${esc(exportable.label)}</button>` : "");
  const open = buttons.querySelector(".tl-open");
  if (open) open.addEventListener("click", () => openOutput(ed, output));
  const button = buttons.querySelector(".tl-export");
  if (button) {
    button.addEventListener("click", () => {
      pause(ed);
      press(ed.at.quill, exportable, {
        record: ed.id,
        here: { quill: ed.at.quill, screen: ed.at.screen },
        after: () => refreshProject(ed),
      });
    });
  }
}

/** The project's status, message and output as they are now; asked again
    every few seconds while an export is on its way. */
async function refreshProject(ed) {
  if (!ed.alive) return;
  try {
    const project = await api("GET", recordsUrl(ed.b.model.id, ed.id));
    if (!ed.alive) return;
    for (const name of ["status", "message", "output"]) ed.project.fields[name] = project.fields[name];
    drawHeader(ed);
  } catch { /* asked again on the next round */ }
  watchExport(ed);
}

function watchExport(ed) {
  clearTimeout(ed.pollTimer);
  if (!ed.alive || !BUSY.has(String(ed.project.fields.status || ""))) return;
  ed.pollTimer = setTimeout(() => refreshProject(ed), POLL);
}

// The export is a file record: fetched through a media link, saved as itself.
async function openOutput(ed, fileId) {
  try {
    const [record, made] = await Promise.all([
      api("GET", recordsUrl("file", fileId)),
      api("POST", recordsUrl("file", fileId, "/media")),
    ]);
    const a = document.createElement("a");
    a.href = made.url;
    a.download = String(record.fields.name || "");
    a.target = "_blank";
    document.body.append(a);
    a.click();
    a.remove();
  } catch (err) {
    toast(err.status === 404 ? "The exported file is not there any more" : said(err));
  }
}

// -- the material --------------------------------------------------------------------------------------
// What is known of a file across visits: its length and size, by id.
const known = new Map();

async function loadMaterial(ed) {
  const box = ed.root.querySelector(".tl-material");
  box.innerHTML = `<p class="group-label">Material</p><p class="tl-quiet">Looking…</p>`;
  if (!ed.b.files) {
    box.innerHTML = `<p class="group-label">Material</p><p class="tl-quiet">Your files are not shared with this screen.</p>`;
    return;
  }
  let records = [];
  try {
    const query = new URLSearchParams(Object.entries(ed.b.media).map(([k, v]) => [k, String(v)])).toString();
    records = await api("GET", recordsUrl(ed.b.files.id) + (query ? `?${query}` : ""));
  } catch (err) {
    ed.materialProblem = said(err);
  }
  if (!ed.alive) return;
  const title = ed.b.files.title || "name";
  const within = String(ed.b.media.within || "").replace(/^\/+|\/+$/g, "");
  for (const r of records) {
    const f = r.fields;
    if (f.kind === "folder") continue;
    const name = String(f[title] || "");
    const kind = mediaKind(name, String(f.mime || ""));
    if (!kind) continue;
    let folder = String(f.folder || "");
    if (within && (folder === within || folder.startsWith(within + "/"))) folder = folder.slice(within.length + 1);
    ed.files.set(r.id, { id: r.id, name, folder, kind, modified: String(f.modified || "") });
  }
  drawMaterial(ed);
  // The pieces' own kinds are known now: a sound has no picture to wait for.
  ed.dirty = true;
  for (const file of ed.files.values()) lengthFor(ed, file);
}

function materialList(ed) {
  const files = [...ed.files.values()];
  if (!files.length) {
    const where = [ed.b.media.within].filter(Boolean).join("");
    return `<p class="tl-quiet">${esc(ed.materialProblem ||
      `No videos or sounds${where ? ` in ${where}` : ""} yet. Put some there, and they are here.`)}</p>`;
  }
  const folders = new Map();
  for (const file of files.sort((a, b) => a.name.localeCompare(b.name))) {
    if (!folders.has(file.folder)) folders.set(file.folder, []);
    folders.get(file.folder).push(file);
  }
  const tracks = ed.tracks.map((t) => `<option value="${esc(t.id)}"${t.id === ed.target ? " selected" : ""}>${esc(t.name)}</option>`).join("");
  return (ed.writes ? `<label class="tl-target">On<select aria-label="The track it goes on">` +
      `<option value="">the first of its kind</option>${tracks}</select></label>` : "") +
    [...folders.keys()].sort().map((folder) =>
      (folder ? `<p class="tl-folder">${esc(folder)}</p>` : "") +
      `<div class="group">${folders.get(folder).map((file) => {
        const info = known.get(file.id);
        return `<div class="row tl-file" data-file="${esc(file.id)}">
          <span class="icon">${glyphs[file.kind]}</span>
          <span class="main"><span class="title">${esc(file.name)}</span>
            <span class="meta"><span class="date tl-length">${esc(info ? lengthOf(info.duration) : "")}</span></span></span>
          ${ed.writes ? `<button type="button" class="tl-add" data-add="${esc(file.id)}" aria-label="Add ${esc(file.name)}">${glyphs.plus}<span>Add</span></button>` : ""}
        </div>`;
      }).join("")}</div>`).join("");
}

function wireMaterial(ed, root, done = () => {}) {
  const select = root.querySelector(".tl-target select");
  if (select) select.addEventListener("change", () => { ed.target = select.value; });
  for (const button of root.querySelectorAll("[data-add]")) {
    button.addEventListener("click", async () => {
      button.disabled = true;
      await addMaterial(ed, ed.files.get(button.dataset.add));
      button.disabled = false;
      done();
    });
  }
}

function drawMaterial(ed) {
  const box = ed.root.querySelector(".tl-material");
  box.innerHTML = `<p class="group-label">Material</p>` + materialList(ed);
  wireMaterial(ed, box);
  const sheet = document.querySelector(".tl-material-sheet .tl-sheet-list");
  if (sheet) { sheet.innerHTML = materialList(ed); wireMaterial(ed, sheet, closeMaterialSheet); }
}

// A phone has no room beside the viewer: the material comes up as a sheet.
function openMaterialSheet(ed) {
  closeMaterialSheet();
  const backdrop = document.createElement("div");
  backdrop.className = "sheet-backdrop tl-sheet-backdrop";
  backdrop.innerHTML = `<div class="sheet tl-material-sheet" role="dialog" aria-modal="true" aria-label="Material">
    <p class="act-sheet-title">Material</p><div class="tl-sheet-list">${materialList(ed)}</div>
    <button type="button" class="sheet-row cancel">Close</button></div>`;
  document.body.append(backdrop);
  wireMaterial(ed, backdrop, closeMaterialSheet);
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop || event.target.closest(".cancel")) closeMaterialSheet();
  });
}

function closeMaterialSheet() {
  for (const el of document.querySelectorAll(".tl-sheet-backdrop")) el.remove();
}

// A few lengths at a time: each is a media link and the first bytes of the file.
let reading = 0;
const toRead = [];

function lengthFor(ed, file) {
  if (known.has(file.id)) return Promise.resolve(known.get(file.id));
  return new Promise((resolve) => {
    toRead.push({ ed, file, resolve });
    readNext();
  });
}

function readNext() {
  while (reading < 3 && toRead.length) {
    const job = toRead.shift();
    if (!job.ed.alive) { job.resolve(null); continue; }
    reading += 1;
    probe(job.ed, job.file).then((info) => {
      if (info) {
        known.set(job.file.id, info);
        const cell = document.querySelectorAll(`.tl-file[data-file="${CSS.escape(job.file.id)}"] .tl-length`);
        for (const el of cell) el.textContent = lengthOf(info.duration);
      }
      job.resolve(info);
    }).finally(() => { reading -= 1; readNext(); });
  }
}

/** A source's length and size: the frames API's answer, else the media's own. */
async function probe(ed, file) {
  if (ed.b.frames) {
    try {
      const info = await api("GET", `${ed.b.frames}/info?file=${encodeURIComponent(file.id)}`);
      if (Number(info.duration) > 0) {
        return { duration: Number(info.duration), width: Number(info.width) || 0, height: Number(info.height) || 0, fps: Number(info.fps) || 0 };
      }
    } catch { /* read from the media below */ }
  }
  let made;
  try { made = await api("POST", recordsUrl("file", file.id, "/media")); } catch { return null; }
  return new Promise((resolve) => {
    const el = document.createElement(file.kind === "audio" ? "audio" : "video");
    el.preload = "metadata";
    el.muted = true;
    const done = (info) => {
      clearTimeout(timer);
      el.removeAttribute("src");
      el.load();
      resolve(info);
    };
    const timer = setTimeout(() => done(null), 15000);
    el.addEventListener("loadedmetadata", () => done(Number.isFinite(el.duration) && el.duration > 0
      ? { duration: el.duration, width: el.videoWidth || 0, height: el.videoHeight || 0, fps: 0 } : null));
    el.addEventListener("error", () => done(null));
    el.src = made.url;
  });
}

/** A source on the timeline, whole, at the playhead: on the chosen track,
    or the first of its kind. The first picture gives the project its size. */
async function addMaterial(ed, file) {
  if (!file || !ed.writes) return;
  const track = trackFor(ed.tracks, file.kind, ed.target);
  if (!track) { toast(`This ${ed.b.model.label.toLowerCase()} has no ${file.kind} track`); return; }
  const info = await lengthFor(ed, file);
  if (!info || !(info.duration > 0)) { toast(`Cannot read how long ${file.name} is`); return; }
  know(ed, file.id, info);
  pause(ed);
  const fields = {
    [ed.b.pieceProject]: ed.id, track: track.id, source: file.id, name: file.name,
    start: ms(ed.t), offset: 0, length: ms(info.duration),
  };
  await write(ed, async () => {
    const made = await api("POST", recordsUrl(ed.b.pieces.id), { fields });
    const piece = pieceOf(made);
    const grew = ed.pieces.length === 0 || (piece.start + piece.length) * ed.zoom > ed.lanes.clientWidth - 24;
    ed.pieces.push(piece);
    prepare(ed, piece);
    // The tracks are fitted again to the cut when it outgrows them.
    if (grew) fitZoom(ed);
    ed.selected = piece.id;
    ed.effect = "";
    const f = ed.project.fields;
    if (file.kind === "video" && info.width && info.height && !(Number(f.width) > 0 && Number(f.height) > 0)) {
      const size = { width: info.width, height: info.height };
      if (!(Number(f.fps) > 0)) size.fps = info.fps || 30;
      Object.assign(f, size);
      fitStage(ed);
      await patch(ed.b.model.id, ed.id, size);
    }
    drawTracks(ed);
    drawSide(ed);
    showTime(ed, ed.t);
    ed.dirty = true;
    toast(`${file.name} is on ${track.name}`);
  });
}

// -- the tracks -----------------------------------------------------------------------------------------
const STEPS = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800];

function fitZoom(ed) {
  const room = Math.max(200, ed.lanes.clientWidth - 24);
  ed.zoom = clamp(room / Math.max(10, total(ed) * 1.15), 4, 300);
}

function drawTracks(ed) {
  if (!ed.zoom) fitZoom(ed);
  const length = total(ed);
  const room = ed.lanes.clientWidth || 600;
  const span = Math.max(length + 20, room / ed.zoom);
  const width = Math.ceil(span * ed.zoom);
  const step = STEPS.find((s) => s * ed.zoom >= 64) || STEPS[STEPS.length - 1];
  const ticks = [];
  for (let t = 0; t <= span; t += step) {
    ticks.push(`<span class="tl-tick" style="left:${t * ed.zoom}px">${esc(clockOf(t).replace(/\.00$/, ""))}</span>`);
  }
  const selectedEffect = ed.effects.find((e) => e.id === ed.effect);
  const pieceEl = (p) => {
    const kind = trackById(ed, p.track)?.kind || "video";
    const blurs = effectsOn(ed, p).length;
    const thumb = ed.thumbs.get(p.id);
    const marks = selectedEffect && selectedEffect.piece === p.id && selectedEffect.keyframes.length > 1
      ? selectedEffect.keyframes.map((k) => `<i class="tl-key" style="left:${k.t * ed.zoom}px"></i>`).join("") : "";
    return `<div class="tl-piece ${kind}${soundOnly(ed, p) ? " sound" : ""}${p.id === ed.selected ? " on" : ""}${p.muted ? " muted" : ""}"` +
      ` data-id="${esc(p.id)}" style="left:${p.start * ed.zoom}px;width:${Math.max(2, p.length * ed.zoom)}px` +
      `${thumb ? `;background-image:url(&quot;${thumb}&quot;)` : ""}" title="${esc(p.name)}">` +
      `<span class="tl-name">${p.muted ? glyphs.mute : ""}${esc(p.name)}</span>` +
      (blurs ? `<span class="tl-badge">${blurs} blur${blurs === 1 ? "" : "s"}</span>` : "") + marks +
      (ed.writes ? `<i class="tl-edge left" data-edge="start"></i><i class="tl-edge right" data-edge="end"></i>` : "") +
      `</div>`;
  };
  ed.inner.style.width = `${width}px`;
  ed.inner.style.setProperty("--minor", `${step / 5 * ed.zoom}px`);
  ed.inner.innerHTML = `<div class="tl-ruler">${ticks.join("")}</div>` +
    ed.tracks.map((track) => `<div class="tl-row ${esc(track.kind)}" data-track="${esc(track.id)}">${
      ed.pieces.filter((p) => p.track === track.id).sort((a, b) => a.start - b.start).map(pieceEl).join("")}</div>`).join("") +
    `<div class="tl-playhead" style="transform:translateX(${ed.t * ed.zoom}px)"></div>`;
  ed.root.querySelector(".tl-heads").innerHTML = `<div class="tl-head-ruler"></div>` +
    ed.tracks.map((track) => `<div class="tl-head ${esc(track.kind)}">${esc(track.name)}</div>`).join("");
  ed.timeText = "";
  showTime(ed, ed.t);
  drawTools(ed);
}

/** Split and Delete, for what is chosen and where the playhead is. */
function drawTools(ed) {
  const piece = pieceById(ed, ed.selected);
  ed.root.querySelector(".tl-split").disabled = !ed.writes || !piece || !splitPiece(piece, ed.t);
  ed.root.querySelector(".tl-delete").disabled = !ed.writes || !piece;
}

function zoomBy(ed, factor, aroundX = null) {
  const lanes = ed.lanes;
  const x = aroundX === null ? lanes.clientWidth / 2 : aroundX;
  const t = (lanes.scrollLeft + x) / ed.zoom;
  ed.zoom = clamp(ed.zoom * factor, 2, 400);
  drawTracks(ed);
  lanes.scrollLeft = t * ed.zoom - x;
}

/** Keep the playhead in sight while it plays. */
function followPlayhead(ed, t) {
  const x = t * ed.zoom;
  const lanes = ed.lanes;
  if (x < lanes.scrollLeft || x > lanes.scrollLeft + lanes.clientWidth - 24) {
    lanes.scrollLeft = Math.max(0, x - 24);
  }
}

function choose(ed, id) {
  if (ed.selected !== id) {
    ed.selected = id;
    const piece = pieceById(ed, id);
    const first = piece ? effectsOn(ed, piece).find((e) => e.kind === "blur") : null;
    ed.effect = first ? first.id : "";
  }
  for (const el of ed.inner.querySelectorAll(".tl-piece")) el.classList.toggle("on", el.dataset.id === id);
  drawTracks(ed);
  drawSide(ed);
  placeOverlay(ed);
}

/** Every edge a moving piece may snap to: the other pieces' ends, the playhead and the start. */
function edgesBut(ed, id) {
  const edges = [0, ed.t];
  for (const p of ed.pieces) if (p.id !== id) edges.push(p.start, p.start + p.length);
  return edges;
}

/** *fn* on the pointer's coming up, unless the browser took it for a scroll. */
function tapped(el, fn) {
  const up = (e) => { done(); fn(e); };
  const done = () => { el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", done); };
  el.addEventListener("pointerup", up);
  el.addEventListener("pointercancel", done);
}

function wireTracks(ed) {
  const lanes = ed.lanes;
  // A ctrl-wheel (or a pinch on a trackpad) zooms, around the pointer.
  lanes.addEventListener("wheel", (event) => {
    if (!event.ctrlKey) return;
    event.preventDefault();
    const rect = lanes.getBoundingClientRect();
    zoomBy(ed, event.deltaY < 0 ? 1.2 : 1 / 1.2, event.clientX - rect.left);
  }, { passive: false });

  lanes.addEventListener("pointerdown", (event) => {
    if (event.button > 0) return;
    const ruler = event.target.closest(".tl-ruler");
    const pieceEl = event.target.closest(".tl-piece");
    const rect = ed.inner.getBoundingClientRect();
    const timeAt = (e) => Math.max(0, (e.clientX - rect.left) / ed.zoom);
    if (ruler) {
      // The ruler is scrubbed: the playhead follows the pointer.
      event.preventDefault();
      ruler.setPointerCapture(event.pointerId);
      seek(ed, timeAt(event));
      const move = (e) => seek(ed, timeAt(e));
      const up = () => { ruler.removeEventListener("pointermove", move); ruler.removeEventListener("pointerup", up); };
      ruler.addEventListener("pointermove", move);
      ruler.addEventListener("pointerup", up);
      return;
    }
    if (!pieceEl) {
      // A tap on an empty stretch of a track puts the playhead there.
      const x0 = event.clientX;
      const y0 = event.clientY;
      tapped(lanes, (e) => {
        if (Math.abs(e.clientX - x0) < 6 && Math.abs(e.clientY - y0) < 6 && e.target.closest(".tl-row, .tl-inner")) {
          if (ed.selected) choose(ed, "");
          seek(ed, timeAt(e));
        }
      });
      return;
    }
    const piece = pieceById(ed, pieceEl.dataset.id);
    if (!piece) return;
    const touch = event.pointerType !== "mouse";
    // A finger scrolls the tracks with any piece but the chosen one; it is
    // chosen with a tap first, and then moved.
    const grabs = ed.writes && (!touch || piece.id === ed.selected);
    const edge = event.target.dataset.edge || "";
    if (!grabs) {
      const x0 = event.clientX;
      tapped(pieceEl, (e) => { if (Math.abs(e.clientX - x0) < 8) choose(ed, piece.id); });
      return;
    }
    event.preventDefault();
    if (piece.id !== ed.selected) choose(ed, piece.id);
    const el = ed.inner.querySelector(`.tl-piece[data-id="${CSS.escape(piece.id)}"]`);
    el.setPointerCapture(event.pointerId);
    const was = { ...piece };
    const x0 = event.clientX;
    let moved = false;
    let next = null;
    const reach = 10 / ed.zoom;
    const edges = edgesBut(ed, piece.id);
    const rows = [...ed.inner.querySelectorAll(".tl-row")];
    const kind = trackById(ed, piece.track)?.kind;
    const move = (e) => {
      const dx = (e.clientX - x0) / ed.zoom;
      if (!moved && Math.abs(e.clientX - x0) < 4 && Math.abs(e.clientY - event.clientY) < 4) return;
      moved = true;
      el.classList.add("dragging");
      if (edge === "start") {
        next = trimStart(was, snapTo(was.start + dx, edges, reach));
      } else if (edge === "end") {
        const info = ed.info.get(was.source);
        next = trimEnd(was, snapTo(was.start + was.length + dx, edges, reach), info ? info.duration : Infinity);
      } else {
        // To another track of the same kind, if the pointer is over one.
        const over = rows.find((row) => {
          const r = row.getBoundingClientRect();
          return e.clientY >= r.top && e.clientY < r.bottom;
        });
        const track = over && trackById(ed, over.dataset.track);
        const to = track && track.kind === kind ? track.id : piece.track;
        next = { start: ms(snapMove(was.start + dx, was.length, edges, reach)), track: to };
        // Shown over the row it is going to; moved into it when it is let go
        // (moving the element itself would lose hold of the pointer).
        const home = el.parentElement.getBoundingClientRect();
        const there = ed.inner.querySelector(`.tl-row[data-track="${CSS.escape(to)}"]`).getBoundingClientRect();
        el.style.transform = to === was.track ? "" : `translateY(${there.top - home.top}px)`;
      }
      Object.assign(piece, next);
      el.style.left = `${piece.start * ed.zoom}px`;
      el.style.width = `${Math.max(2, piece.length * ed.zoom)}px`;
      ed.dirty = true;
    };
    const up = () => {
      for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) el.removeEventListener(type, up);
      el.removeEventListener("pointermove", move);
      el.classList.remove("dragging");
      if (!moved || !next) return;
      commitPiece(ed, piece, was, next);
    };
    el.addEventListener("pointermove", move);
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) el.addEventListener(type, up);
  });
}

/** Write a piece's new place or length; a trimmed start moves its keyframes
    by as much the other way, so nothing on screen moves with it. */
function commitPiece(ed, piece, was, next) {
  const fields = {};
  for (const name of ["start", "offset", "length", "track"]) {
    if (name in next && next[name] !== was[name]) fields[name] = next[name];
  }
  if (!Object.keys(fields).length) { drawTracks(ed); return; }
  const shifted = [];
  if (next.shift) {
    for (const effect of effectsOn(ed, piece)) {
      effect.keyframes = shiftKeyframes(effect.keyframes, next.shift);
      shifted.push(effect);
    }
  }
  drawTracks(ed);
  drawSide(ed);
  showTime(ed, ed.t);
  ed.dirty = true;
  write(ed, async () => {
    await patch(ed.b.pieces.id, piece.id, fields);
    for (const effect of shifted) await patch(ed.b.effects.id, effect.id, { keyframes: effect.keyframes });
  });
}

function setPiece(ed, piece, fields) {
  if (!ed.writes) return;
  Object.assign(piece, fields);
  drawTracks(ed);
  drawSide(ed);
  ed.dirty = true;
  write(ed, () => patch(ed.b.pieces.id, piece.id, fields));
}

/** A trim of either end to *t*, from the keys: `[` and `]`. */
function trimTo(ed, piece, end, t) {
  if (!ed.writes) return;
  const was = { ...piece };
  const info = ed.info.get(piece.source);
  const next = end === "start" ? trimStart(was, t) : trimEnd(was, t, info ? info.duration : Infinity);
  Object.assign(piece, next);
  commitPiece(ed, piece, was, next);
}

/** Cut the chosen piece (else the picture at the playhead) in two at the
    playhead; its effects go with the half they are on, or with both. */
function split(ed) {
  if (!ed.writes) return;
  const pictures = ed.pieces.filter((p) => !soundOnly(ed, p));
  // Cut on a millisecond, as the times are stored, so the playhead is on the second half.
  ed.t = ms(ed.t);
  const piece = pieceById(ed, ed.selected) || pictureAt(pictures, ed.tracks, ed.t);
  const halves = piece && splitPiece(piece, ed.t);
  if (!halves) { toast("Put the playhead inside a piece to split it"); return; }
  pause(ed);
  const [first, second] = halves;
  const cut = ed.t - piece.start;
  const effects = effectsOn(ed, piece);
  Object.assign(piece, first);
  drawTracks(ed);
  write(ed, async () => {
    await patch(ed.b.pieces.id, piece.id, { length: first.length });
    const fields = { [ed.b.pieceProject]: ed.id, track: piece.track, source: piece.source, name: piece.name, ...second };
    // What the datamodel has of the rest, as the first half has it now.
    const has = new Set(ed.b.pieces.fields.map((f) => f.name));
    if (has.has("volume")) fields.volume = piece.volume;
    if (has.has("muted")) fields.muted = piece.muted;
    const made = await api("POST", recordsUrl(ed.b.pieces.id), { fields });
    const other = pieceOf(made);
    ed.pieces.push(other);
    prepare(ed, other);
    for (const effect of effects) {
      const [left, right] = splitKeyframes(effect.keyframes, cut);
      if (!left) {
        effect.keyframes = right;
        effect.piece = other.id;
        await patch(ed.b.effects.id, effect.id, { [ed.b.effectPiece]: other.id, keyframes: right });
      } else {
        effect.keyframes = left;
        await patch(ed.b.effects.id, effect.id, { keyframes: left });
        if (right) {
          const copy = await api("POST", recordsUrl(ed.b.effects.id), {
            fields: { [ed.b.effectPiece]: other.id, kind: effect.kind, label: effect.label, strength: effect.strength, keyframes: right },
          });
          ed.effects.push(effectOf(ed.b, copy));
        }
      }
    }
    ed.selected = other.id;
    const blur = effectsOn(ed, other).find((e) => e.kind === "blur");
    ed.effect = blur ? blur.id : "";
    drawTracks(ed);
    drawSide(ed);
    placeOverlay(ed);
    ed.dirty = true;
  });
}

function remove(ed) {
  const piece = pieceById(ed, ed.selected);
  if (!piece || !ed.writes) return;
  ed.pieces = ed.pieces.filter((p) => p.id !== piece.id);
  ed.effects = ed.effects.filter((e) => e.piece !== piece.id);
  const el = ed.sounds.get(piece.id);
  if (el) { el.pause(); el.remove(); ed.sounds.delete(piece.id); }
  ed.selected = "";
  ed.effect = "";
  if (ed.t > total(ed)) ed.t = total(ed);
  drawTracks(ed);
  drawSide(ed);
  placeOverlay(ed);
  ed.dirty = true;
  write(ed, () => api("DELETE", recordsUrl(ed.b.pieces.id, piece.id)));
}

// -- the side: the chosen piece, its effects, and the crop -------------------------------------------------
function drawSide(ed) {
  const side = ed.root.querySelector(".tl-side");
  // Not while something in it is being typed in or dragged: it is drawn after.
  if (side.contains(document.activeElement) && document.activeElement.matches("input[type=text], input[type=number]")) {
    ed.sideStale = true;
    return;
  }
  const piece = pieceById(ed, ed.selected);
  let html = "";
  if (piece) {
    const track = trackById(ed, piece.track);
    const volume = Math.round(piece.volume * 100);
    html += `<p class="group-label">Piece</p><div class="group tl-card">
      <div class="row"><span class="main"><span class="title">${esc(piece.name)}</span>
        <span class="meta"><span class="date">${esc(track ? track.name : piece.track)}</span>
        <span class="preview">${esc(clockOf(piece.start))} – ${esc(clockOf(piece.start + piece.length))} (${esc(lengthOf(piece.length))})</span></span></span></div>
      <label class="row tl-volume"><span class="main">Volume</span>
        <input type="range" min="0" max="200" step="5" value="${volume}" aria-label="Volume"${ed.writes ? "" : " disabled"}>
        <output>${volume}%</output></label>
      <label class="row tl-mute"><span class="main">Muted</span>
        <input type="checkbox" class="switch"${piece.muted ? " checked" : ""}${ed.writes ? "" : " disabled"}></label>
    </div>`;
    if (ed.b.effects) html += effectsPanel(ed, piece);
  } else {
    html += `<p class="tl-quiet tl-hint">Choose a piece on the tracks to set its volume, cut it, or blur something in it.</p>`;
  }
  html += cropPanel(ed);
  side.innerHTML = html;
  ed.sideStale = false;
  wireSide(ed, side, piece);
}

function effectsPanel(ed, piece) {
  const effects = effectsOn(ed, piece);
  const t = ed.t - piece.start;
  const half = 0.5 / fps(ed);
  const effectRow = (e) => {
    const chosen = e.id === ed.effect;
    if (e.kind !== "blur") {
      return `<div class="row tl-effect other"><span class="main"><span class="title">${esc(e.label || e.kind)}</span>
        <span class="meta"><span class="preview">${esc(e.kind)}, not drawn here</span></span></span></div>`;
    }
    const keys = e.keyframes.map((k) =>
      `<span class="tl-keyframe${Math.abs(k.t - t) <= half ? " here" : ""}"><button type="button" data-jump="${k.t}">${esc(clockOf(piece.start + k.t))}</button>` +
      (ed.writesEffects && e.keyframes.length > 1 ? `<button type="button" class="tl-unkey" data-unkey="${k.t}" aria-label="Remove the keyframe at ${esc(clockOf(piece.start + k.t))}">${glyphs.close}</button>` : "") +
      `</span>`).join("");
    return `<div class="tl-effect${chosen ? " on" : ""}" data-effect="${esc(e.id)}">
      <button type="button" class="tl-effect-pick" aria-pressed="${chosen}">${esc(e.label || "Blur")}</button>
      ${chosen ? `<div class="tl-effect-body">
        <label class="tl-field"><span>Label</span><input type="text" class="tl-label" value="${esc(e.label)}" placeholder="What it hides"${ed.writesEffects ? "" : " disabled"}></label>
        <label class="tl-field"><span>Strength</span><input type="range" class="tl-strength" min="1" max="100" value="${e.strength}"${ed.writesEffects ? "" : " disabled"}><output>${e.strength}</output></label>
        <p class="tl-keys-label">Keyframes <span class="tl-quiet">— move the box on the picture to set one at the playhead</span></p>
        <div class="tl-keyframes">${keys}</div>
        ${ed.writesEffects ? `<button type="button" class="tl-drop-effect">${icons.trash}<span>Remove this blur</span></button>` : ""}
      </div>` : ""}
    </div>`;
  };
  return `<p class="group-label">Effects</p>
    <div class="tl-effects">${effects.length ? effects.map(effectRow).join("")
      : `<p class="tl-quiet">Nothing on this piece yet.</p>`}</div>
    ${ed.writesEffects ? `<button type="button" class="act-chip tl-add-blur">${glyphs.plus}<span>Add blur</span></button>` : ""}`;
}

function cropPanel(ed) {
  const c = crop(ed);
  const number = (name, label) =>
    `<label class="tl-field small"><span>${label}</span><input type="number" min="0" max="100" step="0.5" data-crop="${name}" value="${Math.round(c[name] * 10) / 10}"${ed.writesProject ? "" : " disabled"}></label>`;
  return `<p class="group-label">Crop</p>
    ${ed.cropping ? `<div class="tl-crop-fields">${number("x", "Left")}${number("y", "Top")}${number("w", "Width")}${number("h", "Height")}</div>
      <p class="tl-quiet">Percent of the picture. Drag the box on the viewer, or type.</p>
      <div class="tl-row-buttons">${ed.writesProject ? `<button type="button" class="act-chip tl-crop-reset">Reset</button>` : ""}
        <button type="button" class="act-chip tl-crop-done">Done</button></div>`
    : `<p class="tl-quiet">${wholeFrame(c) ? "The whole picture is kept." : `Kept: ${Math.round(c.w)}% × ${Math.round(c.h)}% from ${Math.round(c.x)}%, ${Math.round(c.y)}%.`}</p>
      <div class="tl-row-buttons"><button type="button" class="act-chip tl-crop-start">${glyphs.crop}<span>Crop</span></button></div>`}`;
}

function wireSide(ed, side, piece) {
  const on = (selector, type, fn) => { const el = side.querySelector(selector); if (el) el.addEventListener(type, fn); };
  if (piece) {
    on(".tl-volume input", "input", (event) => {
      piece.volume = Number(event.target.value) / 100;
      side.querySelector(".tl-volume output").textContent = `${event.target.value}%`;
      const el = ed.sounds.get(piece.id);
      if (el) loudness(ed, el, piece.volume);
    });
    on(".tl-volume input", "change", (event) => setPiece(ed, piece, { volume: Number(event.target.value) / 100 }));
    on(".tl-mute input", "change", (event) => setPiece(ed, piece, { muted: event.target.checked }));
  }
  on(".tl-add-blur", "click", () => addBlur(ed));
  for (const pick of side.querySelectorAll(".tl-effect-pick")) {
    pick.addEventListener("click", () => {
      const id = pick.closest("[data-effect]").dataset.effect;
      ed.effect = ed.effect === id ? "" : id;
      drawSide(ed);
      drawTracks(ed);
      placeOverlay(ed);
    });
  }
  const effect = ed.effects.find((e) => e.id === ed.effect);
  if (effect && piece) {
    on(".tl-label", "change", (event) => {
      effect.label = event.target.value.trim();
      write(ed, () => patch(ed.b.effects.id, effect.id, { label: effect.label }));
      drawSide(ed);
    });
    on(".tl-strength", "input", (event) => {
      effect.strength = Number(event.target.value);
      side.querySelector(".tl-strength + output").textContent = event.target.value;
      ed.dirty = true;
    });
    on(".tl-strength", "change", () => write(ed, () => patch(ed.b.effects.id, effect.id, { strength: effect.strength })));
    for (const jump of side.querySelectorAll("[data-jump]")) {
      jump.addEventListener("click", () => { pause(ed); seek(ed, piece.start + Number(jump.dataset.jump)); followPlayhead(ed, ed.t); });
    }
    for (const drop of side.querySelectorAll("[data-unkey]")) {
      drop.addEventListener("click", () => {
        effect.keyframes = dropKeyframe(effect.keyframes, Number(drop.dataset.unkey), fps(ed));
        ed.dirty = true;
        placeOverlay(ed);
        saveKeyframes(ed, effect);
      });
    }
    on(".tl-drop-effect", "click", () => {
      ed.effects = ed.effects.filter((e) => e.id !== effect.id);
      ed.effect = "";
      ed.dirty = true;
      drawSide(ed);
      drawTracks(ed);
      placeOverlay(ed);
      write(ed, () => api("DELETE", recordsUrl(ed.b.effects.id, effect.id)));
    });
  }
  on(".tl-crop-start", "click", () => setCropping(ed, true));
  on(".tl-crop-done", "click", () => setCropping(ed, false));
  on(".tl-crop-reset", "click", () => saveCrop(ed, { x: 0, y: 0, w: 100, h: 100 }));
  for (const input of side.querySelectorAll("[data-crop]")) {
    input.addEventListener("change", () => {
      const box = { ...crop(ed), [input.dataset.crop]: Number(input.value) || 0 };
      input.blur();
      saveCrop(ed, fitBox(box, 5));
    });
  }
  // Drawn again once the typing is over, if something changed while it went on.
  side.addEventListener("focusout", () => { if (ed.sideStale) setTimeout(() => ed.alive && drawSide(ed), 0); }, { once: true });
}

/** A blur on the chosen piece, at the playhead, with a box in the middle. */
function addBlur(ed) {
  const piece = pieceById(ed, ed.selected);
  if (!piece || !ed.writesEffects) return;
  pause(ed);
  if (ed.t < piece.start || ed.t >= piece.start + piece.length) seek(ed, piece.start);
  const keyframes = [{ t: ms(ed.t - piece.start), x: 35, y: 25, w: 30, h: 40 }];
  const count = effectsOn(ed, piece).length + 1;
  const fields = { [ed.b.effectPiece]: piece.id, kind: "blur", label: `Blur ${count}`, strength: 20, keyframes };
  write(ed, async () => {
    const made = await api("POST", recordsUrl(ed.b.effects.id), { fields });
    const effect = effectOf(ed.b, made);
    ed.effects.push(effect);
    ed.effect = effect.id;
    if (ed.cropping) setCropping(ed, false);
    drawSide(ed);
    drawTracks(ed);
    placeOverlay(ed);
    ed.dirty = true;
  });
}
