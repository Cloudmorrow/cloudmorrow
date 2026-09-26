/* Spaces in the kit: what more than one person shares, and the people in it.

   A channel, a shared calendar, a household's list — any datamodel that is
   a `space` — has the same few things around it, and they are drawn here
   once for every kit element that has spaces:

     renderNewSpace   make one: its name, its other fields, who can see it
                      (a scope), and for a shared one the people in it
     renderWriteTo    pick a person, and the space between the two of you
                      is found, or made (`made_as.direct` on the screen)
     renderSpaceAbout what one is: its fields, who is in it; add somebody,
                      take somebody out, leave, edit, delete — each only
                      where the server would say yes

   Everything is read from the datamodel and the screen's `made_as`, which
   says what fields a space gets for how it was made:

     made_as = { public = { kind = "public" }, shared = { kind = "private" },
                 direct = { kind = "direct" } }

   Nothing here knows what a channel is. `at` is quills.js's place:
   {quill, screen, tab, base}. */

import { api, app, esc, heading, icons, nav, onSignOut, session, toast, wireShell } from "./core.js";

export const recordsUrl = (model, id = "", rest = "") =>
  "/api/records/" + encodeURIComponent(model) + (id ? "/" + encodeURIComponent(id) : "") + rest;

/** How the screen says spaces are made: scope (or `direct`) → the fields it sets. */
export const madeAs = (screen) => screen.made_as || {};

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

let peopleCache = null;
onSignOut(() => { peopleCache = null; });
/** Everybody else on the server, asked once per page. */
export async function people() {
  if (!peopleCache) peopleCache = api("GET", "/api/people").catch((err) => { peopleCache = null; throw err; });
  return peopleCache;
}

// What each scope means, said to the person choosing it.
const SCOPE_WORDS = {
  public: ["Public", "Everybody on this server is in it and can write in it. Nobody leaves."],
  shared: ["Private", "Only the people you pick, and you. They are added, not invited — they are told, and can leave."],
  personal: ["Only you", "Nobody else sees it."],
};

/** A scope's name: the label of the enum value `made_as` gives it, when it gives one. */
function scopeLabel(model, screen, scope) {
  const set = madeAs(screen)[scope] || {};
  for (const [name, value] of Object.entries(set)) {
    const f = model.fields.find((x) => x.name === name);
    if (f && f.kind === "enum") {
      const at = f.values.indexOf(value);
      if (at !== -1) return (f.labels && f.labels[at]) || value;
    }
  }
  return SCOPE_WORDS[scope] ? SCOPE_WORDS[scope][0] : scope;
}

/** The scopes a new space may be made as: `made_as`'s, else the datamodel's. */
function scopesFor(model, screen) {
  const made = Object.keys(madeAs(screen)).filter((how) => how !== "direct");
  return (made.length ? made : model.scopes).filter((s) => model.scopes.includes(s));
}

/** The fields a person types when making one: the title, and the plain text ones. */
function typedFields(model, screen) {
  const set = new Set(Object.values(madeAs(screen)).flatMap((f) => Object.keys(f)));
  return model.fields.filter((f) => f.name !== model.title && !set.has(f.name) &&
    ["string", "text", "markdown", "url", "email", "phone"].includes(f.kind) && !f.stamp);
}

const personLabel = (p) => p.display_name && p.display_name !== p.username
  ? `${p.display_name} (${p.username})` : p.username;

