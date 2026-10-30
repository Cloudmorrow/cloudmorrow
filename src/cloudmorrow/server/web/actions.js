/* A Quill's actions, and what they ask the screen to do after they ran.

   An action is declared in a Quill's manifest — a label, a form, what it is
   on — and runs a handler in its code on the server (docs/QUILLCODE.md).
   Nothing here knows what any action does. It draws the button, the form
   from `[actions.fields]` with the record sheet's own widgets, asks first
   when the manifest says to, sends it, and then does the effects the
   handler answered with — the one place every surface-side effect is done:

     toast     a line that goes away
     open      a record's sheet
     go        another screen of the Quill, with its parameters
     confirm   ask, and on yes run another action with the arguments given
     error     the form stays open, with the words under it
     redraw    draw the screen again, which happens after every action anyway

   Three places press one: the record sheet, for every action `on` the
   record's datamodel, from whichever Quill declares it; the bar under a
   Quill's title, for its actions that are on nothing; and a view's
   buttons, forms and rows (kit_view.js). All three come through `press`.

   The menu a thing has — a right-click on a computer, a long press on a
   phone — is here too (`menu`, `contextMenus`), so every kit's is the
   same one, and what a record's holds (`recordChoices`: Open and its
   actions) is said once for every row, card and tile; and which Quills
   edit a file of a given name (`editorsFor`), read off the screens the
   manifests declare. */

import { ApiError, api, app, encodePath, esc, go, parseHash, route, toast } from "./core.js";
import { ask, openSheet } from "./dialog.js";
import { linkTitles, read, segments, widget } from "./kit.js";

// Every installed Quill as the server fitted it to you; quills.js keeps it.
let quills = [];
export function knowQuills(list) { quills = list; }

const quillById = (id) => quills.find((q) => q.id === id);

/**
 * The address of a folder in Files — the first installed grid screen that
 * groups files by share, whichever Quill it is in (kit_grid.js's folder
 * address) — or "" when nothing here shows files.
 */
export function folderInFiles(share, folder = "") {
  for (const quill of quills) {
    for (const screen of quill.screens || []) {
      if (screen.kit !== "grid" || screen.group !== "share") continue;
      return `#/q/${encodeURIComponent(quill.id)}/${encodeURIComponent(screen.id)}/${encodeURIComponent(share)}`
        + (folder ? "/" + encodePath(folder) : "");
    }
  }
  return "";
}

/** The screen's `suffix`: one, or a list; what files it is over. */
const suffixList = (screen) =>
  (typeof screen.suffix === "string" ? [screen.suffix] : (screen.suffix || [])).map(String).filter(Boolean);

/** The screens that edit a file called *name*, by its suffix: `[{quill, screen}]`, in the Quills' order. */
export const editorsFor = (name) => {
  const lower = String(name || "").toLowerCase();
  return quills.flatMap((quill) => (quill.screens || [])
    .filter((screen) => suffixList(screen).some((s) => lower.endsWith(s.toLowerCase())))
    .map((screen) => ({ quill, screen })));
};
const actionIn = (quill, id) => (quill && quill.actions || []).find((a) => a.id === id);
/** An action by its Quill's id and its own. */
export const findAction = (quillId, actionId) => actionIn(quillById(quillId), actionId);

/** Every action on a record of *modelId*, across the Quills: [{quill, action}]. */
export const actionsOn = (modelId) => quills.flatMap((quill) =>
  (quill.actions || []).filter((a) => a.on === modelId).map((action) => ({ quill, action })));
/** A Quill's actions that are on nothing: pressed from its screens. */
// On no record, and not an administrator's settings: those are drawn by the
// Quill's admin screen on its sheet under Administration, nowhere else.
export const loose = (quill) => (quill.actions || []).filter((a) => !a.on && !a.admin);

// The words the server gave, rather than "request failed": its `detail`
// is {kind, message} for anything a Quill's code refused or broke on.
export const said = (err) =>
  (err && err.detail && typeof err.detail === "object" && err.detail.message) || (err && err.message) || "Something went wrong";

// -- the addresses the effects lead to ------------------------------------------------------
/** A screen of a Quill, with parameters for a view: one path segment, encoded twice
    so a value may hold an `&` or a `/` and still come back as it went. */
