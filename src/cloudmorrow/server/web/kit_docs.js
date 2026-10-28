/* The kit's `document`: a page of blocks, one `.docs` file a document (docs/DOCS.md).

   A screen binds the file `model`, its `title`, and `body`: the text field
   the file's text is in — one JSON object, {"blocks": [...]} — and says,
   as an editor's does, `where` the files are (a share, and the folder
   under it) and their `suffix`: `.docs`, and Word's `.docx`, which the
   server reads and writes as the same text. The list is the editor's,
   folders and search and all (kit_editor.js); a document opens as a page
   of its own: the title, a bar of styles, and the words, edited in place.
   What is typed is kept as blocks and runs by kit_docs_rules.js, the same
   rules quill/docs.py keeps for the terminal and the command line; nothing
   of the browser's own markup is saved.

   The page saves as you type; changing the title renames the file; one
   changed elsewhere since it was opened is not written over. Open picks a
   document from anywhere on the cloud — another folder, a fileshare —
   through filepick.js, and it opens here by its record, wherever it is.
   Export hands the document over to save as Word, PDF or Markdown, made
   by the server from the same blocks (the record API's /export).

   The addresses, under the screen's own (quills.js):
     #/q/<quill>/<screen>                the folders, every document, or one folder's
     #/q/<quill>/<screen>/~new[/folder]  a document not written yet
     #/r/<quill>/<screen>/<model>/<id>   a document */

import {
  SAVE_DELAY, api, app, back, baseName, esc, fileStem, folderOf, formatDate, go, icons, joinPath, mount,
  nav, occupy, previousHash, recordsUrl, renderRoute, replace, seconds, setStatus, tabs, toast, vacate, wireShell,
} from "./core.js";
import { mayWrite } from "./kit.js";
import {
  NEW, TOP, aOr, download, fixedFields, folded, lastList, listHash, listView, load, openButton,
  ownIcons, placeOf, shareLabels, showWhereabouts, sideHead, suffixesOf, trimSlashes, underRoot, whereIs, whereNew,
  whereabouts, wholePath, wide, wireFold, withSuffix, withoutSuffix,
} from "./kit_editor.js";
import { Doc, block, run } from "./kit_docs_rules.js";
import { ask, askText } from "./dialog.js";
import { choose } from "./actions.js";
import { pickFile } from "./filepick.js";

const WORD = ".docx";
// What a document goes out as, by suffix: what the server's /export makes.
const EXPORTS = [[".docx", "Word"], [".pdf", "PDF"], [".md", "Markdown"]];

// -- the screen's bindings ---------------------------------------------------------
function bind(at) {
  const { quill, screen } = at;
  const model = quill.models[screen.model];
  const can = new Set(model.can || []);
  const where = Object.fromEntries(Object.entries(screen.where || {}).map(([k, v]) => [k, String(v)]));
  const suffixes = suffixesOf(screen);
  const filters = suffixes.length ? { ...where, suffix: suffixes.join(",") } : where;
  return {
    at,
    model,
    title: screen.title || model.title || "name",
    body: screen.body || "text",
    path: screen.path || "",
    where,
    suffix: suffixes[0] || "",
    suffixes,
    root: trimSlashes(where.within || ""),
    query: new URLSearchParams(filters).toString(),
    keepsFolders: !!screen.path && can.has("folders"),
    search: can.has("search"),
    label: screen.label || quill.name,
    // A document, whatever the file datamodel calls itself.
    noun: "document",
    writes: mayWrite(model),
  };
}

const pageArg = (b, id) => `${b.at.quill.id}/${b.at.screen.id}/${b.model.id}/${id}`;
const pageHash = (b, id) =>
  `#/r/${encodeURIComponent(b.at.quill.id)}/${encodeURIComponent(b.at.screen.id)}/${encodeURIComponent(b.model.id)}/${encodeURIComponent(id)}`;
