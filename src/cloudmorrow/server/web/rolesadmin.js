/* Roles, for an administrator: who is responsible for what (docs/FLOWS.md).

   A side of Administration, beside Circles. A role is a hat — Team lead,
   Expense Responsible — and gives no access to any data: that is the
   circles' business. It answers one question, who holds it, and that is
   what an approval or a flow asks when it asks a role rather than a name.
   A role is held everywhere, or within one circle, so Sales and Warehouse
   each have a Team lead of their own.

   A Quill that expects a role declares it, and it appears here, empty,
   with the Quill's own words on what the holder is for. The administrator
   picks who holds it. */

import {
  api, app, esc, icons, mount, nav, registerScreen, renderRoute, replace, toast, wireShell,
} from "./core.js";

const roleUrl = (id) => "/api/roles/" + encodeURIComponent(id);
const plural = (n, word, many = word + "s") => `${n} ${n === 1 ? word : many}`;

/** "alice, bob (Sales)" for a row's second line. */
export function holdersSaid(role) {
  if (!role.holders.length) return "Nobody yet";
  return role.holders.map((h) => h.username + (h.circle ? ` (${h.circle})` : "")).join(", ");
}

async function backToRoles() {
  replace("#/admin/roles");
  await renderRoute();
}

// -- the list, in the panel ---------------------------------------------------------------------
export async function drawRoles(panel) {
  const roles = await api("GET", "/api/roles");
  const empty = roles.filter((r) => !r.holders.length);
  panel.innerHTML = `
    <p class="note">A role is a hat somebody wears — Team lead, Expense Responsible — and
      gives no access to data. An approval or a flow asks a role rather than a person,
      so whoever holds it today is the one asked.</p>
    ${empty.length ? `<p class="note warn">Held by nobody, so nothing asked of it is answered:
      ${esc(empty.map((r) => r.name).join(", "))}.</p>` : ""}
    <p class="group-label">${plural(roles.length, "role")}</p>
    <div class="group">${roles.length ? roles.map(roleRow).join("")
      : `<p class="empty">No roles yet. Make one with the + above, or install a Quill that asks for one.</p>`}</div>`;
}

function roleRow(role) {
  return `<a class="row role-row" href="#/adminrole/${encodeURIComponent(role.id)}">
    <span class="main"><span class="title">${esc(role.name)}</span>
    <span class="meta"><span class="preview">${esc(holdersSaid(role))}${
      role.declared_by ? ` · asked for by ${esc(role.declared_by)}` : ""}</span></span></span>
    ${icons.chevronRight}</a>`;
}

// -- one role -----------------------------------------------------------------------------------
async function renderRole(id) {
  const me = await api("GET", "/api/auth/me");
  if (!me.is_admin) {
    toast("Administration is for administrators");
    replace("#/me");
    return renderRoute();
  }
  const making = !id;
  const [roles, users, circles] = await Promise.all([
    api("GET", "/api/roles"), api("GET", "/api/users"), api("GET", "/api/circles"),
  ]);
  let role = { id: "", name: "", description: "", declared_by: "", holders: [] };
  if (!making) {
    role = roles.find((r) => r.id === id);
    if (!role) {
      toast("No such role");
      return backToRoles();
    }
  }
  mount(nav({ back: "#/admin/roles", backLabel: "Roles", title: making ? "New role" : role.name }) + `
    <main>
      <h1 class="large">${esc(making ? "New role" : role.name)}</h1>
      ${role.declared_by ? `<p class="note">Asked for by the Quill <b>${esc(role.declared_by)}</b>${
        role.description ? `: ${esc(role.description)}` : ""}.</p>` : ""}
      <form class="account role-form">
        <div class="group">
          <label class="row"><span class="main">Name</span>
            <input name="name" placeholder="Team lead" required value="${esc(role.name)}"></label>
          <label class="row"><span class="main">For</span>
            <input name="description" placeholder="Approves leave and expenses" value="${esc(role.description)}"></label>
        </div>
        ${making ? "" : `
        <p class="group-label">Held by</p>
        <div class="group holders">${role.holders.length ? role.holders.map((h) => `
          <div class="row holder-row" data-user="${esc(h.username)}" data-circle="${esc(h.circle)}">
            <span class="main"><span class="title">${esc(h.username)}</span>
            <span class="meta"><span class="preview">${h.circle ? "in " + esc(h.circle) : "everywhere"}</span></span></span>
            <button type="button" class="act-chip take" aria-label="Take it off ${esc(h.username)}">Take off</button>
          </div>`).join("") : `<p class="empty">Nobody holds it yet.</p>`}</div>
        <p class="group-label">Give it to somebody</p>
        <div class="group give">
          <label class="row"><span class="main">Who</span>
            <select name="who">${users.map((u) => `<option value="${esc(u.username)}">${esc(u.username)}</option>`).join("")}</select></label>
          <label class="row"><span class="main">Where</span>
            <select name="where"><option value="">Everywhere</option>${circles.map((c) =>
              `<option value="${esc(c.id)}">In ${esc(c.name)}</option>`).join("")}</select></label>
          <button type="button" class="row give-button">Give the role</button>
        </div>`}
        <div class="group"><button class="row primary" type="submit">${making ? "Make the role" : "Save"}</button></div>
        ${making ? "" : `<div class="group"><button class="row bad delete" type="button">Delete this role</button></div>`}
      </form>
    </main>`);
  wireShell();

  const form = app.querySelector("form.role-form");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = form.elements.name.value.trim();
    const description = form.elements.description.value.trim();
    if (!name) return toast("A role needs a name.");
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      if (making) {
        const made = await api("POST", "/api/roles", { name, description });
        toast(`${made.name} is made`);
        replace("#/adminrole/" + encodeURIComponent(made.id));
        return renderRoute();
      }
      await api("PATCH", roleUrl(role.id), { name, description });
      toast("Saved");
      await backToRoles();
    } catch (err) {
      button.disabled = false;
      toast(err.message);
    }
  });

  const give = form.querySelector(".give-button");
  if (give) {
    give.addEventListener("click", async () => {
      const who = form.elements.who.value;
      const where = form.elements.where.value;
      try {
        await api("PUT", roleUrl(role.id) + "/holders/" + encodeURIComponent(who) + (where ? "?circle=" + encodeURIComponent(where) : ""));
        toast(`${who} holds ${role.name}`);
        return renderRoute();
      } catch (err) {
        toast(err.message);
      }
    });
  }
  for (const button of form.querySelectorAll(".take")) {
    button.addEventListener("click", async () => {
      const row = button.closest(".holder-row");
      try {
        await api("DELETE", roleUrl(role.id) + "/holders/" + encodeURIComponent(row.dataset.user)
          + (row.dataset.circle ? "?circle=" + encodeURIComponent(row.dataset.circle) : ""));
        toast(`${row.dataset.user} no longer holds ${role.name}`);
        return renderRoute();
      } catch (err) {
        toast(err.message);
      }
    });
  }
  const remove = form.querySelector(".delete");
  if (remove) {
    remove.addEventListener("click", async () => {
      const sure = confirm(`Delete ${role.name}?\n\nNothing asked of it will be answered. A role a Quill asked for comes back, empty.`);
      if (!sure) return;
      try {
        await api("DELETE", roleUrl(role.id));
        toast(`Deleted ${role.name}`);
        await backToRoles();
      } catch (err) {
        toast(err.message);
      }
    });
  }
}

registerScreen("adminrole", renderRole);
