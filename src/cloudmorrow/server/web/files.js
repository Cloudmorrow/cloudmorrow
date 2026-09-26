/* Files: your own drive on the server, your shares, and what is in them —
   the way a file manager shows a folder. My Files first, then the shares;
   tap one and it is the folders and files in it, sorted by name, date,
   size or kind, as a list or as a grid of thumbnails; tap a picture and it
   is shown. The plus in the bar puts a file in the folder you are in: one
   picked from the phone, or one the camera takes there and then.

   The pages are addresses, so the back button and the swipe both work the
   way they do in Notes: `#/shares`, `#/share/<name>/<folder>`, and
   `#/file/<name>/<path>` for one file.

   A machine share is listed but not opened: its files are on that machine,
   and the server has nothing to show. A picture comes down through fetch,
   as a note's pictures do, because an <img src> cannot carry the token.
   The grid asks the server for small copies, a few at a time and only for
   the tiles that are on the screen, so a folder of a hundred photos is not
   a hundred photos coming down. */

import {
  ApiError, api, app, authHeaders, encodePath, esc, formatDate, heading, icons, nav, onSignOut,
  pixelIcon, registerScreen, registerTab, renderRoute, replace, route, store, tabs, toast, wireShell,
} from "./core.js";
import { call, desktop } from "./desktopbridge.js";

const own = {
  share: '<svg width="22" height="20" viewBox="0 0 22 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="1.5" y="2" width="19" height="6" rx="1.5"/><rect x="1.5" y="12" width="19" height="6" rx="1.5"/><path d="M5 5h.01M5 15h.01" stroke-linecap="round" stroke-width="2.4"/></svg>',
  machine: '<svg width="22" height="20" viewBox="0 0 22 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="1.5" y="2.5" width="19" height="12" rx="1.5"/><path d="M7 17.5h8M11 14.5v3"/></svg>',
  drive: '<svg width="22" height="20" viewBox="0 0 22 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 12.5V5a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2v7.5"/><rect x="1.5" y="12.5" width="19" height="5.5" rx="1.5"/><path d="M16.5 15.25h.01" stroke-width="2.4"/></svg>',
  folder: '<svg width="22" height="18" viewBox="0 0 22 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M1.5 3.5A1.5 1.5 0 0 1 3 2h5l2 2.5h9a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5H3a1.5 1.5 0 0 1-1.5-1.5z"/></svg>',
  file: '<svg width="20" height="22" viewBox="0 0 20 22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M3.5 2h8l5 5v13a1 1 0 0 1-1 1h-12a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z"/><path d="M11.5 2v5h5"/></svg>',
  image: '<svg width="22" height="20" viewBox="0 0 22 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="1.5" y="2" width="19" height="16" rx="2"/><circle cx="7.5" cy="7.5" r="2"/><path d="m20.5 14-5-5-8 8"/></svg>',
  video: '<svg width="22" height="20" viewBox="0 0 22 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="1.5" y="3" width="13" height="14" rx="2"/><path d="m14.5 8 6-3v10l-6-3z"/></svg>',
  audio: '<svg width="20" height="22" viewBox="0 0 20 22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7 16.5V5l10-2v11.5"/><circle cx="4.5" cy="16.5" r="2.5"/><circle cx="14.5" cy="14.5" r="2.5"/></svg>',
  text: '<svg width="20" height="22" viewBox="0 0 20 22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 2h8l5 5v13a1 1 0 0 1-1 1h-12a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z"/><path d="M6.5 11h7M6.5 14.5h7M6.5 18h4"/></svg>',
  archive: '<svg width="20" height="22" viewBox="0 0 20 22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="2" width="15" height="18" rx="2"/><path d="M8 2v3M8 7v3M8 12v3M6.5 15h3v3h-3z"/></svg>',
  download: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12M7 10l5 5 5-5M4 19h16"/></svg>',
  share: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V3M7.5 7.5 12 3l4.5 4.5M5 12v7a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-7"/></svg>',
  up: '<svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 9V1M1.5 4.5 5 1l3.5 3.5"/></svg>',
  plus: '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  pick: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
  camera: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13" r="3.5"/></svg>',
  down: '<svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 1v8M1.5 5.5 5 9l3.5-3.5"/></svg>',
  list: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 4h9M6 9h9M6 14h9M3 4h.01M3 9h.01M3 14h.01"/></svg>',
  grid: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="2" y="2" width="5.5" height="5.5" rx="1"/><rect x="10.5" y="2" width="5.5" height="5.5" rx="1"/><rect x="2" y="10.5" width="5.5" height="5.5" rx="1"/><rect x="10.5" y="10.5" width="5.5" height="5.5" rx="1"/></svg>',
};

