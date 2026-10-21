/* Your Quills: what is on your shelf, and the catalog to add to it from.

   Reached from Me, like Administration, because a Quill is not a sixth kind
   of your own stuff: it is software, and this is where software is
   managed. Three tabs, with a sheet for each Quill — beside the list on a
   computer, a screen of its own on a phone:

     Server Quills   the server's, put on your shelf by an administrator;
                     each with your own switch, which hides its tab from
                     your screens and nothing more
     Yours           the ones you added for yourself — from the catalog, or
                     with `cm quill dev` in a folder your assistant wrote —
                     with Update when the catalog has a newer release, and
                     Update all; the ones people shared with you; what you
                     were offered; what you asked an administrator for
     Catalog         every Quill there is, with what is on the server, what
                     is yours, and what you can add

   Everything here is yours alone to do — a server Quill is the
   administrator's, over in Administration — and a Quill of your own runs
   as you, over the data your circles let you reach, exactly as a tab does
   (docs/SHARING.md). The server says what it allows (`may`): whether people
   may have Quills of their own at all, add them without asking, run code in
   them, share them. The screen shows what is allowed and says, in a line,
   what is not. */

import {
  api, apiRaw, app, esc, icons, mount, nav, registerScreen, renderRoute, replace, store, toast, wireShell,
} from "./core.js";
import { loadFeatures } from "./features.js";
import { refreshQuills } from "./quills.js";
import { removeSheet, sections } from "./quillsadmin.js";
import { ask, askText } from "./dialog.js";

