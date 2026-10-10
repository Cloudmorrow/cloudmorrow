/* Quills, for an administrator: the catalog, and the install sheet.

   The third section of Administration, beside who may sign in and what the
   server offers. The catalog is shelved by category, with what is already
   here marked by its version. Choosing one opens its install sheet — every
   datamodel it uses, extends or introduces, the records it comes with, the
   screens it adds and where they appear, what it runs and what it asks
   for — because nothing is added to a server without a yes, and a yes is
   worth nothing unless it was to something written down.

   Installing puts its tabs in every account's bar; this window's too, at
   once. Removing takes the tabs and the jobs and never a record: the data
   was always the people's, not the Quill's.

   A Quill with code of its own says so on the sheet in plain words — the
   commands it runs on this server, as whom, and what it may reach — and,
   once installed, shows what that code is doing (quillservices.js).

   A Quill that brings data new to this server asks which circles get it
   (docs/CIRCLES.md): a tick each, and after the install every ticked circle
   may write it. A circle with `* = write` has it already, and says so. */

import {
  api, app, esc, nav, registerScreen, renderRoute, replace, store, toast, wireShell,
} from "./core.js";
import { refreshQuills } from "./quills.js";
import { drawRunning, drawRunningList } from "./quillservices.js";

const quillUrl = (id) => "/api/quills/" + encodeURIComponent(id);
// The shelf for what is on no shelf: not an id a catalog category can have.
const SOURCE = "(source)";

/** Back to the catalog, on the Quills side of Administration, whichever
    side it was opened from — a link straight to a sheet included. */
