/* The kit's `photo`: a photo editor, drawn from the screen's bindings alone.

   A photo screen names a datamodel with the kit's own field names
   (docs/PHOTO.md): the edit (`model`) — one picture from the drive, how it
   is turned and mirrored, the part of it kept, and the size it comes out —
   and, optionally, the words laid on it (`texts`); where the photos are
   (`media`, a filter on the drive's file records); and, optionally, a
   pictures API and an export action.

     #/q/<quill>/<screen>          the edits, newest first, with New
     #/q/<quill>/<screen>/<id>     one edit in the editor
     #/q/<quill>/<screen>/edit=<id>   the same, as a Quill's `go` says it

   The editor is the picture, with buttons under it and panels beside it.
   The picture is a canvas the source is drawn on, turned and mirrored as
   the edit says, with every text drawn in its place in the app's own
   font, and the crop either kept to or — while cropping — shown as a box
   to move, the rest dimmed. A text is picked by pressing it, dragged to
   where it should be, and made bigger or smaller by its corner; its words
   and colour are in the panel. The size panel says what the export will
   be, and offers the usual ones. Export is the Quill's action, and the
   header says how it is going.

   The source is drawn from the server's large copy of it (`/thumb`), so a
   phone's photo comes quickly and a HEIC needs no plug-in here; its true
   size is read from the pictures API, or from the file itself once. What
   changes is written as it changes, on the records API; when the server
   says no, the edit is read again and drawn as it is. The arithmetic — the
   turn, the crop, the export's size — is kit_photo_rules.js, the same
   rules the terminal has. */

import {
  api, apiRaw, app, esc, formatDate, go, heading, icons, mount, nav, occupy, pixelIcon, recordsUrl, replace,
  renderRoute, seconds, tabs, toast, vacate, wireShell,
} from "./core.js";
import { aOr, mayWrite, plural, sheetHash } from "./kit.js";
import { press, said } from "./actions.js";
import {
  boxWithRatio, clamp, COLOURS, colourFrom, cropOf, croppedSize, fitBox, isPhoto, mirrored, outputSize,
  pictureSize, picturesPath, RATIOS, ratioOf, rotationOf, SIZES, sizeFrom, sourceSize, TEXT_AT, TEXT_COLOUR,
  TEXT_SIZE, textLines, textOf, turned, wholeFrame,
} from "./kit_photo_rules.js";

const glyphs = {
  left: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9.5a6 6 0 1 1 1.8 4.3"/><path d="M4 5v4.5h4.5"/></svg>',
  right: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M16 9.5a6 6 0 1 0-1.8 4.3"/><path d="M16 5v4.5h-4.5"/></svg>',
  mirror: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 2v16"/><path d="M7 5 2.5 10 7 15zM13 5l4.5 5-4.5 5z"/></svg>',
  crop: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M5 1.5V15h13.5M1.5 5H15v13.5"/></svg>',
  text: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5.5V3h12v2.5M10 3v14M7.5 17h5"/></svg>',
  photo: '<svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="2" y="3" width="16" height="14" rx="2"/><circle cx="7" cy="8" r="1.6"/><path d="m2.5 15 4.5-4.5 3 3 3-3 4.5 4.5"/></svg>',
  close: '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m2.5 2.5 7 7M9.5 2.5l-7 7"/></svg>',
};
// How big a tile's picture is asked for, and the picture that is edited.
const TILE = 256;
const LARGE = 2048;
// How a status is toned beside Export; anything else is said plainly.
const TONES = { queued: "info", rendering: "info", done: "good", failed: "bad" };
const BUSY = new Set(["queued", "rendering"]);
const POLL = 3000;
const WIDEST = 2048;             // the most pixels across the canvas draws
const NEW_WORDS = "Your words";  // what a new text says until it is written

// -- the screen's bindings ---------------------------------------------------------------
const linkTo = (model, to) => {
  const links = (model ? model.fields : []).filter((f) => f.kind === "link" && f.to === to);
  return links.length === 1 ? links[0].name : "";
};

/** What a photo editor is drawn from, read out of its bindings once. */
export function bindingsOf(at) {
  const { quill, screen } = at;
  const model = quill.models[screen.model];
  const texts = screen.texts ? quill.models[screen.texts] || null : null;
  const files = quill.models.file || null;
  return {
    model,
    title: screen.title || model.title,
    has: new Set(model.fields.map((f) => f.name)),
    texts,
    files,
    textEdit: texts ? linkTo(texts, model.id) : "",
    media: screen.media || {},
    pictures: picturesPath(quill, screen),
    exportAction: screen.export ? (quill.actions || []).find((a) => a.id === screen.export) || null : null,
  };
}

