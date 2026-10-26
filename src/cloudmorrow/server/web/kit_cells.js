/* The kit's `sheet`: a spreadsheet, one `.cell` file a sheet (docs/CELLS.md).

   A screen binds the file `model`, its `title`, and `cells`: the text
   field the file's text is in — one JSON object, {"cells": {"A1": "Rent",
   "B4": "=SUM(B1:B3)"}} — and says, as an editor's does, `where` the files
   are (a share, and the folder under it: `within`) and their `suffix`.
   The sheets are listed newest first, by their path under that folder;
   one opens as a grid with a formula bar over it, worked out by
   kit_cells_rules.js, the same rules the terminal and the command line
   follow in quill/cells.py. Nothing here knows what a budget is.

   A click selects a cell, a drag or Shift a range, a heading its row or
   column; Delete clears what is selected. Over the formula bar, buttons
   for the borders of the selected cells; on a row's or a column's heading
   (or the right button anywhere) a menu to put rows and columns in or take
   them out, the formulas following (kit_cells_rules.js).

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
  SAVE_DELAY, api, app, back, baseName, esc, fileStem, formatDate, heading, icons, mount, nav, occupy,
  recordsUrl, renderRoute, replace, seconds, sectionOf, setStatus, tabs, toast, vacate, wireShell,
} from "./core.js";
import { installCard } from "./install.js";
import { mayWrite, sheetHash } from "./kit.js";
import {
  fixedFields, foldButton, folded, trimSlashes, underRoot, wholePath, wide, wireFold, withQuery,
  withSuffix, withoutSuffix,
} from "./kit_editor.js";
import { CellError, SIDES, Sheet, colName, extent, isFormula, parseRef, rangeName, refName, wantsRef } from "./kit_cells_rules.js";
import { ask } from "./dialog.js";
import { choose } from "./actions.js";

const NEW = "~new";

// -- the screen's bindings ---------------------------------------------------------
function bind(at) {
  const { quill, screen } = at;
  const model = quill.models[screen.model];
  const where = Object.fromEntries(Object.entries(screen.where || {}).map(([k, v]) => [k, String(v)]));
  const suffix = screen.suffix || "";
  const filters = suffix ? { ...where, suffix } : where;
  return {
    at,
    model,
    title: screen.title || model.title || "name",
    cells: screen.cells || "text",
    path: screen.path || "",
    where,
    suffix,
    root: trimSlashes(where.within || ""),
    // On every listing: the share, the folder, the suffix.
    query: new URLSearchParams(filters).toString(),
    label: screen.label || quill.name,
    // A sheet, whatever the file datamodel calls itself.
    noun: "sheet",
    writes: mayWrite(model),
  };
}

const openHash = (b, id) => sheetHash(b.at, b.model.id, id);
const openArg = (b, id) => `${b.at.quill.id}/${b.at.screen.id}/${b.model.id}/${id}`;
// A sheet's title is its file's name without the suffix; what the list
// says is its path under the root, when one is bound.
const titleOf = (b, r) => withoutSuffix(b, String(r.fields[b.title] || "").trim())
  || baseName(withoutSuffix(b, underRoot(b, r.fields[b.path]))) || "Untitled";
const keyOf = (b, r) => (b.path ? withoutSuffix(b, underRoot(b, r.fields[b.path])) : "") || titleOf(b, r);
const listSheets = (b) => api("GET", recordsUrl(b.model.id, "", withQuery(b, "")));
const byNewest = (a, c) => (seconds(c.updated_at) || 0) - (seconds(a.updated_at) || 0);

// -- the list -----------------------------------------------------------------------------
// What the list screen is, for a phone to draw alone and a computer to draw
// beside a sheet: {title, html, wire}.
function listView(b, records, openId = "") {
  const compose = !b.writes ? "" : `<a class="button compose" href="${b.at.base}/${NEW}" aria-label="New ${esc(b.noun)}">${icons.compose}</a>`;
  const rows = records.slice().sort(byNewest);
  // A listing leaves a file's text out, so a row is its path and its date.
  const row = (r) => `<a class="row${r.id === openId ? " current" : ""}" href="${openHash(b, r.id)}">
      <span class="main"><span class="title">${esc(keyOf(b, r))}</span>
      <span class="meta"><span class="date">${esc(formatDate(seconds(r.updated_at) || 0))}</span></span></span></a>`;
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
        show(listing, rows.filter((r) => keyOf(b, r).toLowerCase().includes(needle)), { searching: true });
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
  const view = listView(b, await listSheets(b));
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
    sheet: Sheet.fromText(record.fields[b.cells]),
    modified: seconds(record.updated_at) || Date.now() / 1000,
  };
}

async function renderSheet(b, { record = null, isNew = false, arg }) {
  const ed = isNew
    ? { isNew: true, created: false, id: "", stem: "", rev: null, sheet: new Sheet(), modified: Date.now() / 1000 }
    : { isNew: false, created: false, ...sheetState(b, record) };
  // `at` is the cell that is selected — the one the formula bar edits —
  // and `anchor` the far corner of the selection, the same cell when it is
  // one cell; Infinity for a whole row or column, however wide the grid.
  Object.assign(ed, { b, arg, dirty: false, saving: false, pending: false, timer: null,
                      at: [0, 0], anchor: [0, 0], editing: null, point: null, rows: 0, cols: 0 });
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
        ${b.writes ? formatBar() : ""}
        <div class="formula-bar"><span class="where">A1</span><input class="formula" spellcheck="false" autocapitalize="none" autocorrect="off" placeholder="Type a value, or =SUM(B1:B3)"${b.writes ? "" : " readonly"}></div>
        <div class="grid-wrap" tabindex="0"><table class="grid"></table></div>
      </div>`;
  let view = null;
  if (wide()) {
    view = listView(b, await listSheets(b), ed.id);
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
  ed.formatEl = box.querySelector(".format-bar");
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
  // The border buttons: the grid keeps the focus, so the keys go on working.
  ed.formatEl.addEventListener("mousedown", (event) => { if (event.target.closest("button")) event.preventDefault(); });
  ed.formatEl.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-border]");
    if (!button) return;
    if (ed.editing) commit(ed);
    setBorders(ed, button.dataset.border);
    ed.wrap.focus();
  });
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
  const [farRow, farCol] = ed.anchor.map((n) => (Number.isFinite(n) ? n + 2 : 0));
  ed.rows = Math.max(rows, ed.at[0] + 2, farRow);
  ed.cols = Math.max(cols, ed.at[1] + 2, farCol);
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
    const sides = ed.sheet.border(name);
    for (const side of SIDES) td.classList.toggle(`b-${side}`, sides.includes(side));
  }
}

const cellAt = (ed, r, c) => ed.table.querySelector(`td[data-r="${r}"][data-c="${c}"]`);

// -- the selection ----------------------------------------------------------------------
// One cell, or the block between `at` and `anchor`: a drag, Shift and a
// click or an arrow move the far corner and the cell stays, as in Excel;
// a heading takes a whole row or column.
const corner = (ed) => [Math.min(ed.anchor[0], ed.rows - 1), Math.min(ed.anchor[1], ed.cols - 1)];
const rect = (ed) => {
  const far = corner(ed);
  return [Math.min(far[0], ed.at[0]), Math.min(far[1], ed.at[1]), Math.max(far[0], ed.at[0]), Math.max(far[1], ed.at[1])];
};
const isRange = (ed) => ed.anchor[0] !== ed.at[0] || ed.anchor[1] !== ed.at[1];
// Whether the selection is whole rows, or whole columns.
const wholeRows = (ed) => { const [, c0, , c1] = rect(ed); return c0 === 0 && c1 === ed.cols - 1; };
const wholeCols = (ed) => { const [r0, , r1] = rect(ed); return r0 === 0 && r1 === ed.rows - 1; };

function select(ed, r, c, { scroll = true, extend = false } = {}) {
  r = Math.max(0, r);
  c = Math.max(0, c);
  if (!extend) ed.at = [r, c];
  ed.anchor = [r, c];
  settle(ed, scroll ? [r, c] : null);
}

// Rows `from` to `to`, whole; the cell the formula bar edits is the first of `from`.
function selectRows(ed, from, to) {
  ed.at = [from, 0];
  ed.anchor = [to, Infinity];
  settle(ed, null);
}

function selectCols(ed, from, to) {
  ed.at = [0, from];
  ed.anchor = [Infinity, to];
  settle(ed, null);
}

// The selection as it now is, shown: the grid grown to hold it, the
// formula bar on its cell, and `into` scrolled into view.
function settle(ed, into) {
  const far = ed.anchor.map((n) => (Number.isFinite(n) ? n : 0));
  if (Math.max(ed.at[0], far[0]) >= ed.rows || Math.max(ed.at[1], far[1]) >= ed.cols) drawGrid(ed);
  showSelection(ed);
  const name = refName(...ed.at);
  ed.whereEl.textContent = name;
  if (document.activeElement !== ed.formulaEl) ed.formulaEl.value = ed.sheet.raw(name);
  if (into) cellAt(ed, ...into).scrollIntoView({ block: "nearest", inline: "nearest" });
}

function showSelection(ed) {
  for (const el of ed.table.querySelectorAll(".selected, .active, th.current")) el.classList.remove("selected", "active", "current");
  const [r0, c0, r1, c1] = rect(ed);
  for (let r = r0; r <= r1; r += 1) {
    ed.table.querySelector(`th.row[data-r="${r}"]`).classList.add("current");
    for (let c = c0; c <= c1; c += 1) cellAt(ed, r, c).classList.add("selected");
  }
  for (let c = c0; c <= c1; c += 1) ed.table.querySelector(`th.col[data-c="${c}"]`).classList.add("current");
  cellAt(ed, ...ed.at).classList.add("active");
  showFormat(ed);
}

// Every cell of the selection, by name.
function selectedNames(ed) {
  const [r0, c0, r1, c1] = rect(ed);
  const names = [];
  for (let r = r0; r <= r1; r += 1) for (let c = c0; c <= c1; c += 1) names.push(refName(r, c));
  return names;
}

// Delete, with a selection: every cell in it is cleared, and it stays selected.
function clearSelection(ed) {
  if (!ed.b.writes) return;
  if (ed.editing) commit(ed);
  let changed = false;
  for (const name of selectedNames(ed)) {
    if (!ed.sheet.raw(name)) continue;
    ed.sheet.set(name, "");
    changed = true;
  }
  if (changed) { ed.changed(); refresh(ed); }
  settle(ed, null);
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
  input.addEventListener("input", () => { endPoint(ed); ed.formulaEl.value = input.value; });
  input.addEventListener("keydown", (event) => {
    if (pointKeys(ed, input, event)) return;
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
  endPoint(ed);
  const { name, input } = ed.editing;
  ed.editing = null;
  const changed = put(ed, name, input.value);
  const [rows, cols] = extent(ed.sheet.cells);
  if (changed && (rows > ed.rows || cols > ed.cols)) drawGrid(ed); else refresh(ed);
  select(ed, ...ed.at, { scroll: false });
}

function cancel(ed) {
  if (!ed.editing) return;
  endPoint(ed);
  ed.editing = null;
  refresh(ed);
  select(ed, ...ed.at, { scroll: false });
}

// A step: the cell moves, or with Shift the far corner of the selection.
function move(ed, dr, dc, extend = false) {
  const from = extend ? corner(ed) : ed.at;
  select(ed, from[0] + dr, from[1] + dc, { extend });
}

// -- borders ---------------------------------------------------------------------------------
// The buttons over the formula bar: a side of the selection — its top
// row's top, its last column's right — all four around it, every side of
// every cell, or none. One that is there already comes off again.
const BORDER_BUTTONS = [
  ["all", "All borders"], ["outer", "Outside borders"], ["top", "Top border"], ["bottom", "Bottom border"],
  ["left", "Left border"], ["right", "Right border"], ["none", "No borders"],
];
const GLYPH_LINES = { top: "M2 2h12", right: "M14 2v12", bottom: "M2 14h12", left: "M2 2v12", across: "M2 8h12", down: "M8 2v12" };
const GLYPH_SOLID = {
  all: ["top", "right", "bottom", "left", "across", "down"], outer: ["top", "right", "bottom", "left"],
  top: ["top"], bottom: ["bottom"], left: ["left"], right: ["right"], none: [],
};

function borderGlyph(kind) {
  const solid = GLYPH_SOLID[kind];
  const lines = Object.entries(GLYPH_LINES).map(([side, d]) => solid.includes(side)
    ? `<path d="${d}" stroke="currentColor" stroke-width="2"/>`
    : `<path d="${d}" stroke="currentColor" stroke-width="1" stroke-dasharray="1 2" opacity=".45"/>`).join("");
  return `<svg width="16" height="16" viewBox="0 0 16 16" fill="none" shape-rendering="crispEdges" aria-hidden="true">${lines}</svg>`;
}

function formatBar() {
  return `<div class="format-bar" role="toolbar" aria-label="Borders">${BORDER_BUTTONS.map(([kind, label]) =>
    `<button type="button" class="fmt-button" data-border="${kind}" title="${label}" aria-label="${label}">${borderGlyph(kind)}</button>`).join("")}</div>`;
}

// Which sides of which cells a button is about, for the selection as it is.
function borderTargets(ed, kind) {
  const [r0, c0, r1, c1] = rect(ed);
  const targets = [];
  for (let r = r0; r <= r1; r += 1) {
    for (let c = c0; c <= c1; c += 1) {
      const name = refName(r, c);
      const sides = [];
      if (kind === "all") sides.push(...SIDES);
      if ((kind === "top" || kind === "outer") && r === r0) sides.push("top");
      if ((kind === "bottom" || kind === "outer") && r === r1) sides.push("bottom");
      if ((kind === "left" || kind === "outer") && c === c0) sides.push("left");
      if ((kind === "right" || kind === "outer") && c === c1) sides.push("right");
      for (const side of sides) targets.push([name, side]);
    }
  }
  return targets;
}

function setBorders(ed, kind) {
  if (!ed.b.writes) return;
  let changed = false;
  if (kind === "none") {
    for (const name of selectedNames(ed)) {
      if (!ed.sheet.border(name).length) continue;
      ed.sheet.setBorder(name, []);
      changed = true;
    }
  } else {
    const targets = borderTargets(ed, kind);
    const missing = targets.some(([name, side]) => !ed.sheet.border(name).includes(side));
    for (const [name, side] of targets) {
      const had = ed.sheet.border(name);
      ed.sheet.setBorder(name, missing ? [...had, side] : had.filter((s) => s !== side));
    }
    changed = targets.length > 0;
  }
  if (!changed) return;
  ed.changed();
  refresh(ed);
  showFormat(ed);
}

// The buttons say which borders the selection has.
function showFormat(ed) {
  if (!ed.formatEl) return;
  for (const button of ed.formatEl.querySelectorAll("button[data-border]")) {
    const kind = button.dataset.border;
    if (kind === "none") continue;
    const targets = borderTargets(ed, kind);
    const on = targets.length > 0 && targets.every(([name, side]) => ed.sheet.border(name).includes(side));
    button.classList.toggle("on", on);
    button.setAttribute("aria-pressed", on ? "true" : "false");
  }
}

// -- rows and columns ---------------------------------------------------------------------
// The menu on a heading, or the right button anywhere: rows or columns put
// in before or after the selection, as many as are selected, or taken out.
// The sheet moves and the formulas follow (kit_cells_rules.js). Taking out
// rows that hold something asks first: there is no undo.
function menuChoices(ed, kind) {
  const [r0, c0, r1, c1] = rect(ed);
  const nr = r1 - r0 + 1;
  const nc = c1 - c0 + 1;
  const rowsSaid = nr === 1 ? `row ${r0 + 1}` : `rows ${r0 + 1}–${r1 + 1}`;
  const colsSaid = nc === 1 ? `column ${colName(c0)}` : `columns ${colName(c0)}–${colName(c1)}`;
  const rows = [
    { label: nr === 1 ? "Insert row above" : `Insert ${nr} rows above`, run: () => insertRows(ed, r0, nr) },
    { label: nr === 1 ? "Insert row below" : `Insert ${nr} rows below`, run: () => insertRows(ed, r1 + 1, nr) },
    { label: `Delete ${rowsSaid}`, tone: "danger", run: () => deleteRows(ed, r0, nr, rowsSaid) },
  ];
  const cols = [
    { label: nc === 1 ? "Insert column left" : `Insert ${nc} columns left`, run: () => insertCols(ed, c0, nc) },
    { label: nc === 1 ? "Insert column right" : `Insert ${nc} columns right`, run: () => insertCols(ed, c1 + 1, nc) },
    { label: `Delete ${colsSaid}`, tone: "danger", run: () => deleteCols(ed, c0, nc, colsSaid) },
  ];
  const clear = selectedNames(ed).some((name) => ed.sheet.raw(name)) ? [{ label: "Clear", run: () => clearSelection(ed) }, { sep: true }] : [];
  if (kind === "rows") return [...clear, ...rows];
  if (kind === "cols") return [...clear, ...cols];
  return [...clear, ...rows, { sep: true }, ...cols];
}

let menuOpen = null;
function closeMenu() { if (menuOpen) menuOpen(); }

/** The menu for the selection: at the pointer on a computer, a sheet from the bottom on a phone. */
function openMenu(ed, kind, { x = null, y = null } = {}) {
  closeMenu();
  const choices = menuChoices(ed, kind);
  if (matchMedia("(pointer: coarse)").matches || x === null) {
    choose("", choices.filter((c) => !c.sep));
    return;
  }
  const menu = document.createElement("div");
  menu.className = "cell-menu";
  menu.setAttribute("role", "menu");
  menu.innerHTML = choices.map((c, i) => (c.sep ? "<hr>" :
    `<button type="button" role="menuitem"${c.tone === "danger" ? ' class="danger"' : ""} data-choice="${i}">${esc(c.label)}</button>`)).join("");
  document.body.appendChild(menu);
  menu.style.left = `${Math.max(8, Math.min(x, innerWidth - menu.offsetWidth - 8))}px`;
  menu.style.top = `${Math.max(8, Math.min(y, innerHeight - menu.offsetHeight - 8))}px`;
  const items = [...menu.querySelectorAll("button")];
  const gone = new AbortController();
  const close = () => { menu.remove(); gone.abort(); menuOpen = null; };
  menuOpen = close;
  menu.addEventListener("click", (event) => {
    const button = event.target.closest("[data-choice]");
    if (!button) return;
    close();
    ed.wrap.focus();
    choices[+button.dataset.choice].run();
  });
  menu.addEventListener("keydown", (event) => {
    const i = items.indexOf(document.activeElement);
    if (event.key === "ArrowDown") items[(i + 1) % items.length].focus();
    else if (event.key === "ArrowUp") items[(i - 1 + items.length) % items.length].focus();
    else if (event.key === "Escape" || event.key === "Tab") { close(); ed.wrap.focus(); }
    else return;
    event.preventDefault();
  });
  const { signal } = gone;
  document.addEventListener("mousedown", (event) => { if (!menu.contains(event.target)) close(); }, { capture: true, signal });
  document.addEventListener("scroll", close, { capture: true, signal });
  addEventListener("resize", close, { signal });
  addEventListener("hashchange", close, { signal });
  items[0].focus();
}

