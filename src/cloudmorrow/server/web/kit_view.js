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

import {
  api, apiRaw, app, back, esc, go, heading, icons, mount, nav, recordsUrl, seconds, sectionOf, store, tabs, toast,
  wireShell,
} from "./core.js";
import { canDrag, dragLanes, fieldOf, mayWrite, read, segments, sheetHash, spoken, titleOf, widget } from "./kit.js";
import {
  WEEKDAYS, addDays, addMonths, dateOf, longDay, monthOf, today, weeksOf,
} from "./kit_calendar.js";
import {
  choose, contextMenus, findAction, formFields, hideFromBar, linksFor, onRedrawHere, peopleList, press,
  readFields, recordChoices, run, said, screenAt, wireFields,
} from "./actions.js";
import { ask } from "./dialog.js";

const glyphs = {
  left: '<svg width="11" height="18" viewBox="0 0 11 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M8.5 1.5 2 9l6.5 7.5"/></svg>',
  right: '<svg width="11" height="18" viewBox="0 0 11 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 1.5 9 9l-6.5 7.5"/></svg>',
  more: '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
  down: '<svg width="10" height="7" viewBox="0 0 10 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m1 1.5 4 4 4-4"/></svg>',
  send: '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M3.2 11.1 20 3.4c.8-.4 1.6.4 1.2 1.2L13.5 21c-.4.8-1.5.7-1.8-.1l-2.1-6-6-2.1c-.8-.3-.9-1.4-.4-1.7Z"/></svg>',
  close: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  // The list beside what is open: a panel with a pane at its left, to fold away and bring back.
  sidebar: '<svg width="18" height="16" viewBox="0 0 20 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="1.5" y="1.5" width="17" height="15" rx="2.5"/><path d="M7.5 1.5v15"/></svg>',
};

// The same test the board uses: a phone has no way to drag anything.
const onComputer = matchMedia("(min-width: 900px) and (min-height: 600px)");

export async function renderView(at, arg) {
  const params = Object.fromEntries(new URLSearchParams(arg || ""));
  // The screen's pen: the action its manifest names as `compose`, drawn in
  // the heading as a list's New is, and left off the bar under it.
  const compose = at.screen.compose && findAction(at.quill.id, at.screen.compose.action);
  const penLabel = compose ? (at.screen.compose.label || compose.label) : "";
  // The Quill's own settings are a page of their own, the way back to
  // the Quill on its bar; the gear beside its title is what led here.
  const bar = at.screen.settings
    ? nav({ back: at.home, backLabel: at.quill.name, title: at.screen.label })
    : nav({ title: at.screen.label });
  mount(bar + `
    <main class="view-screen">
      ${heading(at.screen.label, compose
    ? `<button class="compose" aria-label="${esc(penLabel)}" title="${esc(penLabel)}">${icons.compose}</button>` : "")}
      <div class="quill-view" aria-busy="true"></div>
    </main>` + tabs(at.tab));
  wireShell();
  const root = app.querySelector(".quill-view");
  const v = await embedView(root, at, params);
  onRedrawHere({ alive: () => root.isConnected, draw: v.draw });
  const pen = app.querySelector(".heading .compose");
  if (pen && compose) pen.addEventListener("click", () => press(at.quill, compose, { here: at, after: v.draw }));
}

/** The view drawn into *root*, a holder on a page of somebody else's: the
    Quill's settings on its sheet under Administration (quillsadmin.js). It
    is the whole of a view but the page around it; a `go` to the same screen
    draws it again here with the new parameters rather than leaving the page. */
