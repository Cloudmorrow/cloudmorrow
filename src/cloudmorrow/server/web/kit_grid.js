/* The kit's grid: records that are files, the way a file manager shows them.

   A grid screen binds a datamodel whose records have bytes beside their
   fields (the record API's `/content`, `/thumb` and `/upload`), and names
   which of its fields say what: the group each record is in (a link — the
   places to pick from first), the folder it is in, whether it is a folder
   (the `kind` enum's "folder"), its size, when it changed and its type.
   Nothing here knows what the groups or the records are called; the
   screen and the datamodel say.

     #/q/<quill>/<screen>                       the groups, to pick one
     #/q/<quill>/<screen>/<group>[/<folder>…]   a folder in one of them
     #/r/<quill>/<screen>/<model>/<id>          one record: a picture shown,
                                                anything saved or shared

   A folder is its folders and its records, sorted by name, date, size or
   type, as a list or as tiles; a tile for a picture shows the picture,
   small, fetched as it scrolls into view and a few at a time. The plus puts
   something in: one picked, a photo taken, or a new folder; a computer can
   drag files in, or paste one. A record is renamed, moved and deleted from
   its own page, a folder from the “…” beside its name.

   A group whose `group_open` field is false is listed and not opened — it
   is somewhere this server cannot show — with its `group_subtitle` saying
   why. Something else in the app may add to the groups list (a line under
   each, and what it does) through `registerGridHook`, without this file
   knowing what it adds. */

import {
  ApiError, api, app, authHeaders, encodePath, esc, formatDate, heading, icons, nav, onSignOut,
  renderRoute, replace, route, seconds, store, tabs, toast, wireShell, back,
} from "./core.js";

const own = {
  place: '<svg width="22" height="20" viewBox="0 0 22 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="1.5" y="2" width="19" height="6" rx="1.5"/><rect x="1.5" y="12" width="19" height="6" rx="1.5"/><path d="M5 5h.01M5 15h.01" stroke-linecap="round" stroke-width="2.4"/></svg>',
  first: '<svg width="22" height="20" viewBox="0 0 22 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 12.5V5a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2v7.5"/><rect x="1.5" y="12.5" width="19" height="5.5" rx="1.5"/><path d="M16.5 15.25h.01" stroke-width="2.4"/></svg>',
  away: '<svg width="22" height="20" viewBox="0 0 22 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="1.5" y="2.5" width="19" height="12" rx="1.5"/><path d="M7 17.5h8M11 14.5v3"/></svg>',
  folder: '<svg width="22" height="18" viewBox="0 0 22 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M1.5 3.5A1.5 1.5 0 0 1 3 2h5l2 2.5h9a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5H3a1.5 1.5 0 0 1-1.5-1.5z"/></svg>',
  file: '<svg width="20" height="22" viewBox="0 0 20 22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M3.5 2h8l5 5v13a1 1 0 0 1-1 1h-12a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z"/><path d="M11.5 2v5h5"/></svg>',
  image: '<svg width="22" height="20" viewBox="0 0 22 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="1.5" y="2" width="19" height="16" rx="2"/><circle cx="7.5" cy="7.5" r="2"/><path d="m20.5 14-5-5-8 8"/></svg>',
  video: '<svg width="22" height="20" viewBox="0 0 22 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="1.5" y="3" width="13" height="14" rx="2"/><path d="m14.5 8 6-3v10l-6-3z"/></svg>',
  audio: '<svg width="20" height="22" viewBox="0 0 20 22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7 16.5V5l10-2v11.5"/><circle cx="4.5" cy="16.5" r="2.5"/><circle cx="14.5" cy="14.5" r="2.5"/></svg>',
  text: '<svg width="20" height="22" viewBox="0 0 20 22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 2h8l5 5v13a1 1 0 0 1-1 1h-12a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z"/><path d="M6.5 11h7M6.5 14.5h7M6.5 18h4"/></svg>',
  archive: '<svg width="20" height="22" viewBox="0 0 20 22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="2" width="15" height="18" rx="2"/><path d="M8 2v3M8 7v3M8 12v3M6.5 15h3v3h-3z"/></svg>',
  download: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12M7 10l5 5 5-5M4 19h16"/></svg>',
  send: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V3M7.5 7.5 12 3l4.5 4.5M5 12v7a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-7"/></svg>',
  up: '<svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 9V1M1.5 4.5 5 1l3.5 3.5"/></svg>',
  down: '<svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 1v8M1.5 5.5 5 9l3.5-3.5"/></svg>',
  plus: '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  pick: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
  newFolder: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M12 10.5v6M9 13.5h6"/></svg>',
  camera: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13" r="3.5"/></svg>',
  rename: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/></svg>',
  move: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 13.5h6M12.5 11l2.5 2.5-2.5 2.5"/></svg>',
  more: '<svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
  list: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 4h9M6 9h9M6 14h9M3 4h.01M3 9h.01M3 14h.01"/></svg>',
  grid: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="2" y="2" width="5.5" height="5.5" rx="1"/><rect x="10.5" y="2" width="5.5" height="5.5" rx="1"/><rect x="2" y="10.5" width="5.5" height="5.5" rx="1"/><rect x="10.5" y="10.5" width="5.5" height="5.5" rx="1"/></svg>',
};

