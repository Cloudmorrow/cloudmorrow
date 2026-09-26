/* Administration: the server itself, rather than anything in it.

   The same two sections the terminal app puts behind f9 — who may sign in,
   and which parts of Cloudmorrow this server offers at all — and the same
   rules about them, because both ends talk to one API that decides.

   It is reached from Me rather than from a tab of its own. Administering a
   server is not a sixth kind of your own stuff, and most accounts never see
   it: the row appears for administrators, and a non-administrator who types
   the address is sent back with a word about it. That is a courtesy, not the
   guard — every call under here is admin-only at the server, and the screen
   would be empty without it.

   Two screens. The panel, which is the sections under a switch, and one
   account's page, which is the same form whether it is a new account or one
   that already exists. The third section, the Quills, is a file of its own
   (quillsadmin.js), with its install sheet. */

import {
  api, app, esc, formatDate, heading, icons, nav, onSignOut, registerScreen, renderRoute,
  replace, seconds, store, toast, wireShell,
} from "./core.js";
import { loadFeatures } from "./features.js";
import { drawQuills } from "./quillsadmin.js";

// What the server stores, and what it is called on screen. The same words
// the terminal app uses, so a role means one thing across the two.
const ROLES = [
  ["administrator", "Administrator", "Runs the server."],
  ["user", "User", "Their own notes, tasks and files."],
  ["dashboard_displayer", "DashboardDisplayer", "May only show dashboards on a shared screen."],
];
const TYPES = [
  ["human", "Human", "Signs in and types."],
  ["agent", "Agent", "A program acting for someone."],
  ["systems_user", "SystemsUser", "The machinery itself — a screen in the hallway, a service."],
];
const LABELS = Object.fromEntries([...ROLES, ...TYPES].map(([key, label]) => [key, label]));

// The server asks for this much; saying so here beats a 422 from the API.
const MIN_PASSWORD = 8;

const roleOf = (user) => user.role || (user.is_admin ? "administrator" : "user");
const userUrl = (username) => "/api/users/" + encodeURIComponent(username);

// -- who is asking -----------------------------------------------------------------
// Cached for the length of the visit: every screen here needs it, and it is
// the same answer each time.
let me = null;

async function requireAdmin() {
  if (!me) me = await api("GET", "/api/auth/me");
  if (!me.is_admin) {
    toast("Administration is for administrators");
    replace("#/me");
    await renderRoute();
    return null;
  }
  return me;
}

/** Whether to draw the way in. Me asks this; it never guesses. */
export const isAdmin = (who) => Boolean(who && who.is_admin);

/** The row that leads here, for Me to put under the rest. */
export function adminRow() {
  return `<div class="group"><a class="row admin-link" href="#/admin">
    <span class="main"><span class="title">Administration</span>
    <span class="meta"><span class="preview">The accounts, what this server offers, and its Quills</span></span></span>
    ${icons.chevronRight}</a></div>`;
}

// -- the panel ------------------------------------------------------------------------
async function renderAdmin() {
  if (!(await requireAdmin())) return;
  const side = store.get("admin.side");
  const which = side === "features" || side === "quills" ? side : "users";
  app.innerHTML = nav({ back: "#/me", backLabel: "Me", title: "Administration" }) + `
    <main>
      ${heading("Administration", which === "users"
        ? `<button class="compose" aria-label="New account">${icons.compose}</button>`
        : "")}
      <div class="seg">
        <button data-side="users"${which === "users" ? ' class="active"' : ""}>Users</button>
        <button data-side="features"${which === "features" ? ' class="active"' : ""}>Features</button>
        <button data-side="quills"${which === "quills" ? ' class="active"' : ""}>Quills</button>
      </div>
      <div class="panel"><p class="empty"><b>…</b></p></div>
    </main>`;
  wireShell();

  for (const button of app.querySelectorAll(".seg button")) {
    button.addEventListener("click", () => {
      store.set("admin.side", button.dataset.side);
      renderAdmin();
    });
  }
  const compose = app.querySelector(".heading .compose");
  if (compose) compose.addEventListener("click", () => { location.hash = "#/adminuser"; });

  const panel = app.querySelector(".panel");
  if (which === "users") await drawUsers(panel);
  else if (which === "features") await drawFeatures(panel);
  else await drawQuills(panel);
}

