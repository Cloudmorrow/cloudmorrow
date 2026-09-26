/* The kit: the screens a Quill is drawn with, on the phone and the full web
   app alike.

   A Quill never ships a screen. It names one of these — a board, a list, a
   detail — and says which of its fields go where, and everything below is
   drawn from that and from the datamodel alone. Nothing in this file knows
   what a task is. A board is a model with an enum for its lanes, a list is
   a model with a title, and every record, of every model, opens on the
   same sheet with the widget its kind has.

   So a change here is a change to every Quill at once. When a Quill cannot
   say something with what is here, the kit grows — here, and in the
   terminal's kit, together — rather than that Quill growing a screen.

   quills.js owns the addresses and hands each screen its place: `at` is
   {quill, screen, tab, base}, where base is the screen's own hash. */

import {
  SAVE_DELAY, api, app, back, esc, formatDate, heading, icons, nav, occupy, renderRoute,
  replace, seconds, setStatus, store, tabs, toast, vacate, wireShell,
} from "./core.js";
import { installCard } from "./install.js";
// Each element beyond the first four is a file of its own, drawn from here.
import { renderEditor, renderEditorPage } from "./kit_editor.js";

const own = {
  // What a board is, for the button that opens its own sheet.
  more: '<svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
};

// -- reading a datamodel -----------------------------------------------------------
const recordsUrl = (model, id) =>
  "/api/records/" + encodeURIComponent(model) + (id ? "/" + encodeURIComponent(id) : "");
const fieldOf = (model, name) => model.fields.find((f) => f.name === name);
const titleField = (at, model) => (model.id === at.screen.model && at.screen.title) || model.title;
const titleOf = (model, record, name = model.title) => String(record.fields[name] || "").trim() || "Untitled";
/** Where one record opens. */
export const sheetHash = (at, model, id) =>
  `#/r/${encodeURIComponent(at.quill.id)}/${encodeURIComponent(at.screen.id)}/${encodeURIComponent(model)}/${encodeURIComponent(id)}`;

// "Add a task", "Add an entry": the label is the model's, the article is ours.
const aOr = (label) => (/^[aeiou]/i.test(label) ? "an " : "a ") + label.toLowerCase();

/** The lanes of an enum field, as [value, label] pairs. */
const lanesOf = (f) => f.values.map((value, i) => [value, (f.labels && f.labels[i]) || value]);

/** A value as a line of text says it: an enum by its label, a date as a date. */
function spoken(f, value, links = {}) {
  if (value === null || value === undefined || value === "") return "";
  switch (f.kind) {
    case "enum": {
      const at = f.values.indexOf(value);
      return at === -1 ? String(value) : (f.labels && f.labels[at]) || String(value);
    }
    case "bool": return value ? f.label : "";
    case "date": {
      const day = new Date(value + "T00:00:00");
      return Number.isNaN(day.getTime()) ? String(value)
        : day.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
    }
    case "datetime": return seconds(value) ? formatDate(seconds(value), { long: true }) : String(value);
    case "link": return links[value] || "";
    case "json": return JSON.stringify(value);
    default: return String(value);
  }
}