// -- what else may add to a grid ---------------------------------------------------
// A hook's `groups({at, model, records})` is asked when the groups are
// drawn; it answers null, or `{after(record) → html, wire(root)}`: a line
// drawn under each group, and what it does once it is on the page.
const hooks = [];
export function registerGridHook(hook) { hooks.push(hook); }

// -- reading the screen ---------------------------------------------------------------
/** What the screen says each field is, and the models it is about. */
function bind(at) {
  const { quill, screen } = at;
  const model = quill.models[screen.model];
  const field = (name) => model.fields.find((f) => f.name === name);
  const groupField = field(screen.group);
  const groupModel = quill.models[groupField.to];
  return {
    model, groupModel,
    group: screen.group,
    title: screen.title || model.title,
    folder: screen.folder,
    kind: screen.kind,
    size: screen.size || "",
    modified: screen.modified || "",
    mime: screen.mime || "",
    groupTitle: groupModel.title,
    groupSubtitle: screen.group_subtitle || "",
    groupOpen: screen.group_open || "",
  };
}

const baseName = (path) => path.slice(path.lastIndexOf("/") + 1);
const folderOf = (path) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");
const join = (folder, name) => (folder ? folder + "/" + name : name);
const extOf = (name) => (name.includes(".") ? name.slice(name.lastIndexOf(".") + 1).toLowerCase() : "");

const recordsUrl = (model, id) =>
  "/api/records/" + encodeURIComponent(model) + (id ? "/" + encodeURIComponent(id) : "");
const folderHash = (at, group, folder) =>
  `${at.base}/${encodeURIComponent(group)}` + (folder ? "/" + encodePath(folder) : "");
const itemHash = (at, b, id) =>
  `#/r/${encodeURIComponent(at.quill.id)}/${encodeURIComponent(at.screen.id)}/${encodeURIComponent(b.model.id)}/${encodeURIComponent(id)}`;

/** A record as the folder shows it. */
function entryOf(b, record) {
  const f = record.fields;
  return {
    id: record.id,
    rev: record.rev,
    name: String(f[b.title] || ""),
    folder: String(f[b.folder] || ""),
    is_dir: f[b.kind] === "folder",
    size: Number(b.size ? f[b.size] : 0) || 0,
    modified: (b.modified && seconds(f[b.modified])) || 0,
    mime: String((b.mime && f[b.mime]) || ""),
  };
}