// How many cells rows (or columns) `from` to `to` hold.
function heldBy(ed, axis, from, to) {
  return Object.keys(ed.sheet.cells).filter((name) => {
    const at = parseRef(name);
    return at && at[axis] >= from && at[axis] <= to;
  }).length;
}

async function mayTakeOut(ed, axis, from, to, said) {
  const held = heldBy(ed, axis, from, to);
  if (!held) return true;
  const what = held === 1 ? "One cell has something in it" : `${held} cells have something in them`;
  return await ask(`Delete ${said}?\n\n${what}, and there is no undo.`);
}

function insertRows(ed, at, n) {
  if (ed.editing) commit(ed);
  ed.sheet.insertRows(at, n);
  ed.changed();
  ed.at = ed.anchor = [at, 0];
  drawGrid(ed);
  selectRows(ed, at, at + n - 1);
}

async function deleteRows(ed, at, n, said) {
  if (ed.editing) commit(ed);
  if (!await mayTakeOut(ed, 0, at, at + n - 1, said)) return;
  ed.sheet.deleteRows(at, n);
  ed.changed();
  ed.at = ed.anchor = [at, 0];
  drawGrid(ed);
  selectRows(ed, at, at);
}

function insertCols(ed, at, n) {
  if (ed.editing) commit(ed);
  ed.sheet.insertCols(at, n);
  ed.changed();
  ed.at = ed.anchor = [0, at];
  drawGrid(ed);
  selectCols(ed, at, at + n - 1);
}

