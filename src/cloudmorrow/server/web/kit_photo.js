/* The kit's `photo`: a photo editor, drawn from the screen's bindings alone.

   A photo screen names a datamodel with the kit's own field names
   (docs/PHOTO.md): the edit (`model`) — one picture from the drive, how it
   is turned and mirrored, the part of it kept, and the size it comes out —
   and, optionally, the layers laid on it (`layers`: words, marker strokes,
   and pieces copied out of the picture); where the photos are (`media`, a
   filter on the drive's file records); and, optionally, a pictures API, an
   export action (with its form) and a save action (overwrite the photo, or
   save as a new file beside it).

     #/q/<quill>/<screen>          the edits, newest first, with New
     #/q/<quill>/<screen>/<id>     one edit in the editor
     #/q/<quill>/<screen>/edit=<id>   the same, as a Quill's `go` says it

   The editor is laid out as a simple picture program: a bar across the
   top with Resize, Export and Save (and how the last save went), the tools
   down the left (Select, Move, Marquee, Crop, Text, Marker, and the
   turns), the picture in the middle on a dark ground, and on the right the tool's
   options and the layers, newest on top. The picture is a canvas the
   source is drawn on, turned and mirrored as the edit says, every layer on
   it in its order in the app's own font, and the crop either kept to or —
   with the Crop tool — shown as a box to move, the rest dimmed. A layer is
   picked by pressing it, dragged to where it should be, and sized by its
   corners; the Marker draws strokes; Marquee draws a box to copy a piece
   of the picture, which Paste lays on it as a layer, or to crop to. Select
   is the tool one comes back to: Escape, Done, Paste, and words just laid
   all hand back to it, so the next press picks and moves. Resize
   asks, in a sheet, what size the saved picture should be; Save asks
   whether to write over the photo or save as a new file; Export is the
   Quill's action with its form.

   A drag — a box moved or sized, a stroke, a box drawn out — is held by
   the overlay over the picture, never by the box itself: the box is drawn
   anew as it moves, and a pointer held by an element that is gone lets go.

   The source is drawn from the server's large copy of it (`/thumb`), so a
   phone's photo comes quickly and a HEIC needs no plug-in here; its true
   size is read from the pictures API, or from the file itself once. What
   changes is written as it changes, on the records API; when the server
   says no, the edit is read again and drawn as it is. The arithmetic — the
   turn, the crop, the export's size, where a layer is — is
   kit_photo_rules.js, the same rules the terminal has. */

import {
  api, apiRaw, app, esc, formatDate, go, heading, icons, mount, nav, occupy, pixelIcon, recordsUrl, replace,
  renderRoute, seconds, tabs, toast, vacate, wireShell,
} from "./core.js";
import { aOr, mayWrite, plural, sheetHash } from "./kit.js";
import { press, said } from "./actions.js";
import { openSheet } from "./dialog.js";
import {
  boxBetween, boxWithRatio, clamp, COLOURS, colourFrom, cropOf, croppedSize, fitBox, HIGHLIGHT_OPACITY, isPhoto,
  layerBox, layerLabel, layerOf, layersInOrder, MARK_OPACITY, MARK_WIDTH, MARK_WIDTHS, markBox, mirrored, movedMark,
  nearMark, outputSize, pictureSize, picturesPath, RATIOS, ratioOf, rotationOf, SIZES, sizeFrom, sourceSize,
  TEXT_AT, TEXT_COLOUR, TEXT_SIZE, textLines, thinned, topOrder, turned, wholeFrame,
} from "./kit_photo_rules.js";

const glyphs = {
  select: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M5 2.5v13l3.4-3.2 2.3 5.2 2.6-1.2-2.3-5h4.8z"/></svg>',
  move: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 2v16M2 10h16"/><path d="m7 5 3-3 3 3M7 15l3 3 3-3M5 7l-3 3 3 3M15 7l3 3-3 3"/></svg>',
  marquee: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-dasharray="3 2.5"><rect x="3" y="3" width="14" height="14" rx="1.5"/></svg>',
  crop: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M5 1.5V15h13.5M1.5 5H15v13.5"/></svg>',
  text: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5.5V3h12v2.5M10 3v14M7.5 17h5"/></svg>',
  marker: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m3 17 1-4 9.5-9.5a1.8 1.8 0 0 1 2.5 0l.5.5a1.8 1.8 0 0 1 0 2.5L7 16z"/><path d="m12 5 3 3M3 17h5"/></svg>',
  left: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9.5a6 6 0 1 1 1.8 4.3"/><path d="M4 5v4.5h4.5"/></svg>',
  right: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M16 9.5a6 6 0 1 0-1.8 4.3"/><path d="M16 5v4.5h-4.5"/></svg>',
  mirror: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 2v16"/><path d="M7 5 2.5 10 7 15zM13 5l4.5 5-4.5 5z"/></svg>',
  paste: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="12" height="14" rx="1.8"/><path d="M7.5 4V2.5h5V4M7.5 9.5h5M7.5 13h5"/></svg>',
  copy: '<svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="7" y="7" width="11" height="11" rx="1.8"/><path d="M13 7V3.8A1.8 1.8 0 0 0 11.2 2H3.8A1.8 1.8 0 0 0 2 3.8v7.4A1.8 1.8 0 0 0 3.8 13H7"/></svg>',
  photo: '<svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="2" y="3" width="16" height="14" rx="2"/><circle cx="7" cy="8" r="1.6"/><path d="m2.5 15 4.5-4.5 3 3 3-3 4.5 4.5"/></svg>',
  piece: '<svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="2.5" y="2.5" width="15" height="15" rx="2"/><path d="M2.5 10h15M10 2.5v15"/></svg>',
  eye: '<svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M1.5 10S4.5 4.5 10 4.5 18.5 10 18.5 10 15.5 15.5 10 15.5 1.5 10 1.5 10z"/><circle cx="10" cy="10" r="2.5"/></svg>',
  eyeOff: '<svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"><path d="M3 3l14 14M8 5a8.9 8.9 0 0 1 2-.5c5.5 0 8.5 5.5 8.5 5.5a14 14 0 0 1-2.7 3.2M5 6.8A13.5 13.5 0 0 0 1.5 10S4.5 15.5 10 15.5a8 8 0 0 0 3-.6"/></svg>',
  up: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 8.5 4-4 4 4"/></svg>',
  down: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 5.5 4 4 4-4"/></svg>',
  close: '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m2.5 2.5 7 7M9.5 2.5l-7 7"/></svg>',
  resize: '<svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="2.5" width="15" height="15" rx="2"/><path d="M11 6h3v3M9 14H6v-3M14 6l-4 4M6 14l4-4"/></svg>',
};
// How big a tile's picture is asked for, and the picture that is edited.
const TILE = 256;
const LARGE = 2048;
// How a status is toned beside Save; anything else is said plainly.
const TONES = { queued: "info", rendering: "info", done: "good", failed: "bad" };
const BUSY = new Set(["queued", "rendering"]);
const POLL = 3000;
const WIDEST = 2048;             // the most pixels across the canvas draws
const NEW_WORDS = "Your words";  // what a new text says until it is written
const TOOLS = [
  ["select", "Select", "V"], ["move", "Move", "G"], ["marquee", "Marquee", "M"], ["crop", "Crop", "C"], ["text", "Text", "T"],
  ["marker", "Marker", "B"],
];
// The tool everything comes back to: Escape, Done, Paste, words just laid.
const HOME = "select";
const HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];
// The tools that make layers: offered only when the screen has them.
const LAYER_TOOLS = new Set(["text", "marker"]);

// -- the screen's bindings ---------------------------------------------------------------
const linkTo = (model, to) => {
  const links = (model ? model.fields : []).filter((f) => f.kind === "link" && f.to === to);
  return links.length === 1 ? links[0].name : "";
};

/** What a photo editor is drawn from, read out of its bindings once. */
export function bindingsOf(at) {
  const { quill, screen } = at;
  const model = quill.models[screen.model];
  const layers = screen.layers ? quill.models[screen.layers] || null : null;
  const files = quill.models.file || null;
  const action = (id) => (id ? (quill.actions || []).find((a) => a.id === id) || null : null);
  return {
    model,
    title: screen.title || model.title,
    has: new Set(model.fields.map((f) => f.name)),
    layers,
    files,
    layerEdit: layers ? linkTo(layers, model.id) : "",
    media: screen.media || {},
    pictures: picturesPath(quill, screen),
    exportAction: action(screen.export),
    saveAction: action(screen.save),
  };
}

/** What the record sheet does for an edit: back to its editor, not to the list. */
export function photoSheet(at, model) {
  if (model.id !== at.screen.model) return null;
  return { parent: (record) => `${at.base}/${encodeURIComponent(record.id)}` };
}

const layerFrom = (record) => ({ id: record.id, record, created_at: record.created_at, ...layerOf(record.fields) });

let live = null;             // the editor on the page, while there is one
let clipboard = null;        // what Copy took: {kind: "region", box} or {kind: "layer", fields}
// The marker as last used, while the app is open.
const marker = { colour: "#e0323c", width: MARK_WIDTH, opacity: MARK_OPACITY };

export async function renderPhoto(at, arg) {
  const b = bindingsOf(at);
  // A Quill's `go("editor", edit=<id>)` arrives as parameters: that edit, at its own address.
  if (arg && arg.includes("=")) {
    const edit = new URLSearchParams(arg).get("edit");
    replace(edit ? `${at.base}/${encodeURIComponent(edit)}` : at.base);
    arg = edit || "";
  }
  if (!arg) return renderEdits(at, b);
  return renderEditorFor(at, b, arg);
}