// What a card can say about a record besides its title: how many of the
// body's `- [ ]` lines are ticked, and the first line that is not one.
function bodyMeta(body) {
  let preview = "";
  let done = 0;
  let total = 0;
  for (const line of String(body || "").split("\n")) {
    const box = /^\s*[-*]\s+\[([ xX])\]/.exec(line);
    if (box) {
      total += 1;
      if (box[1] !== " ") done += 1;
    } else if (!preview && line.trim()) {
      preview = line.trim().replace(/^#+\s*/, "");
    }
  }
  return { preview, done, total };
}

// A record an expire job will take says so, counted in days — the same
// promise the job keeps, told before it is kept rather than after.
function timeLeft(expiresAt) {
  const at = seconds(expiresAt);
  if (!at) return "";
  const days = Math.ceil((at * 1000 - Date.now()) / 86400000);
  if (days <= 0) return "Goes today";
  return `${days} day${days === 1 ? "" : "s"} left`;
}

// The circle on a card: empty in the first lane, full in the last, and a
// dot in any lane between — somewhere along the way.
const circle = (state) => `<span class="check ${state}">${state === "done" ? icons.tick : ""}</span>`;

// Whether a card is worth making draggable. A phone has the circle and the
// lane control and no way to drag anything, and `draggable` on a touch
// screen is only something for a long press to catch on.
const canDrag = () => matchMedia("(hover: hover) and (pointer: fine)").matches;

// The kit elements this file draws. The server refuses to install a screen
// of any other kind until every surface draws it, and a test holds this
// list to the server's; the check below is for a server newer than the page.
export const DRAWS = ["list", "board", "detail", "form", "editor"];

export async function renderKitScreen(at, arg) {
  const { kit } = at.screen;
  if (kit === "board") return renderBoard(at, arg);
  if (kit === "editor") return renderEditor(at, arg);
  if (DRAWS.includes(kit)) return renderList(at);
  app.innerHTML = nav({ title: at.screen.label }) + `<main>${heading(at.screen.label)}
    <p class="empty"><b>Not on this app yet</b>This screen is a ${esc(kit)}, which this
      version of the app cannot draw. Reload to fetch the newest.</p></main>` + tabs(at.tab);
  wireShell();
}

// -- the board ----------------------------------------------------------------------
async function renderBoard(at, arg) {
  const { quill, screen } = at;
  const model = quill.models[screen.model];
  const title = titleField(at, model);
  const laneField = fieldOf(model, screen.lane);
  const lanes = lanesOf(laneField);
  const first = lanes[0][0];
  const doneLane = screen.done || lanes[lanes.length - 1][0];
  const stateOf = (value) => (value === doneLane ? "done" : value === first ? "" : "part");

  // The groups, when the board has them: the chips across the top, each a
  // record of the model the group field links to.
  const groupField = screen.group ? fieldOf(model, screen.group) : null;
  const groupModel = groupField ? quill.models[groupField.to] : null;
  const remembered = "kit." + at.tab;
  let groups = [];
  let group = null;
  if (groupModel) {
    groups = await api("GET", recordsUrl(groupModel.id));
    // The one you asked for, else the one you had open, else the first.
    group = groups.find((g) => g.id === (arg || store.get(remembered))) || groups[0] || null;
    if (arg && (!group || group.id !== arg)) {
      toast(`That ${groupModel.label.toLowerCase()} is gone`);
      replace(group ? `${at.base}/${encodeURIComponent(group.id)}` : at.base);
    }
    store.set(remembered, group ? group.id : null);
  }
  const listUrl = () => recordsUrl(model.id) +
    (group ? `?${encodeURIComponent(groupField.name)}=${encodeURIComponent(group.id)}` : "");
  let records = groupModel && !group ? [] : await api("GET", listUrl());

  const name = group ? titleOf(groupModel, group) : screen.label;
  // The groups, and on the end of them the way to start another. The row
  // is there even with one group: that last chip is what it is for then.
  const chips = !groupModel ? "" : `<div class="chips">${groups.map((g) =>
    `<a class="chip${g === group ? " active" : ""}" href="${at.base}/${encodeURIComponent(g.id)}">${esc(titleOf(groupModel, g))}</a>`).join("")}` +
    `<button class="chip new-group" type="button">+ New ${esc(groupModel.label.toLowerCase())}</button></div>`;
  // The group's own sheet is where it is renamed and deleted: a board is a
  // record like any other, and gets the sheet every record gets.
  const actions = (group
    ? `<a class="button" href="${sheetHash(at, groupModel.id, group.id)}" aria-label="${esc(groupModel.label)} details">${own.more}</a>`
    : "") + `<button class="compose" aria-label="New ${esc(model.label.toLowerCase())}">${icons.compose}</button>`;
  const canAdd = !groupModel || group;
  app.innerHTML = nav({ title: name }) + `
    <main>
      ${heading(name, canAdd ? actions : "")}
      ${chips}
      ${canAdd ? `<form class="add">${circle("")}<input placeholder="Add ${esc(aOr(model.label))}" autocapitalize="sentences" enterkeyhint="done"></form>` : ""}
      <div class="install-slot">${installCard()}</div>
      <div class="listing"></div>
    </main>` + tabs(at.tab);
  wireShell();
  const listing = app.querySelector(".listing");

  const card = (r) => {
    const state = stateOf(r.fields[laneField.name]);
    let meta = "";
    const left = timeLeft(r.expires_at);
    if (left) meta += `<span class="date expires">${left}</span>`;
    if (screen.body) {
      const { preview, done, total } = bodyMeta(r.fields[screen.body]);
      if (total) meta += `<span class="date">${done} of ${total}</span>`;
      if (preview) meta += `<span class="preview">${esc(preview)}</span>`;
    }
    return `<div class="row card${state === "done" ? " is-done" : ""}" data-id="${esc(r.id)}"${canDrag() ? ` draggable="true"` : ""}>
      <button class="tick" data-id="${esc(r.id)}" aria-label="${state === "done" ? "Not done" : "Done"}">${circle(state)}</button>
      <a class="main" href="${sheetHash(at, model.id, r.id)}">
        <span class="title">${esc(titleOf(model, r, title))}</span>${meta ? `<span class="meta">${meta}</span>` : ""}</a></div>`;
  };
  const show = () => {
    if (groupModel && !group) {
      listing.innerHTML = `<p class="empty mascot"><b>No ${esc(groupModel.label.toLowerCase())} yet</b>Start one above, and it will show up here.</p>`;
      return;
    }
    if (!records.length) {
      listing.innerHTML = `<p class="empty mascot"><b>Nothing here yet</b>Add ${esc(aOr(model.label))} above, and it will show up here.</p>`;
      return;
    }
    // Each lane is wrapped, which the phone cannot tell — a plain block
    // around what was already there — and which a computer lays out as
    // columns. A lane with nothing in it is hidden rather than skipped,
    // because on a board of columns an empty one is still somewhere to
    // drop a card.
    listing.innerHTML = `<div class="board" style="--lanes: ${lanes.length}">` + lanes.map(([lane, label]) => {
      const rows = records.filter((r) => r.fields[laneField.name] === lane)
        .sort((a, b) => a.position - b.position);
      return `<div class="lane${rows.length ? "" : " lane-empty"}" data-lane="${esc(lane)}">` +
        `<p class="group-label">${esc(label)}</p>` +
        (rows.length
          ? `<div class="group">${rows.map(card).join("")}</div>`
          : `<div class="group nothing">Nothing here</div>`) +
        `</div>`;
    }).join("") + `</div>`;
    for (const button of listing.querySelectorAll(".tick")) {
      button.addEventListener("click", () => toggle(button.dataset.id));
    }
    wireDragging();
  };

  // The circle is the short way through the lanes: tap to finish, tap
  // again to take it back to the start.
  const toggle = async (id) => {
    const record = records.find((r) => r.id === id);
    if (!record) return;
    const to = record.fields[laneField.name] === doneLane ? first : doneLane;
    try {
      const moved = await api("POST", recordsUrl(model.id, id) + "/move", { fields: { [laneField.name]: to } });
      records = records.map((r) => (r.id === id ? moved : r));
      show();
    } catch (err) { toast(err.message); }
  };

  // -- dragging a card ------------------------------------------------------
  // What the mouse has instead of the circle and the lane control, and the
  // same move the TUI's own drag ends in. The whole board comes back after
  // it rather than the one card: moving a card renumbers the lane it left
  // and the lane it landed in.
  let dragged = null;

  // Where in the lane it would go: the number of the *other* cards whose
  // middle is above the pointer. The server takes the card out before it
  // puts it back, so the card being dragged is not one of them.
  const indexAt = (lane, y) => [...lane.querySelectorAll(".row.card")]
    .filter((row) => row.dataset.id !== dragged)
    .filter((row) => {
      const box = row.getBoundingClientRect();
      return box.top + box.height / 2 < y;
    }).length;

  const moveTo = async (id, lane, index) => {
    try {
      await api("POST", recordsUrl(model.id, id) + "/move", { fields: { [laneField.name]: lane }, index });
      records = await api("GET", listUrl());
      show();
    } catch (err) { toast(err.message); }
  };

  function wireDragging() {
    if (!canDrag()) return;
    for (const row of listing.querySelectorAll(".row.card")) {
      row.addEventListener("dragstart", (event) => {
        dragged = row.dataset.id;
        row.classList.add("dragging");
        event.dataTransfer.effectAllowed = "move";
        // Firefox starts no drag at all without something on the transfer.
        event.dataTransfer.setData("text/plain", row.dataset.id);
      });
      row.addEventListener("dragend", () => {
        dragged = null;
        row.classList.remove("dragging");
        for (const lane of listing.querySelectorAll(".over")) lane.classList.remove("over");
      });
    }
    for (const lane of listing.querySelectorAll(".lane")) {
      lane.addEventListener("dragover", (event) => {
        if (dragged === null) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        lane.classList.add("over");
      });
      lane.addEventListener("dragleave", (event) => {
        if (!lane.contains(event.relatedTarget)) lane.classList.remove("over");
      });
      lane.addEventListener("drop", (event) => {
        if (dragged === null) return;
        event.preventDefault();
        lane.classList.remove("over");
        moveTo(dragged, lane.dataset.lane, indexAt(lane, event.clientY));
      });
    }
  }

  show();

  // New records go in the first lane of the group on screen.
  wireAdd(async (text) => {
    const fields = { [title]: text, [laneField.name]: first };
    if (group) fields[groupField.name] = group.id;
    records.push(await api("POST", recordsUrl(model.id), { fields }));
    show();
  });
  const more = app.querySelector(".new-group");
  if (more) more.addEventListener("click", () => newGroup(at, groupModel));
}

// A group wants only a name, as a folder does in Notes. The new one opens
// as soon as it exists, with nothing in it yet.
async function newGroup(at, groupModel) {
  const text = (prompt(`${groupModel.label} name`) || "").trim();
  if (!text) return;
  try {
    const made = await api("POST", recordsUrl(groupModel.id), { fields: { [groupModel.title]: text } });
    replace(`${at.base}/${encodeURIComponent(made.id)}`);
    renderRoute();
  } catch (err) { toast(err.message); }
}

/** The add row under the title, and the pen beside it that leads there. */
function wireAdd(create) {
  const form = app.querySelector("form.add");
  if (!form) return;
  const input = form.querySelector("input");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    try {
      await create(text);
    } catch (err) {
      input.value = text;
      toast(err.message);
    }
  });
  const compose = app.querySelector(".heading .compose");
  if (compose) compose.addEventListener("click", () => input.focus());
}