async function deleteCols(ed, at, n, said) {
  if (ed.editing) commit(ed);
  if (!await mayTakeOut(ed, 1, at, at + n - 1, said)) return;
  ed.sheet.deleteCols(at, n);
  ed.changed();
  ed.at = ed.anchor = [0, at];
  drawGrid(ed);
  selectCols(ed, at, at);
}

// -- pointing ----------------------------------------------------------------------------
// Excel's way of writing a reference. While the formula wants one — after
// `=`, an operator, `(`, a comma or a colon — the arrows pick a cell and
// its name is written where the caret is, following as they move; Shift
// and an arrow make it a range; a click on a cell points the same way.
// Enter keeps the name and typing goes on, as does any other key.
const ARROWS = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
const MODIFIERS = new Set(["Shift", "Control", "Alt", "Meta"]);

// The input that edits the cell at `ed.at` right now, if any.
const editingInput = (ed) =>
  ed.editing ? ed.editing.input : document.activeElement === ed.formulaEl ? ed.formulaEl : null;

function pointing(ed, input) {
  if (ed.point) return true;
  const { value, selectionStart, selectionEnd } = input;
  return selectionStart === selectionEnd && wantsRef(value.slice(0, selectionStart));
}

function pointTo(ed, input, target, extend) {
  const r = Math.min(Math.max(0, target[0]), ed.rows - 1);
  const c = Math.min(Math.max(0, target[1]), ed.cols - 1);
  const point = ed.point || { start: input.selectionStart, end: input.selectionStart, anchor: [r, c], at: [r, c] };
  point.at = [r, c];
  if (!extend) point.anchor = [r, c];
  const name = rangeName(point.anchor, point.at);
  input.value = input.value.slice(0, point.start) + name + input.value.slice(point.end);
  point.end = point.start + name.length;
  input.setSelectionRange(point.end, point.end);
  if (input !== ed.formulaEl) ed.formulaEl.value = input.value;
  ed.point = point;
  showPoint(ed);
}