// -- the edits -------------------------------------------------------------------------------
async function renderEdits(at, b) {
  const { screen } = at;
  const records = await api("GET", recordsUrl(b.model.id));
  records.sort((x, y) => String(y.created_at || "").localeCompare(String(x.created_at || "")));
  const writes = mayWrite(b.model);
  const row = (r) => {
    const f = r.fields;
    const status = b.has.has("status") && f.status && f.status !== "editing" ? String(f.status) : "";
    const size = outputSize(f);
    const line = [size ? `${size.w} × ${size.h}` : "", status && status[0].toUpperCase() + status.slice(1), f.message]
      .filter(Boolean).join(" · ");
    const changed = seconds(r.updated_at || r.created_at);
    return `<a class="row ph-edit" href="${at.base}/${encodeURIComponent(r.id)}">
      <span class="icon ph-thumb" data-thumb="${esc(String(f.source || ""))}">${glyphs.photo}</span>
      <span class="main"><span class="title">${esc(String(f[b.title] || "").trim() || "Untitled")}</span>
        <span class="meta">${changed ? `<span class="date">${esc(formatDate(changed))}</span>` : ""}${
          line ? `<span class="preview">${esc(line)}</span>` : ""}</span></span>${icons.chevronRight}</a>`;
  };
  const label = b.model.label.toLowerCase();
  mount(nav({ title: screen.label }) + `
    <main class="kit-photo-list">
      ${heading(screen.label, writes ? `<button class="compose" aria-label="New ${esc(label)}">${icons.compose}</button>` : "")}
      <div class="listing">${records.length
        ? `<div class="group">${records.map(row).join("")}</div>`
        : `<p class="empty"><b>No ${esc(plural(label))} yet</b>${writes ? `Start ${aOr(b.model.label)} from a photo with the button at the top.` : ""}</p>`}</div>
    </main>` + tabs(at.tab));
  wireShell();
  const compose = app.querySelector(".heading .compose");
  if (compose) compose.addEventListener("click", () => pickPhoto(at, b));
  for (const thumb of app.querySelectorAll(".ph-thumb[data-thumb]")) {
    if (!thumb.dataset.thumb) continue;
    thumbURL(thumb.dataset.thumb, 128).then((url) => { if (url) thumb.innerHTML = `<img src="${url}" alt="">`; });
  }
}

// The server's small copy of a file's picture, by id and size, kept while the app is open.
const thumbs = new Map();
function thumbURL(fileId, size) {
  const key = `${fileId}/${size}`;
  if (!thumbs.has(key)) {
    thumbs.set(key, apiRaw("GET", recordsUrl("file", fileId) + `/thumb?size=${size}`, { fail: "no picture" })
      .then(async (res) => URL.createObjectURL(await res.blob()))
      .catch(() => ""));
  }
  return thumbs.get(key);
}

// -- a new edit: a photo from the drive ------------------------------------------------------
// The drive last chosen for a Quill's photos, while the app is open.
const lastDrive = new Map();

/** The photos of a drive as tiles in a sheet; tapping one starts an edit of it. */
async function pickPhoto(at, b, onMade = null) {
  if (!b.files) { toast("Your files are not shared with this screen"); return; }
  closePhotoSheet();
  const backdrop = document.createElement("div");
  backdrop.className = "sheet-backdrop ph-sheet-backdrop";
  backdrop.innerHTML = `<div class="sheet ph-photo-sheet" role="dialog" aria-modal="true" aria-label="Which photo">
    <p class="act-sheet-title">New ${esc(b.model.label.toLowerCase())}</p>
    <div class="ph-sheet-list"><p class="ph-quiet">Looking…</p></div>
    <button type="button" class="sheet-row cancel">Cancel</button></div>`;
  document.body.append(backdrop);
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop || event.target.closest(".cancel")) closePhotoSheet();
  });
  const picker = { drives: [], drive: lastDrive.get(at.quill.id) || String(b.media.share || ""), files: [], problem: "" };
  try {
    const shares = await api("GET", recordsUrl("share"));
    picker.drives = shares.filter((s) => s.fields.browsable !== false).map((s) => ({ id: s.id, label: String(s.fields.label || s.id) }));
  } catch { picker.drives = []; }
  if (picker.drive && !picker.drives.some((d) => d.id === picker.drive)) picker.drives.unshift({ id: picker.drive, label: picker.drive });
  if (!picker.drive && picker.drives.length) picker.drive = picker.drives[0].id;
  const list = backdrop.querySelector(".ph-sheet-list");
  const load = async () => {
    picker.files = [];
    picker.problem = "";
    try {
      const where = { ...b.media, share: picker.drive };
      const query = new URLSearchParams(Object.entries(where).map(([k, v]) => [k, String(v)])).toString();
      const records = await api("GET", recordsUrl(b.files.id) + (query ? `?${query}` : ""));
      const title = b.files.title || "name";
      const within = String(b.media.within || "").replace(/^\/+|\/+$/g, "");
      for (const r of records) {
        const f = r.fields;
        const name = String(f[title] || "");
        if (f.kind === "folder" || !isPhoto(name, String(f.mime || ""))) continue;
        let folder = String(f.folder || "");
        if (within && (folder === within || folder.startsWith(within + "/"))) folder = folder.slice(within.length + 1);
        picker.files.push({ id: r.id, name, folder, record: r });
      }
    } catch (err) {
      picker.problem = said(err);
    }
    if (!backdrop.isConnected) return;
    draw();
  };
  const draw = () => {
    const drives = picker.drives.length > 1
      ? `<label class="ph-drive"><span>From</span><select aria-label="Which drive the photos are in">${picker.drives.map((d) =>
        `<option value="${esc(d.id)}"${d.id === picker.drive ? " selected" : ""}>${esc(d.label)}</option>`).join("")}</select></label>`
      : "";
    let body = "";
    if (!picker.files.length) {
      const where = [b.media.within].filter(Boolean).join("");
      body = `<p class="ph-quiet">${esc(picker.problem || `No photos${where ? ` in ${where}` : ""} here yet. Put some there, and they are here.`)}</p>`;
    } else {
      const folders = new Map();
      for (const file of picker.files.sort((a, c) => a.name.localeCompare(c.name))) {
        if (!folders.has(file.folder)) folders.set(file.folder, []);
        folders.get(file.folder).push(file);
      }
      const tile = (file) => `<div class="ph-tile" role="button" tabindex="0" data-file="${esc(file.id)}" title="${esc(file.name)}" aria-label="Edit ${esc(file.name)}">` +
        `<span class="ph-tile-pic" data-tile="${esc(file.id)}">${glyphs.photo}</span><span class="ph-tile-name">${esc(file.name)}</span></div>`;
      body = [...folders.keys()].sort().map((folder) =>
        (folder ? `<p class="ph-folder">${esc(folder)}</p>` : "") +
        `<div class="ph-tiles">${folders.get(folder).map(tile).join("")}</div>`).join("");
    }
    list.innerHTML = drives + body;
    const select = list.querySelector(".ph-drive select");
    if (select) {
      select.addEventListener("change", () => {
        picker.drive = select.value;
        lastDrive.set(at.quill.id, picker.drive);
        load();
      });
    }
    for (const tile of list.querySelectorAll(".ph-tile")) {
      const file = picker.files.find((f) => f.id === tile.dataset.file);
      const start = async () => {
        if (tile.classList.contains("busy")) return;
        tile.classList.add("busy");
        try {
          const stem = file.name.includes(".") ? file.name.slice(0, file.name.lastIndexOf(".")) : file.name;
          const made = await api("POST", recordsUrl(b.model.id), { fields: { [b.title]: stem || "Photo", source: file.id } });
          closePhotoSheet();
          if (onMade) onMade(made);
          else go(`${at.base}/${encodeURIComponent(made.id)}`);
        } catch (err) {
          tile.classList.remove("busy");
          toast(said(err));
        }
      };
      tile.addEventListener("click", start);
      tile.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); start(); } });
      thumbURL(file.id, TILE).then((url) => {
        const pic = list.querySelector(`.ph-tile-pic[data-tile="${CSS.escape(file.id)}"]`);
        if (url && pic) pic.innerHTML = `<img src="${url}" alt="" draggable="false">`;
      });
    }
  };
  load();
}

function closePhotoSheet() {
  for (const el of document.querySelectorAll(".ph-sheet-backdrop")) el.remove();
}

// -- the editor --------------------------------------------------------------------------------
async function loadEdit(b, id) {
  const [edit, layers] = await Promise.all([
    api("GET", recordsUrl(b.model.id, id)),
    b.layers ? api("GET", recordsUrl(b.layers.id) + `?${encodeURIComponent(b.layerEdit)}=${encodeURIComponent(id)}`) : Promise.resolve([]),
  ]);
  return { edit, layers: layersInOrder(layers).map(layerFrom) };
}