const mineUrl = (id) => "/api/quills/mine/" + encodeURIComponent(id);
const quillUrl = (id) => "/api/quills/" + encodeURIComponent(id);
const myFeatureUrl = (key) => "/api/me/features/" + encodeURIComponent(key);
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const listed = (items) => (items.length < 2 ? items.join("")
  : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`);
// A computer has the room for the sheet beside the list; the same query
// desktop.css stands the tabs up with.
const wide = () => matchMedia("(min-width: 900px) and (min-height: 600px)").matches;

const TABS = [
  ["server", "Server Quills"],
  ["mine", "Yours"],
  ["catalog", "Catalog"],
];

// Which sheet is open beside the list: kept while the page is, so a redraw
// after an install does not close the one you were reading.
let shown = "";

/** The row that leads here, for Me. */
export function myQuillsRow() {
  return `<div class="group"><a class="row myquills-link" href="#/myquills">
    <span class="main"><span class="title">Your Quills</span>
    <span class="meta"><span class="preview">What is on your shelf, the Quills of your own and their updates, and the catalog</span></span></span>
    ${icons.chevronRight}</a></div>`;
}

// -- what there is -------------------------------------------------------------------------
/** Everything the page draws from, asked for together. The catalog may be
    unreachable; the rest is this server's own and has to answer. */
async function load() {
  let catalogProblem = "";
  const [mine, shelf, me, features, catalog] = await Promise.all([
    api("GET", "/api/quills/mine"),
    api("GET", "/api/quills"),
    api("GET", "/api/auth/me"),
    api("GET", "/api/me/features").catch(() => []),
    api("GET", "/api/quills/catalog").catch((err) => { catalogProblem = err.message; return null; }),
  ]);
  return { mine, shelf, me, features, catalog, catalogProblem, may: mine.may || {} };
}

// Where a Quill of your own stands against the catalog: a newer release
// there (true), the same (false), or no telling (null) — the entry names no
// release, or it came from a source of its own. Installing again is the
// update in both of those cases.
function standing(own, catalog) {
  const entry = catalog && catalog.quills.find((q) => q.id === own.id);
  const origin = own.origin || {};
  if (!entry || !origin.catalog) {
    if (origin.dev) return { entry: null, newer: false, said: "from a folder, with cm quill dev" };
    if (origin.repo) return { entry: null, newer: null, said: `from ${origin.repo}` };
    return { entry: null, newer: false, said: "not in the catalog" };
  }
  const ref = String(entry.ref || "");
  if (!ref) return { entry, newer: null, said: "from the catalog" };
  if (ref !== String(origin.ref || "")) return { entry, newer: true, said: `newer in the catalog: ${ref}` };
  return { entry, newer: false, said: "up to date" };
}

// What the catalog is to you: on the server, yours, or there to add.
function placeOf(id, data) {
  if (data.mine.quills.some((q) => q.id === id)) return "mine";
  const onShelf = data.shelf.find((q) => q.id === id);
  if (onShelf && onShelf.shared_by) return "shared";
  if (onShelf) return "server";
  return "catalog";
}

// -- the page ---------------------------------------------------------------------------------
async function renderMine() {
  let data;
  try { data = await load(); } catch (err) {
    toast(err.message);
    replace("#/me");
    return renderRoute();
  }
  const which = TABS.some(([key]) => key === store.get("myquills.tab")) ? store.get("myquills.tab") : "server";
  const split = wide();
  mount(nav({ back: "#/me", backLabel: "Me", title: "Your Quills" }) + `
    <main class="myquills">
      <h1 class="large">Your Quills</h1>
      ${allowed(data.may)}
      <div class="${split ? "quills-split" : "quills-stack"}">
        <div class="side">
          <div class="quill-tabs" role="tablist">${TABS.map(([key, label]) =>
            `<button type="button" role="tab" data-tab="${key}" aria-selected="${key === which}"${
              key === which ? ' class="active"' : ""}>${label}</button>`).join("")}</div>
          <div class="quill-list"></div>
        </div>
        ${split ? `<div class="page"><p class="empty"><b>Nothing open</b>Choose a Quill on the left.</p></div>` : ""}
      </div>
    </main>`);
  wireShell();
  for (const button of app.querySelectorAll(".quill-tabs button")) {
    button.addEventListener("click", () => {
      store.set("myquills.tab", button.dataset.tab);
      renderMine();
    });
  }
  const ctx = { ...data, list: app.querySelector(".quill-list"), again: () => renderMine() };
  if (which === "server") drawServer(ctx);
  else if (which === "mine") drawMine(ctx);
  else drawCatalog(ctx);
  if (split && shown) await openSheet(ctx, shown);
}

function allowed(may) {
  if (!may.have) {
    return `<p class="note">Quills of people's own are switched off on this server. An administrator
      can switch them on under Administration, Quills.</p>`;
  }
  const bits = [
    may.install
      ? (may.create ? "You may add Quills for yourself: from the catalog, or with <code>cm quill dev</code> in a folder your assistant wrote."
        : "You may add Quills for yourself, from the catalog.")
      : "On this server a Quill of your own comes through a request: ask from the catalog, and an administrator says yes.",
    may.code ? "" : "They may not run code of their own here.",
    may.share ? "You may share yours with people; each says yes before it is theirs." : "Sharing them is switched off.",
  ].filter(Boolean);
  return `<p class="note">${bits.join(" ")}</p>`;
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

const quillRow = (id, title, preview, chip, extra = "") =>
  `<div class="row quill-row${id === shown ? " current" : ""}" data-id="${esc(id)}" role="button" tabindex="0">
    <span class="main"><span class="title">${title}</span>
    <span class="meta"><span class="preview">${preview}</span></span></span>
    ${extra}${chip}${icons.chevronRight}</div>`;

// -- Server Quills: the server's, on your shelf, with your switch on each -------------------
function drawServer(ctx) {
  const theirs = ctx.shelf.filter((q) => !q.mine && !q.shared_by);
  const switches = new Map(ctx.features.map((f) => [f.key, f]));
  ctx.list.innerHTML = `
    <p class="shelf-note">The server's Quills, put on your shelf by an administrator. The switch on each
      is yours: off takes its tab off your own screens, here and in the terminal alike, and nothing more.</p>
    ${theirs.length ? `<div class="group">${theirs.map((q) => {
      const mine = switches.get(q.id);
      const on = mine ? mine.enabled : q.enabled !== false;
      return quillRow(q.id, esc(q.name || q.id), `v${esc(q.version)} · ${esc(q.summary || "")}`,
        `<span class="quill-chip run-state ${on ? "good" : ""}">${on ? "on" : "off"}</span>`);
    }).join("")}</div>` : `<p class="empty"><b>Nothing from the server yet</b>An administrator adds Quills for everybody under Administration.</p>`}`;
  for (const row of ctx.list.querySelectorAll(".quill-row[data-id]")) wireRow(ctx, row);
}

// -- Yours: your own, with their updates; shared with you; offered; asked for ------------------
function drawMine(ctx) {
  const { mine, catalog, may } = ctx;
  const own = mine.quills || [];
  const stood = new Map(own.map((q) => [q.id, standing(q, catalog)]));
  const updatable = own.filter((q) => stood.get(q.id).newer !== false && (stood.get(q.id).entry || (q.origin || {}).repo));
  const newer = own.filter((q) => stood.get(q.id).newer === true).length;
  const offers = mine.offers || [];
  const open = offers.filter((o) => o.state === "offered");
  const had = offers.filter((o) => o.state === "accepted");
  const requests = mine.requests || [];
  const broken = Object.entries(mine.broken || {});
  const offerRow = (o, buttons) => `<div class="row offer-row" data-owner="${esc(o.owner)}" data-quill="${esc(o.quill)}">
    <span class="main"><span class="title">${esc(o.name)}</span>
    <span class="meta"><span class="preview">${esc(o.owner)}'s · v${esc(o.version)} · ${esc(o.summary || "")}</span></span></span>
    <span class="own-buttons">${buttons}</span></div>`;

  ctx.list.innerHTML = `
    ${ctx.catalogProblem ? `<p class="shelf-note warn">The catalog could not be read: ${esc(ctx.catalogProblem)}</p>` : ""}
    <div class="quill-actions">
      <button type="button" class="chip-button update-all"${updatable.length ? "" : " disabled"}>${
        !own.length ? "Nothing of yours yet" : !updatable.length ? "Everything is up to date"
          : newer ? `Update all · ${newer} newer` : "Update all"}</button>
    </div>
    <div class="update-log" hidden></div>
    ${own.length ? `<p class="group-label">Yours</p><div class="group">${own.map((q) => {
      const { newer: isNewer, said } = stood.get(q.id);
      const shared = (q.shared_with || []);
      const yes = shared.filter((s) => s.state === "accepted").map((s) => s.username);
      const who = yes.length ? ` · shared with ${esc(yes.join(", "))}` : "";
      const chip = isNewer ? `<span class="quill-chip new">update</span>`
        : `<span class="quill-chip ${q.enabled === false ? "" : "on"}">v${esc(q.version)}</span>`;
      return quillRow(q.id, esc(q.name || q.id), `${esc(said)}${who}`, chip);
    }).join("")}</div>` : `<p class="shelf-note">${may.install
      ? "Nothing of your own yet: add one from the catalog, or send a folder with <code>cm quill dev</code>."
      : "Nothing of your own yet: ask for one from the catalog."}</p>`}
    ${had.length ? `<p class="group-label">Shared with you</p>
    <div class="group">${had.map((o) => offerRow(o, `<button type="button" class="quill-chip leave">Leave</button>`)).join("")}</div>` : ""}
    ${open.length ? `<p class="group-label">Offered to you</p>
    <p class="shelf-note">Saying yes puts it on your shelf, over your own data, run as you. The owner
      never sees your records; you never see theirs.</p>
    <div class="group">${open.map((o) => offerRow(o,
      `<button type="button" class="quill-chip on accept">Yes</button><button type="button" class="quill-chip decline">No</button>`)).join("")}</div>` : ""}
    ${requests.length ? `<p class="group-label">Asked for</p>
    <div class="group">${requests.map((r) => `<div class="row request-row" data-id="${r.id}">
      <span class="main"><span class="title">${esc(r.kind === "promote" ? `Promote ${r.quill}` : r.quill || r.source)}</span>
      <span class="meta"><span class="preview">${esc(r.state)}${r.note ? ` · ${esc(r.note)}` : ""}${
        r.answer && r.answer.note ? ` · ${esc(r.answer.note)}` : ""}</span></span></span>
      ${r.state === "open" ? `<span class="own-buttons"><button type="button" class="quill-chip withdraw">Withdraw</button></span>` : ""}</div>`).join("")}</div>` : ""}
    ${broken.length ? `<p class="group-label">Not loading</p><div class="group">${broken.map(([key, why]) =>
      `<div class="row"><span class="main"><span class="title">${esc(key)}</span>
      <span class="meta"><span class="preview">${esc(why)}</span></span></span></div>`).join("")}</div>` : ""}`;

  for (const row of ctx.list.querySelectorAll(".quill-row[data-id]")) wireRow(ctx, row);
  const attempt = async (fn, done) => {
    try { await fn(); await refreshQuills(); if (done) toast(done); await ctx.again(); } catch (err) { toast(err.message); }
  };
  for (const row of ctx.list.querySelectorAll(".offer-row")) {
    const { owner, quill } = row.dataset;
    const base = `/api/quills/offers/${encodeURIComponent(owner)}/${encodeURIComponent(quill)}`;
    row.querySelector(".accept")?.addEventListener("click", () => attempt(() => api("POST", base + "/accept"), `${quill} is on your shelf`));
    row.querySelector(".decline")?.addEventListener("click", () => attempt(() => api("POST", base + "/decline")));
    row.querySelector(".leave")?.addEventListener("click", async () => {
      if (await ask(`Leave ${owner}'s ${quill}? Your records of its data stay yours.`)) attempt(() => api("DELETE", base));
    });
  }
  for (const button of ctx.list.querySelectorAll(".request-row .withdraw")) {
    button.addEventListener("click", () => attempt(() => api("DELETE", "/api/quills/requests/" + button.closest(".request-row").dataset.id)));
  }
  ctx.list.querySelector(".update-all").addEventListener("click", () => updateMany(ctx, updatable));
}