const isWord = (name) => String(name || "").toLowerCase().endsWith(WORD);

// -- the list: the editor's, over these files ------------------------------------------
export async function renderDocs(at, arg) {
  const b = bind(at);
  if ((arg === NEW || arg.startsWith(NEW + "/")) && !b.writes) {
    toast(`You can read ${b.noun}s here, not write them`);
    replace(at.base);
    return renderRoute();
  }
  if (arg === NEW || arg.startsWith(NEW + "/")) {
    return renderPage(b, { isNew: true, folder: arg.slice(NEW.length + 1), arg: `${at.quill.id}/${at.screen.id}/${arg}` });
  }
  const key = b.path ? arg : "";
  lastList.set(at.tab, key);
  const view = listView(b, await load(b), key);
  const right = openButton(b);
  if (wide()) {
    mount(nav({ title: view.title, right }) + `
      <main class="split">
        <section class="side">${sideHead(view, { fold: false })}${view.html}</section>
        <section class="page"><p class="empty mascot"><b>Nothing open</b>Choose ${esc(aOr(b.noun))} on the left${
          b.writes ? ", or start one with the pen" : ""}, or open one from anywhere with the folder.</p></section>
      </main>` + tabs(at.tab));
  } else {
    mount(nav({ back: view.backTo, backLabel: view.backLabel, title: view.title, right }) +
      `<main>${view.html}</main>` + tabs(at.tab));
  }
  wireShell();
  view.wire(app.querySelector("main"));
  app.querySelector(".nav .open").addEventListener("click", () => openOther(b));
}

// -- opening from anywhere ------------------------------------------------------------
// A document picked from any share and folder opens by its record: the
// page is the same, and the file stays where it is.
async function openOther(b) {
  const picked = await pickFile({ suffixes: b.suffixes, title: `Open ${aOr(b.noun)}`, model: b.model.id });
  if (picked) go(pageHash(b, picked.id));
}

/** One document: the kit's own page, in place of the record sheet. */
export async function renderDocsPage(at, id, arg) {
  const b = bind(at);
  let record;
  try { record = await api("GET", recordsUrl(b.model.id, id)); }
  catch (err) {
    if (err.status === 404) { toast(`That ${b.noun} is gone`); replace(at.base); return renderRoute(); }
    throw err;
  }
  return renderPage(b, { record, arg });
}

// -- blocks as markup, and back --------------------------------------------------------
// What contenteditable shows: h1–h3, p, ul/ol with li (nested for a level),
// blockquote, table. Runs wrap their text in b, i, u, s and a. Reading it
// back takes the browser's own spellings too (strong, em, a styled span).
function runsHtml(runs) {
  return runs.map((r) => {
    let html = esc(r.text).replace(/\n/g, "<br>");
    if (r.bold) html = `<b>${html}</b>`;
    if (r.italic) html = `<i>${html}</i>`;
    if (r.underline) html = `<u>${html}</u>`;
    if (r.strike) html = `<s>${html}</s>`;
    if (r.link) html = `<a href="${esc(r.link)}">${html}</a>`;
    return html;
  }).join("") || "<br>";
}

const alignAttr = (b) => (b.align ? ` style="text-align:${b.align}"` : "");

