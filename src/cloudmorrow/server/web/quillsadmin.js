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
  api, app, esc, formatDate, icons, mount, nav, registerScreen, renderRoute, replace, seconds, store, toast,
  wireShell,
} from "./core.js";
import { loadFeatures } from "./features.js";
import { refreshQuills } from "./quills.js";
import { drawRunning } from "./quillservices.js";

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
  try {
    [catalog, all, running] = await Promise.all([
      api("GET", "/api/quills/catalog").catch((err) => { catalogProblem = err.message; return null; }),
      api("GET", "/api/quills/all"),
      api("GET", "/api/quillservices").catch(() => []),
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
  for (const button of panel.querySelectorAll(".quill-tabs button")) {
    button.addEventListener("click", () => {
      store.set("admin.quills", button.dataset.tab);
      lastLog = [];
      drawQuills(panel);
    });
  }
  const ctx = { panel, catalog, catalogProblem, all, running, list: panel.querySelector(".quill-list") };
  if (which === "server") await drawServer(ctx);
  else if (which === "own") await drawOwn(ctx);
  else drawCatalog(ctx);
  // The sheet that was open stays open, drawn afresh: it may have changed.
  if (split && shown) await openSheet(ctx, shown);
}

/** Open a Quill's sheet: beside the list on a computer, as its own screen on a phone. */
async function openSheet(ctx, id) {
  if (!wide()) { location.hash = "#/adminquill/" + encodeURIComponent(id); return; }
  shown = id;
  for (const row of ctx.panel.querySelectorAll(".quill-row[data-id]")) {
    row.classList.toggle("current", row.dataset.id === id);
  }
  const page = ctx.panel.querySelector(".page");
  if (!page) return;
  const sheet = await buildSheet(id);
  if (!sheet) {
    shown = "";
    page.innerHTML = `<p class="empty"><b>Nothing open</b>Choose a Quill on the left.</p>`;
    return;
  }
  page.innerHTML = `<div class="quill-sheet">${sheet.html}</div>`;
  sheet.wire(page.firstElementChild, async ({ removed } = {}) => {
    if (removed) shown = "";
    await drawQuills(ctx.panel);
  });
}

/** A row that opens a sheet: a click, or Enter on it, that is not on a control in it. */
function wireRow(ctx, row) {
  row.addEventListener("click", (event) => {
    if (event.target.closest("input, button, a")) return;
    openSheet(ctx, row.dataset.id);
  });
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
    ${stateChip(stateOf(quill, running))}${icons.chevronRight}</div>`;
}

/** Install each of *quills* again from the catalog, one after the other, saying
    how each went; who each is for goes with it. */
async function updateMany(ctx, quills) {
  if (!quills.length) return;
  const names = quills.map((q) => q.name || q.id);
  const sure = confirm(`Update ${listed(names)}?\n\nEach is installed again from the catalog. `
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
        </span></div>`;
    }).join("")}</div>
    <p class="shelf-note">Promoting makes it the server's, for everyone: every record of its own datamodels —
      the owner's and the people's it was shared with — moves with it. Switching one off takes it from
      everybody who has it until it is switched on again.</p>`
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
    row.querySelector(".decline").addEventListener("click", () => {
      const note = prompt(`Decline ${who}'s request? A word back, if you like:`);
      if (note === null) return;
      redo(() => api("POST", url + "/decline", { note }), "Declined");
    });
  }
  for (const row of list.querySelectorAll(".own-row")) {
    const { owner, quill, name } = row.dataset;
    row.querySelector(".promote").addEventListener("click", () => {
      if (!confirm(`Promote ${owner}'s ${name}, for everyone? Every record of its datamodels moves to the server's.`)) return;
      redo(() => api("POST", "/api/quills/promote", { owner, id: quill }), `${name} is the server's now`);
    });
    const key = `~${owner}.${quill}`;
    row.querySelector(".switch-off")?.addEventListener("click", () => redo(
      () => api("PATCH", featureUrl(key), { enabled: false })));
    row.querySelector(".switch-on")?.addEventListener("click", () => redo(
      () => api("PATCH", featureUrl(key), { enabled: true })));
  }
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
async function renderQuill(id) {
  const me = await api("GET", "/api/auth/me");
  if (!me.is_admin) {
    toast("Administration is for administrators");
    replace("#/me");
    return renderRoute();
  }
  // A computer has the sheet beside the list; a link to one lands there.
  if (wide()) {
    shown = id;
    return backToQuills();
  }
  const sheet = await buildSheet(id, me);
  if (!sheet) return backToQuills();
  mount(nav({ back: "#/admin/quills", backLabel: "Quills", title: sheet.name }) + `
    <main class="quill-sheet">${sheet.html}</main>`);
  wireShell();
  sheet.wire(app.querySelector("main"), backToQuills);
}

/** The sheet for one Quill — its name, the HTML, and what wires it into a holder
    — or null, with a word said, when there is no such Quill. *after(what)* is
    called once an install, update or removal has gone through. */
