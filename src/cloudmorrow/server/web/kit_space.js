/* Spaces in the kit: the list of them, making one, and who is in one.

   A space is a record more than one person may be in — a calendar, a
   channel (docs/QUILLS.md, *Spaces*). It is personal (its owner's alone),
   shared (its owner's and its members'), or public (everybody's). Every
   kit element that draws things in spaces uses what is here rather than
   its own: the list grouped by who can see each, the page for making one
   with its scope and its people, and the part of a space's record sheet
   that says who is in it, adds somebody, takes somebody out, and leaves.

   Nothing here knows what any space is for. The words come from the
   datamodel's label; the record's `scope`, `members` and `can_manage` are
   what the record API sends for every space. */

import {
  api, app, esc, heading, icons, nav, renderRoute, replace, session, tabs, toast, wireShell,
} from "./core.js";
import { sheetHash } from "./kit.js";

const recordsUrl = (model, id) =>
  "/api/records/" + encodeURIComponent(model) + (id ? "/" + encodeURIComponent(id) : "");
const nameOf = (model, record) => String(record.fields[model.title] || "").trim() || "Untitled";

// Everybody a space could be shared with, asked once per page that wants it.
const people = () => api("GET", "/api/people");

/** Who can see a space, said the way a person would. */
export function scopeSaid(record) {
  if (record.scope === "personal") return "Only you";
  if (record.scope === "public") return "Everybody here";
  const count = (record.members || []).length + 1;
  return `${count} ${count === 1 ? "person" : "people"}`;
}

// -- the list ------------------------------------------------------------------------
/** Every space of *model* you can see: yours, the shared ones, everybody's.
    *dot* draws what goes before a name (a calendar's colour). */