export function blocksHtml(blocks) {
  const out = [];
  // Open lists, one per level: [{tag, level}]; a change of kind or a step
  // down closes them.
  const lists = [];
  const closeLists = (toLevel = -1) => {
    while (lists.length && lists[lists.length - 1].level > toLevel) out.push(`</li></${lists.pop().tag}>`);
  };
  for (const b of blocks) {
    if (b.kind === "bullet" || b.kind === "numbered") {
      const tag = b.kind === "bullet" ? "ul" : "ol";
      const level = b.level || 0;
      closeLists(level);
      const top = lists[lists.length - 1];
      if (top && top.level === level && top.tag !== tag) closeLists(level - 1);
      if (!lists.length || lists[lists.length - 1].level < level) {
        out.push(`<${tag}><li${alignAttr(b)}>${runsHtml(b.runs)}`);
        lists.push({ tag, level });
      } else {
        out.push(`</li><li${alignAttr(b)}>${runsHtml(b.runs)}`);
      }
      continue;
    }
    closeLists();
    if (b.kind === "heading") out.push(`<h${b.level}${alignAttr(b)}>${runsHtml(b.runs)}</h${b.level}>`);
    else if (b.kind === "quote") out.push(`<blockquote${alignAttr(b)}><p>${runsHtml(b.runs)}</p></blockquote>`);
    else if (b.kind === "table") {
      out.push(`<table><tbody>${b.rows.map((row) =>
        `<tr>${row.map((c) => `<td>${runsHtml(c.runs)}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
    } else out.push(`<p${alignAttr(b)}>${runsHtml(b.runs)}</p>`);
  }
  closeLists();
  return out.join("") || "<p><br></p>";
}

const BOLD = new Set(["B", "STRONG"]);
const ITALIC = new Set(["I", "EM"]);
const UNDER = new Set(["U", "INS"]);
const STRIKE = new Set(["S", "STRIKE", "DEL"]);
const BLOCK_TAGS = new Set(["P", "DIV", "H1", "H2", "H3", "H4", "H5", "H6", "UL", "OL", "LI", "BLOCKQUOTE", "TABLE", "PRE"]);

function runsOf(node, style = {}) {
  const runs = [];
  for (const child of node.childNodes) {
    if (child.nodeType === Node.TEXT_NODE) {
      runs.push(run(child.data.replace(/ /g, " "), style));
      continue;
    }
    if (child.nodeType !== Node.ELEMENT_NODE) continue;
    const tag = child.tagName;
    if (tag === "BR") { runs.push(run("\n", style)); continue; }
    if (BLOCK_TAGS.has(tag)) {
      // A block inside a line (a pasted div): its words, on a line of their own.
      if (runs.length && runs[runs.length - 1].text !== "\n") runs.push(run("\n", style));
      runs.push(...runsOf(child, style));
      continue;
    }
    const css = child.style || {};
    const next = {
      bold: style.bold || BOLD.has(tag) || /^(bold|[6-9]00)$/.test(css.fontWeight || ""),
      italic: style.italic || ITALIC.has(tag) || css.fontStyle === "italic",
      underline: style.underline || UNDER.has(tag) || /underline/.test(css.textDecoration || css.textDecorationLine || ""),
      strike: style.strike || STRIKE.has(tag) || /line-through/.test(css.textDecoration || css.textDecorationLine || ""),
      link: style.link || (tag === "A" ? child.getAttribute("href") || "" : ""),
    };
    runs.push(...runsOf(child, next));
  }
  return runs;
}

const alignOf = (el) => {
  const a = (el.style && el.style.textAlign) || el.getAttribute("align") || "";
  return ["center", "right", "justify"].includes(a) ? a : "";
};

function listBlocks(list, level, out) {
  const kind = list.tagName === "OL" ? "numbered" : "bullet";
  for (const li of list.children) {
    if (li.tagName !== "LI") continue;
    const own = li.cloneNode(true);
    const nested = [...own.children].filter((c) => c.tagName === "UL" || c.tagName === "OL");
    for (const n of nested) own.removeChild(n);
    out.push(block(kind, runsOf(own), { level, align: alignOf(li) }));
    for (const n of li.children) if (n.tagName === "UL" || n.tagName === "OL") listBlocks(n, level + 1, out);
  }
}

export function blocksOf(root) {
  const out = [];
  let loose = [];
  const flush = () => {
    if (loose.length) { out.push(block("paragraph", loose)); loose = []; }
  };
  for (const node of root.childNodes) {
    if (node.nodeType === Node.TEXT_NODE) {
      if (node.data.trim()) loose.push(run(node.data));
      continue;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) continue;
    const tag = node.tagName;
    if (!BLOCK_TAGS.has(tag) && tag !== "BR") { loose.push(...runsOf(node)); continue; }
    flush();
    if (tag === "BR") continue;
    if (/^H[1-6]$/.test(tag)) out.push(block("heading", runsOf(node), { level: Math.min(3, +tag[1]), align: alignOf(node) }));
    else if (tag === "UL" || tag === "OL") listBlocks(node, 0, out);
    else if (tag === "BLOCKQUOTE") {
      const inner = [...node.children].filter((c) => BLOCK_TAGS.has(c.tagName));
      const runs = inner.length
        ? inner.flatMap((c, i) => (i ? [run("\n"), ...runsOf(c)] : runsOf(c)))
        : runsOf(node);
      out.push(block("quote", runs, { align: alignOf(node) }));
    } else if (tag === "TABLE") {
      const rows = [...node.querySelectorAll("tr")].map((tr) => [...tr.children].map((td) => ({ runs: runsOf(td) })));
      if (rows.length) out.push(block("table", [], { rows }));
    } else if (tag === "DIV" && [...node.children].some((c) => BLOCK_TAGS.has(c.tagName))) {
      out.push(...blocksOf(node));
    } else out.push(block("paragraph", runsOf(node), { align: alignOf(node) }));
  }
  flush();
  // A trailing newline a <br> left at the end of a line is not a word.
  for (const b of out) {
    if (b.runs && b.runs.length && b.runs[b.runs.length - 1].text.endsWith("\n")) {
      const last = b.runs[b.runs.length - 1];
      last.text = last.text.replace(/\n+$/, "");
      if (!last.text) b.runs.pop();
    }
  }
  return out;
}

// -- a page -------------------------------------------------------------------------------
let open = null;

function pageState(b, record) {
  const name = String(record.fields[b.title] || "").trim();
  const stem = withoutSuffix(b, name) || baseName(withoutSuffix(b, underRoot(b, record.fields[b.path])));
  const path = b.path ? withoutSuffix(b, underRoot(b, record.fields[b.path])) : stem;
  // Where it is, when that is not the screen's own folder: opened from elsewhere.
  const where = placeOf(b, record);
  return {
    id: record.id, stem, folder: b.path && !where ? folderOf(path) : "", where, rev: record.rev, word: isWord(name),
    doc: Doc.fromText(record.fields[b.body]),
    modified: seconds(record.updated_at) || Date.now() / 1000,
  };
}

const TOOLS = [
  ["block", "p", "¶", "Paragraph"], ["block", "h1", "H1", "Heading 1"], ["block", "h2", "H2", "Heading 2"],
  ["block", "h3", "H3", "Heading 3"], ["sep"],
  ["cmd", "bold", "<b>B</b>", "Bold (Ctrl+B)"], ["cmd", "italic", "<i>I</i>", "Italic (Ctrl+I)"],
  ["cmd", "underline", "<u>U</u>", "Underline (Ctrl+U)"], ["cmd", "strikeThrough", "<s>S</s>", "Strike through"], ["sep"],
  ["cmd", "insertUnorderedList", "•", "Bullets"], ["cmd", "insertOrderedList", "1.", "Numbered"],
  ["block", "blockquote", "❝", "Quote"], ["link", "", "🔗", "Link"], ["sep"],
  ["cmd", "justifyLeft", "⇤", "Left"], ["cmd", "justifyCenter", "↔", "Centre"], ["cmd", "justifyRight", "⇥", "Right"],
];

const toolbar = () => `<div class="doc-tools" role="toolbar">${TOOLS.map(([kind, arg, label, title]) =>
  kind === "sep" ? `<span class="sep"></span>`
    : `<button type="button" data-kind="${kind}" data-arg="${esc(arg)}" title="${esc(title)}" aria-label="${esc(title)}">${label}</button>`
).join("")}</div>`;

async function renderPage(b, { record = null, isNew = false, folder = "", arg }) {
  const ed = isNew
    ? { isNew: true, created: false, id: "", stem: "", folder, where: "", rev: null, word: false, doc: new Doc(),
        modified: Date.now() / 1000 }
    : { isNew: false, created: false, ...pageState(b, record) };
  Object.assign(ed, { b, arg, dirty: false, saving: false, pending: false, timer: null });
  open = ed;
  const hold = {
    stays: (name, a) => a === ed.arg && (name === "r" || (name === "q" && ed.isNew)),
    leave: () => leavePage(ed),
    flush: () => { if (ed.dirty) { clearTimeout(ed.timer); savePage(ed, { keepalive: true }); } },
  };
  occupy(hold);

  const listKey = lastList.has(b.at.tab) ? lastList.get(b.at.tab) : "";
  const parent = b.path
    ? listHash(b, ed.folder || (previousHash() === listHash(b, TOP) ? TOP : listKey))
    : listHash(b, "");
  const parentLabel = ed.folder ? baseName(ed.folder) : b.label;
  const actions = `<button class="done strong" hidden>Done</button>` + openButton(b) +
    (ed.isNew ? "" : `<button class="export" aria-label="Export" title="Export">${ownIcons.export}</button>`) +
    (b.writes ? `<button class="delete" aria-label="Delete ${esc(b.noun)}">${icons.trash}</button>` : "");
  const names = await shareLabels();
  const page = `
      <div class="editor doc${b.writes ? "" : " read-only"}">
        <input class="title" placeholder="Title" value="${esc(ed.isNew ? "" : ed.stem)}" autocapitalize="sentences" enterkeyhint="next"${b.writes ? "" : " readonly"}>
        <p class="stamp"><span class="when">${esc(formatDate(ed.modified, { long: true }))}</span>${
          ed.word ? `<span class="badge">Word</span>` : ""}${
          ed.where ? `<span class="badge where">${esc(ed.where)}</span>` : ""}<span class="status"></span></p>
        ${b.writes ? toolbar() : ""}
        <div class="doc-body" ${b.writes ? 'contenteditable="true"' : ""} spellcheck="true">${blocksHtml(ed.doc.blocks)}</div>
        ${whereabouts(ed.isNew ? whereNew(b, ed.folder, names) : whereIs(b, record, names))}
      </div>`;
  let view = null;
  if (wide()) {
    view = listView(b, await load(b), listKey, ed.id);
    mount(nav({ title: ed.stem || "New", right: actions }) + `
      <main class="split${folded() ? " folded" : ""}">
        <section class="side">${sideHead(view)}${view.html}</section>
        <section class="page">${page}</section>
      </main>` + tabs(b.at.tab));
  } else {
    mount(nav({ back: parent, backLabel: parentLabel, title: ed.stem, right: actions }) + `<main>${page}</main>`);
  }
  wireShell();
  if (view) { view.wire(app.querySelector(".side")); wireFold(); }
  app.querySelector(".nav").classList.add("lined");

  const box = app.querySelector(".doc");
  ed.titleEl = box.querySelector(".title");
  ed.statusEl = box.querySelector(".stamp .status");
  ed.bodyEl = box.querySelector(".doc-body");
  const done = app.querySelector(".nav .done");
  const del = app.querySelector(".nav .delete");
  const openEl = app.querySelector(".nav .open");
  const exportEl = app.querySelector(".nav .export");
  openEl.addEventListener("click", () => openOther(b));
  if (exportEl) exportEl.addEventListener("click", () => exportMenu(ed));
  // While the page is being typed in, the bar is Done's.
  const editing = (on) => {
    done.hidden = !on;
    openEl.hidden = on;
    if (del) del.hidden = on;
    if (exportEl) exportEl.hidden = on;
  };

  ed.changed = () => {
    ed.dirty = true;
    setStatus(ed, "");
    clearTimeout(ed.timer);
    ed.timer = setTimeout(() => savePage(ed), SAVE_DELAY);
  };
  if (!b.writes) return;

  ed.titleEl.addEventListener("input", ed.changed);
  ed.titleEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); ed.bodyEl.focus(); }
  });
  ed.bodyEl.addEventListener("input", ed.changed);
  ed.bodyEl.addEventListener("paste", (event) => {
    // Pasted markup is reduced to what a document keeps on the next save;
    // plain text comes in as paragraphs, not as one long line.
    const html = event.clipboardData.getData("text/html");
    if (html) return;
    const text = event.clipboardData.getData("text/plain");
    if (!text) return;
    event.preventDefault();
    const paragraphs = text.split(/\n{2,}/).map((p) => `<p>${esc(p).replace(/\n/g, "<br>")}</p>`).join("");
    document.execCommand("insertHTML", false, paragraphs);
  });
  box.querySelector(".doc-tools").addEventListener("mousedown", (event) => event.preventDefault());
  box.querySelector(".doc-tools").addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    ed.bodyEl.focus();
    const { kind, arg: what } = button.dataset;
    if (kind === "cmd") document.execCommand(what, false, null);
    else if (kind === "block") document.execCommand("formatBlock", false, what);
    else if (kind === "link") {
      const selection = window.getSelection();
      const anchor = selection && selection.anchorNode && selection.anchorNode.parentElement.closest("a");
      if (anchor) { document.execCommand("unlink", false, null); }
      else {
        const url = await askText("Link to", "https://", { yes: "Link", placeholder: "https://…" });
        ed.bodyEl.focus();
        if (url && url.trim() && url.trim() !== "https://") document.execCommand("createLink", false, url.trim());
      }
    }
    ed.changed();
  });
  box.addEventListener("focusin", () => editing(true));
  box.addEventListener("focusout", () => {
    setTimeout(() => { if (!box.contains(document.activeElement)) editing(false); }, 0);
    if (ed.dirty) { clearTimeout(ed.timer); savePage(ed); }
  });
  done.addEventListener("click", () => document.activeElement && document.activeElement.blur());
  del.addEventListener("click", async () => {
    if (ed.isNew) { back(parent); return; }
    if (!await ask(`Delete “${ed.stem}”?`)) return;
    try {
      clearTimeout(ed.timer);
      ed.dirty = false;
      await api("DELETE", recordsUrl(b.model.id, ed.id));
      vacate(hold);
      open = null;
      back(parent);
    } catch (err) { toast(err.message); }
  });
  if (ed.isNew) ed.titleEl.focus();
}

// -- saving ----------------------------------------------------------------------------------
function moved(ed, record) {
  ed.id = record.id;
  ed.arg = pageArg(ed.b, record.id);
  replace(pageHash(ed.b, record.id));
  showWhereabouts(whereIs(ed.b, record));
}

const bodyDoc = (ed) => new Doc(blocksOf(ed.bodyEl));

async function savePage(ed, { keepalive = false } = {}) {
  if (!ed.dirty) return;
  if (ed.saving) { ed.pending = true; return; }
  const { b } = ed;
  ed.dirty = false;
  ed.saving = true;
  setStatus(ed, "Saving…");
  try {
    const title = fileStem(ed.titleEl.value);
    ed.doc = bodyDoc(ed);
    const text = ed.doc.toText();
    if (ed.isNew) {
      if (!title && !ed.doc.text.trim()) { setStatus(ed, ""); return; }
      const made = await createUnique(ed, title || `New ${b.noun}`, text);
      ed.isNew = false;
      ed.created = true;
      Object.assign(ed, pageState(b, made), { doc: ed.doc });
      moved(ed, made);
    } else {
      if (title && title !== ed.stem) await renameTo(ed, title);
      let saved;
      try {
        saved = await api("PATCH", recordsUrl(b.model.id, ed.id), { fields: { [b.body]: text }, rev: ed.rev }, { keepalive });
      } catch (err) {
        const current = err.status === 409 && err.detail && err.detail.current;
        if (!current) throw err;
        const fresh = pageState(b, current);
        ed.rev = fresh.rev;
        ed.doc = fresh.doc;
        ed.bodyEl.innerHTML = blocksHtml(fresh.doc.blocks);
        toast(`This ${b.noun} changed elsewhere — showing that copy`);
        setStatus(ed, "Reloaded");
        return;
      }
      ed.rev = saved.rev;
      ed.modified = seconds(saved.updated_at) || ed.modified;
    }
    const center = app.querySelector(".nav .center .text");
    if (center && open === ed) center.textContent = ed.stem;
    setStatus(ed, "Saved");
  } catch (err) {
    ed.dirty = true;
    setStatus(ed, "Not saved", true);
    if (err.status !== 401) toast(err.message);
  } finally {
    ed.saving = false;
    if (ed.pending) { ed.pending = false; ed.dirty = true; savePage(ed); }
  }
}

// A new document is a file nobody else in its folder has the name of.
async function createUnique(ed, stem, text) {
  const { b } = ed;
  let taken = new Set();
  try { taken = new Set((await load(b)).pages.filter((p) => p.folder === ed.folder).map((p) => p.title)); }
  catch { /* the server will say if it is taken */ }
  for (let n = 1; n < 100; n += 1) {
    const name = n === 1 ? stem : `${stem} ${n}`;
    if (taken.has(name)) continue;
    const fields = { ...fixedFields(b), [b.body]: text };
    if (b.path) fields[b.path] = wholePath(b, joinPath(ed.folder, name));
    else fields[b.title] = withSuffix(b, name);
    return api("POST", recordsUrl(b.model.id), { fields });
  }
  throw new Error(`Too many called ${stem}`);
}

async function renameTo(ed, stem) {
  const { b } = ed;
  // A Word file stays a Word file under its new name.
  const name = ed.word ? stem + WORD : withSuffix(b, stem);
  try {
    const renamed = await api("PATCH", recordsUrl(b.model.id, ed.id), { fields: { [b.title]: name } });
    ed.stem = pageState(b, renamed).stem;
    ed.rev = renamed.rev;
    moved(ed, renamed);
  } catch (err) {
    if (err.status === 400) { toast(err.message); ed.titleEl.value = ed.stem; return; }
    throw err;
  }
}

// -- export ---------------------------------------------------------------------------------
// The document handed over to save in another shape — Word, PDF, Markdown
// — made by the server from the same blocks; a document that is a Word
// file already is handed over as it is. Nothing is written beside it.
function exportMenu(ed) {
  if (ed.isNew) return;
  choose("Export as", EXPORTS.map(([suffix, label]) => ({ label, run: () => exportAs(ed, suffix) })));
}

async function exportAs(ed, suffix) {
  if (ed.dirty) { clearTimeout(ed.timer); await savePage(ed); }
  while (ed.saving) await new Promise((r) => setTimeout(r, 50));
  try {
    await download(ed.b, ed.id, suffix, ed.stem + suffix);
    toast(`Saved ${ed.stem}${suffix}`);
  } catch (err) { toast(err.message); }
}

// Leaving saves what is there, and throws away a document that never got
// a name or a word.
async function leavePage(ed) {
  if (open === ed) open = null;
  clearTimeout(ed.timer);
  if (ed.dirty) await savePage(ed);
  while (ed.saving) await new Promise((r) => setTimeout(r, 50));
  if (ed.created && !fileStem(ed.titleEl.value) && !bodyDoc(ed).text.trim()) {
    try { await api("DELETE", recordsUrl(ed.b.model.id, ed.id)); }
    catch { /* it will show up; fine */ }
  }
}