// -- the list, and the detail -------------------------------------------------------
// A list is rows titled by one field, with a second under it and a circle
// for a bool if the screen names them. A detail is the same rows, saying
// the fields it names, and opening on a sheet that shows only those.
async function renderList(at) {
  const { quill, screen } = at;
  const model = quill.models[screen.model];
  const title = titleField(at, model);
  const tick = screen.kit === "list" && screen.tick ? fieldOf(model, screen.tick) : null;
  const under = screen.kit === "list"
    ? [screen.subtitle].filter(Boolean)
    : (screen.fields || []).filter((n) => n !== title).slice(0, 2);
  const underFields = under.map((n) => fieldOf(model, n)).filter(Boolean);
  let records = await api("GET", recordsUrl(model.id));
  const links = await linkTitles(quill, underFields);

  app.innerHTML = nav({ title: screen.label }) + `
    <main>
      ${heading(screen.label, `<button class="compose" aria-label="New ${esc(model.label.toLowerCase())}">${icons.compose}</button>`)}
      <form class="add">${tick ? circle("") : ""}<input placeholder="Add ${esc(aOr(model.label))}" autocapitalize="sentences" enterkeyhint="done"></form>
      <div class="install-slot">${installCard()}</div>
      <div class="listing"></div>
    </main>` + tabs(at.tab);
  wireShell();
  const listing = app.querySelector(".listing");

  const row = (r) => {
    const said = underFields.map((f) => spoken(f, r.fields[f.name], links[f.name])).filter(Boolean);
    const left = timeLeft(r.expires_at);
    const meta = (left ? `<span class="date expires">${left}</span>` : "") +
      (said.length ? `<span class="preview">${esc(said.join(" · "))}</span>` : "");
    const text = `<span class="title">${esc(titleOf(model, r, title))}</span>${meta ? `<span class="meta">${meta}</span>` : ""}`;
    if (!tick) {
      return `<a class="row" href="${sheetHash(at, model.id, r.id)}"><span class="main">${text}</span>${icons.chevronRight}</a>`;
    }
    const on = !!r.fields[tick.name];
    return `<div class="row card${on ? " is-done" : ""}">
      <button class="tick" data-id="${esc(r.id)}" aria-label="${esc(tick.label)}" aria-pressed="${on}">${circle(on ? "done" : "")}</button>
      <a class="main" href="${sheetHash(at, model.id, r.id)}">${text}</a></div>`;
  };
  const show = () => {
    listing.innerHTML = records.length
      ? `<div class="group kit-list">${records.map(row).join("")}</div>`
      : `<p class="empty mascot"><b>Nothing here yet</b>Add ${esc(aOr(model.label))} above, and it will show up here.</p>`;
    for (const button of listing.querySelectorAll(".tick")) {
      button.addEventListener("click", () => flip(button.dataset.id));
    }
  };
  const flip = async (id) => {
    const record = records.find((r) => r.id === id);
    if (!record) return;
    try {
      const changed = await api("PATCH", recordsUrl(model.id, id),
        { fields: { [tick.name]: !record.fields[tick.name] }, rev: record.rev });
      records = records.map((r) => (r.id === id ? changed : r));
    } catch (err) {
      toast(err.status === 409 ? "That changed somewhere else" : err.message);
      records = await api("GET", recordsUrl(model.id));
    }
    show();
  };
  show();
  wireAdd(async (text) => {
    records.push(await api("POST", recordsUrl(model.id), { fields: { [title]: text } }));
    show();
  });
}

