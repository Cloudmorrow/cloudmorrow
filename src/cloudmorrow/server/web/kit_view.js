/* The kit's `view`: a screen a Quill's own code draws, as a tree of primitives.

   A screen with `kit = "view"` names a handler in the Quill's Python
   (docs/QUILLCODE.md). The server runs it as whoever is looking and sends
   back a tree — stack, table, button and the rest, every one of them in
   `cloudmorrow.quill.ui` — and this file draws that tree, the same one the
   terminal draws its own way. Nothing here knows what any Quill is; a
   primitive this page cannot draw says so rather than drawing a gap.

   The address carries the view's parameters in one segment after the
   screen, as a query string: #/q/<quill>/<screen>/<a%3D1%26b%3D2>. `go`
   effects and buttons land there (actions.js builds it).

   What can be pressed goes through actions.js: a button runs an action (its
   form first, when it has fields), opens a record on the sheet every record
   has, or goes to another screen of the Quill. After an action the tree is
   asked for again and drawn in place; and, like every kit screen, it is
   drawn afresh when the app comes back to the front. A `field` with
   `edit` saves as the sheet does, with the revision it came with; a card
   dragged to another lane moves at once, and the server agrees or it goes
   back when the view is drawn again. */

import { api, app, authHeaders, esc, go, heading, nav, tabs, toast, wireShell } from "./core.js";
import { fieldOf, mayWrite, read, recordsUrl, segments, sheetHash, spoken, titleOf, widget } from "./kit.js";
import { addDays, addMonths, dateOf, longDay, monthOf, today, weeksOf } from "./kit_calendar.js";
import {
  ask, choose, findAction, formFields, hideFromBar, linksFor, onRedrawHere, press, readFields, run,
  said, screenAt, wireFields,
} from "./actions.js";

const glyphs = {
  left: '<svg width="11" height="18" viewBox="0 0 11 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M8.5 1.5 2 9l6.5 7.5"/></svg>',
  right: '<svg width="11" height="18" viewBox="0 0 11 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 1.5 9 9l-6.5 7.5"/></svg>',
  more: '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
  down: '<svg width="10" height="7" viewBox="0 0 10 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m1 1.5 4 4 4-4"/></svg>',
};

// The same test the board uses: a phone has no way to drag anything.
const canDrag = () => matchMedia("(hover: hover) and (pointer: fine)").matches;
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export async function renderView(at, arg) {
  const params = Object.fromEntries(new URLSearchParams(arg || ""));
  app.innerHTML = nav({ title: at.screen.label }) + `
    <main class="view-screen">
      ${heading(at.screen.label)}
      <div class="quill-view" aria-busy="true"></div>
    </main>` + tabs(at.tab);
  wireShell();
  const root = app.querySelector(".quill-view");
  // Everything one drawing of the view needs, and what it keeps between
  // drawings: which tab is open, which month is shown, each record's rev.
  const v = {
    at, params, root, tree: null,
    open: new Map(), months: new Map(), revs: new Map(), thumbs: new Map(),
    links: {}, formLinks: {}, handlers: [], edits: [], forms: [], lanes: [], amber: false,
  };
  v.draw = () => draw(v);
  v.paint = () => paint(v);
  onRedrawHere({ alive: () => root.isConnected, draw: v.draw });
  // One listener for everything pressed in the view: each drawing hands
  // out numbers, and the element pressed carries its own.
  root.addEventListener("click", (event) => {
    const el = event.target.closest("[data-do]");
    if (!el || !root.contains(el)) return;
    const handler = v.handlers[Number(el.dataset.do)];
    if (!handler) return;
    event.preventDefault();
    event.stopPropagation();
    handler(el, event);
  });
  await draw(v);
}

