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
   drag files in, or paste one; the room around the rows has a menu with a
   new folder and a new, empty text file by any name. A record is renamed,
   moved and deleted from its own page, a folder from the “…” beside its
   name — and every row and tile has a menu (a right-click, a long press on
   a phone: actions.js's) with Open, the Quills that edit that kind of file,
   Rename, Duplicate, Copy to, Move to and Delete. Select beside the title,
   or Shift or Ctrl with a click, picks several for one of those; and a row
   or tile dragged onto a folder moves there, with whatever is picked.
   The magnifier beside the title opens a search through the folder and
   everything under it — names, and the lines of text files, as the record
   API searches (`within` and `q`) — whose hits say where each one is.

   Deleting does not lose anything: the server moves what is deleted to a
   Trash folder, and a record in there — the screen's `deleted` field says
   when it went, `deleted_from` where it was — has Restore in place of
   Rename and Move, and a Delete that is for good. The server sweeps the
   Trash of what has sat there a month; the kit only draws what it says.
   The screen's `trash` names the folder at the top of a group the server
   keeps it in: that one is not among the folders but a bin before the
   plus, and in it an Empty button in place of the “…”, which deletes the
   folder itself — what the server takes as emptying it.

   A group whose `group_open` field is false is listed and not opened — it
   is somewhere this server cannot show — with its `group_subtitle` saying
   why. One whose `group_writes` field is false is opened as if its records
   could only be read: everything still opens, and nothing writes. Something else in the app may add to the groups list (a line under
   each, and what it does) through `registerGridHook`, without this file
   knowing what it adds.

   On records you may only read (docs/CIRCLES.md) it is the same file
   manager with nothing that writes: no plus, no dropping or pasting files
   in, no new folder, and nothing renamed, moved or deleted. Everything
   still opens, and is still sent on or saved. */

import {
  api, apiRaw, app, back, baseName, encodePath, esc, folderOf, formatDate, go, heading, icons, joinPath,
  localDay, mount, nav, onSignOut, pad2, recordsUrl, renderRoute, replace, route, seconds, store,
  tabs, toast, wireShell,
} from "./core.js";
import { mayWrite, plural } from "./kit.js";
import { ask, askText } from "./dialog.js";
import { contextMenus, editorsFor, menu } from "./actions.js";
import { pickFolder } from "./filepick.js";

const own = {
  place: '<svg width="22" height="20" viewBox="0 0 22 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="1.5" y="2" width="19" height="6" rx="1.5"/><rect x="1.5" y="12" width="19" height="6" rx="1.5"/><path d="M5 5h.01M5 15h.01" stroke-linecap="round" stroke-width="2.4"/></svg>',
  first: '<svg width="22" height="20" viewBox="0 0 22 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 12.5V5a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2v7.5"/><rect x="1.5" y="12.5" width="19" height="5.5" rx="1.5"/><path d="M16.5 15.25h.01" stroke-width="2.4"/></svg>',
  away: '<svg width="22" height="20" viewBox="0 0 22 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="1.5" y="2.5" width="19" height="12" rx="1.5"/><path d="M7 17.5h8M11 14.5v3"/></svg>',
  folder: '<svg width="22" height="18" viewBox="0 0 22 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M1.5 3.5A1.5 1.5 0 0 1 3 2h5l2 2.5h9a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5H3a1.5 1.5 0 0 1-1.5-1.5z"/></svg>',
  // A folder's tile: the folder itself, filled, with its tab.
  folderFull: '<svg width="22" height="18" viewBox="0 0 22 18" fill="currentColor"><path d="M1.5 3.5A1.5 1.5 0 0 1 3 2h5l2 2.5h9a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5H3a1.5 1.5 0 0 1-1.5-1.5z"/></svg>',
  copy: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/></svg>',
  edit: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4H6a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-9"/><path d="m11 15 9.5-9.5-2-2L9 13l-.5 2.5z"/></svg>',
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
  restore: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 10a8 8 0 1 1 2.3 5.7"/><path d="M4 4v6h6"/></svg>',
  more: '<svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
  list: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 4h9M6 9h9M6 14h9M3 4h.01M3 9h.01M3 14h.01"/></svg>',
  grid: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="2" y="2" width="5.5" height="5.5" rx="1"/><rect x="10.5" y="2" width="5.5" height="5.5" rx="1"/><rect x="2" y="10.5" width="5.5" height="5.5" rx="1"/><rect x="10.5" y="10.5" width="5.5" height="5.5" rx="1"/></svg>',
};

// -- what else may add to a grid ---------------------------------------------------
// A hook's `groups({at, model, records})` is asked when the groups are
// drawn; it answers null, or `{after(record) → html, wire(root), menu()}`:
// a line drawn under each group, what it does once it is on the page, and
// choices for the “…” beside the title (actions.js's menu).
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
    deleted: screen.deleted || "",
    deletedFrom: screen.deleted_from || "",
    trash: screen.trash || "",
    groupTitle: groupModel.title,
    groupSubtitle: screen.group_subtitle || "",
    groupOpen: screen.group_open || "",
    groupWrites: screen.group_writes || "",
    writes: mayWrite(model),
  };
}