/** For each link field: the linked records' titles, by id. */
async function linkTitles(quill, fields) {
  const out = {};
  for (const f of fields) {
    if (f.kind !== "link" || !quill.models[f.to]) continue;
    const target = quill.models[f.to];
    const rows = await api("GET", recordsUrl(target.id));
    out[f.name] = Object.fromEntries(rows.map((r) => [r.id, titleOf(target, r)]));
  }
  return out;
}

// -- the record sheet ------------------------------------------------------------------
// Every record opens here: the title large and first, as a note's is, and
// then each field with the widget its kind has. It saves as you go, as the
// editors do, and a record changed somewhere else since it was opened is
// shown afresh rather than written over.
let editor = null;

// The widget for each field kind. Every kind a datamodel may use is here —
// a test holds the list to the server's — because a kind with no widget is
// a field somebody's Quill cannot show. The plain ones are an <input> of
// the type named; the rest are drawn below by name.
export const WIDGET = {
  string: "text",
  text: "textarea",
  markdown: "textarea",
  bool: "switch",
  int: "number",
  decimal: "number",
  date: "date",
  datetime: "datetime-local",
  enum: "segments",
  email: "email",
  phone: "tel",
  url: "url",
  link: "select",
  json: "textarea",
};
const LONG = new Set(Object.keys(WIDGET).filter((kind) => WIDGET[kind] === "textarea"));