/** What the record sheet does for an edit: back to its editor, not to the list. */
export function photoSheet(at, model) {
  if (model.id !== at.screen.model) return null;
  return { parent: (record) => `${at.base}/${encodeURIComponent(record.id)}` };
}

const textFrom = (record) => ({ id: record.id, record, ...textOf(record.fields) });

let live = null;   // the editor on the page, while there is one

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
  const [edit, texts] = await Promise.all([
    api("GET", recordsUrl(b.model.id, id)),
    b.texts ? api("GET", recordsUrl(b.texts.id) + `?${encodeURIComponent(b.textEdit)}=${encodeURIComponent(id)}`) : Promise.resolve([]),
  ]);
  texts.sort((x, y) => String(x.created_at || "").localeCompare(String(y.created_at || "")));
  return { edit, texts: texts.map(textFrom) };
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
    imageProblem: "",            // or why there is none
    cropping: false, ratio: "",
    selected: "",                // the text being worked on
    dirty: true, alive: true, writing: Promise.resolve(),
    writes: mayWrite(b.model),
    writesTexts: !!b.texts && mayWrite(b.texts),
    boxes: [],                   // where each text is on the picture, in percent, as last drawn
  };
  if (live) live.stop();
  live = ed;
  ed.stop = () => stopEditor(ed);
  const hold = { stays: () => false, leave: async () => { ed.stop(); vacate(hold); }, flush: () => {} };
  occupy(hold);

  const title = String(ed.edit.fields[b.title] || "").trim() || "Untitled";
  mount(nav({ back: at.base, backLabel: at.screen.label, title }) + `
    <main class="kit-photo">
      ${heading(title, `<span class="ph-head-actions"></span><a class="button ph-settings" href="${sheetHash(at, b.model.id, id)}" aria-label="${esc(b.model.label)} settings" title="${esc(b.model.label)} settings">${pixelIcon("settings")}</a>`)}
      <div class="ph-headbar" role="status"></div>
      <div class="ph-desk">
        <section class="ph-viewer">
          <div class="ph-stage-box"><div class="ph-stage">
            <canvas aria-label="The picture as it will be"></canvas><div class="ph-over"></div>
            <p class="ph-stage-words" hidden></p>
          </div></div>
          <div class="ph-tools">
            <button type="button" data-turn="-90" aria-label="Turn left" title="Turn left (shift+R)"${ed.writes ? "" : " disabled"}>${glyphs.left}<span>Left</span></button>
            <button type="button" data-turn="90" aria-label="Turn right" title="Turn right (R)"${ed.writes ? "" : " disabled"}>${glyphs.right}<span>Right</span></button>
            <button type="button" class="ph-mirror" aria-pressed="false" aria-label="Mirror" title="Mirror (M)"${ed.writes ? "" : " disabled"}>${glyphs.mirror}<span>Mirror</span></button>
            <button type="button" class="ph-crop-toggle" aria-pressed="false" aria-label="Crop" title="Crop (C)">${glyphs.crop}<span>Crop</span></button>
            ${ed.writesTexts ? `<button type="button" class="ph-add-text" aria-label="Add text" title="Add text (T)">${glyphs.text}<span>Text</span></button>` : ""}
          </div>
        </section>
        <section class="ph-side" aria-label="The edit"></section>
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
}

function stopEditor(ed) {
  if (!ed.alive) return;
  ed.alive = false;
  clearTimeout(ed.pollTimer);
  if (ed.resize) ed.resize.disconnect();
  if (ed.onKey) removeEventListener("keydown", ed.onKey);
  if (ed.image) { if (ed.image.src.startsWith("blob:")) URL.revokeObjectURL(ed.image.src); ed.image = null; }
  closePhotoSheet();
  if (live === ed) live = null;
}

// -- what is where ------------------------------------------------------------------------------
const f = (ed) => ed.edit.fields;
const textById = (ed, id) => ed.texts.find((t) => t.id === id) || null;
const crop = (ed) => cropOf(f(ed).crop);
const viewOf = (ed) => (ed.cropping ? { x: 0, y: 0, w: 100, h: 100 } : crop(ed));
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
  if (!textById(ed, ed.selected)) ed.selected = "";
  ed.dirty = true;
  drawHeader(ed);
  drawTools(ed);
  drawSide(ed);
  fitStage(ed);
  paint(ed);
}

function setEdit(ed, fields) {
  Object.assign(ed.edit.fields, fields);
  ed.dirty = true;
  drawHeader(ed);
  drawTools(ed);
  drawSide(ed);
  fitStage(ed);
  paint(ed);
  write(ed, () => patch(ed.b.model.id, ed.id, fields));
}

// -- the source ----------------------------------------------------------------------------------
/** The server's large copy of the source, to draw; and its true size, when the edit has none. */
async function loadPicture(ed) {
  const source = String(f(ed).source || "");
  const words = ed.root.querySelector(".ph-stage-words");
  if (!source) {
    ed.imageProblem = "This edit has no photo.";
    words.textContent = ed.imageProblem;
    words.hidden = false;
    return;
  }
  const url = await thumbURL(source, LARGE);
  if (!ed.alive) return;
  if (!url) {
    ed.imageProblem = "The photo cannot be drawn here: the server could not read it as a picture.";
    words.textContent = ed.imageProblem;
    words.hidden = false;
  } else {
    const img = new Image();
    img.decoding = "async";
    await new Promise((resolve) => { img.onload = resolve; img.onerror = resolve; img.src = url; });
    if (!ed.alive) return;
    if (img.naturalWidth) {
      ed.image = img;
      words.hidden = true;
    } else {
      ed.imageProblem = "The photo cannot be drawn here.";
      words.textContent = ed.imageProblem;
      words.hidden = false;
    }
  }
  ed.dirty = true;
  fitStage(ed);
  paint(ed);
  if (!sourceSize(f(ed)) && ed.writes) fillSize(ed, source);
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
  const room = box.clientWidth;
  const tall = matchMedia("(min-width: 900px) and (min-height: 600px)").matches
    ? Math.min(innerHeight * 0.62, 760) : Math.min(innerHeight * 0.48, 480);
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
  ed.dirty = true;
}

/** The picture as the export will be: the source turned and mirrored,
    every text on it in its place, and the crop kept to — or, while
    cropping, the whole picture with the crop drawn over it. */
function paint(ed) {
  if (!ed.alive) return;
  const { ctx, canvas } = ed;
  const pic = picture(ed);
  const view = viewOf(ed);
  const s = canvas.width / (pic.w * view.w / 100);
  const ox = pic.w * view.x / 100;
  const oy = pic.h * view.y / 100;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.setTransform(s, 0, 0, s, -ox * s, -oy * s);
  if (ed.image) {
    const img = ed.image;
    const rotate = rotationOf(f(ed));
    const src = turned(pic.w, pic.h, rotate);   // the source's own shape, in picture pixels
    ctx.save();
    ctx.translate(pic.w / 2, pic.h / 2);
    if (mirrored(f(ed))) ctx.scale(-1, 1);
    ctx.rotate(rotate * Math.PI / 180);
    ctx.drawImage(img, -src.w / 2, -src.h / 2, src.w, src.h);
    ctx.restore();
  }
  ed.boxes = [];
  for (const text of ed.texts) {
    const { lines, px, lineHeight } = textLines(text, pic.h);
    ctx.font = `600 ${px}px Barlow, "Barlow Semi Condensed", sans-serif`;
    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    ctx.lineJoin = "round";
    ctx.lineWidth = Math.max(1, px * 0.08);
    ctx.strokeStyle = "rgba(0, 0, 0, .55)";
    ctx.fillStyle = text.colour;
    const x = text.x / 100 * pic.w;
    const y = text.y / 100 * pic.h;
    let widest = 0;
    lines.forEach((line, i) => {
      widest = Math.max(widest, ctx.measureText(line).width);
      ctx.strokeText(line, x, y + i * lineHeight);
      ctx.fillText(line, x, y + i * lineHeight);
    });
    ed.boxes.push({
      id: text.id,
      x: text.x,
      y: text.y,
      w: Math.max(widest, px * 0.6) / pic.w * 100,
      h: lines.length * lineHeight / pic.h * 100,
    });
  }
  ed.dirty = false;
  placeOverlay(ed);
}

// -- the boxes on the picture -------------------------------------------------------------------
const HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

/** The crop's box while cropping; otherwise a box per text, the chosen one with its corner. */
function placeOverlay(ed) {
  if (!ed.alive) return;
  const view = viewOf(ed);
  const at = (box) => `left:${(box.x - view.x) / view.w * 100}%;top:${(box.y - view.y) / view.h * 100}%;` +
    `width:${box.w / view.w * 100}%;height:${box.h / view.h * 100}%`;
  if (ed.cropping) {
    const box = crop(ed);
    ed.over.innerHTML = `<div class="ph-box crop" data-what="crop" style="${at(box)}">` +
      (ed.writes ? HANDLES.map((h) => `<i data-h="${h}"></i>`).join("") : "") + `</div>`;
    return;
  }
  ed.over.innerHTML = ed.boxes.map((box) => {
    const on = box.id === ed.selected;
    return `<div class="ph-box text${on ? " on" : ""}" data-what="text" data-text="${esc(box.id)}" style="${at(box)}">` +
      (on && ed.writesTexts ? `<i data-h="se"></i>` : "") + `</div>`;
  }).join("");
}

function wireOverlay(ed) {
  ed.over.addEventListener("pointerdown", (event) => {
    const el = event.target.closest(".ph-box");
    if (!el || event.button > 0) return;
    const what = el.dataset.what;
    if (what === "text" && el.dataset.text !== ed.selected) {
      choose(ed, el.dataset.text);
      // Chosen, and dragged in the same press: the box is drawn again, so hold the new one.
      const again = ed.over.querySelector(`.ph-box[data-text="${CSS.escape(el.dataset.text)}"]`);
      if (!again) return;
      return dragBox(ed, again, event);
    }
    dragBox(ed, el, event);
  });
}

function dragBox(ed, el, event) {
  const what = el.dataset.what;
  const may = what === "crop" ? ed.writes : ed.writesTexts;
  if (!may) return;
  event.preventDefault();
  el.setPointerCapture(event.pointerId);
  const handle = event.target.dataset.h || "";
  const rect = ed.stage.getBoundingClientRect();
  const view = viewOf(ed);
  const pic = picture(ed);
  const text = what === "text" ? textById(ed, el.dataset.text) : null;
  const box = what === "crop" ? crop(ed) : ed.boxes.find((b) => b.id === el.dataset.text);
  if (!box || (what === "text" && !text)) return;
  const start = { ...box };
  const was = text ? { x: text.x, y: text.y, size: text.size } : null;
  const x0 = event.clientX;
  const y0 = event.clientY;
  let last = null;
  const move = (e) => {
    const dx = (e.clientX - x0) / rect.width * view.w;
    const dy = (e.clientY - y0) / rect.height * view.h;
    if (what === "crop") {
      let b = { ...start };
      if (!handle) { b.x += dx; b.y += dy; }
      if (handle.includes("w")) { b.x += dx; b.w -= dx; }
      if (handle.includes("e")) b.w += dx;
      if (handle.includes("n")) { b.y += dy; b.h -= dy; }
      if (handle.includes("s")) b.h += dy;
      if (b.w < 0) { b.x += b.w; b.w = -b.w; }
      if (b.h < 0) { b.y += b.h; b.h = -b.h; }
      if (!handle) b = { ...b, x: clamp(b.x, 0, 100 - b.w), y: clamp(b.y, 0, 100 - b.h) };
      const ratio = ratioOf(ed.ratio);
      last = ratio && handle ? boxWithRatio(b, ratio, pic, handle === "n" || handle === "s") : fitBox(b, 5);
      ed.edit.fields.crop = last;
      placeOverlay(ed);
    } else if (!handle) {
      text.x = clamp(was.x + dx, 0, Math.max(0, 100 - start.w));
      text.y = clamp(was.y + dy, 0, Math.max(0, 100 - start.h));
      last = { x: Math.round(text.x * 100) / 100, y: Math.round(text.y * 100) / 100 };
      paint(ed);
    } else {
      // The corner: taller by as much as it is pulled down, in proportion.
      const grow = 1 + dy / Math.max(start.h, 0.5);
      text.size = clamp(Math.round(was.size * grow * 10) / 10, 0.5, 100);
      last = { size: text.size };
      paint(ed);
    }
  };
  const up = () => {
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) el.removeEventListener(type, up);
    el.removeEventListener("pointermove", move);
    if (!last) return;
    if (what === "crop") saveCrop(ed, last);
    else {
      drawSide(ed);
      write(ed, () => patch(ed.b.texts.id, text.id, last));
    }
  };
  el.addEventListener("pointermove", move);
  for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) el.addEventListener(type, up);
}

function saveCrop(ed, box) {
  const r = (n) => Math.round(n * 100) / 100;
  const value = wholeFrame(box) ? null : { x: r(box.x), y: r(box.y), w: r(box.w), h: r(box.h) };
  setEdit(ed, { crop: value });
}

function setCropping(ed, on) {
  ed.cropping = on;
  if (on) choose(ed, "", false);
  const toggle = ed.root.querySelector(".ph-crop-toggle");
  toggle.classList.toggle("on", on);
  toggle.setAttribute("aria-pressed", String(on));
  fitStage(ed);
  paint(ed);
  drawSide(ed);
}

function choose(ed, id, redraw = true) {
  ed.selected = id;
  if (redraw) { placeOverlay(ed); drawSide(ed); }
}

// -- turning, mirroring, texts --------------------------------------------------------------------
function turn(ed, by) {
  if (!ed.writes || !ed.b.has.has("rotate")) return;
  setEdit(ed, { rotate: (rotationOf(f(ed)) + by + 360) % 360 });
}

function mirror(ed) {
  if (!ed.writes || !ed.b.has.has("mirror")) return;
  setEdit(ed, { mirror: !mirrored(f(ed)) });
}

/** Words on the picture, in a corner, picked, with the panel ready to take them. */
function addText(ed) {
  if (!ed.writesTexts) return;
  if (ed.cropping) setCropping(ed, false);
  const fields = { [ed.b.textEdit]: ed.id, text: NEW_WORDS, ...TEXT_AT, size: TEXT_SIZE, colour: TEXT_COLOUR };
  // Each new one a little lower than the last, so two are not on top of each other.
  fields.y = clamp(TEXT_AT.y + ed.texts.length * (TEXT_SIZE * 1.4), 0, 90);
  write(ed, async () => {
    const made = await api("POST", recordsUrl(ed.b.texts.id), { fields });
    ed.texts.push(textFrom(made));
    ed.selected = made.id;
    paint(ed);
    drawSide(ed);
    const words = ed.root.querySelector(".ph-words");
    if (words) { words.focus(); words.select(); }
  });
}

function setText(ed, text, fields) {
  Object.assign(text, textOf({ ...text, ...fields }));
  paint(ed);
  write(ed, () => patch(ed.b.texts.id, text.id, fields));
}

function removeText(ed, text) {
  if (!text || !ed.writesTexts) return;
  ed.texts = ed.texts.filter((t) => t.id !== text.id);
  if (ed.selected === text.id) ed.selected = "";
  paint(ed);
  drawSide(ed);
  write(ed, () => api("DELETE", recordsUrl(ed.b.texts.id, text.id)));
}

// -- the buttons and the keys ----------------------------------------------------------------------
function drawTools(ed) {
  const mirrorButton = ed.root.querySelector(".ph-mirror");
  mirrorButton.classList.toggle("on", mirrored(f(ed)));
  mirrorButton.setAttribute("aria-pressed", String(mirrored(f(ed))));
}

function wireTools(ed) {
  for (const button of ed.root.querySelectorAll("[data-turn]")) {
    button.addEventListener("click", () => turn(ed, Number(button.dataset.turn)));
  }
  ed.root.querySelector(".ph-mirror").addEventListener("click", () => mirror(ed));
  ed.root.querySelector(".ph-crop-toggle").addEventListener("click", () => setCropping(ed, !ed.cropping));
  const add = ed.root.querySelector(".ph-add-text");
  if (add) add.addEventListener("click", () => addText(ed));
  // A press on the picture itself, outside every box, lets go of the text.
  ed.over.addEventListener("pointerdown", (event) => {
    if (!event.target.closest(".ph-box") && !ed.cropping && ed.selected) choose(ed, "");
  });
}

function wireKeys(ed) {
  ed.onKey = (event) => {
    if (!ed.alive || event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
    const target = event.target;
    if (target.closest && target.closest("input, textarea, select, [contenteditable]")) return;
    if (document.querySelector(".sheet-backdrop")) return;
    const text = textById(ed, ed.selected);
    const keys = {
      r: () => turn(ed, 90),
      R: () => turn(ed, -90),
      m: () => mirror(ed),
      c: () => setCropping(ed, !ed.cropping),
      t: () => addText(ed),
      Delete: () => removeText(ed, text),
      Backspace: () => removeText(ed, text),
      Escape: () => { if (ed.cropping) setCropping(ed, false); else choose(ed, ""); },
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
  const bar = ed.root.querySelector(".ph-headbar");
  const buttons = ed.root.querySelector(".ph-head-actions");
  const fields = f(ed);
  const status = ed.b.has.has("status") ? String(fields.status || "") : "";
  const tone = TONES[status] || "";
  const message = ed.b.has.has("message") ? String(fields.message || "") : "";
  const shownStatus = status && status !== "editing" ? status[0].toUpperCase() + status.slice(1) : "";
  const exportable = ed.b.exportAction;
  const output = ed.b.has.has("output") && fields.output ? String(fields.output) : "";
  bar.innerHTML =
    `<span class="ph-status${tone ? " tone-" + tone : ""}">${BUSY.has(status) ? '<i class="ph-spin"></i>' : ""}` +
    `${esc(shownStatus)}${shownStatus && message ? " · " : ""}${esc(message)}</span>`;
  bar.hidden = !(shownStatus || message);
  buttons.innerHTML =
    (output ? `<button type="button" class="ph-open">Open</button>` : "") +
    (exportable ? `<button type="button" class="act-button primary ph-export"${BUSY.has(status) ? " disabled" : ""}>${esc(exportable.label)}</button>` : "");
  const open = buttons.querySelector(".ph-open");
  if (open) open.addEventListener("click", () => openOutput(ed, output));
  const button = buttons.querySelector(".ph-export");
  if (button) {
    button.addEventListener("click", () => {
      press(ed.at.quill, exportable, {
        record: ed.id,
        here: { quill: ed.at.quill, screen: ed.at.screen },
        after: () => refreshEdit(ed),
      });
    });
  }
}

/** The edit's status, message and output as they are now; asked again every
    few seconds while an export is on its way. */
async function refreshEdit(ed) {
  if (!ed.alive) return;
  try {
    const edit = await api("GET", recordsUrl(ed.b.model.id, ed.id));
    if (!ed.alive) return;
    for (const name of ["status", "message", "output"]) ed.edit.fields[name] = edit.fields[name];
    drawHeader(ed);
  } catch { /* asked again on the next round */ }
  watchExport(ed);
}

function watchExport(ed) {
  clearTimeout(ed.pollTimer);
  if (!ed.alive || !BUSY.has(String(f(ed).status || ""))) return;
  ed.pollTimer = setTimeout(() => refreshEdit(ed), POLL);
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

// -- the panels beside the picture ------------------------------------------------------------------
function drawSide(ed) {
  const side = ed.root.querySelector(".ph-side");
  // Not while something in it is being typed in: it is drawn after.
  if (side.contains(document.activeElement) && document.activeElement.matches("input, textarea")) {
    ed.sideStale = true;
    return;
  }
  const text = textById(ed, ed.selected);
  let html = "";
  if (ed.cropping) html += cropPanel(ed);
  else if (text) html += textPanel(ed, text);
  else html += pickPanel(ed) + sizePanel(ed) + cropPanel(ed);
  side.innerHTML = html;
  ed.sideStale = false;
  wireSide(ed, side, text);
}

/** The words that are on the picture, to pick one; and Add text. */
function pickPanel(ed) {
  if (!ed.b.texts) return "";
  const chips = ed.texts.map((t) =>
    `<button type="button" class="act-chip ph-pick" data-text="${esc(t.id)}">${esc(t.text.split("\n")[0].slice(0, 24) || "…")}</button>`).join("");
  return `<p class="group-label">Text</p>
    <div class="ph-chips">${chips}${ed.writesTexts ? `<button type="button" class="act-chip ph-add-text-side">${glyphs.text}<span>Add text</span></button>` : ""}</div>
    <p class="ph-quiet">${ed.texts.length ? "Press words on the picture to move them, or pick them here." : "Words laid on the picture, in the app's own letters."}</p>`;
}

/** What the export will be, and the usual sizes. */
function sizePanel(ed) {
  const fields = f(ed);
  const cropped = croppedSize(fields);
  const out = outputSize(fields);
  const own = !!(Number(fields.out_width) > 0 || Number(fields.out_height) > 0);
  // Which of the usual sizes the edit is at, if any; else it is another size.
  const same = (size) => !!size && Number(size.out_width || 0) === Number(fields.out_width || 0) &&
    Number(size.out_height || 0) === Number(fields.out_height || 0);
  const usual = SIZES.map(([value, label]) => [value, label, same(sizeFrom(value, cropped))]);
  const options = usual.map(([value, label, chosen]) =>
    `<option value="${esc(value)}"${chosen ? " selected" : ""}>${esc(label)}</option>`).join("") +
    `<option value="custom"${own && !usual.some(([, , chosen]) => chosen) ? " selected" : ""}>Another size…</option>`;
  const disabled = ed.writes && ed.b.has.has("out_width") ? "" : " disabled";
  return `<p class="group-label">Size</p>
    <p class="ph-size-now">${out ? `<b>${out.w} × ${out.h}</b> pixels${cropped && (out.w !== cropped.w || out.h !== cropped.h) ? ` <span class="ph-quiet-inline">from ${cropped.w} × ${cropped.h}</span>` : ""}` : `<span class="ph-quiet-inline">The photo's size is not known yet.</span>`}</p>
    <label class="ph-field"><span>Make it</span><select class="ph-size-pick" aria-label="Size"${disabled}>${options}</select></label>
    <div class="ph-size-fields"${own ? "" : " hidden"}>
      <label class="ph-field small"><span>Width</span><input type="number" min="1" max="8192" data-size="out_width" value="${esc(String(fields.out_width || ""))}" placeholder="${cropped ? cropped.w : ""}"${disabled}></label>
      <label class="ph-field small"><span>Height</span><input type="number" min="1" max="8192" data-size="out_height" value="${esc(String(fields.out_height || ""))}" placeholder="${cropped ? cropped.h : ""}"${disabled}></label>
    </div>
    <p class="ph-quiet">One of them keeps the shape; both are taken as typed.</p>`;
}

function cropPanel(ed) {
  const c = crop(ed);
  const number = (name, label) =>
    `<label class="ph-field small"><span>${label}</span><input type="number" min="0" max="100" step="0.5" data-crop="${name}" value="${Math.round(c[name] * 10) / 10}"${ed.writes ? "" : " disabled"}></label>`;
  const size = croppedSize(f(ed));
  if (!ed.cropping) {
    return `<p class="group-label">Crop</p>
      <p class="ph-quiet">${wholeFrame(c) ? "The whole picture is kept." : `Kept: ${Math.round(c.w)}% × ${Math.round(c.h)}% from ${Math.round(c.x)}%, ${Math.round(c.y)}%${size ? `, ${size.w} × ${size.h} pixels` : ""}.`}</p>
      <div class="ph-row-buttons"><button type="button" class="act-chip ph-crop-start">${glyphs.crop}<span>Crop</span></button>
      ${ed.writes && !wholeFrame(c) ? `<button type="button" class="act-chip ph-crop-reset">Keep all of it</button>` : ""}</div>`;
  }
  const ratios = RATIOS.map(([value, label]) =>
    `<button type="button" class="act-chip ph-ratio${value === ed.ratio ? " on" : ""}" data-ratio="${esc(value)}" aria-pressed="${value === ed.ratio}">${esc(label)}</button>`).join("");
  return `<p class="group-label">Crop</p>
    <div class="ph-chips">${ratios}</div>
    <div class="ph-crop-fields">${number("x", "Left")}${number("y", "Top")}${number("w", "Width")}${number("h", "Height")}</div>
    <p class="ph-quiet">Percent of the picture. Drag the box, or type.${size ? ` Kept: ${size.w} × ${size.h} pixels.` : ""}</p>
    <div class="ph-row-buttons">${ed.writes ? `<button type="button" class="act-chip ph-crop-reset">Keep all of it</button>` : ""}
      <button type="button" class="act-chip primary ph-crop-done">Done</button></div>`;
}

function textPanel(ed, text) {
  const writes = ed.writesTexts;
  const swatches = COLOURS.map(([name, hex]) =>
    `<button type="button" class="ph-swatch${hex === text.colour ? " on" : ""}" data-colour="${hex}" style="--swatch:${hex}" aria-label="${esc(name)}" title="${esc(name)}"${writes ? "" : " disabled"}></button>`).join("");
  return `<p class="group-label">Text</p>
    <div class="group ph-card">
      <textarea class="ph-words" rows="2" aria-label="The words" placeholder="The words"${writes ? "" : " disabled"}>${esc(text.text)}</textarea>
      <label class="ph-field"><span>Size</span><input type="range" class="ph-text-size" min="1" max="40" step="0.5" value="${text.size}"${writes ? "" : " disabled"}><output>${text.size}%</output></label>
      <div class="ph-field"><span>Colour</span><div class="ph-swatches">${swatches}<input type="color" class="ph-colour" value="${esc(text.colour)}" aria-label="Another colour"${writes ? "" : " disabled"}></div></div>
      <div class="ph-crop-fields">
        <label class="ph-field small"><span>Left</span><input type="number" min="0" max="100" step="0.5" data-at="x" value="${Math.round(text.x * 10) / 10}"${writes ? "" : " disabled"}></label>
        <label class="ph-field small"><span>Top</span><input type="number" min="0" max="100" step="0.5" data-at="y" value="${Math.round(text.y * 10) / 10}"${writes ? "" : " disabled"}></label>
      </div>
    </div>
    <div class="ph-row-buttons">
      <button type="button" class="act-chip ph-text-done">Done</button>
      ${writes ? `<button type="button" class="act-chip ph-drop-text">${icons.trash}<span>Remove</span></button>` : ""}
    </div>`;
}

function wireSide(ed, side, text) {
  const on = (selector, type, fn) => { const el = side.querySelector(selector); if (el) el.addEventListener(type, fn); };
  for (const pick of side.querySelectorAll(".ph-pick")) pick.addEventListener("click", () => choose(ed, pick.dataset.text));
  on(".ph-add-text-side", "click", () => addText(ed));
  // Size.
  on(".ph-size-pick", "change", (event) => {
    const value = event.target.value;
    if (value === "custom") {
      side.querySelector(".ph-size-fields").hidden = false;
      side.querySelector('[data-size="out_width"]').focus();
      return;
    }
    const size = value ? sizeFrom(value, croppedSize(f(ed))) : { out_width: null, out_height: null };
    if (!size) { toast("The photo's size is not known yet"); return; }
    setEdit(ed, size);
  });
  for (const input of side.querySelectorAll("[data-size]")) {
    input.addEventListener("change", () => {
      const value = input.value.trim() ? clamp(Math.round(Number(input.value)), 1, 8192) : null;
      input.blur();
      setEdit(ed, { [input.dataset.size]: value });
    });
  }
  // Crop.
  on(".ph-crop-start", "click", () => setCropping(ed, true));
  on(".ph-crop-done", "click", () => setCropping(ed, false));
  on(".ph-crop-reset", "click", () => saveCrop(ed, { x: 0, y: 0, w: 100, h: 100 }));
  for (const chip of side.querySelectorAll(".ph-ratio")) {
    chip.addEventListener("click", () => {
      ed.ratio = chip.dataset.ratio;
      const ratio = ratioOf(ed.ratio);
      if (ratio && ed.writes) saveCrop(ed, boxWithRatio(crop(ed), ratio, picture(ed)));
      else drawSide(ed);
    });
  }
  for (const input of side.querySelectorAll("[data-crop]")) {
    input.addEventListener("change", () => {
      const box = { ...crop(ed), [input.dataset.crop]: Number(input.value) || 0 };
      input.blur();
      saveCrop(ed, fitBox(box, 5));
    });
  }
  // A text.
  if (text) {
    const words = side.querySelector(".ph-words");
    on(".ph-words", "input", () => { text.text = words.value; paint(ed); });
    on(".ph-words", "change", () => setText(ed, text, { text: words.value }));
    on(".ph-text-size", "input", (event) => {
      text.size = Number(event.target.value);
      side.querySelector(".ph-text-size + output").textContent = `${event.target.value}%`;
      paint(ed);
    });
    on(".ph-text-size", "change", (event) => setText(ed, text, { size: Number(event.target.value) }));
    for (const swatch of side.querySelectorAll(".ph-swatch")) {
      swatch.addEventListener("click", () => { setText(ed, text, { colour: swatch.dataset.colour }); drawSide(ed); });
    }
    on(".ph-colour", "input", (event) => { text.colour = colourFrom(event.target.value) || text.colour; paint(ed); });
    on(".ph-colour", "change", (event) => { setText(ed, text, { colour: colourFrom(event.target.value) || TEXT_COLOUR }); drawSide(ed); });
    for (const input of side.querySelectorAll("[data-at]")) {
      input.addEventListener("change", () => {
        input.blur();
        setText(ed, text, { [input.dataset.at]: clamp(Number(input.value) || 0, 0, 100) });
      });
    }
    on(".ph-text-done", "click", () => choose(ed, ""));
    on(".ph-drop-text", "click", () => removeText(ed, text));
  }
  // Drawn again once the typing is over, if something changed while it went on.
  side.addEventListener("focusout", () => { if (ed.sideStale) setTimeout(() => ed.alive && drawSide(ed), 0); }, { once: true });
}