export async function renderSpaceList(at, model, { dot = () => "", back, backLabel } = {}) {
  const spaces = await api("GET", recordsUrl(model.id));
  const plural = `${model.label}s`;
  const row = (s) => `<a class="row has-icon" href="${sheetHash(at, model.id, s.id)}">
      <span class="icon">${dot(s)}</span>
      <span class="main"><span class="title">${esc(nameOf(model, s))}</span>
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
/** A name, who can see it, and — for a shared one — who is in it. There is
    no invitation: the people ticked are in it, and are told. *fields* may
    add to what a new one starts with, given the ones there are. */
export async function renderNewSpace(at, model, { back, fields = async () => ({}) } = {}) {
  const [everyone, spaces] = await Promise.all([people(), api("GET", recordsUrl(model.id))]);
  const scopes = model.scopes.filter((s) => s !== "personal");
  const said = {
    shared: ["Shared", "Only the people you pick. They are added, not invited."],
    public: ["Everybody's", "Everyone here sees it, and can put things in it."],
  };
  const noun = model.label.toLowerCase();
  app.innerHTML = nav({ back, backLabel: `${model.label}s`, title: `New ${noun}` }) + `
    <main>
      <h1 class="large">New ${esc(noun)}</h1>
      <form class="new-space">
        <div class="group">
          <label class="row"><input name="name" placeholder="Name" aria-label="Name"
            autocapitalize="sentences" required></label>
        </div>
        ${scopes.length > 1 ? `<p class="group-label">Who can see it</p>
        <div class="group kinds">${scopes.map((s, i) => `
          <label class="row"><input type="radio" name="scope" value="${s}"${i === 0 ? " checked" : ""}>
            <span class="main"><span class="title">${esc((said[s] || [s])[0])}</span>
            <span class="meta"><span class="preview">${esc((said[s] || ["", ""])[1])}</span></span></span></label>`).join("")}
        </div>` : `<input type="hidden" name="scope" value="${esc(scopes[0] || "shared")}">`}
        <div class="who-list">
          <p class="group-label">People</p>
          <div class="group">${everyone.map((p) => `
            <label class="row"><input type="checkbox" name="member" value="${esc(p.username)}">
              <span class="main">${esc(p.display_name || p.username)}</span></label>`).join("")
            || `<p class="empty"><b>Nobody else yet</b>Make an account for them first.</p>`}</div>
        </div>
        <div class="group"><button class="row primary" type="submit">Make the ${esc(noun)}</button></div>
      </form>
    </main>`;
  wireShell();
  const form = app.querySelector("form.new-space");
  const whoList = form.querySelector(".who-list");
  const scopeOf = () => (form.querySelector('input[name="scope"]:checked') || form.elements.scope).value;
  const showWho = () => { whoList.hidden = scopeOf() !== "shared"; };
  for (const radio of form.querySelectorAll('input[name="scope"]')) radio.addEventListener("change", showWho);
  showWho();
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = form.elements.name.value.trim();
    if (!name) return;
    const scope = scopeOf();
    const members = scope === "shared"
      ? [...form.querySelectorAll('input[name="member"]:checked')].map((b) => b.value) : [];
    try {
      const made = await api("POST", recordsUrl(model.id), {
        fields: { ...(await fields(spaces)), [model.title]: name }, scope,
      });
      for (const who of members) {
        await api("POST", recordsUrl(model.id, made.id) + "/members", { username: who });
      }
      replace(sheetHash(at, model.id, made.id));
      renderRoute();
    } catch (err) { toast(err.message); }
  });
}

// -- who is in one, on its record sheet --------------------------------------------------
/** The people part of a space's sheet: who can see it, who is in it, the
    way to add somebody and take them out, and the way out yourself. */
export async function spaceSection(model, record) {
  const shared = record.scope === "shared";
  const inIt = [record.owner, ...(record.members || [])];
  const outside = shared ? (await people()).filter((p) => !inIt.includes(p.username)) : [];
  const mayAdd = shared && (record.can_manage || inIt.includes(session.user));
  const who = (name) => `<div class="row member"><span class="avatar" aria-hidden="true">${esc(name.charAt(0).toUpperCase())}</span>
      <span class="main">${esc(name)}${name === session.user ? " (you)" : ""}${name === record.owner ? ` <span class="said">made it</span>` : ""}</span>
      ${shared && record.can_manage && name !== record.owner
        ? `<button class="take-out" type="button" data-who="${esc(name)}" aria-label="Take ${esc(name)} out">Take out</button>` : ""}</div>`;
  return `<section class="space-people">
    <p class="group-label">Who can see it</p>
    <div class="group"><div class="row"><span class="main">${esc(scopeSaid(record))}</span>${
      record.scope === "public" ? "" : `<span class="said">${esc(record.owner === session.user ? "you made it" : `${record.owner} made it`)}</span>`}</div></div>
    ${shared ? `<p class="group-label">In it (${inIt.length})</p><div class="group members">${inIt.map(who).join("")}</div>` : ""}
    ${mayAdd && outside.length ? `<p class="group-label">Share it with</p>
      <div class="group">${outside.map((p) => `
        <button class="row add-who" type="button" data-who="${esc(p.username)}">
          <span class="main">${esc(p.display_name || p.username)}</span><span class="said">Add</span></button>`).join("")}</div>` : ""}
    ${shared && record.owner !== session.user
      ? `<div class="group"><button class="row bad leave" type="button">Leave this ${esc(model.label.toLowerCase())}</button></div>` : ""}
  </section>`;
}

/** The buttons *spaceSection* drew. *left* is where to go once you have left. */
export function wireSpace(root, model, record, { left }) {
  const url = recordsUrl(model.id, record.id) + "/members";
  for (const button of root.querySelectorAll(".add-who")) {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await api("POST", url, { username: button.dataset.who });
        toast(`${button.dataset.who} is in, and has been told`);
        renderRoute();
      } catch (err) { toast(err.message); button.disabled = false; }
    });
  }
  for (const button of root.querySelectorAll(".take-out")) {
    button.addEventListener("click", async () => {
      if (!confirm(`Take ${button.dataset.who} out of ${nameOf(model, record)}?`)) return;
      try {
        await api("DELETE", `${url}/${encodeURIComponent(button.dataset.who)}`);
        renderRoute();
      } catch (err) { toast(err.message); }
    });
  }
  const leave = root.querySelector(".leave");
  if (leave) {
    leave.addEventListener("click", async () => {
      if (!confirm(`Leave ${nameOf(model, record)}? You will stop seeing what is in it. Somebody in it can add you back.`)) return;
      try {
        await api("DELETE", `${url}/${encodeURIComponent(session.user)}`);
        replace(left);
        renderRoute();
      } catch (err) { toast(err.message); }
    });
  }
}