const extOf = (name) => (name.includes(".") ? name.slice(name.lastIndexOf(".") + 1).toLowerCase() : "");

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
    group: String(f[b.group] || ""),
    folder: String(f[b.folder] || ""),
    is_dir: f[b.kind] === "folder",
    size: Number(b.size ? f[b.size] : 0) || 0,
    modified: (b.modified && seconds(f[b.modified])) || 0,
    mime: String((b.mime && f[b.mime]) || ""),
    // In the Trash: when it went there, and the path it had.
    deleted: (b.deleted && seconds(f[b.deleted])) || 0,
    deletedFrom: String((b.deletedFrom && f[b.deletedFrom]) || ""),
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
// A group whose `group_writes` field is false is read, never written: the
// circles may allow the datamodel, and this one place still not.
const readOnlyIn = (b, record) => !!(b.groupWrites && record && record.fields[b.groupWrites] === false);

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
  // What the hooks offer beside the title: making a group, say.
  const choices = extras.flatMap((x) => (x.menu ? x.menu() : []));
  const moreButton = choices.length ? `<button class="more" aria-label="More">${own.more}</button>` : "";
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
  mount(nav({ title: at.screen.label }) + `
    <main class="grid-groups">
      ${heading(at.screen.label, moreButton)}
      ${first ? `<div class="group">${rowOf(first, 0)}${after(first)}</div>` : ""}
      ${rest.length ? `<div class="group-label">${esc(plural(b.groupModel.label))}</div>
        <div class="group">${rest.map((r, i) => rowOf(r, i + 1) + after(r)).join("")}</div>` : ""}
      ${records.length ? "" : `<p class="empty mascot"><b>Nothing here yet</b>There is nowhere to open yet.</p>`}
    </main>` + tabs(at.tab));
  wireShell();
  const more = app.querySelector(".heading .more");
  if (more) {
    more.addEventListener("click", () => {
      const box = more.getBoundingClientRect();
      menu(choices, { x: box.right - 200, y: box.bottom + 4 });
    });
  }
  for (const x of extras) if (x.wire) x.wire(app);
}

// "Share" → "Shares", for the label over the rest of them.
// -- a folder ------------------------------------------------------------------------------
async function listFolder(b, group, folder) {
  const query = `?${encodeURIComponent(b.group)}=${encodeURIComponent(group)}` +
    `&${encodeURIComponent(b.folder)}=${encodeURIComponent(folder)}`;
  return (await api("GET", recordsUrl(b.model.id) + query)).map((r) => entryOf(b, r));
}