/** Ask for the tree, and draw it; or say why it could not be. */
async function draw(v) {
  const { quill, screen } = v.at;
  const query = new URLSearchParams(v.params).toString();
  let answer;
  try {
    answer = await api("GET", `/api/quills/${encodeURIComponent(quill.id)}/views/${encodeURIComponent(screen.id)}` +
      (query ? "?" + query : ""));
  } catch (err) {
    if (err.status === 401 || !v.root.isConnected) return;
    v.root.removeAttribute("aria-busy");
    v.root.innerHTML = `<div class="empty v-failed"><b>This screen could not be drawn</b>` +
      `<span>${esc(said(err))}</span>` +
      `<button type="button" class="act-button" data-retry>Try again</button></div>`;
    v.root.querySelector("[data-retry]").addEventListener("click", () => draw(v));
    hideFromBar(new Set());
    return;
  }
  if (!v.root.isConnected) return;
  v.tree = trimmed(v, answer.tree);
  await fetchLinks(v, v.tree);
  if (v.root.isConnected) paint(v);
}

// The heading is already the screen's label; a view that starts by saying
// it again as a title is not made to say it twice.
function trimmed(v, tree) {
  const same = (n) => n && n.ui === "text" && n.style === "title" &&
    n.text.trim().toLowerCase() === String(v.at.screen.label).trim().toLowerCase();
  if (same(tree)) return { ui: "stack", children: [] };
  if (tree && tree.ui === "stack" && same(tree.children[0])) return { ...tree, children: tree.children.slice(1) };
  return tree;
}

/** Draw the tree as it was last sent: after a fetch, and when a tab or a month changes. */
function paint(v) {
  v.handlers = [];
  v.edits = [];
  v.forms = [];
  v.lanes = [];
  v.amber = false;
  v.root.removeAttribute("aria-busy");
  v.root.innerHTML = node(v, v.tree, "0");
  wireEdits(v);
  wireForms(v);
  wireLanes(v);
  loadThumbs(v);
  // What the view has its own button for is not in the bar as well.
  hideFromBar(pressedIn(v.tree));
}

/** A handler for an element, as the attribute the element carries. */
const doing = (v, fn) => {
  v.handlers.push(fn);
  return `data-do="${v.handlers.length - 1}"`;
};

// -- reading records ------------------------------------------------------------------------
const modelOf = (v, record) => v.at.quill.models[record.model];
const fieldFor = (v, modelId, name) => {
  const model = v.at.quill.models[modelId];
  return model ? fieldOf(model, name) : null;
};
const labelOf = (v, modelId, name) => {
  const f = fieldFor(v, modelId, name);
  return f ? f.label : name;
};
/** A field of a record, said the way the sheet says it: an enum by its label, a link by its title. */
function say(v, record, name) {
  const value = record.fields[name];
  const f = fieldFor(v, record.model, name);
  if (!f) return value === null || value === undefined ? "" : typeof value === "object" ? JSON.stringify(value) : String(value);
  if (f.kind === "bool") return value ? "Yes" : "No";
  return spoken(f, value, v.links[`${record.model}.${name}`] || {});
}
const titled = (v, record, name) => {
  const model = modelOf(v, record);
  const text = name ? say(v, record, name) : model ? titleOf(model, record) : "";
  return String(text || "").trim() || "Untitled";
};
/** A record opens on its sheet, if its datamodel is one this Quill shows you. */
const sheetOf = (v, record) => (record && modelOf(v, record) ? sheetHash(v.at, record.model, record.id) : "");

// Every link field the tree says, so its titles are fetched once, before
// anything is drawn, rather than a request per row.
function* walk(n) {
  if (!n || typeof n !== "object") return;
  yield n;
  for (const child of n.children || n.items || []) yield* walk(child);
  for (const tab of n.tabs || []) yield* walk(tab.child);
}

async function fetchLinks(v, tree) {
  const wanted = new Map();   // "model.field" → field
  const want = (modelId, name) => {
    const f = name && fieldFor(v, modelId, name);
    if (f && f.kind === "link" && f.to && v.at.quill.models[f.to]) wanted.set(`${modelId}.${name}`, f);
  };
  const forms = new Set();
  for (const n of walk(tree)) {
    const models = new Set((n.records || []).map((r) => r.model));
    if (n.record) models.add(n.record.model);
    for (const modelId of models) {
      for (const c of n.columns || []) want(modelId, c.field);
      for (const key of ["title", "subtitle", "body", "badge", "name"]) {
        if (typeof n[key] === "string") want(modelId, n[key]);
      }
    }
    if (n.ui === "form") forms.add(n.action);
  }
  const byTarget = new Map();
  const titles = async (to) => {
    if (!byTarget.has(to)) {
      const target = v.at.quill.models[to];
      byTarget.set(to, api("GET", recordsUrl(to)).then(
        (rows) => Object.fromEntries(rows.map((r) => [r.id, titleOf(target, r)])), () => ({})));
    }
    return byTarget.get(to);
  };
  const links = {};
  for (const [key, f] of wanted) links[key] = await titles(f.to);
  v.links = links;
  for (const id of forms) {
    const action = findAction(v.at.quill.id, id);
    if (action && !v.formLinks[id]) v.formLinks[id] = await linksFor(v.at.quill, action.fields);
  }
}