export async function embedView(root, at, params = {}) {
  root.classList.add("quill-view");
  root.setAttribute("aria-busy", "true");
  // Everything one drawing of the view needs, and what it keeps between
  // drawings: which tab is open, which month is shown, each record's rev.
  const v = {
    at, params, root, tree: null,
    open: new Map(), months: new Map(), revs: new Map(), thumbs: new Map(),
    links: {}, formLinks: {}, handlers: [], menus: [], edits: [], forms: [], toggles: [], chats: [], lanes: [], amber: false,
  };
  v.draw = () => draw(v);
  v.paint = () => paint(v);
  if (at.embedded) at.goHere = (next) => { v.params = { ...(next || {}) }; return v.draw(); };
  // One listener for everything pressed in the view: each drawing hands
  // out numbers, and the element pressed carries its own.
  root.addEventListener("click", (event) => {
    const el = event.target.closest("[data-do]");
    if (!el || !root.contains(el)) return;
    const handler = v.handlers[Number(el.dataset.do)];
    if (!handler) return;
    event.preventDefault();
    event.stopPropagation();
    // A press that takes a while — an action that reaches out — shows it on
    // the button itself until it is over: busy, and not to be pressed twice.
    const outcome = handler(el, event);
    if (outcome && typeof outcome.then === "function") {
      el.setAttribute("aria-busy", "true");
      if ("disabled" in el) el.disabled = true;
      outcome.finally(() => {
        if (!el.isConnected) return;
        el.removeAttribute("aria-busy");
        if ("disabled" in el) el.disabled = false;
      });
    }
  });
  // And one for the menu a row, card or tile has — a right-click on a
  // computer, a finger held on it on a phone — numbered the same way.
  contextMenus(root, "[data-menu]", (el) => v.menus[Number(el.dataset.menu)] || null);
  await draw(v);
  return v;
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
  await fetchPeople(v, v.tree);
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
  v.menus = [];
  v.edits = [];
  v.forms = [];
  v.toggles = [];
  v.chats = [];
  v.lanes = [];
  v.amber = false;
  v.root.removeAttribute("aria-busy");
  v.root.innerHTML = node(v, v.tree, "0");
  wireEdits(v);
  wireForms(v);
  wireToggles(v);
  wireChats(v);
  wireRows(v);
  wireFolds(v);
  wireLanes(v);
  loadThumbs(v);
  // What the view has its own button for is not in the bar as well.
  const pressed = pressedIn(v.tree);
  if (v.at.screen.compose) pressed.add(v.at.screen.compose.action);
  hideFromBar(pressed);
  if (!v.at.embedded) syncBack(v);
}

/** A handler for an element, as the attribute the element carries. */
const doing = (v, fn) => {
  v.handlers.push(fn);
  return `data-do="${v.handlers.length - 1}"`;
};

/** The menu a record's row, card or tile has, as the attribute it carries:
    Open (to *hash*), the *actions* the view declares on it, and the actions
    on its datamodel (actions.js, `recordChoices`); "" when it has none. */
