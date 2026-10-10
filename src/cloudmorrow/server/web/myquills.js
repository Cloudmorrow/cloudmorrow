/* Your Quills: the ones you made or added for yourself, the ones people
   offered you, and what you asked an administrator for (docs/SHARING.md).

   Reached from Me, like Administration, because a Quill of your own is not
   a sixth kind of your own stuff: it is software, and this is where software
   is managed. Everything here is yours alone to do — a server Quill is the
   administrator's, over in Administration, Quills — and it runs as you, over
   the data your circles let you reach, exactly as a tab does.

   The server says what it allows (`may`): whether people may have Quills of
   their own at all, install them without asking, run code in them, share
   them. The screen shows what is allowed and says, in a line, what is not. */

import {
  api, apiRaw, app, esc, nav, registerScreen, renderRoute, replace, toast, wireShell,
} from "./core.js";
import { refreshQuills } from "./quills.js";
import { sections } from "./quillsadmin.js";

const mineUrl = (id) => "/api/quills/mine/" + encodeURIComponent(id);
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** The row that leads here, for Me. */
export function myQuillsRow() {
  return `<div class="group"><a class="row myquills-link" href="#/myquills">
    <span class="main"><span class="title">Your Quills</span>
    <span class="meta"><span class="preview">Software of your own, the Quills people shared with you, and what you asked for</span></span></span>
    </a></div>`;
}

async function renderMine() {
  let mine;
  let me;
  try {
    [mine, me] = await Promise.all([api("GET", "/api/quills/mine"), api("GET", "/api/auth/me")]);
  } catch (err) {
    toast(err.message);
    replace("#/me");
    return renderRoute();
  }
  const may = mine.may || {};
  app.innerHTML = nav({ back: "#/me", backLabel: "Me", title: "Your Quills" }) + `
    <main class="myquills">
      <h1 class="large">Your Quills</h1>
      ${allowed(may)}
      ${offers(mine.offers || [])}
      ${own(mine.quills || [], may)}
      ${requests(mine.requests || [])}
      ${may.have && (may.install || may.ask) ? `<p class="group-label">Add one</p>${await catalogRows(may)}` : ""}
      ${Object.keys(mine.broken || {}).length ? broken(mine.broken) : ""}
    </main>`;
  wireShell();
  wire(mine, me);
}

function allowed(may) {
  if (!may.have) {
    return `<p class="note">Quills of people's own are switched off on this server. An administrator
      can switch them on under Administration, Quills.</p>`;
  }
  const bits = [
    may.install ? "You may add Quills for yourself: from the catalog below, or with <code>cm quill dev</code> in a folder your assistant wrote."
      : "On this server a Quill of your own comes through a request: ask below, and an administrator says yes.",
    may.code ? "" : "They may not run code of their own here.",
    may.share ? "You may share yours with people; each says yes before it is theirs." : "Sharing them is switched off.",
  ].filter(Boolean);
  return `<p class="note">${bits.join(" ")}</p>`;
}

function offers(list) {
  const open = list.filter((o) => o.state === "offered");
  const had = list.filter((o) => o.state === "accepted");
  if (!open.length && !had.length) return "";
  const row = (o, buttons) => `<div class="row offer-row" data-owner="${esc(o.owner)}" data-quill="${esc(o.quill)}">
    <span class="main"><span class="title">${esc(o.name)}</span>
    <span class="meta"><span class="preview">${esc(o.owner)}'s · v${esc(o.version)} · ${esc(o.summary || "")}</span></span></span>
    ${buttons}</div>`;
  return (open.length ? `<p class="group-label">Offered to you</p>
    <p class="shelf-note">Saying yes puts it on your shelf, over your own data, run as you. The owner
      never sees your records; you never see theirs.</p>
    <div class="group">${open.map((o) => row(o,
      `<button type="button" class="quill-chip on accept">Yes</button><button type="button" class="quill-chip decline">No</button>`)).join("")}</div>` : "")
    + (had.length ? `<p class="group-label">Shared with you</p>
    <div class="group">${had.map((o) => row(o, `<button type="button" class="quill-chip leave">Leave</button>`)).join("")}</div>` : "");
}