/** The actions the view has a button, a form or an empty state's button for. */
function pressedIn(tree) {
  const ids = new Set();
  for (const n of walk(tree)) if (n.action) ids.add(n.action);
  return ids;
}

// -- drawing ---------------------------------------------------------------------------------
// One function per primitive in cloudmorrow.quill.ui.PRIMITIVES; a test
// holds the two lists together.
const DRAW = {
  stack: (v, n, p) =>
    `<div class="v-stack gap-${esc(["none", "small", "normal", "large"].includes(n.gap) ? n.gap : "normal")}">${children(v, n.children, p)}</div>`,
  row: (v, n, p) => `<div class="v-row${n.wrap === false ? " nowrap" : ""}">${children(v, n.children, p)}</div>`,
  columns: (v, n, p) =>
    `<div class="v-columns" style="--n: ${Math.max(1, Math.min(n.children.length, 4))}">` +
    n.children.map((c, i) => `<div class="v-column">${node(v, c, `${p}.${i}`)}</div>`).join("") + `</div>`,
  tabs: drawTabs,
  text: (v, n) => {
    const style = n.style || "body";
    if (style === "title") return `<h2 class="v-title">${esc(n.text)}</h2>`;
    if (style === "subtitle") return `<h3 class="v-subtitle">${esc(n.text)}</h3>`;
    if (style === "mono") return `<pre class="v-text mono">${esc(n.text)}</pre>`;
    return `<p class="v-text ${esc(style)}">${esc(n.text)}</p>`;
  },
  markdown: (v, n) => `<div class="v-markdown">${markdown(n.text)}</div>`,
  image: (v, n) => (n.src
    ? `<img class="v-image" src="${esc(n.src)}" alt="${esc(n.alt || "")}" loading="lazy" referrerpolicy="no-referrer">`
    : `<div class="v-image v-thumb" role="img" aria-label="${esc(n.alt || "")}" data-thumb-model="${esc(n.model || "")}" data-thumb-id="${esc(n.id || "")}"></div>`),
  badge: (v, n) => `<span class="v-badge tone-${esc(n.tone || "neutral")}">${esc(n.text)}</span>`,
  stat: (v, n) => `<div class="v-stat tone-${esc(n.tone || "neutral")}">` +
    `<span class="v-stat-label">${esc(n.label)}</span><span class="v-stat-value">${esc(n.value)}</span>` +
    (n.hint ? `<span class="v-stat-hint">${esc(n.hint)}</span>` : "") + `</div>`,
  empty: (v, n) => {
    const action = n.action && findAction(v.at.quill.id, n.action);
    return `<div class="v-empty"><p>${esc(n.text)}</p>` +
      (action ? drawButton(v, { ui: "button", label: n.label || action.label, action: n.action, tone: action.tone || "primary" }) : "") +
      `</div>`;
  },
  divider: () => `<hr class="v-divider">`,
  field: (v, n) => `<div class="group fields record v-fields">${fieldRow(v, n)}</div>`,
  form: drawForm,
  button: (v, n) => drawButton(v, n),
  menu: (v, n) => {
    const items = n.items.map((item) => pressable(v, item)).filter(Boolean);
    if (!items.length) return "";
    return `<button type="button" class="act-button v-menu" aria-haspopup="menu" ${doing(v, () => choose(n.label, items))}>` +
      `${esc(n.label)}${glyphs.down}</button>`;
  },
  table: drawTable,
  cards: drawCards,
  lanes: drawLanes,
  month: drawMonth,
};