export function screenAt(quillId, screenId, params = {}) {
  const query = new URLSearchParams(Object.entries(params || {})
    .filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => [k, String(v)])).toString();
  return `#/q/${encodeURIComponent(quillId)}/${encodeURIComponent(screenId)}` +
    (query ? "/" + encodeURIComponent(query) : "");
}

/** Where a record's sheet is: in the Quill and screen on the page when they have
    its datamodel, else on the first screen of a Quill that does. */
function sheetOf(model, id, here) {
  const sheet = (quill, screen) =>
    `#/r/${encodeURIComponent(quill.id)}/${encodeURIComponent(screen.id)}/${encodeURIComponent(model)}/${encodeURIComponent(id)}`;
  if (here && here.quill.models[model]) return sheet(here.quill, here.screen);
  const owner = quills.find((q) => q.screens.some((s) => s.model === model)) ||
    quills.find((q) => q.models[model] && q.screens.length);
  if (!owner) return "";
  return sheet(owner, owner.screens.find((s) => s.model === model) || owner.screens[0]);
}

/** The screen on the page, as quills.js hands it to the kit, or null. */
export function hereNow() {
  const { name, arg } = parseHash();
  if (name !== "q" && name !== "r") return null;
  const [quillId, screenId] = arg.split("/");
  const quill = quillById(quillId);
  const screen = quill && quill.screens.find((s) => s.id === screenId);
  return screen ? { quill, screen } : null;
}

// -- asking ---------------------------------------------------------------------------------
// The sheet, and yes-or-no, are dialog.js's: every screen asks the same way.
/** A list of things to press, in a sheet: a row's actions, a view's menu. */
export function choose(title, choices) {
  const { backdrop, close } = openSheet(
    (title ? `<p class="act-sheet-title">${esc(title)}</p>` : "") +
    choices.map((c, i) => `<button type="button" class="sheet-row${c.tone === "danger" ? " danger" : ""}" data-choice="${i}">${esc(c.label)}</button>`).join("") +
    `<button type="button" class="sheet-row cancel">Cancel</button>`, "act-choose");
  backdrop.addEventListener("click", (event) => {
    const row = event.target.closest("[data-choice], .cancel");
    if (!row) return;
    close();
    if (row.dataset.choice) choices[Number(row.dataset.choice)].run();
  });
}

// -- a menu on a thing ------------------------------------------------------------------------
// The choices a right-click, a long press or the menu key offers on a
// thing: `[{label, run, tone, sep}]`. On a computer a small menu at the
// pointer, with the arrows, Enter and Escape working; on a phone, or with
// no place given, the sheet from the bottom that `choose` is. One at a
// time — opening one closes the last — and what was focused is again after.
let menuOpen = null;
export function closeMenu() { if (menuOpen) menuOpen(); }

export function menu(choices, { x = null, y = null } = {}) {
  closeMenu();
  if (!choices.length) return;
  if (matchMedia("(pointer: coarse)").matches || x === null) {
    choose("", choices.filter((c) => !c.sep));
    return;
  }
  const was = document.activeElement;
  const box = document.createElement("div");
  box.className = "context-menu";
  box.setAttribute("role", "menu");
  box.innerHTML = choices.map((c, i) => (c.sep ? "<hr>" :
    `<button type="button" role="menuitem"${c.tone === "danger" ? ' class="danger"' : ""} data-choice="${i}">${esc(c.label)}</button>`)).join("");
  document.body.appendChild(box);
  box.style.left = `${Math.max(8, Math.min(x, innerWidth - box.offsetWidth - 8))}px`;
  box.style.top = `${Math.max(8, Math.min(y, innerHeight - box.offsetHeight - 8))}px`;
  const items = [...box.querySelectorAll("button")];
  const gone = new AbortController();
  const close = () => {
    box.remove();
    gone.abort();
    menuOpen = null;
    if (was && was.isConnected && typeof was.focus === "function") was.focus();
  };
  menuOpen = close;
  box.addEventListener("click", (event) => {
    const button = event.target.closest("[data-choice]");
    if (!button) return;
    close();
    choices[+button.dataset.choice].run();
  });
  box.addEventListener("keydown", (event) => {
    const i = items.indexOf(document.activeElement);
    if (event.key === "ArrowDown") items[(i + 1) % items.length].focus();
    else if (event.key === "ArrowUp") items[(i - 1 + items.length) % items.length].focus();
    else if (event.key === "Escape" || event.key === "Tab") close();
    else return;
    event.preventDefault();
  });
  const { signal } = gone;
  document.addEventListener("mousedown", (event) => { if (!box.contains(event.target)) close(); }, { capture: true, signal });
  document.addEventListener("scroll", close, { capture: true, signal });
  addEventListener("resize", close, { signal });
  addEventListener("hashchange", close, { signal });
  items[0].focus();
}

