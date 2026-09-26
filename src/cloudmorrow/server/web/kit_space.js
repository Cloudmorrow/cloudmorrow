/* Spaces in the kit: the list of them, making one, and who is in one.

   A space is a record more than one person may be in — a calendar, a
   channel (docs/QUILLS.md, *Spaces*). It is personal (its owner's alone),
   shared (its owner's and its members'), or public (everybody's). Every
   kit element that draws things in spaces uses what is here rather than
   its own:

     renderSpaceList   every space you can see, grouped by who can see it
     renderNewSpace    make one: its name, its other plain fields, who can
                       see it (a scope), and for a shared one its people
     renderWriteTo     pick a person, and the space between the two of you
                       is found, or made (`made_as.direct` on the screen)
     renderSpaceAbout  what one is and who is in it, for a screen that
                       does not open spaces on the record sheet
     spaceSection      the people part of a space's page — who can see it,
     wireSpace         who is in it, add, take out, leave — on the record
                       sheet (kit.js) and on renderSpaceAbout alike

   A screen may say how spaces are made in `made_as`: scope (or `direct`)
   → the fields a space gets when made that way —

     made_as = { public = { kind = "public" }, shared = { kind = "private" },
                 direct = { kind = "direct" } }

   Nothing here knows what any space is for. The words come from the
   datamodel's label; the record's `scope`, `members` and `can_manage` are
   what the record API sends for every space. `at` is quills.js's place:
   {quill, screen, tab, base}. */

import {
  api, app, esc, heading, icons, nav, onSignOut, renderRoute, replace, session, tabs, toast,
  wireShell,
} from "./core.js";
import { sheetHash } from "./kit.js";

export const recordsUrl = (model, id = "", rest = "") =>
  "/api/records/" + encodeURIComponent(model) + (id ? "/" + encodeURIComponent(id) : "") + rest;

// -- reading a space ---------------------------------------------------------------------
/** How the screen says spaces are made: scope (or `direct`) → the fields it sets. */
export const madeAs = (screen) => (screen && screen.made_as) || {};

/** Is this a space made between people — named for whoever else is in it? */
export function isBetween(screen, space) {
  const marks = madeAs(screen).direct;
  if (!marks || !space) return false;
  return Object.entries(marks).every(([name, value]) => space.fields[name] === value);
}

/** Everybody in a space: its owner, then the people added to it. */
export const peopleIn = (space) => [space.owner, ...(space.members || [])];

/** What a space is called, to whoever is looking. */
export function spaceName(model, space, screen, me = session.user) {
  if (isBetween(screen, space)) {
    const others = peopleIn(space).filter((who) => who !== me);
    return others.join(", ") || me;
  }
  return String(space.fields[model.title] || "").trim() || "Untitled";
}

/** The square beside a space: an initial for a person, a # for a room. */
export function spaceMark(model, space, screen, me = session.user) {
  if (isBetween(screen, space)) {
    const name = spaceName(model, space, screen, me);
    return `<span class="avatar" aria-hidden="true">${esc(name.charAt(0).toUpperCase() || "?")}</span>`;
  }
  return `<span class="hash" aria-hidden="true">#</span>`;
}

/** Who can see a space, said the way a person would. */
export function scopeSaid(record) {
  if (record.scope === "personal") return "Only you";
  if (record.scope === "public") return "Everybody here";
  const count = (record.members || []).length + 1;
  return `${count} ${count === 1 ? "person" : "people"}`;
}

// Everybody a space could be shared with, asked once per page load.
let peopleCache = null;
onSignOut(() => { peopleCache = null; });
export function people() {
  if (!peopleCache) peopleCache = api("GET", "/api/people").catch((err) => { peopleCache = null; throw err; });
  return peopleCache;
}

const personLabel = (p) => p.display_name && p.display_name !== p.username
  ? `${p.display_name} (${p.username})` : p.username;

// -- the list ------------------------------------------------------------------------
/** Every space of *model* you can see: yours, the shared ones, everybody's.
    *dot* draws what goes before a name (a calendar's colour). */