function node(v, n, p) {
  const draw = n && DRAW[n.ui];
  if (!draw) {
    return `<p class="v-text muted v-unknown">This screen has a ${esc(n && n.ui || "thing")} in it, which this` +
      ` version of the app cannot draw. Reload to fetch the newest.</p>`;
  }
  return draw(v, n, p);
}

// Fields one after another are one box of rows, as on the sheet, rather
// than a box each.
function children(v, list, p) {
  let out = "";
  let run = [];
  const flush = () => {
    if (run.length) out += `<div class="group fields record v-fields">${run.join("")}</div>`;
    run = [];
  };
  list.forEach((child, i) => {
    if (child && child.ui === "field") { run.push(fieldRow(v, child)); return; }
    flush();
    out += node(v, child, `${p}.${i}`);
  });
  flush();
  return out;
}

function drawTabs(v, n, p) {
  if (!n.tabs.length) return "";
  const chosen = Math.min(v.open.get(p) || 0, n.tabs.length - 1);
  return `<div class="v-tabs"><div class="segments v-tab-strip" role="tablist">` +
    n.tabs.map((tab, i) => `<button type="button" role="tab" aria-selected="${i === chosen}"` +
      `${i === chosen ? ' class="active"' : ""} ${doing(v, () => { v.open.set(p, i); v.paint(); })}>${esc(tab.label)}</button>`).join("") +
    `</div><div class="v-tab-panel" role="tabpanel">${node(v, n.tabs[chosen].child, `${p}.t${chosen}`)}</div></div>`;
}

// -- pressing --------------------------------------------------------------------------------
// Amber fills one action per view (the brand guide): the first primary
// button in the tree is it, and any other primary is the blue fill.
function toneClass(v, tone) {
  if (tone === "primary") {
    if (v.amber) return "fill";
    v.amber = true;
    return "primary";
  }
  return tone === "danger" || tone === "bad" ? "danger" : "";
}

/** What pressing a button does, for a button or a menu's row; null when it cannot. */
function pressable(v, n) {
  const { quill } = v.at;
  if (n.action) {
    const action = findAction(quill.id, n.action);
    if (!action) return null;   // one the circles left out, or a server behind the page
    return {
      label: n.label, tone: n.tone,
      run: () => press(quill, action, { record: n.record ? n.record.id : "", args: n.args || {}, here: v.at, after: v.draw }),
    };
  }
  if (n.open) {
    const hash = sheetOf(v, n.open);
    return hash ? { label: n.label, tone: n.tone, href: hash, run: () => go(hash) } : null;
  }
  if (n.go) {
    const hash = screenAt(quill.id, n.go, n.params);
    return { label: n.label, tone: n.tone, href: hash, run: () => (hash === location.hash ? v.draw() : go(hash)) };
  }
  return null;
}

function drawButton(v, n) {
  const does = pressable(v, n);
  if (!does) return "";
  const cls = `act-button ${toneClass(v, n.tone)}`.trim();
  if (does.href && does.href !== location.hash) return `<a class="${cls}" href="${esc(does.href)}">${esc(n.label)}</a>`;
  return `<button type="button" class="${cls}" ${doing(v, does.run)}>${esc(n.label)}</button>`;
}

// -- a field -----------------------------------------------------------------------------------
// Read, it is said as the sheet says it; with `edit`, it is the sheet's
// widget, saved the moment it changes — for somebody who may write it.
function fieldRow(v, n) {
  const record = n.record;
  const model = modelOf(v, record);
  const f = model && fieldOf(model, n.name);
  const label = n.label || (f ? f.label : n.name);
  const said = say(v, record, n.name);
  const edits = n.edit && f && mayWrite(model) && !f.stamp;
  if (!edits) {
    return `<div class="row field${f ? " kind-" + esc(f.kind) : ""}"><span class="main">${esc(label)}</span>` +
      `<span class="value">${esc(said || "—")}</span></div>`;
  }
  v.edits.push({ record, f });
  const at = `data-edit="${v.edits.length - 1}"`;
  const value = record.fields[f.name];
  if (f.kind === "enum") {
    return `<div class="row field v-enum" ${at}><span class="main">${esc(label)}</span>${segments(f, value)}</div>`;
  }
  if (["text", "markdown", "json"].includes(f.kind)) {
    const text = f.kind === "json" && value != null ? JSON.stringify(value, null, 2) : value ?? "";
    return `<label class="row field v-long" ${at}><span class="main">${esc(label)}</span>` +
      `<textarea class="long" data-field="${esc(f.name)}" rows="3" aria-label="${esc(label)}">${esc(text)}</textarea></label>`;
  }
  const links = { [f.name]: v.links[`${record.model}.${f.name}`] || {} };
  return `<label class="row field kind-${esc(f.kind)}" ${at}><span class="main">${esc(label)}</span>${widget(f, value, links)}</label>`;
}

