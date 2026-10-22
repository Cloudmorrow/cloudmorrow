/* The kit's `sheet`: a spreadsheet, one record a sheet (docs/CELLS.md).

   A screen binds a `model`, its `title`, and `cells`: a json field holding
   what is typed in each cell, by name — {"A1": "Rent", "B4":
   "=SUM(B1:B3)"}. The sheets are listed like any records, newest first;
   one opens as a grid with a formula bar over it, worked out by
   kit_cells_rules.js, the same rules the terminal and the command line
   follow in quill/cells.py. Nothing here knows what a budget is.

   The sheet saves as you type, like a page in the editor; one changed
   elsewhere since it was opened is not written over. Sheets of a
   datamodel you may only read (docs/CIRCLES.md) open read-only: the grid
   shows, and nothing types into it.

   On a phone it is the list, then the sheet; on a computer the list and
   the sheet are side by side, and the list folds away (kit_editor.js's
   split, shared).

   The addresses, under the screen's own (quills.js):
     #/q/<quill>/<screen>                every sheet, newest first
     #/q/<quill>/<screen>/~new           a sheet not made yet
     #/r/<quill>/<screen>/<model>/<id>   a sheet */

import {
  SAVE_DELAY, api, app, back, esc, formatDate, heading, icons, mount, nav, occupy, recordsUrl,
  renderRoute, replace, seconds, sectionOf, setStatus, tabs, toast, vacate, wireShell,
} from "./core.js";
import { installCard } from "./install.js";
import { mayWrite, sheetHash } from "./kit.js";
import { foldButton, folded, wide, wireFold } from "./kit_editor.js";
import { CellError, Sheet, colName, extent, isFormula, refName } from "./kit_cells_rules.js";
import { ask } from "./dialog.js";

const NEW = "~new";

// -- the screen's bindings ---------------------------------------------------------
function bind(at) {
  const { quill, screen } = at;
  const model = quill.models[screen.model];
  return {
    at,
    model,
    title: screen.title || model.title || "name",
    cells: screen.cells || "cells",
    label: screen.label || quill.name,
    noun: model.label.toLowerCase(),
    writes: mayWrite(model),
  };
}

const openHash = (b, id) => sheetHash(b.at, b.model.id, id);
const openArg = (b, id) => `${b.at.quill.id}/${b.at.screen.id}/${b.model.id}/${id}`;
const titleOf = (b, r) => String(r.fields[b.title] || "").trim() || "Untitled";
const countOf = (b, r) => Object.keys(Sheet.fromField(r.fields[b.cells]).cells).length;
const byNewest = (a, c) => (seconds(c.updated_at) || 0) - (seconds(a.updated_at) || 0);

// -- the list -----------------------------------------------------------------------------
// What the list screen is, for a phone to draw alone and a computer to draw
// beside a sheet: {title, html, wire}.
function listView(b, records, openId = "") {
  const compose = !b.writes ? "" : `<a class="button compose" href="${b.at.base}/${NEW}" aria-label="New ${esc(b.noun)}">${icons.compose}</a>`;
  const rows = records.slice().sort(byNewest);
  const row = (r) => {
    const n = countOf(b, r);
    return `<a class="row${r.id === openId ? " current" : ""}" href="${openHash(b, r.id)}">
      <span class="main"><span class="title">${esc(titleOf(b, r))}</span>
      <span class="meta"><span class="date">${esc(formatDate(seconds(r.updated_at) || 0))}</span>` +
      `<span class="preview">${n ? `${n} cell${n === 1 ? "" : "s"}` : "Empty"}</span></span></span></a>`;
  };
  const show = (listing, items, { searching = false } = {}) => {
    if (!items.length) {
      listing.innerHTML = searching
        ? `<p class="empty">Nothing matches.</p>`
        : `<p class="empty mascot"><b>Nothing here yet</b>${b.writes
          ? `Start your first ${esc(b.noun)} with the pen, and it will show up here.` : "When there is, it will show up here."}</p>`;
      return;
    }
    if (searching) { listing.innerHTML = `<div class="group">${items.map(row).join("")}</div>`; return; }
    // Newest first already, so the sections fall out in order: Today,
    // Yesterday, Last 7 Days, Last 30 Days, each month, each year.
    const sections = new Map();
    for (const r of items) {
      const label = sectionOf(seconds(r.updated_at) || 0);
      if (!sections.has(label)) sections.set(label, []);
      sections.get(label).push(r);
    }
    listing.innerHTML = [...sections].map(([label, group]) =>
      `<p class="group-label">${esc(label)}</p><div class="group">${group.map(row).join("")}</div>`).join("");
  };
  return {
    title: b.label,
    html: `${heading(b.label, compose)}
      <div class="search">${icons.search}<input type="search" placeholder="Search" autocapitalize="none" autocorrect="off"></div>
      <div class="install-slot">${installCard()}</div>
      <div class="listing"></div>`,
    wire(root) {
      const listing = root.querySelector(".listing");
      const search = root.querySelector("input[type=search]");
      show(listing, rows);
      search.addEventListener("input", () => {
        const needle = search.value.trim().toLowerCase();
        if (!needle) { show(listing, rows); return; }
        show(listing, rows.filter((r) => titleOf(b, r).toLowerCase().includes(needle)), { searching: true });
      });
    },
  };
}