function showPoint(ed) {
  for (const td of ed.table.querySelectorAll("td.pointed")) td.classList.remove("pointed");
  if (!ed.point) return;
  const [[r0, c0], [r1, c1]] = [ed.point.anchor, ed.point.at];
  for (let r = Math.min(r0, r1); r <= Math.max(r0, r1); r++) {
    for (let c = Math.min(c0, c1); c <= Math.max(c0, c1); c++) cellAt(ed, r, c).classList.add("pointed");
  }
  cellAt(ed, ...ed.point.at).scrollIntoView({ block: "nearest", inline: "nearest" });
}

function endPoint(ed) {
  if (!ed.point) return;
  ed.point = null;
  showPoint(ed);
}

// A key in an input editing the cell at `ed.at`: true when it was pointing's.
function pointKeys(ed, input, event) {
  const arrow = ARROWS[event.key];
  if (arrow && !event.ctrlKey && !event.metaKey && !event.altKey && pointing(ed, input)) {
    event.preventDefault();
    const from = ed.point ? ed.point.at : ed.at;
    pointTo(ed, input, [from[0] + arrow[0], from[1] + arrow[1]], event.shiftKey);
    return true;
  }
  if (!ed.point) return false;
  if (event.key === "Enter") { event.preventDefault(); endPoint(ed); return true; }
  if (!MODIFIERS.has(event.key)) endPoint(ed);
  return false;
}