function wireEdits(v) {
  for (const row of v.root.querySelectorAll("[data-edit]")) {
    const { record, f } = v.edits[Number(row.dataset.edit)];
    const save = () => saveField(v, record, f, row);
    const segs = row.querySelector(".segments");
    if (segs) {
      segs.addEventListener("click", (event) => {
        const button = event.target.closest("button");
        if (!button || button.classList.contains("active")) return;
        for (const other of segs.querySelectorAll("button")) {
          other.classList.toggle("active", other === button);
          other.setAttribute("aria-checked", String(other === button));
        }
        save();
      });
    } else {
      row.querySelector("[data-field]").addEventListener("change", save);
    }
  }
}

async function saveField(v, record, f, row) {
  const key = `${record.model}/${record.id}`;
  let value;
  try { value = read(f, row.querySelector("[data-field]")); }
  catch { toast(`${f.label} is not JSON`); return; }
  if (f.kind === "string" && !f.secret && typeof value === "string") value = value.trim();
  try {
    const saved = await api("PATCH", recordsUrl(record.model, record.id),
      { fields: { [f.name]: value }, rev: v.revs.get(key) ?? record.rev });
    v.revs.set(key, saved.rev);
  } catch (err) {
    toast(err.status === 409 ? "That changed somewhere else, so here it is as it is now" : said(err));
    v.draw();
  }
}

// -- a form --------------------------------------------------------------------------------------
// The action's own form, drawn in the view rather than in a sheet: the
// same fields, and a submit that is the action's button.
function drawForm(v, n) {
  const action = findAction(v.at.quill.id, n.action);
  if (!action) return "";
  v.forms.push({ n, action });
  return `<form class="v-form record" novalidate data-form="${v.forms.length - 1}">` +
    formFields(action.fields, n.values || {}, v.formLinks[action.id] || {}) +
    `<p class="act-error" role="alert" hidden></p>` +
    `<div class="act-buttons"><button type="submit" class="act-button ${toneClass(v, action.tone === "danger" ? "danger" : "primary")}">` +
    `${esc(n.submit || action.label)}</button></div></form>`;
}

function wireForms(v) {
  for (const form of v.root.querySelectorAll("form[data-form]")) {
    const { n, action } = v.forms[Number(form.dataset.form)];
    const errorEl = form.querySelector(".act-error");
    const showError = (text) => { errorEl.textContent = text; errorEl.hidden = !text; };
    wireFields(form);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const { fields, problem } = readFields(form, action.fields);
      if (problem) { showError(problem); return; }
      if (action.confirm && !(await ask(action.confirm, { yes: action.label, tone: action.tone }))) return;
      const submit = form.querySelector("[type=submit]");
      submit.disabled = true;
      showError("");
      await run(v.at.quill, action, {
        record: n.record ? n.record.id : "", fields: { ...(n.values || {}), ...fields },
        here: v.at, after: v.draw, showError,
      });
      if (submit.isConnected) submit.disabled = false;
    });
  }
}

// -- records -------------------------------------------------------------------------------------
const none = (text) => (text ? `<p class="v-none">${esc(text)}</p>` : "");