/** The list of sheets, and a sheet not made yet. */
export async function renderCells(at, arg) {
  const b = bind(at);
  if (arg === NEW && !b.writes) {
    toast(`You can read ${b.noun}s here, not write them`);
    replace(at.base);
    return renderRoute();
  }
  if (arg === NEW) return renderSheet(b, { isNew: true, arg: `${at.quill.id}/${at.screen.id}/${arg}` });
  const records = await api("GET", recordsUrl(b.model.id));
  const view = listView(b, records);
  if (wide()) {
    mount(nav({ title: view.title }) + `
      <main class="split">
        <section class="side">${view.html}</section>
        <section class="page"><p class="empty mascot"><b>Nothing open</b>Choose a ${esc(b.noun)} on the left${
          b.writes ? ", or start one with the pen" : ""}.</p></section>
      </main>` + tabs(at.tab));
  } else {
    mount(nav({ title: view.title }) + `<main>${view.html}</main>` + tabs(at.tab));
  }
  wireShell();
  view.wire(app.querySelector("main"));
}

/** One sheet: the kit's own page, in place of the record sheet. */
export async function renderCellsPage(at, id, arg) {
  const b = bind(at);
  let record;
  try { record = await api("GET", recordsUrl(b.model.id, id)); }
  catch (err) {
    if (err.status === 404) { toast(`That ${b.noun} is gone`); replace(at.base); return renderRoute(); }
    throw err;
  }
  return renderSheet(b, { record, arg });
}

// -- a sheet -------------------------------------------------------------------------------
let open = null;

function sheetState(b, record) {
  return {
    id: record.id, stem: titleOf(b, record), rev: record.rev,
    sheet: Sheet.fromField(record.fields[b.cells]),
    modified: seconds(record.updated_at) || Date.now() / 1000,
  };
}

