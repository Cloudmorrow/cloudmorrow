/* Notes: the screens a phone's notes app has. Folders, the notes in one,
   and a note — the same files the TUI edits. */

import {
  ApiError, SAVE_DELAY, SEARCH_DELAY, api, app, back, encodePath, esc, fileStem, formatDate,
  heading, icons, nav, occupy, pixelIcon, previousHash, registerScreen, registerTab,
  renderRoute, replace,
  sectionOf, setStatus, tabs, toast, vacate, wireShell,
} from "./core.js";
import { installCard } from "./install.js";
import { bodyMarkup, bodyText, focusBody, mountBody, photoButton, setBody } from "./pictures.js";

const NEW_NOTE = "New Note";

const own = {
  folder: '<svg width="22" height="18" viewBox="0 0 22 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M1.5 3.5A1.5 1.5 0 0 1 3 2h5l2 2.5h9a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5H3a1.5 1.5 0 0 1-1.5-1.5z"/></svg>',
  notes: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="2" width="14" height="16" rx="2"/><path d="M6.5 7h7M6.5 10.5h7M6.5 14h4"/></svg>',
  folderSmall: '<svg width="14" height="12" viewBox="0 0 22 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round"><path d="M1.5 3.5A1.5 1.5 0 0 1 3 2h5l2 2.5h9a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5H3a1.5 1.5 0 0 1-1.5-1.5z"/></svg>',
  newFolder: '<svg width="22" height="18" viewBox="0 0 22 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M1.5 3.5A1.5 1.5 0 0 1 3 2h5l2 2.5h9a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5H3a1.5 1.5 0 0 1-1.5-1.5z"/><path d="M11 7.5v6M8 10.5h6"/></svg>',
};

const stemOf = (path) => {
  const name = path.slice(path.lastIndexOf("/") + 1);
  return name.endsWith(".md") ? name.slice(0, -3) : name;
};
const folderOf = (path) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");
const baseName = (path) => path.slice(path.lastIndexOf("/") + 1);
const join = (folder, name) => (folder ? folder + "/" + name : name);

// -- the tree, flattened ---------------------------------------------------
let notes = [];    // [{path, title, folder, modified, preview}]
let folders = [];  // [{path, name, depth, count}] in tree order, root first

async function loadTree() {
  const tree = await api("GET", "/api/notes/tree?previews=true");
  notes = [];
  folders = [];
  walk(tree, 0);
}

function walk(node, depth) {
  const files = node.children.filter((c) => !c.is_dir);
  const dirs = node.children.filter((c) => c.is_dir);
  folders.push({ path: node.path, name: node.path ? node.name : "Notes", depth, count: files.length });
  for (const file of files) {
    notes.push({
      path: file.path,
      title: stemOf(file.path),
      folder: node.path,
      modified: file.modified,
      preview: file.preview || "",
    });
  }
  for (const dir of dirs) walk(dir, depth + 1);
}

const byNewest = (a, b) => b.modified - a.modified;
const notesIn = (folder) => notes.filter((n) => n.folder === folder).sort(byNewest);
const subfoldersOf = (folder) => folders.filter((f) => f.path && folderOf(f.path) === folder);

// -- folders ------------------------------------------------------------------
function renderFolders() {
  const total = notes.length;
  const rows = folders.map((f) => {
    const href = f.path ? "#/list/" + encodePath(f.path) : "#/list";
    return `<a class="row has-icon indent-${Math.min(f.depth, 3)}" href="${href}">
      <span class="icon">${own.folder}</span>
      <span class="main"><span class="title">${esc(f.name)}</span></span>
      <span class="count">${f.count}</span><span class="chevron">${icons.chevronRight}</span></a>`;
  }).join("");
  app.innerHTML = nav({ title: "Folders" }) + `
    <main>
      ${heading("Folders", `<button class="new-folder" aria-label="New folder">${own.newFolder}</button>`)}
      <div class="install-slot">${installCard()}</div>
      <div class="group">
        <a class="row has-icon" href="#/all">
          <span class="icon">${own.notes}</span>
          <span class="main"><span class="title">All Notes</span></span>
          <span class="count">${total}</span><span class="chevron">${icons.chevronRight}</span></a>
        ${rows}
      </div>
    </main>` + tabs("notes");
  wireShell();
  app.querySelector(".new-folder").addEventListener("click", async () => {
    const name = fileStem(prompt("Folder name") || "");
    if (!name) return;
    try {
      await api("POST", "/api/notes/dir", { path: name });
      await loadTree();
      renderFolders();
    } catch (err) {
      toast(err.status === 409 ? "That folder already exists" : err.message);
    }
  });
}