// An ISO moment as a datetime-local box shows it, in the reader's own time.
function localMoment(iso) {
  const ms = Date.parse(iso || "");
  if (Number.isNaN(ms)) return "";
  const d = new Date(ms);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function widget(f, value, links) {
  const data = `data-field="${esc(f.name)}"`;
  const label = `aria-label="${esc(f.label)}"`;
  if (f.stamp) return `<span class="value" ${data} data-readonly>${esc(spoken(f, value) || "—")}</span>`;
  switch (WIDGET[f.kind]) {
    case "switch":
      return `<input type="checkbox" class="switch" ${data} ${label}${value ? " checked" : ""}>`;
    case "select": {
      const options = Object.entries(links[f.name] || {});
      return `<select ${data} ${label}>${f.required ? "" : `<option value="">None</option>`}` +
        options.map(([id, text]) => `<option value="${esc(id)}"${id === value ? " selected" : ""}>${esc(text)}</option>`).join("") +
        `</select>`;
    }
    case "datetime-local":
      return `<input type="datetime-local" ${data} ${label} value="${esc(localMoment(value))}">`;
    default: {
      const step = f.kind === "decimal" ? ' step="any"' : "";
      return `<input type="${WIDGET[f.kind] || "text"}"${step} ${data} ${label} value="${esc(value ?? "")}"` +
        ` placeholder="${f.required ? "" : "optional"}">`;
    }
  }
}

// An enum is a row of buttons, one lit: the lane control a task always had.
const segments = (f, value) =>
  `<div class="segments" role="radiogroup" aria-label="${esc(f.label)}" data-field="${esc(f.name)}">` +
  lanesOf(f).map(([v, text]) => `<button type="button" role="radio" data-value="${esc(v)}"` +
    `${v === value ? ' class="active" aria-checked="true"' : ' aria-checked="false"'}>${esc(text)}</button>`).join("") +
  `</div>`;

/** What a widget holds now, as the record would store it. */
function read(f, el) {
  switch (f.kind) {
    case "bool": return el.checked;
    case "enum": {
      const on = el.querySelector("button.active");
      return on ? on.dataset.value : null;
    }
    case "int": return el.value === "" ? null : Math.trunc(Number(el.value));
    case "decimal": return el.value === "" ? null : el.value;
    case "datetime": return el.value ? new Date(el.value).toISOString() : null;
    case "json": {
      if (!el.value.trim()) return null;
      return JSON.parse(el.value);   // a SyntaxError is the caller's to show
    }
    case "string": case "text": case "markdown": return el.value;
    default: return el.value === "" ? null : el.value;
  }
}

// Whether two values are the same, as the server would store them: it
// writes decimals back as it likes and datetimes to the second.
function same(f, a, b) {
  if (a === b) return true;
  if ((a ?? "") === "" && (b ?? "") === "") return true;
  if (f.kind === "decimal") return a != null && b != null && Number(a) === Number(b);
  if (f.kind === "datetime") return Math.floor(Date.parse(a) / 60000) === Math.floor(Date.parse(b) / 60000);
  return JSON.stringify(a) === JSON.stringify(b);
}

export async function renderRecordSheet(at, modelId, id, arg) {
  const { quill, screen } = at;
  // An editor's own records open on its page, not on the sheet.
  if (screen.kit === "editor" && modelId === screen.model) return renderEditorPage(at, id, arg);
  const model = quill.models[modelId];
  let record;
  try { record = await api("GET", recordsUrl(model.id, id)); }
  catch (err) {
    if (err.status !== 404) throw err;
    toast(`That ${model.label.toLowerCase()} is gone`);
    replace(at.base);
    return renderRoute();
  }
  const onScreen = model.id === screen.model;
  const title = titleField(at, model);
  const wanted = onScreen && screen.fields && screen.fields.length ? new Set([title, ...screen.fields]) : null;
  const fields = model.fields.filter((f) => f.name !== title && (!wanted || wanted.has(f.name)));
  const links = await linkTitles(quill, fields.filter((f) => f.kind === "link"));

  // Back to where it came from: a card to its board, a board to itself.
  const groupField = onScreen && screen.group ? fieldOf(model, screen.group) : null;
  let parent = at.base;
  let backLabel = screen.label;
  if (groupField && record.fields[groupField.name]) {
    parent = `${at.base}/${encodeURIComponent(record.fields[groupField.name])}`;
    backLabel = (links[groupField.name] || {})[record.fields[groupField.name]] || backLabel;
  } else if (!onScreen) {
    parent = `${at.base}/${encodeURIComponent(record.id)}`;
    backLabel = titleOf(model, record);
  }

  const ed = { model, id, record, title, fields, dirty: false, saving: false, pending: false, timer: null };
  editor = ed;
  const hold = {
    stays: (name, a) => name === "r" && a === arg,
    leave: () => leaveSheet(ed),
    flush: () => { if (ed.dirty) { clearTimeout(ed.timer); saveSheet(ed, { keepalive: true }); } },
  };
  ed.hold = hold;
  occupy(hold);

  const enums = fields.filter((f) => f.kind === "enum" && !f.stamp);
  const long = fields.filter((f) => LONG.has(f.kind) && !f.stamp);
  const short = fields.filter((f) => !enums.includes(f) && !long.includes(f));
  // One long text is the body, as a task's notes were: no label, the rest
  // of the page to grow into. The board's own body if it names one, else
  // the first Markdown, else the first text; any other gets a heading.
  const body = long.find((f) => onScreen && f.name === screen.body)
    || long.find((f) => f.kind === "markdown") || long.find((f) => f.kind === "text");
  const more = long.filter((f) => f !== body);
  const hint = body && onScreen && body.name === screen.body && screen.kit === "board"
    ? ", and subtasks as “- [ ]” lines…" : "…";
  const left = timeLeft(record.expires_at);
  app.innerHTML = nav({
    back: parent, backLabel, title: titleOf(model, record, title),
    right: `<button class="done strong" hidden>Done</button><button class="delete" aria-label="Delete ${esc(model.label.toLowerCase())}">${icons.trash}</button>`,
  }) + `
    <main>
      <div class="editor record">
        <input class="title" data-field="${esc(title)}" placeholder="${esc(fieldOf(model, title).label)}" value="${esc(record.fields[title] ?? "")}" autocapitalize="sentences" enterkeyhint="next">
        <p class="stamp"><span class="when">${esc(formatDate(seconds(record.updated_at) || Date.now() / 1000, { long: true }))}</span>${
          left ? `<span class="expires"> · ${esc(left)}</span>` : ""}<span class="status"></span></p>
        ${enums.map((f) => (enums.length > 1 ? `<p class="group-label">${esc(f.label)}</p>` : "") + segments(f, record.fields[f.name])).join("")}
        ${short.length ? `<div class="group fields">${short.map((f) =>
          `<label class="row field kind-${esc(f.kind)}"><span class="main">${esc(f.label)}</span>${widget(f, record.fields[f.name], links)}</label>`).join("")}</div>` : ""}
        ${more.map((f) => `<p class="group-label">${esc(f.label)}</p>` +
          `<textarea class="long" data-field="${esc(f.name)}" rows="3" aria-label="${esc(f.label)}">${esc(f.kind === "json" && record.fields[f.name] != null ? JSON.stringify(record.fields[f.name], null, 2) : record.fields[f.name] ?? "")}</textarea>`).join("")}
        ${body ? `<textarea class="body" data-field="${esc(body.name)}" aria-label="${esc(body.label)}" placeholder="${esc(body.label + hint)}" rows="1">${esc(
          body.kind === "json" && record.fields[body.name] != null ? JSON.stringify(record.fields[body.name], null, 2) : record.fields[body.name] ?? "")}</textarea>` : ""}
      </div>
    </main>`;
  wireShell();
  app.querySelector(".nav").classList.add("lined");

  const box = app.querySelector(".editor");
  const titleEl = app.querySelector(".editor .title");
  const bodyEl = app.querySelector(".editor .body");
  const done = app.querySelector(".nav .done");
  const del = app.querySelector(".nav .delete");
  ed.statusEl = app.querySelector(".stamp .status");
  ed.box = box;

  const areas = [...box.querySelectorAll("textarea")];
  const grow = ed.grow = () => {
    for (const area of areas) { area.style.height = "auto"; area.style.height = area.scrollHeight + "px"; }
  };
  grow();
  addEventListener("resize", grow);

  // Typing waits for a pause; a choice — a lane, a tick, a date — is a
  // decision already made, and is saved the moment it is.
  const changed = (now = false) => {
    ed.dirty = true;
    setStatus(ed, "");
    clearTimeout(ed.timer);
    if (now) saveSheet(ed);
    else ed.timer = setTimeout(() => saveSheet(ed), SAVE_DELAY);
  };
  for (const el of box.querySelectorAll("input[data-field], textarea[data-field], select[data-field]")) {
    const typed = el.tagName === "TEXTAREA" || ["text", "email", "tel", "url", "number"].includes(el.type);
    if (typed) el.addEventListener("input", () => { if (el.tagName === "TEXTAREA") grow(); changed(); });
    else el.addEventListener("change", () => changed(true));
  }
  for (const group of box.querySelectorAll(".segments")) {
    for (const button of group.querySelectorAll("button")) {
      button.addEventListener("click", () => {
        if (button.classList.contains("active")) return;
        for (const other of group.querySelectorAll("button")) {
          const on = other === button;
          other.classList.toggle("active", on);
          other.setAttribute("aria-checked", String(on));
        }
        changed(true);
      });
    }
  }
  titleEl.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    if (bodyEl) { bodyEl.focus(); bodyEl.setSelectionRange(0, 0); } else titleEl.blur();
  });
  box.addEventListener("click", (event) => {
    if (event.target === box && bodyEl) { bodyEl.focus(); bodyEl.setSelectionRange(bodyEl.value.length, bodyEl.value.length); }
  });
  // While something is being typed, the bar's corner is the way to stop.
  const typing = (el) => el && (el.tagName === "TEXTAREA" || el === titleEl ||
    (el.tagName === "INPUT" && ["text", "email", "tel", "url", "number"].includes(el.type)));
  box.addEventListener("focusin", (event) => {
    if (typing(event.target)) { done.hidden = false; del.hidden = true; }
  });
  box.addEventListener("focusout", () => {
    setTimeout(() => {
      if (!typing(document.activeElement)) { done.hidden = true; del.hidden = false; }
    }, 0);
    if (ed.dirty) { clearTimeout(ed.timer); saveSheet(ed); }
  });
  done.addEventListener("click", () => document.activeElement && document.activeElement.blur());

  del.addEventListener("click", async () => {
    // What goes with it, said before rather than found out after.
    const along = Object.values(quill.models).filter((m) => m.fields.some((f) =>
      f.kind === "link" && f.to === model.id && f.on_delete === "cascade"));
    const warning = along.length
      ? `\n\nEvery ${along.map((m) => m.label.toLowerCase()).join(" and ")} on it goes with it.` : "";
    if (!confirm(`Delete “${titleOf(model, ed.record, title)}”?${warning}`)) return;
    try {
      clearTimeout(ed.timer);
      ed.dirty = false;
      await api("DELETE", recordsUrl(model.id, id));
      vacate(hold);
      if (editor === ed) editor = null;
      if (onScreen) back(parent);
      else { replace(at.base); renderRoute(); }
    } catch (err) { toast(err.message); }
  });
}

