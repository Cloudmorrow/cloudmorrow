/* The kit's `editor`: pages of Markdown in folders, and the page you are on.

   A screen binds a `model`, its `title`, its Markdown `body`, and — if the
   records have folders — a `path`: a string like `ideas/garden/beds`, whose
   folders are the tree and whose last part is the title. Everything below
   is read from those and from the datamodel's `can`: `folders` when its
   backend keeps folders that exist empty, `attachments` when it keeps
   pictures beside the pages, `search` when a listing answers `?q=`. Nothing
   here knows what a note is.

   On a phone it is the tree, then a list, then the page, one screen at a
   time. On a computer the list and the page are side by side.

   The addresses, under the screen's own (quills.js):
     #/q/<quill>/<screen>                every page, newest first
     #/q/<quill>/<screen>/~folders       the folders
     #/q/<quill>/<screen>/~top           the pages in no folder
     #/q/<quill>/<screen>/<folder>       the pages in a folder
     #/q/<quill>/<screen>/~new[/<folder>] a page not written yet
     #/r/<quill>/<screen>/<model>/<id>   a page */

import {
  SAVE_DELAY, SEARCH_DELAY, api, app, back, encodePath, esc, fileStem, formatDate, heading,
  icons, nav, occupy, previousHash, renderRoute, replace, sectionOf, seconds, setStatus, tabs,
  toast, vacate, wireShell,
} from "./core.js";
import { installCard } from "./install.js";
import { bodyMarkup, bodyText, focusBody, mountBody, photoButton, setBody } from "./pictures.js";

const own = {
  folder: '<svg width="22" height="18" viewBox="0 0 22 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M1.5 3.5A1.5 1.5 0 0 1 3 2h5l2 2.5h9a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5H3a1.5 1.5 0 0 1-1.5-1.5z"/></svg>',
  pages: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="2" width="14" height="16" rx="2"/><path d="M6.5 7h7M6.5 10.5h7M6.5 14h4"/></svg>',
  folderSmall: '<svg width="14" height="12" viewBox="0 0 22 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round"><path d="M1.5 3.5A1.5 1.5 0 0 1 3 2h5l2 2.5h9a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5H3a1.5 1.5 0 0 1-1.5-1.5z"/></svg>',
  newFolder: '<svg width="22" height="18" viewBox="0 0 22 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M1.5 3.5A1.5 1.5 0 0 1 3 2h5l2 2.5h9a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5H3a1.5 1.5 0 0 1-1.5-1.5z"/><path d="M11 7.5v6M8 10.5h6"/></svg>',
};

// A computer, by the same measure desktop.css draws its rail by.
const wide = () => matchMedia("(min-width: 900px) and (min-height: 600px)").matches;

const FOLDERS = "~folders";
const TOP = "~top";
const NEW = "~new";

const folderOf = (path) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");
const baseName = (path) => path.slice(path.lastIndexOf("/") + 1);
const join = (folder, name) => (folder ? folder + "/" + name : name);
const recordsUrl = (model, rest = "") => "/api/records/" + encodeURIComponent(model) + rest;

// -- the screen's bindings ---------------------------------------------------------
function bind(at) {
  const { quill, screen } = at;
  const model = quill.models[screen.model];
  const can = new Set(model.can || []);
  return {
    at,
    model,
    title: screen.title || model.title,
    body: screen.body,
    path: screen.path || "",
    keepsFolders: !!screen.path && can.has("folders"),
    search: can.has("search"),
    attachments: can.has("attachments") ? recordsUrl(model.id, "/_attachments") : "",
    label: screen.label || quill.name,
    noun: model.label.toLowerCase(),
  };
}

const listHash = (b, key) => b.at.base + (key ? "/" + encodePath(key) : "");
const pageArg = (b, id) =>
  `${b.at.quill.id}/${b.at.screen.id}/${b.model.id}/${id}`;