/** Install each of *quills* of yours again, one after the other, saying how each went. */
async function updateMany(ctx, quills) {
  if (!quills.length) return;
  const names = quills.map((q) => q.name || q.id);
  if (!await ask(`Update ${listed(names)}?\n\nEach is installed again, for you. Nothing you wrote is touched.`)) return;
  const log = ctx.list.querySelector(".update-log");
  const button = ctx.list.querySelector(".update-all");
  button.disabled = true;
  log.hidden = false;
  log.innerHTML = "";
  const line = (text, tone) => {
    const p = document.createElement("p");
    p.className = tone;
    p.textContent = text;
    log.append(p);
    return p;
  };
  for (const quill of quills) {
    const name = quill.name || quill.id;
    const p = line(`Updating ${name}…`, "muted");
    try {
      const done = await installAgain(quill);
      p.className = "good";
      p.textContent = done.version === quill.version ? `${name} v${quill.version} installed again` : `${name} v${quill.version} → v${done.version}`;
    } catch (err) {
      p.className = "bad";
      p.textContent = `${name}: ${err.message}`;
    }
  }
  await refreshQuills();
  // The lines stay on the page a moment before the list is drawn afresh.
  await new Promise((r) => setTimeout(r, 1500));
  await ctx.again();
}

/** The same install again, as your own: from the catalog by id, or from the source it came from. */
function installAgain(quill) {
  const origin = quill.origin || {};
  const body = origin.catalog || !origin.repo ? { id: quill.id } : { source: origin.repo, ref: origin.ref || "" };
  return api("POST", "/api/quills/mine", body);
}

