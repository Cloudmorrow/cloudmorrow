/* The kit's list, picked through: a `list` screen with a `group`, and
   perhaps a `subgroup` under it, and the kit's way with a secret field.

   A group is a row of chips across the top, one per value of its field:
   the records a link points at, an enum's values, or — for an indexed
   string — the values the records have, with "+ New" on the end to name
   another. A subgroup is a second row, of the values inside the chosen
   group. The rows below are the records in both, and a new one goes into
   both. The address says which: #/q/<quill>/<screen>/<group>/<subgroup>.

   A field the datamodel marks `secret` is never in a listing; the server
   sends it as null. So a row says it is there — dots — and a tap on the
   eye fetches that one record and shows it, until tapped again or the
   screen is left. The copy button fetches it without showing it. On the
   record sheet it is a password box with the same eye.

   Nothing here knows what it is drawing: a vault and an environment are a
   group and a subgroup, as a customer and a project would be. */

import { api, app, esc, go, heading, icons, nav, replace, store, tabs, toast, wireShell } from "./core.js";
import { installCard } from "./install.js";
import {
  aOr, circle, fieldOf, linkTitles, recordsUrl, sheetHash, spoken, timeLeft, titleField, titleOf, wireAdd,
} from "./kit.js";

export const MASK = "••••••••";

export const secretIcons = {
  show: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>',
  hide: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M10.6 5.1A10 10 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.1 3.9M6.6 6.6C3.7 8.4 2 12 2 12s3.6 7 10 7a9.7 9.7 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2M3 3l18 18"/></svg>',
  copy: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="1"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/></svg>',
};

/** Whether a list screen is drawn here rather than by kit.js's plain list. */
export const drawsHere = (model, screen) =>
  !!(screen.group || (screen.subtitle && (fieldOf(model, screen.subtitle) || {}).secret));

/** The record sheet's widget for a secret field: a password box and the eye. */
export function secretWidget(f, value) {
  return `<span class="secret-field"><input type="password" data-field="${esc(f.name)}"` +
    ` aria-label="${esc(f.label)}" value="${esc(value ?? "")}" autocomplete="off" spellcheck="false"` +
    ` placeholder="${f.required ? "" : "hidden"}">` +
    `<button type="button" class="reveal" aria-label="Show ${esc(f.label.toLowerCase())}" aria-pressed="false">${secretIcons.show}</button></span>`;
}

/** The eyes on a sheet: each shows its box, or hides it again. */
export function wireSecretWidgets(root) {
  for (const button of root.querySelectorAll(".secret-field .reveal")) {
    button.addEventListener("click", () => {
      const input = button.parentElement.querySelector("input");
      const shown = input.type === "password";
      input.type = shown ? "text" : "password";
      button.innerHTML = shown ? secretIcons.hide : secretIcons.show;
      button.setAttribute("aria-pressed", String(shown));
    });
  }
}

// -- the levels ------------------------------------------------------------------------
/** What a level offers, as [value, label] pairs, in order. */
async function choicesOf(quill, f, records) {
  if (f.kind === "link") {
    const target = quill.models[f.to];
    if (!target) return [];
    return (await api("GET", recordsUrl(target.id))).map((r) => [r.id, titleOf(target, r)]);
  }
  if (f.kind === "enum") return f.values.map((v, i) => [v, (f.labels && f.labels[i]) || v]);
  const seen = new Set(records.map((r) => r.fields[f.name]).filter((v) => v !== null && v !== undefined && v !== ""));
  return [...seen].sort((a, b) => String(a).localeCompare(String(b))).map((v) => [v, String(v)]);
}

/** The value a level stands on: the one asked for, else the one you had, else the default, else the first. */
function pick(choices, asked, remembered, fallback) {
  const has = (v) => v && choices.some(([c]) => c === v);
  if (asked) return asked;
  if (has(remembered)) return remembered;
  if (has(fallback)) return fallback;
  return choices.length ? choices[0][0] : fallback || null;
}