async function buildSheet(id, me = null) {
  if (!me) me = await api("GET", "/api/auth/me");
  // A Quill in the catalog is described fresh from it — what installing
  // would add now. One installed from a source has only what it added.
  let plan;
  let entry = null;
  let here = null;
  let feature = null;
  try {
    const catalog = await api("GET", "/api/quills/catalog");
    entry = catalog.quills.find((q) => q.id === id) || null;
    plan = entry ? await api("POST", "/api/quills/plan", { id }) : { ...(await api("GET", quillUrl(id))), from_source: true };
    if (plan.from_source) plan.installed_version = plan.version;
    if (plan.installed_version) {
      // Who it is for, where it came from, and whether it is on: on the
      // Quill itself and the server's switch, not in the catalog.
      [here, feature] = await Promise.all([
        api("GET", quillUrl(id)).catch(() => null),
        api("GET", "/api/server/features").then((rows) => rows.find((f) => f.key === id) || null).catch(() => null),
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
  // a folder sent with `cm quill dev` has to be sent again from there.
  const again = installed && (entry || (!origin.dev && origin.repo));

  const html = `
      <h1 class="large">${esc(name)}</h1>
      <p class="quill-lede">${esc(plan.summary || "")}</p>
      <p class="quill-facts">${[
        `v${esc(plan.version)}`, esc(plan.publisher || ""), esc(plan.license || ""),
        installed ? `<span class="quill-chip on">v${esc(installed)} installed</span>` : "",
        newer ? `<span class="quill-chip new">v${esc(plan.version)} in the catalog</span>` : "",
      ].filter(Boolean).join(" · ")}</p>
      ${installed ? switchRow(name, feature) : ""}
      ${installed ? `<div class="group sheet-actions">
        ${newer ? `<button class="row primary update-quill" type="button">Update to v${esc(plan.version)}</button>`
          : entry ? `<button class="row" type="button" disabled>Up to date</button>` : ""}
        ${again ? `<button class="row reinstall-quill" type="button">Reinstall v${esc(installed)}</button>` : ""}
        <button class="row bad remove-quill" type="button">Remove ${esc(name)}</button>
      </div>
      ${again ? "" : `<p class="shelf-note">Installed from a folder with <code>cm quill dev</code>: to install it again, send it from there.</p>`}
      <div class="quill-running"></div>` : ""}
      ${sections(plan, me)}
      ${whoGetsIt(fresh, circles)}
      ${whoItIsFor(circles, audience, installed)}
      ${adoptSheet(plan.adopt || [])}
      ${installed ? "" : `<div class="group"><button class="row primary add-quill" type="button">Install ${esc(name)}</button></div>`}`;

  const wire = (holder, after) => {
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

    const box = holder.querySelector(".server-switch input");
    if (box) box.addEventListener("change", async () => {
      box.disabled = true;
      try {
        const turned = await api("PATCH", featureUrl(id), { enabled: box.checked });
        // "Everywhere" includes this window: the bar is drawn from what
        // this account has, and that has just changed.
        await loadFeatures();
        await done(turned.enabled ? `${name} is on.` : `${name} is off — its tabs are gone everywhere.`);
      } catch (err) {
        box.checked = !box.checked;
        box.disabled = false;
        toast(err.message);
      }
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
    if (reinstall) reinstall.addEventListener("click", () => {
      if (!confirm(`Install ${name} v${installed} again?\n\nIts tabs stay for the same people; nothing anybody wrote is touched.`)) return;
      installOnceMore(reinstall, "Installing");
    });

    const remove = holder.querySelector(".remove-quill");
    if (remove) remove.addEventListener("click", async () => {
      let brought = [];
      try { brought = await api("GET", quillUrl(id) + "/brought"); } catch (err) { toast(err.message); return; }
      const gone = async (drop) => removeQuill(id, name, drop, (message) => done(message, { removed: true }));
      if (!brought.length) {
        const sure = confirm(
          `Remove ${name}?\n\nIts tabs and jobs go, for everybody. Nothing anybody `
          + "wrote is deleted: the records stay, and are there again if it comes back.",
        );
        if (!sure) return;
        return gone([]);
      }
      // What it brought, each ticked to keep; the administrator unticks what goes.
      remove.closest(".group").insertAdjacentHTML("afterend", removeSheet(name, brought));
      remove.closest(".group").hidden = true;
      const sheet = holder.querySelector(".remove-sheet");
      sheet.querySelector(".cancel").addEventListener("click", () => {
        sheet.remove();
        remove.closest(".group").hidden = false;
      });
      sheet.querySelector(".confirm").addEventListener("click", async () => {
        const drop = [...sheet.querySelectorAll("input[type=checkbox]:not(:checked)")].map((b) => b.value);
        await gone(drop);
      });
    });
  };
  return { name, html, wire };
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
  return `<div class="group"><label class="row feature-row server-switch">
    <span class="main"><span class="title">On for everybody</span>
    <span class="meta"><span class="preview">${esc(`Off takes its tabs out of every client and closes its part of the API.${turned}`)}</span></span></span>
    <input type="checkbox"${on ? " checked" : ""} aria-label="${esc(name)} is on"></label></div>`;
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
    <div class="group"><button class="row bad confirm" type="button">Remove ${esc(name)}</button></div>
    <div class="group"><button class="row cancel" type="button">Keep it</button></div>
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
    ${installed ? `<div class="group"><button class="row change-audience" type="button">Change who it is for</button></div>` : ""}`;
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