// -- the catalog --------------------------------------------------------------------------------
function drawCatalog(ctx) {
  const { catalog } = ctx;
  if (!catalog) {
    ctx.list.innerHTML = `<p class="note">The catalog could not be read: ${esc(ctx.catalogProblem)}</p>`;
    return;
  }
  const shelves = [...catalog.categories];
  const known = new Set(shelves.map((c) => c.id));
  if (catalog.quills.some((q) => !known.has(q.category))) shelves.push({ id: "", label: "Other", description: "" });
  const chipFor = (q) => {
    const place = placeOf(q.id, ctx);
    if (place === "server") return `<span class="quill-chip on">on the server</span>`;
    if (place === "shared") return `<span class="quill-chip on">shared with you</span>`;
    if (place === "mine") {
      const own = ctx.mine.quills.find((x) => x.id === q.id);
      return standing(own, catalog).newer ? `<span class="quill-chip new">update</span>` : `<span class="quill-chip on">yours · v${esc(own.version)}</span>`;
    }
    return `<span class="quill-chip">${ctx.may.install ? "Add" : ctx.may.ask ? "Ask" : ""}</span>`;
  };
  ctx.list.innerHTML = `
    <p class="shelf-note">Every Quill there is. What the server has is on your shelf already; the rest you
      can ${ctx.may.install ? "add for yourself alone" : ctx.may.ask ? "ask an administrator for" : "read about"}.</p>` +
    shelves.map((shelf) => {
      const here = catalog.quills.filter((q) => (known.has(q.category) ? q.category : "") === shelf.id);
      if (!here.length) return "";
      return `<p class="group-label">${esc(shelf.label)}</p>` +
        (shelf.description ? `<p class="shelf-note">${esc(shelf.description)}</p>` : "") +
        `<div class="group">${here.map((q) => quillRow(q.id, esc(q.name || q.id),
          `${esc(q.summary || "")}${q.publisher ? ` · ${esc(q.publisher)}` : ""}`, chipFor(q))).join("")}</div>`;
    }).join("");
  for (const row of ctx.list.querySelectorAll(".quill-row[data-id]")) wireRow(ctx, row);
}