async function renderEditorFor(at, b, id) {
  let loaded;
  try {
    loaded = await loadEdit(b, id);
  } catch (err) {
    if (err.status !== 404) throw err;
    toast(`That ${b.model.label.toLowerCase()} is gone`);
    replace(at.base);
    return renderRoute();
  }
  const ed = {
    at, b, id,
    ...loaded,
    image: null,                 // the source, drawn: an <img> of the server's large copy
    turnedPic: null,             // the source turned and mirrored, as a canvas: what a piece is cut from
    turnedKey: "",
    sourceFile: null,            // the photo's file record: its name, for Save
    tool: HOME, ratio: "",
    selected: "",                // the layer being worked on
    selection: null,             // the Select tool's box, in percent of the picture
    stroke: null,                // a marker stroke being drawn: its points
    alive: true, writing: Promise.resolve(),
    writes: mayWrite(b.model),
    writesLayers: !!b.layers && mayWrite(b.layers),
    boxes: new Map(),            // where each text is on the picture, in percent, as last drawn
  };
  if (live) live.stop();
  live = ed;
  ed.stop = () => stopEditor(ed);
  const hold = { stays: () => false, leave: async () => { ed.stop(); vacate(hold); }, flush: () => {} };
  occupy(hold);

  const title = String(ed.edit.fields[b.title] || "").trim() || "Untitled";
  const tool = ([id, label, key]) =>
    `<button type="button" class="ph-tool" data-tool="${id}" aria-pressed="${id === ed.tool}" title="${label} (${key})">${glyphs[id]}<span>${label}</span></button>`;
  // Without layers there are no words, strokes or pieces: those tools are not offered.
  const tools = TOOLS.filter(([id]) => b.layers || !LAYER_TOOLS.has(id));
  mount(nav({ back: at.base, backLabel: at.screen.label, title }) + `
    <main class="kit-photo">
      ${heading(title, `<a class="button ph-settings" href="${sheetHash(at, b.model.id, id)}" aria-label="${esc(b.model.label)} settings" title="${esc(b.model.label)} settings">${pixelIcon("settings")}</a>`)}
      <div class="ph-bar"><span class="ph-status" role="status"></span><span class="ph-bar-actions"></span></div>
      <div class="ph-desk">
        <nav class="ph-tools" aria-label="Tools">
          ${tools.map(tool).join("")}
          <span class="ph-tools-gap"></span>
          <button type="button" class="ph-tool ph-act" data-turn="-90" title="Turn left (shift+R)"${ed.writes ? "" : " disabled"}>${glyphs.left}<span>Left</span></button>
          <button type="button" class="ph-tool ph-act" data-turn="90" title="Turn right (R)"${ed.writes ? "" : " disabled"}>${glyphs.right}<span>Right</span></button>
          <button type="button" class="ph-tool ph-act ph-mirror" aria-pressed="false" title="Mirror"${ed.writes ? "" : " disabled"}>${glyphs.mirror}<span>Mirror</span></button>
          ${b.layers ? `<button type="button" class="ph-tool ph-act ph-paste" title="Paste (ctrl+V)"${ed.writesLayers ? "" : " disabled"}>${glyphs.paste}<span>Paste</span></button>` : ""}
        </nav>
        <section class="ph-viewer">
          <div class="ph-stage-box"><div class="ph-stage">
            <canvas aria-label="The picture as it will be"></canvas><div class="ph-over"></div>
            <p class="ph-stage-words" hidden></p>
          </div></div>
          <p class="ph-footline"></p>
        </section>
        <aside class="ph-side">
          <section class="ph-options" aria-label="The tool"></section>
          <section class="ph-layers" aria-label="Layers"></section>
        </aside>
      </div>
    </main>` + tabs(at.tab));
  wireShell();

  ed.root = app.querySelector("main.kit-photo");
  ed.canvas = ed.root.querySelector("canvas");
  ed.ctx = ed.canvas.getContext("2d");
  ed.stage = ed.root.querySelector(".ph-stage");
  ed.over = ed.root.querySelector(".ph-over");

  drawHeader(ed);
  drawTools(ed);
  drawSide(ed);
  wireTools(ed);
  wireOverlay(ed);
  wireKeys(ed);
  fitStage(ed);
  ed.resize = new ResizeObserver(() => { fitStage(ed); paint(ed); });
  ed.resize.observe(ed.root.querySelector(".ph-stage-box"));
  watchExport(ed);
  loadPicture(ed);
  loadSourceFile(ed);
}

function stopEditor(ed) {
  if (!ed.alive) return;
  ed.alive = false;
  clearTimeout(ed.pollTimer);
  if (ed.resize) ed.resize.disconnect();
  if (ed.onKey) removeEventListener("keydown", ed.onKey);
  ed.image = null;
  ed.turnedPic = null;
  closePhotoSheet();
  if (live === ed) live = null;
}

// -- what is where ------------------------------------------------------------------------------
const f = (ed) => ed.edit.fields;
const layerById = (ed, id) => ed.layers.find((l) => l.id === id) || null;
const chosen = (ed) => layerById(ed, ed.selected);
const crop = (ed) => cropOf(f(ed).crop);
const cropping = (ed) => ed.tool === "crop";
const viewOf = (ed) => (cropping(ed) ? { x: 0, y: 0, w: 100, h: 100 } : crop(ed));
/** The picture as worked on — the source, turned — or a placeholder shape until it is known. */
const picture = (ed) => pictureSize(f(ed)) || (ed.image && ed.image.naturalWidth
  ? turned(ed.image.naturalWidth, ed.image.naturalHeight, rotationOf(f(ed))) : { w: 4, h: 3 });

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
    Object.assign(ed, await loadEdit(ed.b, ed.id));
  } catch (err) {
    toast(said(err));
    return;
  }
  if (!chosen(ed)) ed.selected = "";
  redraw(ed);
}

/** Everything drawn again: the header, the picture, the panels. */
function redraw(ed) {
  drawHeader(ed);
  drawTools(ed);
  fitStage(ed);
  paint(ed);
  drawSide(ed);
}

function setEdit(ed, fields) {
  Object.assign(ed.edit.fields, fields);
  redraw(ed);
  write(ed, () => patch(ed.b.model.id, ed.id, fields));
}

// -- the source ----------------------------------------------------------------------------------
/** The server's large copy of the source, to draw; and its true size, when the edit has none. */
async function loadPicture(ed) {
  const source = String(f(ed).source || "");
  const words = ed.root.querySelector(".ph-stage-words");
  const problem = (text) => { words.textContent = text; words.hidden = false; };
  if (!source) { problem("This edit has no photo."); return; }
  const url = await thumbURL(source, LARGE);
  if (!ed.alive) return;
  if (!url) {
    problem("The photo cannot be drawn here: the server could not read it as a picture.");
  } else {
    const img = new Image();
    img.decoding = "async";
    await new Promise((resolve) => { img.onload = resolve; img.onerror = resolve; img.src = url; });
    if (!ed.alive) return;
    if (img.naturalWidth) { ed.image = img; words.hidden = true; } else problem("The photo cannot be drawn here.");
  }
  fitStage(ed);
  paint(ed);
  if (!sourceSize(f(ed)) && ed.writes) fillSize(ed, source);
}

/** The photo's file record: what Save writes over, by name. */
async function loadSourceFile(ed) {
  const source = String(f(ed).source || "");
  if (!source) return;
  try {
    ed.sourceFile = await api("GET", recordsUrl("file", source));
  } catch { ed.sourceFile = null; }
  if (ed.alive) drawFootline(ed);
}

/** An edit made without its photo's size gets it: from the pictures API, or
    from the file itself, read once. */
async function fillSize(ed, source) {
  let size = null;
  if (ed.b.pictures) {
    try {
      const info = await api("GET", `${ed.b.pictures}/info?file=${encodeURIComponent(source)}`);
      if (info && info.width > 0 && info.height > 0) size = { width: Number(info.width), height: Number(info.height) };
    } catch { /* the file itself, then */ }
  }
  if (!size) {
    try {
      const made = await api("POST", recordsUrl("file", source, "/media"));
      const img = new Image();
      await new Promise((resolve) => { img.onload = resolve; img.onerror = resolve; img.src = made.url; });
      if (img.naturalWidth) size = { width: img.naturalWidth, height: img.naturalHeight };
      img.removeAttribute("src");
    } catch { /* unknown until a service fills it in */ }
  }
  if (!ed.alive || !size || sourceSize(f(ed))) return;
  setEdit(ed, size);
}

// -- the picture -------------------------------------------------------------------------------
function fitStage(ed) {
  if (!ed.alive) return;
  const box = ed.root.querySelector(".ph-stage-box");
  const pic = picture(ed);
  const view = viewOf(ed);
  const ratio = (pic.w * view.w) / (pic.h * view.h);
  const room = Math.max(1, box.clientWidth - 2);
  const tall = matchMedia("(min-width: 900px) and (min-height: 600px)").matches
    ? Math.max(240, Math.min(innerHeight - 250, 900)) : Math.min(innerHeight * 0.5, 520);
  const width = Math.max(1, Math.min(room, tall * ratio));
  ed.stage.style.width = `${Math.round(width)}px`;
  ed.stage.style.height = `${Math.round(width / ratio)}px`;
  const across = Math.min(WIDEST, Math.round(width * (devicePixelRatio || 1)), Math.round(pic.w * view.w / 100) || 1);
  const canvasW = Math.max(16, across);
  const canvasH = Math.max(9, Math.round(canvasW / ratio));
  if (ed.canvas.width !== canvasW || ed.canvas.height !== canvasH) {
    ed.canvas.width = canvasW;
    ed.canvas.height = canvasH;
  }
}

/** The source as the edit turns and mirrors it, drawn once into a canvas of
    its own: the picture every piece is cut from, and what is painted. */
function turnedPicture(ed) {
  if (!ed.image) return null;
  const rotate = rotationOf(f(ed));
  const mirror = mirrored(f(ed));
  const key = `${ed.image.src}|${rotate}|${mirror}`;
  if (ed.turnedKey === key && ed.turnedPic) return ed.turnedPic;
  const img = ed.image;
  const size = turned(img.naturalWidth, img.naturalHeight, rotate);
  const canvas = document.createElement("canvas");
  canvas.width = size.w;
  canvas.height = size.h;
  const ctx = canvas.getContext("2d");
  ctx.translate(size.w / 2, size.h / 2);
  if (mirror) ctx.scale(-1, 1);
  ctx.rotate(rotate * Math.PI / 180);
  ctx.drawImage(img, -img.naturalWidth / 2, -img.naturalHeight / 2);
  ed.turnedPic = canvas;
  ed.turnedKey = key;
  return canvas;
}