// A finger held this long on a thing asks for its menu.
const LONG_PRESS = 500;

/**
 * Menus on the things under *root* that match *selector*, and on the room
 * around them: a right-click on a computer, a long press on a phone.
 * `choicesFor(el, event)` answers the choices for a thing, `blank(event)`
 * for the room; nothing from either leaves the browser's own menu. The
 * press that became a menu is not also a tap on the thing.
 */
export function contextMenus(root, selector, choicesFor, { blank = null } = {}) {
  const open = (event, el) => {
    const choices = el ? choicesFor(el, event) : (blank ? blank(event) : null);
    if (!choices || !choices.length) return false;
    event.preventDefault();
    menu(choices, { x: event.clientX, y: event.clientY });
    return true;
  };
  let pressed = null;   // the press under way: where it began, and its timer
  const end = () => { if (pressed) clearTimeout(pressed.timer); pressed = null; };
  root.addEventListener("contextmenu", (event) => {
    end();
    if (held()) { event.preventDefault(); return; }
    const el = event.target.closest(selector);
    open(event, el && root.contains(el) ? el : null);
  });
  root.addEventListener("pointerdown", (event) => {
    end();
    if (event.pointerType === "mouse" || event.button !== 0) return;
    const el = event.target.closest(selector);
    const { clientX, clientY, target } = event;
    pressed = { x: clientX, y: clientY, timer: setTimeout(() => {
      pressed = null;
      if (open({ clientX, clientY, target, preventDefault() {} }, el && root.contains(el) ? el : null)) heldAt = Date.now();
    }, LONG_PRESS) };
  });
  root.addEventListener("pointermove", (event) => {
    if (pressed && Math.hypot(event.clientX - pressed.x, event.clientY - pressed.y) > 10) end();
  });
  for (const type of ["pointerup", "pointercancel"]) root.addEventListener(type, end);
}

/**
 * The menu a record has wherever it is drawn — a row of a list, a card on
 * a board, a row, card or tile in a view: Open (when *open* is where it
 * opens), the actions the screen declares on it (*extra*, `[{quill,
 * action}]`), then every action `on` its datamodel from whichever Quill
 * declares it — the ones its sheet has — none twice. Nothing is declared
 * for the menu itself: a record's actions are its menu.
 */
export function recordChoices(record, { open = "", extra = [], here = hereNow(), after = null } = {}) {
  const choices = [];
  if (open) choices.push({ label: "Open", run: () => go(open) });
  const seen = new Set();
  const add = ({ quill, action }) => {
    const key = `${quill.id}/${action.id}`;
    if (seen.has(key)) return;
    seen.add(key);
    choices.push({ label: action.label, tone: action.tone, run: () => press(quill, action, { record: record.id, here, after }) });
  };
  extra.forEach(add);
  const own = actionsOn(record.model).filter(({ quill, action }) => !seen.has(`${quill.id}/${action.id}`));
  if (own.length && choices.length) choices.push({ sep: true });
  own.forEach(add);
  return choices;
}

// When a press became a menu: the tap the finger's lift makes — on the
// thing, or on the sheet that has opened over it — and the browser's own
// menu are taken back, once, wherever they land.
let heldAt = 0;
const held = () => heldAt && Date.now() - heldAt < 1500;
document.addEventListener("click", (event) => {
  if (!held()) return;
  heldAt = 0;
  event.preventDefault();
  event.stopPropagation();
}, { capture: true });

// -- the form ---------------------------------------------------------------------------------
// An action's fields are a datamodel's fields, so they are drawn with the
// record sheet's widgets and read back the way it reads them. In the order
// the manifest lists them; short ones side by side in one box, as a sheet
// has them, and a long text or a choice of a few under a label of its own.
const LONG = new Set(["text", "markdown", "json"]);

const needed = (f) => (f.required ? `<span class="act-needed" aria-label="needed">*</span>` : "");