// -- the accounts -----------------------------------------------------------------------
async function drawUsers(panel) {
  const users = await api("GET", "/api/users");
  panel.innerHTML = `
    <p class="group-label">${users.length} account${users.length === 1 ? "" : "s"}</p>
    <div class="group">${users.map(userRow).join("")}</div>`;
}

function userRow(user) {
  const role = roleOf(user);
  const name = user.display_name || user.username;
  // The chip says the role, so the line under the name does not: two copies
  // of "Administrator" in one row only pushed the rest of it off the screen.
  const bits = [user.display_name, LABELS[user.user_type] || user.user_type].filter(Boolean);
  // An account that cannot sign in is the one thing here worth interrupting
  // for, so it goes first, where nothing can truncate it away.
  const barred = user.is_active ? "" : `<span class="off">no sign-in</span> · `;
  return `<a class="row user-row" href="#/adminuser/${encodeURIComponent(user.username)}">
    <span class="avatar" aria-hidden="true">${esc(name.trim().charAt(0).toUpperCase() || "?")}</span>
    <span class="main">
      <span class="title">${esc(user.username)}</span>
      <span class="meta"><span class="preview">${barred}${esc(bits.join(" · "))}</span></span>
    </span>
    <span class="role-chip role-${esc(role)}">${esc(LABELS[role] || role)}</span>
    ${icons.chevronRight}</a>`;
}

// -- what this server offers ---------------------------------------------------------------
async function drawFeatures(panel) {
  const features = await api("GET", "/api/server/features");
  panel.innerHTML = `
    <p class="note">Switching a feature off takes its tab out of every client
      and closes its part of the API. Off here is off for everybody.</p>
    <div class="group">${features.map(featureRow).join("")}</div>`;

  for (const box of panel.querySelectorAll(".feature-row input")) {
    box.addEventListener("change", async () => {
      const key = box.dataset.key;
      box.disabled = true;
      try {
        const feature = await api("PATCH", "/api/server/features/" + encodeURIComponent(key), {
          enabled: box.checked,
        });
        toast(feature.enabled
          ? `${feature.label} is on.`
          : `${feature.label} is off — its tab is gone everywhere.`);
        // "Everywhere" includes this window: the bar at the bottom is
        // drawn from what this account has, and that has just changed.
        await loadFeatures();
        await drawFeatures(panel);
      } catch (err) {
        // Put the tick back where the server still has it.
        box.checked = !box.checked;
        box.disabled = false;
        toast(err.message);
      }
    });
  }
}

function featureRow(feature) {
  let turned = "";
  if (feature.changed_by) {
    const when = seconds(feature.updated_at);
    turned = ` · switched ${feature.enabled ? "on" : "off"} by ${feature.changed_by}`
      + (when ? ` ${formatDate(when)}` : "");
  }
  return `<label class="row feature-row">
    <span class="main">
      <span class="title">${esc(feature.label)}</span>
      <span class="meta"><span class="preview">${esc(feature.description + turned)}</span></span>
    </span>
    <input type="checkbox" data-key="${esc(feature.key)}"${feature.enabled ? " checked" : ""}
      aria-label="${esc(feature.label)}"></label>`;
}

// -- one account -------------------------------------------------------------------------
function choices(group, options, chosen) {
  return `<div class="group choices">${options.map(([key, label, note]) => `
    <label class="row"><input type="radio" name="${group}" value="${esc(key)}"${
      key === chosen ? " checked" : ""}>
      <span class="main"><span class="title">${esc(label)}</span>
      <span class="meta"><span class="preview">${esc(note)}</span></span></span></label>`).join("")}</div>`;
}