async function renderSheet(b, { record = null, isNew = false, arg }) {
  const ed = isNew
    ? { isNew: true, created: false, id: "", stem: "", rev: null, sheet: new Sheet(), modified: Date.now() / 1000 }
    : { isNew: false, created: false, ...sheetState(b, record) };
  Object.assign(ed, { b, arg, dirty: false, saving: false, pending: false, timer: null,
                      at: [0, 0], editing: null, rows: 0, cols: 0 });
  open = ed;
  // The screen is this sheet's until it is left: a new one while the hash
  // says new, a saved one while the hash is its own.
  const hold = {
    stays: (name, a) => a === ed.arg && (name === "r" || (name === "q" && ed.isNew)),
    leave: () => leaveSheet(ed),
    flush: () => { if (ed.dirty) { clearTimeout(ed.timer); saveSheet(ed, { keepalive: true }); } },
  };
  occupy(hold);

  const parent = b.at.base;
  const actions = !b.writes ? "" : `<button class="done strong" hidden>Done</button>` +
    `<button class="delete" aria-label="Delete ${esc(b.noun)}">${icons.trash}</button>`;
  const page = `
      <div class="editor cells${b.writes ? "" : " read-only"}">
        <input class="title" placeholder="Title" value="${esc(ed.isNew ? "" : ed.stem)}" autocapitalize="sentences" enterkeyhint="next"${b.writes ? "" : " readonly"}>
        <p class="stamp"><span class="when">${esc(formatDate(ed.modified, { long: true }))}</span><span class="status"></span></p>
        <div class="formula-bar"><span class="where">A1</span><input class="formula" spellcheck="false" autocapitalize="none" autocorrect="off" placeholder="Type a value, or =SUM(B1:B3)"${b.writes ? "" : " readonly"}></div>
        <div class="grid-wrap" tabindex="0"><table class="grid"></table></div>
      </div>`;
  let view = null;
  if (wide()) {
    view = listView(b, await api("GET", recordsUrl(b.model.id)), ed.id);
    mount(nav({ title: ed.stem || "New", right: actions }) + `
      <main class="split${folded() ? " folded" : ""}">
        <section class="side">${view.html}</section>
        <section class="page">${foldButton()}${page}</section>
      </main>` + tabs(b.at.tab));
  } else {
    mount(nav({ back: parent, backLabel: b.label, title: ed.stem, right: actions }) +
      `<main>${page}</main>`);
  }
  wireShell();
  if (view) { view.wire(app.querySelector(".side")); wireFold(); }
  app.querySelector(".nav").classList.add("lined");

  const box = app.querySelector(".cells");
  ed.titleEl = box.querySelector(".title");
  ed.statusEl = box.querySelector(".stamp .status");
  ed.whereEl = box.querySelector(".formula-bar .where");
  ed.formulaEl = box.querySelector(".formula");
  ed.wrap = box.querySelector(".grid-wrap");
  ed.table = box.querySelector(".grid");
  const done = app.querySelector(".nav .done");
  const del = app.querySelector(".nav .delete");

  ed.changed = () => {
    ed.dirty = true;
    setStatus(ed, "");
    clearTimeout(ed.timer);
    ed.timer = setTimeout(() => saveSheet(ed), SAVE_DELAY);
  };
  if (!b.writes) ed.changed = () => {};
  drawGrid(ed);
  select(ed, 0, 0, { scroll: false });
  wireGrid(ed);
  if (!b.writes) return;

  ed.titleEl.addEventListener("input", ed.changed);
  ed.titleEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); ed.wrap.focus(); }
  });
  box.addEventListener("focusin", () => { done.hidden = false; del.hidden = true; });
  box.addEventListener("focusout", () => {
    setTimeout(() => {
      if (!box.contains(document.activeElement)) { done.hidden = true; del.hidden = false; }
    }, 0);
    if (ed.dirty) { clearTimeout(ed.timer); saveSheet(ed); }
  });
  done.addEventListener("click", () => { commit(ed); if (document.activeElement) document.activeElement.blur(); });
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

// -- the grid ------------------------------------------------------------------------------
// As many rows and columns as the sheet uses, with room beyond, and never
// fewer than the selection needs: moving past the edge makes more.
function drawGrid(ed) {
  const [rows, cols] = extent(ed.sheet.cells);
  ed.rows = Math.max(rows, ed.at[0] + 2);
  ed.cols = Math.max(cols, ed.at[1] + 2);
  const head = `<thead><tr><th class="corner"></th>${
    Array.from({ length: ed.cols }, (_, c) => `<th class="col" data-c="${c}">${colName(c)}</th>`).join("")}</tr></thead>`;
  const body = `<tbody>${Array.from({ length: ed.rows }, (_, r) =>
    `<tr><th class="row" data-r="${r}">${r + 1}</th>${
      Array.from({ length: ed.cols }, (_, c) => `<td data-r="${r}" data-c="${c}"></td>`).join("")}</tr>`).join("")}</tbody>`;
  ed.table.innerHTML = head + body;
  refresh(ed);
}

// Every cell's text and tone, from the sheet as it now is.
function refresh(ed) {
  for (const td of ed.table.querySelectorAll("td")) {
    const name = refName(+td.dataset.r, +td.dataset.c);
    const value = ed.sheet.value(name);
    td.textContent = ed.sheet.shown(name);
    td.classList.toggle("num", typeof value === "number");
    td.classList.toggle("bad", value instanceof CellError);
    td.classList.toggle("has-formula", isFormula(ed.sheet.raw(name)));
  }
}

const cellAt = (ed, r, c) => ed.table.querySelector(`td[data-r="${r}"][data-c="${c}"]`);