/** The picture as the export will be: the source turned and mirrored,
    every layer on it in its order, and the crop kept to — or, with the
    Crop tool, the whole picture with the crop drawn over it. */
function paint(ed) {
  if (!ed.alive) return;
  const { ctx, canvas } = ed;
  const pic = picture(ed);
  const view = viewOf(ed);
  const s = canvas.width / (pic.w * view.w / 100);
  const ox = pic.w * view.x / 100;
  const oy = pic.h * view.y / 100;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = 1;
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.setTransform(s, 0, 0, s, -ox * s, -oy * s);
  const base = turnedPicture(ed);
  if (base) ctx.drawImage(base, 0, 0, pic.w, pic.h);
  ed.boxes.clear();
  for (const layer of ed.layers) {
    if (layer.hidden) continue;
    if (layer.kind === "text") paintText(ed, ctx, layer, pic);
    else if (layer.kind === "mark") paintMark(ctx, layer, pic);
    else if (base) paintPiece(ctx, base, layer, pic);
  }
  if (ed.stroke && ed.stroke.length) {
    paintMark(ctx, { points: ed.stroke, colour: marker.colour, width: marker.width, opacity: marker.opacity }, pic);
  }
  ctx.globalAlpha = 1;
  placeOverlay(ed);
  drawFootline(ed);
}

function paintText(ed, ctx, layer, pic) {
  const { lines, px, lineHeight } = textLines(layer, pic.h);
  ctx.font = `600 ${px}px Barlow, "Barlow Semi Condensed", sans-serif`;
  ctx.textBaseline = "top";
  ctx.textAlign = "left";
  ctx.lineJoin = "round";
  ctx.lineWidth = Math.max(1, px * 0.08);
  ctx.strokeStyle = "rgba(0, 0, 0, .55)";
  ctx.fillStyle = layer.colour;
  const x = layer.x / 100 * pic.w;
  const y = layer.y / 100 * pic.h;
  let widest = 0;
  lines.forEach((line, i) => {
    widest = Math.max(widest, ctx.measureText(line).width);
    ctx.strokeText(line, x, y + i * lineHeight);
    ctx.fillText(line, x, y + i * lineHeight);
  });
  ed.boxes.set(layer.id, {
    x: layer.x, y: layer.y,
    w: Math.max(widest, px * 0.6) / pic.w * 100,
    h: lines.length * lineHeight / pic.h * 100,
  });
}

function paintMark(ctx, layer, pic) {
  const pts = layer.points;
  if (!pts.length) return;
  ctx.globalAlpha = layer.opacity;
  ctx.strokeStyle = layer.colour;
  ctx.fillStyle = layer.colour;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  const width = Math.max(1, layer.width / 100 * pic.h);
  ctx.lineWidth = width;
  ctx.beginPath();
  if (pts.length === 1) {
    ctx.arc(pts[0][0] / 100 * pic.w, pts[0][1] / 100 * pic.h, width / 2, 0, Math.PI * 2);
    ctx.fill();
  } else {
    ctx.moveTo(pts[0][0] / 100 * pic.w, pts[0][1] / 100 * pic.h);
    for (const p of pts.slice(1)) ctx.lineTo(p[0] / 100 * pic.w, p[1] / 100 * pic.h);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

function paintPiece(ctx, base, layer, pic) {
  const src = layer.source;
  ctx.drawImage(base,
    src.x / 100 * base.width, src.y / 100 * base.height, src.w / 100 * base.width, src.h / 100 * base.height,
    layer.x / 100 * pic.w, layer.y / 100 * pic.h, layer.w / 100 * pic.w, layer.h / 100 * pic.h);
}

/** Under the picture: the sizes, and what the tool does. */
function drawFootline(ed) {
  const line = ed.root.querySelector(".ph-footline");
  if (!line) return;
  const fields = f(ed);
  const src = sourceSize(fields);
  const out = outputSize(fields);
  const turn = rotationOf(fields);
  const how = [turn ? `turned ${turn}°` : "", mirrored(fields) ? "mirrored" : ""].filter(Boolean).join(", ");
  const sizes = (src ? `${src.w} × ${src.h}${out && (out.w !== src.w || out.h !== src.h) ? ` → ${out.w} × ${out.h}` : ""}` : "") +
    (how ? ` · ${how}` : "");
  const hints = {
    select: "Press a layer to pick it; drag to move, pull a corner to size it.",
    move: "Drag anywhere to move the chosen layer; press another to pick it.",
    marquee: "Drag a box on the picture: Copy it, or Crop to it.",
    crop: "Drag the box or draw a new one; Done keeps it.",
    text: "Press on the picture to put words there.",
    marker: "Draw on the picture.",
  };
  line.innerHTML = `<span>${esc(sizes)}</span><span class="ph-quiet-inline">${esc(hints[ed.tool] || "")}</span>`;
}

// -- the boxes on the picture -------------------------------------------------------------------
const boxStyle = (box, view) => `left:${(box.x - view.x) / view.w * 100}%;top:${(box.y - view.y) / view.h * 100}%;` +
  `width:${box.w / view.w * 100}%;height:${box.h / view.h * 100}%`;

/** The crop box with the Crop tool; the selection with Select; else the chosen layer's box. */
function placeOverlay(ed) {
  if (!ed.alive) return;
  const view = viewOf(ed);
  const handles = (which) => which.map((h) => `<i data-h="${h}"></i>`).join("");
  if (cropping(ed)) {
    ed.over.innerHTML = `<div class="ph-box crop" data-what="crop" style="${boxStyle(crop(ed), view)}">${ed.writes ? handles(HANDLES) : ""}</div>`;
    return;
  }
  if (ed.tool === "marquee") {
    ed.over.innerHTML = ed.selection
      ? `<div class="ph-box select" data-what="select" style="${boxStyle(ed.selection, view)}">${handles(HANDLES)}</div>` : "";
    return;
  }
  // The Marker draws wherever it is pressed, so no box is in the way; Text
  // keeps the box of the words just laid, to move them, and nothing else's.
  const layer = chosen(ed);
  if (!layer || layer.hidden || ed.tool === "marker" || (ed.tool === "text" && layer.kind !== "text")) { ed.over.innerHTML = ""; return; }
  const box = layerBox(layer, picture(ed), ed.boxes.get(layer.id));
  const grips = !ed.writesLayers ? "" : layer.kind === "piece" ? handles(HANDLES) : layer.kind === "text" ? handles(["se"]) : "";
  ed.over.innerHTML = `<div class="ph-box layer ${layer.kind}" data-what="layer" style="${boxStyle(box, view)}">${grips}</div>`;
}

/** Where a pointer is on the picture, in percent of the turned picture. */
function pointAt(ed, event) {
  const rect = ed.stage.getBoundingClientRect();
  const view = viewOf(ed);
  return {
    x: clamp(view.x + (event.clientX - rect.left) / rect.width * view.w, 0, 100),
    y: clamp(view.y + (event.clientY - rect.top) / rect.height * view.h, 0, 100),
  };
}

/** The topmost layer under (x, y), or null. */
function layerAt(ed, x, y) {
  const pic = picture(ed);
  for (const layer of [...ed.layers].reverse()) {
    if (layer.hidden) continue;
    if (layer.kind === "mark") {
      if (nearMark(layer, x, y, Math.max(layer.width, 1.5))) return layer;
      continue;
    }
    const box = layerBox(layer, pic, ed.boxes.get(layer.id));
    if (x >= box.x && x <= box.x + box.w && y >= box.y && y <= box.y + box.h) return layer;
  }
  return null;
}

function wireOverlay(ed) {
  ed.over.addEventListener("pointerdown", (event) => {
    if (event.button > 0) return;
    const box = event.target.closest(".ph-box");
    const at = pointAt(ed, event);
    if (box) {
      // The crop box over the whole picture has nowhere to go: a press on it, off its handles, draws a new one.
      if (box.dataset.what === "crop" && !event.target.dataset.h && wholeFrame(crop(ed)) && ed.writes) rubberBand(ed, event, at, "crop");
      else dragBox(ed, box.dataset.what, event, event.target.dataset.h || "");
      return;
    }
    if (ed.tool === "marker") { drawStroke(ed, event, at); return; }
    if (ed.tool === "marquee") { rubberBand(ed, event, at, "select"); return; }
    if (ed.tool === "crop") { if (ed.writes) rubberBand(ed, event, at, "crop"); return; }
    const hit = layerAt(ed, at.x, at.y);
    if (hit) {
      choose(ed, hit.id);
      dragBox(ed, "layer", event, "");
      return;
    }
    // Move: the chosen layer follows the hand, wherever it is pressed.
    if (ed.tool === "move" && chosen(ed)) { dragBox(ed, "layer", event, ""); return; }
    if (ed.tool === "text") { addText(ed, at); return; }
    choose(ed, "");
  });
}

/** A box held: moved, or sized by *handle*. The crop, the selection, or the chosen layer. */
function dragBox(ed, what, event, handle) {
  const layer = what === "layer" ? chosen(ed) : null;
  const may = what === "crop" ? ed.writes : what === "select" ? true : ed.writesLayers && !!layer;
  if (!may) return;
  event.preventDefault();
  const over = ed.over;
  over.setPointerCapture(event.pointerId);
  const rect = ed.stage.getBoundingClientRect();
  const view = viewOf(ed);
  const pic = picture(ed);
  const start = what === "crop" ? crop(ed) : what === "select" ? { ...ed.selection } : { ...layerBox(layer, pic, ed.boxes.get(layer.id)) };
  const was = layer ? { x: layer.x, y: layer.y, w: layer.w, h: layer.h, size: layer.size, points: layer.points } : null;
  const x0 = event.clientX;
  const y0 = event.clientY;
  let last = null;
  const resized = (dx, dy) => {
    let b = { ...start };
    if (!handle) { b.x += dx; b.y += dy; }
    if (handle.includes("w")) { b.x += dx; b.w -= dx; }
    if (handle.includes("e")) b.w += dx;
    if (handle.includes("n")) { b.y += dy; b.h -= dy; }
    if (handle.includes("s")) b.h += dy;
    if (b.w < 0) { b.x += b.w; b.w = -b.w; }
    if (b.h < 0) { b.y += b.h; b.h = -b.h; }
    if (!handle) b = { ...b, x: clamp(b.x, 0, 100 - b.w), y: clamp(b.y, 0, 100 - b.h) };
    return b;
  };
  const move = (e) => {
    const dx = (e.clientX - x0) / rect.width * view.w;
    const dy = (e.clientY - y0) / rect.height * view.h;
    if (what === "crop") {
      const b = resized(dx, dy);
      const ratio = ratioOf(ed.ratio);
      last = ratio && handle ? boxWithRatio(b, ratio, pic, handle === "n" || handle === "s") : fitBox(b, 5);
      ed.edit.fields.crop = last;
      placeOverlay(ed);
    } else if (what === "select") {
      last = fitBox(resized(dx, dy), 0.5);
      ed.selection = last;
      placeOverlay(ed);
      drawSide(ed);
    } else if (layer.kind === "piece") {
      const b = fitBox(resized(dx, dy), 0.5);
      Object.assign(layer, { x: b.x, y: b.y, w: b.w, h: b.h });
      last = { x: r2(b.x), y: r2(b.y), w: r2(b.w), h: r2(b.h) };
      paint(ed);
    } else if (layer.kind === "mark") {
      layer.points = movedMark({ ...layer, points: was.points }, dx, dy);
      last = { points: layer.points };
      paint(ed);
    } else if (!handle) {
      layer.x = clamp(was.x + dx, 0, Math.max(0, 100 - start.w));
      layer.y = clamp(was.y + dy, 0, Math.max(0, 100 - start.h));
      last = { x: r2(layer.x), y: r2(layer.y) };
      paint(ed);
    } else {
      // The corner: taller by as much as it is pulled down, in proportion.
      const grow = 1 + dy / Math.max(start.h, 0.5);
      layer.size = clamp(Math.round(was.size * grow * 10) / 10, 0.5, 100);
      last = { size: layer.size };
      paint(ed);
    }
  };
  const up = () => {
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) over.removeEventListener(type, up);
    over.removeEventListener("pointermove", move);
    if (!last) return;
    if (what === "crop") saveCrop(ed, last);
    else if (what === "layer") { drawSide(ed); write(ed, () => patch(ed.b.layers.id, layer.id, last)); }
  };
  over.addEventListener("pointermove", move);
  for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) over.addEventListener(type, up);
}