const menuOn = (v, record, hash, actions = []) => {
  const choices = recordChoices(record, {
    open: hash || "", extra: actions.map((action) => ({ quill: v.at.quill, action })), here: v.at, after: v.draw,
  });
  if (!choices.length) return "";
  v.menus.push(choices);
  return `data-menu="${v.menus.length - 1}"`;
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
/** Where a table's row or a card goes: a screen of the Quill's own (`go`), with the record's id, else its sheet. */
const rowGoes = (v, n, record) => n.go
  ? screenAt(v.at.quill.id, n.go, { ...(n.params || {}), [n.param || "record"]: record.id })
  : n.open !== false ? sheetOf(v, record) : "";

// Every link field the tree says, so its titles are fetched once, before
// anything is drawn, rather than a request per row.
function* walk(n) {
  if (!n || typeof n !== "object") return;
  yield n;
  for (const child of n.children || n.items || []) yield* walk(child);
  for (const tab of n.tabs || []) yield* walk(tab.child);
  if (n.ui === "split") { yield* walk(n.side); yield* walk(n.main); }
}

/** The server's people, once, when a form in the tree suggests them. */
async function fetchPeople(v, tree) {
  if (v.people) return;
  for (const n of walk(tree)) {
    if (n.ui !== "form") continue;
    const action = findAction(v.at.quill.id, n.action);
    if (action && action.fields.some((f) => f.suggest === "people")) {
      v.people = await peopleList();
      return;
    }
  }
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
/** The way back a split names when it shows its main: the screen's back
    button, put in the bar as a page of a document has one, or taken out. */
function syncBack(v) {
  const bar = app.querySelector("header.nav .left");
  if (!bar) return;
  const split = [...walk(v.tree)].find((n) => n.ui === "split" && n.show === "main" && n.back);
  const had = bar.querySelector("[data-view-back]");
  if (!split) { if (had) had.remove(); return; }
  const hash = screenAt(v.at.quill.id, v.at.screen.id, split.back);
  if (had && had.dataset.back === hash) return;
  if (had) had.remove();
  bar.insertAdjacentHTML("afterbegin",
    `<button class="back" data-view-back data-back="${esc(hash)}">${icons.chevronLeft}${esc(v.at.screen.label)}</button>`);
  bar.querySelector("[data-view-back]").addEventListener("click", () => back(hash));
}

function pressedIn(tree) {
  const ids = new Set();
  for (const n of walk(tree)) {
    if (n.action) ids.add(n.action);
    if (n.ask) ids.add(n.ask);
    if (n.close) ids.add(n.close);   // a conversation's X, or the X on each row
  }
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
  // A list beside what is chosen in it. On a phone only one of the two has
  // room: `show` says which, and the stylesheet hides the other there.
  split: (v, n, p) => {
    // A side that folds: a line over it with the button at its right end, on
    // a computer; folded, the strip alone. The choice is kept per screen.
    const key = n.fold ? foldKey(v) : "";
    const folded = !!key && store.get(key) === "1";
    const head = !key ? "" : `<div class="v-side-head"><button type="button" class="v-fold" aria-label="${folded ? "Show the list" : "Hide the list"}" ` +
      `title="${folded ? "Show the list" : "Hide the list"}">${glyphs.sidebar}</button></div>`;
    return `<div class="v-split${folded ? " folded" : ""}" data-show="${esc(n.show === "main" ? "main" : "side")}"${key ? ` data-fold="${esc(key)}"` : ""}>` +
      `<div class="v-split-side">${head}${node(v, n.side, `${p}.0`)}</div>` +
      `<div class="v-split-main">${node(v, n.main, `${p}.1`)}</div></div>`;
  },
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
  toggle: drawToggle,
  conversation: drawConversation,
  button: (v, n) => drawButton(v, n),
  menu: (v, n) => {
    const items = n.items.map((item) => pressable(v, item)).filter(Boolean);
    if (!items.length) return "";
    return `<button type="button" class="act-button v-menu" aria-haspopup="menu" ${doing(v, () => choose(n.label, items))}>` +
      `${esc(n.label)}${glyphs.down}</button>`;
  },
  table: drawTable,
  cards: drawCards,
  rows: drawRows,
  gallery: drawGallery,
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
// than a box each; toggles the same, so a settings screen is one box of switches.
function children(v, list, p) {
  let out = "";
  let run = [];
  const flush = () => {
    if (run.length) out += `<div class="group fields record v-fields">${run.join("")}</div>`;
    run = [];
  };
  list.forEach((child, i) => {
    if (child && child.ui === "field") { run.push(fieldRow(v, child)); return; }
    if (child && child.ui === "toggle") { run.push(toggleRow(v, child)); return; }
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
    if (v.at.goHere && n.go === v.at.screen.id) {
      return { label: n.label, tone: n.tone, run: () => v.at.goHere(n.params) };
    }
    const hash = screenAt(quill.id, n.go, n.params);
    return { label: n.label, tone: n.tone, href: hash, run: () => (hash === location.hash ? v.draw() : go(hash)) };
  }
  return null;
}

function drawButton(v, n) {
  const does = pressable(v, n);
  if (!does) return "";
  const cls = `act-button ${toneClass(v, n.tone)}${n.current ? " current" : ""}`.trim();
  const now = n.current ? ' aria-current="page"' : "";
  if (does.href && does.href !== location.hash) return `<a class="${cls}"${now} href="${esc(does.href)}">${esc(n.label)}</a>`;
  return `<button type="button" class="${cls}"${now} ${doing(v, does.run)}>${esc(n.label)}</button>`;
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
    formFields(action.fields, n.values || {}, v.formLinks[action.id] || {}, v.people || []) +
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

// -- a toggle ------------------------------------------------------------------------------------
// A setting as a switch: flipping it runs the action at once with the new
// state, and the view is drawn again. No form, no button lit or unlit.
function drawToggle(v, n) {
  const row = toggleRow(v, n);
  return row ? `<div class="group fields record v-fields">${row}</div>` : "";
}

function toggleRow(v, n) {
  const action = findAction(v.at.quill.id, n.action);
  if (!action) return "";
  v.toggles.push({ n, action });
  return `<label class="row field v-toggle" data-toggle="${v.toggles.length - 1}"><span class="main">${esc(n.label)}` +
    (n.hint ? `<span class="v-toggle-hint">${esc(n.hint)}</span>` : "") + `</span>` +
    `<input type="checkbox" class="switch" aria-label="${esc(n.label)}"${n.on ? " checked" : ""}></label>`;
}

const foldKey = (v) => `view.folded.${v.at.quill.id}/${v.at.screen.id}`;
function wireFolds(v) {
  for (const button of v.root.querySelectorAll(".v-split[data-fold] > .v-split-side > .v-side-head > .v-fold")) {
    const split = button.closest(".v-split");
    button.addEventListener("click", () => {
      const now = !split.classList.contains("folded");
      split.classList.toggle("folded", now);
      store.set(split.dataset.fold, now ? "1" : null);
      button.setAttribute("aria-label", now ? "Show the list" : "Hide the list");
      button.title = button.getAttribute("aria-label");
    });
  }
}

// The search field over rows: what is typed narrows them to the titles and
// subtitles holding it, a heading going with its last row.
function wireRows(v) {
  for (const box of v.root.querySelectorAll(".v-rows > .v-search > input")) {
    const rows = box.closest(".v-rows");
    box.addEventListener("input", () => {
      const needle = box.value.trim().toLowerCase();
      let shown = 0;
      for (const row of rows.querySelectorAll(".v-row-item")) {
        const hit = !needle || row.dataset.find.includes(needle);
        row.classList.toggle("v-hidden", !hit);
        shown += hit ? 1 : 0;
      }
      for (const group of rows.querySelectorAll(".v-list")) {
        const empty = !group.querySelector(".v-row-item:not(.v-hidden)");
        group.classList.toggle("v-hidden", empty);
        const label = group.previousElementSibling;
        if (label && label.classList.contains("group-label")) label.classList.toggle("v-hidden", empty);
      }
      rows.querySelector(".v-nomatch").hidden = shown > 0;
    });
  }
}

function wireToggles(v) {
  for (const row of v.root.querySelectorAll("[data-toggle]")) {
    const { n, action } = v.toggles[Number(row.dataset.toggle)];
    const box = row.querySelector("input");
    box.addEventListener("change", async () => {
      const on = box.checked;
      if (action.confirm && !(await ask(action.confirm, { yes: action.label, tone: action.tone }))) { box.checked = !on; return; }
      box.disabled = true;
      const failed = await run(v.at.quill, action, {
        record: n.record ? n.record.id : "", fields: { ...(n.args || {}), [n.field]: on }, here: v.at, after: v.draw,
      });
      // Still on the page only when the action did not end in a redraw: put the switch back.
      if (box.isConnected) { box.disabled = false; if (failed) box.checked = !on; }
    });
  }
}

// -- a conversation ------------------------------------------------------------------------------
// A chat: the person's lines on the right in a filled bubble, the other
// side's on the left as a page, the newest at the bottom, and the box to
// write in on the floor. What is sent is shown at once, with the other
// side thinking, until the action is done and the view drawn again; what
// could not be sent goes back into the box.
const askField = (action) => (action && (action.fields || []).find((f) => ["text", "markdown", "string"].includes(f.kind))) || null;

function drawConversation(v, n) {
  const action = n.ask ? findAction(v.at.quill.id, n.ask) : null;
  const field = askField(action);
  const lines = n.records.map((r) => chatLine(v, n, r)).join("");
  let box = "";
  if (action && field) {
    v.chats.push({ n, action, field });
    const words = n.placeholder || action.label;
    box = `<form class="v-composer" data-chat="${v.chats.length - 1}">` +
      `<textarea rows="1" placeholder="${esc(words)}" aria-label="${esc(words)}" enterkeyhint="send" autocapitalize="sentences"></textarea>` +
      `<button type="submit" aria-label="${esc(action.label)}">${glyphs.send}</button></form>`;
  }
  // The X in the corner: the `close` action on the conversation's record,
  // through press, so the manifest's confirm is asked first.
  const closing = n.close ? findAction(v.at.quill.id, n.close) : null;
  const x = !closing ? "" :
    `<button type="button" class="v-close" aria-label="${esc(closing.label)}" title="${esc(closing.label)}" ` +
    `${doing(v, () => press(v.at.quill, closing, { record: n.record ? n.record.id : "", here: v.at, after: v.draw }))}>${glyphs.close}</button>`;
  return `<div class="v-conversation${n.backdrop ? " backdrop-" + esc(n.backdrop) : ""}">` + x + `<div class="v-lines" aria-live="polite">` +
    (lines || (n.empty ? `<div class="v-greeting">${esc(n.empty)}</div>` : "")) + `</div>` + box +
    (n.hint ? `<p class="v-composer-hint">${esc(n.hint)}</p>` : "") + `</div>`;
}

function chatLine(v, n, r) {
  const fields = r.fields || {};
  const mine = !!fields[n.mine];
  const failed = !!(n.failed && fields[n.failed]);
  const at = n.at ? say(v, r, n.at) : "";
  const note = n.note ? say(v, r, n.note) : "";
  const words = String(fields[n.body] ?? "");
  const under = (failed ? `<span class="v-badge tone-bad">Did not go through</span>` : "") +
    (note ? `<span>${esc(note)}</span>` : "") + (at ? `<span>${esc(at)}</span>` : "");
  return `<div class="v-line${mine ? " mine" : ""}${failed ? " failed" : ""}">` +
    (!mine && n.name ? `<span class="v-who">${esc(n.name)}</span>` : "") +
    (mine ? `<div class="v-bubble">${esc(words)}</div>` : `<div class="v-bubble v-markdown">${markdown(words)}</div>`) +
    (under ? `<span class="v-under">${under}</span>` : "") + `</div>`;
}

// A one-line box that grows to what is typed and stops before it eats the
// screen; past that it scrolls inside itself.
const MAX_BOX = 140;
function growBox(box) {
  box.style.height = "auto";
  const wanted = box.scrollHeight;
  box.style.height = Math.min(wanted, MAX_BOX) + "px";
  box.style.overflowY = wanted > MAX_BOX ? "auto" : "hidden";
}

function wireChats(v) {
  for (const form of v.root.querySelectorAll("form[data-chat]")) {
    const { n, action, field } = v.chats[Number(form.dataset.chat)];
    const box = form.querySelector("textarea");
    const button = form.querySelector("button");
    const lines = form.parentElement.querySelector(".v-lines");
    const toBottom = () => { lines.scrollTop = lines.scrollHeight; };
    toBottom();
    growBox(box);
    // On a computer the box has the focus as soon as the conversation is
    // drawn — on arriving, and again once the answer is in. A phone would
    // raise its keyboard over the answer, so there the person taps first.
    if (onComputer.matches && !v.root.contains(document.activeElement)) box.focus({ preventScroll: true });
    box.addEventListener("input", () => growBox(box));
    // Enter sends on a keyboard, and the return key on a phone is the send
    // key because `enterkeyhint` made it one. Shift+Enter is a new line.
    box.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        form.requestSubmit();
      }
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const text = box.value.trim();
      if (!text || box.disabled) return;
      box.value = "";
      growBox(box);
      box.disabled = true;
      button.disabled = true;
      const greeting = lines.querySelector(".v-greeting");
      if (greeting) greeting.remove();
      lines.insertAdjacentHTML("beforeend",
        `<div class="v-line mine v-sent"><div class="v-bubble">${esc(text)}</div></div>` +
        `<div class="v-line v-thinking" role="status" aria-label="Waiting for an answer"><span></span><span></span><span></span></div>`);
      toBottom();
      const failed = await run(v.at.quill, action, {
        record: n.record ? n.record.id : "", fields: { [field.name]: text }, here: v.at, after: v.draw,
      });
      // Not drawn again, so it ended in an error: the words go back rather than being lost.
      if (failed && form.isConnected) {
        for (const el of lines.querySelectorAll(".v-sent, .v-thinking")) el.remove();
        box.value = text;
        growBox(box);
        box.disabled = false;
        button.disabled = false;
        box.focus();
      }
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
    const hash = rowGoes(v, n, r);
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
    return `<tr ${menuOn(v, r, hash, actions)}${hash ? ` class="v-opens" ${doing(v, () => go(hash))}` : ""}>${cells}` +
      (actions.length ? `<td class="v-row-actions">${buttons}</td>` : "") + `</tr>`;
  }).join("");
  return `<div class="v-table"><table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
}

// The app's own rows, as a list screen draws them: the title, a line under
// it, a badge at the end; the one that is open lit, beside what it opened.
function drawRows(v, n) {
  if (!n.records.length) return none(n.empty);
  // The X at a row's end: the `close` action on that record, through press,
  // so the manifest's confirm is asked first; the view's one click listener
  // keeps the press from opening the row.
  const closing = n.close ? findAction(v.at.quill.id, n.close) : null;
  const row = (r) => {
    const hash = rowGoes(v, n, r);
    const badge = n.badge ? say(v, r, n.badge) : "";
    const sub = n.subtitle ? say(v, r, n.subtitle) : "";
    const title = titled(v, r, n.title);
    const x = !closing ? "" : `<button type="button" class="v-row-close" aria-label="${esc(closing.label)}: ${esc(title)}" title="${esc(closing.label)}" ` +
      `${doing(v, () => press(v.at.quill, closing, { record: r.id, here: v.at, after: v.draw }))}>${glyphs.close}</button>`;
    const inner = `<span class="main"><span class="title">${esc(title)}</span>` +
      (sub ? `<span class="meta"><span class="preview">${esc(sub)}</span></span>` : "") + `</span>` +
      (badge ? `<span class="v-badge">${esc(badge)}</span>` : "") + x;
    const menu = menuOn(v, r, hash);
    const cls = `row v-row-item${n.current && n.current === r.id ? " current" : ""}`;
    const find = `data-find="${esc((title + " " + sub).toLowerCase())}"`;
    return hash ? `<a class="${cls}" ${menu} ${find} href="${esc(hash)}"${n.current === r.id ? ' aria-current="true"' : ""}>${inner}</a>`
      : `<div class="${cls}" ${menu} ${find}>${inner}</div>`;
  };
  let groups;
  if (n.group) {
    // Given newest first, so the headings fall out in order: Today,
    // Yesterday, Last 7 Days, Last 30 Days, each month, each year.
    const sections = new Map();
    for (const r of n.records) {
      const at = seconds(r.fields[n.group]);
      const label = at === null ? "" : sectionOf(at);
      if (!sections.has(label)) sections.set(label, []);
      sections.get(label).push(r);
    }
    groups = [...sections].map(([label, rs]) =>
      (label ? `<p class="group-label">${esc(label)}</p>` : "") + `<div class="group v-list">${rs.map(row).join("")}</div>`).join("");
  } else {
    groups = `<div class="group v-list">${n.records.map(row).join("")}</div>`;
  }
  if (!n.search) return groups;
  return `<div class="v-rows"><div class="v-search">${icons.search}<input type="search" placeholder="${esc(n.search)}" ` +
    `aria-label="${esc(n.search)}" autocapitalize="none" autocorrect="off"></div>${groups}` +
    `<p class="v-none v-nomatch" hidden>Nothing matches.</p></div>`;
}

function drawCards(v, n) {
  if (!n.records.length) return none(n.empty);
  return `<div class="v-cards">` + n.records.map((r) => {
    const hash = rowGoes(v, n, r);
    const badge = n.badge ? say(v, r, n.badge) : "";
    const inner = `<span class="v-card-head"><span class="title">${esc(titled(v, r, n.title))}</span>` +
      (badge ? `<span class="v-badge">${esc(badge)}</span>` : "") + `</span>` +
      (n.subtitle && say(v, r, n.subtitle) ? `<span class="v-card-sub">${esc(say(v, r, n.subtitle))}</span>` : "") +
      (n.body && say(v, r, n.body) ? `<span class="v-card-body">${esc(say(v, r, n.body))}</span>` : "");
    const menu = menuOn(v, r, hash);
    const cls = `v-card${n.current && n.current === r.id ? " current" : ""}`;
    return hash ? `<a class="${cls}" ${menu} href="${esc(hash)}"${n.current === r.id ? ' aria-current="true"' : ""}>${inner}</a>`
      : `<div class="${cls}" ${menu}>${inner}</div>`;
  }).join("") + `</div>`;
}

// Tiles, each the record's own picture with its title under it: a photo
// library's grid. The picture is the record's thumbnail, fetched when the
// tile comes into sight; a video's is a frame of it. The stars run the
// view's rating action at once, no form — the star already lit takes it
// back to none — and are lit at once, before the view is drawn again.
function drawGallery(v, n) {
  if (!n.records.length) return none(n.empty);
  const rate = n.rate && findAction(v.at.quill.id, n.rate);
  const actions = (n.actions || []).map((id) => findAction(v.at.quill.id, id)).filter(Boolean);
  return `<div class="v-gallery">` + n.records.map((r) => {
    const hash = n.open !== false ? sheetOf(v, r) : "";
    const title = titled(v, r, n.title);
    const badge = n.badge ? say(v, r, n.badge) : "";
    const pic = `<span class="v-thumb v-tile-thumb" role="img" aria-label="${esc(title)}" data-thumb-size="256"` +
      ` data-thumb-model="${esc(r.model)}" data-thumb-id="${esc(r.id)}"></span>` +
      (badge ? `<span class="v-tile-badge">${esc(badge)}</span>` : "");
    const lit = n.stars ? Math.max(0, Math.min(5, Number(r.fields[n.stars]) || 0)) : 0;
    let stars = "";
    if (n.stars) {
      const star = (i) => {
        const on = i <= lit ? " on" : "";
        const label = `${i} star${i === 1 ? "" : "s"}`;
        if (!rate) return `<span class="v-star${on}" aria-hidden="true">★</span>`;
        return `<button type="button" class="v-star${on}" aria-label="${label}" aria-pressed="${i === lit}"` +
          ` ${doing(v, (el) => rateTile(v, rate, r, i === lit ? 0 : i, el))}>★</button>`;
      };
      stars = `<span class="v-stars" role="group" aria-label="${rate ? "Rate it" : `${lit} of 5 stars`}">` +
        [1, 2, 3, 4, 5].map(star).join("") + `</span>`;
    }
    const runOn = (action) => () => press(v.at.quill, action, { record: r.id, here: v.at, after: v.draw });
    const more = !actions.length ? "" : actions.length === 1
      ? `<button type="button" class="act-chip" ${doing(v, runOn(actions[0]))}>${esc(actions[0].label)}</button>`
      : `<button type="button" class="v-more" aria-label="More" ${doing(v, () => choose(title,
        actions.map((a) => ({ label: a.label, tone: a.tone, run: runOn(a) }))))}>${glyphs.more}</button>`;
    const sub = n.subtitle ? say(v, r, n.subtitle) : "";
    return `<div class="v-tile" ${menuOn(v, r, hash, actions)}>` +
      (hash ? `<a class="v-tile-pic" href="${esc(hash)}">${pic}</a>` : `<span class="v-tile-pic">${pic}</span>`) +
      `<span class="v-tile-text"><span class="title">${esc(title)}</span>` +
      (sub ? `<span class="v-tile-sub">${esc(sub)}</span>` : "") + `</span>` +
      (stars || more ? `<span class="v-tile-foot">${stars}${more}</span>` : "") +
      `</div>`;
  }).join("") + `</div>`;
}

async function rateTile(v, action, record, stars, el) {
  const group = el.closest(".v-stars");
  if (group) {
    group.querySelectorAll(".v-star").forEach((star, i) => {
      star.classList.toggle("on", i < stars);
      star.setAttribute("aria-pressed", String(i + 1 === stars));
    });
  }
  await run(v.at.quill, action, { record: record.id, fields: { stars }, here: v.at, after: v.draw });
}

// The board's lanes, from the tree: the enum's own values and labels unless
// the view names them. A card dragged to another lane is moved with the
// same call the board makes, at once, and the view drawn again after.
function drawLanes(v, n) {
  const modelId = n.model || (n.records[0] && n.records[0].model) || v.at.screen.model;
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
        return `<div class="row v-lane-card" data-id="${esc(r.id)}" ${menuOn(v, r, hash)}${drags ? ' draggable="true"' : ""}>` +
          (hash ? `<a class="main" href="${esc(hash)}"${drags ? ' draggable="false"' : ""}>${text}</a>` : `<span class="main">${text}</span>`) + `</div>`;
      }).join("") : `<div class="nothing">Nothing here</div>`) +
      `</div></div>`;
  }).join("") + `</div>`;
}

function wireLanes(v) {
  if (!canDrag()) return;
  for (const board of v.root.querySelectorAll("[data-lanes]")) {
    const { n, modelId } = v.lanes[Number(board.dataset.lanes)];
    dragLanes(board, {
      card: ".v-lane-card", lane: ".v-lane", group: ".v-lane-cards",
      // The card is already where it was let go; the server agrees, or
      // the view is drawn again as it is.
      drop: async (card, lane, index) => {
        try {
          await api("POST", recordsUrl(modelId, card.dataset.id) + "/move", { fields: { [n.field]: lane }, index });
        } catch (err) { toast(said(err)); }
        v.draw();
      },
    });
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
// cannot carry, and is kept for as long as the view is open. Each is asked
// for once it comes near the screen, a few at a time, so a gallery of
// hundreds asks for the ones being looked at.
const THUMBS_AT_ONCE = 6;

function loadThumbs(v) {
  if (v.thumbWatch) v.thumbWatch.disconnect();
  const waiting = [];
  let busy = 0;
  const next = () => {
    while (busy < THUMBS_AT_ONCE && waiting.length) {
      busy += 1;
      fillThumb(v, waiting.shift()).finally(() => { busy -= 1; next(); });
    }
  };
  const want = (el) => { waiting.push(el); next(); };
  const els = [...v.root.querySelectorAll("[data-thumb-id]")];
  if (!("IntersectionObserver" in window)) { els.forEach(want); return; }
  v.thumbWatch = new IntersectionObserver((seen) => {
    for (const entry of seen) {
      if (!entry.isIntersecting) continue;
      v.thumbWatch.unobserve(entry.target);
      want(entry.target);
    }
  }, { rootMargin: "400px 0px" });
  els.forEach((el) => v.thumbWatch.observe(el));
}

async function fillThumb(v, el) {
  if (!el.isConnected) return;
  const big = (window.devicePixelRatio || 1) > 1.5;
  const asked = Number(el.dataset.thumbSize) || 512;
  const size = big ? asked * 2 : asked;
  const key = `${el.dataset.thumbModel}/${el.dataset.thumbId}/${size}`;
  try {
    if (!v.thumbs.has(key)) {
      const path = recordsUrl(el.dataset.thumbModel, el.dataset.thumbId, "/thumb?size=" + size);
      v.thumbs.set(key, apiRaw("GET", path, { fail: "no picture" })
        .then(async (res) => URL.createObjectURL(await res.blob())));
    }
    const url = await v.thumbs.get(key);
    const img = document.createElement("img");
    img.alt = el.getAttribute("aria-label") || "";
    img.src = url;
    el.replaceChildren(img);
    el.classList.add("has-img");
  } catch {
    el.textContent = el.classList.contains("v-tile-thumb") ? "" : el.getAttribute("aria-label") || "No picture";
    el.classList.add("no-img");
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