const pageHash = (b, id) =>
  `#/r/${encodeURIComponent(b.at.quill.id)}/${encodeURIComponent(b.at.screen.id)}/${encodeURIComponent(b.model.id)}/${encodeURIComponent(id)}`;

// -- the pages and the folders ---------------------------------------------------------
// [{id, path, title, folder, modified, preview}], and the folders in tree
// order: [{path, name, depth, count}], the top first.
async function load(b) {
  const rows = await api("GET", recordsUrl(b.model.id, "?previews=true"));
  const pages = rows.map((r) => {
    const path = String(r.fields[b.path || b.title] || "");
    return {
      id: r.id,
      path,
      title: String(r.fields[b.title] || "").trim() || baseName(path) || "Untitled",
      folder: b.path ? folderOf(path) : "",
      modified: seconds(r.updated_at) || 0,
      preview: r.preview || "",
    };
  });
  const known = new Set();
  const add = (folder) => { while (folder) { known.add(folder); folder = folderOf(folder); } };
  for (const page of pages) add(page.folder);
  if (b.keepsFolders) {
    try { for (const f of await api("GET", recordsUrl(b.model.id, "/_folders"))) add(f.path); }
    catch { /* the folders there are pages in are still the tree */ }
  }
  const byPath = (x, y) => {
    const a = x.split("/"); const c = y.split("/");
    for (let i = 0; i < Math.min(a.length, c.length); i += 1) {
      const d = a[i].localeCompare(c[i], undefined, { sensitivity: "base" });
      if (d) return d;
    }
    return a.length - c.length;
  };
  const count = (folder) => pages.filter((p) => p.folder === folder).length;
  const folders = [{ path: "", name: b.label, depth: 0, count: count("") }].concat(
    [...known].sort(byPath).map((path) => ({
      path, name: baseName(path), depth: path.split("/").length, count: count(path),
    })));
  return { pages, folders };
}

const byNewest = (a, c) => c.modified - a.modified;