function own(list, may) {
  if (!list.length) return "";
  return `<p class="group-label">Yours</p>
    <div class="group">${list.map((q) => {
      const shared = (q.shared_with || []);
      const yes = shared.filter((s) => s.state === "accepted").map((s) => s.username);
      const waiting = shared.filter((s) => s.state === "offered").map((s) => s.username);
      const who = [
        yes.length ? `shared with ${esc(yes.join(", "))}` : "",
        waiting.length ? `offered to ${esc(waiting.join(", "))}` : "",
      ].filter(Boolean).join(" · ") || "yours alone";
      return `<div class="row own-row" data-quill="${esc(q.id)}" data-name="${esc(q.name)}">
        <span class="main"><span class="title">${esc(q.name)} <span class="meta-inline">v${esc(q.version)}</span></span>
        <span class="meta"><span class="preview">${who}</span></span></span>
        <span class="own-buttons">
          ${may.share ? `<button type="button" class="quill-chip share">Share…</button>` : ""}
          <button type="button" class="quill-chip export">Export</button>
          <button type="button" class="quill-chip ask-promote">Ask to promote</button>
          <button type="button" class="quill-chip remove">Remove</button>
        </span></div>`;
    }).join("")}</div>
    <p class="shelf-note">Export writes it the way a repository holds it, ready for <code>cm quill test</code>,
      a push and the Quill Catalog. Asking to promote asks an administrator to make it the server's, for
      everyone, your records going with it.</p>`;
}

function requests(list) {
  if (!list.length) return "";
  return `<p class="group-label">Asked for</p>
    <div class="group">${list.map((r) => `<div class="row request-row" data-id="${r.id}">
      <span class="main"><span class="title">${esc(r.kind === "promote" ? `Promote ${r.quill}` : r.quill || r.source)}</span>
      <span class="meta"><span class="preview">${esc(r.state)}${r.note ? ` · ${esc(r.note)}` : ""}${
        r.answer && r.answer.note ? ` · ${esc(r.answer.note)}` : ""}</span></span></span>
      ${r.state === "open" ? `<button type="button" class="quill-chip withdraw">Withdraw</button>` : ""}</div>`).join("")}</div>`;
}

async function catalogRows(may) {
  let catalog;
  let shelf;
  try {
    [catalog, shelf] = await Promise.all([api("GET", "/api/quills/catalog"), api("GET", "/api/quills")]);
  } catch (err) {
    return `<p class="note">The catalog could not be read: ${esc(err.message)}</p>`;
  }
  const have = new Set(shelf.map((q) => q.id));
  const rows = catalog.quills.filter((q) => !have.has(q.id));
  if (!rows.length) return `<p class="note">Everything in the catalog is on your shelf already.</p>`;
  return `<p class="shelf-note">${may.install
    ? "From the Quill Catalog, for yourself alone. Its install sheet says what it adds before you say yes."
    : "From the Quill Catalog. An administrator sees your request and installs it for you, or for everyone."}</p>
    <div class="group">${rows.map((q) => `<div class="row catalog-row" data-quill="${esc(q.id)}" data-name="${esc(q.name || q.id)}">
      <span class="main"><span class="title">${esc(q.name || q.id)}</span>
      <span class="meta"><span class="preview">${esc(q.summary || "")}${q.publisher ? ` · ${esc(q.publisher)}` : ""}</span></span></span>
      <button type="button" class="quill-chip on add">${may.install ? "Add for me" : "Ask for it"}</button></div>`).join("")}</div>`;
}

function broken(map) {
  return `<p class="group-label">Not loading</p><div class="group">${Object.entries(map).map(([key, why]) =>
    `<div class="row"><span class="main"><span class="title">${esc(key)}</span>
    <span class="meta"><span class="preview">${esc(why)}</span></span></span></div>`).join("")}</div>`;
}

// -- doing things ----------------------------------------------------------------------------
function wire(mine, me) {
  const again = () => renderMine();
  const attempt = async (fn, done) => {
    try { await fn(); await refreshQuills(); if (done) toast(done); await again(); } catch (err) { toast(err.message); }
  };
  for (const row of app.querySelectorAll(".offer-row")) {
    const { owner, quill } = row.dataset;
    const base = `/api/quills/offers/${encodeURIComponent(owner)}/${encodeURIComponent(quill)}`;
    row.querySelector(".accept")?.addEventListener("click", () => attempt(() => api("POST", base + "/accept"), `${quill} is on your shelf`));
    row.querySelector(".decline")?.addEventListener("click", () => attempt(() => api("POST", base + "/decline")));
    row.querySelector(".leave")?.addEventListener("click", () => {
      if (confirm(`Leave ${owner}'s ${quill}? Your records of its data stay yours.`)) attempt(() => api("DELETE", base));
    });
  }
  for (const row of app.querySelectorAll(".own-row")) {
    const { quill, name } = row.dataset;
    row.querySelector(".share")?.addEventListener("click", () => shareSheet(row, quill, name, again));
    row.querySelector(".export")?.addEventListener("click", () => exportIt(quill));
    row.querySelector(".ask-promote")?.addEventListener("click", () => {
      const note = prompt(`Ask an administrator to make ${name} the server's, for everyone? Say why, if you like:`);
      if (note === null) return;
      attempt(() => api("POST", "/api/quills/requests", { kind: "promote", id: quill, note }), "Asked");
    });
    row.querySelector(".remove")?.addEventListener("click", async () => {
      let brought = [];
      try { brought = await api("GET", mineUrl(quill) + "/brought"); } catch (err) { toast(err.message); return; }
      const held = brought.filter((b) => b.records);
      const words = held.length
        ? `\n\nIts own data stays: ${held.map((b) => `${plural(b.records, "record")} of ${b.label}`).join(", ")}.`
        : "";
      if (!confirm(`Remove ${name}? Its tabs go, for you and anybody you shared it with.${words}`)) return;
      attempt(() => api("DELETE", mineUrl(quill)), `${name} is removed`);
    });
  }
  for (const row of app.querySelectorAll(".request-row .withdraw")) {
    row.addEventListener("click", () => attempt(() => api("DELETE", "/api/quills/requests/" + row.closest(".request-row").dataset.id)));
  }
  for (const row of app.querySelectorAll(".catalog-row")) {
    const { quill, name } = row.dataset;
    row.querySelector(".add").addEventListener("click", () => {
      if (mine.may.install) return addSheet(quill, name, me);
      const note = prompt(`Ask an administrator for ${name}? Say why, if you like:`);
      if (note === null) return;
      attempt(() => api("POST", "/api/quills/requests", { id: quill, note }), "Asked");
    });
  }
}