const r2 = (n) => Math.round(n * 100) / 100;

/** A box drawn out from a point: a new selection, or a new crop. */
function rubberBand(ed, event, from, what) {
  event.preventDefault();
  ed.over.setPointerCapture(event.pointerId);
  let box = null;
  const move = (e) => {
    const to = pointAt(ed, e);
    box = boxBetween(from, to, 0.5);
    if (what === "crop") {
      const ratio = ratioOf(ed.ratio);
      ed.edit.fields.crop = ratio ? boxWithRatio(box, ratio, picture(ed), false) : fitBox(box, 5);
    } else {
      ed.selection = box;
    }
    placeOverlay(ed);
  };
  const up = () => {
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) ed.over.removeEventListener(type, up);
    ed.over.removeEventListener("pointermove", move);
    if (!box) {
      if (what === "select") { ed.selection = null; placeOverlay(ed); drawSide(ed); }
      return;
    }
    if (what === "crop") saveCrop(ed, ed.edit.fields.crop);
    else drawSide(ed);
  };
  ed.over.addEventListener("pointermove", move);
  for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) ed.over.addEventListener(type, up);
}

/** A marker stroke: the points as the pointer goes, then one layer. */
function drawStroke(ed, event, from) {
  if (!ed.writesLayers) return;
  event.preventDefault();
  ed.over.setPointerCapture(event.pointerId);
  ed.stroke = [[r2(from.x), r2(from.y)]];
  paint(ed);
  const move = (e) => {
    const to = pointAt(ed, e);
    ed.stroke.push([r2(to.x), r2(to.y)]);
    ed.stroke = thinned(ed.stroke, 0.15);
    paint(ed);
  };
  const up = () => {
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) ed.over.removeEventListener(type, up);
    ed.over.removeEventListener("pointermove", move);
    const points = ed.stroke;
    ed.stroke = null;
    if (!points || !points.length) return;
    addLayer(ed, { kind: "mark", points, colour: marker.colour, width: marker.width, opacity: marker.opacity, x: points[0][0], y: points[0][1] });
  };
  ed.over.addEventListener("pointermove", move);
  for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) ed.over.addEventListener(type, up);
}

function saveCrop(ed, box) {
  const value = wholeFrame(box) ? null : { x: r2(box.x), y: r2(box.y), w: r2(box.w), h: r2(box.h) };
  setEdit(ed, { crop: value });
}

function choose(ed, id) {
  ed.selected = id;
  placeOverlay(ed);
  drawSide(ed);
}

function setTool(ed, tool) {
  if (tool === "crop" && !ed.writes) return;
  if (LAYER_TOOLS.has(tool) && !ed.b.layers) return;
  ed.tool = tool;
  if (tool !== "marquee") ed.selection = null;
  for (const button of ed.root.querySelectorAll(".ph-tool[data-tool]")) {
    button.setAttribute("aria-pressed", String(button.dataset.tool === tool));
  }
  ed.over.dataset.tool = tool;
  fitStage(ed);
  paint(ed);
  drawSide(ed);
}

// -- turning, mirroring, layers -----------------------------------------------------------------
function turn(ed, by) {
  if (!ed.writes || !ed.b.has.has("rotate")) return;
  setEdit(ed, { rotate: (rotationOf(f(ed)) + by + 360) % 360 });
}

function mirror(ed) {
  if (!ed.writes || !ed.b.has.has("mirror")) return;
  setEdit(ed, { mirror: !mirrored(f(ed)) });
}

/** A new layer on top of the others, chosen. */
function addLayer(ed, fields, then = null) {
  if (!ed.writesLayers) return;
  const record = { [ed.b.layerEdit]: ed.id, order: topOrder(ed.layers), ...fields };
  write(ed, async () => {
    const made = await api("POST", recordsUrl(ed.b.layers.id), { fields: record });
    ed.layers.push(layerFrom(made));
    ed.selected = made.id;
    paint(ed);
    drawSide(ed);
    if (then) then(made);
  });
}

/** Words on the picture — where it was pressed, or in a corner — picked,
    the panel ready to take them, and the tool back to Select: the next
    press moves or sizes them, or picks something else, rather than laying
    more words. */
function addText(ed, at = null) {
  if (!ed.writesLayers) return;
  const where = at ? { x: r2(at.x), y: r2(at.y) } : { x: TEXT_AT.x, y: clamp(TEXT_AT.y + ed.layers.length * TEXT_SIZE * 1.4, 0, 90) };
  addLayer(ed, { kind: "text", text: NEW_WORDS, ...where, size: TEXT_SIZE, colour: TEXT_COLOUR }, () => {
    if (ed.tool !== HOME) setTool(ed, HOME);
    const words = ed.root.querySelector(".ph-words");
    if (words) { words.focus(); words.select(); }
  });
}

function setLayer(ed, layer, fields) {
  Object.assign(layer, layerOf({ ...layer, ...fields }));
  paint(ed);
  write(ed, () => patch(ed.b.layers.id, layer.id, fields));
}

function removeLayer(ed, layer) {
  if (!layer || !ed.writesLayers) return;
  ed.layers = ed.layers.filter((l) => l.id !== layer.id);
  if (ed.selected === layer.id) ed.selected = "";
  paint(ed);
  drawSide(ed);
  write(ed, () => api("DELETE", recordsUrl(ed.b.layers.id, layer.id)));
}

/** The fields a layer is made of, for Copy and Duplicate. */
function fieldsOf(layer) {
  const base = { kind: layer.kind, x: layer.x, y: layer.y, colour: layer.colour };
  if (layer.kind === "text") return { ...base, text: layer.text, size: layer.size };
  if (layer.kind === "mark") return { ...base, points: layer.points, width: layer.width, opacity: layer.opacity };
  return { ...base, w: layer.w, h: layer.h, source: layer.source };
}

/** A layer a little to the side of *layer*: Duplicate, and Paste of a copied layer. */
function copyOf(fields, by = 3) {
  const moved = { ...fields, x: clamp(fields.x + by, 0, 100), y: clamp(fields.y + by, 0, 100) };
  if (fields.kind === "mark") moved.points = movedMark({ points: fields.points }, by, by);
  return moved;
}

function copySelection(ed) {
  if (ed.selection) {
    clipboard = { kind: "region", box: { ...ed.selection } };
    toast("Copied: Paste puts it on the picture as a piece");
    return;
  }
  const layer = chosen(ed);
  if (!layer) { toast("Select a part of the picture, or a layer, first"); return; }
  clipboard = { kind: "layer", fields: fieldsOf(layer) };
  toast(`Copied the ${layerLabel(layer).toLowerCase()}`);
}