// -- the sheet ------------------------------------------------------------------------------------
/** Open a Quill's sheet: beside the list on a computer, as its own screen on a phone. */
async function openSheet(ctx, id) {
  if (!wide()) { location.hash = "#/myquill/" + encodeURIComponent(id); return; }
  shown = id;
  for (const row of app.querySelectorAll(".quill-row[data-id]")) row.classList.toggle("current", row.dataset.id === id);
  const page = app.querySelector(".quills-split .page");
  if (!page) return;
  const sheet = await buildSheet(id, ctx);
  if (!sheet) {
    shown = "";
    page.innerHTML = `<p class="empty"><b>Nothing open</b>Choose a Quill on the left.</p>`;
    return;
  }
  page.innerHTML = `<div class="quill-sheet">${sheet.html}</div>`;
  sheet.wire(page.firstElementChild, async ({ gone } = {}) => {
    if (gone) shown = "";
    await ctx.again();
  });
}

/** A Quill's sheet, as a screen of its own: the phone's way, and a link's. */
async function renderSheet(id) {
  if (wide()) {
    shown = id;
    replace("#/myquills");
    return renderRoute();
  }
  let data;
  try { data = await load(); } catch (err) { toast(err.message); replace("#/me"); return renderRoute(); }
  const sheet = await buildSheet(id, data);
  if (!sheet) { replace("#/myquills"); return renderRoute(); }
  mount(nav({ back: "#/myquills", backLabel: "Your Quills", title: sheet.name }) + `
    <main class="quill-sheet myquills">${sheet.html}</main>`);
  wireShell();
  sheet.wire(app.querySelector("main"), async () => { replace("#/myquills"); await renderRoute(); });
}

/** One Quill's sheet — its name, the HTML, and what wires it — or null, with a
    word said. *after(what)* is called once something has changed. */