function select(ed, r, c, { scroll = true } = {}) {
  r = Math.max(0, r);
  c = Math.max(0, c);
  const was = cellAt(ed, ...ed.at);
  if (was) was.classList.remove("selected");
  ed.at = [r, c];
  if (r >= ed.rows || c >= ed.cols) drawGrid(ed);
  const td = cellAt(ed, r, c);
  td.classList.add("selected");
  for (const th of ed.table.querySelectorAll("th.current")) th.classList.remove("current");
  ed.table.querySelector(`th.row[data-r="${r}"]`).classList.add("current");
  ed.table.querySelector(`th.col[data-c="${c}"]`).classList.add("current");
  const name = refName(r, c);
  ed.whereEl.textContent = name;
  if (document.activeElement !== ed.formulaEl) ed.formulaEl.value = ed.sheet.raw(name);
  if (scroll) td.scrollIntoView({ block: "nearest", inline: "nearest" });
}

// -- editing a cell ----------------------------------------------------------------------------
// An input laid in the cell; Enter keeps it and moves down, Tab across,
// Escape leaves the cell as it was. The formula bar edits the same cell
// from above.
function edit(ed, { initial = null } = {}) {
  if (!ed.b.writes || ed.editing) return;
  const td = cellAt(ed, ...ed.at);
  const name = refName(...ed.at);
  const input = document.createElement("input");
  input.className = "cell-input";
  input.spellcheck = false;
  input.autocapitalize = "none";
  input.value = initial === null ? ed.sheet.raw(name) : initial;
  td.textContent = "";
  td.appendChild(input);
  ed.editing = { name, input, td };
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
  input.addEventListener("input", () => { ed.formulaEl.value = input.value; });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); commit(ed); move(ed, event.shiftKey ? -1 : 1, 0); ed.wrap.focus(); }
    else if (event.key === "Tab") { event.preventDefault(); commit(ed); move(ed, 0, event.shiftKey ? -1 : 1); ed.wrap.focus(); }
    else if (event.key === "Escape") { event.preventDefault(); cancel(ed); ed.wrap.focus(); }
  });
  input.addEventListener("blur", () => { if (ed.editing && ed.editing.input === input) commit(ed); });
}

function put(ed, name, raw) {
  if (ed.sheet.raw(name) === raw) return false;
  ed.sheet.set(name, raw);
  ed.changed();
  return true;
}

function commit(ed) {
  if (!ed.editing) return;
  const { name, input } = ed.editing;
  ed.editing = null;
  const changed = put(ed, name, input.value);
  const [rows, cols] = extent(ed.sheet.cells);
  if (changed && (rows > ed.rows || cols > ed.cols)) drawGrid(ed); else refresh(ed);
  select(ed, ...ed.at, { scroll: false });
}

function cancel(ed) {
  if (!ed.editing) return;
  ed.editing = null;
  refresh(ed);
  select(ed, ...ed.at, { scroll: false });
}

const move = (ed, dr, dc) => select(ed, ed.at[0] + dr, ed.at[1] + dc);

