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
   once installed, shows what that code is doing (quillservices.js). */

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
    [catalog, installed] = await Promise.all([
      api("GET", "/api/quills/catalog"), api("GET", "/api/quills"),
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
  } catch (err) {
    toast(err.message);
    replace("#/admin");
    return renderRoute();
  }
  const installed = plan.installed_version;
  const name = plan.name || plan.id;
  const verb = !installed ? `Install ${name}`
    : installed !== plan.version ? `Update to v${plan.version}` : "";

  app.innerHTML = nav({ back: "#/admin", backLabel: "Admin", title: name }) + `
    <main class="quill-sheet">
      <h1 class="large">${esc(name)}</h1>
      <p class="quill-lede">${esc(plan.summary || "")}</p>
      <p class="quill-facts">${[
        `v${esc(plan.version)}`, esc(plan.publisher || ""), esc(plan.license || ""),
        installed ? `<span class="quill-chip on">v${esc(installed)} installed</span>` : "",
      ].filter(Boolean).join(" · ")}</p>
      ${sections(plan, me)}
      ${installed ? `<div class="quill-running"></div>` : ""}
      ${verb ? `<div class="group"><button class="row primary add-quill" type="button">${esc(verb)}</button></div>` : ""}
      ${installed ? `<div class="group"><button class="row bad remove-quill" type="button">Remove ${esc(name)}</button></div>` : ""}
    </main>`;
  wireShell();
  const running = app.querySelector(".quill-running");
  if (running) drawRunning(running, id);

  const install = app.querySelector(".add-quill");
  if (install) install.addEventListener("click", async () => {
    install.disabled = true;
    install.textContent = "Installing…";
    try {
      await api("POST", "/api/quills", { id });
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
    const sure = confirm(
      `Remove ${name}?\n\nIts tabs and jobs go, for everybody. Nothing anybody `
      + "wrote is deleted: the records stay, and are there again if it comes back.",
    );
    if (!sure) return;
    try {
      await api("DELETE", quillUrl(id));
      await refreshQuills();
      toast(`${name} is removed; its records are kept`);
      await backToCatalog();
    } catch (err) { toast(err.message); }
  });
}

/** Everything the Quill contains and adds, a section each. */
function sections(plan, me) {
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