function paste(ed) {
  if (!ed.writesLayers) return;
  if (!clipboard) { toast("Nothing copied yet: Select a part of the picture and Copy it"); return; }
  if (clipboard.kind === "region") {
    const b = clipboard.box;
    addLayer(ed, { kind: "piece", source: { ...b }, x: clamp(b.x + 3, 0, 100 - b.w), y: clamp(b.y + 3, 0, 100 - b.h), w: b.w, h: b.h, colour: TEXT_COLOUR });
  } else {
    addLayer(ed, copyOf(clipboard.fields));
  }
  if (ed.tool !== HOME) setTool(ed, HOME);
}

function duplicate(ed, layer) {
  if (!layer) return;
  addLayer(ed, copyOf(fieldsOf(layer)));
}

/** The chosen layer one step up or down the stack: every layer's `order` is its place, written where it changed. */
function restack(ed, layer, by) {
  const index = ed.layers.indexOf(layer);
  const to = index + by;
  if (index < 0 || to < 0 || to >= ed.layers.length) return;
  ed.layers.splice(index, 1);
  ed.layers.splice(to, 0, layer);
  const changes = [];
  ed.layers.forEach((l, i) => { if (l.order !== i) { l.order = i; changes.push([l.id, i]); } });
  paint(ed);
  drawSide(ed);
  write(ed, async () => { for (const [id, order] of changes) await patch(ed.b.layers.id, id, { order }); });
}

// -- the buttons and the keys ----------------------------------------------------------------------
function drawTools(ed) {
  const mirrorButton = ed.root.querySelector(".ph-mirror");
  mirrorButton.classList.toggle("on", mirrored(f(ed)));
  mirrorButton.setAttribute("aria-pressed", String(mirrored(f(ed))));
}

function wireTools(ed) {
  for (const button of ed.root.querySelectorAll(".ph-tool[data-tool]")) {
    button.addEventListener("click", () => setTool(ed, button.dataset.tool));
  }
  for (const button of ed.root.querySelectorAll("[data-turn]")) {
    button.addEventListener("click", () => turn(ed, Number(button.dataset.turn)));
  }
  ed.root.querySelector(".ph-mirror").addEventListener("click", () => mirror(ed));
  const pasteButton = ed.root.querySelector(".ph-paste");
  if (pasteButton) pasteButton.addEventListener("click", () => paste(ed));
  ed.over.dataset.tool = ed.tool;
}

function wireKeys(ed) {
  ed.onKey = (event) => {
    if (!ed.alive || event.defaultPrevented || event.altKey) return;
    const target = event.target;
    if (target.closest && target.closest("input, textarea, select, [contenteditable]")) return;
    if (document.querySelector(".sheet-backdrop")) return;
    const layer = chosen(ed);
    if (event.metaKey || event.ctrlKey) {
      const combos = {
        c: () => copySelection(ed),
        v: () => paste(ed),
        d: () => duplicate(ed, layer),
        s: () => { if (ed.b.saveAction) saveSheet(ed); },
      };
      const run = combos[event.key.toLowerCase()];
      if (!run) return;
      event.preventDefault();
      run();
      return;
    }
    const keys = {
      v: () => setTool(ed, "select"),
      g: () => setTool(ed, "move"),
      m: () => setTool(ed, "marquee"),
      c: () => setTool(ed, "crop"),
      t: () => setTool(ed, "text"),
      b: () => setTool(ed, "marker"),
      r: () => turn(ed, 90),
      R: () => turn(ed, -90),
      h: () => layer && setLayer(ed, layer, { hidden: !layer.hidden }),
      Delete: () => removeLayer(ed, layer),
      Backspace: () => removeLayer(ed, layer),
      Escape: () => { if (ed.tool !== HOME) setTool(ed, HOME); else choose(ed, ""); },
    };
    const run = keys[event.key];
    if (!run) return;
    event.preventDefault();
    run();
  };
  addEventListener("keydown", ed.onKey);
}

// -- the bar: resize, save, export, and how it is going --------------------------------------------
function drawHeader(ed) {
  const bar = ed.root.querySelector(".ph-bar .ph-status");
  const buttons = ed.root.querySelector(".ph-bar-actions");
  const fields = f(ed);
  const status = ed.b.has.has("status") ? String(fields.status || "") : "";
  const tone = TONES[status] || "";
  const message = ed.b.has.has("message") ? String(fields.message || "") : "";
  const shownStatus = status && status !== "editing" ? status[0].toUpperCase() + status.slice(1) : "";
  const output = ed.b.has.has("output") && fields.output ? String(fields.output) : "";
  const busy = BUSY.has(status);
  bar.className = `ph-status${tone ? " tone-" + tone : ""}`;
  bar.innerHTML = `${busy ? '<i class="ph-spin"></i>' : ""}${esc(shownStatus)}${shownStatus && message ? " · " : ""}${esc(message)}`;
  const resizes = ed.b.has.has("out_width") && ed.b.has.has("out_height");
  buttons.innerHTML =
    (resizes ? `<button type="button" class="act-button ph-resize"${ed.writes ? "" : " disabled"}>${glyphs.resize}<span>Resize</span></button>` : "") +
    (output ? `<button type="button" class="act-button ph-open">Open</button>` : "") +
    (ed.b.exportAction ? `<button type="button" class="act-button ph-export"${busy ? " disabled" : ""}>${esc(ed.b.exportAction.label)}</button>` : "") +
    (ed.b.saveAction ? `<button type="button" class="act-button primary ph-save"${busy || !ed.writes ? " disabled" : ""}>${esc(ed.b.saveAction.label)}</button>` : "");
  const resize = buttons.querySelector(".ph-resize");
  if (resize) resize.addEventListener("click", () => resizeSheet(ed));
  const open = buttons.querySelector(".ph-open");
  if (open) open.addEventListener("click", () => openOutput(ed, output));
  const exportButton = buttons.querySelector(".ph-export");
  if (exportButton) {
    exportButton.addEventListener("click", () => {
      press(ed.at.quill, ed.b.exportAction, { record: ed.id, here: { quill: ed.at.quill, screen: ed.at.screen }, after: () => refreshEdit(ed) });
    });
  }
  const saveButton = buttons.querySelector(".ph-save");
  if (saveButton) saveButton.addEventListener("click", () => saveSheet(ed));
}

/** Resize: what the saved picture will be — the usual sizes, or a width and
    a height typed — in a sheet; each choice is written as it is made. */