/** The form's fields, filled from *values* and then each field's default. */
export function formFields(fields, values = {}, links = {}, people = []) {
  let out = "";
  let run = [];
  const flush = () => {
    if (run.length) out += `<div class="group fields">${run.join("")}</div>`;
    run = [];
  };
  // Fields marked extra — Cc, Bcc — wait behind one link that names them,
  // where the first of them would be, until it is pressed.
  const extra = fields.filter((f) => f.extra);
  let extraOpen = false;
  for (const f of fields) {
    const value = values[f.name] !== undefined ? values[f.name] : f.default;
    if (f.extra && !extraOpen) {
      flush();
      extraOpen = true;
      out += `<button type="button" class="fields-more">${esc(extra.map((e) => e.label).join(", "))}</button>` +
        `<div class="fields-extra" hidden>`;
    } else if (!f.extra && extraOpen) {
      flush();
      extraOpen = false;
      out += `</div>`;
    }
    if (f.suggest === "people") {
      flush();
      out += `<p class="group-label">${esc(f.label)}${needed(f)}</p>` + peopleWidget(f, value);
    } else if (f.kind === "enum") {
      flush();
      out += `<p class="group-label">${esc(f.label)}${needed(f)}</p>` + segments(f, value);
    } else if (LONG.has(f.kind)) {
      flush();
      const text = f.kind === "json" && value != null ? JSON.stringify(value, null, 2) : value ?? "";
      out += `<p class="group-label">${esc(f.label)}${needed(f)}</p>` +
        `<textarea class="long" data-field="${esc(f.name)}" rows="3" aria-label="${esc(f.label)}">${esc(text)}</textarea>`;
    } else {
      run.push(`<label class="row field kind-${esc(f.kind)}"><span class="main">${esc(f.label)}${needed(f)}</span>${widget(f, value, links)}</label>`);
    }
  }
  flush();
  if (extraOpen) out += `</div>`;
  return out;
}

// -- people ---------------------------------------------------------------------------------
// A field that suggests the server's people as it is typed: names become
// chips, with the entry box after them; what the field sends is the names
// with commas between, so the handler reads it like any string. A name
// that is nobody here is kept as typed — an address outside — and the
// field's `outside` warning is shown while one is in it.
let peopleKnown = null;
export async function peopleList() {
  if (!peopleKnown) {
    peopleKnown = api("GET", "/api/people").catch(() => []);
  }
  return peopleKnown;
}

const splitNames = (text) => String(text || "").split(/[,;\s]+/).map((s) => s.trim()).filter(Boolean);

function peopleWidget(f, value) {
  const names = splitNames(value);
  return `<div class="people-field" data-people="${esc(f.name)}" data-outside="${esc(f.outside || "")}">` +
    `<div class="people-chips" role="list">${names.map(peopleChip).join("")}` +
    `<input type="text" class="people-entry" autocomplete="off" autocapitalize="off" spellcheck="false"` +
    ` aria-label="${esc(f.label)}" placeholder="${names.length ? "" : f.required ? "A name, or an address" : "optional"}"></div>` +
    `<input type="hidden" data-field="${esc(f.name)}" value="${esc(names.join(", "))}">` +
    `<div class="people-suggest" role="listbox" hidden></div>` +
    `<p class="people-note" hidden>${esc(f.outside || "")}</p></div>`;
}

const peopleChip = (name) =>
  `<span class="people-chip${name.includes("@") ? " outside" : ""}" role="listitem" data-name="${esc(name)}">${esc(name)}` +
  `<button type="button" class="people-drop" aria-label="Remove ${esc(name)}">×</button></span>`;