async function renderFolder(at, b, group, folder) {
  // The Trash is made by the first delete and goes when it is emptied: not
  // there to list, it is there to open, and empty.
  const isTrash = Boolean(b.trash) && folder === b.trash;
  const inTrash = Boolean(b.trash) && (isTrash || folder.startsWith(b.trash + "/"));
  const list = async () => {
    try {
      return await listFolder(b, group, folder);
    } catch (err) {
      if (isTrash && (err.status === 404 || err.status === 400)) return [];
      throw err;
    }
  };
  let entries;
  try {
    entries = await list();
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
  if (readOnlyIn(b, here)) b.writes = false;
  const groupName = here ? groupLabel(b, here) : group;
  const parent = folder ? folderHash(at, group, folderOf(folder)) : at.base;
  const parentLabel = folder ? (folderOf(folder) ? baseName(folderOf(folder)) : groupName) : at.screen.label;
  const title = folder ? baseName(folder) : groupName;
  // Nothing goes into the Trash, or into what is in it, but by being deleted.
  const takesIn = b.writes && !inTrash;
  const moreButton = folder && b.writes && !isTrash
    ? `<button class="more" aria-label="${esc(title)}: rename, move or delete">${own.more}</button>` : "";
  // At the top of a group the Trash is a bin, not a folder; in it, Empty.
  const binButton = !folder && b.trash
    ? `<a class="button bin" href="${folderHash(at, group, b.trash)}" aria-label="${esc(b.trash)}">${icons.trash}</a>` : "";
  const emptyButton = isTrash && b.writes
    ? `<button class="empty-trash" hidden>${icons.trash}<span>Empty</span></button>` : "";
  // A search through the folder and all under it, in the heading: the
  // magnifier opens the field, Escape or Cancel closes it. Not at the
  // groups, which are not a folder.
  const findButton = `<button class="find" aria-label="Search" aria-pressed="false">${icons.search}</button>`;
  const findField = `<input class="find-input" type="search" placeholder="Search ${esc(title)}" aria-label="Search ${esc(title)}" autocapitalize="none" autocorrect="off" spellcheck="false" hidden>`;
  // Several at once: Select, then what can be done to them, by where they are.
  const selectButton = `<button class="choose" aria-pressed="false" hidden>Select</button>`;
  const bulk = inTrash
    ? (b.writes ? [["restore", "Restore"], ["delete", "Delete for good", "danger"]] : [])
    : [["copy", "Copy to…"], ...(b.writes ? [["move", "Move to…"], ["delete", "Delete", "danger"]] : [])];
  const bulkButtons = bulk.map(([what, label, tone]) =>
    `<button type="button" class="${tone || ""}" data-bulk="${what}" disabled>${label}</button>`).join("");
  mount(nav({ back: parent, backLabel: parentLabel, title }) + `
    <main>
      ${heading(title, findField + findButton + selectButton + moreButton + binButton + emptyButton + (takesIn ? `<button class="add" aria-label="Add">${own.plus}</button>` : ""))}
      <div class="sort-row">
        <div class="sort" role="group" aria-label="Sort by"></div>
        <div class="view-switch" role="group" aria-label="Show as"></div>
      </div>
      <div class="choose-bar" hidden>
        <span class="count"></span>
        <button type="button" class="all">All</button>
        ${bulkButtons}
      </div>
      <div class="listing"></div>
      ${takesIn ? `<input type="file" class="pick-input" multiple hidden>
      <input type="file" class="camera-input" accept="image/*" capture="environment" hidden>` : ""}
    </main>` + tabs(at.tab));
  wireShell();

  const sortEl = app.querySelector(".sort");
  const viewEl = app.querySelector(".view-switch");
  const listingEl = app.querySelector(".listing");
  const emptyEl = app.querySelector(".heading .empty-trash");
  const selectEl = app.querySelector(".heading .choose");
  const barEl = app.querySelector(".choose-bar");
  const mainEl = app.querySelector("main");
  const findEl = app.querySelector(".heading .find");
  const findInput = app.querySelector(".heading .find-input");
  // The Trash is drawn beside the title, not among the folders.
  const shown = () => (folder || !b.trash ? entries : entries.filter((e) => !(e.is_dir && e.name === b.trash)));
  let choice = sortChoice(at);
  let view = viewChoice(at);

  const hrefOf = (entry) => (entry.is_dir ? folderHash(at, group, joinPath(folder, entry.name)) : itemHash(at, b, entry.id));
  // Every row and tile says which record it is, can be picked, and — where
  // it may be moved — dragged onto a folder.
  const check = `<span class="check" aria-hidden="true">${icons.tick}</span>`;
  const itemAttrs = (entry) => `data-id="${esc(entry.id)}"${takesIn ? ' draggable="true"' : ""}`;
  // A hit says where it is under this folder, and the line that matched.
  const whereSaid = (entry) => {
    const under = folder && entry.folder.startsWith(folder + "/") ? entry.folder.slice(folder.length + 1) : (folder === entry.folder ? "" : entry.folder);
    return under ? `<span class="date">${esc(under)}</span>` : "";
  };
  const row = (entry) => {
    const kind = kindOf(entry);
    if (found !== null && !entry.is_dir) {
      return `<a class="row has-icon" href="${hrefOf(entry)}" ${itemAttrs(entry)}>${check}
        <span class="icon">${own[kind] || own.file}</span>
        <span class="main"><span class="title">${esc(entry.name)}</span>
        <span class="meta">${whereSaid(entry)}${entry.preview ? `<span class="preview">${esc(entry.preview)}</span>` : ""}` +
        `<span class="type">${esc(typeLabel(entry))}</span></span></span></a>`;
    }
    if (entry.is_dir) {
      return `<a class="row has-icon folder" href="${hrefOf(entry)}" ${itemAttrs(entry)}>${check}
        <span class="icon">${own.folder}</span>
        <span class="main"><span class="title">${esc(entry.name)}</span></span>
        <span class="chevron">${icons.chevronRight}</span></a>`;
    }
    return `<a class="row has-icon" href="${hrefOf(entry)}" ${itemAttrs(entry)}>${check}
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
    const thumb = kind === "image" ? ` data-thumb="${esc(entry.id)}" data-stamp="${esc(entry.rev)}"` : "";
    return `<a class="tile ${kind}" href="${hrefOf(entry)}" ${itemAttrs(entry)}${thumb}>
      <span class="thumb">${check}<span class="icon">${entry.is_dir ? own.folderFull : own[kind] || own.file}</span></span>
      <span class="name">${esc(entry.name)}</span></a>`;
  };
  let watcher = null;
  let sorted = [];
  // What the search found, or null when there is none on: the listing is
  // those instead, each saying where it is.
  let found = null;
  const show = () => {
    sortEl.innerHTML = SORTS.map(([key, label]) => {
      const active = key === choice.key;
      const arrow = active ? (choice.dir === "asc" ? own.up : own.down) : "";
      return `<button class="${active ? "active" : ""}" data-sort="${key}" aria-pressed="${active}">${label}${arrow}</button>`;
    }).join("");
    viewEl.innerHTML = VIEWS.map(([key, label]) =>
      `<button class="${key === view ? "active" : ""}" data-view="${key}" aria-pressed="${key === view}" aria-label="${label}">${own[key]}</button>`).join("");
    if (watcher) { watcher.disconnect(); watcher = null; }
    sorted = sortEntries(found !== null ? found : shown(), choice);
    if (emptyEl) emptyEl.hidden = !sorted.length;
    selectEl.hidden = !sorted.length && !selecting;
    if (!sorted.length) {
      listingEl.innerHTML = found !== null
        ? `<p class="empty"><b>Nothing found</b>No name or line in here says “${esc(findInput.value.trim())}”.</p>`
        : isTrash
        ? `<p class="empty mascot"><b>The ${esc(b.trash)} is empty</b>What you delete waits here before it goes for good.</p>`
        : `<p class="empty mascot"><b>Nothing here yet</b>This folder is empty.${takesIn ? " Add something with the plus." : ""}</p>`;
    } else if (view === "grid") {
      listingEl.innerHTML = `<div class="tiles">${sorted.map(tile).join("")}</div>`;
      watcher = watchTiles(b, listingEl);
    } else {
      listingEl.innerHTML = `<div class="group">${sorted.map(row).join("")}</div>`;
    }
    showSelection();
  };

  // -- several at once ------------------------------------------------------------
  // Select, or Shift or Ctrl with a click, picks; Shift from the last one
  // picked takes the run between. Picked, a click picks rather than opens.
  const picked = new Set();
  let selecting = false;
  let anchorId = null;
  const byId = (id) => sorted.find((e) => e.id === id);
  const chosen = () => sorted.filter((e) => picked.has(e.id));
  const showSelection = () => {
    for (const id of [...picked]) if (!byId(id)) picked.delete(id);
    mainEl.classList.toggle("selecting", selecting);
    selectEl.textContent = selecting ? "Done" : "Select";
    selectEl.setAttribute("aria-pressed", String(selecting));
    barEl.hidden = !selecting;
    barEl.querySelector(".count").textContent = `${picked.size} selected`;
    for (const button of barEl.querySelectorAll("[data-bulk]")) button.disabled = !picked.size;
    for (const el of listingEl.querySelectorAll("[data-id]")) el.classList.toggle("picked", picked.has(el.dataset.id));
  };
  const setSelecting = (on) => {
    selecting = on;
    if (!on) { picked.clear(); anchorId = null; }
    showSelection();
  };
  selectEl.addEventListener("click", () => setSelecting(!selecting));
  barEl.querySelector(".all").addEventListener("click", () => {
    for (const entry of sorted) picked.add(entry.id);
    showSelection();
  });
  listingEl.addEventListener("click", (event) => {
    const item = event.target.closest("[data-id]");
    if (!item || !(selecting || event.ctrlKey || event.metaKey || event.shiftKey)) return;
    event.preventDefault();
    const id = item.dataset.id;
    if (event.shiftKey && anchorId && byId(anchorId)) {
      const ids = sorted.map((e) => e.id);
      const [from, to] = [ids.indexOf(anchorId), ids.indexOf(id)].sort((p, q) => p - q);
      for (const one of ids.slice(from, to + 1)) picked.add(one);
    } else if (picked.has(id)) picked.delete(id);
    else picked.add(id);
    anchorId = id;
    selecting = true;
    showSelection();
  });
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
    entries = await list();
    if (found !== null) await find();
    else show();
  };
  const place = { b, group, folder };

  // -- the search ------------------------------------------------------------------
  // Through the folder and everything under it, as typed, a moment after
  // the last letter; the hits are files, with the line that matched.
  let asked = 0;
  const find = async () => {
    const q = findInput.value.trim();
    const turn = ++asked;
    if (!q) { found = null; show(); return; }
    const query = `?${encodeURIComponent(b.group)}=${encodeURIComponent(group)}` +
      `&within=${encodeURIComponent(folder)}&q=${encodeURIComponent(q)}`;
    let hits;
    try { hits = await api("GET", recordsUrl(b.model.id) + query); }
    catch (err) { if (turn === asked) toast(err.message); return; }
    if (turn !== asked) return;
    found = hits.map((r) => ({ ...entryOf(b, r), preview: String(r.fields.preview || "") }))
      .filter((e) => !(b.trash && !folder && (e.folder === b.trash || e.folder.startsWith(b.trash + "/"))));
    show();
  };
  let typing = null;
  const openFind = (on) => {
    findInput.hidden = !on;
    findEl.setAttribute("aria-pressed", String(on));
    mainEl.classList.toggle("finding", on);
    if (on) { findInput.focus(); return; }
    findInput.value = "";
    found = null;
    show();
  };
  findEl.addEventListener("click", () => openFind(findInput.hidden));
  findInput.addEventListener("input", () => {
    clearTimeout(typing);
    typing = setTimeout(find, 250);
  });
  findInput.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { event.preventDefault(); openFind(false); }
    if (event.key === "Enter") { event.preventDefault(); clearTimeout(typing); find(); }
  });
  barEl.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-bulk]");
    if (!button) return;
    const said = await changeMany(b, chosen(), button.dataset.bulk);
    if (said) toast(said);
    setSelecting(false);
    await reload();
  });

  // -- the menu on a row, a tile, and the room around them ------------------------
  const editHash = (e, id) =>
    `#/r/${encodeURIComponent(e.quill.id)}/${encodeURIComponent(e.screen.id)}/${encodeURIComponent(e.screen.model)}/${encodeURIComponent(id)}`;
  const editors = (entry) => (entry.is_dir || entry.deleted ? [] : editorsFor(entry.name)
    .filter((e) => e.screen.model === b.model.id)
    .map((e) => ({ label: `Edit with ${e.quill.name}`, run: () => go(editHash(e, entry.id)) })));
  const act = async (entry, what) => {
    const done = await change(b, entry, what);
    if (!done) return;
    const said = saidDone(done, entry.name);
    if (said) toast(said);
    await reload();
  };
  const choicesFor = (entry) => {
    const open = [{ label: "Open", run: () => go(hrefOf(entry)) }, ...editors(entry)];
    if (inTrash) {
      return b.writes ? [...open, { sep: true },
        { label: "Restore", run: () => act(entry, "restore") },
        { label: "Delete for good", tone: "danger", run: () => act(entry, "delete") }] : open;
    }
    const copy = { label: "Copy to…", run: () => act(entry, "copy") };
    if (!b.writes) return [...open, { sep: true }, copy];
    return [...open, { sep: true },
      { label: "Rename…", run: () => act(entry, "rename") },
      { label: "Duplicate", run: () => act(entry, "duplicate") },
      copy,
      { label: "Move to…", run: () => act(entry, "move") },
      { sep: true },
      { label: "Delete", tone: "danger", run: () => act(entry, "delete") }];
  };
  const blank = (event) => (takesIn && !event.target.closest(".heading, .sort-row, .choose-bar, button, input") ? [
    { label: "New folder…", run: () => newFolder(place, reload) },
    { label: "New text file…", run: () => newTextFile(place, reload) },
    { sep: true },
    { label: "Choose a file…", run: () => app.querySelector(".pick-input").click() },
  ] : null);
  contextMenus(mainEl, "[data-id]", (el) => {
    const entry = byId(el.dataset.id);
    return entry ? choicesFor(entry) : null;
  }, { blank });

  // Nothing goes in, by any of the ways below, where nothing may be written.
  openFolder = null;
  if (!b.writes) return;

  const more = app.querySelector(".heading .more");
  if (more) {
    // Which choices depends on where the folder is: one in the Trash is
    // restored or deleted for good, not renamed or moved about in there.
    more.addEventListener("click", async () => {
      const here = await folderEntry(b, group, folder);
      if (!here) return;
      openSheet(here.deleted ? [
        { icon: own.restore, label: "Restore folder", run: () => folderAction(at, place, "restore", here) },
        { icon: icons.trash, label: "Delete folder for good", bad: true, run: () => folderAction(at, place, "delete", here) },
      ] : [
        { icon: own.rename, label: "Rename folder", run: () => folderAction(at, place, "rename", here) },
        { icon: own.copy, label: "Duplicate folder", run: () => folderAction(at, place, "duplicate", here) },
        { icon: own.copy, label: "Copy folder to…", run: () => folderAction(at, place, "copy", here) },
        { icon: own.move, label: "Move folder to…", run: () => folderAction(at, place, "move", here) },
        { icon: icons.trash, label: "Delete folder", bad: true, run: () => folderAction(at, place, "delete", here) },
      ]);
    });
  }
  if (emptyEl) emptyEl.addEventListener("click", () => emptyTrash(place, reload));
  if (!takesIn) return;

  // -- dragged onto a folder ---------------------------------------------------------
  // A row or tile dragged onto a folder moves there — with everything
  // picked, when the one dragged is among it. The folder lights up on the
  // way over; what is dragged fades. A drag carrying the computer's own
  // files is the drop below, not this.
  let dragging = null;
  listingEl.addEventListener("dragstart", (event) => {
    const item = event.target.closest("[data-id]");
    if (!item) return;
    const id = item.dataset.id;
    dragging = picked.has(id) ? chosen() : [byId(id)].filter(Boolean);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", id);
    item.classList.add("dragging");
  });
  const dropFolder = (event) => {
    if (!dragging) return null;
    const item = event.target.closest("[data-id]");
    const target = item && byId(item.dataset.id);
    if (!target || !target.is_dir || dragging.some((e) => e.id === target.id)) return null;
    return { item, target };
  };
  listingEl.addEventListener("dragover", (event) => {
    const over = dropFolder(event);
    for (const el of listingEl.querySelectorAll(".drop-target")) if (!over || el !== over.item) el.classList.remove("drop-target");
    if (!over) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    over.item.classList.add("drop-target");
  });
  listingEl.addEventListener("dragend", () => {
    dragging = null;
    for (const el of listingEl.querySelectorAll(".dragging, .drop-target")) el.classList.remove("dragging", "drop-target");
  });
  listingEl.addEventListener("drop", async (event) => {
    const over = dropFolder(event);
    if (!over) return;
    event.preventDefault();
    event.stopPropagation();
    const moving = dragging;
    dragging = null;
    const said = await moveAll(b, moving, joinPath(folder, over.target.name), over.target.name);
    if (said) toast(said);
    setSelecting(false);
    await reload();
  });

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
// page, because `mount` leaves the old one detached.
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
  const stamp = `${localDay(now)} ${pad2(now.getHours())}.${pad2(now.getMinutes())}.${pad2(now.getSeconds())}`;
  const ext = (file.type.split("/")[1] || "jpg").replace("jpeg", "jpg");
  return `Photo ${stamp}.${ext}`;
}

async function uploadOne({ b, group, folder }, file, name) {
  const query = `?${encodeURIComponent(b.group)}=${encodeURIComponent(group)}` +
    `&${encodeURIComponent(b.folder)}=${encodeURIComponent(folder)}` +
    `&${encodeURIComponent(b.title)}=${encodeURIComponent(name)}`;
  const res = await apiRaw("POST", recordsUrl(b.model.id) + "/upload" + query, {
    body: file, type: file.type || "application/octet-stream", fail: "upload failed",
  });
  return res.json().catch(() => null);
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
  const name = (await askText("Folder name") || "").trim();
  if (!name) return;
  try {
    await api("POST", recordsUrl(b.model.id), {
      fields: { [b.group]: group, [b.folder]: folder, [b.title]: name, [b.kind]: "folder" },
    });
    toast("Made " + name);
    await reload();
  } catch (err) { toast(err.message); }
}

/** An empty text file, by any name: notes.md, todo.txt; one with no suffix is Markdown. */
async function newTextFile(place, reload) {
  let name = (await askText("File name", "", { placeholder: "notes.md" }) || "").trim();
  if (!name) return;
  if (!name.includes(".")) name += ".md";
  await uploadAll(place, [[new Blob([], { type: "text/plain" }), name]]);
  await reload();
}

// -- renaming, moving, deleting, restoring, copying -------------------------------------------
/** Where a picked folder is, in a few words. */
const placeSaid = (to) => (to.folder ? baseName(to.folder) : to.label);

/** What was done to a record: the record as it is now; `{ deleted: true }`
    when it went to the Trash, `{ gone: true }` when it went for good,
    `{ copied, to }` or `{ duplicated, name }` for a copy; or null when
    nothing happened. */
async function change(b, entry, what) {
  const noun = entry.is_dir ? "folder" : b.model.label.toLowerCase();
  try {
    if (what === "rename") {
      const name = (await askText(`Rename the ${noun}`, entry.name) || "").trim();
      if (!name || name === entry.name) return null;
      return await api("PATCH", recordsUrl(b.model.id, entry.id), { fields: { [b.title]: name }, rev: entry.rev });
    }
    if (what === "move") {
      // A folder in the same group, picked: a file does not leave its group.
      const to = await pickFolder({ title: `Move “${entry.name}” to`, model: b.model.id, within: entry.group, button: "Move here", not: [b.trash] });
      if (!to || to.folder === entry.folder) return null;
      return await api("PATCH", recordsUrl(b.model.id, entry.id), { fields: { [b.folder]: to.folder }, rev: entry.rev });
    }
    if (what === "copy") {
      const to = await pickFolder({ title: `Copy “${entry.name}” to`, model: b.model.id, button: "Copy here", not: [b.trash] });
      if (!to) return null;
      await api("POST", recordsUrl(b.model.id, entry.id) + "/copy", { fields: { [b.group]: to.group, [b.folder]: to.folder } });
      return { copied: true, to };
    }
    if (what === "duplicate") {
      const made = await api("POST", recordsUrl(b.model.id, entry.id) + "/copy", { fields: {} });
      return { duplicated: true, name: String(made.fields[b.title] || "") };
    }
    if (what === "restore") {
      // Back where it was: the server makes the folders on the way if they
      // are gone, and numbers the name if it is taken since.
      const to = entry.deletedFrom || entry.name;
      const fields = { [b.folder]: folderOf(to), [b.title]: baseName(to) };
      return await api("PATCH", recordsUrl(b.model.id, entry.id), { fields, rev: entry.rev });
    }
    if (what === "delete") {
      const contents = entry.is_dir ? " Everything in it goes with it." : "";
      if (entry.deleted || !b.deleted) {
        // For good: in the Trash already, or on a screen without one.
        const warning = entry.deleted ? ` It cannot be restored after this.${contents}` : contents;
        if (!await ask(`Delete “${entry.name}” for good?${warning ? "\n\n" + warning.trim() : ""}`)) return null;
        await api("DELETE", recordsUrl(b.model.id, entry.id));
        return { gone: true };
      }
      if (!await ask(`Move “${entry.name}” to the Trash?${contents ? "\n\n" + contents.trim() : ""}`, { yes: "Move" })) return null;
      await api("DELETE", recordsUrl(b.model.id, entry.id));
      return { deleted: true };
    }
  } catch (err) {
    toast(err.status === 409 ? "That changed somewhere else; look again" : err.message);
  }
  return null;
}

/** What was done, said in a few words. */
const saidDone = (done, name) =>
  done.gone ? `Deleted ${name} for good` : done.deleted ? `Moved ${name} to the Trash` : done.restored ? `Restored ${name}`
    : done.copied ? `Copied ${name} to ${placeSaid(done.to)}` : done.duplicated ? `Made ${done.name}` : "";

/** Several moved into one folder: what was done, in a few words, or "" when nothing was. */
async function moveAll(b, entries, folderPath, said) {
  const moving = entries.filter((e) => e.folder !== folderPath);
  if (!moving.length) return "";
  try {
    for (const entry of moving) {
      await api("PATCH", recordsUrl(b.model.id, entry.id), { fields: { [b.folder]: folderPath }, rev: entry.rev });
    }
  } catch (err) {
    toast(err.status === 409 ? "That changed somewhere else; look again" : err.message);
    return "";
  }
  return `Moved ${moving.length === 1 ? moving[0].name : moving.length + " items"} to ${said}`;
}

/** The same to several at once — one question, one folder picked — and
    what was done, in a few words, or "" when nothing was. */
async function changeMany(b, entries, what) {
  const n = entries.length;
  if (!n) return "";
  const them = n === 1 ? `“${entries[0].name}”` : `${n} items`;
  try {
    if (what === "delete") {
      const forGood = Boolean(entries[0].deleted) || !b.deleted;
      const yes = forGood
        ? await ask(`Delete ${them} for good?\n\nIt cannot be undone.`)
        : await ask(`Move ${them} to the Trash?`, { yes: "Move" });
      if (!yes) return "";
      for (const entry of entries) await api("DELETE", recordsUrl(b.model.id, entry.id));
      return forGood ? `Deleted ${them} for good` : `Moved ${them} to the Trash`;
    }
    if (what === "restore") {
      for (const entry of entries) {
        const to = entry.deletedFrom || entry.name;
        await api("PATCH", recordsUrl(b.model.id, entry.id), { fields: { [b.folder]: folderOf(to), [b.title]: baseName(to) }, rev: entry.rev });
      }
      return `Restored ${them}`;
    }
    if (what === "move") {
      const to = await pickFolder({ title: `Move ${them} to`, model: b.model.id, within: entries[0].group, button: "Move here", not: [b.trash] });
      if (!to) return "";
      return await moveAll(b, entries, to.folder, placeSaid(to));
    }
    if (what === "copy") {
      const to = await pickFolder({ title: `Copy ${them} to`, model: b.model.id, button: "Copy here", not: [b.trash] });
      if (!to) return "";
      for (const entry of entries) {
        await api("POST", recordsUrl(b.model.id, entry.id) + "/copy", { fields: { [b.group]: to.group, [b.folder]: to.folder } });
      }
      return `Copied ${them} to ${placeSaid(to)}`;
    }
  } catch (err) {
    toast(err.status === 409 ? "That changed somewhere else; look again" : err.message);
  }
  return "";
}

/** The Trash, emptied: deleting the folder itself is how the server takes it. */
async function emptyTrash({ b, group, folder }, reload) {
  const trash = await folderEntry(b, group, folder);
  if (!trash) return;
  if (!await ask(`Empty the ${trash.name}?\n\nEverything in it is deleted for good.`, { yes: "Empty", tone: "danger" })) return;
  try {
    await api("DELETE", recordsUrl(b.model.id, trash.id));
    toast(`Emptied the ${trash.name}`);
    await reload();
  } catch (err) { toast(err.message); }
}

/** The folder's own record, which is in the listing of the folder it is in. */
async function folderEntry(b, group, folder) {
  let entry;
  try {
    entry = (await listFolder(b, group, folderOf(folder))).find((e) => e.is_dir && e.name === baseName(folder));
  } catch (err) { toast(err.message); return null; }
  if (!entry) toast("That folder is gone");
  return entry || null;
}

async function folderAction(at, { b, group, folder }, what, entry = null) {
  entry = entry || await folderEntry(b, group, folder);
  if (!entry) return;
  const done = await change(b, entry, what);
  if (!done) return;
  if (done.deleted || done.gone) {
    toast(saidDone(done, entry.name));
    back(folderHash(at, group, folderOf(folder)));
    return;
  }
  if (done.copied || done.duplicated) {
    toast(saidDone(done, entry.name));
    return;
  }
  const moved = entryOf(b, done);
  if (what === "restore") toast(saidDone({ restored: true }, entry.name));
  replace(folderHash(at, group, joinPath(moved.folder, moved.name)));
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
  const res = await apiRaw("GET", recordsUrl(b.model.id, entry.id) + "/content", {
    fail: (status) => (status === 404 ? `That ${b.model.label.toLowerCase()} is gone` : "Could not fetch it"),
  });
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
  const res = await apiRaw("GET", recordsUrl(b.model.id, id) + "/thumb?size=" + THUMB_SIZE, { fail: "no thumbnail" });
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
  const groupRecord = groups.find((g) => g.id === group);
  if (readOnlyIn(b, groupRecord)) b.writes = false;
  const groupName = groupLabel(b, groupRecord) || group;
  const kind = kindOf(entry);
  const parent = folderHash(at, group, entry.folder);
  const facts = [
    ["Type", typeLabel(entry)],
    ...(b.size ? [["Size", formatSize(entry.size)]] : []),
    ...(entry.modified ? [["Modified", formatDate(entry.modified, { long: true })]] : []),
    ["Where", groupName + (entry.folder ? "/" + entry.folder : "")],
    // In the Trash: when it went there, and where Restore puts it back.
    ...(entry.deleted ? [["Deleted", formatDate(entry.deleted, { long: true })]] : []),
    ...(entry.deleted ? [["Was in", groupName + (folderOf(entry.deletedFrom) ? "/" + folderOf(entry.deletedFrom) : "")]] : []),
  ];
  const actionRow = (what, label, icon, danger = false) =>
    `<button class="row has-icon${danger ? " danger" : ""}" data-do="${what}"><span class="icon">${icon}</span><span class="main"><span class="title">${label}</span></span></button>`;
  // The Quills that edit this kind of file, then what can be done to it:
  // copying needs only reading; the rest, writing; in the Trash, Restore
  // and a Delete that is for good.
  const editRows = entry.deleted ? "" : editorsFor(entry.name).filter((e) => e.screen.model === b.model.id).map((e) =>
    `<a class="row has-icon" href="#/r/${encodeURIComponent(e.quill.id)}/${encodeURIComponent(e.screen.id)}/${encodeURIComponent(e.screen.model)}/${encodeURIComponent(entry.id)}">` +
    `<span class="icon">${own.edit}</span><span class="main"><span class="title">Edit with ${esc(e.quill.name)}</span></span></a>`).join("");
  const copyRow = entry.deleted ? "" : actionRow("copy", "Copy to another folder", own.copy);
  const actions = editRows + copyRow + (entry.deleted ? (b.writes ? `
        ${actionRow("restore", "Restore", own.restore)}
        ${actionRow("delete", "Delete for good", icons.trash, true)}` : "") : (b.writes ? `
        ${actionRow("rename", "Rename", own.rename)}
        ${actionRow("duplicate", "Duplicate", own.copy)}
        ${actionRow("move", "Move to another folder", own.move)}
        ${actionRow("delete", "Delete", icons.trash, true)}` : ""));
  const sending = canSendFiles();
  mount(nav({
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
      ${actions ? `<div class="group item-actions">${actions}
      </div>` : ""}
    </main>`);
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
      if (done.copied || done.duplicated) {
        toast(saidDone(done, entry.name));
        return;
      }
      if (done.deleted || done.gone) {
        toast(saidDone(done, entry.name));
        back(parent);
        return;
      }
      if (button.dataset.do === "restore") {
        // Back in its folder, which the page it came from is not any more.
        toast(saidDone({ restored: true }, entry.name));
        replace(folderHash(at, group, entryOf(b, done).folder));
        return renderRoute();
      }
      replace(itemHash(at, b, done.id));
      route();
    });
  }
}
