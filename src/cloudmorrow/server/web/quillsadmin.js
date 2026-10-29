/* Quills, for an administrator: what the server runs, what people added
   for themselves, and the catalog to add more from — with a sheet for each.

   The third section of Administration, beside who may sign in and their
   circles, under three tabs:

     Server Quills   every one installed here, with whether it is on and
                     whether its code is running; tick some, or all, and
                     update them from the catalog in one go
     User Quills     what the server allows people to add for themselves,
                     what they have asked for, and whose is whose
     Catalog         shelved by category, with what is already here marked

   Choosing a Quill opens its sheet: on a computer beside the list, on a
   phone as a screen of its own. The sheet is every datamodel it uses,
   extends or introduces, the records it comes with, the screens it adds
   and where they appear, what it runs and what it asks for — because
   nothing is added to a server without a yes, and a yes is worth nothing
   unless it was to something written down. An installed Quill's sheet is
   where it is switched on or off for everybody (there is no separate list
   of features: what this server offers is its Quills), updated, installed
   again, or removed.

   Installing puts its tabs in every account's bar; this window's too, at
   once. Updating and reinstalling are the same install again, which keeps
   who it is for. Removing takes the tabs and the jobs and never a record:
   the data was always the people's, not the Quill's.

   A Quill with code of its own says so on the sheet in plain words — the
   commands it runs on this server, as whom, and what it may reach — and,
   once installed, shows what that code is doing (quillservices.js).

   A Quill that brings data new to this server asks which circles get it
   (docs/CIRCLES.md): a tick each, and after the install every ticked circle
   may write it. A circle with `* = write` has it already, and says so. */

import {
  api, app, esc, formatDate, icons, loader, mount, nav, pixelArt, registerScreen, renderRoute, replace, seconds,
  store, toast, wireShell,
} from "./core.js";
import { loadFeatures } from "./features.js";
import { refreshQuills } from "./quills.js";
import { drawRunning } from "./quillservices.js";
import { embedView } from "./kit_view.js";
import { ask, askText } from "./dialog.js";

const quillUrl = (id) => "/api/quills/" + encodeURIComponent(id);
const featureUrl = (id) => "/api/server/features/" + encodeURIComponent(id);
// A computer has the room for the sheet beside the list; the same query
// desktop.css stands the tabs up with.
const wide = () => matchMedia("(min-width: 900px) and (min-height: 600px)").matches;

const TABS = [
  ["server", "Server Quills"],
  ["own", "User Quills"],
  ["catalog", "Catalog"],
];

// Which sheet is open beside the list, and which rows are ticked for an
// update: kept while the page is, so a redraw after an install does not
// close the one you were reading or untick the rest.
let shown = "";
const picked = new Set();
// What the last update in one go said, line by line, drawn again under the
// buttons until the next one.
let lastLog = [];

/** Back to the Quills side of Administration, from a sheet opened as a screen. */
async function backToQuills() {
  replace("#/admin/quills");
  await renderRoute();
}

// How a Quill relates to each datamodel, as a sentence starts.
const HOW = {
  uses: "Uses",
  extends: "Adds fields to",
  introduces: "Introduces",
  "asks for": "Asks to reach",
};
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// -- the Quills side, in the panel ----------------------------------------------------
/** The three tabs and, on a computer, the sheet beside them, into Administration's panel. */
export async function drawQuills(panel) {
  const which = TABS.some(([key]) => key === store.get("admin.quills")) ? store.get("admin.quills") : "server";
  let catalog = null;
  let catalogProblem = "";
  let all;
  let running = [];
  let features = [];
  try {
    [catalog, all, running, features] = await Promise.all([
      api("GET", "/api/quills/catalog").catch((err) => { catalogProblem = err.message; return null; }),
      api("GET", "/api/quills/all"),
      api("GET", "/api/quillservices").catch(() => []),
      api("GET", "/api/server/features").catch(() => []),
    ]);
  } catch (err) {
    panel.innerHTML = `<p class="note">The Quills could not be read: ${esc(err.message)}</p>`;
    return;
  }
  const split = wide();
  panel.classList.toggle("quills-split", split);
  panel.innerHTML = `
    <div class="side">
      <div class="quill-tabs" role="tablist">${TABS.map(([key, label]) =>
        `<button type="button" role="tab" data-tab="${key}" aria-selected="${key === which}"${
          key === which ? ' class="active"' : ""}>${label}</button>`).join("")}</div>
      <div class="quill-list"></div>
    </div>
    ${split ? `<div class="page"><p class="empty"><b>Nothing open</b>Choose a Quill on the left.</p></div>` : ""}`;
  // Another tab is another list: what was open beside the old one closes
  // with it, rather than standing there as if it were still chosen.
  for (const button of panel.querySelectorAll(".quill-tabs button")) {
    button.addEventListener("click", () => {
      if (button.dataset.tab === which) return;
      store.set("admin.quills", button.dataset.tab);
      lastLog = [];
      shown = "";
      drawQuills(panel);
    });
  }
  const ctx = { panel, catalog, catalogProblem, all, running, features, list: panel.querySelector(".quill-list") };
  if (which === "server") await drawServer(ctx);
  else if (which === "own") await drawOwn(ctx);
  else drawCatalog(ctx);
  // The sheet that was open stays open, drawn afresh: it may have changed.
  if (split && shown) await openSheet(ctx, shown);
}

/** What a Quill is called, from the lists already read, for the line under the loader. */
function nameOf(ctx, id) {
  const installed = Object.values(ctx.all || {}).filter(Array.isArray).flat();
  const known = [...installed, ...((ctx.catalog && ctx.catalog.quills) || [])].find((q) => q && q.id === id);
  return (known && known.name) || id;
}

// Which sheet was asked for last: a sheet takes a moment to build — the
// plan comes from the catalog's release — and a row clicked meanwhile wins.
let asked = 0;
// The sheet to open on its settings: the gear on a row was pressed.
let wantSettings = "";

// A gear, eight dots across like the tabs' marks: on the row of a Quill
// that has settings of its own (a screen marked admin), and it opens them.
const GEAR = [
  "...XX...",
  ".X.XX.X.",
  "..XXXX..",
  "XXX..XXX",
  "XXX..XXX",
  "..XXXX..",
  ".X.XX.X.",
  "...XX...",
];
const hasSettings = (quill) => (quill.screens || []).some((s) => s.admin && s.kit === "view");

/** The sheet's settings box, scrolled to: the Quill's own screens under the switch. */
function showSettings(holder) {
  const box = holder && holder.querySelector(".quill-admin-screen");
  const label = box && box.previousElementSibling;
  if (box) (label || box).scrollIntoView({ block: "start", behavior: "smooth" });
}

/** The gear on a row: the Quill's sheet, open on its settings. */
function openSettings(ctx, id) {
  wantSettings = id;
  if (!wide()) { location.hash = "#/adminquill/" + encodeURIComponent(id) + "/settings"; return; }
  openSheet(ctx, id);
}