async function backToCatalog() {
  store.set("admin.side", "quills");
  replace("#/admin");
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

// -- the catalog, in the panel -------------------------------------------------------
/** The catalog, into Administration's panel. */
export async function drawQuills(panel) {
  let catalog;
  let installed = [];
  try {
    // Every server Quill, on this administrator's own shelf or not.
    [catalog, installed] = await Promise.all([
      api("GET", "/api/quills/catalog"), api("GET", "/api/quills/all").then((all) => all.server),
    ]);
  } catch (err) {
    panel.innerHTML = `<p class="note">The catalog could not be read: ${esc(err.message)}</p>`;
    return;
  }
  const shelves = [...catalog.categories];
  const known = new Set(shelves.map((c) => c.id));
  if (catalog.quills.some((q) => !known.has(q.category))) {
    shelves.push({ id: "", label: "Other", description: "" });
  }
  // A Quill installed from a folder or a repository of its own — one
  // being written, with `cm quill dev` — is on no shelf, and still has to
  // be somewhere it can be looked at and taken away again.
  const listed = new Set(catalog.quills.map((q) => q.id));
  const loose = installed.filter((q) => !listed.has(q.id))
    .map((q) => ({ ...q, installed_version: q.version, category: SOURCE }));
  if (loose.length) {
    shelves.push({ id: SOURCE, label: "Installed from a source", description: "Not in the catalog: added from a folder or a repository." });
    known.add(SOURCE);
    catalog.quills.push(...loose);
  }
  panel.innerHTML = `
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
  await drawRunningList(panel);
  await drawShelves(panel);
}

// -- Quills of people's own: what the server allows, what was asked for, whose is whose ----
const POLICY = [
  ["personal_quills", "Quills of people's own", {
    on: "Anybody may add one for themselves",
    ask: "Only through a request an administrator approves",
    off: "Nobody; the ones there are go dark",
  }],
  ["personal_quill_code", "May run code", { on: "In the sandbox, as its owner", off: "Declared Quills only" }],
  ["personal_quill_sharing", "May be shared", { on: "With people who say yes", off: "Yours alone" }],
];

async function drawShelves(panel) {
  let all;
  try { all = await api("GET", "/api/quills/all"); } catch (err) {
    panel.insertAdjacentHTML("beforeend", `<p class="note">People's own Quills could not be read: ${esc(err.message)}</p>`);
    return;
  }
  const requests = all.requests || [];
  const personal = all.personal || [];
  panel.insertAdjacentHTML("beforeend", `
    <p class="group-label">Quills of people's own</p>
    <p class="shelf-note">What this server allows (docs/SHARING.md). A Quill somebody adds for themselves is on
      their shelf alone, over their own data, run as them; it changes nothing other people see.</p>
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
    ${personal.length ? `<p class="group-label">Whose</p>
    <div class="group">${personal.map((q) => {
      const yes = (q.shared_with || []).filter((x) => x.state === "accepted").map((x) => x.username);
      const gone = q.owner_active === false ? " · its owner's account is gone: promote it, or remove it" : "";
      return `<div class="row own-row" data-owner="${esc(q.owner)}" data-quill="${esc(q.id)}" data-name="${esc(q.name)}">
        <span class="main"><span class="title">${esc(q.name)} <span class="meta-inline">v${esc(q.version)}</span></span>
        <span class="meta"><span class="preview">${esc(q.owner)}'s${yes.length ? `, shared with ${esc(yes.join(", "))}` : ""}${
          q.code ? " · runs code, as each of them" : ""}${gone}</span></span></span>
        <span class="own-buttons">
          <button type="button" class="quill-chip on promote">Promote</button>
          <button type="button" class="quill-chip ${q.enabled ? "switch-off" : "switch-on"}">${q.enabled ? "Switch off" : "Switch on"}</button>
        </span></div>`;
    }).join("")}</div>
    <p class="shelf-note">Promoting makes it the server's, for everyone: every record of its own datamodels —
      the owner's and the people's it was shared with — moves with it. Switching one off takes it from
      everybody who has it until it is switched on again.</p>` : ""}`);

  for (const select of panel.querySelectorAll(".policy select")) {
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
  for (const row of panel.querySelectorAll(".request-row")) {
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
  for (const row of panel.querySelectorAll(".own-row")) {
    const { owner, quill, name } = row.dataset;
    row.querySelector(".promote").addEventListener("click", () => {
      if (!confirm(`Promote ${owner}'s ${name}, for everyone? Every record of its datamodels moves to the server's.`)) return;
      redo(() => api("POST", "/api/quills/promote", { owner, id: quill }), `${name} is the server's now`);
    });
    const key = `~${owner}.${quill}`;
    row.querySelector(".switch-off")?.addEventListener("click", () => redo(
      () => api("PATCH", "/api/server/features/" + encodeURIComponent(key), { enabled: false })));
    row.querySelector(".switch-on")?.addEventListener("click", () => redo(
      () => api("PATCH", "/api/server/features/" + encodeURIComponent(key), { enabled: true })));
  }
}

function catalogRow(q) {
  const state = q.installed_version
    ? `<span class="quill-chip on">v${esc(q.installed_version)}</span>`
    : `<span class="quill-chip">Add</span>`;
  const by = q.publisher ? ` · ${q.publisher}` : "";
  return `<a class="row quill-row" href="#/adminquill/${encodeURIComponent(q.id)}">
    <span class="main"><span class="title">${esc(q.name || q.id)}</span>
    <span class="meta"><span class="preview">${esc((q.summary || "") + by)}</span></span></span>
    ${state}</a>`;
}

// -- the install sheet -----------------------------------------------------------------
async function renderQuill(id) {
  const me = await api("GET", "/api/auth/me");
  if (!me.is_admin) {
    toast("Administration is for administrators");
    replace("#/me");
    return renderRoute();
  }
  // A Quill in the catalog is described fresh from it — what installing
  // would add now. One installed from a source has only what it added.
  let plan;
  try {
    const catalog = await api("GET", "/api/quills/catalog");
    plan = catalog.quills.some((q) => q.id === id)
      ? await api("POST", "/api/quills/plan", { id })
      : { ...(await api("GET", quillUrl(id))), from_source: true };
    if (plan.from_source) plan.installed_version = plan.version;
    // Who an installed Quill is for is on the Quill itself, not in the catalog.
    if (plan.installed_version && !plan.from_source) {
      try { plan.audience = (await api("GET", quillUrl(id))).audience; } catch { /* everyone, then */ }
    }
  } catch (err) {
    toast(err.message);
    replace("#/admin");
    return renderRoute();
  }
  const installed = plan.installed_version;
  const name = plan.name || plan.id;
  // The data it brings that no circle names yet, and the circles to give it to.
  const fresh = installed ? [] : (plan.data || []).filter((d) => d.new);
  let circles = [];
  if (fresh.length) {
    try { circles = await api("GET", "/api/circles"); } catch { circles = []; }
  }
  const verb = !installed ? `Install ${name}`
    : installed !== plan.version ? `Update to v${plan.version}` : "";
  // Who the Quill is for: everyone, or the circles ticked (docs/SHARING.md).
  let allCircles = circles;
  if (!allCircles.length) {
    try { allCircles = await api("GET", "/api/circles"); } catch { allCircles = []; }
  }
  const audience = plan.audience || { circles: [], people: [] };

  app.innerHTML = nav({ back: "#/admin", backLabel: "Admin", title: name }) + `
    <main class="quill-sheet">
      <h1 class="large">${esc(name)}</h1>
      <p class="quill-lede">${esc(plan.summary || "")}</p>
      <p class="quill-facts">${[
        `v${esc(plan.version)}`, esc(plan.publisher || ""), esc(plan.license || ""),
        installed ? `<span class="quill-chip on">v${esc(installed)} installed</span>` : "",
      ].filter(Boolean).join(" · ")}</p>
      ${sections(plan, me)}
      ${whoGetsIt(fresh, circles)}
      ${whoItIsFor(allCircles, audience, installed)}
      ${adoptSheet(plan.adopt || [])}
      ${installed ? `<div class="quill-running"></div>` : ""}
      ${verb ? `<div class="group"><button class="row primary add-quill" type="button">${esc(verb)}</button></div>` : ""}
      ${installed ? `<div class="group"><button class="row bad remove-quill" type="button">Remove ${esc(name)}</button></div>` : ""}
    </main>`;
  wireShell();
  const running = app.querySelector(".quill-running");
  if (running) drawRunning(running, id);
  const change = app.querySelector(".change-audience");
  if (change) change.addEventListener("click", async () => {
    const forCircles = [...app.querySelectorAll(".who-it-is-for input:checked")].map((b) => b.value);
    try {
      await api("PUT", quillUrl(id) + "/audience", { circles: forCircles, people: audience.people || [] });
      await refreshQuills();
      toast(forCircles.length ? `${name} is for ${forCircles.length} circle${forCircles.length === 1 ? "" : "s"}` : `${name} is for everyone`);
    } catch (err) { toast(err.message); }
  });

  const install = app.querySelector(".add-quill");
  if (install) install.addEventListener("click", async () => {
    install.disabled = true;
    install.textContent = "Installing…";
    try {
      const forCircles = [...app.querySelectorAll(".who-it-is-for input:checked")].map((b) => b.value);
      const adopt = [...app.querySelectorAll(".adopt-sheet input:checked")].map((b) => b.value);
      await api("POST", "/api/quills", { id, audience: { circles: forCircles, people: [] }, adopt });
      const ticked = [...app.querySelectorAll(".who-gets-it input:checked:not(:disabled)")];
      for (const box of ticked) {
        for (const d of fresh) {
          await api("PUT", `/api/circles/${encodeURIComponent(box.value)}/rules/${encodeURIComponent(d.id)}`,
            { access: "write" });
        }
      }
      // The tabs are in every account's bar from now; this one's at once.
      await refreshQuills();
      toast(`${name} is installed`);
      await backToCatalog();
    } catch (err) {
      install.disabled = false;
      install.textContent = verb;
      toast(err.message);
    }
  });

  const remove = app.querySelector(".remove-quill");
  if (remove) remove.addEventListener("click", async () => {
    let brought = [];
    try { brought = await api("GET", quillUrl(id) + "/brought"); } catch (err) { toast(err.message); return; }
    if (!brought.length) {
      const sure = confirm(
        `Remove ${name}?\n\nIts tabs and jobs go, for everybody. Nothing anybody `
        + "wrote is deleted: the records stay, and are there again if it comes back.",
      );
      if (!sure) return;
      return removeQuill(id, name, []);
    }
    // What it brought, each ticked to keep; the administrator unticks what goes.
    remove.closest(".group").insertAdjacentHTML("afterend", removeSheet(name, brought));
    remove.closest(".group").hidden = true;
    const sheet = app.querySelector(".remove-sheet");
    sheet.querySelector(".cancel").addEventListener("click", () => {
      sheet.remove();
      remove.closest(".group").hidden = false;
    });
    sheet.querySelector(".confirm").addEventListener("click", async () => {
      const drop = [...sheet.querySelectorAll("input[type=checkbox]:not(:checked)")].map((b) => b.value);
      await removeQuill(id, name, drop);
    });
  });
}

async function removeQuill(id, name, drop) {
  try {
    const gone = await api("DELETE", quillUrl(id) + (drop.length ? "?drop=" + encodeURIComponent(drop.join(",")) : ""));
    await refreshQuills();
    const dropped = Object.values((gone && gone.dropped) || {}).reduce((a, b) => a + b, 0);
    toast(dropped ? `${name} is removed, and ${dropped} record${dropped === 1 ? "" : "s"} with it`
      : `${name} is removed; its records are kept`);
    await backToCatalog();
  } catch (err) { toast(err.message); }
}

/** What a Quill brought, a tick each to keep it: the datamodels it introduced
    and the fields it added, with how many records hold each. Unticked goes
    with the Quill, records and all. */
function removeSheet(name, brought) {
  const rows = brought.map((b) => `<label class="row"><span class="main">
      <span class="title">${esc(b.label)}</span>
      <span class="meta"><span class="preview">${esc(b.kind === "datamodel" ? "A datamodel it introduced" : "A field it added")} · ${
        b.records} record${b.records === 1 ? "" : "s"}</span></span></span>
      <input type="checkbox" value="${esc(b.id)}" checked aria-label="Keep ${esc(b.label)}"></label>`).join("");
  return `<div class="remove-sheet">
    <p class="group-label">Removing ${esc(name)}</p>
    <p class="shelf-note">Its tabs and jobs go, for everybody. What it brought stays, ticked:
      a datamodel's records are there again the day it comes back, and a field stays on the
      records, read-only. Untick what should go with it — records and all, for good.</p>
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

registerScreen("adminquill", renderQuill);