// A table on a computer; on a phone each row is a card of its own, the
// first column its title and the rest said under it with their labels.
function drawTable(v, n) {
  if (!n.records.length) return none(n.empty);
  const first = n.records[0].model;
  const labels = n.columns.map((c) => c.label || labelOf(v, first, c.field));
  const actions = (n.actions || []).map((id) => findAction(v.at.quill.id, id)).filter(Boolean);
  const head = labels.map((label) => `<th scope="col">${esc(label)}</th>`).join("") +
    (actions.length ? `<th class="v-row-actions"><span class="v-hidden">Actions</span></th>` : "");
  const rows = n.records.map((r) => {
    const hash = n.open !== false ? sheetOf(v, r) : "";
    const cells = n.columns.map((c, i) => {
      const text = say(v, r, c.field) || "—";
      const inner = i === 0 && hash ? `<a href="${esc(hash)}">${esc(text)}</a>` : esc(text);
      return `<td data-label="${esc(labels[i])}">${inner}</td>`;
    }).join("");
    const runOn = (action) => () => press(v.at.quill, action, { record: r.id, here: v.at, after: v.draw });
    const buttons = !actions.length ? "" : actions.length === 1
      ? `<button type="button" class="act-chip" ${doing(v, runOn(actions[0]))}>${esc(actions[0].label)}</button>`
      : `<button type="button" class="v-more" aria-label="More" ${doing(v, () => choose(titled(v, r, n.columns[0] && n.columns[0].field),
        actions.map((a) => ({ label: a.label, tone: a.tone, run: runOn(a) }))))}>${glyphs.more}</button>`;
    return `<tr${hash ? ` class="v-opens" ${doing(v, () => go(hash))}` : ""}>${cells}` +
      (actions.length ? `<td class="v-row-actions">${buttons}</td>` : "") + `</tr>`;
  }).join("");
  return `<div class="v-table"><table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
}

function drawCards(v, n) {
  if (!n.records.length) return none(n.empty);
  return `<div class="v-cards">` + n.records.map((r) => {
    const hash = n.open !== false ? sheetOf(v, r) : "";
    const badge = n.badge ? say(v, r, n.badge) : "";
    const inner = `<span class="v-card-head"><span class="title">${esc(titled(v, r, n.title))}</span>` +
      (badge ? `<span class="v-badge">${esc(badge)}</span>` : "") + `</span>` +
      (n.subtitle && say(v, r, n.subtitle) ? `<span class="v-card-sub">${esc(say(v, r, n.subtitle))}</span>` : "") +
      (n.body && say(v, r, n.body) ? `<span class="v-card-body">${esc(say(v, r, n.body))}</span>` : "");
    return hash ? `<a class="v-card" href="${esc(hash)}">${inner}</a>` : `<div class="v-card">${inner}</div>`;
  }).join("") + `</div>`;
}

// The board's lanes, from the tree: the enum's own values and labels unless
// the view names them. A card dragged to another lane is moved with the
// same call the board makes, at once, and the view drawn again after.
function drawLanes(v, n) {
  const modelId = (n.records[0] && n.records[0].model) || v.at.screen.model;
  const model = v.at.quill.models[modelId];
  const f = model && fieldOf(model, n.field);
  const lanes = n.lanes && n.lanes.length
    ? n.lanes.map((l) => [l.value, l.label])
    : f && f.kind === "enum" ? f.values.map((value, i) => [value, (f.labels && f.labels[i]) || value])
      : [...new Set(n.records.map((r) => String(r.fields[n.field] ?? "")))].map((x) => [x, x]);
  const drags = !!(model && f && mayWrite(model) && canDrag());
  v.lanes.push({ n, modelId });
  return `<div class="v-lanes" style="--lanes: ${lanes.length}" data-lanes="${v.lanes.length - 1}">` + lanes.map(([value, label]) => {
    const cards = n.records.filter((r) => String(r.fields[n.field] ?? "") === String(value));
    return `<div class="v-lane" data-lane="${esc(value)}"><p class="group-label">${esc(label)}` +
      `<span class="v-count">${cards.length}</span></p><div class="group v-lane-cards">` +
      (cards.length ? cards.map((r) => {
        const hash = sheetOf(v, r);
        const body = n.body ? say(v, r, n.body) : "";
        const text = `<span class="title">${esc(titled(v, r, n.title))}</span>` +
          (body ? `<span class="meta"><span class="preview">${esc(body)}</span></span>` : "");
        return `<div class="row v-lane-card" data-id="${esc(r.id)}"${drags ? ' draggable="true"' : ""}>` +
          (hash ? `<a class="main" href="${esc(hash)}">${text}</a>` : `<span class="main">${text}</span>`) + `</div>`;
      }).join("") : `<div class="nothing">Nothing here</div>`) +
      `</div></div>`;
  }).join("") + `</div>`;
}

function wireLanes(v) {
  if (!canDrag()) return;
  for (const board of v.root.querySelectorAll("[data-lanes]")) {
    const { n, modelId } = v.lanes[Number(board.dataset.lanes)];
    let dragged = null;
    // Where in the lane it would go: the other cards whose middle is above the pointer.
    const indexAt = (lane, y) => [...lane.querySelectorAll(".v-lane-card")]
      .filter((card) => card !== dragged)
      .filter((card) => { const box = card.getBoundingClientRect(); return box.top + box.height / 2 < y; }).length;
    for (const card of board.querySelectorAll('.v-lane-card[draggable="true"]')) {
      card.addEventListener("dragstart", (event) => {
        dragged = card;
        card.classList.add("dragging");
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", card.dataset.id);
      });
      card.addEventListener("dragend", () => {
        card.classList.remove("dragging");
        dragged = null;
        for (const lane of board.querySelectorAll(".over")) lane.classList.remove("over");
      });
    }
    for (const lane of board.querySelectorAll(".v-lane")) {
      lane.addEventListener("dragover", (event) => {
        if (!dragged) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        lane.classList.add("over");
      });
      lane.addEventListener("dragleave", (event) => {
        if (!lane.contains(event.relatedTarget)) lane.classList.remove("over");
      });
      lane.addEventListener("drop", async (event) => {
        if (!dragged) return;
        event.preventDefault();
        lane.classList.remove("over");
        const card = dragged;
        const index = indexAt(lane, event.clientY);
        // Moved on the page first, so the drop does not wait for the server.
        const cards = lane.querySelector(".v-lane-cards");
        const nothing = cards.querySelector(".nothing");
        if (nothing) nothing.remove();
        cards.insertBefore(card, [...cards.querySelectorAll(".v-lane-card")].filter((c) => c !== card)[index] || null);
        try {
          await api("POST", recordsUrl(modelId, card.dataset.id) + "/move",
            { fields: { [n.field]: lane.dataset.lane }, index });
        } catch (err) { toast(said(err)); }
        v.draw();
      });
    }
  }
}

// A month of records by a date field. On a computer each day says what is
// on it; on a phone a day has dots, and the month's records are listed
// under it by day.
function drawMonth(v, n, p) {
  const first = v.months.get(p) || ((n.start && /^\d{4}-\d{2}$/.test(n.start) ? n.start : monthOf(today())) + "-01");
  const byDay = new Map();
  for (const r of n.records) {
    const start = String(r.fields[n.date] || "").slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(start)) continue;
    let end = n.ends ? String(r.fields[n.ends] || "").slice(0, 10) : start;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(end) || end < start) end = start;
    // Every day it is on, and no more than a couple of months of them.
    for (let day = start, i = 0; day <= end && i < 62; day = addDays(day, 1), i += 1) {
      if (!byDay.has(day)) byDay.set(day, []);
      byDay.get(day).push(r);
    }
  }
  const month = monthOf(first);
  const name = dateOf(first).toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const step = (by) => doing(v, () => { v.months.set(p, addMonths(first, by)); v.paint(); });
  const now = today();
  const item = (r) => {
    const hash = sheetOf(v, r);
    const text = esc(titled(v, r, n.title));
    return hash ? `<a class="v-day-item" href="${esc(hash)}">${text}</a>` : `<span class="v-day-item">${text}</span>`;
  };
  const cells = weeksOf(first).flat().map((day) => {
    const on = byDay.get(day) || [];
    return `<div class="v-day${monthOf(day) !== month ? " out" : ""}${day === now ? " today" : ""}">` +
      `<span class="n">${dateOf(day).getDate()}</span>` +
      on.slice(0, 3).map(item).join("") +
      (on.length > 3 ? `<span class="v-day-more">+${on.length - 3}</span>` : "") + `</div>`;
  }).join("");
  const days = [...byDay.keys()].filter((day) => monthOf(day) === month).sort();
  const list = days.map((day) => `<p class="group-label">${esc(longDay(day))}</p><div class="group">` +
    byDay.get(day).map((r) => {
      const hash = sheetOf(v, r);
      const text = `<span class="main"><span class="title">${esc(titled(v, r, n.title))}</span></span>`;
      return hash ? `<a class="row" href="${esc(hash)}">${text}</a>` : `<div class="row">${text}</div>`;
    }).join("") + `</div>`).join("");
  return `<div class="v-month">` +
    `<div class="v-month-bar"><button type="button" class="step" aria-label="Previous month" ${step(-1)}>${glyphs.left}</button>` +
    `<h3>${esc(name)}</h3><button type="button" class="step" aria-label="Next month" ${step(1)}>${glyphs.right}</button></div>` +
    `<div class="v-weekdays">${WEEKDAYS.map((d) => `<span>${d}</span>`).join("")}</div>` +
    `<div class="v-days">${cells}</div>` +
    `<div class="v-month-list">${list || `<p class="v-none">Nothing in ${esc(name)}.</p>`}</div></div>`;
}

// -- pictures --------------------------------------------------------------------------------
// A record's picture comes through fetch with the token, which an <img src>
// cannot carry, and is kept for as long as the view is open.
async function loadThumbs(v) {
  const size = (window.devicePixelRatio || 1) > 1.5 ? 1024 : 512;
  for (const el of v.root.querySelectorAll("[data-thumb-id]")) {
    const key = `${el.dataset.thumbModel}/${el.dataset.thumbId}`;
    try {
      if (!v.thumbs.has(key)) {
        v.thumbs.set(key, fetch(recordsUrl(el.dataset.thumbModel, el.dataset.thumbId) + "/thumb?size=" + size,
          { headers: authHeaders() }).then(async (res) => {
          if (!res.ok) throw new Error("no picture");
          return URL.createObjectURL(await res.blob());
        }));
      }
      const url = await v.thumbs.get(key);
      const img = document.createElement("img");
      img.alt = el.getAttribute("aria-label") || "";
      img.src = url;
      el.replaceChildren(img);
      el.classList.add("has-img");
    } catch {
      el.textContent = el.getAttribute("aria-label") || "No picture";
      el.classList.add("no-img");
    }
  }
}

// -- Markdown ----------------------------------------------------------------------------------
// What a view's words need and no more: paragraphs, headings, lists,
// quotes, code, emphasis and links. Escaped first, so nothing in the text
// is ever markup of its own; a link is only an http(s) or mailto one.
function inline(text) {
  return esc(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*\w])[*_]([^*_\s][^*_]*)[*_](?![*\w])/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\(((?:https?:\/\/|mailto:)[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

export function markdown(source) {
  const out = [];
  let para = [];
  let list = null;
  let code = null;
  const endPara = () => { if (para.length) out.push(`<p>${inline(para.join(" "))}</p>`); para = []; };
  const endList = () => { if (list) out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`); list = null; };
  for (const line of String(source).split("\n")) {
    if (code !== null) {
      if (/^```/.test(line.trim())) { out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`); code = null; }
      else code.push(line);
      continue;
    }
    if (/^```/.test(line.trim())) { endPara(); endList(); code = []; continue; }
    const head = /^(#{1,4})\s+(.*)$/.exec(line);
    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    const quote = /^>\s?(.*)$/.exec(line);
    if (!line.trim()) { endPara(); endList(); }
    else if (head) { endPara(); endList(); out.push(`<h${head[1].length + 2}>${inline(head[2])}</h${head[1].length + 2}>`); }
    else if (bullet || numbered) {
      endPara();
      const tag = bullet ? "ul" : "ol";
      if (list && list.tag !== tag) endList();
      list = list || { tag, items: [] };
      list.items.push((bullet || numbered)[1]);
    } else if (quote) { endPara(); endList(); out.push(`<blockquote>${inline(quote[1])}</blockquote>`); }
    else { endList(); para.push(line.trim()); }
  }
  if (code !== null) out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
  endPara();
  endList();
  return out.join("");
}