// What the mouse button went down on, until it comes up: a drag across
// cells, down the row headings or along the column headings widens the
// selection; while a formula wants a reference, it points out a range.
let drag = null;
let dragWired = false;
const placeOf = (el) => (el && el.dataset.r !== undefined ? +el.dataset.r : null);
const colOf = (el) => (el && el.dataset.c !== undefined ? +el.dataset.c : null);
const coarse = () => matchMedia("(pointer: coarse)").matches;

function wireGrid(ed) {
  const { wrap, table, formulaEl } = ed;
  if (!dragWired) { document.addEventListener("mouseup", () => { drag = null; }); dragWired = true; }
  table.addEventListener("mousedown", (event) => {
    if (event.button !== 0 || event.target.tagName === "INPUT") return;
    const td = event.target.closest("td");
    const th = event.target.closest("th");
    if (!td && !th) return;
    event.preventDefault();
    const input = editingInput(ed);
    if (td && input && pointing(ed, input)) {
      pointTo(ed, input, [+td.dataset.r, +td.dataset.c], event.shiftKey);
      drag = { kind: "point", input };
      return;
    }
    // The focus first: the formula bar, or the cell's input, keeps what
    // was typed in the cell it was for.
    wrap.focus();
    if (ed.editing) commit(ed);
    if (td) {
      select(ed, +td.dataset.r, +td.dataset.c, { scroll: false, extend: event.shiftKey });
      drag = { kind: "cells" };
    } else if (th.classList.contains("row")) {
      const from = event.shiftKey ? ed.at[0] : +th.dataset.r;
      selectRows(ed, from, +th.dataset.r);
      drag = { kind: "rows", from };
    } else if (th.classList.contains("col")) {
      const from = event.shiftKey ? ed.at[1] : +th.dataset.c;
      selectCols(ed, from, +th.dataset.c);
      drag = { kind: "cols", from };
    } else {
      // The corner: everything.
      ed.at = [0, 0];
      ed.anchor = [Infinity, Infinity];
      settle(ed, null);
    }
  });
  table.addEventListener("mouseover", (event) => {
    if (!drag) return;
    const td = event.target.closest("td");
    const el = td || event.target.closest("th");
    const r = placeOf(el);
    const c = colOf(el);
    if (drag.kind === "cells" && td) select(ed, r, c, { extend: true, scroll: false });
    else if (drag.kind === "rows" && r !== null) selectRows(ed, drag.from, r);
    else if (drag.kind === "cols" && c !== null) selectCols(ed, drag.from, c);
    else if (drag.kind === "point" && td) pointTo(ed, drag.input, [r, c], true);
  });
  table.addEventListener("dblclick", (event) => {
    const td = event.target.closest("td");
    if (!td || event.target.tagName === "INPUT") return;
    select(ed, +td.dataset.r, +td.dataset.c, { scroll: false });
    edit(ed);
  });
  // A finger has no double tap worth waiting for, and no right button: the
  // second tap on the selected cell opens it, on a selected heading its menu.
  table.addEventListener("click", (event) => {
    if (event.target.tagName === "INPUT" || !coarse()) return;
    const td = event.target.closest("td");
    const th = event.target.closest("th");
    if (td) {
      if (+td.dataset.r === ed.at[0] && +td.dataset.c === ed.at[1] && !ed.editing && !isRange(ed)) edit(ed);
      return;
    }
    if (!th || !ed.b.writes) return;
    const [r0, c0, r1, c1] = rect(ed);
    const r = placeOf(th);
    const c = colOf(th);
    if (r !== null && wholeRows(ed) && r >= r0 && r <= r1 && !event.shiftKey) openMenu(ed, "rows");
    else if (c !== null && wholeCols(ed) && c >= c0 && c <= c1 && !event.shiftKey) openMenu(ed, "cols");
  });
  table.addEventListener("contextmenu", (event) => {
    if (!ed.b.writes || event.target.tagName === "INPUT") return;
    const td = event.target.closest("td");
    const th = event.target.closest("th");
    if (!td && !th) return;
    event.preventDefault();
    wrap.focus();
    if (ed.editing) commit(ed);
    const [r0, c0, r1, c1] = rect(ed);
    let kind;
    if (td) {
      const [r, c] = [+td.dataset.r, +td.dataset.c];
      if (r < r0 || r > r1 || c < c0 || c > c1) select(ed, r, c, { scroll: false });
      kind = "cell";
    } else if (th.classList.contains("row")) {
      const r = +th.dataset.r;
      if (!(wholeRows(ed) && r >= r0 && r <= r1)) selectRows(ed, r, r);
      kind = "rows";
    } else if (th.classList.contains("col")) {
      const c = +th.dataset.c;
      if (!(wholeCols(ed) && c >= c0 && c <= c1)) selectCols(ed, c, c);
      kind = "cols";
    } else return;
    openMenu(ed, kind, { x: event.clientX, y: event.clientY });
  });
  wrap.addEventListener("keydown", (event) => {
    if (ed.editing || event.target !== wrap) return;
    const { key, shiftKey } = event;
    if (key === "ArrowDown") move(ed, 1, 0, shiftKey);
    else if (key === "ArrowUp") move(ed, -1, 0, shiftKey);
    else if (key === "ArrowRight") move(ed, 0, 1, shiftKey);
    else if (key === "ArrowLeft") move(ed, 0, -1, shiftKey);
    else if (key === "Tab") move(ed, 0, shiftKey ? -1 : 1);
    else if (key === "Enter" || key === "F2") edit(ed);
    else if (key === "Delete" || key === "Backspace") clearSelection(ed);
    else if (key === "Escape") { if (!isRange(ed)) return; select(ed, ...ed.at, { scroll: false }); }
    else if (key === " " && shiftKey) { const [r0, , r1] = rect(ed); selectRows(ed, r0, r1); }
    else if (key === " " && (event.ctrlKey || event.metaKey)) { const [, c0, , c1] = rect(ed); selectCols(ed, c0, c1); }
    else if (key === "ContextMenu" || (key === "F10" && shiftKey)) {
      if (!ed.b.writes) return;
      const box = cellAt(ed, ...ed.at).getBoundingClientRect();
      openMenu(ed, wholeRows(ed) ? "rows" : wholeCols(ed) ? "cols" : "cell", { x: box.left + 12, y: box.bottom });
    } else if (key === "Home") select(ed, ed.at[0], 0, { extend: shiftKey });
    else if (key === "PageDown") move(ed, 10, 0, shiftKey);
    else if (key === "PageUp") move(ed, -10, 0, shiftKey);
    else if (key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) edit(ed, { initial: key });
    else return;
    event.preventDefault();
  });
  // The formula bar: typing there is typing into the cell.
  formulaEl.addEventListener("input", () => endPoint(ed));
  formulaEl.addEventListener("keydown", (event) => {
    if (pointKeys(ed, formulaEl, event)) return;
    if (event.key === "Enter") {
      event.preventDefault();
      if (ed.editing) cancel(ed);
      if (put(ed, refName(...ed.at), formulaEl.value)) refresh(ed);
      move(ed, event.shiftKey ? -1 : 1, 0);
      wrap.focus();
    } else if (event.key === "Escape") {
      event.preventDefault();
      endPoint(ed);
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
// The sheet's address has moved — made, or renamed, which for a file kept
// by its path is a new id. The screen stays the sheet's.
function moved(ed, record) {
  ed.id = record.id;
  ed.arg = openArg(ed.b, record.id);
  replace(openHash(ed.b, record.id));
}

async function saveSheet(ed, { keepalive = false } = {}) {
  if (!ed.dirty) return;
  if (ed.saving) { ed.pending = true; return; }
  const { b } = ed;
  ed.dirty = false;
  ed.saving = true;
  setStatus(ed, "Saving…");
  try {
    const title = fileStem(ed.titleEl.value);
    const text = ed.sheet.toText();
    if (ed.isNew) {
      if (!title && !Object.keys(ed.sheet.cells).length) { setStatus(ed, ""); return; }
      const made = await createUnique(ed, title || `New ${b.noun}`, text);
      ed.isNew = false;
      ed.created = true;
      Object.assign(ed, sheetState(b, made), { sheet: ed.sheet });
      moved(ed, made);
    } else {
      if (title && title !== ed.stem) await renameTo(ed, title);
      let saved;
      try {
        saved = await api("PATCH", recordsUrl(b.model.id, ed.id), { fields: { [b.cells]: text }, rev: ed.rev }, { keepalive });
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

// A new sheet is a file nobody else under the root has the name of: "New
// sheet", then "New sheet 2" — the server says no to a second of the same.
async function createUnique(ed, stem, text) {
  const { b } = ed;
  let taken = new Set();
  try { taken = new Set((await listSheets(b)).map((r) => keyOf(b, r))); }
  catch { /* the server will say if it is taken */ }
  for (let n = 1; n < 100; n += 1) {
    const name = n === 1 ? stem : `${stem} ${n}`;
    if (taken.has(name)) continue;
    const fields = { ...fixedFields(b), [b.cells]: text };
    if (b.path) fields[b.path] = wholePath(b, name);
    else fields[b.title] = withSuffix(b, name);
    return api("POST", recordsUrl(b.model.id), { fields });
  }
  throw new Error(`Too many called ${stem}`);
}

async function renameTo(ed, stem) {
  const { b } = ed;
  try {
    const renamed = await api("PATCH", recordsUrl(b.model.id, ed.id), { fields: { [b.title]: withSuffix(b, stem) } });
    ed.stem = titleOf(b, renamed);
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

// Leaving saves what is there, and throws away a sheet that never got a
// name or a cell.
async function leaveSheet(ed) {
  if (open === ed) open = null;
  clearTimeout(ed.timer);
  if (ed.editing) commit(ed);
  if (ed.dirty) await saveSheet(ed);
  while (ed.saving) await new Promise((r) => setTimeout(r, 50));
  if (ed.created && !fileStem(ed.titleEl.value) && !Object.keys(ed.sheet.cells).length) {
    try { await api("DELETE", recordsUrl(ed.b.model.id, ed.id)); }
    catch { /* it will show up; fine */ }
  }
}