/** Pick people to offer it to: everybody on the server, a tick each. */
async function shareSheet(row, quill, name, again) {
  let people = [];
  try { people = await api("GET", "/api/people"); } catch (err) { toast(err.message); return; }
  const already = new Set();
  try {
    const found = await api("GET", mineUrl(quill));
    for (const s of found.shared_with || []) if (s.state !== "declined") already.add(s.username);
  } catch { /* the list is drawn without it */ }
  const choices = people.filter((p) => !already.has(p.username));
  row.insertAdjacentHTML("afterend", `<div class="share-sheet">
    <p class="shelf-note">Offer ${esc(name)} to: each says yes themselves, and then has it over their own data.</p>
    <div class="group choices">${choices.length ? choices.map((p) => `<label class="row"><span class="main">
      <span class="title">${esc(p.display_name)}</span><span class="meta"><span class="preview">${esc(p.username)}</span></span></span>
      <input type="checkbox" value="${esc(p.username)}" aria-label="${esc(p.display_name)}"></label>`).join("")
      : `<p class="empty">Everybody has been offered it already.</p>`}</div>
    <div class="group"><button class="row primary confirm" type="button">Offer it</button></div>
    <div class="group"><button class="row cancel" type="button">Not now</button></div></div>`);
  const sheet = row.nextElementSibling;
  sheet.querySelector(".cancel").addEventListener("click", () => sheet.remove());
  sheet.querySelector(".confirm").addEventListener("click", async () => {
    const chosen = [...sheet.querySelectorAll("input:checked")].map((b) => b.value);
    if (!chosen.length) { sheet.remove(); return; }
    try {
      await api("PUT", mineUrl(quill) + "/share", { people: chosen });
      toast(`Offered to ${chosen.join(", ")}`);
      await again();
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

/** The install sheet for a Quill of your own: what it adds, then a yes. */
async function addSheet(quill, name, me) {
  let plan;
  try { plan = await api("POST", "/api/quills/mine/plan", { id: quill }); } catch (err) { toast(err.message); return; }
  app.innerHTML = nav({ back: "#/myquills", backLabel: "Your Quills", title: name }) + `
    <main class="quill-sheet">
      <h1 class="large">${esc(plan.name || name)}</h1>
      <p class="quill-lede">${esc(plan.summary || "")}</p>
      <p class="quill-facts">v${esc(plan.version)}${plan.publisher ? ` · ${esc(plan.publisher)}` : ""} · <span class="quill-chip">yours alone</span></p>
      ${sections(plan, me)}
      <p class="shelf-note">On your shelf and nobody else's. Its data of its own is yours and nobody else
        can reach it; what it uses of the rest is what your circles let you reach, no more.</p>
      <div class="group"><button class="row primary add-mine" type="button">Add ${esc(plan.name || name)} for me</button></div>
    </main>`;
  wireShell();
  const button = app.querySelector(".add-mine");
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "Adding…";
    try {
      await api("POST", "/api/quills/mine", { id: quill });
      await refreshQuills();
      toast(`${plan.name || name} is on your shelf`);
      replace("#/myquills");
      await renderRoute();
    } catch (err) {
      button.disabled = false;
      button.textContent = `Add ${plan.name || name} for me`;
      toast(err.message);
    }
  });
}

registerScreen("myquills", renderMine);