// -- the notes in a folder ---------------------------------------------------
function renderList(folder, all) {
  const title = all ? "All Notes" : (folder ? baseName(folder) : "Notes");
  const composeTarget = "#/new" + (folder ? "/" + encodePath(folder) : "");
  app.innerHTML = nav({ back: "#/folders", backLabel: "Folders", title }) + `
    <main>
      ${heading(title, `<a class="button compose" href="${composeTarget}" aria-label="New note">${icons.compose}</a>`)}
      <div class="search">${icons.search}<input type="search" placeholder="Search" autocapitalize="none" autocorrect="off"></div>
      <div class="install-slot">${installCard()}</div>
      <div class="listing"></div>
    </main>` + tabs("notes");
  wireShell();
  const listing = app.querySelector(".listing");
  const search = app.querySelector("input[type=search]");
  const scope = all ? notes.slice().sort(byNewest) : notesIn(folder);
  const subfolders = all ? [] : subfoldersOf(folder);

  const show = (items, subs, { searching = false } = {}) => {
    if (!items.length && !subs.length) {
      listing.innerHTML = searching
        ? `<p class="empty">No notes match.</p>`
        : `<p class="empty mascot"><b>Nothing here yet</b>Write your first note with the pen, and it will show up here.</p>`;
      return;
    }
    const folderRows = subs.map((f) => `<a class="row has-icon" href="#/list/${encodePath(f.path)}">
        <span class="icon">${own.folder}</span>
        <span class="main"><span class="title">${esc(f.name)}</span></span>
        <span class="count">${f.count}</span><span class="chevron">${icons.chevronRight}</span></a>`).join("");
    const noteRow = (n) => `<a class="row" href="#/note/${encodePath(n.path)}">
        <span class="main"><span class="title">${esc(n.title)}</span>
        <span class="meta"><span class="date">${esc(formatDate(n.modified))}</span>` +
        `<span class="preview">${esc(n.preview || "No additional text")}</span>` +
        (all && n.folder ? `<span class="where">${own.folderSmall}${esc(n.folder)}</span>` : "") +
        `</span></span></a>`;
    let noteGroups;
    if (all && !searching) {
      // Newest first already, so the sections fall out in order: Today,
      // Yesterday, Last 7 Days, Last 30 Days, each month, each year.
      const sections = new Map();
      for (const n of items) {
        const label = sectionOf(n.modified);
        if (!sections.has(label)) sections.set(label, []);
        sections.get(label).push(n);
      }
      noteGroups = [...sections].map(([label, rows]) =>
        `<p class="group-label">${esc(label)}</p><div class="group">${rows.map(noteRow).join("")}</div>`).join("");
    } else {
      noteGroups = items.length ? `<div class="group">${items.map(noteRow).join("")}</div>` : "";
    }
    listing.innerHTML = (folderRows ? `<div class="group">${folderRows}</div>` : "") + noteGroups;
  };
  show(scope, subfolders);

  let searchTimer = null;
  let latest = 0;
  search.addEventListener("input", () => {
    const query = search.value.trim();
    clearTimeout(searchTimer);
    if (!query) { show(scope, subfolders); return; }
    const needle = query.toLowerCase();
    const local = scope.filter((n) => n.title.toLowerCase().includes(needle));
    show(local, [], { searching: true });
    const request = ++latest;
    searchTimer = setTimeout(async () => {
      let results;
      try { results = (await api("GET", "/api/notes/search?q=" + encodeURIComponent(query))).results; }
      catch (err) { toast(err.message); return; }
      if (request !== latest) return;
      const found = new Map(local.map((n) => [n.path, n]));
      for (const hit of results) {
        const note = scope.find((n) => n.path === hit.path);
        if (!note || found.has(note.path)) continue;
        const line = hit.matches.find((m) => m.line > 0);
        found.set(note.path, line ? { ...note, preview: line.text.replace(/^#+\s*/, "") } : note);
      }
      show([...found.values()].sort(byNewest), [], { searching: true });
    }, SEARCH_DELAY);
  });
}

// -- a note ---------------------------------------------------------------------
let editor = null;

// The TUI starts every note with a heading that repeats its file name. The
// editor shows that heading as the title, so the body is only the body.
function splitHeading(content, stem) {
  const lines = content.split("\n");
  const match = /^#\s+(.*?)\s*$/.exec(lines[0] || "");
  if (!match || match[1] !== stem) return { body: content, hadHeading: false };
  let start = 1;
  while (start < lines.length && lines[start].trim() === "") start += 1;
  return { body: lines.slice(start).join("\n"), hadHeading: true };
}
const compose = (stem, body, withHeading) => (withHeading ? `# ${stem}\n\n${body}` : body);

async function renderNote(arg, isNew = false) {
  let ed;
  if (isNew) {
    ed = { isNew: true, created: false, folder: arg, path: "", stem: "", rev: null,
           hadHeading: true, body: "", modified: Date.now() / 1000 };
  } else {
    let note;
    try { note = await api("GET", "/api/notes/file/" + encodePath(arg)); }
    catch (err) {
      if (err.status === 404) { toast("That note is gone"); replace("#/all"); return renderRoute(); }
      throw err;
    }
    const stem = stemOf(note.path);
    const { body, hadHeading } = splitHeading(note.content, stem);
    ed = { isNew: false, created: false, folder: folderOf(note.path), path: note.path, stem,
           rev: note.rev, hadHeading, body, modified: note.modified };
  }
  ed.dirty = false; ed.saving = false; ed.pending = false; ed.timer = null;
  editor = ed;
  // The screen is this note's until it is left: a new note stays while the
  // hash says new, and a saved one while the hash says its path.
  const hold = {
    stays: (name, a) => (name === "note" && a === ed.path) || (name === "new" && ed.isNew),
    leave: () => leaveEditor(ed),
    flush: () => { if (ed.dirty) { clearTimeout(ed.timer); saveEditor(ed, { keepalive: true }); } },
  };
  occupy(hold);

  const parent = ed.folder ? "#/list/" + encodePath(ed.folder) : (previousHash() === "#/list" ? "#/list" : "#/all");
  const parentLabel = ed.folder ? baseName(ed.folder) : "Notes";
  app.innerHTML = nav({
    back: parent, backLabel: parentLabel, title: ed.stem,
    right: `<button class="done strong" hidden>Done</button>` + photoButton +
      `<button class="delete" aria-label="Delete note">${icons.trash}</button>`,
  }) + `
    <main>
      <div class="editor">
        <input class="title" placeholder="Title" value="${esc(ed.isNew ? "" : ed.stem)}" autocapitalize="sentences" enterkeyhint="next">
        <p class="stamp"><span class="when">${esc(formatDate(ed.modified, { long: true }))}</span><span class="status"></span></p>
        ${bodyMarkup}
      </div>
    </main>`;
  wireShell();
  app.querySelector(".nav").classList.add("lined");

  const titleEl = ed.titleEl = app.querySelector(".title");
  ed.statusEl = app.querySelector(".stamp .status");
  const done = app.querySelector(".done");
  const del = app.querySelector(".delete");
  const box = app.querySelector(".editor");

  const changed = ed.changed = () => {
    ed.dirty = true;
    setStatus(ed, "");
    clearTimeout(ed.timer);
    ed.timer = setTimeout(() => saveEditor(ed), SAVE_DELAY);
  };
  // The body: text, with the pictures shown where they are.
  mountBody(ed, box, ed.body);
  addEventListener("resize", ed.grow);
  titleEl.addEventListener("input", changed);
  titleEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); focusBody(ed); }
  });
  // Tapping the empty space under the text starts writing there — on the
  // editor's own space, or on the page under a short note.
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
      await api("DELETE", "/api/notes/" + encodePath(ed.path));
      vacate(hold);
      editor = null;
      back(parent);
    } catch (err) { toast(err.message); }
  });

  if (ed.isNew) titleEl.focus();
}