async function renderUser(username) {
  if (!(await requireAdmin())) return;
  const making = !username;
  let user = {};
  if (!making) {
    const users = await api("GET", "/api/users");
    user = users.find((u) => u.username === username);
    if (!user) {
      toast("No such account");
      replace("#/admin");
      return renderRoute();
    }
  }
  // Deleting yourself is refused by the server, so the button is not drawn.
  const yourself = !making && user.username === (me && me.username);

  app.innerHTML = nav({
    back: "#/admin",
    // Short on purpose: the bar's left column is narrow and the wordmark
    // sits in the middle of it, so a long label runs into the mark.
    backLabel: "Admin",
    title: making ? "New account" : user.username,
  }) + `
    <main>
      <h1 class="large">${esc(making ? "New account" : user.username)}</h1>
      <form class="account">
        <div class="group">
          ${making ? `<label class="row"><span class="main">Username</span>
            <input name="username" placeholder="ada" autocapitalize="none" autocorrect="off"
              spellcheck="false" required></label>`
          : `<div class="row"><span class="main">Username</span>
            <span class="value">${esc(user.username)}</span></div>`}
          <label class="row"><span class="main">Name</span>
            <input name="display_name" placeholder="optional"
              value="${esc(user.display_name || "")}"></label>
          <label class="row"><span class="main">Password</span>
            <input name="password" type="password" autocomplete="new-password"
              placeholder="${making ? `${MIN_PASSWORD} characters or more` : "leave blank to keep"}"
              ${making ? "required" : ""}></label>
        </div>
        <p class="group-label">Role</p>
        ${choices("role", ROLES, roleOf(user))}
        <p class="group-label">Type</p>
        ${choices("user_type", TYPES, user.user_type || "human")}
        ${making ? "" : `
          <p class="group-label">Signing in</p>
          <div class="group"><label class="row">
            <span class="main"><span class="title">May sign in</span>
            <span class="meta"><span class="preview">Off keeps the account and its files,
              and turns away the password.</span></span></span>
            <input type="checkbox" name="is_active"${user.is_active ? " checked" : ""}></label></div>`}
        <div class="group"><button class="row primary" type="submit">${
          making ? "Make the account" : "Save"}</button></div>
        ${yourself || making ? "" :
          `<div class="group"><button class="row bad delete" type="button">Delete this account</button></div>`}
      </form>
    </main>`;
  wireShell();

  const form = app.querySelector("form.account");
  const say = (message) => toast(message);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const password = form.elements.password.value;
    if (making && !password) return say("A new account needs a password.");
    if (password && password.length < MIN_PASSWORD) {
      return say(`A password is ${MIN_PASSWORD} characters or more.`);
    }
    const body = {
      display_name: form.elements.display_name.value.trim(),
      role: form.elements.role.value,
      user_type: form.elements.user_type.value,
    };
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      if (making) {
        await api("POST", "/api/users", {
          ...body,
          username: form.elements.username.value.trim().toLowerCase(),
          password,
        });
      } else {
        // A blank password box means "leave it alone", not "no password".
        if (password) body.password = password;
        body.is_active = form.elements.is_active.checked;
        await api("PATCH", userUrl(user.username), body);
      }
      toast(making ? "Account made" : "Saved");
      replace("#/admin");
      await renderRoute();
    } catch (err) {
      button.disabled = false;
      say(err.message);
    }
  });

  const remove = form.querySelector(".delete");
  if (remove) {
    remove.addEventListener("click", async () => {
      const sure = confirm(
        `Delete ${user.username}?\n\nSigning in stops at once. Their notes and `
        + "files stay on the disc, under their name.",
      );
      if (!sure) return;
      try {
        await api("DELETE", userUrl(user.username));
        toast(`Deleted ${user.username}`);
        replace("#/admin");
        await renderRoute();
      } catch (err) {
        say(err.message);
      }
    });
  }
}

registerScreen("admin", renderAdmin);
registerScreen("adminuser", renderUser);
// Signing out as one person and in as another must not leave the first
// person's answer behind.
onSignOut(() => { me = null; });