async function buildSheet(id, data) {
  const { may, me, catalog } = data;
  const place = placeOf(id, data);
  const entry = catalog && catalog.quills.find((q) => q.id === id);
  let plan;
  // Why it cannot be yours, when the server says so: a Quill that adds fields
  // to everybody's data, say. The sheet still opens, with the reason on it.
  let refused = "";
  try {
    if (place === "mine") plan = await api("GET", mineUrl(id));
    else if (place === "server" || place === "shared") plan = await api("GET", quillUrl(id));
    else if (!entry) throw new Error(`${id} is not in the catalog`);
    else if (may.install) {
      try { plan = await api("POST", "/api/quills/mine/plan", { id }); } catch (err) {
        if (err.status !== 400 && err.status !== 403) throw err;
        refused = err.message;
        plan = { ...entry, data: [], screens: [], jobs: [], datasets: [] };
      }
    } else plan = { ...entry, data: [], screens: [], jobs: [], datasets: [] };
  } catch (err) {
    toast(err.message);
    return null;
  }
  const name = plan.name || plan.id || id;
  const stood = place === "mine" ? standing(plan, catalog) : null;
  const own = place === "mine" ? data.mine.quills.find((q) => q.id === id) || plan : null;
  const mySwitch = place === "server" ? data.features.find((f) => f.key === id) : null;
  const shelfRow = data.shelf.find((q) => q.id === id);
  const holders = plan.holders || [];
  const facts = [
    `v${esc(plan.version || entry?.ref || "")}`, esc(plan.publisher || ""), esc(plan.license || ""),
    place === "server" ? `<span class="quill-chip on">the server's</span>` : "",
    place === "shared" ? `<span class="quill-chip on">${esc(shelfRow.shared_by)}'s, shared with you</span>` : "",
    place === "mine" ? `<span class="quill-chip on">yours · v${esc(plan.version)}</span>` : "",
    stood && stood.newer ? `<span class="quill-chip new">${esc(stood.entry.ref)} in the catalog</span>` : "",
    place === "catalog" ? `<span class="quill-chip">not on your shelf</span>` : "",
  ].filter(Boolean).join(" · ");

  const html = `
    <h1 class="large">${esc(name)}</h1>
    <p class="quill-lede">${esc(plan.summary || "")}</p>
    <p class="quill-facts">${facts}</p>
    ${place === "server" ? `<div class="group"><label class="row feature-row my-switch">
      <span class="main"><span class="title">Shown to you</span>
      <span class="meta"><span class="preview">Off takes its tab off your own screens, here and in the terminal alike; nothing of yours is deleted. The server's own switch is an administrator's.</span></span></span>
      <input type="checkbox"${mySwitch ? (mySwitch.enabled ? " checked" : "") : " checked"} aria-label="${esc(name)} is shown to you"></label></div>` : ""}
    ${place === "mine" ? `<div class="group sheet-actions">
      ${stood.newer === false ? `<button class="row" type="button" disabled>${esc(stood.said === "up to date" ? "Up to date" : stood.said)}</button>`
        : `<button class="row primary update-mine" type="button">${stood.newer ? `Update to ${esc(stood.entry.ref)}`
          : stood.entry ? "Update from the catalog" : "Update from its source"}</button>`}
      ${stood.entry || (own.origin || {}).repo ? `<button class="row reinstall-mine" type="button">Reinstall v${esc(plan.version)}</button>` : ""}
      ${may.share ? `<button class="row share-mine" type="button">Share…</button>` : ""}
      <button class="row export-mine" type="button">Export</button>
      <button class="row promote-mine" type="button">Ask to promote</button>
      <button class="row bad remove-mine" type="button">Remove ${esc(name)}</button>
    </div>
    <p class="shelf-note">${esc(stood.said.charAt(0).toUpperCase() + stood.said.slice(1))}.${holders.length > 1
      ? ` Stands with ${esc(listed(holders.filter((h) => h !== me.username)))} too: its data is the Quill's, shared as you set it, and it stays for them if you take it off your shelf.`
      : " Its own data is yours and nobody else's until you share it."} Export writes it the way a repository holds it, ready for
      <code>cm quill test</code>, a push and the Quill Catalog. Asking to promote asks an administrator to
      make it the server's, for everyone, your records going with it.</p>
    <div class="share-slot"></div>` : ""}
    ${place === "shared" ? `<div class="group sheet-actions"><button class="row bad leave-shared" type="button">Leave it</button></div>
    <p class="shelf-note">On your shelf because ${esc(shelfRow.shared_by)} offered it and you said yes. Leaving it keeps your records of its data.</p>` : ""}
    ${sections(plan, me)}
    ${place === "catalog" ? (refused
      ? `<p class="shelf-note warn">Not one you can add for yourself: ${esc(refused)}</p>
        ${may.have ? `<p class="shelf-note">An administrator can install it for everyone: ask, and they see it under Administration.</p>
        <div class="group"><button class="row primary ask-mine" type="button">Ask for ${esc(name)}</button></div>` : ""}`
      : may.install
      ? `<p class="shelf-note">On your shelf and nobody else's. Its data of its own is yours and nobody else
          can reach it; what it uses of the rest is what your circles let you reach, no more.</p>
        <div class="group"><button class="row primary add-mine" type="button">Add ${esc(name)} for me</button></div>`
      : may.ask ? `<p class="shelf-note">On this server a Quill of your own comes through a request: an administrator
          sees it and installs it for you, or for everyone.</p>
        <div class="group"><button class="row primary ask-mine" type="button">Ask for ${esc(name)}</button></div>`
      : `<p class="shelf-note">Quills of people's own are switched off on this server.</p>`) : ""}`;

  const wire = (holder, after) => {
    const done = async (message, what) => {
      await refreshQuills();
      toast(message);
      await after(what);
    };
    const on = (selector, fn) => { const el = holder.querySelector(selector); if (el) el.addEventListener("click", fn); };
    const busy = (button, text) => {
      const live = [...holder.querySelectorAll(".sheet-actions button:not(:disabled), .row.primary")];
      const was = button.textContent;
      for (const b of live) b.disabled = true;
      button.textContent = text;
      return () => { for (const b of live) b.disabled = false; button.textContent = was; };
    };

    const box = holder.querySelector(".my-switch input");
    if (box) box.addEventListener("change", async () => {
      box.disabled = true;
      try {
        const feature = await api("PATCH", myFeatureUrl(id), { enabled: box.checked });
        await loadFeatures();
        toast(feature.enabled ? `${name} is back` : `${name} is off your screens`);
        await after();
      } catch (err) {
        box.checked = !box.checked;
        box.disabled = false;
        toast(err.message);
      }
    });

    on(".add-mine", async (event) => {
      const undo = busy(event.currentTarget, "Adding…");
      try {
        await api("POST", "/api/quills/mine", { id });
        await done(`${name} is on your shelf`);
      } catch (err) { undo(); toast(err.message); }
    });
    on(".ask-mine", async () => {
      const note = await askText(`Ask an administrator for ${name}? Say why, if you like:`);
      if (note === null) return;
      try { await api("POST", "/api/quills/requests", { id, note }); await done("Asked"); } catch (err) { toast(err.message); }
    });
    const again = async (button, verb) => {
      const undo = busy(button, `${verb}…`);
      try {
        const result = await installAgain(own);
        await done(result.version === plan.version ? `${name} v${plan.version} is installed again` : `${name} is updated to v${result.version}`);
      } catch (err) { undo(); toast(err.message); }
    };
    on(".update-mine", (event) => again(event.currentTarget, "Updating"));
    on(".reinstall-mine", async (event) => {
      if (!await ask(`Install ${name} v${plan.version} again?\n\nNothing you wrote is touched.`)) return;
      again(event.currentTarget, "Installing");
    });
    on(".share-mine", () => shareSheet(holder.querySelector(".share-slot"), id, name, plan, after));
    on(".export-mine", () => exportIt(id));
    on(".promote-mine", async () => {
      const note = await askText(`Ask an administrator to make ${name} the server's, for everyone? Say why, if you like:`);
      if (note === null) return;
      try { await api("POST", "/api/quills/requests", { kind: "promote", id, note }); await done("Asked"); } catch (err) { toast(err.message); }
    });
    // Off your shelf: while others still have it, it stays for them; the last
    // to have it is asked what it brought should go with it.
    const offShelf = async (button, url, broughtUrl, whose) => {
      const others = holders.filter((h) => h !== me.username);
      if (others.length) {
        if (!await ask(`Take ${name} off your shelf?\n\nIt stays for ${listed(others)}, its data and all; what you wrote stays the Quill's.`)) return;
        try {
          await api("DELETE", url);
          await done(`${name} is off your shelf; it stays with ${listed(others)}`, { gone: true });
        } catch (err) { toast(err.message); }
        return;
      }
      let brought = [];
      try { brought = await api("GET", broughtUrl); } catch (err) { toast(err.message); return; }
      if (!brought.length) {
        if (!await ask(`Remove ${whose}${name}?\n\nYou are the last to have it, so it goes from the server. Nothing it kept is deleted.`)) return;
        try { await api("DELETE", url); await done(`${name} is removed`, { gone: true }); } catch (err) { toast(err.message); }
        return;
      }
      button.closest(".group").insertAdjacentHTML("afterend", removeSheet(name, brought));
      button.closest(".group").hidden = true;
      const sheet = holder.querySelector(".remove-sheet");
      sheet.querySelector(".cancel").addEventListener("click", () => { sheet.remove(); button.closest(".group").hidden = false; });
      sheet.querySelector(".confirm").addEventListener("click", async () => {
        const drop = [...sheet.querySelectorAll("input[type=checkbox]:not(:checked)")].map((b) => b.value);
        try {
          const gone = await api("DELETE", url + (drop.length ? "?drop=" + encodeURIComponent(drop.join(",")) : ""));
          const dropped = Object.values((gone && gone.dropped) || {}).reduce((a, b) => a + b, 0);
          await done(dropped ? `${name} is removed, and ${plural(dropped, "record")} with it` : `${name} is removed; its records are kept`, { gone: true });
        } catch (err) { toast(err.message); }
      });
    };
    on(".remove-mine", (event) => offShelf(event.currentTarget, mineUrl(id), mineUrl(id) + "/brought", ""));
    on(".leave-shared", (event) => {
      const base = `/api/quills/offers/${encodeURIComponent(shelfRow.shared_by)}/${encodeURIComponent(id)}`;
      offShelf(event.currentTarget, base, base + "/brought", `${shelfRow.shared_by}'s `);
    });
  };
  return { name, html, wire };
}