function wireGrid(ed) {
  const { wrap, table, formulaEl } = ed;
  table.addEventListener("mousedown", (event) => {
    const td = event.target.closest("td");
    if (!td || event.target.tagName === "INPUT") return;
    event.preventDefault();
    if (ed.editing) commit(ed);
    select(ed, +td.dataset.r, +td.dataset.c, { scroll: false });
    wrap.focus();
  });
  table.addEventListener("dblclick", (event) => {
    const td = event.target.closest("td");
    if (!td || event.target.tagName === "INPUT") return;
    select(ed, +td.dataset.r, +td.dataset.c, { scroll: false });
    edit(ed);
  });
  // A finger has no double tap worth waiting for: the second tap on the
  // selected cell opens it.
  table.addEventListener("click", (event) => {
    const td = event.target.closest("td");
    if (!td || event.target.tagName === "INPUT" || !matchMedia("(pointer: coarse)").matches) return;
    if (+td.dataset.r === ed.at[0] && +td.dataset.c === ed.at[1] && !ed.editing) edit(ed);
  });
  wrap.addEventListener("keydown", (event) => {
    if (ed.editing || event.target !== wrap) return;
    const { key } = event;
    if (key === "ArrowDown") move(ed, 1, 0);
    else if (key === "ArrowUp") move(ed, -1, 0);
    else if (key === "ArrowRight") move(ed, 0, 1);
    else if (key === "ArrowLeft") move(ed, 0, -1);
    else if (key === "Tab") move(ed, 0, event.shiftKey ? -1 : 1);
    else if (key === "Enter" || key === "F2") edit(ed);
    else if (key === "Delete" || key === "Backspace") {
      if (!ed.b.writes) return;
      if (put(ed, refName(...ed.at), "")) refresh(ed);
      select(ed, ...ed.at, { scroll: false });
    } else if (key === "Home") select(ed, ed.at[0], 0);
    else if (key === "PageDown") move(ed, 10, 0);
    else if (key === "PageUp") move(ed, -10, 0);
    else if (key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) edit(ed, { initial: key });
    else return;
    event.preventDefault();
  });
  // The formula bar: typing there is typing into the cell.
  formulaEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      if (ed.editing) cancel(ed);
      if (put(ed, refName(...ed.at), formulaEl.value)) refresh(ed);
      move(ed, event.shiftKey ? -1 : 1, 0);
      wrap.focus();
    } else if (event.key === "Escape") {
      event.preventDefault();
      formulaEl.value = ed.sheet.raw(refName(...ed.at));
      wrap.focus();
    } else if (event.key === "Tab") {
      event.preventDefault();
      if (put(ed, refName(...ed.at), formulaEl.value)) refresh(ed);
      move(ed, 0, event.shiftKey ? -1 : 1);
      wrap.focus();
    }
  });
  formulaEl.addEventListener("blur", () => {
    if (!ed.b.writes || ed.editing) return;
    if (put(ed, refName(...ed.at), formulaEl.value)) refresh(ed);
  });
}

// -- saving --------------------------------------------------------------------------------
async function saveSheet(ed, { keepalive = false } = {}) {
  if (!ed.dirty) return;
  if (ed.saving) { ed.pending = true; return; }
  const { b } = ed;
  ed.dirty = false;
  ed.saving = true;
  setStatus(ed, "Saving…");
  try {
    const title = ed.titleEl.value.trim();
    const fields = { [b.cells]: ed.sheet.toField() };
    if (ed.isNew) {
      if (!title && !Object.keys(ed.sheet.cells).length) { setStatus(ed, ""); return; }
      fields[b.title] = title || `New ${b.noun}`;
      const made = await api("POST", recordsUrl(b.model.id), { fields });
      ed.isNew = false;
      ed.created = true;
      Object.assign(ed, sheetState(b, made), { sheet: ed.sheet });
      ed.arg = openArg(b, made.id);
      replace(openHash(b, made.id));
    } else {
      if (title && title !== ed.stem) fields[b.title] = title;
      let saved;
      try {
        saved = await api("PATCH", recordsUrl(b.model.id, ed.id), { fields, rev: ed.rev }, { keepalive });
      } catch (err) {
        const current = err.status === 409 && err.detail && err.detail.current;
        if (!current) throw err;
        // Somebody else wrote it meanwhile. Theirs is what is kept; show that.
        const fresh = sheetState(b, current);
        ed.rev = fresh.rev;
        ed.sheet = fresh.sheet;
        ed.stem = fresh.stem;
        ed.titleEl.value = fresh.stem;
        if (ed.editing) cancel(ed);
        drawGrid(ed);
        select(ed, ...ed.at, { scroll: false });
        toast(`This ${b.noun} changed elsewhere — showing that copy`);
        setStatus(ed, "Reloaded");
        return;
      }
      ed.rev = saved.rev;
      ed.stem = titleOf(b, saved);
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
    if (ed.pending) { ed.pending = false; ed.dirty = true; saveSheet(ed); }
  }
}

// Leaving saves what is there, and throws away a sheet that never got a
// name or a cell.
async function leaveSheet(ed) {
  if (open === ed) open = null;
  clearTimeout(ed.timer);
  if (ed.editing) commit(ed);
  if (ed.dirty) await saveSheet(ed);
  while (ed.saving) await new Promise((r) => setTimeout(r, 50));
  if (ed.created && !ed.titleEl.value.trim() && !Object.keys(ed.sheet.cells).length) {
    try { await api("DELETE", recordsUrl(ed.b.model.id, ed.id)); }
    catch { /* it will show up; fine */ }
  }
}