/** Open a Quill's sheet: beside the list on a computer, as its own screen on a phone.
    Whatever was there goes at once. A Quill on the server is on the list already,
    so its head — name, what it says of itself, the version it is at, its switch
    and its settings — is drawn from that at once, and the loader stands only
    under it, for what the catalog has to be asked about. One the list does not
    know gets the loader alone until the sheet is built. */
async function openSheet(ctx, id) {
  if (!wide()) { location.hash = "#/adminquill/" + encodeURIComponent(id); return; }
  shown = id;
  for (const row of ctx.panel.querySelectorAll(".quill-row[data-id]")) {
    row.classList.toggle("current", row.dataset.id === id);
  }
  const page = ctx.panel.querySelector(".page");
  if (!page) return;
  const turn = ++asked;
  const after = async ({ removed } = {}) => {
    if (removed) shown = "";
    await drawQuills(ctx.panel);
  };
  const listed = (ctx.all.server || []).find((q) => q.id === id) || null;
  const feature = (ctx.features || []).find((f) => f.key === id) || null;
  const entry = (ctx.catalog && ctx.catalog.quills.find((q) => q.id === id)) || null;
  let here = null;
  if (listed) {
    const name = listed.name || listed.id;
    const newer = Boolean(entry && entry.update_available === true);
    page.innerHTML = `<div class="quill-sheet">${sheetHead({ name, plan: listed, installed: listed.version, newer, feature, here: listed })}` +
      `<div class="quill-rest">${loader(`Reading ${name}`)}</div></div>`;
    const holder = page.firstElementChild;
    wireSwitch(holder, { id, name, after });
    if (wantSettings === id) {
      wantSettings = "";
      showSettings(page);
    }
    // The settings screens are the Quill's own code drawing its datamodels,
    // which the list does not carry: one quick read of the Quill, and they
    // are live, long before the catalog answers.
    here = await api("GET", quillUrl(id)).catch(() => null);
    if (turn !== asked) return;
    if (here) wireSettings(holder, here);
  } else {
    page.innerHTML = loader(`Reading ${nameOf(ctx, id)}`);
  }
  const sheet = await buildSheet(id, { catalog: ctx.catalog, feature, here });
  if (turn !== asked) return;
  if (!sheet) {
    if (listed) {
      page.querySelector(".quill-rest").innerHTML = `<p class="shelf-note warn">The rest of the sheet could not be read.</p>`;
      return;
    }
    shown = "";
    page.innerHTML = `<p class="empty"><b>Nothing open</b>Choose a Quill on the left.</p>`;
    return;
  }
  if (listed) {
    // The head stays as drawn, its settings live; only the facts line is
    // said again with what the catalog knows, and the rest fills in.
    const holder = page.firstElementChild;
    holder.querySelector(".quill-facts").innerHTML = sheet.facts;
    holder.querySelector(".quill-rest").innerHTML = sheet.body;
    sheet.wireBody(holder, after);
    return;
  }
  page.innerHTML = `<div class="quill-sheet">${sheet.head}<div class="quill-rest">${sheet.body}</div></div>`;
  sheet.wire(page.firstElementChild, after);
  if (wantSettings === id) {
    wantSettings = "";
    showSettings(page);
  }
}