// -- what a file is -------------------------------------------------------------------
// Which of the icons a file gets, and the order the kinds sort in.
const KINDS = ["folder", "image", "video", "audio", "document", "text", "archive", "file"];
const BY_EXT = {
  image: ["jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "avif", "bmp", "svg", "tif", "tiff"],
  video: ["mp4", "m4v", "mov", "mkv", "webm", "avi", "wmv"],
  audio: ["mp3", "m4a", "aac", "flac", "wav", "ogg", "opus", "aiff"],
  document: ["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "pages", "numbers", "key", "epub"],
  text: ["txt", "md", "json", "csv", "xml", "yaml", "yml", "toml", "log", "py", "js", "ts", "html", "css", "sh", "ini", "conf"],
  archive: ["zip", "tar", "gz", "tgz", "bz2", "xz", "7z", "rar", "dmg", "iso"],
};
const KIND_OF_EXT = new Map();
for (const [kind, exts] of Object.entries(BY_EXT)) for (const ext of exts) KIND_OF_EXT.set(ext, kind);

export function kindOf(entry) {
  if (entry.is_dir) return "folder";
  const mime = entry.mime || "";
  if (mime.startsWith("image/")) return "image";
  if (mime.startsWith("video/")) return "video";
  if (mime.startsWith("audio/")) return "audio";
  return KIND_OF_EXT.get(extOf(entry.name)) || (mime.startsWith("text/") ? "text" : "file");
}
const KIND_LABEL = {
  folder: "Folder", image: "Picture", video: "Video", audio: "Audio", document: "Document",
  text: "Text", archive: "Archive", file: "File",
};
// What the row says a file is: its extension, or the kind when it has none.
const typeLabel = (entry) => {
  const kind = kindOf(entry);
  const ext = extOf(entry.name);
  return kind === "folder" ? "Folder" : (ext ? ext.toUpperCase() : KIND_LABEL[kind]);
};

export function formatSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return (value >= 10 ? Math.round(value) : value.toFixed(1)) + " " + units[unit];
}

// -- sorting ----------------------------------------------------------------------------
// Name, date, size or type; tapping the one in use turns it around. Folders
// come first whichever it is, as a file manager has them, and the choice is
// kept so every folder opens the way the last one was left.
const SORTS = [["name", "Name"], ["date", "Date"], ["size", "Size"], ["type", "Type"]];
const DEFAULT_DIR = { name: "asc", date: "desc", size: "desc", type: "asc" };
function sortChoice(at) {
  try {
    const saved = JSON.parse(store.get(`kit.${at.tab}.sort`) || "null");
    if (saved && DEFAULT_DIR[saved.key]) return saved;
  } catch { /* a fresh choice, then */ }
  return { key: "name", dir: "asc" };
}
const byName = (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" });
const COMPARE = {
  name: byName,
  date: (a, b) => a.modified - b.modified || byName(a, b),
  size: (a, b) => a.size - b.size || byName(a, b),
  type: (a, b) => KINDS.indexOf(kindOf(a)) - KINDS.indexOf(kindOf(b))
    || extOf(a.name).localeCompare(extOf(b.name)) || byName(a, b),
};
export function sortEntries(entries, { key, dir }) {
  const compare = COMPARE[key] || byName;
  const sign = dir === "desc" ? -1 : 1;
  const folders = entries.filter((e) => e.is_dir).sort((a, b) => sign * compare(a, b));
  const rest = entries.filter((e) => !e.is_dir).sort((a, b) => sign * compare(a, b));
  return [...folders, ...rest];
}

// A list says when and how big; tiles show what a picture is of. Kept the
// way the sort is, so a folder opens the way the last one was left.
const VIEWS = [["list", "List"], ["grid", "Thumbnails"]];
function viewChoice(at) {
  const saved = store.get(`kit.${at.tab}.view`);
  return VIEWS.some(([key]) => key === saved) ? saved : "list";
}

// -- the groups ------------------------------------------------------------------------
let groupCache = { tab: "", records: [] };
async function groupsOf(at, b, fresh = false) {
  if (fresh || groupCache.tab !== at.tab) {
    groupCache = { tab: at.tab, records: await api("GET", recordsUrl(b.groupModel.id)) };
  }
  return groupCache.records;
}
const groupLabel = (b, record) => String((record && record.fields[b.groupTitle]) || (record && record.id) || "");
const opens = (b, record) => !b.groupOpen || record.fields[b.groupOpen] !== false;

export async function renderGrid(at, arg) {
  const b = bind(at);
  const slash = arg.indexOf("/");
  const group = slash === -1 ? arg : arg.slice(0, slash);
  const folder = slash === -1 ? "" : arg.slice(slash + 1);
  if (!group) return renderGroups(at, b);
  return renderFolder(at, b, group, folder);
}

async function renderGroups(at, b) {
  const records = await groupsOf(at, b, true);
  const extras = (await Promise.all(hooks.map(async (hook) => {
    try { return hook.groups ? await hook.groups({ at, model: b.groupModel, records }) : null; }
    catch { return null; }
  }))).filter(Boolean);
  const after = (r) => extras.map((x) => (x.after ? x.after(r) : "")).join("");
  const rowOf = (r, index) => {
    const about = b.groupSubtitle ? String(r.fields[b.groupSubtitle] || "") : "";
    const meta = about ? `<span class="meta"><span class="preview">${esc(about)}</span></span>` : "";
    if (!opens(b, r)) {
      return `<div class="row has-icon elsewhere"><span class="icon">${own.away}</span>
        <span class="main"><span class="title">${esc(groupLabel(b, r))}</span>${meta}</span></div>`;
    }
    // The first is the one that is always there — a person's own — and
    // looks it; the rest are places beside it.
    return `<a class="row has-icon" href="${folderHash(at, r.id, "")}">
      <span class="icon">${index === 0 ? own.first : own.place}</span>
      <span class="main"><span class="title">${esc(groupLabel(b, r))}</span>${meta}</span>
      <span class="chevron">${icons.chevronRight}</span></a>`;
  };
  const [first, ...rest] = records;
  app.innerHTML = nav({ title: at.screen.label }) + `
    <main class="grid-groups">
      ${heading(at.screen.label)}
      ${first ? `<div class="group">${rowOf(first, 0)}${after(first)}</div>` : ""}
      ${rest.length ? `<div class="group-label">${esc(plural(b.groupModel.label))}</div>
        <div class="group">${rest.map((r, i) => rowOf(r, i + 1) + after(r)).join("")}</div>` : ""}
      ${records.length ? "" : `<p class="empty mascot"><b>Nothing here yet</b>There is nowhere to open yet.</p>`}
    </main>` + tabs(at.tab);
  wireShell();
  for (const x of extras) if (x.wire) x.wire(app);
}

// "Share" → "Shares", for the label over the rest of them.
const plural = (label) => (/s$/i.test(label) ? label : label + "s");

// -- a folder ------------------------------------------------------------------------------
async function listFolder(b, group, folder) {
  const query = `?${encodeURIComponent(b.group)}=${encodeURIComponent(group)}` +
    `&${encodeURIComponent(b.folder)}=${encodeURIComponent(folder)}`;
  return (await api("GET", recordsUrl(b.model.id) + query)).map((r) => entryOf(b, r));
}

async function renderFolder(at, b, group, folder) {
  let entries;
  try {
    entries = await listFolder(b, group, folder);
  } catch (err) {
    // Gone, or a place this server cannot show after all: back a step.
    if (err.status === 404 || err.status === 400) {
      toast(err.message);
      replace(folder ? folderHash(at, group, folderOf(folder)) : at.base);
      return renderRoute();
    }
    throw err;
  }
  const groups = await groupsOf(at, b).catch(() => []);
  const here = groups.find((g) => g.id === group);
  const groupName = here ? groupLabel(b, here) : group;
  const parent = folder ? folderHash(at, group, folderOf(folder)) : at.base;
  const parentLabel = folder ? (folderOf(folder) ? baseName(folderOf(folder)) : groupName) : at.screen.label;
  const title = folder ? baseName(folder) : groupName;
  const moreButton = folder
    ? `<button class="more" aria-label="${esc(title)}: rename, move or delete">${own.more}</button>` : "";
  app.innerHTML = nav({ back: parent, backLabel: parentLabel, title }) + `
    <main>
      ${heading(title, moreButton + `<button class="add" aria-label="Add">${own.plus}</button>`)}
      <div class="sort-row">
        <div class="sort" role="group" aria-label="Sort by"></div>
        <div class="view-switch" role="group" aria-label="Show as"></div>
      </div>
      <div class="listing"></div>
      <input type="file" class="pick-input" multiple hidden>
      <input type="file" class="camera-input" accept="image/*" capture="environment" hidden>
    </main>` + tabs(at.tab);
  wireShell();

  const sortEl = app.querySelector(".sort");
  const viewEl = app.querySelector(".view-switch");
  const listingEl = app.querySelector(".listing");
  let choice = sortChoice(at);
  let view = viewChoice(at);

  const row = (entry) => {
    const kind = kindOf(entry);
    if (entry.is_dir) {
      return `<a class="row has-icon" href="${folderHash(at, group, join(folder, entry.name))}">
        <span class="icon">${own.folder}</span>
        <span class="main"><span class="title">${esc(entry.name)}</span></span>
        <span class="chevron">${icons.chevronRight}</span></a>`;
    }
    return `<a class="row has-icon" href="${itemHash(at, b, entry.id)}">
      <span class="icon">${own[kind] || own.file}</span>
      <span class="main"><span class="title">${esc(entry.name)}</span>
      <span class="meta">${entry.modified ? `<span class="date">${esc(formatDate(entry.modified))}</span>` : ""}` +
      `${b.size ? `<span class="size">${esc(formatSize(entry.size))}</span>` : ""}` +
      `<span class="type">${esc(typeLabel(entry))}</span></span></span></a>`;
  };
  // A tile: the picture itself where the server can make one small, else
  // the kind's icon — and its name under it. The picture comes when the
  // tile scrolls into view, not before.
  const tile = (entry) => {
    const kind = kindOf(entry);
    const href = entry.is_dir ? folderHash(at, group, join(folder, entry.name)) : itemHash(at, b, entry.id);
    const thumb = kind === "image" ? ` data-thumb="${esc(entry.id)}" data-stamp="${esc(entry.rev)}"` : "";
    return `<a class="tile ${kind}" href="${href}"${thumb}>
      <span class="thumb"><span class="icon">${own[kind] || own.file}</span></span>
      <span class="name">${esc(entry.name)}</span></a>`;
  };
  let watcher = null;
  const show = () => {
    sortEl.innerHTML = SORTS.map(([key, label]) => {
      const active = key === choice.key;
      const arrow = active ? (choice.dir === "asc" ? own.up : own.down) : "";
      return `<button class="${active ? "active" : ""}" data-sort="${key}" aria-pressed="${active}">${label}${arrow}</button>`;
    }).join("");
    viewEl.innerHTML = VIEWS.map(([key, label]) =>
      `<button class="${key === view ? "active" : ""}" data-view="${key}" aria-pressed="${key === view}" aria-label="${label}">${own[key]}</button>`).join("");
    if (watcher) { watcher.disconnect(); watcher = null; }
    const sorted = sortEntries(entries, choice);
    if (!sorted.length) {
      listingEl.innerHTML = `<p class="empty mascot"><b>Nothing here yet</b>This folder is empty. Add something with the plus.</p>`;
    } else if (view === "grid") {
      listingEl.innerHTML = `<div class="tiles">${sorted.map(tile).join("")}</div>`;
      watcher = watchTiles(b, listingEl);
    } else {
      listingEl.innerHTML = `<div class="group">${sorted.map(row).join("")}</div>`;
    }
  };
  show();
  viewEl.addEventListener("click", (event) => {
    const button = event.target.closest("[data-view]");
    if (!button || button.dataset.view === view) return;
    view = button.dataset.view;
    store.set(`kit.${at.tab}.view`, view);
    show();
  });
  sortEl.addEventListener("click", (event) => {
    const button = event.target.closest("[data-sort]");
    if (!button) return;
    const key = button.dataset.sort;
    choice = key === choice.key
      ? { key, dir: choice.dir === "asc" ? "desc" : "asc" }
      : { key, dir: DEFAULT_DIR[key] };
    store.set(`kit.${at.tab}.sort`, JSON.stringify(choice));
    show();
  });

  const reload = async () => {
    entries = await listFolder(b, group, folder);
    show();
  };
  const place = { b, group, folder };

  // Adding: the plus opens a sheet with the ways in. A picker or the camera
  // ends in a file input, which has to be clicked from the tap itself for
  // the phone to open it.
  const pickInput = app.querySelector(".pick-input");
  const cameraInput = app.querySelector(".camera-input");
  app.querySelector(".heading .add").addEventListener("click", () => openSheet([
    { icon: own.pick, label: "Choose a file", run: () => pickInput.click() },
    { icon: own.camera, label: "Take a photo", run: () => cameraInput.click() },
    { icon: own.newFolder, label: "New folder", run: () => newFolder(place, reload) },
  ]));
  const more = app.querySelector(".heading .more");
  if (more) {
    more.addEventListener("click", () => openSheet([
      { icon: own.rename, label: "Rename folder", run: () => folderAction(at, place, "rename") },
      { icon: own.move, label: "Move folder", run: () => folderAction(at, place, "move") },
      { icon: icons.trash, label: "Delete folder", bad: true, run: () => folderAction(at, place, "delete") },
    ]));
  }
  pickInput.addEventListener("change", async () => {
    const picked = [...pickInput.files];
    pickInput.value = "";
    await uploadAll(place, picked.map((file) => [file, file.name]));
    await reload();
  });
  cameraInput.addEventListener("change", async () => {
    const taken = [...cameraInput.files];
    cameraInput.value = "";
    // The camera calls every photo image.jpg; the moment it was taken is a
    // better name, and one that sorts.
    await uploadAll(place, taken.map((file) => [file, photoName(file)]));
    await reload();
  });

  // The two ways a computer puts a file somewhere: dragged onto the
  // folder, or pasted into it. Both end where the picker ends. A phone has
  // neither — nothing it can do produces a drag carrying files.
  const carriesFiles = (event) =>
    [...((event.dataTransfer && event.dataTransfer.types) || [])].includes("Files");
  const mainEl = app.querySelector("main");
  // `dragenter` and `dragleave` fire again for every child the pointer
  // crosses, so the two are counted rather than believed.
  let over = 0;
  mainEl.addEventListener("dragenter", (event) => {
    if (!carriesFiles(event)) return;
    over += 1;
    mainEl.classList.add("dropping");
  });
  mainEl.addEventListener("dragover", (event) => {
    if (!carriesFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  });
  mainEl.addEventListener("dragleave", () => {
    over = Math.max(0, over - 1);
    if (!over) mainEl.classList.remove("dropping");
  });
  mainEl.addEventListener("drop", async (event) => {
    if (!carriesFiles(event)) return;
    event.preventDefault();
    over = 0;
    mainEl.classList.remove("dropping");
    const dropped = [...event.dataTransfer.files];
    if (!dropped.length) return;
    await uploadAll(place, dropped.map((file) => [file, file.name]));
    await reload();
  });
  // A paste lands on the document when nothing is focused, so it cannot be
  // hung off this screen's own elements; the one listener below reads this.
  openFolder = { main: mainEl, place, reload };
}

// -- putting something in ----------------------------------------------------------------
// The folder on the screen, for a paste with nothing focused. Set by every
// folder drawn; the listener checks the screen it names is still on the
// page, because `app.innerHTML` leaves the old one detached.
let openFolder = null;

addEventListener("paste", async (event) => {
  if (!openFolder || !app.contains(openFolder.main)) return;
  const pasted = [...((event.clipboardData && event.clipboardData.files) || [])];
  if (!pasted.length) return;
  event.preventDefault();
  const { place, reload } = openFolder;
  // A screenshot arrives called image.png every single time, which is no
  // name for the third one. The moment it was taken is, and it sorts.
  await uploadAll(place, pasted.map((file) =>
    [file, file.name && file.name !== "image.png" ? file.name : photoName(file)]));
  await reload();
});

function photoName(file) {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  const stamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ` +
    `${pad(now.getHours())}.${pad(now.getMinutes())}.${pad(now.getSeconds())}`;
  const ext = (file.type.split("/")[1] || "jpg").replace("jpeg", "jpg");
  return `Photo ${stamp}.${ext}`;
}

async function uploadOne({ b, group, folder }, file, name) {
  const headers = { ...authHeaders(), "Content-Type": file.type || "application/octet-stream" };
  const query = `?${encodeURIComponent(b.group)}=${encodeURIComponent(group)}` +
    `&${encodeURIComponent(b.folder)}=${encodeURIComponent(folder)}` +
    `&${encodeURIComponent(b.title)}=${encodeURIComponent(name)}`;
  let res;
  try {
    res = await fetch(recordsUrl(b.model.id) + "/upload" + query, { method: "POST", headers, body: file });
  } catch {
    throw new ApiError(0, "Could not reach the server");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data && data.detail !== undefined ? data.detail : "upload failed");
  return data;
}

// One after another, with the bar saying which; a failure says why and
// stops there, so what did arrive is not lost in a run of errors.
async function uploadAll(place, items) {
  let done = 0;
  for (const [file, name] of items) {
    toast(items.length > 1 ? `Uploading ${name} (${done + 1} of ${items.length})…` : `Uploading ${name}…`, 60000);
    try { await uploadOne(place, file, name); }
    catch (err) { toast(err.message); return; }
    done += 1;
  }
  toast(done === 1 ? "Added " + items[0][1] : `Added ${done} files`);
}

async function newFolder({ b, group, folder }, reload) {
  const name = (prompt("Folder name") || "").trim();
  if (!name) return;
  try {
    await api("POST", recordsUrl(b.model.id), {
      fields: { [b.group]: group, [b.folder]: folder, [b.title]: name, [b.kind]: "folder" },
    });
    toast("Made " + name);
    await reload();
  } catch (err) { toast(err.message); }
}

// -- renaming, moving, deleting ----------------------------------------------------------
/** Rename, move or delete one record; true when it changed. `after(record)` follows a change. */
async function change(b, entry, what) {
  const noun = entry.is_dir ? "folder" : b.model.label.toLowerCase();
  try {
    if (what === "rename") {
      const name = (prompt(`Rename the ${noun}`, entry.name) || "").trim();
      if (!name || name === entry.name) return null;
      return await api("PATCH", recordsUrl(b.model.id, entry.id), { fields: { [b.title]: name }, rev: entry.rev });
    }
    if (what === "move") {
      const to = prompt(`Move “${entry.name}” to which folder? Empty is the top.`, entry.folder);
      if (to === null) return null;
      const target = to.trim().replace(/^\/+|\/+$/g, "");
      if (target === entry.folder) return null;
      return await api("PATCH", recordsUrl(b.model.id, entry.id), { fields: { [b.folder]: target }, rev: entry.rev });
    }
    if (what === "delete") {
      const warning = entry.is_dir ? "\n\nEverything in it goes with it." : "";
      if (!confirm(`Delete “${entry.name}”?${warning}`)) return null;
      await api("DELETE", recordsUrl(b.model.id, entry.id));
      return { deleted: true };
    }
  } catch (err) {
    toast(err.status === 409 ? "That changed somewhere else; look again" : err.message);
  }
  return null;
}

async function folderAction(at, { b, group, folder }, what) {
  // The folder's own record is in the listing of the folder it is in.
  let entry;
  try {
    entry = (await listFolder(b, group, folderOf(folder))).find((e) => e.is_dir && e.name === baseName(folder));
  } catch (err) { toast(err.message); return; }
  if (!entry) { toast("That folder is gone"); return; }
  const done = await change(b, entry, what);
  if (!done) return;
  if (done.deleted) {
    toast("Deleted " + entry.name);
    back(folderHash(at, group, folderOf(folder)));
    return;
  }
  const moved = entryOf(b, done);
  replace(folderHash(at, group, join(moved.folder, moved.name)));
  renderRoute();
}

// A sheet from the bottom, the phone's way of asking which of a few
// things you meant. Tapping outside it, or Cancel, is no.
function openSheet(choices) {
  const backdrop = document.createElement("div");
  backdrop.className = "sheet-backdrop";
  backdrop.innerHTML = `<div class="sheet" role="menu">` +
    choices.map((c, i) => `<button class="sheet-row${c.bad ? " danger" : ""}" role="menuitem" data-choice="${i}">${c.icon}<span>${esc(c.label)}</span></button>`).join("") +
    `<button class="sheet-row cancel">Cancel</button></div>`;
  const close = () => backdrop.remove();
  backdrop.addEventListener("click", (event) => {
    const row = event.target.closest("[data-choice]");
    close();
    if (row) choices[Number(row.dataset.choice)].run();
  });
  document.body.appendChild(backdrop);
}

// -- the bytes ------------------------------------------------------------------------------
// A record's bytes come down through fetch with the token — an <img src>
// cannot carry it — and are kept for the page's life, keyed by the record's
// rev, so going back and forth does not fetch twice and a changed file is
// fetched afresh.
const blobs = new Map();
const blobURLs = new Map();
const thumbURLs = new Map();
onSignOut(() => {
  for (const url of [...blobURLs.values(), ...thumbURLs.values()]) URL.revokeObjectURL(url);
  blobURLs.clear();
  thumbURLs.clear();
  blobs.clear();
});

async function contentBlob(b, entry) {
  const key = entry.id + "@" + entry.rev;
  if (blobs.has(key)) return blobs.get(key);
  let res;
  try {
    res = await fetch(recordsUrl(b.model.id, entry.id) + "/content", { headers: authHeaders() });
  } catch {
    throw new ApiError(0, "Could not reach the server");
  }
  if (!res.ok) throw new ApiError(res.status, res.status === 404 ? `That ${b.model.label.toLowerCase()} is gone` : "Could not fetch it");
  const blob = await res.blob();
  blobs.set(key, blob);
  return blob;
}

async function contentURL(b, entry) {
  const key = entry.id + "@" + entry.rev;
  if (blobURLs.has(key)) return blobURLs.get(key);
  const url = URL.createObjectURL(await contentBlob(b, entry));
  blobURLs.set(key, url);
  return url;
}

// Sharp on a phone's screen, and one size for the whole grid so the
// server makes each picture small once.
const THUMB_SIZE = (window.devicePixelRatio || 1) > 2 ? 512 : 256;

async function thumbURL(b, id, stamp) {
  const key = id + "@" + stamp;
  if (thumbURLs.has(key)) return thumbURLs.get(key);
  const res = await fetch(recordsUrl(b.model.id, id) + "/thumb?size=" + THUMB_SIZE, { headers: authHeaders() });
  if (!res.ok) throw new ApiError(res.status, "no thumbnail");
  const url = URL.createObjectURL(await res.blob());
  thumbURLs.set(key, url);
  return url;
}

// The tiles ask for their pictures as they come into view, a few at a time:
// scrolling fast through a big folder queues what it passed, and the queue
// is what is on the screen now, not everything that ever was.
const THUMBS_AT_ONCE = 4;
function watchTiles(b, root) {
  const waiting = [];
  let inFlight = 0;
  const next = () => {
    while (inFlight < THUMBS_AT_ONCE && waiting.length) {
      const el = waiting.shift();
      if (!el.isConnected || el.classList.contains("has-img")) continue;
      inFlight += 1;
      thumbURL(b, el.dataset.thumb, el.dataset.stamp)
        .then((url) => {
          const img = document.createElement("img");
          img.alt = "";
          img.src = url;
          el.querySelector(".thumb").appendChild(img);
          el.classList.add("has-img");
        })
        .catch(() => { /* the icon stays */ })
        .finally(() => { inFlight -= 1; next(); });
    }
  };
  const watcher = new IntersectionObserver((hits) => {
    for (const hit of hits) {
      if (!hit.isIntersecting) continue;
      watcher.unobserve(hit.target);
      waiting.push(hit.target);
    }
    next();
  }, { rootMargin: "200px 0px" });
  for (const el of root.querySelectorAll(".tile[data-thumb]")) watcher.observe(el);
  return watcher;
}

// The phone's own share sheet, where there is one — save to Photos, send
// it on, AirDrop it — and a plain save where there is not. The sheet has
// to open from the tap itself, so the bytes are fetched before, when the
// screen opens, rather than after the tap.
const canSendFiles = () => typeof navigator.share === "function" && typeof navigator.canShare === "function";

async function sendOrSave(b, entry) {
  let blob;
  try { blob = await contentBlob(b, entry); }
  catch (err) { toast(err.message); return; }
  if (canSendFiles()) {
    const file = new File([blob], entry.name, { type: blob.type || entry.mime || "application/octet-stream" });
    if (navigator.canShare({ files: [file] })) {
      try { await navigator.share({ files: [file], title: entry.name }); return; }
      catch (err) { if (err.name === "AbortError") return; }
    }
  }
  const link = document.createElement("a");
  link.href = await contentURL(b, entry);
  link.download = entry.name;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

// -- one record ------------------------------------------------------------------------------
// A picture is shown; anything else is named. Either can be sent on or
// saved, renamed, moved or deleted. This is the grid's record sheet: kit.js
// hands a grid's own records here rather than to the sheet of fields.
export async function renderGridItem(at, id) {
  const b = bind(at);
  let record;
  try { record = await api("GET", recordsUrl(b.model.id, id)); }
  catch (err) {
    if (err.status !== 404) throw err;
    toast(`That ${b.model.label.toLowerCase()} is gone`);
    replace(at.base);
    return renderRoute();
  }
  const entry = entryOf(b, record);
  const group = String(record.fields[b.group] || "");
  const groups = await groupsOf(at, b).catch(() => []);
  const groupName = groupLabel(b, groups.find((g) => g.id === group)) || group;
  const kind = kindOf(entry);
  const parent = folderHash(at, group, entry.folder);
  const facts = [
    ["Type", typeLabel(entry)],
    ...(b.size ? [["Size", formatSize(entry.size)]] : []),
    ...(entry.modified ? [["Modified", formatDate(entry.modified, { long: true })]] : []),
    ["Where", groupName + (entry.folder ? "/" + entry.folder : "")],
  ];
  const sending = canSendFiles();
  app.innerHTML = nav({
    back: parent, backLabel: entry.folder ? baseName(entry.folder) : groupName, title: entry.name,
    right: `<button class="download" aria-label="${sending ? "Send" : "Save"}">${sending ? own.send : own.download}</button>`,
  }) + `
    <main>
      ${kind === "image"
        ? `<figure class="view"><img alt="${esc(entry.name)}"></figure>`
        : `<div class="file-card"><span class="icon">${own[kind] || own.file}</span></div>`}
      <h1 class="large file-name">${esc(entry.name)}</h1>
      <div class="group facts">${facts.map(([label, value]) =>
        `<div class="row"><span class="main">${esc(label)}</span><span class="value">${esc(value)}</span></div>`).join("")}</div>
      <div class="group item-actions">
        <button class="row has-icon" data-do="rename"><span class="icon">${own.rename}</span><span class="main"><span class="title">Rename</span></span></button>
        <button class="row has-icon" data-do="move"><span class="icon">${own.move}</span><span class="main"><span class="title">Move to another folder</span></span></button>
        <button class="row has-icon danger" data-do="delete"><span class="icon">${icons.trash}</span><span class="main"><span class="title">Delete</span></span></button>
      </div>
    </main>`;
  wireShell();
  app.querySelector(".nav").classList.add("lined");

  const img = app.querySelector(".view img");
  if (img) {
    contentURL(b, entry)
      .then((url) => { img.src = url; })
      .catch((err) => { toast(err.message); img.closest(".view").classList.add("missing"); });
    // Tap the picture and it fills the screen, on its own; tap again and it is back.
    img.addEventListener("click", () => {
      if (!img.src) return;
      const box = document.createElement("div");
      box.className = "lightbox";
      box.innerHTML = `<img src="${esc(img.src)}" alt="${esc(entry.name)}">`;
      box.addEventListener("click", () => box.remove());
      document.body.appendChild(box);
    });
  }
  // Fetched now, so the share sheet can open straight from the tap.
  contentBlob(b, entry).catch(() => { /* said when the tap comes */ });
  app.querySelector(".download").addEventListener("click", () => sendOrSave(b, entry));
  for (const button of app.querySelectorAll(".item-actions [data-do]")) {
    button.addEventListener("click", async () => {
      const done = await change(b, entry, button.dataset.do);
      if (!done) return;
      if (done.deleted) {
        toast("Deleted " + entry.name);
        back(parent);
        return;
      }
      replace(itemHash(at, b, done.id));
      route();
    });
  }
}