// -- a list: the folders, every page, or one folder's ----------------------------------------
// Returns what the list screen is, for a phone to draw alone and a computer
// to draw beside a page: {title, backTo, backLabel, html, wire}.
function listView(b, data, key, openId = "") {
  const hasFolders = !!b.path;
  const compose = `<a class="button compose" href="${listHash(b, NEW + (key && !key.startsWith("~") ? "/" + key : ""))}" aria-label="New ${esc(b.noun)}">${icons.compose}</a>`;

  if (key === FOLDERS) {
    const rows = data.folders.map((f) => {
      const href = listHash(b, f.path || TOP);
      return `<a class="row has-icon indent-${Math.min(f.depth, 3)}" href="${href}">
        <span class="icon">${own.folder}</span>
        <span class="main"><span class="title">${esc(f.name)}</span></span>
        <span class="count">${f.count}</span><span class="chevron">${icons.chevronRight}</span></a>`;
    }).join("");
    const make = b.keepsFolders ? `<button class="new-folder" aria-label="New folder">${own.newFolder}</button>` : "";
    return {
      title: "Folders",
      html: `${heading("Folders", make)}
        <div class="install-slot">${installCard()}</div>
        <div class="group">
          <a class="row has-icon" href="${listHash(b, "")}">
            <span class="icon">${own.pages}</span>
            <span class="main"><span class="title">All ${esc(b.label)}</span></span>
            <span class="count">${data.pages.length}</span><span class="chevron">${icons.chevronRight}</span></a>
          ${rows}
        </div>`,
      wire(root) {
        const button = root.querySelector(".new-folder");
        if (button) button.addEventListener("click", () => newFolder(b, ""));
      },
    };
  }

  const all = !key;
  const folder = key === TOP ? "" : key;
  const title = all ? `All ${b.label}` : (folder ? baseName(folder) : b.label);
  const scope = all ? data.pages.slice().sort(byNewest)
    : data.pages.filter((p) => p.folder === folder).sort(byNewest);
  const subfolders = all ? [] : data.folders.filter((f) => f.path && folderOf(f.path) === folder);

  const row = (p) => `<a class="row${p.id === openId ? " current" : ""}" href="${pageHash(b, p.id)}">
      <span class="main"><span class="title">${esc(p.title)}</span>
      <span class="meta"><span class="date">${esc(formatDate(p.modified))}</span>` +
      `<span class="preview">${esc(p.preview || "No additional text")}</span>` +
      (all && p.folder ? `<span class="where">${own.folderSmall}${esc(p.folder)}</span>` : "") +
      `</span></span></a>`;

  const show = (listing, items, subs, { searching = false } = {}) => {
    if (!items.length && !subs.length) {
      listing.innerHTML = searching
        ? `<p class="empty">Nothing matches.</p>`
        : `<p class="empty mascot"><b>Nothing here yet</b>Write your first ${esc(b.noun)} with the pen, and it will show up here.</p>`;
      return;
    }
    const folderRows = subs.map((f) => `<a class="row has-icon" href="${listHash(b, f.path)}">
        <span class="icon">${own.folder}</span>
        <span class="main"><span class="title">${esc(f.name)}</span></span>
        <span class="count">${f.count}</span><span class="chevron">${icons.chevronRight}</span></a>`).join("");
    let groups;
    if (all && !searching) {
      // Newest first already, so the sections fall out in order: Today,
      // Yesterday, Last 7 Days, Last 30 Days, each month, each year.
      const sections = new Map();
      for (const p of items) {
        const label = sectionOf(p.modified);
        if (!sections.has(label)) sections.set(label, []);
        sections.get(label).push(p);
      }
      groups = [...sections].map(([label, rows]) =>
        `<p class="group-label">${esc(label)}</p><div class="group">${rows.map(row).join("")}</div>`).join("");
    } else {
      groups = items.length ? `<div class="group">${items.map(row).join("")}</div>` : "";
    }
    listing.innerHTML = (folderRows ? `<div class="group">${folderRows}</div>` : "") + groups;
  };

  return {
    title,
    backTo: hasFolders ? listHash(b, FOLDERS) : undefined,
    backLabel: "Folders",
    html: `${heading(title, compose)}
      <div class="search">${icons.search}<input type="search" placeholder="Search" autocapitalize="none" autocorrect="off"></div>
      <div class="install-slot">${installCard()}</div>
      <div class="listing"></div>`,
    wire(root) {
      const listing = root.querySelector(".listing");
      const search = root.querySelector("input[type=search]");
      show(listing, scope, subfolders);
      let timer = null;
      let latest = 0;
      search.addEventListener("input", () => {
        const query = search.value.trim();
        clearTimeout(timer);
        if (!query) { show(listing, scope, subfolders); return; }
        const needle = query.toLowerCase();
        const local = scope.filter((p) => p.title.toLowerCase().includes(needle));
        show(listing, local, [], { searching: true });
        if (!b.search) return;
        const request = ++latest;
        timer = setTimeout(async () => {
          let found;
          try { found = await api("GET", recordsUrl(b.model.id, "?q=" + encodeURIComponent(query))); }
          catch (err) { toast(err.message); return; }
          if (request !== latest) return;
          const hits = new Map(local.map((p) => [p.id, p]));
          for (const hit of found) {
            const page = scope.find((p) => p.id === hit.id);
            if (!page || hits.has(page.id)) continue;
            hits.set(page.id, hit.preview ? { ...page, preview: hit.preview.replace(/^#+\s*/, "") } : page);
          }
          show(listing, [...hits.values()].sort(byNewest), [], { searching: true });
        }, SEARCH_DELAY);
      });
    },
  };
}

async function newFolder(b, parent) {
  const name = fileStem(prompt("Folder name") || "");
  if (!name) return;
  try {
    await api("POST", recordsUrl(b.model.id, "/_folders"), { path: join(parent, name) });
    renderRoute();
  } catch (err) {
    toast(err.message);
  }
}

// Which list a computer shows beside a page: the last one looked at.
const lastList = new Map();

/** The editor's list screens, and a page not written yet. */
export async function renderEditor(at, arg) {
  const b = bind(at);
  if (arg === NEW || arg.startsWith(NEW + "/")) {
    return renderPage(b, { isNew: true, folder: arg.slice(NEW.length + 1), arg: `${at.quill.id}/${at.screen.id}/${arg}` });
  }
  const key = b.path ? arg : "";
  lastList.set(at.tab, key);
  const data = await load(b);
  const view = listView(b, data, key);
  if (wide()) {
    app.innerHTML = nav({ title: view.title }) + `
      <main class="split">
        <section class="side">${sideBack(view)}${view.html}</section>
        <section class="page"><p class="empty mascot"><b>Nothing open</b>Choose ${esc(aOr(b.noun))} on the left, or start one with the pen.</p></section>
      </main>` + tabs(at.tab);
  } else {
    app.innerHTML = nav({ back: view.backTo, backLabel: view.backLabel, title: view.title }) +
      `<main>${view.html}</main>` + tabs(at.tab);
  }
  wireShell();
  view.wire(app.querySelector("main"));
}

// On a computer the bar has no back button — the list is right there —
// so the way up to the folders is over the list instead.
const sideBack = (view) => (view.backTo
  ? `<a class="side-back" href="${view.backTo}">${icons.chevronLeft}${esc(view.backLabel)}</a>` : "");

const aOr = (label) => (/^[aeiou]/i.test(label) ? "an " : "a ") + label;

/** One page: the editor's own, in place of the record sheet. */
export async function renderEditorPage(at, id, arg) {
  const b = bind(at);
  let record;
  try { record = await api("GET", recordsUrl(b.model.id, "/" + encodeURIComponent(id))); }
  catch (err) {
    if (err.status === 404) { toast(`That ${b.noun} is gone`); replace(at.base); return renderRoute(); }
    throw err;
  }
  return renderPage(b, { record, arg });
}

// -- a page ---------------------------------------------------------------------------
let editor = null;

// A page that starts with a heading repeating its title — the terminal
// starts every new one so — shows that heading as the title, so the body
// is only the body. It is put back on the way out.
function splitHeading(content, stem) {
  const lines = content.split("\n");
  const match = /^#\s+(.*?)\s*$/.exec(lines[0] || "");
  if (!match || match[1] !== stem) return { body: content, hadHeading: false };
  let start = 1;
  while (start < lines.length && lines[start].trim() === "") start += 1;
  return { body: lines.slice(start).join("\n"), hadHeading: true };
}
const compose = (stem, body, withHeading) => (withHeading ? `# ${stem}\n\n${body}` : body);

function pageState(b, record) {
  const stem = String(record.fields[b.title] || "").trim() || baseName(String(record.fields[b.path] || ""));
  const path = b.path ? String(record.fields[b.path] || "") : stem;
  const { body, hadHeading } = splitHeading(String(record.fields[b.body] || ""), stem);
  return { id: record.id, stem, folder: b.path ? folderOf(path) : "", rev: record.rev, hadHeading, body,
           modified: seconds(record.updated_at) || Date.now() / 1000 };
}

async function renderPage(b, { record = null, isNew = false, folder = "", arg }) {
  const ed = isNew
    ? { isNew: true, created: false, id: "", stem: "", folder, rev: null, hadHeading: true, body: "",
        modified: Date.now() / 1000 }
    : { isNew: false, created: false, ...pageState(b, record) };
  Object.assign(ed, { b, arg, dirty: false, saving: false, pending: false, timer: null,
                      attachments: b.attachments });
  editor = ed;
  // The screen is this page's until it is left: a new one while the hash
  // says new, a saved one while the hash is its own.
  const hold = {
    stays: (name, a) => a === ed.arg && (name === "r" || (name === "q" && ed.isNew)),
    leave: () => leaveEditor(ed),
    flush: () => { if (ed.dirty) { clearTimeout(ed.timer); saveEditor(ed, { keepalive: true }); } },
  };
  occupy(hold);

  const listKey = lastList.has(b.at.tab) ? lastList.get(b.at.tab) : "";
  const parent = b.path
    ? listHash(b, ed.folder || (previousHash() === listHash(b, TOP) ? TOP : listKey))
    : listHash(b, "");
  const parentLabel = ed.folder ? baseName(ed.folder) : b.label;
  const actions = `<button class="done strong" hidden>Done</button>` +
    (ed.attachments ? photoButton : "") +
    `<button class="delete" aria-label="Delete ${esc(b.noun)}">${icons.trash}</button>`;
  const page = `
      <div class="editor">
        <input class="title" placeholder="Title" value="${esc(ed.isNew ? "" : ed.stem)}" autocapitalize="sentences" enterkeyhint="next">
        <p class="stamp"><span class="when">${esc(formatDate(ed.modified, { long: true }))}</span><span class="status"></span></p>
        ${bodyMarkup}
      </div>`;
  let view = null;
  if (wide()) {
    view = listView(b, await load(b), listKey, ed.id);
    app.innerHTML = nav({ title: ed.stem || "New", right: actions }) + `
      <main class="split">
        <section class="side">${sideBack(view)}${view.html}</section>
        <section class="page">${page}</section>
      </main>` + tabs(b.at.tab);
  } else {
    app.innerHTML = nav({ back: parent, backLabel: parentLabel, title: ed.stem, right: actions }) +
      `<main>${page}</main>`;
  }
  wireShell();
  if (view) view.wire(app.querySelector(".side"));
  app.querySelector(".nav").classList.add("lined");

  const box = app.querySelector(".editor");
  const titleEl = ed.titleEl = box.querySelector(".title");
  ed.statusEl = box.querySelector(".stamp .status");
  const done = app.querySelector(".nav .done");
  const del = app.querySelector(".nav .delete");

  ed.changed = () => {
    ed.dirty = true;
    setStatus(ed, "");
    clearTimeout(ed.timer);
    ed.timer = setTimeout(() => saveEditor(ed), SAVE_DELAY);
  };
  // The body: text, with the pictures shown where they are.
  mountBody(ed, box, ed.body);
  addEventListener("resize", ed.grow);
  titleEl.addEventListener("input", ed.changed);
  titleEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); focusBody(ed); }
  });
  // Tapping the empty space under the text starts writing there.
  box.parentElement.addEventListener("click", (event) => {
    if (event.target === box || event.target === box.parentElement) focusBody(ed, { end: true });
  });
  box.addEventListener("focusin", () => { done.hidden = false; del.hidden = true; });
  box.addEventListener("focusout", () => {
    setTimeout(() => {
      if (!box.contains(document.activeElement)) { done.hidden = true; del.hidden = false; }
    }, 0);
    if (ed.dirty) { clearTimeout(ed.timer); saveEditor(ed); }
  });
  done.addEventListener("click", () => document.activeElement && document.activeElement.blur());
  del.addEventListener("click", async () => {
    if (ed.isNew) { back(parent); return; }
    if (!confirm(`Delete “${ed.stem}”?`)) return;
    try {
      clearTimeout(ed.timer);
      ed.dirty = false;
      await api("DELETE", recordsUrl(b.model.id, "/" + encodeURIComponent(ed.id)));
      vacate(hold);
      editor = null;
      back(parent);
    } catch (err) { toast(err.message); }
  });

  if (ed.isNew) titleEl.focus();
}