/** A row that opens a sheet: a click, or Enter on it, that is not on a control in it. */
function wireRow(ctx, row) {
  row.addEventListener("click", (event) => {
    if (event.target.closest("input, button, a")) return;
    openSheet(ctx, row.dataset.id);
  });
  const gear = row.querySelector(".quill-gear");
  if (gear) gear.addEventListener("click", () => openSettings(ctx, row.dataset.id));
  row.addEventListener("keydown", (event) => {
    if (event.target !== row || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    openSheet(ctx, row.dataset.id);
  });
}

// -- Server Quills: everything installed, and updating it -------------------------------
// What a Quill is doing, in one word for the chip: off, or on and — when
// it has code of its own — running, restarting or stopped.
function stateOf(quill, running) {
  if (quill.enabled === false) return ["off", ""];
  const code = running.find((r) => r.id === quill.id);
  const live = code ? (code.services || []).filter((s) => !s.scheduled) : [];
  if (!live.length) return ["on", "good"];
  if (live.some((s) => s.state === "stopped")) return ["stopped", "warn"];
  if (live.some((s) => s.state === "restarting")) return ["restarting", "warn"];
  return ["running", "good"];
}
const stateChip = ([state, tone]) => `<span class="quill-chip run-state ${tone}">${esc(state)}</span>`;

// Where an installed Quill stands against the catalog (routes/quills.py):
// a newer release there, up to date, or no telling — the entry names no
// release, or the Quill came from a source of its own.
function standing(quill, catalog) {
  const entry = catalog && catalog.quills.find((q) => q.id === quill.id);
  if (!entry && catalog && (quill.origin || {}).catalog) return { entry: null, newer: false, said: "no longer in the catalog" };
  if (!entry) return { entry: null, newer: false, said: fromWhere(quill) };
  if (entry.update_available === true) return { entry, newer: true, said: `newer in the catalog: ${entry.ref}` };
  if (entry.update_available === false) return { entry, newer: false, said: "up to date" };
  return { entry, newer: null, said: fromWhere(quill) };
}
function fromWhere(quill) {
  const origin = quill.origin || {};
  if (origin.dev) return "from a folder, with cm quill dev";
  if (!origin.catalog && origin.repo) return `from ${origin.repo}`;
  return "from the catalog";
}

async function drawServer(ctx) {
  const { catalog, all, running, list } = ctx;
  const server = all.server || [];
  const stood = new Map(server.map((q) => [q.id, standing(q, catalog)]));
  // What "update all" would do: every Quill the catalog has a newer release
  // of, and every one there is no telling about, which is updated by
  // installing it again.
  const updatable = server.filter((q) => stood.get(q.id).entry && stood.get(q.id).newer !== false).map((q) => q.id);
  const newer = server.filter((q) => stood.get(q.id).newer === true).length;
  for (const id of [...picked]) if (!stood.get(id) || !stood.get(id).entry) picked.delete(id);
  const broken = Object.entries(all.broken || {});

  list.innerHTML = `
    <p class="note">Every Quill on this server. Its tabs are in everybody's bar while it is on;
      one with code of its own says whether that is running. Tick some and update them, or
      update all: each is installed again from the catalog, for the same people.</p>
    ${ctx.catalogProblem ? `<p class="shelf-note warn">The catalog could not be read: ${esc(ctx.catalogProblem)}</p>` : ""}
    <div class="quill-actions">
      <button type="button" class="chip-button update-picked" disabled>Update selected</button>
      <button type="button" class="chip-button update-all"${updatable.length ? "" : " disabled"}>${
        !updatable.length ? "Everything is up to date"
          : newer ? `Update all · ${newer} newer` : "Update all"}</button>
    </div>
    <div class="update-log"${lastLog.length ? "" : " hidden"}>${lastLog.map(([text, tone]) =>
      `<p class="${tone}">${esc(text)}</p>`).join("")}</div>
    ${server.length ? `<div class="group">${server.map((q) => serverRow(q, stood.get(q.id), running)).join("")}</div>`
      : `<p class="empty"><b>No Quills yet</b>Add some from the catalog.</p>`}
    ${broken.length ? `<p class="group-label">Could not load</p>
    <div class="group">${broken.map(([key, why]) => `<div class="row quill-row"><span class="main">
      <span class="title">${esc(key)}</span><span class="meta"><span class="preview">${esc(why)}</span></span></span>
      <span class="quill-chip run-state warn">broken</span></div>`).join("")}</div>` : ""}`;

  const pickedButton = list.querySelector(".update-picked");
  const sayPicked = () => {
    pickedButton.disabled = !picked.size;
    pickedButton.textContent = picked.size ? `Update selected · ${picked.size}` : "Update selected";
  };
  sayPicked();
  for (const row of list.querySelectorAll(".quill-row[data-id]")) {
    wireRow(ctx, row);
    const box = row.querySelector("input.pick");
    if (!box) continue;
    box.addEventListener("change", () => {
      if (box.checked) picked.add(row.dataset.id); else picked.delete(row.dataset.id);
      sayPicked();
    });
  }
  pickedButton.addEventListener("click", () => updateMany(ctx, server.filter((q) => picked.has(q.id))));
  list.querySelector(".update-all").addEventListener("click", () =>
    updateMany(ctx, server.filter((q) => updatable.includes(q.id))));
}

function serverRow(quill, stood, running) {
  const pick = stood.entry
    ? `<input type="checkbox" class="pick" aria-label="Select ${esc(quill.name)}"${picked.has(quill.id) ? " checked" : ""}>`
    : `<input type="checkbox" class="pick" disabled aria-label="${esc(quill.name)} is not in the catalog">`;
  return `<div class="row quill-row pick-row${quill.id === shown ? " current" : ""}" data-id="${esc(quill.id)}" role="button" tabindex="0">
    ${pick}
    <span class="main"><span class="title">${esc(quill.name || quill.id)}</span>
    <span class="meta"><span class="preview">v${esc(quill.version)} · ${esc(stood.said)}</span></span></span>
    ${hasSettings(quill) ? `<button type="button" class="quill-gear" title="Settings" aria-label="Settings of ${esc(quill.name || quill.id)}">${pixelArt(GEAR)}</button>` : ""}
    ${stateChip(stateOf(quill, running))}${icons.chevronRight}</div>`;
}

/** Install each of *quills* again from the catalog, one after the other, saying
    how each went; who each is for goes with it. */
async function updateMany(ctx, quills) {
  if (!quills.length) return;
  const names = quills.map((q) => q.name || q.id);
  const sure = await ask(`Update ${listed(names)}?\n\nEach is installed again from the catalog. `
    + "Its tabs stay for the same people; nothing anybody wrote is touched.");
  if (!sure) return;
  for (const button of ctx.list.querySelectorAll(".quill-actions button")) button.disabled = true;
  const log = ctx.list.querySelector(".update-log");
  log.hidden = false;
  log.innerHTML = "";
  lastLog = [];
  // A line on the page and in what is kept of it, so the redraw after says
  // how each went rather than that each was being updated.
  const line = (text, tone = "") => {
    const kept = [text, tone];
    lastLog.push(kept);
    const p = document.createElement("p");
    const say = (said, how) => {
      kept[0] = said;
      kept[1] = how;
      p.className = how;
      p.textContent = said;
    };
    say(text, tone);
    log.append(p);
    return say;
  };
  for (const quill of quills) {
    const name = quill.name || quill.id;
    const say = line(`Updating ${name}…`, "muted");
    try {
      const plan = await installAgain(quill);
      say(plan.version === quill.version
        ? `${name} v${quill.version} installed again`
        : `${name} v${quill.version} → v${plan.version}`, "good");
    } catch (err) {
      say(`${name}: ${err.message}`, "bad");
    }
  }
  picked.clear();
  await refreshQuills();
  await drawQuills(ctx.panel);
}

/** The same install again: from the catalog by id, or from the source it came
    from, for the people it is for. */
function installAgain(quill) {
  const origin = quill.origin || {};
  const audience = quill.audience || { circles: [], people: [] };
  const body = origin.catalog || !origin.repo
    ? { id: quill.id, audience }
    : { source: origin.repo, ref: origin.ref || "", audience };
  return api("POST", "/api/quills", body);
}

// -- User Quills: what the server allows, what was asked for, whose is whose ----------------
const POLICY = [
  ["personal_quills", "Quills of people's own", {
    on: "Anybody may add one for themselves",
    ask: "Only through a request an administrator approves",
    off: "Nobody; the ones there are go dark",
  }],
  ["personal_quill_code", "May run code", { on: "In the sandbox, as its owner", off: "Declared Quills only" }],
  ["personal_quill_sharing", "May be shared", { on: "With people who say yes", off: "Yours alone" }],
  ["personal_quill_create", "May be made", { on: "From a folder, a source, a fork, an assistant", off: "The catalog only" }],
];

async function drawOwn(ctx) {
  const { panel, all, list } = ctx;
  const requests = all.requests || [];
  const personal = all.personal || [];
  list.innerHTML = `
    <p class="note">What this server allows (docs/SHARING.md), for everybody; an account's page says it
      again for one person. A Quill somebody adds for themselves is on their shelf, its own data the
      Quill's and nobody else's until they share it; it changes nothing other people see.</p>
    <div class="group policy">${POLICY.map(([key, label, words]) => `<label class="row">
      <span class="main"><span class="title">${esc(label)}</span>
      <span class="meta"><span class="preview">${esc(words[all.policy[key]] || "")}</span></span></span>
      <select data-key="${key}" aria-label="${esc(label)}">${Object.keys(words).map((v) =>
        `<option value="${v}"${all.policy[key] === v ? " selected" : ""}>${v}</option>`).join("")}</select></label>`).join("")}</div>
    ${requests.length ? `<p class="group-label">Asked for</p>
    <p class="shelf-note">Approve for everyone, for the one who asked, or decline with a word. A circle is
      chosen on the Quill's own sheet afterwards, under its audience.</p>
    <div class="group">${requests.map((r) => `<div class="row request-row" data-id="${r.id}" data-who="${esc(r.username)}">
      <span class="main"><span class="title">${esc(r.username)} asks for ${esc(r.kind === "promote" ? `${r.quill} to be promoted` : r.quill || r.source)}</span>
      <span class="meta"><span class="preview">${esc(r.note || "")}</span></span></span>
      <span class="own-buttons">
        <button type="button" class="quill-chip on everyone">For everyone</button>
        ${r.kind === "promote" ? "" : `<button type="button" class="quill-chip asker">For ${esc(r.username)}</button>`}
        <button type="button" class="quill-chip decline">Decline</button></span></div>`).join("")}</div>` : ""}
    <p class="group-label">Whose</p>
    ${personal.length ? `<div class="group">${personal.map((q) => {
      const holders = q.holders || [];
      const others = holders.filter((h) => h !== q.owner);
      const gone = q.owner_active === false ? " · its owner's account is gone: promote it, or remove it" : "";
      const left = q.owner_left ? ` · ${esc(q.owner)} took it off their shelf; it stands with ${esc(listed(others)) || "nobody"}` : "";
      return `<div class="row own-row" data-owner="${esc(q.owner)}" data-quill="${esc(q.id)}" data-name="${esc(q.name)}">
        <span class="main"><span class="title">${esc(q.name)} <span class="meta-inline">v${esc(q.version)}</span></span>
        <span class="meta"><span class="preview">${esc(q.owner)}'s${others.length && !q.owner_left ? `, shared with ${esc(others.join(", "))}` : ""}${
          q.code ? " · runs code, as each of them" : ""}${left}${gone}</span></span></span>
        <span class="own-buttons">
          <button type="button" class="quill-chip on promote">Promote</button>
          <button type="button" class="quill-chip ${q.enabled ? "switch-off" : "switch-on"}">${q.enabled ? "Switch off" : "Switch on"}</button>
          <button type="button" class="quill-chip remove-own">Remove</button>
        </span></div>`;
    }).join("")}</div>
    <p class="shelf-note">Promoting makes it the server's, for everyone: every record of its own datamodels —
      the owner's and the people's it was shared with — moves with it. Switching one off takes it from
      everybody who has it until it is switched on again. Removing it takes it off the server, off
      every shelf it is on; its records stay unless you untick them.</p>`
      : `<p class="shelf-note">Nobody has added a Quill of their own yet.</p>`}`;

  for (const select of list.querySelectorAll(".policy select")) {
    select.addEventListener("change", async () => {
      try {
        await api("PUT", "/api/quills/policy", { [select.dataset.key]: select.value });
        toast("Saved");
        await drawQuills(panel);
      } catch (err) { toast(err.message); }
    });
  }
  const redo = async (fn, done) => {
    try { await fn(); if (done) toast(done); await refreshQuills(); await drawQuills(panel); } catch (err) { toast(err.message); }
  };
  for (const row of list.querySelectorAll(".request-row")) {
    const { id, who } = row.dataset;
    const url = `/api/quills/requests/${id}`;
    row.querySelector(".everyone").addEventListener("click", () => redo(() => api("POST", url + "/approve", {}), "Installed for everyone"));
    row.querySelector(".asker")?.addEventListener("click", () => redo(
      () => api("POST", url + "/approve", { audience: { people: [who] } }), `Installed for ${who}`));
    row.querySelector(".decline").addEventListener("click", async () => {
      const note = await askText(`Decline ${who}'s request? A word back, if you like:`);
      if (note === null) return;
      redo(() => api("POST", url + "/decline", { note }), "Declined");
    });
  }
  for (const row of list.querySelectorAll(".own-row")) {
    const { owner, quill, name } = row.dataset;
    row.querySelector(".promote").addEventListener("click", async () => {
      if (!await ask(`Promote ${owner}'s ${name}, for everyone? Every record of its datamodels moves to the server's.`)) return;
      redo(() => api("POST", "/api/quills/promote", { owner, id: quill }), `${name} is the server's now`);
    });
    const key = `~${owner}.${quill}`;
    row.querySelector(".switch-off")?.addEventListener("click", () => redo(
      () => api("PATCH", featureUrl(key), { enabled: false })));
    row.querySelector(".switch-on")?.addEventListener("click", () => redo(
      () => api("PATCH", featureUrl(key), { enabled: true })));
    row.querySelector(".remove-own").addEventListener("click", () => removeTheirs(row, redo));
  }
}

// Somebody's own Quill, off the server and every shelf it is on: what it
// brought is offered the way a server Quill's is, ticked to keep.
async function removeTheirs(row, redo) {
  const { owner, quill, name } = row.dataset;
  const url = `/api/quills/personal/${encodeURIComponent(owner)}/${encodeURIComponent(quill)}`;
  const gone = (drop) => redo(() => api("DELETE", url + (drop.length ? "?drop=" + encodeURIComponent(drop.join(",")) : "")),
    `${owner}'s ${name} is removed`);
  let brought = [];
  try { brought = await api("GET", url + "/brought"); } catch (err) { toast(err.message); return; }
  if (!brought.length) {
    if (!await ask(`Remove ${owner}'s ${name}?\n\nIts tabs and jobs go, for everybody who has it. `
      + "Nothing anybody wrote is deleted: the records stay, and are there again if it comes back.")) return;
    return gone([]);
  }
  const group = row.closest(".group");
  group.insertAdjacentHTML("afterend", removeSheet(`${owner}'s ${name}`, brought));
  group.hidden = true;
  const sheet = group.nextElementSibling;
  sheet.querySelector(".cancel").addEventListener("click", () => { sheet.remove(); group.hidden = false; });
  sheet.querySelector(".confirm").addEventListener("click", () =>
    gone([...sheet.querySelectorAll("input[type=checkbox]:not(:checked)")].map((b) => b.value)));
}

// -- the catalog ----------------------------------------------------------------------
function drawCatalog(ctx) {
  const { catalog, list } = ctx;
  if (!catalog) {
    list.innerHTML = `<p class="note">The catalog could not be read: ${esc(ctx.catalogProblem)}</p>`;
    return;
  }
  const shelves = [...catalog.categories];
  const known = new Set(shelves.map((c) => c.id));
  if (catalog.quills.some((q) => !known.has(q.category))) {
    shelves.push({ id: "", label: "Other", description: "" });
  }
  list.innerHTML = `
    <p class="note">Quills for your cloud, from the Quill Catalog. Each one
      says what it adds before it is added, and its tabs appear for everybody
      here once it is.</p>` +
    shelves.map((shelf) => {
      const here = catalog.quills.filter((q) => (known.has(q.category) ? q.category : "") === shelf.id);
      if (!here.length) return "";
      return `<p class="group-label">${esc(shelf.label)}</p>` +
        (shelf.description ? `<p class="shelf-note">${esc(shelf.description)}</p>` : "") +
        `<div class="group">${here.map(catalogRow).join("")}</div>`;
    }).join("");
  for (const row of list.querySelectorAll(".quill-row[data-id]")) wireRow(ctx, row);
}

function catalogRow(q) {
  const state = q.update_available
    ? `<span class="quill-chip new">update</span>`
    : q.installed_version ? `<span class="quill-chip on">v${esc(q.installed_version)}</span>`
    : `<span class="quill-chip">Add</span>`;
  const by = q.publisher ? ` · ${q.publisher}` : "";
  return `<div class="row quill-row${q.id === shown ? " current" : ""}" data-id="${esc(q.id)}" role="button" tabindex="0">
    <span class="main"><span class="title">${esc(q.name || q.id)}</span>
    <span class="meta"><span class="preview">${esc((q.summary || "") + by)}</span></span></span>
    ${state}${icons.chevronRight}</div>`;
}

// -- the sheet ------------------------------------------------------------------------
/** A Quill's sheet, as a screen of its own: the phone's way, and a link's. */
async function renderQuill(arg) {
  // #/adminquill/<id>, or #/adminquill/<id>/settings from the gear on a row.
  const [id, part] = arg.split("/");
  if (part === "settings") wantSettings = id;
  // A computer has the sheet beside the list; a link to one lands there.
  if (wide()) {
    shown = id;
    return backToQuills();
  }
  // The screen is there before anything is read: the bar, and the loader
  // where the sheet will be, so the row tapped is answered at once.
  mount(nav({ back: "#/admin/quills", backLabel: "Quills", title: "Quill" }) + `
    <main class="quill-sheet">${loader("Reading the Quill")}</main>`);
  wireShell();
  const turn = ++asked;
  const me = await api("GET", "/api/auth/me");
  if (!me.is_admin) {
    toast("Administration is for administrators");
    replace("#/me");
    return renderRoute();
  }
  const sheet = await buildSheet(id, { me });
  if (turn !== asked) return;
  if (!sheet) return backToQuills();
  mount(nav({ back: "#/admin/quills", backLabel: "Quills", title: sheet.name }) + `
    <main class="quill-sheet">${sheet.head}<div class="quill-rest">${sheet.body}</div></main>`);
  wireShell();
  sheet.wire(app.querySelector("main"), backToQuills);
  if (wantSettings === id) {
    wantSettings = "";
    showSettings(app.querySelector("main"));
  }
}

/** The sheet for one Quill — its name, the HTML in two halves (the head: name,
    lede, facts and settings; the body: the rest), and what wires each into a
    holder — or null, with a word said, when there is no such Quill. What is
    known already — the catalog, the switch, the Quill itself — is taken rather
    than read again. *after(what)* is called once an install, update or removal
    has gone through. */
async function buildSheet(id, { me = null, catalog = undefined, feature = null, here = null } = {}) {
  if (!me) me = await api("GET", "/api/auth/me");
  // A Quill in the catalog is described fresh from it — what installing
  // would add now. One installed from a source has only what it added.
  let plan;
  let entry = null;
  // A catalog that cannot be read leaves an installed Quill its sheet — and
  // its Remove — described from what it added.
  if (catalog === undefined) {
    try { catalog = await api("GET", "/api/quills/catalog"); } catch { catalog = null; }
  }
  try {
    entry = (catalog && catalog.quills.find((q) => q.id === id)) || null;
    plan = entry ? await api("POST", "/api/quills/plan", { id }) : { ...(here || await api("GET", quillUrl(id))), from_source: true };
    if (plan.from_source) plan.installed_version = plan.version;
    if (plan.installed_version) {
      // Who it is for, where it came from, and whether it is on: on the
      // Quill itself and the server's switch, not in the catalog.
      [here, feature] = await Promise.all([
        here || api("GET", quillUrl(id)).catch(() => null),
        feature || api("GET", "/api/server/features").then((rows) => rows.find((f) => f.key === id) || null).catch(() => null),
      ]);
      if (here) plan.audience = here.audience;
    }
  } catch (err) {
    toast(err.message);
    return null;
  }
  const installed = plan.installed_version;
  const name = plan.name || plan.id;
  // The data it brings that no circle names yet, and the circles to give it to.
  const fresh = installed ? [] : (plan.data || []).filter((d) => d.new);
  let circles = [];
  try { circles = await api("GET", "/api/circles"); } catch { circles = []; }
  const audience = plan.audience || { circles: [], people: [] };
  // A newer release: the catalog's copy says a version the installed one is
  // not, or the catalog names a release it was not installed from.
  const newer = Boolean(installed && entry && (plan.version !== installed || entry.update_available === true));
  const origin = (here && here.origin) || {};
  // Installing again is from the catalog, or from the source it came from;
  // a folder sent with `cm quill dev` has to be sent again from there, and
  // one the catalog has dropped cannot be had again at all.
  const again = installed && (entry || (!origin.dev && !origin.catalog && origin.repo));
  const dropped = Boolean(installed && catalog && !entry && origin.catalog);

  const facts = sheetFacts({ plan, installed, newer });
  const head = sheetHead({ name, plan, installed, newer, feature, here });
  const body = `
      ${installed ? `<p class="group-label">Version</p><div class="group sheet-actions">
        ${standingRow(plan, installed, entry, newer, origin)}
        <div class="sheet-buttons">
          ${newer ? `<button class="act-button primary update-quill" type="button">Update to v${esc(plan.version)}</button>` : ""}
          ${again ? `<button class="act-button reinstall-quill" type="button">Reinstall v${esc(installed)}</button>` : ""}
          <button class="act-button danger remove-quill" type="button">Remove ${esc(name)}</button>
        </div>
      </div>
      ${again ? "" : dropped
        ? `<p class="shelf-note">The catalog no longer has ${esc(name)}, so it cannot be installed again or updated: remove it, and install what replaced it from the catalog.</p>`
        : `<p class="shelf-note">Installed from a folder with <code>cm quill dev</code>: to install it again, send it from there.</p>`}
      <div class="quill-running"></div>` : ""}
      ${sections(plan, me)}
      ${whoGetsIt(fresh, circles)}
      ${whoItIsFor(circles, audience, installed)}
      ${adoptSheet(plan.adopt || [])}
      ${installed ? "" : `<div class="sheet-buttons"><button class="act-button primary add-quill" type="button">Install ${esc(name)}</button></div>`}`;

  const wireHead = (holder, after) => {
    wireSwitch(holder, { id, name, after });
    if (here) wireSettings(holder, here);
  };
  const wireBody = (holder, after) => {
    const running = holder.querySelector(".quill-running");
    if (running) drawRunning(running, id);
    const done = async (message, what) => {
      await refreshQuills();
      toast(message);
      await after(what);
    };
    const change = holder.querySelector(".change-audience");
    if (change) change.addEventListener("click", async () => {
      const forCircles = [...holder.querySelectorAll(".who-it-is-for input:checked")].map((b) => b.value);
      try {
        await api("PUT", quillUrl(id) + "/audience", { circles: forCircles, people: audience.people || [] });
        await refreshQuills();
        toast(forCircles.length ? `${name} is for ${forCircles.length} circle${forCircles.length === 1 ? "" : "s"}` : `${name} is for everyone`);
      } catch (err) { toast(err.message); }
    });

    const install = holder.querySelector(".add-quill");
    if (install) install.addEventListener("click", async () => {
      install.disabled = true;
      install.textContent = "Installing…";
      try {
        const forCircles = [...holder.querySelectorAll(".who-it-is-for input:checked")].map((b) => b.value);
        const adopt = [...holder.querySelectorAll(".adopt-sheet input:checked")].map((b) => b.value);
        await api("POST", "/api/quills", { id, audience: { circles: forCircles, people: [] }, adopt });
        const ticked = [...holder.querySelectorAll(".who-gets-it input:checked:not(:disabled)")];
        for (const tick of ticked) {
          for (const d of fresh) {
            await api("PUT", `/api/circles/${encodeURIComponent(tick.value)}/rules/${encodeURIComponent(d.id)}`,
              { access: "write" });
          }
        }
        // The tabs are in every account's bar from now; this one's at once.
        await done(`${name} is installed`);
      } catch (err) {
        install.disabled = false;
        install.textContent = `Install ${name}`;
        toast(err.message);
      }
    });

    // Updating and installing again are one and the same install, for the
    // same people: only the words, and the version that comes of it, differ.
    const installOnceMore = async (button, verb) => {
      const was = button.textContent;
      // Every button that was live goes quiet until it is over; "Up to
      // date" was not live, and stays so.
      const live = [...holder.querySelectorAll(".sheet-actions button:not(:disabled)")];
      for (const b of live) b.disabled = true;
      button.textContent = `${verb}…`;
      try {
        const result = await installAgain({ id, origin, audience });
        await done(result.version === installed ? `${name} v${installed} is installed again`
          : `${name} is updated to v${result.version}`);
      } catch (err) {
        for (const b of live) b.disabled = false;
        button.textContent = was;
        toast(err.message);
      }
    };
    const update = holder.querySelector(".update-quill");
    if (update) update.addEventListener("click", () => installOnceMore(update, "Updating"));
    const reinstall = holder.querySelector(".reinstall-quill");
    if (reinstall) reinstall.addEventListener("click", async () => {
      if (!await ask(`Install ${name} v${installed} again?\n\nIts tabs stay for the same people; nothing anybody wrote is touched.`)) return;
      installOnceMore(reinstall, "Installing");
    });

    const remove = holder.querySelector(".remove-quill");
    if (remove) remove.addEventListener("click", async () => {
      let brought = [];
      try { brought = await api("GET", quillUrl(id) + "/brought"); } catch (err) { toast(err.message); return; }
      const gone = async (drop) => removeQuill(id, name, drop, (message) => done(message, { removed: true }));
      if (!brought.length) {
        const sure = await ask(
          `Remove ${name}?\n\nIts tabs and jobs go, for everybody. Nothing anybody `
          + "wrote is deleted: the records stay, and are there again if it comes back.",
        );
        if (!sure) return;
        return gone([]);
      }
      // What it brought, each ticked to keep; the administrator unticks what goes.
      const box = remove.closest(".sheet-actions");
      box.insertAdjacentHTML("afterend", removeSheet(name, brought));
      box.hidden = true;
      const sheet = holder.querySelector(".remove-sheet");
      sheet.querySelector(".cancel").addEventListener("click", () => {
        sheet.remove();
        box.hidden = false;
      });
      sheet.querySelector(".confirm").addEventListener("click", async () => {
        const drop = [...sheet.querySelectorAll("input[type=checkbox]:not(:checked)")].map((b) => b.value);
        await gone(drop);
      });
    });
  };
  const wire = (holder, after) => { wireHead(holder, after); wireBody(holder, after); };
  return { name, head, body, facts, wire, wireHead, wireBody };
}

/** The sheet's head: the name, what the Quill says of itself, the facts line,
    and — installed — its settings. Drawn from the list alone when a row is
    clicked, and from the plan on a phone. */
function sheetHead({ name, plan, installed, newer, feature, here }) {
  return `
      <h1 class="large">${esc(name)}</h1>
      <p class="quill-lede">${esc(plan.summary || "")}</p>
      <p class="quill-facts">${sheetFacts({ plan, installed, newer })}</p>
      ${installed ? settingsBox(name, feature, here) : ""}`;
}

/** The facts line: the version, who publishes it, its licence, and the chips
    saying it is installed and whether the catalog has a newer one. */
function sheetFacts({ plan, installed, newer }) {
  return [
    `v${esc(plan.version)}`, esc(plan.publisher || ""), esc(plan.license || ""),
    installed ? `<span class="quill-chip on">v${esc(installed)} installed</span>` : "",
    newer ? `<span class="quill-chip new">v${esc(plan.version)} in the catalog</span>` : "",
  ].filter(Boolean).join(" · ");
}

/** The server's switch on the sheet, live: off takes the Quill's tabs out
    of every client, and this window's bar is drawn again at once. */
function wireSwitch(holder, { id, name, after }) {
  const box = holder.querySelector(".server-switch input");
  if (!box) return;
  box.addEventListener("change", async () => {
    box.disabled = true;
    try {
      const turned = await api("PATCH", featureUrl(id), { enabled: box.checked });
      // "Everywhere" includes this window: the bar is drawn from what
      // this account has, and that has just changed.
      await loadFeatures();
      await refreshQuills();
      toast(turned.enabled ? `${name} is on.` : `${name} is off — its tabs are gone everywhere.`);
      await after();
    } catch (err) {
      box.checked = !box.checked;
      box.disabled = false;
      toast(err.message);
    }
  });
}

/** The Quill's own settings: each screen it marked admin, drawn in its box by
    the kit as the Quill's code draws it, its buttons live. */
function wireSettings(holder, here) {
  for (const box of holder.querySelectorAll(".quill-admin-screen")) {
    const screen = here.screens.find((s) => s.id === box.dataset.screen);
    if (!screen) continue;
    embedView(box, { quill: here, screen, tab: "", base: "", embedded: true }, {});
  }
}

/** An installed Quill's settings, first on its sheet: the server's switch,
    and under it every screen the Quill marked `admin = true` — its own
    settings, a mail domain, a key everybody's traffic goes through — drawn
    by the kit as the Quill's code draws them, only ever here. */
function settingsBox(name, feature, here) {
  const own = ((here && here.screens) || []).filter((s) => s.admin && s.kit === "view");
  return `<p class="group-label">Settings</p><div class="group quill-settings">${switchRow(name, feature)}</div>` +
    own.map((s) => `<p class="group-label">${esc(s.label || name)}</p>` +
      `<div class="quill-admin-screen" data-screen="${esc(s.id)}"></div>`).join("");
}

/** The server's switch on an installed Quill: off takes its tabs out of every
    client and closes its API. What Features used to list, on the sheet instead. */
function switchRow(name, feature) {
  const on = feature ? feature.enabled : true;
  let turned = "";
  if (feature && feature.changed_by) {
    const when = seconds(feature.updated_at);
    turned = ` Switched ${on ? "on" : "off"} by ${feature.changed_by}${when ? ` ${formatDate(when)}` : ""}.`;
  }
  return `<label class="row feature-row server-switch">
    <span class="main"><span class="title">On for everybody</span>
    <span class="meta"><span class="preview">${esc(`Off takes its tabs out of every client and closes its part of the API.${turned}`)}</span></span></span>
    <input type="checkbox"${on ? " checked" : ""} aria-label="${esc(name)} is on"></label>`;
}

/** Where the installed Quill stands against the catalog, said as a fact above
    the buttons: a newer release, up to date, or installed from somewhere else. */
function standingRow(plan, installed, entry, newer, origin) {
  const fact = (title, note) => `<div class="row sheet-fact"><span class="main"><span class="title">${esc(title)}</span>
    <span class="meta"><span class="preview">${esc(note)}</span></span></span></div>`;
  if (newer) return fact(`v${plan.version} is in the catalog`, `v${installed} is installed here.`);
  if (entry) return fact("Up to date", `v${installed}, from the catalog.`);
  if (origin.dev) return fact(`v${installed}`, "Installed from a folder, with cm quill dev.");
  if (origin.repo) return fact(`v${installed}`, `Installed from ${origin.repo}.`);
  return fact(`v${installed}`, origin.catalog ? "Installed from the catalog." : "Installed from a source.");
}

async function removeQuill(id, name, drop, done) {
  try {
    const gone = await api("DELETE", quillUrl(id) + (drop.length ? "?drop=" + encodeURIComponent(drop.join(",")) : ""));
    const dropped = Object.values((gone && gone.dropped) || {}).reduce((a, b) => a + b, 0);
    const programs = (gone && gone.runtimes) || [];
    const also = programs.length ? `, and ${listed(programs)} with it` : "";
    await done(dropped ? `${name} is removed, and ${dropped} record${dropped === 1 ? "" : "s"} with it${programs.length ? ` and ${listed(programs)}` : ""}`
      : `${name} is removed; its records are kept${also}`);
  } catch (err) { toast(err.message); }
}

/** What a Quill brought, a tick each to keep it: the datamodels it introduced
    and the fields it added, with how many records hold each. Unticked goes
    with the Quill, records and all. */
export function removeSheet(name, brought) {
  const rows = brought.map((b) => {
    // A program it fetched that nothing else needs is offered the other way
    // round: unticked, it goes with the quill, because nothing runs on it.
    const runtime = b.kind === "runtime";
    const what = runtime ? `A program it added · ${esc(b.size_said || megabytes(b.size || 0))} · nothing else needs it`
      : `${esc(b.kind === "datamodel" ? "A datamodel it introduced" : "A field it added")} · ${
        b.records} record${b.records === 1 ? "" : "s"}`;
    return `<label class="row"><span class="main">
      <span class="title">${esc(b.label)}</span>
      <span class="meta"><span class="preview">${what}</span></span></span>
      <input type="checkbox" value="${esc(b.id)}" ${runtime ? "" : "checked"} aria-label="Keep ${esc(b.label)}"></label>`;
  }).join("");
  const programs = brought.some((b) => b.kind === "runtime");
  return `<div class="remove-sheet">
    <p class="group-label">Removing ${esc(name)}</p>
    <p class="shelf-note">Its tabs and jobs go, for everybody. What it brought stays, ticked:
      a datamodel's records are there again the day it comes back, and a field stays on the
      records, read-only. Untick what should go with it — records and all, for good.${programs
        ? " A program only this quill needed is unticked: it goes too, unless you tick it to keep it for later." : ""}</p>
    <div class="group choices">${rows}</div>
    <div class="sheet-buttons">
      <button class="act-button danger confirm" type="button">Remove ${esc(name)}</button>
      <button class="act-button cancel" type="button">Keep it</button>
    </div>
  </div>`;
}

/** Who the Quill is for: nobody ticked is everyone; a circle ticked is its people,
    and the Quill is not on anybody else's shelf. The data under it is still the
    gate's business, so this is about the software, not the records. */
function whoItIsFor(circles, audience, installed) {
  if (!circles.length) return "";
  const chosen = new Set((audience.circles || []).map((c) => c.toLowerCase()));
  const people = audience.people || [];
  return `<p class="group-label">Who it is for</p>
    <p class="shelf-note">Nobody ticked is everyone on the server. Tick circles to put its tabs on their
      shelves only.${people.length ? ` Also for ${esc(people.join(", "))}, from a request.` : ""}</p>
    <div class="group choices who-it-is-for">${circles.map((c) => `<label class="row"><span class="main">
      <span class="title">${esc(c.name)}</span><span class="meta"><span class="preview">${esc(c.members.join(", ") || "nobody")}</span></span></span>
      <input type="checkbox" value="${esc(c.id)}"${chosen.has(c.id.toLowerCase()) || chosen.has(c.name.toLowerCase()) ? " checked" : ""}
        aria-label="${esc(c.name)}"></label>`).join("")}</div>
    ${installed ? `<div class="sheet-buttons"><button class="act-button change-audience" type="button">Change who it is for</button></div>` : ""}`;
}

/** Somebody's own Quill of the same id: tick to bring their records into this one. */
function adoptSheet(adopt) {
  if (!adopt.length) return "";
  return `<p class="group-label">Already here as somebody's own</p>
    <p class="shelf-note">Ticked, their records of its datamodels move into the server's, and their own
      copy goes; they have this one instead.</p>
    <div class="group choices adopt-sheet">${adopt.map((a) => `<label class="row"><span class="main">
      <span class="title">${esc(a.owner)}'s, v${esc(a.version)}</span>
      <span class="meta"><span class="preview">${esc(a.records.join(", "))}</span></span></span>
      <input type="checkbox" value="${esc(a.owner)}" checked aria-label="${esc(a.owner)}"></label>`).join("")}</div>`;
}

/** A tick per circle for the data the Quill brings; a `* = write` circle is
    ticked and fixed, because it has everything already. */
function whoGetsIt(fresh, circles) {
  if (!fresh.length || !circles.length) return "";
  const what = listed(fresh.map((d) => d.label || d.id));
  const everyone = circles.filter((c) => c.rules["*"] === "write").map((c) => c.name);
  const lead = everyone.length
    ? `Everyone in ${esc(listed(everyone))} can read and write ${esc(what)} the moment it is installed.`
    : `No circle has everything, so nobody reaches ${esc(what)} until a circle is ticked here.`;
  return `<p class="group-label">Who gets it</p>
    <p class="shelf-note">${lead} Tick the other circles that should too; the rest do not
      see it until a circle is given it, under Circles.</p>
    <div class="group choices who-gets-it">${circles.map((c) => {
      const already = c.rules["*"] === "write";
      return `<label class="row"><span class="main"><span class="title">${esc(c.name)}</span>
        <span class="meta"><span class="preview">${already ? "Has everything (*): gets it anyway"
          : esc(c.members.join(", ") || "nobody")}</span></span></span>
        <input type="checkbox" value="${esc(c.id)}"${already ? " checked disabled" : ""}
          aria-label="${esc(c.name)}"></label>`;
    }).join("")}</div>`;
}

/** Everything the Quill contains and adds, a section each. Your Quills (myquills.js) draws the same. */
export function sections(plan, me) {
  const out = [];
  const row = (title, note = "", right = "") => `<div class="row sheet-fact">
    <span class="main"><span class="title">${title}</span>${note ? `<span class="meta"><span class="preview">${note}</span></span>` : ""}</span>${right}</div>`;
  const group = (label, rows, foot = "") => rows.length
    ? `<p class="group-label">${esc(label)}</p><div class="group">${rows.join("")}</div>${foot}` : "";

  // The data first: it is what outlives the Quill.
  const data = (plan.data || []).filter((d) => d.how !== "asks for");
  out.push(group("Data", data.map((d) => {
    const whose = d.foundation ? "a standard kind of data, shared by every quill" : `from ${esc(plan.name || plan.id)}`;
    const extra = d.fields && d.fields.length ? ` · adds ${d.fields.map(esc).join(", ")}` : "";
    return row(`${esc(HOW[d.how] || d.how)} ${esc(d.label)}`, `${whose}${extra}`,
      d.new ? `<span class="quill-chip new">new</span>` : "");
  }), `<p class="shelf-note">Records belong to the people who write them, not to
    the quill: removing it later leaves every one of them where it is.</p>`));

  const asks = (plan.data || []).filter((d) => d.how === "asks for");
  out.push(group("It asks for", asks.map((d) =>
    row(`${d.access === "write" ? "Read and write" : "Read"} ${esc(d.label)}`, esc(d.why || ""),
      d.new ? `<span class="quill-chip new">new</span>` : ""))));

  const label = (model) => {
    const found = (plan.data || []).find((d) => d.id === model);
    return found ? found.label : model;
  };
  out.push(group("Comes with", (plan.datasets || []).map((d) =>
    row(`${esc(plural(d.count, label(d.model).toLowerCase()))}`,
      d.seed === "per-owner" ? "for each person, the first time they open it" : esc(d.seed || "")))));

  const surfaces = plan.surfaces || [];
  out.push(group("Screens", (plan.screens || []).map((s) =>
    row(esc(s.label || s.id), `a ${esc(s.kit)} of ${esc(label(s.model).toLowerCase())}s`)),
  surfaces.length ? `<p class="shelf-note">Each a tab on ${esc(listed(surfaces))}.</p>` : ""));

  out.push(group("Runs on a schedule", (plan.jobs || []).map((j) => row(esc(j.id), esc(jobSaid(j, label, plan.models || {}))))));

  // The other quills it works with: installed first, from the catalog, and
  // kept while it is here.
  const needs = plan.quills || [];
  out.push(group("Installs with it", needs.map((q) => {
    const facts = [q.summary || ""].filter(Boolean).map(esc);
    if (q.problem) facts.push(`<span class="warn">${esc(q.problem)}</span>`);
    const chip = q.installed ? `<span class="quill-chip on">here already</span>`
      : q.problem ? "" : `<span class="quill-chip new">will install</span>`;
    return row(`${esc(q.name || q.id)}${q.version ? ` ${esc(q.version)}` : ""}`, facts.join(" · "), chip);
  }), needs.length ? `<p class="shelf-note">This quill works with ${needs.length === 1 ? "this one" : "these"}:
    ${needs.length === 1 ? "it is" : "they are"} installed first, from the catalog, and cannot be removed while
    this quill is here.</p>` : ""));

  // Programs its services need: the server fetches them from where the
  // catalog says and keeps them for its Quills. Said with the size before
  // the yes, because a hundred megabytes is a thing to know.
  const runtimes = plan.runtimes || [];
  out.push(group("Adds to this server", runtimes.map((r) => {
    const facts = [r.summary, r.size ? megabytes(r.size) : "", r.license].filter(Boolean).map(esc);
    if (r.problem) facts.push(`<span class="warn">${esc(r.problem)}</span>`);
    const chip = r.installed ? `<span class="quill-chip on">here already</span>`
      : r.available ? `<span class="quill-chip new">will download</span>` : "";
    return row(`${esc(r.label || r.id)}${r.version ? ` ${esc(r.version)}` : ""}`, facts.join(" · "), chip);
  }), runtimes.length ? `<p class="shelf-note">A program the quill's code runs. The server downloads it,
    checks it against the catalog's checksum, and keeps it for its quills; nothing is installed on the
    system itself. When the last quill that needs it is removed, you are asked whether it goes too.</p>` : ""));

  // And what its machine handlers bring to a computer they are switched on on:
  // fetched there, by the agent, after the person says yes there.
  const onMachines = plan.machine_runtimes || [];
  out.push(group("Adds to a machine that runs it", onMachines.map((r) => {
    const facts = [r.summary, r.size ? `up to ${megabytes(r.size)}` : "", r.license].filter(Boolean).map(esc);
    if (r.problem) facts.push(`<span class="warn">${esc(r.problem)}</span>`);
    return row(`${esc(r.label || r.id)}${r.version ? ` ${esc(r.version)}` : ""}`, facts.join(" · "));
  }), onMachines.length ? `<p class="shelf-note">Part of this quill runs on a person's own computer, once
    they switch it on there, and needs this program: the agent on that computer fetches it then, checks it,
    and keeps it; the server does not.</p>` : ""));

  const code = [
    ...(plan.services || []).map((s) => row(`Service ${esc(s.id)}`, esc((s.command || []).join(" ")))),
    ...(plan.webhooks || []).map((w) => row(`Webhook ${esc(w.id)}`, `POST /hooks/${esc(plan.id)}/${esc(w.path || w.id)}`)),
    ...(plan.apis || []).map((a) => row(`API ${esc(a.id)}`, `/api/q/${esc(plan.id)}/…`)),
  ];
  // Code is the one part of a Quill the kit does not draw: a program this
  // server starts, acting for an account. So the yes is to that, in words.
  const commands = plan.runs_code || [];
  const who = plan.runs_as || (me && me.username) || "you";
  const reach = (plan.reach || []).map(label).join(", ") || "nothing";
  out.push(group("Its own code", code, code.length
    ? `<p class="shelf-note warn">${commands.length
      ? `Runs code on this server: ${esc(commands.join("; "))}. ` : ""}It runs as
      ${esc(who)}, and can read and write only: ${esc(reach)}.</p>` : ""));

  if (plan.readme && plan.readme.trim()) {
    // As its author wrote it, folded: the facts above are what the yes is
    // to, and this is the Quill in its own words for whoever wants them.
    out.push(`<details class="group readme"><summary class="row">Its read me</summary>` +
      `<pre>${esc(plan.readme.trim())}</pre></details>`);
  }
  return out.join("");
}

// "7d" as a person says it; "1h" as "hour", for after "every".
const UNITS = { m: "minute", h: "hour", d: "day" };
function span(text, alone = false) {
  const m = /^(\d+)\s*([mhd])$/.exec(String(text || "").trim());
  if (!m) return String(text || "");
  const n = Number(m[1]);
  return alone && n === 1 ? UNITS[m[2]] : plural(n, UNITS[m[2]]);
}

// When an expire job's clock starts, in the datamodel's own words. A field
// the server stamps is said by what stamps it — "after their lane becomes
// Done" — because that is the thing a person does; any other by its label.
function whenSet(models, modelId, name) {
  const model = models[modelId];
  const f = model && model.fields.find((x) => x.name === name);
  if (!f) return `their ${name.replace(/_/g, " ")} is set`;
  const by = f.stamp && model.fields.find((x) => x.name === f.stamp.field);
  if (by) {
    const at = (by.values || []).indexOf(f.stamp.value);
    const value = at === -1 ? String(f.stamp.value) : (by.labels || by.values)[at];
    return `their ${by.label.toLowerCase()} becomes ${value}`;
  }
  return `their ${f.label.toLowerCase()}`;
}

function jobSaid(job, label, models) {
  const every = job.every ? `, checked every ${span(job.every, true)}` : "";
  if (job.action === "expire") {
    return `Deletes ${label(job.model).toLowerCase()}s ${span(job.after)} after ` +
      `${whenSet(models, job.model, job.field)}${every}`;
  }
  if (job.action === "run") return `Starts its service${job.every ? ` every ${span(job.every, true)}` : ""}`;
  return job.action;
}

const listed = (items) => (items.length < 2 ? items.join("")
  : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`);

// A download's size as a person reads it: 119 MB, 1.5 GB.
const megabytes = (size) => (size >= 1e9 ? `${(size / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(size / 1e6))} MB`);

registerScreen("adminquill", renderQuill);