export async function renderGroupedList(at, arg) {
  const { quill, screen } = at;
  const model = quill.models[screen.model];
  const title = titleField(at, model);
  const tick = screen.tick ? fieldOf(model, screen.tick) : null;
  const under = screen.subtitle ? fieldOf(model, screen.subtitle) : null;
  const levels = [screen.group, screen.subgroup].map((n) => (n ? fieldOf(model, n) : null)).filter(Boolean);
  const asked = String(arg || "").split("/").filter(Boolean);
  const remembered = (() => { try { return JSON.parse(store.get("kit." + at.tab) || "[]"); } catch { return []; } })();

  let all = await api("GET", recordsUrl(model.id));
  const links = under && under.kind === "link" ? await linkTitles(quill, [under]) : {};

  // Each level's choices are the ones inside the level above it.
  const chosen = [];
  const offered = [];
  let inside = all;
  for (const [i, f] of levels.entries()) {
    const choices = await choicesOf(quill, f, inside);
    const value = pick(choices, asked[i], remembered[i], f.default);
    // A value nothing has yet — a vault just named — is still somewhere to stand.
    if (value !== null && !choices.some(([c]) => c === value)) choices.push([value, String(value)]);
    chosen.push(value);
    offered.push(choices);
    inside = inside.filter((r) => value === null || r.fields[f.name] === value);
  }
  try { store.set("kit." + at.tab, JSON.stringify(chosen)); } catch { /* private window */ }
  const here = () => all.filter((r) => levels.every((f, i) => chosen[i] === null || r.fields[f.name] === chosen[i]));
  const hashFor = (values) => at.base + values.map((v) => "/" + encodeURIComponent(v)).join("");
  if (asked.length && asked.some((v, i) => v !== chosen[i])) replace(hashFor(chosen));

  const chipRow = (f, i) => `<div class="chips${i ? " sub" : ""}" data-level="${i}">` +
    offered[i].map(([value, label]) => `<a class="chip${value === chosen[i] ? " active" : ""}" href="${
      esc(hashFor([...chosen.slice(0, i), value]))}">${esc(label)}</a>`).join("") +
    `<button class="chip new-group" type="button" data-level="${i}">+ New ${esc(f.label.toLowerCase())}</button></div>`;
  const where = chosen.filter((v) => v !== null).map((v, i) =>
    levels[i].kind === "link" ? (offered[i].find(([c]) => c === v) || [v, v])[1] : String(v));

  app.innerHTML = nav({ title: screen.label }) + `
    <main>
      ${heading(screen.label, `<button class="compose" aria-label="New ${esc(model.label.toLowerCase())}">${icons.compose}</button>`)}
      ${levels.map(chipRow).join("")}
      <form class="add">${tick ? circle("") : ""}<input placeholder="Add ${esc(aOr(model.label))}${
        where.length ? ` to ${esc(where.join(" · "))}` : ""}" autocapitalize="off" autocomplete="off" spellcheck="false" enterkeyhint="done"></form>
      <div class="install-slot">${installCard()}</div>
      <div class="listing"></div>
    </main>` + tabs(at.tab);
  wireShell();
  const listing = app.querySelector(".listing");
  // What has been revealed, by record id, for as long as this screen is up.
  const revealed = new Map();

  const underText = (r) => {
    if (!under) return "";
    if (under.secret) {
      const value = revealed.get(r.id);
      return value === undefined
        ? `<span class="preview mask" aria-label="Hidden">${MASK}</span>`
        : `<span class="preview shown">${esc(value || "(empty)")}</span>`;
    }
    const said = spoken(under, r.fields[under.name], links[under.name]);
    return said ? `<span class="preview">${esc(said)}</span>` : "";
  };
  const row = (r) => {
    const left = timeLeft(r.expires_at);
    const meta = (left ? `<span class="date expires">${left}</span>` : "") + underText(r);
    const text = `<span class="title">${esc(titleOf(model, r, title))}</span>${meta ? `<span class="meta">${meta}</span>` : ""}`;
    const on = tick && !!r.fields[tick.name];
    const eyes = under && under.secret
      ? `<button class="reveal" data-id="${esc(r.id)}" aria-label="${revealed.has(r.id) ? "Hide" : "Show"} ${esc(under.label.toLowerCase())}" aria-pressed="${revealed.has(r.id)}">${revealed.has(r.id) ? secretIcons.hide : secretIcons.show}</button>` +
        `<button class="copy" data-id="${esc(r.id)}" aria-label="Copy ${esc(under.label.toLowerCase())}">${secretIcons.copy}</button>`
      : "";
    return `<div class="row card grouped${on ? " is-done" : ""}${tick ? "" : " no-tick"}">` +
      (tick ? `<button class="tick" data-id="${esc(r.id)}" aria-label="${esc(tick.label)}" aria-pressed="${on}">${circle(on ? "done" : "")}</button>` : "") +
      `<a class="main" href="${sheetHash(at, model.id, r.id)}">${text}</a>${eyes}</div>`;
  };
  const show = () => {
    const rows = here();
    if (!rows.length) {
      const place = where.length ? ` in ${esc(where.join(" · "))}` : "";
      listing.innerHTML = `<p class="empty mascot"><b>Nothing${place} yet</b>Add ${esc(aOr(model.label))} above, and it will show up here.</p>`;
      return;
    }
    listing.innerHTML = `<div class="group kit-list">${rows.map(row).join("")}</div>`;
    for (const button of listing.querySelectorAll(".tick")) button.addEventListener("click", () => flip(button.dataset.id));
    for (const button of listing.querySelectorAll(".reveal")) button.addEventListener("click", () => reveal(button.dataset.id));
    for (const button of listing.querySelectorAll(".copy")) button.addEventListener("click", () => copy(button.dataset.id));
  };

  const valueOf = async (id) => {
    if (revealed.has(id)) return revealed.get(id);
    const one = await api("GET", recordsUrl(model.id, id));
    return one.fields[under.name] ?? "";
  };
  const reveal = async (id) => {
    if (revealed.has(id)) revealed.delete(id);
    else {
      try { revealed.set(id, await valueOf(id)); } catch (err) { toast(err.message); return; }
    }
    show();
  };
  const copy = async (id) => {
    try {
      await navigator.clipboard.writeText(await valueOf(id));
      toast("Copied");
    } catch (err) { toast(err.message || "Could not copy"); }
  };
  const flip = async (id) => {
    const record = all.find((r) => r.id === id);
    if (!record) return;
    try {
      const changed = await api("PATCH", recordsUrl(model.id, id),
        { fields: { [tick.name]: !record.fields[tick.name] }, rev: record.rev });
      all = all.map((r) => (r.id === id ? changed : r));
    } catch (err) {
      toast(err.status === 409 ? "That changed somewhere else" : err.message);
      all = await api("GET", recordsUrl(model.id));
    }
    show();
  };
  show();

  // A new record goes into the group and subgroup on screen, and opens, so
  // what the add row has no room for — a value, a date — is typed next.
  wireAdd(async (text) => {
    const fields = { [title]: text };
    levels.forEach((f, i) => { if (chosen[i] !== null) fields[f.name] = chosen[i]; });
    const made = await api("POST", recordsUrl(model.id), { fields });
    go(sheetHash(at, model.id, made.id));
  });

  for (const button of app.querySelectorAll(".new-group")) {
    button.addEventListener("click", () => newValue(Number(button.dataset.level)));
  }
  async function newValue(i) {
    const f = levels[i];
    if (f.kind === "enum") { toast(`${f.label} is one of the chips`); return; }
    const text = (prompt(`New ${f.label.toLowerCase()}`) || "").trim();
    if (!text) return;
    let value = text.toLowerCase();
    if (f.kind === "link") {
      const target = quill.models[f.to];
      try {
        value = (await api("POST", recordsUrl(target.id), { fields: { [target.title]: text } })).id;
      } catch (err) { toast(err.message); return; }
    }
    // A name with nothing in it yet: the list is empty there until the first is added.
    go(hashFor([...chosen.slice(0, i), value]));
  }
}