/** Pick people to offer it to, and what each may do with the Quill's own data:
    write or read, per datamodel. The people who have it already are listed with
    their rules, to be changed the same way. */
async function shareSheet(slot, quill, name, plan, after) {
  if (!slot || slot.querySelector(".share-sheet")) return;
  let people = [];
  try { people = await api("GET", "/api/people"); } catch (err) { toast(err.message); return; }
  const shares = (plan.shared_with || []).filter((s) => s.state !== "declined" && s.state !== "left");
  const already = new Map(shares.map((s) => [s.username, s]));
  const own = (plan.data || []).filter((d) => d.how === "introduces");
  const person = (p, share) => `<label class="row"><span class="main">
      <span class="title">${esc(p.display_name)}</span><span class="meta"><span class="preview">${esc(p.username)}${
        share ? ` · ${share.state === "accepted" ? "has it" : "offered"}` : ""}</span></span></span>
      <input type="checkbox" value="${esc(p.username)}"${share ? " checked" : ""} aria-label="${esc(p.display_name)}"></label>`;
  slot.innerHTML = `<div class="share-sheet">
    <p class="shelf-note">Offer ${esc(name)} to people: each says yes themselves, and then works on the Quill's data
      with you, as the rules below let them. Ticked already is somebody who has it, or was offered it; offered
      again, only their rules change.</p>
    <div class="group choices share-people">${people.length ? people.filter((p) => p.username !== plan.owner).map((p) => person(p, already.get(p.username))).join("")
      : `<p class="empty">Nobody else is on this server.</p>`}</div>
    ${own.length ? `<p class="group-label">What they may do with its data</p>
    <p class="shelf-note">Per datamodel of the Quill's own, for everybody ticked. Read is a screen looked at.</p>
    <div class="group policy share-rules">${own.map((d) => `<label class="row">
      <span class="main"><span class="title">${esc(d.label || d.plain || d.id)}</span></span>
      <select data-model="${esc(d.id)}" aria-label="${esc(d.label || d.id)}">
        <option value="write">write</option><option value="read">read</option></select></label>`).join("")}</div>` : ""}
    <div class="group"><button class="row primary confirm" type="button">Offer it</button></div>
    <div class="group"><button class="row cancel" type="button">Not now</button></div></div>`;
  slot.querySelector(".cancel").addEventListener("click", () => { slot.innerHTML = ""; });
  slot.querySelector(".confirm").addEventListener("click", async () => {
    const chosen = [...slot.querySelectorAll(".share-people input:checked")].map((b) => b.value);
    if (!chosen.length) { slot.innerHTML = ""; return; }
    const rules = {};
    for (const select of slot.querySelectorAll(".share-rules select")) rules[select.dataset.model] = select.value;
    try {
      await api("PUT", mineUrl(quill) + "/share", { people: chosen, rules });
      toast(`Offered to ${chosen.join(", ")}`);
      await after();
    } catch (err) { toast(err.message); }
  });
}

/** The .tar.gz, handed to the browser to save. */
async function exportIt(quill) {
  try {
    const response = await apiRaw("GET", mineUrl(quill) + "/export", { fail: "the export failed" });
    const blob = await response.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `quill-${quill}.tar.gz`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 10_000);
  } catch (err) { toast(err.message); }
}

registerScreen("myquills", renderMine);
registerScreen("myquill", renderSheet);