function resizeSheet(ed) {
  if (!ed.writes || !ed.b.has.has("out_width")) return;
  const { sheet, close } = openSheet(`<div class="ph-resize-sheet">
      <p class="act-sheet-title">Resize</p>
      <div class="ph-resize-body"></div>
      <p class="ph-quiet">One of them keeps the shape; both are taken as typed. The picture itself is not touched until you save.</p>
      <div class="act-buttons"><button type="button" class="act-button primary" data-done>Done</button></div>
    </div>`, "act-form-sheet");
  const body = sheet.querySelector(".ph-resize-body");
  const fill = () => {
    const fields = f(ed);
    const cropped = croppedSize(fields);
    const out = outputSize(fields);
    const same = (size) => !!size && Number(size.out_width || 0) === Number(fields.out_width || 0) &&
      Number(size.out_height || 0) === Number(fields.out_height || 0);
    const chips = SIZES.map(([value, label]) =>
      `<button type="button" class="act-chip ph-size-chip${same(sizeFrom(value, cropped)) ? " on" : ""}" data-size-pick="${esc(value)}">${esc(label)}</button>`).join("");
    body.innerHTML = `<p class="ph-size-now">${out
      ? `<b>${out.w} × ${out.h}</b> pixels${cropped && (out.w !== cropped.w || out.h !== cropped.h) ? ` <span class="ph-quiet-inline">from ${cropped.w} × ${cropped.h}</span>` : ""}`
      : `<span class="ph-quiet-inline">The photo's size is not known yet.</span>`}</p>
      <div class="ph-chips">${chips}</div>
      <div class="ph-size-fields">
        ${number("Width", 'data-size="out_width"', esc(String(fields.out_width || "")), `min="1" max="8192" placeholder="${cropped ? cropped.w : ""}"`)}
        ${number("Height", 'data-size="out_height"', esc(String(fields.out_height || "")), `min="1" max="8192" placeholder="${cropped ? cropped.h : ""}"`)}
      </div>`;
    for (const chip of body.querySelectorAll("[data-size-pick]")) {
      chip.addEventListener("click", () => {
        const value = chip.dataset.sizePick;
        const size = value ? sizeFrom(value, croppedSize(f(ed))) : { out_width: null, out_height: null };
        if (!size) { toast("The photo's size is not known yet"); return; }
        setEdit(ed, size);
        fill();
      });
    }
    for (const input of body.querySelectorAll("[data-size]")) {
      input.addEventListener("change", () => {
        const value = input.value.trim() ? clamp(Math.round(Number(input.value)), 1, 8192) : null;
        setEdit(ed, { [input.dataset.size]: value });
        fill();
      });
    }
  };
  fill();
  sheet.querySelector("[data-done]").addEventListener("click", close);
}

/** Save: over the photo, or as a new file beside it, by name. The action is
    pressed with `overwrite` and `name` answered, so no form opens. */
function saveSheet(ed) {
  const action = ed.b.saveAction;
  if (!action || !ed.writes) return;
  const photoName = ed.sourceFile ? String(ed.sourceFile.fields.name || "") : "the photo";
  const dot = photoName.lastIndexOf(".");
  const stem = dot > 0 ? photoName.slice(0, dot) : photoName;
  const suffix = dot > 0 ? photoName.slice(dot) : "";
  const { sheet, close } = openSheet(
    `<form class="act-form ph-save-sheet" novalidate>
      <p class="act-sheet-title">Save ${esc(String(f(ed).name || "").trim() || "the picture")}</p>
      <p class="act-description">Write over <b>${esc(photoName)}</b>, or save as a new file beside it. The photo as it was goes to the Trash when you write over it.</p>
      <div class="ph-save-choices">
        <button type="button" class="act-button primary" data-save="overwrite">Overwrite ${esc(photoName)}</button>
        <button type="button" class="act-button" data-save="as">Save as…</button>
      </div>
      <div class="group fields ph-save-as" hidden>
        <label class="row field kind-string"><span class="main">Name</span>
          <input type="text" data-field="name" aria-label="Name" value="${esc(stem + " edited" + suffix)}" autocapitalize="sentences" enterkeyhint="go"></label>
      </div>
      <p class="act-error" role="alert" hidden></p>
      <div class="act-buttons"><button type="button" class="act-button" data-cancel>Cancel</button>
        <button type="submit" class="act-button primary ph-save-go" hidden>Save</button></div>
    </form>`, "act-form-sheet");
  const form = sheet.querySelector("form");
  const errorEl = form.querySelector(".act-error");
  const showError = (text) => { errorEl.textContent = text; errorEl.hidden = !text; };
  const run = async (args) => {
    for (const button of form.querySelectorAll("button")) button.disabled = true;
    try {
      await press(ed.at.quill, action, { record: ed.id, args, here: { quill: ed.at.quill, screen: ed.at.screen }, after: () => refreshEdit(ed) });
      close();
    } catch (err) {
      for (const button of form.querySelectorAll("button")) button.disabled = false;
      showError(said(err));
    }
  };
  form.querySelector("[data-cancel]").addEventListener("click", close);
  form.querySelector('[data-save="overwrite"]').addEventListener("click", () => run({ overwrite: true, name: photoName }));
  form.querySelector('[data-save="as"]').addEventListener("click", () => {
    form.querySelector(".ph-save-as").hidden = false;
    form.querySelector(".ph-save-go").hidden = false;
    form.querySelector(".ph-save-choices").hidden = true;
    const input = form.querySelector('[data-field="name"]');
    input.focus();
    input.setSelectionRange(0, stem.length + " edited".length);
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const name = form.querySelector('[data-field="name"]').value.trim();
    if (!name) { showError("Give the file a name"); return; }
    run({ overwrite: false, name });
  });
}

/** The edit's status, message and output as they are now; asked again every
    few seconds while a save is on its way. Done, the picture may have
    changed under the edit (written over): everything is read again. */
async function refreshEdit(ed) {
  if (!ed.alive) return;
  try {
    const edit = await api("GET", recordsUrl(ed.b.model.id, ed.id));
    if (!ed.alive) return;
    const wasBusy = BUSY.has(String(f(ed).status || ""));
    const nowBusy = BUSY.has(String(edit.fields.status || ""));
    for (const name of ["status", "message", "output"]) ed.edit.fields[name] = edit.fields[name];
    drawHeader(ed);
    if (wasBusy && !nowBusy && String(edit.fields.status) === "done") {
      // Written over, the photo is new: its large copy and the edit's numbers both.
      thumbs.delete(`${f(ed).source}/${LARGE}`);
      thumbs.delete(`${f(ed).source}/128`);
      ed.turnedKey = "";
      await reload(ed);
      await loadPicture(ed);
    }
  } catch { /* asked again on the next round */ }
  watchExport(ed);
}

function watchExport(ed) {
  clearTimeout(ed.pollTimer);
  if (!ed.alive || !BUSY.has(String(f(ed).status || ""))) return;
  ed.pollTimer = setTimeout(() => refreshEdit(ed), POLL);
}

// The saved file is a file record: fetched through a media link, saved as itself.
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
    toast(err.status === 404 ? "The saved file is not there any more" : said(err));
  }
}

// -- the panels beside the picture ------------------------------------------------------------------
function drawSide(ed) {
  const side = ed.root.querySelector(".ph-side");
  // Not while something in it is being typed in: it is drawn after.
  if (side.contains(document.activeElement) && document.activeElement.matches("input, textarea")) {
    ed.sideStale = true;
    return;
  }
  const layer = chosen(ed);
  side.querySelector(".ph-options").innerHTML = optionsPanel(ed, layer);
  side.querySelector(".ph-layers").innerHTML = layersPanel(ed);
  ed.sideStale = false;
  wireSide(ed, side, layer);
}

const field = (label, inner) => `<label class="ph-field"><span>${label}</span>${inner}</label>`;
const number = (label, data, value, more = "") =>
  `<label class="ph-field small"><span>${label}</span><input type="number" ${data} value="${value}" ${more}></label>`;

/** What the tool does, and the chosen layer's own numbers. */
function optionsPanel(ed, layer) {
  const title = TOOLS.find(([id]) => id === ed.tool)[1];
  let body = "";
  if (ed.tool === "crop") body = cropOptions(ed);
  else if (ed.tool === "marquee") body = selectOptions(ed);
  else if (ed.tool === "marker") body = markerOptions();
  else if (ed.tool === "text" && !layer) {
    body = `<p class="ph-quiet">Press on the picture to put words there.</p>
      ${ed.writesLayers ? `<div class="ph-row-buttons"><button type="button" class="act-chip ph-add-text">${glyphs.text}<span>Add text</span></button></div>` : ""}`;
  }
  if (layer && ed.tool !== "crop" && ed.tool !== "marquee") body += layerOptions(ed, layer);
  if (!body) body = `<p class="ph-quiet">Press a layer on the picture, or pick one in Layers.</p>`;
  return `<p class="group-label">${esc(title)}</p>${body}`;
}

function cropOptions(ed) {
  const c = crop(ed);
  const size = croppedSize(f(ed));
  const ratios = RATIOS.map(([value, label]) =>
    `<button type="button" class="act-chip ph-ratio${value === ed.ratio ? " on" : ""}" data-ratio="${esc(value)}" aria-pressed="${value === ed.ratio}">${esc(label)}</button>`).join("");
  const dis = ed.writes ? "" : "disabled";
  return `<div class="ph-chips">${ratios}</div>
    <div class="ph-crop-fields">${number("Left", 'data-crop="x"', Math.round(c.x * 10) / 10, `min="0" max="100" step="0.5" ${dis}`)}${number("Top", 'data-crop="y"', Math.round(c.y * 10) / 10, `min="0" max="100" step="0.5" ${dis}`)}${number("Width", 'data-crop="w"', Math.round(c.w * 10) / 10, `min="5" max="100" step="0.5" ${dis}`)}${number("Height", 'data-crop="h"', Math.round(c.h * 10) / 10, `min="5" max="100" step="0.5" ${dis}`)}</div>
    <p class="ph-quiet">Percent of the picture.${size ? ` Kept: ${size.w} × ${size.h} pixels.` : ""}</p>
    <div class="ph-row-buttons">${ed.writes && !wholeFrame(c) ? `<button type="button" class="act-chip ph-crop-reset">Keep all of it</button>` : ""}
      <button type="button" class="act-chip primary ph-crop-done">Done</button></div>`;
}

function selectOptions(ed) {
  const s = ed.selection;
  if (!s) return `<p class="ph-quiet">Drag a box on the picture. Then copy what is in it, or crop to it.</p>`;
  const pic = picture(ed);
  return `<p class="ph-quiet">${Math.round(s.w / 100 * pic.w)} × ${Math.round(s.h / 100 * pic.h)} pixels, from ${Math.round(s.x)}%, ${Math.round(s.y)}%.</p>
    <div class="ph-row-buttons">
      <button type="button" class="act-chip ph-copy">${glyphs.copy}<span>Copy</span></button>
      ${ed.writesLayers ? `<button type="button" class="act-chip ph-copy-paste">${glyphs.paste}<span>Copy and paste</span></button>` : ""}
      ${ed.writes ? `<button type="button" class="act-chip ph-crop-to">${glyphs.crop}<span>Crop to it</span></button>` : ""}
      <button type="button" class="act-chip ph-unselect">Clear</button></div>`;
}

const swatches = (current, cls) => COLOURS.map(([name, hex]) =>
  `<button type="button" class="ph-swatch ${cls}${hex === current ? " on" : ""}" data-colour="${hex}" style="--swatch:${hex}" aria-label="${esc(name)}" title="${esc(name)}"></button>`).join("");

function markerOptions() {
  const widths = MARK_WIDTHS.map(([name, value]) =>
    `<button type="button" class="act-chip ph-mark-width${value === marker.width ? " on" : ""}" data-width="${value}">${name[0].toUpperCase() + name.slice(1)}</button>`).join("");
  const solid = marker.opacity >= 0.99;
  return `<div class="ph-field"><span>Colour</span><div class="ph-swatches">${swatches(marker.colour, "ph-marker-colour")}<input type="color" class="ph-marker-custom" value="${marker.colour}" aria-label="Another colour"></div></div>
    <div class="ph-field"><span>Width</span><div class="ph-chips">${widths}</div></div>
    <div class="ph-field"><span>Style</span><div class="ph-chips">
      <button type="button" class="act-chip ph-mark-style${solid ? " on" : ""}" data-opacity="${MARK_OPACITY}">Pen</button>
      <button type="button" class="act-chip ph-mark-style${solid ? "" : " on"}" data-opacity="${HIGHLIGHT_OPACITY}">Highlighter</button></div></div>
    <p class="ph-quiet">Draw on the picture. Each stroke is a layer: move it with the Move tool, or take it off.</p>`;
}

/** The chosen layer's own numbers, by its kind. */
function layerOptions(ed, layer) {
  const dis = ed.writesLayers ? "" : "disabled";
  let own = "";
  if (layer.kind === "text") {
    own = `<textarea class="ph-words" rows="2" aria-label="The words" placeholder="The words" ${dis}>${esc(layer.text)}</textarea>
      ${field("Size", `<input type="range" class="ph-text-size" min="1" max="40" step="0.5" value="${layer.size}" ${dis}><output>${layer.size}%</output>`)}
      <div class="ph-field"><span>Colour</span><div class="ph-swatches">${swatches(layer.colour, "ph-layer-colour")}<input type="color" class="ph-layer-custom" value="${esc(layer.colour)}" aria-label="Another colour" ${dis}></div></div>`;
  } else if (layer.kind === "mark") {
    own = `<div class="ph-field"><span>Colour</span><div class="ph-swatches">${swatches(layer.colour, "ph-layer-colour")}<input type="color" class="ph-layer-custom" value="${esc(layer.colour)}" aria-label="Another colour" ${dis}></div></div>
      ${field("Width", `<input type="range" class="ph-mark-w" min="0.2" max="12" step="0.1" value="${layer.width}" ${dis}><output>${layer.width}%</output>`)}
      ${field("Solid", `<input type="range" class="ph-mark-o" min="0.1" max="1" step="0.05" value="${layer.opacity}" ${dis}><output>${Math.round(layer.opacity * 100)}%</output>`)}`;
  } else {
    own = `<div class="ph-crop-fields">${number("Width", 'data-at="w"', Math.round(layer.w * 10) / 10, `min="0.5" max="100" step="0.5" ${dis}`)}${number("Height", 'data-at="h"', Math.round(layer.h * 10) / 10, `min="0.5" max="100" step="0.5" ${dis}`)}</div>
      <p class="ph-quiet">A piece of the picture, from ${Math.round(layer.source.x)}%, ${Math.round(layer.source.y)}%. Drag it, pull its corners.</p>`;
  }
  return `<div class="group ph-card">${own}
      <div class="ph-crop-fields">${number("Left", 'data-at="x"', Math.round(layer.x * 10) / 10, `min="0" max="100" step="0.5" ${dis}`)}${number("Top", 'data-at="y"', Math.round(layer.y * 10) / 10, `min="0" max="100" step="0.5" ${dis}`)}</div>
    </div>
    <div class="ph-row-buttons">
      ${ed.writesLayers ? `<button type="button" class="act-chip ph-duplicate">${glyphs.copy}<span>Duplicate</span></button>
      <button type="button" class="act-chip ph-hide">${layer.hidden ? glyphs.eyeOff : glyphs.eye}<span>${layer.hidden ? "Show" : "Hide"}</span></button>
      <button type="button" class="act-chip ph-drop-layer">${icons.trash}<span>Remove</span></button>` : ""}
    </div>`;
}

/** Every layer, the top one first, with its eye; the chosen one lit. */
function layersPanel(ed) {
  if (!ed.b.layers) return "";
  const glyphFor = { text: glyphs.text, mark: glyphs.marker, piece: glyphs.piece };
  const rows = [...ed.layers].reverse().map((layer) => {
    const on = layer.id === ed.selected;
    return `<div class="ph-layer${on ? " on" : ""}${layer.hidden ? " hidden" : ""}" data-layer="${esc(layer.id)}">
      <button type="button" class="ph-layer-eye" aria-label="${layer.hidden ? "Show" : "Hide"}" title="${layer.hidden ? "Show" : "Hide"}"${ed.writesLayers ? "" : " disabled"}>${layer.hidden ? glyphs.eyeOff : glyphs.eye}</button>
      <button type="button" class="ph-layer-pick"><span class="ph-layer-kind" style="--swatch:${esc(layer.colour)}">${glyphFor[layer.kind]}</span><span class="ph-layer-name">${esc(layerLabel(layer))}</span></button>
      ${on && ed.writesLayers ? `<button type="button" class="ph-layer-move" data-by="1" aria-label="Up" title="Bring forward">${glyphs.up}</button>
      <button type="button" class="ph-layer-move" data-by="-1" aria-label="Down" title="Send back">${glyphs.down}</button>
      <button type="button" class="ph-layer-drop" aria-label="Remove" title="Remove">${glyphs.close}</button>` : ""}
    </div>`;
  }).join("");
  return `<p class="group-label">Layers <span class="ph-count">${ed.layers.length || ""}</span></p>
    <div class="ph-layer-list">${rows || `<p class="ph-quiet">Nothing on the picture yet: words, marker strokes and pasted pieces land here.</p>`}</div>`;
}

function wireSide(ed, side, layer) {
  const on = (selector, type, fn) => { for (const el of side.querySelectorAll(selector)) el.addEventListener(type, fn); };
  // Crop.
  on(".ph-crop-done", "click", () => setTool(ed, HOME));
  on(".ph-crop-reset", "click", () => saveCrop(ed, { x: 0, y: 0, w: 100, h: 100 }));
  on(".ph-ratio", "click", (event) => {
    ed.ratio = event.currentTarget.dataset.ratio;
    const ratio = ratioOf(ed.ratio);
    if (ratio && ed.writes) saveCrop(ed, boxWithRatio(crop(ed), ratio, picture(ed)));
    else drawSide(ed);
  });
  on("[data-crop]", "change", (event) => {
    const input = event.currentTarget;
    const box = { ...crop(ed), [input.dataset.crop]: Number(input.value) || 0 };
    input.blur();
    saveCrop(ed, fitBox(box, 5));
  });
  // Select.
  on(".ph-copy", "click", () => copySelection(ed));
  on(".ph-copy-paste", "click", () => { copySelection(ed); paste(ed); });
  on(".ph-crop-to", "click", () => { if (ed.selection) { saveCrop(ed, fitBox(ed.selection, 5)); ed.selection = null; setTool(ed, HOME); } });
  on(".ph-unselect", "click", () => { ed.selection = null; placeOverlay(ed); drawSide(ed); });
  // Marker.
  on(".ph-marker-colour", "click", (event) => { marker.colour = event.currentTarget.dataset.colour; drawSide(ed); });
  on(".ph-marker-custom", "change", (event) => { marker.colour = colourFrom(event.target.value) || marker.colour; drawSide(ed); });
  on(".ph-mark-width", "click", (event) => { marker.width = Number(event.currentTarget.dataset.width); drawSide(ed); });
  on(".ph-mark-style", "click", (event) => { marker.opacity = Number(event.currentTarget.dataset.opacity); drawSide(ed); });
  // Text.
  on(".ph-add-text", "click", () => addText(ed));
  // The chosen layer.
  if (layer) {
    const words = side.querySelector(".ph-words");
    if (words) {
      words.addEventListener("input", () => { layer.text = words.value; paint(ed); });
      words.addEventListener("change", () => setLayer(ed, layer, { text: words.value }));
    }
    on(".ph-text-size", "input", (event) => {
      layer.size = Number(event.target.value);
      event.target.nextElementSibling.textContent = `${event.target.value}%`;
      paint(ed);
    });
    on(".ph-text-size", "change", (event) => setLayer(ed, layer, { size: Number(event.target.value) }));
    on(".ph-mark-w", "input", (event) => { layer.width = Number(event.target.value); event.target.nextElementSibling.textContent = `${event.target.value}%`; paint(ed); });
    on(".ph-mark-w", "change", (event) => setLayer(ed, layer, { width: Number(event.target.value) }));
    on(".ph-mark-o", "input", (event) => { layer.opacity = Number(event.target.value); event.target.nextElementSibling.textContent = `${Math.round(event.target.value * 100)}%`; paint(ed); });
    on(".ph-mark-o", "change", (event) => setLayer(ed, layer, { opacity: Number(event.target.value) }));
    on(".ph-layer-colour", "click", (event) => { setLayer(ed, layer, { colour: event.currentTarget.dataset.colour }); drawSide(ed); });
    on(".ph-layer-custom", "input", (event) => { layer.colour = colourFrom(event.target.value) || layer.colour; paint(ed); });
    on(".ph-layer-custom", "change", (event) => { setLayer(ed, layer, { colour: colourFrom(event.target.value) || TEXT_COLOUR }); drawSide(ed); });
    on("[data-at]", "change", (event) => {
      const input = event.currentTarget;
      input.blur();
      setLayer(ed, layer, { [input.dataset.at]: clamp(Number(input.value) || 0, 0, 100) });
      placeOverlay(ed);
    });
    on(".ph-duplicate", "click", () => duplicate(ed, layer));
    on(".ph-hide", "click", () => { setLayer(ed, layer, { hidden: !layer.hidden }); placeOverlay(ed); drawSide(ed); });
    on(".ph-drop-layer", "click", () => removeLayer(ed, layer));
  }
  // Layers.
  for (const row of side.querySelectorAll(".ph-layer")) {
    const id = row.dataset.layer;
    const it = layerById(ed, id);
    row.querySelector(".ph-layer-pick").addEventListener("click", () => {
      if (ed.tool === "crop" || ed.tool === "marquee") setTool(ed, HOME);
      choose(ed, ed.selected === id ? "" : id);
    });
    row.querySelector(".ph-layer-eye").addEventListener("click", () => { if (it) { setLayer(ed, it, { hidden: !it.hidden }); placeOverlay(ed); drawSide(ed); } });
    for (const move of row.querySelectorAll(".ph-layer-move")) move.addEventListener("click", () => restack(ed, it, Number(move.dataset.by)));
    const drop = row.querySelector(".ph-layer-drop");
    if (drop) drop.addEventListener("click", () => removeLayer(ed, it));
  }
  // Drawn again once the typing is over, if something changed while it went on.
  side.addEventListener("focusout", () => { if (ed.sideStale) setTimeout(() => ed.alive && drawSide(ed), 0); }, { once: true });
}
