/* The kit's `data`: every datamodel a screen's Quill has, and the records in
   each, to look at.

   The Data tab (server/dataview.py) is the one that uses it today: the
   server composes a Quill for whoever asks with every datamodel their
   circles give them, each marked `read`, and this draws it — but a Quill of
   its own may declare a `data` screen over its own datamodels the same way.
   Two levels, then the sheet every record has:

     #/q/<quill>/<screen>              the datamodels, by domain
     #/q/<quill>/<screen>/<model>      the records of one
     #/r/<quill>/<screen>/<model>/<id> one record, on the sheet (kit.js)

   On the sheet, under the fields, this adds what the record is to the
   rest: the records of other datamodels that link to it, and — for a
   snapshot — its digest, whether its bundle is intact, and the attestations
   on it; for a space, the snapshots taken of it (docs/ATTESTATIONS.md).
   Nothing here knows what any datamodel is: a ledger and a book are both a
   space, a snapshot is a datamodel with a route of its own. */

import { api, apiRaw, app, esc, heading, icons, mount, nav, recordsUrl, tabs, toast, wireShell } from "./core.js";
import { fieldOf, linkTitles, spoken, titleOf } from "./kit.js";

const SNAPSHOT = "snapshot";
const ATTESTATION = "attestation";
// How many of the records linking to one are shown on its sheet.
const LINKED_SHOWN = 25;

const domainOf = (model) => (model.domain || "other").replace(/_/g, " ");
/** A datamodel's label for all of its records: Deals, Activities, Journal entries. */
const plural = (label) => (/s$/i.test(label) ? label : /[^aeiou]y$/i.test(label) ? label.slice(0, -1) + "ies" : label + "s");
const count = (n, noun) => `${n} ${n === 1 ? noun : plural(noun)}`;
const capital = (text) => text.charAt(0).toUpperCase() + text.slice(1);
const modelHash = (at, model) => `${at.base}/${encodeURIComponent(model.id)}`;
const recordHash = (at, model, id) =>
  `#/r/${encodeURIComponent(at.quill.id)}/${encodeURIComponent(at.screen.id)}/${encodeURIComponent(model.id)}/${encodeURIComponent(id)}`;

/** The datamodels a data screen draws: the Quill's, or the ones the screen names. */
function modelsOf(at) {
  const { quill, screen } = at;
  const ids = screen.models && screen.models.length ? screen.models : Object.keys(quill.models);
  return ids.map((id) => quill.models[id]).filter(Boolean);
}

/** What a row says under a record's title: where it is, then what it is sorted by. */
function underFields(model) {
  const title = model.title;
  const fields = [];
  if (model.in_space && fieldOf(model, model.in_space)) fields.push(fieldOf(model, model.in_space));
  for (const f of model.fields) {
    if (fields.length >= 2) break;
    if (f.name === title || fields.includes(f) || !f.indexed || f.kind === "json" || f.secret) continue;
    fields.push(f);
  }
  return fields;
}

export async function renderData(at, arg) {
  const [modelId] = String(arg || "").split("/").filter(Boolean);
  if (modelId) return renderRecords(at, modelId);
  const models = modelsOf(at);
  const byDomain = new Map();
  for (const model of models) {
    const domain = domainOf(model);
    if (!byDomain.has(domain)) byDomain.set(domain, []);
    byDomain.get(domain).push(model);
  }
  const row = (model) => `<a class="row" href="${esc(modelHash(at, model))}"><span class="main">` +
    `<span class="title">${esc(model.label)}</span>` +
    (model.description ? `<span class="meta"><span class="preview">${esc(model.description)}</span></span>` : "") +
    `</span>${icons.chevronRight}</a>`;
  mount(nav({ title: at.screen.label }) + `
    <main>
      ${heading(at.screen.label)}
      ${models.length ? [...byDomain.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([domain, inside]) =>
        `<p class="group-label">${esc(capital(domain))}</p><div class="group kit-list">${inside.map(row).join("")}</div>`).join("")
        : `<p class="empty mascot"><b>Nothing to see</b>Your circles give you no data here yet.</p>`}
    </main>` + tabs(at.tab));
  wireShell();
}

async function renderRecords(at, modelId) {
  const model = at.quill.models[modelId];
  if (!model) {
    mount(nav({ back: at.base, backLabel: at.screen.label, title: modelId }) +
      `<main><p class="empty"><b>Not here</b>There is no ${esc(modelId)} you may see.</p></main>` + tabs(at.tab));
    wireShell();
    return;
  }
  const under = underFields(model);
  const records = await api("GET", recordsUrl(model.id));
  const links = await linkTitles(at.quill, under.filter((f) => f.kind === "link"));
  const row = (r) => {
    const said = under.map((f) => spoken(f, r.fields[f.name], links[f.name])).filter(Boolean);
    return `<a class="row" href="${esc(recordHash(at, model, r.id))}"><span class="main">` +
      `<span class="title">${esc(titleOf(model, r))}</span>` +
      (said.length ? `<span class="meta"><span class="preview">${esc(said.join(" · "))}</span></span>` : "") +
      `</span>${icons.chevronRight}</a>`;
  };
  mount(nav({ back: at.base, backLabel: at.screen.label, title: plural(model.label) }) + `
    <main>
      ${heading(plural(model.label), `<span class="count">${esc(count(records.length, model.label.toLowerCase()))}</span>`)}
      ${model.description ? `<p class="data-about">${esc(model.description)}</p>` : ""}
      ${records.length
        ? `<div class="group kit-list">${records.map(row).join("")}</div>`
        : `<p class="empty mascot"><b>Nothing yet</b>No ${esc(model.label.toLowerCase())} you may see.</p>`}
    </main>` + tabs(at.tab));
  wireShell();
}