export async function renderSpaceList(at, model, { dot = () => "", back, backLabel } = {}) {
  const spaces = await api("GET", recordsUrl(model.id));
  const plural = `${model.label}s`;
  const row = (s) => `<a class="row has-icon" href="${sheetHash(at, model.id, s.id)}">
      <span class="icon">${dot(s)}</span>
      <span class="main"><span class="title">${esc(spaceName(model, s, at.screen))}</span>
        <span class="meta"><span class="preview">${esc(scopeSaid(s))}${
          s.owner !== session.user && s.scope !== "public" ? ` · ${esc(s.owner)}'s` : ""}</span></span></span>
      ${icons.chevronRight}</a>`;
  const group = (label, rows) => (rows.length
    ? `<p class="group-label">${label}</p><div class="group">${rows.map(row).join("")}</div>` : "");
  app.innerHTML = nav({ back, backLabel, title: plural }) + `
    <main>
      ${heading(plural, `<a class="button compose" href="${at.base}/newspace" aria-label="New ${esc(model.label.toLowerCase())}">${icons.compose}</a>`)}
      ${group("Yours", spaces.filter((s) => s.scope === "personal"))}
      ${group("Shared", spaces.filter((s) => s.scope === "shared"))}
      ${group("Everybody's", spaces.filter((s) => s.scope === "public"))}
      ${spaces.length ? "" : `<p class="empty mascot"><b>None yet</b>Make one with the pen above.</p>`}
    </main>` + tabs(at.tab);
  wireShell();
}

// -- making one ------------------------------------------------------------------------
// What each scope means, said to the person choosing it.
const SCOPE_WORDS = {
  public: ["Everybody's", "Everybody on this server is in it, and can put things in it. Nobody leaves."],
  shared: ["Shared", "Only the people you pick, and you. They are added, not invited — they are told, and can leave."],
  personal: ["Only you", "Nobody else sees it."],
};

/** A scope's name: the label of the enum value `made_as` gives it, when it gives one. */
function scopeLabel(model, screen, scope) {
  for (const [name, value] of Object.entries(madeAs(screen)[scope] || {})) {
    const f = model.fields.find((x) => x.name === name);
    if (f && f.kind === "enum") {
      const at = f.values.indexOf(value);
      if (at !== -1) return (f.labels && f.labels[at]) || value;
    }
  }
  return SCOPE_WORDS[scope] ? SCOPE_WORDS[scope][0] : scope;
}

/** The scopes a new space may be made as: `made_as`'s, else the datamodel's
    shared and public ones — a personal space is seeded, not made. */
export function scopesFor(model, screen) {
  const made = Object.keys(madeAs(screen)).filter((how) => how !== "direct");
  const wanted = made.length ? made : model.scopes.filter((s) => s !== "personal");
  // In the order the screen, or else the datamodel, gives them: the first is the one ticked.
  return wanted.filter((s) => model.scopes.includes(s));
}

/** The fields a person types when making one: the plain text ones `made_as` does not set. */
function typedFields(model, screen) {
  const set = new Set(Object.values(madeAs(screen)).flatMap((f) => Object.keys(f)));
  return model.fields.filter((f) => f.name !== model.title && !set.has(f.name) &&
    ["text", "markdown"].includes(f.kind) && !f.stamp);
}

/** A name, who can see it, and — for a shared one — who is in it. There is
    no invitation: the people ticked are in it, and are told. *fields* may
    add to what a new one starts with, given the ones there are; *opened*
    is where the new one goes (its record sheet, unless it says otherwise). */
export async function renderNewSpace(at, model, { back, backLabel, fields = async () => ({}), opened } = {}) {
  const { screen } = at;
  const [everyone, spaces] = await Promise.all([people().catch(() => []), api("GET", recordsUrl(model.id))]);
  const scopes = scopesFor(model, screen);
  const first = scopes[0] || "shared";
  const extra = typedFields(model, screen);
  const noun = model.label.toLowerCase();
  const title = model.fields.find((f) => f.name === model.title);
  app.innerHTML = nav({ back, backLabel: backLabel || `${model.label}s`, title: `New ${noun}` }) + `
    <main>
      <h1 class="large">New ${esc(noun)}</h1>
      <form class="new-space">
        <div class="group">
          <label class="row"><input name="title" placeholder="${esc(title ? title.label : "Name")}"
            aria-label="${esc(title ? title.label : "Name")}" autocapitalize="sentences" required></label>
          ${extra.map((f) => `<label class="row"><input name="${esc(f.name)}" placeholder="${esc(f.label)} (optional)"
            aria-label="${esc(f.label)}"></label>`).join("")}
        </div>
        ${scopes.length > 1 ? `<p class="group-label">Who can see it</p>
        <div class="group kinds">${scopes.map((scope) => `
          <label class="row"><input type="radio" name="scope" value="${esc(scope)}"${scope === first ? " checked" : ""}>
            <span class="main"><span class="title">${esc(scopeLabel(model, screen, scope))}</span>
            <span class="meta"><span class="preview">${esc((SCOPE_WORDS[scope] || ["", ""])[1])}</span></span></span></label>`).join("")}
        </div>` : `<input type="hidden" name="scope" value="${esc(first)}">`}
        <div class="who-list" hidden>
          <p class="group-label">People</p>
          <div class="group">${everyone.map((p) => `
            <label class="row"><input type="checkbox" name="member" value="${esc(p.username)}">
              <span class="main">${esc(personLabel(p))}</span></label>`).join("")
            || `<p class="empty"><b>Nobody else yet</b>You can add people once they have accounts.</p>`}</div>
        </div>
        <div class="group"><button class="row primary" type="submit">Make the ${esc(noun)}</button></div>
      </form>
    </main>`;
  wireShell();
  const form = app.querySelector("form.new-space");
  const whoList = form.querySelector(".who-list");
  const scopeNow = () => (form.querySelector('input[name="scope"]:checked') || form.elements.scope).value;
  const showWho = () => { whoList.hidden = scopeNow() !== "shared"; };
  for (const radio of form.querySelectorAll('input[name="scope"]')) radio.addEventListener("change", showWho);
  showWho();
  form.elements.title.focus();
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = form.elements.title.value.trim();
    if (!name) return;
    const scope = scopeNow();
    const made = { ...(await fields(spaces)), ...(madeAs(screen)[scope] || {}), [model.title]: name };
    for (const f of extra) {
      const value = form.elements[f.name].value.trim();
      if (value) made[f.name] = value;
    }
    // A tick made before switching away from a shared one is not one.
    const members = scope === "shared"
      ? [...form.querySelectorAll('input[name="member"]:checked')].map((b) => b.value) : [];
    try {
      const record = await api("POST", recordsUrl(model.id), { fields: made, scope, members });
      if (opened) opened(record);
      else { replace(sheetHash(at, model.id, record.id)); renderRoute(); }
    } catch (err) { toast(err.message); }
  });
}

// -- writing to somebody -------------------------------------------------------------
/** Pick a person; the space between you and them opens, found or made. */
export async function renderWriteTo(at, model, { back, backLabel, opened }) {
  const everyone = await people();
  app.innerHTML = nav({ back, backLabel, title: "New message" }) + `
    <main>
      <h1 class="large">New message</h1>
      ${everyone.length ? `<div class="group">${everyone.map((p) => `
        <button class="row person" data-who="${esc(p.username)}">
          <span class="avatar" aria-hidden="true">${esc((p.display_name || p.username).charAt(0).toUpperCase())}</span>
          <span class="main"><span class="title">${esc(p.display_name || p.username)}</span>
          ${p.display_name ? `<span class="meta"><span class="preview">${esc(p.username)}</span></span>` : ""}</span>
          ${icons.chevronRight}</button>`).join("")}</div>`
        : `<p class="empty"><b>Nobody else yet</b>There is only your account on this server.</p>`}
    </main>`;
  wireShell();
  for (const button of app.querySelectorAll(".person")) {
    button.addEventListener("click", async () => {
      try { opened(await between(at, model, [button.dataset.who])); } catch (err) { toast(err.message); }
    });
  }
}

/** The space between you and *others*: the one there is, or a new one. */
export async function between(at, model, others) {
  const names = [...new Set([session.user, ...others])].sort();
  return api("POST", recordsUrl(model.id), {
    fields: { [model.title]: names.join(" & "), ...(madeAs(at.screen).direct || {}) },
    scope: "shared",
    members: others,
    unique: true,
  });
}

// -- who is in one ------------------------------------------------------------------------
/** The people part of a space's page: who can see it, who is in it, the way
    to add somebody and take them out, and the way out yourself. *fixed*
    draws who is in it and nothing to change it with — a space between two
    people stays those two. */
export async function spaceSection(model, record, { fixed = false } = {}) {
  const shared = record.scope === "shared";
  const inIt = peopleIn(record);
  const mayAdd = shared && !fixed && (record.can_manage || inIt.includes(session.user));
  const outside = mayAdd ? (await people().catch(() => [])).filter((p) => !inIt.includes(p.username)) : [];
  const who = (name) => `<div class="row member"><span class="avatar" aria-hidden="true">${esc(name.charAt(0).toUpperCase())}</span>
      <span class="main">${esc(name)}${name === session.user ? " (you)" : ""}${name === record.owner && !fixed ? ` <span class="said">made it</span>` : ""}</span>
      ${shared && !fixed && record.can_manage && name !== record.owner
        ? `<button class="take-out" type="button" data-who="${esc(name)}" aria-label="Take ${esc(name)} out">Take out</button>` : ""}</div>`;
  return `<section class="space-people">
    <p class="group-label">Who can see it</p>
    <div class="group"><div class="row"><span class="main">${esc(fixed ? "The two of you" : scopeSaid(record))}</span>${
      record.scope === "public" || fixed ? "" : `<span class="said">${esc(record.owner === session.user ? "you made it" : `${record.owner} made it`)}</span>`}</div></div>
    ${shared ? `<p class="group-label">In it (${inIt.length})</p><div class="group members">${inIt.map(who).join("")}</div>` : ""}
    ${outside.length ? `<p class="group-label">Share it with</p>
      <div class="group">${outside.map((p) => `
        <button class="row add-who" type="button" data-who="${esc(p.username)}">
          <span class="main">${esc(personLabel(p))}</span><span class="said">Add</span></button>`).join("")}</div>` : ""}
    ${shared && !fixed && record.owner !== session.user && inIt.includes(session.user)
      ? `<div class="group"><button class="row bad leave" type="button">Leave this ${esc(model.label.toLowerCase())}</button></div>` : ""}
  </section>`;
}

/** The buttons *spaceSection* drew. *left* is where to go once you have
    left; *again* redraws the page after a change (the route, by default). */
export function wireSpace(root, model, record, { left, again = renderRoute } = {}) {
  const url = recordsUrl(model.id, record.id, "/members");
  const name = String(record.fields[model.title] || "").trim() || "it";
  for (const button of root.querySelectorAll(".add-who")) {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await api("POST", url, { username: button.dataset.who });
        toast(`${button.dataset.who} is in, and has been told`);
        again();
      } catch (err) { toast(err.message); button.disabled = false; }
    });
  }
  for (const button of root.querySelectorAll(".take-out")) {
    button.addEventListener("click", async () => {
      if (!confirm(`Take ${button.dataset.who} out of ${name}?`)) return;
      try {
        await api("DELETE", `${url}/${encodeURIComponent(button.dataset.who)}`);
        again();
      } catch (err) { toast(err.message); }
    });
  }
  const leave = root.querySelector(".leave");
  if (leave) {
    leave.addEventListener("click", async () => {
      if (!confirm(`Leave ${name}? You will stop seeing what is in it. Somebody in it can add you back.`)) return;
      try {
        await api("DELETE", `${url}/${encodeURIComponent(session.user)}`);
        replace(left);
        renderRoute();
      } catch (err) { toast(err.message); }
    });
  }
}

// -- what one is, for a screen that opens spaces in place ---------------------------------------
/** A space's facts and its people, with edit (its record sheet) and delete
    for whoever manages it. *gone* is where to go once it is gone or left. */
export async function renderSpaceAbout(at, model, id, { back, backLabel, gone }) {
  const { screen } = at;
  let space;
  try { space = await api("GET", recordsUrl(model.id, id)); }
  catch (err) {
    if (err.status !== 404) throw err;
    toast(`That ${model.label.toLowerCase()} is gone`);
    return gone();
  }
  const two = isBetween(screen, space);
  const name = spaceName(model, space, screen);
  const set = new Set(Object.values(madeAs(screen)).flatMap((f) => Object.keys(f)));
  const facts = model.fields.filter((f) => f.name !== model.title && !set.has(f.name) && f.kind !== "link" &&
    space.fields[f.name] !== null && space.fields[f.name] !== undefined && space.fields[f.name] !== "")
    .map((f) => [f.label, String(space.fields[f.name])]);
  const people = await spaceSection(model, space, { fixed: two });
  app.innerHTML = nav({ back, backLabel, title: "About" }) + `
    <main>
      ${heading(name, space.can_manage && !two ? `<a class="button edit" href="${sheetHash(at, model.id, id)}" aria-label="Edit ${esc(model.label.toLowerCase())}">${icons.compose}</a>` : "")}
      ${facts.length ? `<div class="group facts">${facts.map(([label, value]) =>
        `<div class="row"><span class="main">${esc(label)}</span><span class="said">${esc(value)}</span></div>`).join("")}</div>` : ""}
      ${people}
      ${space.can_manage && !two ? `<div class="group"><button class="row bad delete">Delete this ${esc(model.label.toLowerCase())}</button></div>` : ""}
    </main>`;
  wireShell();
  const leftTo = () => { gone(); };
  // Out of it, you are back at the screen's start: it is not yours to open any more.
  wireSpace(app, model, space, { left: at.base, again: () => renderSpaceAbout(at, model, id, { back, backLabel, gone }) });
  const del = app.querySelector(".delete");
  if (del) {
    del.addEventListener("click", async () => {
      if (!confirm(`Delete ${name}? Everything in it goes too.`)) return;
      try {
        await api("DELETE", recordsUrl(model.id, id));
        leftTo();
      } catch (err) { toast(err.message); }
    });
  }
}