/** The fields whose widgets say something other than the record does. */
function changes(ed) {
  const out = {};
  for (const f of [fieldOf(ed.model, ed.title), ...ed.fields]) {
    if (!f || f.stamp) continue;
    const el = ed.box.querySelector(`[data-field="${CSS.escape(f.name)}"]`);
    if (!el) continue;
    let value = read(f, el);
    // A record with no title keeps the one it had.
    if (f.name === ed.title && !String(value || "").trim()) continue;
    if (f.kind === "string" && typeof value === "string") value = value.trim();
    if (!same(f, value, ed.record.fields[f.name])) out[f.name] = value;
  }
  return out;
}

async function saveSheet(ed, { keepalive = false } = {}) {
  if (!ed.dirty) return;
  if (ed.saving) { ed.pending = true; return; }
  ed.dirty = false;
  let fields;
  try { fields = changes(ed); }
  catch {
    setStatus(ed, "Not saved: that is not JSON", true);
    return;
  }
  if (!Object.keys(fields).length) { setStatus(ed, "Saved"); return; }
  ed.saving = true;
  setStatus(ed, "Saving…");
  try {
    ed.record = await api("PATCH", recordsUrl(ed.model.id, ed.id), { fields, rev: ed.record.rev }, { keepalive });
    if (editor === ed) {
      const center = app.querySelector(".nav .center .text");
      if (center) center.textContent = titleOf(ed.model, ed.record, ed.title);
      // What the server sets itself — the moment a task was finished — has
      // moved with what was just saved.
      for (const el of ed.box.querySelectorAll("[data-readonly]")) {
        const f = fieldOf(ed.model, el.dataset.field);
        el.textContent = spoken(f, ed.record.fields[f.name]) || "—";
      }
    }
    setStatus(ed, "Saved");
  } catch (err) {
    if (err.status === 409 && editor === ed) {
      // Somebody — another window, the terminal — got there first. Their
      // version is shown; what was typed here since the last save is not
      // kept, because two versions of one field is not something a sheet
      // can put in front of you honestly.
      toast("This changed somewhere else, so here it is as it is now");
      ed.dirty = false;
      ed.saving = false;
      ed.pending = false;
      vacate(ed.hold);
      editor = null;
      removeEventListener("resize", ed.grow);
      renderRoute();
      return;
    }
    ed.dirty = true;
    setStatus(ed, "Not saved", true);
    if (err.status !== 401) toast(err.message);
  } finally {
    ed.saving = false;
    if (ed.pending) { ed.pending = false; ed.dirty = true; saveSheet(ed); }
  }
}

async function leaveSheet(ed) {
  if (editor === ed) editor = null;
  clearTimeout(ed.timer);
  removeEventListener("resize", ed.grow);
  if (ed.dirty) await saveSheet(ed);
  while (ed.saving) await new Promise((r) => setTimeout(r, 50));
}