async function wirePeople(field) {
  const entry = field.querySelector(".people-entry");
  const chips = field.querySelector(".people-chips");
  const hidden = field.querySelector("[data-field]");
  const suggest = field.querySelector(".people-suggest");
  const note = field.querySelector(".people-note");
  // The server's people, read once for the page (formFields had them too,
  // for the first drawing; here they are read again, cached, for the offers).
  const people = await peopleList();
  const names = () => [...chips.querySelectorAll(".people-chip")].map((c) => c.dataset.name);
  const sync = () => {
    const typed = entry.value.trim();
    hidden.value = [...names(), ...(typed ? [typed] : [])].join(", ");
    const outside = field.dataset.outside && [...names(), typed].some((n) => n.includes("@"));
    note.hidden = !outside;
  };
  const add = (name) => {
    name = name.trim().replace(/,$/, "");
    if (!name || names().includes(name)) return;
    entry.insertAdjacentHTML("beforebegin", peopleChip(name));
    entry.placeholder = "";
  };
  const offer = () => {
    const typed = entry.value.trim().toLowerCase();
    const have = new Set(names());
    const found = typed ? people.filter((p) => !have.has(p.username) &&
      (p.username.toLowerCase().startsWith(typed) || (p.display_name || "").toLowerCase().includes(typed))) : [];
    suggest.innerHTML = found.slice(0, 8).map((p) =>
      `<button type="button" role="option" data-name="${esc(p.username)}"><b>${esc(p.username)}</b>` +
      (p.display_name && p.display_name !== p.username ? ` <span>${esc(p.display_name)}</span>` : "") + `</button>`).join("");
    suggest.hidden = !found.length;
  };
  const commit = () => {
    for (const part of splitNames(entry.value)) add(part);
    entry.value = "";
    suggest.hidden = true;
    sync();
  };
  entry.addEventListener("input", () => { offer(); sync(); });
  entry.addEventListener("keydown", (event) => {
    if (event.key === "," || event.key === "Enter" || event.key === "Tab" || event.key === " ") {
      if (event.key === "Tab" && !entry.value.trim()) return;
      if (event.key === "Enter" && !suggest.hidden && suggest.firstElementChild) {
        event.preventDefault();
        add(suggest.firstElementChild.dataset.name);
        entry.value = "";
        suggest.hidden = true;
        sync();
        return;
      }
      if (!entry.value.trim() && event.key !== "Tab") { event.preventDefault(); return; }
      event.preventDefault();
      commit();
    } else if (event.key === "Backspace" && !entry.value) {
      const last = chips.querySelector(".people-chip:last-of-type");
      if (last) last.remove();
      sync();
    }
  });
  entry.addEventListener("blur", () => setTimeout(commit, 150));
  suggest.addEventListener("mousedown", (event) => event.preventDefault());
  suggest.addEventListener("click", (event) => {
    const option = event.target.closest("[data-name]");
    if (!option) return;
    add(option.dataset.name);
    entry.value = "";
    suggest.hidden = true;
    sync();
    entry.focus();
  });
  chips.addEventListener("click", (event) => {
    const drop = event.target.closest(".people-drop");
    if (drop) { drop.closest(".people-chip").remove(); sync(); entry.focus(); return; }
    if (event.target === chips) entry.focus();
  });
  sync();
}

/** Choosing a lane of an enum: one lit at a time, as on the sheet. */
export function wireFields(root) {
  for (const field of root.querySelectorAll(".people-field")) wirePeople(field);
  for (const more of root.querySelectorAll(".fields-more")) {
    more.addEventListener("click", () => {
      const hidden = more.nextElementSibling;
      if (hidden) hidden.hidden = false;
      more.remove();
      const first = hidden && hidden.querySelector("input:not([type=hidden]), textarea, select");
      if (first) first.focus();
    });
  }
  for (const group of root.querySelectorAll(".segments")) {
    group.addEventListener("click", (event) => {
      const button = event.target.closest("button");
      if (!button) return;
      for (const other of group.querySelectorAll("button")) {
        const on = other === button && !other.classList.contains("active");
        other.classList.toggle("active", on);
        other.setAttribute("aria-checked", String(on));
      }
    });
  }
}

/** What the form holds, as the action takes it; or the first thing missing, in words. */
export function readFields(root, fields) {
  const out = {};
  for (const f of fields) {
    const el = root.querySelector(`[data-field="${CSS.escape(f.name)}"]`);
    if (!el) continue;
    let value;
    try { value = read(f, el); } catch { return { problem: `${f.label} is not JSON` }; }
    if (typeof value === "string" && f.kind === "string") value = value.trim();
    if (f.required && (value === null || value === "" || value === undefined)) return { problem: `${f.label} is needed` };
    if (value !== null && value !== "" && value !== undefined) out[f.name] = value;
  }
  return { fields: out };
}

/** Titles for the link fields' pickers: the linked records, from the action's own Quill. */
export const linksFor = (quill, fields) => linkTitles(quill, fields.filter((f) => f.kind === "link"));

// -- pressing ---------------------------------------------------------------------------------
/** Press *action* of *quill*: its form first when it has fields, else at once.

    `record` is the id of the record it is on, `args` fills the form (or is
    sent as it is when there is none), `here` is the screen on the page, and
    `after` is called once it is done and nothing took the page somewhere
    else — the view drawing itself again, the sheet showing what changed. */