// The page's address has moved — made, or renamed, which for a record kept
// by its path is a new id. The screen stays the page's.
function moved(ed, record) {
  ed.id = record.id;
  ed.arg = pageArg(ed.b, record.id);
  replace(pageHash(ed.b, record.id));
}

async function saveEditor(ed, { keepalive = false } = {}) {
  if (!ed.dirty) return;
  if (ed.saving) { ed.pending = true; return; }
  const { b } = ed;
  ed.dirty = false;
  ed.saving = true;
  setStatus(ed, "Saving…");
  try {
    const title = fileStem(ed.titleEl.value);
    const body = bodyText(ed);
    if (ed.isNew) {
      if (!title && !body.trim()) { setStatus(ed, ""); return; }
      const made = await createUnique(ed, title || `New ${b.noun}`, body);
      ed.isNew = false;
      ed.created = true;
      ed.rev = made.rev;
      ed.stem = pageState(b, made).stem;
      ed.hadHeading = true;
      moved(ed, made);
    } else {
      if (title && title !== ed.stem) await renameTo(ed, title);
      let saved;
      try {
        saved = await api("PATCH", recordsUrl(b.model.id, "/" + encodeURIComponent(ed.id)),
          { fields: { [b.body]: compose(ed.stem, body, ed.hadHeading) }, rev: ed.rev }, { keepalive });
      } catch (err) {
        const current = err.status === 409 && err.detail && err.detail.current;
        if (!current) throw err;
        // Somebody else wrote it meanwhile. Theirs is what is kept; show that.
        const fresh = pageState(b, current);
        ed.rev = fresh.rev;
        ed.hadHeading = fresh.hadHeading;
        setBody(ed, fresh.body);
        toast(`This ${b.noun} changed elsewhere — showing that copy`);
        setStatus(ed, "Reloaded");
        return;
      }
      ed.rev = saved.rev;
      ed.modified = seconds(saved.updated_at) || ed.modified;
    }
    const center = app.querySelector(".nav .center .text");
    if (center && editor === ed) center.textContent = ed.stem;
    setStatus(ed, "Saved");
  } catch (err) {
    ed.dirty = true;
    setStatus(ed, "Not saved", true);
    if (err.status !== 401) toast(err.message);
  } finally {
    ed.saving = false;
    if (ed.pending) { ed.pending = false; ed.dirty = true; saveEditor(ed); }
  }
}