const baseName = (path) => path.slice(path.lastIndexOf("/") + 1);
const folderOf = (path) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");
const join = (folder, name) => (folder ? folder + "/" + name : name);
const extOf = (name) => (name.includes(".") ? name.slice(name.lastIndexOf(".") + 1).toLowerCase() : "");

// The drive every account has on the server. The server calls it my-files
// and serves it as a share; the screen calls it what it is.
const DRIVE = "my-files";
const shareLabel = (name) => (name === DRIVE ? "My Files" : name);

const shareHash = (name, path) => "#/share/" + encodeURIComponent(name) + (path ? "/" + encodePath(path) : "");
const fileHash = (name, path) => "#/file/" + encodeURIComponent(name) + "/" + encodePath(path);
// The hash after `#/share/` or `#/file/`: the share's name, then the path in it.
function splitArg(arg) {
  const slash = arg.indexOf("/");
  return slash === -1 ? [arg, ""] : [arg.slice(0, slash), arg.slice(slash + 1)];
}

// -- what a file is -------------------------------------------------------------
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

// -- sorting ----------------------------------------------------------------------
// Name, date, size or type; tapping the one in use turns it around. Folders
// come first whichever it is, as a file manager has them, and the choice is
// kept so every folder opens the way the last one was left.
const SORTS = [["name", "Name"], ["date", "Date"], ["size", "Size"], ["type", "Type"]];
const DEFAULT_DIR = { name: "asc", date: "desc", size: "desc", type: "asc" };
function sortChoice() {
  try {
    const saved = JSON.parse(store.get("files.sort") || "null");
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
  const files = entries.filter((e) => !e.is_dir).sort((a, b) => sign * compare(a, b));
  return [...folders, ...files];
}

// -- list or grid ------------------------------------------------------------------
// A list says when and how big; a grid shows what a picture is of. Kept the
// way the sort is, so a folder opens the way the last one was left.
const VIEWS = [["list", "List"], ["grid", "Thumbnails"]];
function viewChoice() {
  const saved = store.get("files.view");
  return VIEWS.some(([key]) => key === saved) ? saved : "list";
}

// -- the shares -------------------------------------------------------------------
async function renderShares() {
  // In the desktop app, what this computer has mounted comes with the list,
  // so the page is drawn once with it rather than twice.
  const [listed, here] = await Promise.all([
    api("GET", "/api/shares"), desktop() ? call("mounted_here") : null,
  ]);
  const mountRow = here ? (share) => mountLine(share, here.mounts || {}) : () => "";
  // The drive comes first from the server; here it stands on its own above
  // the shares, so what is yours and what is shared are not one list.
  const drives = listed.filter((share) => share.kind === "drive");
  const shares = listed.filter((share) => share.kind !== "drive");
  const rowOf = (share) => {
    if (share.kind === "drive") {
      return `<a class="row has-icon" href="${shareHash(share.name)}">
        <span class="icon">${own.drive}</span>
        <span class="main"><span class="title">${esc(shareLabel(share.name))}</span>
        <span class="meta"><span class="preview">${esc(share.description || "on the server")}</span></span></span>
        <span class="chevron">${icons.chevronRight}</span></a>`;
    }
    if (share.kind === "machine") {
      const where = share.online ? `on ${share.machine}` : `on ${share.machine}, offline`;
      return `<div class="row has-icon machine">
        <span class="icon">${own.machine}</span>
        <span class="main"><span class="title">${esc(share.name)}</span>
        <span class="meta"><span class="preview">${esc(where)} — mount it to browse it</span></span></span></div>`;
    }
    return `<a class="row has-icon" href="${shareHash(share.name)}">
      <span class="icon">${own.share}</span>
      <span class="main"><span class="title">${esc(share.name)}</span>
      <span class="meta"><span class="preview">${esc(share.description || "on the server")}</span></span></span>
      <span class="chevron">${icons.chevronRight}</span></a>`;
  };
  const driveRows = drives.map((share) => rowOf(share) + mountRow(share)).join("");
  const shareRows = shares.map((share) => rowOf(share) + mountRow(share)).join("");
  app.innerHTML = nav({ title: "Files" }) + `
    <main>
      ${heading("Files")}
      ${driveRows ? `<div class="group">${driveRows}</div>` : ""}
      <div class="group-label">Shares</div>
      ${shareRows ? `<div class="group">${shareRows}</div>`
        : `<p class="empty"><b>No shares yet</b>A share is made in the terminal app's Files tab.</p>`}
    </main>` + tabs("files");
  wireShell();
  wireMounts();
}

// -- on this computer, in the desktop app ------------------------------------------------
// Under each share, a line of its own: where it is mounted here and the way
// to it, or the button that mounts it. Only the desktop app draws it — a
// browser cannot mount anything — and it is the same mount the terminal app
// and `cm share mount` make, so all three agree on what is mounted.
// Mounting is Cloud blue: a strong choice, but not the one thing Files is for.
function mountLine(share, mounted) {
  const here = mounted[share.name] || {};
  let words;
  let buttons = "";
  if (here.mounted) {
    words = "Mounted at " + here.path;
    buttons = `<button class="desk-button ghost" data-open="${esc(here.path)}">Open folder</button>` +
      `<button class="desk-button ghost" data-unmount="${esc(share.name)}">Unmount</button>`;
  } else if (share.kind === "machine" && !share.online) {
    words = "Not mounted — its machine is offline";
  } else {
    words = "Not mounted on this computer";
    buttons = `<button class="desk-button cloud" data-mount="${esc(share.name)}">Mount on this computer</button>`;
  }
  return `<div class="row mount-row${here.mounted ? " on" : ""}">` +
    `<span class="main"><span class="meta"><span class="preview">${esc(words)}</span></span></span>` +
    (buttons ? `<span class="mount-actions">${buttons}</span>` : "") + `</div>`;
}

function wireMounts() {
  // One at a time: a mount waits for rclone, and a second click meanwhile
  // would only be refused.
  const act = (button, busy, method, done) => button.addEventListener("click", async () => {
    for (const other of app.querySelectorAll(".mount-actions button")) other.disabled = true;
    button.textContent = busy;
    const answer = await call(method, button.dataset[method]);
    toast(answer.error || done(answer), answer.error ? 6000 : 2200);
    route();
  });
  for (const button of app.querySelectorAll("[data-mount]")) {
    act(button, "Mounting…", "mount", (answer) => "Mounted at " + answer.path);
  }
  for (const button of app.querySelectorAll("[data-unmount]")) {
    act(button, "Unmounting…", "unmount", () => "Unmounted");
  }
  for (const button of app.querySelectorAll("[data-open]")) {
    button.addEventListener("click", async () => {
      const answer = await call("open_folder", button.dataset.open);
      if (answer.error) toast(answer.error, 6000);
    });
  }
}

// -- a folder in a share ------------------------------------------------------------
async function renderFolder(arg) {
  const [share, path] = splitArg(arg);
  if (!share) { replace("#/shares"); return renderRoute(); }
  let listing;
  try {
    listing = await api("GET", "/api/shares/" + encodeURIComponent(share) + "/ls?path=" + encodeURIComponent(path));
  } catch (err) {
    if (err.status === 404) {
      toast(path ? "That folder is gone" : "That share is gone");
      replace(path ? shareHash(share) : "#/shares");
      return renderRoute();
    }
    if (err.status === 409) { toast(err.message); replace("#/shares"); return renderRoute(); }
    throw err;
  }
  const parent = path ? shareHash(share, folderOf(path)) : "#/shares";
  const parentLabel = path ? (folderOf(path) ? baseName(folderOf(path)) : shareLabel(share)) : "Files";
  const title = path ? baseName(path) : shareLabel(share);
  app.innerHTML = nav({ back: parent, backLabel: parentLabel, title }) + `
    <main>
      ${heading(title, `<button class="add" aria-label="Add a file">${own.plus}</button>`)}
      <div class="sort-row">
        <div class="sort" role="group" aria-label="Sort by"></div>
        <div class="view-switch" role="group" aria-label="Show as"></div>
      </div>
      <div class="listing"></div>
      <input type="file" class="pick-input" multiple hidden>
      <input type="file" class="camera-input" accept="image/*" capture="environment" hidden>
    </main>` + tabs("files");
  wireShell();

  const sortEl = app.querySelector(".sort");
  const viewEl = app.querySelector(".view-switch");
  const listingEl = app.querySelector(".listing");
  let choice = sortChoice();
  let view = viewChoice();

  const row = (entry) => {
    const kind = kindOf(entry);
    const target = join(path, entry.name);
    if (entry.is_dir) {
      return `<a class="row has-icon" href="${shareHash(share, target)}">
        <span class="icon">${own.folder}</span>
        <span class="main"><span class="title">${esc(entry.name)}</span></span>
        <span class="chevron">${icons.chevronRight}</span></a>`;
    }
    return `<a class="row has-icon" href="${fileHash(share, target)}">
      <span class="icon">${own[kind] || own.file}</span>
      <span class="main"><span class="title">${esc(entry.name)}</span>
      <span class="meta"><span class="date">${esc(formatDate(entry.modified))}</span>` +
      `<span class="size">${esc(formatSize(entry.size))}</span>` +
      `<span class="type">${esc(typeLabel(entry))}</span></span></span></a>`;
  };
  // A tile: the picture itself where the server can make one small, else
  // the kind's icon — and its name under it. The picture comes when the
  // tile scrolls into view, not before.
  const tile = (entry) => {
    const kind = kindOf(entry);
    const target = join(path, entry.name);
    const href = entry.is_dir ? shareHash(share, target) : fileHash(share, target);
    const thumb = kind === "image" ? ` data-thumb="${esc(target)}" data-stamp="${entry.modified}"` : "";
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
    const entries = sortEntries(listing.entries, choice);
    if (!entries.length) {
      listingEl.innerHTML = `<p class="empty mascot"><b>Nothing here yet</b>This folder is empty. Add a file with the plus.</p>`;
    } else if (view === "grid") {
      listingEl.innerHTML = `<div class="tiles">${entries.map(tile).join("")}</div>`;
      watcher = watchTiles(share, listingEl);
    } else {
      listingEl.innerHTML = `<div class="group">${entries.map(row).join("")}</div>`;
    }
  };
  show();
  viewEl.addEventListener("click", (event) => {
    const button = event.target.closest("[data-view]");
    if (!button || button.dataset.view === view) return;
    view = button.dataset.view;
    store.set("files.view", view);
    show();
  });
  sortEl.addEventListener("click", (event) => {
    const button = event.target.closest("[data-sort]");
    if (!button) return;
    const key = button.dataset.sort;
    choice = key === choice.key
      ? { key, dir: choice.dir === "asc" ? "desc" : "asc" }
      : { key, dir: DEFAULT_DIR[key] };
    store.set("files.sort", JSON.stringify(choice));
    show();
  });

  // Adding: the plus opens a sheet with the two ways in. Either ends in a
  // file input, which has to be clicked from the tap itself for the phone
  // to open its picker or its camera.
  const pickInput = app.querySelector(".pick-input");
  const cameraInput = app.querySelector(".camera-input");
  app.querySelector(".heading .add").addEventListener("click", () => openSheet([
    { icon: own.pick, label: "Choose a file", run: () => pickInput.click() },
    { icon: own.camera, label: "Take a photo", run: () => cameraInput.click() },
  ]));
  const reload = async () => {
    listing = await api("GET", "/api/shares/" + encodeURIComponent(share) + "/ls?path=" + encodeURIComponent(path));
    show();
  };
  pickInput.addEventListener("change", async () => {
    const files = [...pickInput.files];
    pickInput.value = "";
    await uploadAll(share, path, files.map((file) => [file, file.name]));
    await reload();
  });
  // The two ways a computer puts a file somewhere: dragged onto the
  // folder, or pasted into it. Both end where the picker ends, so there
  // is one upload and one reload however the file arrived. A phone has
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
    const files = [...event.dataTransfer.files];
    if (!files.length) return;
    await uploadAll(share, path, files.map((file) => [file, file.name]));
    await reload();
  });
  // A paste lands on the document when nothing is focused, so it cannot
  // be hung off this screen's own elements; the one listener below reads
  // this instead, and checks the screen it names is still the one up.
  openFolder = { main: mainEl, share, path, reload };

  cameraInput.addEventListener("change", async () => {
    const files = [...cameraInput.files];
    cameraInput.value = "";
    // The camera calls every photo image.jpg; the moment it was taken is a
    // better name, and one that sorts.
    await uploadAll(share, path, files.map((file) => [file, photoName(file)]));
    await reload();
  });
}

// -- putting a file in ----------------------------------------------------------------
// The folder on the screen, for the one way in that cannot be hung off an
// element: a paste with nothing focused goes to the document. Set by every
// folder render; the listener checks the screen it names is still on the
// page, because `app.innerHTML` leaves the old one detached.
let openFolder = null;

addEventListener("paste", async (event) => {
  if (!openFolder || !app.contains(openFolder.main)) return;
  const files = [...((event.clipboardData && event.clipboardData.files) || [])];
  if (!files.length) return;
  event.preventDefault();
  const { share, path, reload } = openFolder;
  // A screenshot arrives called image.png every single time, which is no
  // name for the third one. The moment it was taken is, and it sorts.
  await uploadAll(share, path, files.map((file) =>
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

async function uploadOne(share, folder, file, name) {
  const headers = { ...authHeaders(), "Content-Type": file.type || "application/octet-stream" };
  let res;
  try {
    res = await fetch("/api/shares/" + encodeURIComponent(share) + "/upload?path=" + encodeURIComponent(folder) +
      "&filename=" + encodeURIComponent(name), { method: "POST", headers, body: file });
  } catch {
    throw new ApiError(0, "Could not reach the server");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data && data.detail !== undefined ? data.detail : "upload failed");
  return data;
}

// One after another, with the bar saying which; a failure says why and
// stops there, so what did arrive is not lost in a run of errors.
async function uploadAll(share, folder, items) {
  let done = 0;
  for (const [file, name] of items) {
    toast(items.length > 1 ? `Uploading ${name} (${done + 1} of ${items.length})…` : `Uploading ${name}…`, 60000);
    try { await uploadOne(share, folder, file, name); }
    catch (err) { toast(err.message); return; }
    done += 1;
  }
  toast(done === 1 ? "Added " + items[0][1] : `Added ${done} files`);
}

// A sheet from the bottom, the phone's way of asking which of a few
// things you meant. Tapping outside it, or Cancel, is no.
function openSheet(choices) {
  const backdrop = document.createElement("div");
  backdrop.className = "sheet-backdrop";
  backdrop.innerHTML = `<div class="sheet" role="menu">` +
    choices.map((c, i) => `<button class="sheet-row" role="menuitem" data-choice="${i}">${c.icon}<span>${esc(c.label)}</span></button>`).join("") +
    `<button class="sheet-row cancel">Cancel</button></div>`;
  const close = () => backdrop.remove();
  backdrop.addEventListener("click", (event) => {
    const row = event.target.closest("[data-choice]");
    close();
    if (row) choices[Number(row.dataset.choice)].run();
  });
  document.body.appendChild(backdrop);
}

// -- one file --------------------------------------------------------------------------
// A picture is shown; anything else is named. Either can be shared or
// saved. Both come down through fetch with the token, and the bytes are
// kept for the page's life so going back and forth does not fetch twice.
const blobs = new Map();
const blobURLs = new Map();
onSignOut(() => {
  for (const url of blobURLs.values()) URL.revokeObjectURL(url);
  blobURLs.clear();
  blobs.clear();
});

async function fileBlob(share, path) {
  const key = share + "/" + path;
  if (blobs.has(key)) return blobs.get(key);
  let res;
  try {
    res = await fetch("/api/shares/" + encodeURIComponent(share) + "/file?path=" + encodeURIComponent(path), { headers: authHeaders() });
  } catch {
    throw new ApiError(0, "Could not reach the server");
  }
  if (!res.ok) throw new ApiError(res.status, res.status === 404 ? "That file is gone" : "Could not fetch the file");
  const blob = await res.blob();
  blobs.set(key, blob);
  return blob;
}

async function fileBlobURL(share, path) {
  const key = share + "/" + path;
  if (blobURLs.has(key)) return blobURLs.get(key);
  const url = URL.createObjectURL(await fileBlob(share, path));
  blobURLs.set(key, url);
  return url;
}

// -- thumbnails --------------------------------------------------------------------
// A small copy of a picture, from the server, kept for the page's life like
// the files are. The key carries when the file changed, so a picture put
// back under the same name is fetched afresh.
const thumbURLs = new Map();
onSignOut(() => {
  for (const url of thumbURLs.values()) URL.revokeObjectURL(url);
  thumbURLs.clear();
});
// Sharp on a phone's screen, and one size for the whole grid so the
// server makes each picture small once.
const THUMB_SIZE = (window.devicePixelRatio || 1) > 2 ? 512 : 256;

async function thumbURL(share, path, stamp) {
  const key = share + "/" + path + "@" + stamp;
  if (thumbURLs.has(key)) return thumbURLs.get(key);
  const res = await fetch("/api/shares/" + encodeURIComponent(share) + "/thumb?path=" + encodeURIComponent(path) +
    "&size=" + THUMB_SIZE, { headers: authHeaders() });
  if (!res.ok) throw new ApiError(res.status, "no thumbnail");
  const url = URL.createObjectURL(await res.blob());
  thumbURLs.set(key, url);
  return url;
}

// The tiles ask for their pictures as they come into view, a few at a time:
// scrolling fast through a big folder queues what it passed, and the queue
// is what is on the screen now, not everything that ever was.
const THUMBS_AT_ONCE = 4;
function watchTiles(share, root) {
  const waiting = [];
  let inFlight = 0;
  const next = () => {
    while (inFlight < THUMBS_AT_ONCE && waiting.length) {
      const el = waiting.shift();
      if (!el.isConnected || el.classList.contains("has-img")) continue;
      inFlight += 1;
      thumbURL(share, el.dataset.thumb, el.dataset.stamp)
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
const canShareFiles = () => typeof navigator.share === "function" && typeof navigator.canShare === "function";

async function shareOrSave(share, path, name, mime) {
  let blob;
  try { blob = await fileBlob(share, path); }
  catch (err) { toast(err.message); return; }
  if (canShareFiles()) {
    const file = new File([blob], name, { type: blob.type || mime || "application/octet-stream" });
    if (navigator.canShare({ files: [file] })) {
      try { await navigator.share({ files: [file], title: name }); return; }
      catch (err) { if (err.name === "AbortError") return; }
    }
  }
  const link = document.createElement("a");
  link.href = await fileBlobURL(share, path);
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

async function renderFile(arg) {
  const [share, path] = splitArg(arg);
  if (!share || !path) { replace("#/shares"); return renderRoute(); }
  const folder = folderOf(path);
  const name = baseName(path);
  // The file's facts are in its folder's listing; one request, and the
  // same one the folder screen made a moment ago.
  let entry = null;
  try {
    const listing = await api("GET", "/api/shares/" + encodeURIComponent(share) + "/ls?path=" + encodeURIComponent(folder));
    entry = listing.entries.find((e) => e.name === name && !e.is_dir) || null;
  } catch (err) {
    if (err.status !== 404 && err.status !== 409) throw err;
  }
  if (!entry) {
    toast("That file is gone");
    replace(shareHash(share, folder));
    return renderRoute();
  }
  const kind = kindOf(entry);
  const parent = shareHash(share, folder);
  const facts = [
    ["Type", typeLabel(entry)],
    ["Size", formatSize(entry.size)],
    ["Modified", formatDate(entry.modified, { long: true })],
    ["Where", shareLabel(share) + (folder ? "/" + folder : "")],
  ];
  const sharing = canShareFiles();
  app.innerHTML = nav({
    back: parent, backLabel: folder ? baseName(folder) : share, title: name,
    right: `<button class="download" aria-label="${sharing ? "Share" : "Save"}">${sharing ? own.share : own.download}</button>`,
  }) + `
    <main>
      ${kind === "image"
        ? `<figure class="view"><img alt="${esc(name)}"></figure>`
        : `<div class="file-card"><span class="icon">${own[kind] || own.file}</span></div>`}
      <h1 class="large file-name">${esc(name)}</h1>
      <div class="group facts">${facts.map(([label, value]) =>
        `<div class="row"><span class="main">${esc(label)}</span><span class="value">${esc(value)}</span></div>`).join("")}</div>
    </main>`;
  wireShell();
  app.querySelector(".nav").classList.add("lined");

  const img = app.querySelector(".view img");
  if (img) {
    fileBlobURL(share, path)
      .then((url) => { img.src = url; })
      .catch((err) => { toast(err.message); img.closest(".view").classList.add("missing"); });
    // Tap the picture and it fills the screen, on its own; tap again and it is back.
    img.addEventListener("click", () => {
      if (!img.src) return;
      const box = document.createElement("div");
      box.className = "lightbox";
      box.innerHTML = `<img src="${esc(img.src)}" alt="${esc(name)}">`;
      box.addEventListener("click", () => box.remove());
      document.body.appendChild(box);
    });
  }
  // Fetched now, so the share sheet can open straight from the tap.
  fileBlob(share, path).catch(() => { /* said when the tap comes */ });
  app.querySelector(".download").addEventListener("click", () => shareOrSave(share, path, name, entry.mime));
}

// -- what this feature adds to the app -------------------------------------------------
registerScreen("shares", renderShares);
registerScreen("share", renderFolder);
registerScreen("file", renderFile);
registerTab({
  name: "files", label: "Files", icon: pixelIcon("files"), feature: "files",
  href: () => "#/shares",
});