export async function press(quill, action, { record = "", args = {}, here = hereNow(), after = null } = {}) {
  if (!action) { toast("That is not something you can do here"); return; }
  // The form opens for what is left to fill in; a button whose args answer
  // every field of the action runs it at once, as the terminal does.
  const fields = action.fields || [];
  const unanswered = fields.some((f) => args[f.name] === undefined || args[f.name] === null || args[f.name] === "");
  if (fields.length && unanswered) return openForm(quill, action, { record, args, here, after });
  if (action.confirm && !(await ask(action.confirm, { yes: action.label, tone: action.tone }))) return;
  await run(quill, action, { record, fields: args, here, after });
}

/** Send it, and do what it answers. Resolves to the error it ended in, or "". */
export async function run(quill, action, { record = "", fields = {}, here = null, after = null, showError = null } = {}) {
  let effects;
  try {
    const body = { fields };
    if (action.on && record) body.record = record;
    ({ effects } = await api("POST", `/api/quills/${encodeURIComponent(quill.id)}/actions/${encodeURIComponent(action.id)}`, body));
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return "signed out";
    const text = said(err);
    if (showError) showError(text); else toast(text);
    return text;
  }
  return applyEffects(effects || [], { quill, record, here, after, showError });
}

/** Every effect, in the order the handler gave them. The one place they are done. */
export async function applyEffects(effects, { quill, record = "", here = null, after = null, showError = null }) {
  let error = "";
  let moved = false;
  let redraw = false;
  for (const effect of effects) {
    switch (effect.effect) {
      case "toast":
        toast(effect.text);
        break;
      case "open": {
        const hash = sheetOf(effect.model, effect.id, here);
        if (hash) { moved = moved || hash !== location.hash; go(hash); }
        break;
      }
      case "go": {
        // A view drawn into another page (kit_view.js's embedView): a go
        // to itself is drawn again there, with the parameters it names.
        if (here && here.goHere && effect.screen === here.screen.id) {
          await here.goHere(effect.params);
          return error;
        }
        const hash = screenAt(quill.id, effect.screen, effect.params);
        if (hash === location.hash) redraw = true;
        else { moved = true; go(hash); }
        break;
      }
      case "confirm": {
        const then = actionIn(quill, effect.then);
        if (!then) { toast(`${quill.name} asked for ${effect.then}, which it does not have`); break; }
        if (await ask(effect.text, { yes: then.label, tone: then.tone })) {
          // Its own effects are done by the run it starts, redraw and all.
          await run(quill, then, { record, fields: effect.args || {}, here, after });
          return error;
        }
        break;
      }
      case "error":
        error = effect.text;
        if (showError) showError(effect.text); else toast(effect.text);
        break;
      case "redraw":
        redraw = true;
        break;
      default:
        // An effect from a newer server than this page: nothing to do with it.
        break;
    }
  }
  // After every action the screen it came from is drawn again, unless an
  // effect took the page somewhere else; an error leaves the form as it is,
  // unless the handler asked for the redraw as well.
  if (after && !moved && (!error || redraw)) await after();
  return error;
}

// A form in a sheet: the action's label on it, its fields, and one button
// that is the point of it — the sheet's amber, as Done is a sheet's.
async function openForm(quill, action, { record, args, here, after }) {
  const links = await linksFor(quill, action.fields);
  const people = action.fields.some((f) => f.suggest === "people") ? await peopleList() : [];
  const { backdrop, sheet, close } = openSheet(
    `<form class="act-form record" novalidate>` +
    `<p class="act-sheet-title">${esc(action.label)}</p>` +
    (action.description ? `<p class="act-description">${esc(action.description)}</p>` : "") +
    formFields(action.fields, args, links, people) +
    `<p class="act-error" role="alert" hidden></p>` +
    `<div class="act-buttons"><button type="button" class="act-button" data-cancel>Cancel</button>` +
    `<button type="submit" class="act-button ${action.tone === "danger" ? "danger" : "primary"}">${esc(action.label)}</button></div>` +
    `</form>`, "act-form-sheet");
  const form = sheet.querySelector("form");
  const errorEl = form.querySelector(".act-error");
  const showError = (text) => { errorEl.textContent = text; errorEl.hidden = !text; };
  wireFields(form);
  form.querySelector("[data-cancel]").addEventListener("click", close);
  const first = form.querySelector("input:not([type=checkbox]):not([type=hidden]), textarea, select");
  if (first && matchMedia("(hover: hover)").matches) first.focus();
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const { fields, problem } = readFields(form, action.fields);
    if (problem) { showError(problem); return; }
    // What the form did not ask for, the button still sends.
    const sent = { ...args, ...fields };
    if (action.confirm && !(await ask(action.confirm, { yes: action.label, tone: action.tone }))) return;
    const submit = form.querySelector("[type=submit]");
    submit.disabled = true;
    showError("");
    // A refusal or an `error` effect is said under the fields, and the form
    // stays with what was typed in it; anything else closes it.
    const error = await run(quill, action, { record, fields: sent, here, after, showError });
    submit.disabled = false;
    if (!error) close();
  });
}

