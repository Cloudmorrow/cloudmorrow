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
   buttons, forms and rows (kit_view.js). All three come through `press`. */

import { ApiError, api, app, esc, go, parseHash, route, toast } from "./core.js";
import { linkTitles, read, segments, widget } from "./kit.js";

// Every installed Quill as the server fitted it to you; quills.js keeps it.
let quills = [];
export function knowQuills(list) { quills = list; }

const quillById = (id) => quills.find((q) => q.id === id);
const actionIn = (quill, id) => (quill && quill.actions || []).find((a) => a.id === id);
/** An action by its Quill's id and its own. */
export const findAction = (quillId, actionId) => actionIn(quillById(quillId), actionId);

/** Every action on a record of *modelId*, across the Quills: [{quill, action}]. */
export const actionsOn = (modelId) => quills.flatMap((quill) =>
  (quill.actions || []).filter((a) => a.on === modelId).map((action) => ({ quill, action })));
/** A Quill's actions that are on nothing: pressed from its screens. */
export const loose = (quill) => (quill.actions || []).filter((a) => !a.on);

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
// The phone's sheet from the bottom, a dialog in the middle on a computer
// (desktop.css): the same `.sheet` the grid's choices are drawn on.
// Tapping outside it, or Escape, is no: `dismissed` hears about it.
function openSheet(inner, className = "", dismissed = () => {}) {
  const backdrop = document.createElement("div");
  backdrop.className = "sheet-backdrop act-backdrop";
  backdrop.innerHTML = `<div class="sheet act-sheet ${className}" role="dialog" aria-modal="true">${inner}</div>`;
  document.body.appendChild(backdrop);
  const close = () => { backdrop.remove(); removeEventListener("keydown", onKey); };
  const dismiss = () => { close(); dismissed(); };
  const onKey = (event) => {
    // Only the sheet on top: a confirm over a form is answered first.
    if (event.key === "Escape" && [...document.querySelectorAll(".act-backdrop")].pop() === backdrop) dismiss();
  };
  addEventListener("keydown", onKey);
  backdrop.addEventListener("click", (event) => { if (event.target === backdrop) dismiss(); });
  return { backdrop, sheet: backdrop.firstElementChild, close };
}

/** Yes or no, in a sheet: resolves true on yes. */
export function ask(text, { yes = "OK", tone = "neutral" } = {}) {
  return new Promise((resolve) => {
    const { backdrop, sheet, close } = openSheet(
      `<p class="act-question">${esc(text)}</p>` +
      `<div class="act-buttons"><button type="button" class="act-button" data-answer="no">Cancel</button>` +
      `<button type="button" class="act-button ${tone === "danger" ? "danger" : "fill"}" data-answer="yes">${esc(yes)}</button></div>`,
      "act-ask", () => resolve(false));
    backdrop.addEventListener("click", (event) => {
      const button = event.target.closest("[data-answer]");
      if (!button) return;
      close();
      resolve(button.dataset.answer === "yes");
    });
    sheet.querySelector('[data-answer="yes"]').focus();
  });
}

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

// -- the form ---------------------------------------------------------------------------------
// An action's fields are a datamodel's fields, so they are drawn with the
// record sheet's widgets and read back the way it reads them. In the order
// the manifest lists them; short ones side by side in one box, as a sheet
// has them, and a long text or a choice of a few under a label of its own.
const LONG = new Set(["text", "markdown", "json"]);

const needed = (f) => (f.required ? `<span class="act-needed" aria-label="needed">*</span>` : "");

/** The form's fields, filled from *values* and then each field's default. */
export function formFields(fields, values = {}, links = {}) {
  let out = "";
  let run = [];
  const flush = () => {
    if (run.length) out += `<div class="group fields">${run.join("")}</div>`;
    run = [];
  };
  for (const f of fields) {
    const value = values[f.name] !== undefined ? values[f.name] : f.default;
    if (f.kind === "enum") {
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
  return out;
}

/** Choosing a lane of an enum: one lit at a time, as on the sheet. */
export function wireFields(root) {
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
  if (action.fields && action.fields.length) return openForm(quill, action, { record, args, here, after });
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
  const { backdrop, sheet, close } = openSheet(
    `<form class="act-form record" novalidate>` +
    `<p class="act-sheet-title">${esc(action.label)}</p>` +
    (action.description ? `<p class="act-description">${esc(action.description)}</p>` : "") +
    formFields(action.fields, args, links) +
    `<p class="act-error" role="alert" hidden></p>` +
    `<div class="act-buttons"><button type="button" class="act-button" data-cancel>Cancel</button>` +
    `<button type="submit" class="act-button ${action.tone === "danger" ? "danger" : "primary"}">${esc(action.label)}</button></div>` +
    `</form>`, "act-form-sheet");
  const form = sheet.querySelector("form");
  const errorEl = form.querySelector(".act-error");
  const showError = (text) => { errorEl.textContent = text; errorEl.hidden = !text; };
  wireFields(form);
  form.querySelector("[data-cancel]").addEventListener("click", close);
  const first = form.querySelector("input:not([type=checkbox]), textarea, select");
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