// A new page gets a name nobody else in its folder has: "New note", then
// "New note 2" — the server says no to a second of the same.
async function createUnique(ed, stem, body) {
  const { b } = ed;
  let taken = new Set();
  try { taken = new Set((await load(b)).pages.filter((p) => p.folder === ed.folder).map((p) => p.title)); }
  catch { /* the server will say if it is taken */ }
  for (let n = 1; n < 100; n += 1) {
    const name = n === 1 ? stem : `${stem} ${n}`;
    if (taken.has(name)) continue;
    const fields = { [b.body]: compose(name, body, true) };
    if (b.path) fields[b.path] = join(ed.folder, name);
    else fields[b.title] = name;
    return api("POST", recordsUrl(b.model.id), { fields });
  }
  throw new Error(`Too many called ${stem}`);
}

async function renameTo(ed, stem) {
  const { b } = ed;
  try {
    const renamed = await api("PATCH", recordsUrl(b.model.id, "/" + encodeURIComponent(ed.id)),
      { fields: { [b.title]: stem } });
    ed.stem = pageState(b, renamed).stem;
    ed.rev = renamed.rev;
    moved(ed, renamed);
  } catch (err) {
    if (err.status === 400) {
      toast(err.message);
      ed.titleEl.value = ed.stem;
      return;
    }
    throw err;
  }
}

// Leaving a page saves what is there, and throws away one that never got
// any words — the way a phone does when you back out of an empty note.
async function leaveEditor(ed) {
  if (editor === ed) editor = null;
  clearTimeout(ed.timer);
  removeEventListener("resize", ed.grow);
  if (ed.dirty) await saveEditor(ed);
  while (ed.saving) await new Promise((r) => setTimeout(r, 50));
  if (ed.created && !fileStem(ed.titleEl.value) && !bodyText(ed).trim()) {
    try { await api("DELETE", recordsUrl(ed.b.model.id, "/" + encodeURIComponent(ed.id))); }
    catch { /* it will show up; fine */ }
  }
}