async function saveEditor(ed, { keepalive = false } = {}) {
  if (!ed.dirty) return;
  if (ed.saving) { ed.pending = true; return; }
  ed.dirty = false;
  ed.saving = true;
  setStatus(ed, "Saving…");
  try {
    const title = fileStem(ed.titleEl.value);
    const body = bodyText(ed);
    if (ed.isNew) {
      if (!title && !body.trim()) { setStatus(ed, ""); return; }
      const created = await createUnique(ed.folder, title || NEW_NOTE, body);
      ed.isNew = false;
      ed.created = true;
      ed.path = created.path;
      ed.stem = stemOf(created.path);
      ed.rev = created.rev;
      ed.hadHeading = true;
      replace("#/note/" + encodePath(ed.path));
    } else {
      if (title && title !== ed.stem) await renameTo(ed, title);
      let saved;
      try {
        saved = await api("PUT", "/api/notes/file/" + encodePath(ed.path),
          { content: compose(ed.stem, body, ed.hadHeading), rev: ed.rev }, { keepalive });
      } catch (err) {
        if (err.status !== 409 || !err.detail || err.detail.rev === undefined) throw err;
        // Someone else wrote it meanwhile. Theirs is on disk; show that.
        ed.rev = err.detail.rev;
        const split = splitHeading(err.detail.content, ed.stem);
        ed.hadHeading = split.hadHeading;
        setBody(ed, split.body);
        toast("This note changed elsewhere — showing that copy");
        setStatus(ed, "Reloaded");
        return;
      }
      ed.rev = saved.rev;
      ed.modified = saved.modified;
    }
    const title2 = app.querySelector(".nav .center .text");
    if (title2 && editor === ed) title2.textContent = ed.stem;
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

async function createUnique(folder, stem, body) {
  for (let n = 1; n < 100; n += 1) {
    const name = n === 1 ? stem : `${stem} ${n}`;
    try {
      return await api("POST", "/api/notes/file", { path: join(folder, name + ".md"), content: compose(name, body, true) });
    } catch (err) {
      if (err.status !== 409) throw err;
    }
  }
  throw new ApiError(409, "Too many notes called " + stem);
}

async function renameTo(ed, stem) {
  const dest = join(ed.folder, stem + ".md");
  try {
    const moved = await api("POST", "/api/notes/move", { src: ed.path, dest });
    ed.path = moved.path;
    ed.stem = stemOf(moved.path);
    const fresh = await api("GET", "/api/notes/file/" + encodePath(ed.path));
    ed.rev = fresh.rev;
    replace("#/note/" + encodePath(ed.path));
  } catch (err) {
    if (err.status === 409) {
      toast(`There is already a note called “${stem}”`);
      ed.titleEl.value = ed.stem;
      return;
    }
    throw err;
  }
}

// Leaving a note saves what is there, and throws away a note that never got
// any words — the way a phone does when you back out of an empty one.
async function leaveEditor(ed) {
  if (editor === ed) editor = null;
  clearTimeout(ed.timer);
  removeEventListener("resize", ed.grow);
  if (ed.dirty) await saveEditor(ed);
  while (ed.saving) await new Promise((r) => setTimeout(r, 50));
  if (ed.created && !fileStem(ed.titleEl.value) && !bodyText(ed).trim()) {
    try { await api("DELETE", "/api/notes/" + encodePath(ed.path)); } catch { /* it will show up; fine */ }
  }
}

// -- what this feature adds to the app ---------------------------------------------
registerScreen("folders", async () => { await loadTree(); renderFolders(); });
registerScreen("list", async (folder) => { await loadTree(); renderList(folder, false); });
registerScreen("all", async () => { await loadTree(); renderList("", true); });
registerScreen("note", (path) => renderNote(path));
registerScreen("new", (folder) => renderNote(folder, true));
registerTab({
  name: "notes",
  label: "Notes",
  icon: pixelIcon("notes"),
  feature: "notes",
  href: (active) => (active ? "#/folders" : "#/all"),
});