// -- making one ---------------------------------------------------------------------
export async function renderNewSpace(at, model, { back, backLabel, opened }) {
  const { screen } = at;
  const everyone = await people().catch(() => []);
  const scopes = scopesFor(model, screen);
  const first = scopes.includes("public") ? "public" : scopes[0];
  const extra = typedFields(model, screen);
  const noun = model.label.toLowerCase();
  const title = model.fields.find((f) => f.name === model.title);
  app.innerHTML = nav({ back, backLabel, title: `New ${noun}` }) + `
    <main>
      <h1 class="large">New ${esc(noun)}</h1>
      <form class="new-space">
        <div class="group">
          <label class="row"><span class="main">${esc(title ? title.label : "Name")}</span>
            <input name="title" autocapitalize="none" required></label>
          ${extra.map((f) => `<label class="row"><span class="main">${esc(f.label)}</span>
            <input name="${esc(f.name)}" placeholder="optional"></label>`).join("")}
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
  const whoList = app.querySelector(".who-list");
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
    const fields = { [model.title]: name, ...(madeAs(screen)[scope] || {}) };
    for (const f of extra) {
      const value = form.elements[f.name].value.trim();
      if (value) fields[f.name] = value;
    }
    // A tick made before switching away from Private is not one.
    const members = scope === "shared"
      ? [...form.querySelectorAll('input[name="member"]:checked')].map((b) => b.value) : [];
    try {
      const made = await api("POST", recordsUrl(model.id), { fields, scope, members });
      opened(made);
    } catch (err) { toast(err.message); }
  });
}

// -- writing to somebody -------------------------------------------------------------
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

// -- what one is, and who is in it ------------------------------------------------------
export async function renderSpaceAbout(at, model, id, { back, backLabel, gone }) {
  const { screen } = at;
  let space;
  try { space = await api("GET", recordsUrl(model.id, id)); }
  catch (err) {
    if (err.status !== 404) throw err;
    toast(`That ${model.label.toLowerCase()} is gone`);
    return gone();
  }
  const me = session.user;
  const two = isBetween(screen, space);
  const shared = space.scope === "shared";
  const inIt = peopleIn(space).includes(me);
  const name = spaceName(model, space, screen);
  const set = new Set(Object.values(madeAs(screen)).flatMap((f) => Object.keys(f)));
  const facts = [
    ["Who can see it", two ? "The two of you" : space.scope === "public" ? "Everybody on this server"
      : shared ? "The people in it" : "Only its owner"],
    ...model.fields.filter((f) => f.name !== model.title && !set.has(f.name) && f.kind !== "link" &&
      space.fields[f.name] !== null && space.fields[f.name] !== undefined && space.fields[f.name] !== "")
      .map((f) => [f.label, String(space.fields[f.name])]),
    !two && ["Made by", space.owner === me ? "You" : space.owner],
  ].filter(Boolean);
  const canAdd = shared && !two && (space.can_manage || inIt);
  const outside = canAdd ? (await people().catch(() => [])).filter((p) => !peopleIn(space).includes(p.username)) : [];
  const sheet = `#/r/${encodeURIComponent(at.quill.id)}/${encodeURIComponent(screen.id)}/${encodeURIComponent(model.id)}/${encodeURIComponent(id)}`;

  app.innerHTML = nav({ back, backLabel, title: "About" }) + `
    <main>
      ${heading(name, space.can_manage && !two ? `<a class="button edit" href="${sheet}" aria-label="Edit ${esc(model.label.toLowerCase())}">${icons.compose}</a>` : "")}
      <div class="group facts">${facts.map(([label, value]) =>
        `<div class="row"><span class="main">${esc(label)}</span><span class="fact">${esc(value)}</span></div>`).join("")}</div>
      ${space.scope === "public" ? "" : `
      <p class="group-label">In here (${peopleIn(space).length})</p>
      <div class="group members">${peopleIn(space).map((who) => `
        <div class="row"><span class="avatar" aria-hidden="true">${esc(who.charAt(0).toUpperCase())}</span>
          <span class="main">${esc(who)}${who === me ? " (you)" : ""}${who === space.owner && !two ? ' <span class="muted">made it</span>' : ""}</span>
          ${space.can_manage && shared && !two && who !== space.owner
            ? `<button class="value remove-who" data-who="${esc(who)}">Remove</button>` : ""}</div>`).join("")}</div>`}
      ${outside.length ? `
        <p class="group-label">Add somebody</p>
        <div class="group">${outside.map((p) => `
          <button class="row add-who" data-who="${esc(p.username)}">
            <span class="main">${esc(personLabel(p))}</span><span class="value">Add</span></button>`).join("")}</div>` : ""}
      ${shared && !two && inIt && me !== space.owner ? `<div class="group"><button class="row bad leave">Leave</button></div>` : ""}
      ${space.can_manage && !two ? `<div class="group"><button class="row bad delete">Delete</button></div>` : ""}
    </main>`;
  wireShell();
  const again = () => renderSpaceAbout(at, model, id, { back, backLabel, gone });

  for (const button of app.querySelectorAll(".add-who")) {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await api("POST", recordsUrl(model.id, id, "/members"), { username: button.dataset.who });
        toast(`${button.dataset.who} is in`);
        again();
      } catch (err) { toast(err.message); button.disabled = false; }
    });
  }
  for (const button of app.querySelectorAll(".remove-who")) {
    button.addEventListener("click", async () => {
      if (!confirm(`Take ${button.dataset.who} out of ${name}?`)) return;
      try {
        await api("DELETE", recordsUrl(model.id, id, "/members/" + encodeURIComponent(button.dataset.who)));
        again();
      } catch (err) { toast(err.message); }
    });
  }
  const leave = app.querySelector(".leave");
  if (leave) {
    leave.addEventListener("click", async () => {
      if (!confirm(`Leave ${name}? Somebody in it can add you back.`)) return;
      try {
        await api("DELETE", recordsUrl(model.id, id, "/members/" + encodeURIComponent(me)));
        gone();
      } catch (err) { toast(err.message); }
    });
  }
  const del = app.querySelector(".delete");
  if (del) {
    del.addEventListener("click", async () => {
      if (!confirm(`Delete ${name}? Everything in it goes too.`)) return;
      try {
        await api("DELETE", recordsUrl(model.id, id));
        gone();
      } catch (err) { toast(err.message); }
    });
  }
}