// -- the sheet -------------------------------------------------------------------------
/** What a data screen adds to the record sheet (kit.js's SHEETS): where back goes,
    and the sections under the fields. */
export function dataSheet(at, model) {
  return {
    parent: () => modelHash(at, model),
    backLabel: plural(model.label),
    section: (slot, record) => fillSections(at, model, record, slot),
  };
}

async function fillSections(at, model, record, slot) {
  const parts = [];
  if (model.id === SNAPSHOT) parts.push(await snapshotSection(record));
  if (model.space && at.quill.models[SNAPSHOT]) parts.push(await snapshotsOf(at, record));
  parts.push(await linkedHere(at, model, record));
  slot.innerHTML = parts.filter(Boolean).join("");
  const download = slot.querySelector(".bundle-download");
  if (download) download.addEventListener("click", () => downloadBundle(record.id));
}

const VERDICT = { validated: "good", qualified: "warn", rejected: "bad" };

async function snapshotSection(record) {
  let told;
  try { told = await api("GET", `/api/snapshots/${encodeURIComponent(record.id)}`); }
  catch (err) { return `<p class="group-label">Snapshot</p><p class="data-note">${esc(err.message)}</p>`; }
  const stamps = told.attestations.map((a) => {
    const f = a.fields;
    const who = f.signer_name + (f.signer_organisation ? `, ${f.signer_organisation}` : "");
    return `<div class="row attestation"><span class="main">` +
      `<span class="title"><span class="verdict ${VERDICT[f.verdict] || ""}">${esc(f.verdict)}</span> ${esc(who)}</span>` +
      `<span class="meta"><span class="date">${esc(String(f.signed_at).slice(0, 10))}</span>` +
      `<span class="preview">key ${esc(f.signer_fingerprint || "")}${f.statement ? ` · ${esc(f.statement)}` : ""}</span></span>` +
      `</span></div>`;
  });
  return `<p class="group-label">Snapshot</p>
    <div class="group data-snapshot">
      <div class="row"><span class="main"><span class="title">Digest</span><span class="meta"><span class="preview digest">${esc(told.digest || "")}</span></span></span></div>
      <div class="row"><span class="main"><span class="title">Bundle</span><span class="meta"><span class="preview">${
        told.intact ? `<span class="verdict good">intact</span>` : `<span class="verdict bad">does not match its digest</span>`
      } · ${esc(count(told.size || 0, "byte"))}</span></span></span><button type="button" class="chip bundle-download">Download</button></div>
    </div>
    <p class="group-label">Attestations</p>
    ${stamps.length ? `<div class="group kit-list">${stamps.join("")}</div>`
      : `<p class="data-note">Nobody has given their word on this snapshot yet.</p>`}`;
}

async function downloadBundle(id) {
  try {
    const res = await apiRaw("GET", `/api/snapshots/${encodeURIComponent(id)}/bundle`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `snapshot-${id}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) { toast(err.message); }
}

async function snapshotsOf(at, record) {
  const snapshot = at.quill.models[SNAPSHOT];
  let found;
  try { found = await api("GET", `${recordsUrl(SNAPSHOT)}?of_space=${encodeURIComponent(record.id)}`); }
  catch { return ""; }
  if (!found.length) return "";
  const rows = found.map((s) => {
    const f = s.fields;
    const series = f.series ? `${f.series} v${f.version || 1} · ` : "";
    return `<a class="row" href="${esc(recordHash(at, snapshot, s.id))}"><span class="main">` +
      `<span class="title">${esc(titleOf(snapshot, s))}</span>` +
      `<span class="meta"><span class="preview">${esc(series)}${esc(f.status || "")} · ${esc(String(f.sealed_at || "").slice(0, 10))}</span></span>` +
      `</span>${icons.chevronRight}</a>`;
  });
  return `<p class="group-label">Snapshots of it</p><div class="group kit-list">${rows.join("")}</div>`;
}

/** The records of other datamodels that link to this one, a datamodel at a time. */
async function linkedHere(at, model, record) {
  const parts = [];
  for (const other of Object.values(at.quill.models)) {
    // An attestation is shown with its snapshot above, as what it is.
    if (model.id === SNAPSHOT && other.id === ATTESTATION) continue;
    for (const f of other.fields) {
      if (f.kind !== "link" || f.to !== model.id) continue;
      let found;
      try {
        found = await api("GET", `${recordsUrl(other.id)}?${encodeURIComponent(f.name)}=${encodeURIComponent(record.id)}&_last=${LINKED_SHOWN}`);
      } catch { continue; }
      if (!found.length) continue;
      const under = underFields(other).filter((u) => u.name !== f.name);
      const links = await linkTitles(at.quill, under.filter((u) => u.kind === "link"));
      const rows = found.map((r) => {
        const said = under.map((u) => spoken(u, r.fields[u.name], links[u.name])).filter(Boolean);
        return `<a class="row" href="${esc(recordHash(at, other, r.id))}"><span class="main">` +
          `<span class="title">${esc(titleOf(other, r))}</span>` +
          (said.length ? `<span class="meta"><span class="preview">${esc(said.join(" · "))}</span></span>` : "") +
          `</span>${icons.chevronRight}</a>`;
      });
      const label = f.name === other.in_space ? plural(other.label) : `${plural(other.label)} · ${f.label}`;
      const more = found.length >= LINKED_SHOWN ? ` <span class="data-more">(the newest ${LINKED_SHOWN})</span>` : "";
      parts.push(`<p class="group-label">${esc(label)}${more}</p><div class="group kit-list">${rows.join("")}</div>`);
    }
  }
  return parts.join("");
}