// -- where they are drawn ---------------------------------------------------------------------
/** The ghost button for an action; a primary one is left to its caller to fill. */
const chip = (quill, action) =>
  `<button type="button" class="act-chip${action.tone && action.tone !== "neutral" ? " " + esc(action.tone) : ""}"` +
  ` data-quill="${esc(quill.id)}" data-action="${esc(action.id)}">${esc(action.label)}</button>`;

/** The bar under a Quill's title: what it does that is on no record. quills.js
    puts it on every screen of the Quill, after the title. */
export function placeActionBar(quill, main = app.querySelector("main")) {
  const actions = loose(quill);
  if (!actions.length || !main || main.querySelector(":scope > .act-bar")) return;
  const heading = main.querySelector(":scope > .heading");
  if (!heading) return;
  heading.insertAdjacentHTML("afterend",
    `<div class="act-bar" role="toolbar" aria-label="${esc(quill.name)}">${actions.map((a) => chip(quill, a)).join("")}</div>`);
  const bar = main.querySelector(":scope > .act-bar");
  bar.addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    // A view draws itself again after; any other screen does it by its route.
    press(quill, actionIn(quill, button.dataset.action), { here: hereNow(), after: redrawHere });
  });
}

/** Leave off the bar what the screen already has a button for. */
export function hideFromBar(ids) {
  const bar = app.querySelector("main > .act-bar");
  if (!bar) return;
  let left = 0;
  for (const button of bar.querySelectorAll("[data-action]")) {
    button.hidden = ids.has(button.dataset.action);
    if (!button.hidden) left += 1;
  }
  bar.hidden = !left;
}

// What drawing the screen again is, per screen: a view registers its own,
// so an action pressed from the bar redraws it in place; anything else is
// drawn again by its route, as a return to the tab would.
let redrawer = null;
export function onRedrawHere(fn) { redrawer = fn; }
async function redrawHere() {
  if (redrawer && redrawer.alive()) return redrawer.draw();
  route();
}

/** The actions on the record sheet: every one on this datamodel, by Quill. */
export function sheetSection(modelId) {
  const found = actionsOn(modelId);
  if (!found.length) return "";
  const byQuill = new Map();
  for (const { quill, action } of found) {
    if (!byQuill.has(quill.id)) byQuill.set(quill.id, { quill, actions: [] });
    byQuill.get(quill.id).actions.push(action);
  }
  return `<section class="act-section">` + [...byQuill.values()].map(({ quill, actions }) =>
    (byQuill.size > 1 ? `<p class="group-label">${esc(quill.name)}</p>` : "") +
    `<div class="group act-list">${actions.map((a) =>
      `<button type="button" class="row act-row${a.tone === "danger" ? " danger" : ""}" data-quill="${esc(quill.id)}" data-action="${esc(a.id)}">` +
      `<span class="main"><span class="title">${esc(a.label)}</span>${a.description ? `<span class="meta"><span class="preview">${esc(a.description)}</span></span>` : ""}</span>` +
      `</button>`).join("")}</div>`).join("") + `</section>`;
}

/** Wire the sheet's actions: `before` settles what is being typed, `after` redraws. */
export function wireSheetSection(root, { record, here, before, after }) {
  const section = root.querySelector(".act-section");
  if (!section) return;
  section.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const quill = quillById(button.dataset.quill);
    await before();
    press(quill, actionIn(quill, button.dataset.action), { record, here, after });
  });
}
