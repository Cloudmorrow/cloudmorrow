/* Administration: the server itself, rather than anything in it.

   The same sections the terminal app puts behind f9 — who may sign in,
   which data they may use, and which Quills this server runs — and the
   same rules about them, because both ends talk to one API that decides.

   Where it is depends on the room. On a computer it is a section of the
   rail — Administration, with a page under it per side, the way the
   terminal app's sidebar lists them — and on a phone, whose bar has no room
   for a section, it is a row at the bottom of Me, with the sides under a
   switch. The roles people hold (rolesadmin.js) are a side of their own. Administering a server is not a sixth kind of your own stuff,
   and most accounts never see it: the section and the row appear for
   administrators, and a non-administrator who types the address is sent
   back with a word about it. That is a courtesy, not the guard — every
   call under here is admin-only at the server, and the screen would be
   empty without it.

   Six sides, each at its own address — #/admin/users and so on, so the
   rail can light one — and one account's page, which is the same form
   whether it is a new account or one that already exists. The circles
   (circlesadmin.js), the Quills (quillsadmin.js, with its sheet) and the
   backups (backupsadmin.js) are files of their own; the server's own side
   — what it runs, and updating it — is below. There is no Features side any more: what this server
   offers is its Quills, and each is switched on or off on its own sheet. */

import {
  api, app, esc, heading, icons, mount, nav, onShell, onSignOut, pixelArt, pixelIcon, registerScreen,
  registerTab, renderRoute, replace, session, setAdmin, store, tabs, toast, wireShell,
} from "./core.js";
import { circlesByPerson, domainsOf, drawCircles, rulesForm, rulesFrom, rulesSaid, wireRulesForm } from "./circlesadmin.js";
import { drawRoles } from "./rolesadmin.js";
import { drawQuills } from "./quillsadmin.js";
import { drawBackups } from "./backupsadmin.js";
import { QUILL_GLYPH } from "./quills.js";
import { ask, openSheet } from "./dialog.js";

// The sides, in the order of the rail and of the switch: the places the
// terminal app's sidebar lists under ADMINISTRATION. The icons are the
// library's, read after the first paint, with one of this app's own to
// stand in until then — or for good, on a server without the library.
const SIDES = [
  ["users", "Users", () => pixelIcon("people") || pixelIcon("me")],
  ["circles", "Circles", () => pixelIcon("group") || pixelIcon("me")],
  ["roles", "Roles", () => pixelIcon("badge") || pixelIcon("me")],
  ["quills", "Quills", () => pixelIcon("feather") || pixelArt(QUILL_GLYPH)],
  ["server", "Server", () => pixelIcon("server") || pixelIcon("settings")],
  ["backups", "Backups", () => pixelIcon("cloud-upload") || pixelIcon("upload") || pixelIcon("server")],
];
const SIDE_LABELS = Object.fromEntries(SIDES.map(([key, label]) => [key, label]));
/** The address of one side. */
export const sideHash = (side) => "#/admin/" + side;

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
// the same answer each time. Whatever it says about administering goes to
// the shell, which draws the rail's section by it.
let me = null;

async function whoami() {
  if (!me) {
    me = await api("GET", "/api/auth/me");
    setAdmin(me.is_admin);
  }
  return me;
}

async function requireAdmin() {
  const who = await whoami();
  if (!who.is_admin) {
    toast("Administration is for administrators");
    replace("#/me");
    await renderRoute();
    return null;
  }
  return who;
}

/** Whether to draw the way in. Me asks this; it never guesses. */
export const isAdmin = (who) => Boolean(who && who.is_admin);

/** The row that leads here, for Me to put under the rest — on a phone. A
    computer has the rail's section, and the stylesheet keeps the row off it. */
export function adminRow() {
  return `<div class="group admin-group"><a class="row admin-link" href="#/admin">
    <span class="main"><span class="title">Administration</span>
    <span class="meta"><span class="preview">The accounts, their circles, the Quills, and the server itself</span></span></span>
    ${icons.chevronRight}</a></div>`;
}

// -- the sides ------------------------------------------------------------------------
async function renderAdmin(arg) {
  if (!(await requireAdmin())) return;
  // The side is in the address, so the rail can light it. A bare #/admin —
  // the row in Me — opens whichever was last open; "features" was a side
  // once, and whoever last stood there is sent to the Quills.
  const last = store.get("admin.side");
  const which = SIDE_LABELS[arg] ? arg : SIDE_LABELS[last] ? last : last === "features" ? "quills" : "users";
  if (arg !== which) replace(sideHash(which));
  store.set("admin.side", which);
  // The + beside the heading makes whatever this side lists.
  const making = {
    users: ["#/adminuser", "New account"], circles: ["#/admincircle", "New circle"], roles: ["#/adminrole", "New role"],
  }[which];
  // A top-level screen, like a Quill's: the rail says where you are, and Me
  // is in the corner. The switch is for the phone, which has no rail.
  mount(nav({ title: SIDE_LABELS[which] }) + `
    <main class="admin">
      ${heading(SIDE_LABELS[which], making
        ? `<button class="compose" aria-label="${making[1]}">${icons.compose}</button>`
        : "")}
      <div class="seg">${SIDES.map(([key, label]) =>
        `<a data-side="${key}" href="${sideHash(key)}"${key === which ? ' class="active"' : ""}>${label}</a>`).join("")}
      </div>
      <div class="panel"><p class="empty"><b>…</b></p></div>
    </main>` + tabs("admin." + which));
  wireShell();

  const compose = app.querySelector(".heading .compose");
  if (compose) compose.addEventListener("click", () => { location.hash = making[0]; });

  const panel = app.querySelector(".panel");
  if (which === "users") await drawUsers(panel);
  else if (which === "circles") await drawCircles(panel);
  else if (which === "roles") await drawRoles(panel);
  else if (which === "server") await drawServer(panel);
  else if (which === "backups") await drawBackups(panel);
  else await drawQuills(panel);
}

// -- the accounts -----------------------------------------------------------------------
async function drawUsers(panel) {
  const [users, circles] = await Promise.all([api("GET", "/api/users"), api("GET", "/api/circles")]);
  const placed = circlesByPerson(circles);
  panel.innerHTML = `
    <p class="group-label">${users.length} account${users.length === 1 ? "" : "s"}</p>
    <div class="group">${users.map((user) => userRow(user, placed[user.username] || [])).join("")}</div>`;
}

function userRow(user, circles) {
  const role = roleOf(user);
  const name = user.display_name || user.username;
  // The chip says the role, so the line under the name does not: two copies
  // of "Administrator" in one row only pushed the rest of it off the screen.
  const bits = [user.display_name, LABELS[user.user_type] || user.user_type].filter(Boolean);
  // An account that cannot sign in is the one thing here worth interrupting
  // for, so it goes first, where nothing can truncate it away.
  const barred = user.is_active ? "" : `<span class="off">no sign-in</span> · `;
  // Their circles are what they may reach; in none, they reach nothing, and
  // that is said as plainly as not signing in (docs/CIRCLES.md, rule 3).
  const within = circles.length
    ? `<span class="circles">${esc(circles.join(", "))}</span>`
    : `<span class="off">reaches no data</span>`;
  return `<a class="row user-row" href="#/adminuser/${encodeURIComponent(user.username)}">
    <span class="avatar" aria-hidden="true">${esc(name.trim().charAt(0).toUpperCase() || "?")}</span>
    <span class="main">
      <span class="title">${esc(user.username)}</span>
      <span class="meta"><span class="preview">${barred}${within}${
        bits.length ? " · " + esc(bits.join(" · ")) : ""}</span></span>
    </span>
    <span class="role-chip role-${esc(role)}">${esc(LABELS[role] || role)}</span>
    ${icons.chevronRight}</a>`;
}

// -- the server itself -----------------------------------------------------------------------
// What this server runs, and the way to the newest: the same deploy
// `cloudmorrow update server` asks for, from the phone. The server puts its
// checkout on what its remote branch says, reinstalls, republishes the
// client wheel and restarts onto the new code — and this screen, like the
// command, watches it go away and come back, then reloads onto the new
// app. `/api/health` is the witness at both ends: the version never moves
// between commits, so the commit is the only honest answer to "did it land".
const HEALTH_WAIT = 60 * 1000;

async function drawServer(panel) {
  const [health, settings] = await Promise.all([api("GET", "/api/health"), api("GET", "/api/server/settings")]);
  panel.innerHTML = `
    <p class="group-label">Settings</p>
    <form class="server-settings">
      <div class="group">
        <label class="row"><span class="main">Name</span>
          <input name="name" value="${esc(settings.name || "")}" maxlength="64" required
            placeholder="Cloudmorrow" autocapitalize="words" autocorrect="off"></label>
        <label class="row"><span class="main">Weather for</span>
          <input name="weather_place" value="${esc(settings.weather_place || "")}" maxlength="120"
            placeholder="a town, or latitude,longitude" autocapitalize="words" autocorrect="off"></label>
      </div>
      <p class="note">The name is on every screen and the home-screen icon. The weather on Today is
        for the place: a town (<i>Copenhagen</i>, <i>Aarhus, Denmark</i>) or <i>55.68,12.57</i> when a
        name is ambiguous; blank and Today says nothing about the weather.</p>
      <div class="group"><button class="row primary" type="submit">Save</button></div>
    </form>
    <p class="group-label">Running</p>
    <div class="group">
      <div class="row"><span class="main">Version</span><span class="value">${esc(health.version || "?")}</span></div>
      <div class="row"><span class="main">Commit</span><span class="value">${esc(shortCommit(health.commit) || "not a checkout")}</span></div>
      <div class="row"><span class="main">Accounts</span><span class="value">${esc(String(health.users ?? "?"))}</span></div>
    </div>
    <p class="group-label">Updating</p>
    <p class="note">The server fetches the newest code from its git remote, reinstalls,
      republishes the app the computers install, and restarts onto it. Everybody is
      offline for a few seconds, and this app comes back on the new version by itself.
      The same as <code>cloudmorrow update server</code> from a computer.</p>
    <div class="update-notice" aria-live="polite"><p class="note muted">Looking for a newer version…</p></div>
    <div class="group"><button class="row primary update-server" type="button">Update server</button></div>
    <div class="update-log" hidden></div>`;
  // Whether a newer release is out, found after the page is up: the look
  // fetches the server's git remote, which is a moment the page need not wait.
  lookForUpdates(panel.querySelector(".update-notice"));

  const form = panel.querySelector("form.server-settings");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const save = form.querySelector("button[type=submit]");
    save.disabled = true;
    try {
      const saved = await api("PATCH", "/api/server/settings", {
        name: form.elements.name.value.trim(),
        weather_place: form.elements.weather_place.value.trim(),
      });
      form.elements.name.value = saved.name;
      form.elements.weather_place.value = saved.weather_place;
      toast("Saved");
    } catch (err) {
      toast(err.message);
    } finally {
      save.disabled = false;
    }
  });

  const button = panel.querySelector(".update-server");
  const log = panel.querySelector(".update-log");
  button.addEventListener("click", async () => {
    const sure = await ask(
      "Update the server?\n\nIt fetches the newest code, reinstalls and restarts. "
      + "Everybody is offline for a few seconds.",
    );
    if (!sure) return;
    button.disabled = true;
    button.textContent = "Updating…";
    log.hidden = false;
    log.innerHTML = "";
    const line = (text, tone = "") => {
      const p = document.createElement("p");
      if (tone) p.className = tone;
      p.textContent = text;
      log.append(p);
      return p;
    };
    let result;
    try {
      result = await api("POST", "/api/server/update", {});
    } catch (err) {
      const why = err.status === 404
        ? "This server is from before updates over the API. Update it once with `cloudmorrow update server --ssh`."
        : err.message;
      line(why, "bad");
      button.disabled = false;
      button.textContent = "Update server";
      return;
    }
    for (const [text, tone] of deployLines(result)) line(text, tone);
    if (!result.restarting) {
      button.disabled = false;
      button.textContent = "Update server";
      return;
    }
    const waiting = line("Restarting — waiting for the server to come back…", "muted");
    const back = await waitForServer(result.new_commit);
    if (back === null) {
      waiting.textContent = "The server has not answered yet. It may still be starting; this app reloads when it does.";
      waiting.className = "warn";
      button.disabled = false;
      button.textContent = "Update server";
      return;
    }
    waiting.textContent = back === result.new_commit
      ? `Back up on ${shortCommit(back)}. Reloading…`
      : `Back up, but on ${shortCommit(back)} rather than ${shortCommit(result.new_commit)} — something else deployed at the same time? Reloading…`;
    waiting.className = back === result.new_commit ? "good" : "warn";
    // The page is last week's app by now; the server has the new one.
    setTimeout(() => location.reload(), 1200);
  });
}

const shortCommit = (commit) => (commit || "").slice(0, 8);

// -- a newer version ---------------------------------------------------------------
// Above the Update button: a box saying a newer release is out, with its
// version, and Release notes — a sheet listing every release from the one
// this server runs to the latest, newest first, each with the note on its
// tag and what went into it. Nothing when the server is on the latest, and
// a quiet line when it cannot look (no checkout, no network).
async function lookForUpdates(box) {
  let found;
  try {
    found = await api("GET", "/api/server/updates");
  } catch (err) {
    box.innerHTML = `<p class="note muted">${esc(err.status === 404
      ? "This server is from before it could look for a newer version."
      : "Could not look for a newer version: " + err.message)}</p>`;
    return;
  }
  if (found.error) {
    box.innerHTML = `<p class="note muted">Could not look for a newer version: ${esc(found.error)}</p>`;
    return;
  }
  if (!found.available) {
    box.innerHTML = `<p class="note muted">This server runs the latest version${found.running_version
      ? `, ${esc(found.running_version)}` : ""}.</p>`;
    return;
  }
  const count = found.releases.length;
  const latest = found.releases[0];
  box.innerHTML = `<div class="group new-version">
    <div class="row">
      <span class="main">
        <span class="title">Version ${esc(latest.version)} is out</span>
        <span class="meta">${esc(found.running_version ? `This server runs ${found.running_version}` : "This server runs an untagged commit")}
          · ${count === 1 ? "one release" : `${count} releases`} since · ${esc(latest.date)}</span>
      </span>
      <button class="act-chip release-notes" type="button">Release notes</button>
    </div>
  </div>`;
  box.querySelector(".release-notes").addEventListener("click", () => showReleaseNotes(found));
}

function showReleaseNotes(found) {
  const latest = found.releases[0];
  const release = (r) => `<section class="release">
    <h3>${esc(r.version)} <span class="date">${esc(r.date)}</span></h3>
    ${r.notes ? `<p>${esc(r.notes)}</p>` : ""}
    ${r.changes.length ? `<ul>${r.changes.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}
  </section>`;
  const { sheet, close } = openSheet(
    `<h2 class="act-sheet-title">Release notes</h2>
    <p class="act-description">From ${esc(found.running_version || "what this server runs")} to ${esc(latest.version)}, newest first.</p>
    <div class="releases">${found.releases.map(release).join("")}
      <p class="running">${esc(found.running_version || shortCommit(found.running_commit))} — what this server runs now.</p>
    </div>
    <div class="act-buttons"><button class="act-button" type="button">Close</button></div>`,
    "release-notes-sheet",
  );
  sheet.querySelector(".act-buttons button").addEventListener("click", close);
}

// What to call one end of a deploy: its release, or its commit. A tagged
// commit is a release and says so; anything else is named by its commit,
// rather than read as a release it is not. The same words the command prints.
function deployName(result, end) {
  const version = (result[`${end}_version`] || "").trim();
  const commit = shortCommit(result[`${end}_commit`]);
  return version && !version.includes(".dev") ? `v${version}` : commit;
}

/** The lines that say what a deploy did, each with its tone. */
export function deployLines(result) {
  const lines = [];
  if (result.discarded) {
    lines.push([`Rewound onto origin/${result.branch}, discarding ${result.discarded} commit${
      result.discarded === 1 ? "" : "s"} the remote does not have`, "warn"]);
  }
  if (result.changed) {
    let from = deployName(result, "old");
    let to = deployName(result, "new");
    if (from === to) { from = shortCommit(result.old_commit); to = shortCommit(result.new_commit); }
    lines.push([`Updated ${from} → ${to} · ${result.changed_files} files · ${result.branch}`, "good"]);
  } else {
    lines.push([`Already up to date · ${deployName(result, "new")} · ${result.branch}`, "good"]);
  }
  if (result.commit_subject) lines.push([result.commit_subject, "muted"]);
  const done = [];
  if (result.reinstalled) done.push("reinstalled");
  if (result.published_wheel) done.push(`published ${result.published_wheel}`);
  if (done.length) lines.push([done.join(" · "), "muted"]);
  if (result.restart_blocked) {
    lines.push([`Not restarted: ${result.restart_blocked}`, "warn"]);
    lines.push(["The new code is on disk; the old code is still serving.", "muted"]);
  }
  return lines;
}

// The server going away and coming back: /api/health answers again, and
// says which commit it is on. Null when it has not answered in time. A
// moment first, or the old process, still draining, answers for the new.
// Through `api` like every other call, so a server that comes back and
// turns the token away signs out the way it does everywhere; the clock on
// the address keeps a browser from answering from its cache.
async function waitForServer(expect) {
  const deadline = Date.now() + HEALTH_WAIT;
  await new Promise((r) => setTimeout(r, 2000));
  while (Date.now() < deadline) {
    try {
      const body = await api("GET", "/api/health?t=" + Date.now());
      const commit = body.commit || "";
      // The old process answering with the old commit is not "back".
      if (commit === expect || !commit) return commit;
    } catch { /* down: that is the restart */ }
    await new Promise((r) => setTimeout(r, 700));
  }
  return null;
}

// -- one account -------------------------------------------------------------------------
// The four settings about Quills of people's own, as they read on the screen.
const QUILL_POLICY = [
  ["personal_quills", "Quills of their own", { on: "May add them", ask: "Only through a request", off: "None" }],
  ["personal_quill_create", "May make their own", { on: "From a folder, a source, a fork, an assistant", off: "The catalog only" }],
  ["personal_quill_code", "May run code", { on: "In the sandbox, as them", off: "Declared Quills only" }],
  ["personal_quill_sharing", "May share theirs", { on: "With people who say yes", off: "Theirs alone" }],
];

/** The server's answer on each, with a select to say otherwise for this person. */
function quillPolicyForm(policy) {
  return `<p class="group-label">Quills of their own</p>
    <p class="shelf-note">The server's answers (Administration, Quills, User Quills), said again for this
      account where it should differ. <i>The server's</i> follows the server as it changes.</p>
    <div class="group policy quill-policy">${QUILL_POLICY.map(([key, label, words]) => {
      const own = policy.own[key];
      const server = policy.server[key];
      return `<label class="row">
        <span class="main"><span class="title">${esc(label)}</span>
        <span class="meta"><span class="preview">${esc(words[policy.effective[key]] || policy.effective[key])}</span></span></span>
        <select name="${key}" aria-label="${esc(label)}">
          <option value="inherit"${own ? "" : " selected"}>the server's (${esc(server)})</option>
          ${Object.keys(words).map((v) => `<option value="${v}"${own === v ? " selected" : ""}>${v}</option>`).join("")}
        </select></label>`;
    }).join("")}</div>`;
}

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
      replace(sideHash("users"));
      return renderRoute();
    }
  }
  // Deleting yourself is refused by the server, so the button is not drawn.
  const yourself = !making && user.username === (me && me.username);
  // Their access: what their circles give, and rules of their own beside
  // them — the one person who needs the budget without a circle for them.
  let access = null;
  let shelves = [];
  // What they may do with Quills of their own: the server's answers, and
  // what was said about them in particular (docs/SHARING.md, rule 9).
  let quillPolicy = null;
  if (!making) {
    const [found, models, policy] = await Promise.all([
      api("GET", "/api/access/" + encodeURIComponent(user.username)), api("GET", "/api/datamodels"),
      api("GET", "/api/quills/policy/" + encodeURIComponent(user.username)).catch(() => null),
    ]);
    access = found;
    shelves = domainsOf(models);
    quillPolicy = policy;
  }

  mount(nav({
    back: sideHash("users"),
    // Short on purpose: the bar's left column is narrow and the wordmark
    // sits in the middle of it, so a long label runs into the mark.
    backLabel: "Users",
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
        ${access ? `
          <p class="group-label">Data of their own</p>
          <p class="shelf-note">${access.circles.length
            ? `Beside their circles (${esc(access.circles.join(", "))}): what they reach is the most any of it gives.`
            : "They are in no circle, so this is all they reach."} Nothing set here
            follows their circles.</p>
          ${rulesForm(access.own, shelves)}
          <p class="shelf-note reaches">${Object.keys(access.access).length
            ? "They reach: " + esc(rulesSaid(access.access, Object.fromEntries(shelves.flatMap((s) => s.models.map((m) => [m.id, m.label || m.id])))))
            : "They reach no data."}</p>` : ""}
        ${quillPolicy ? quillPolicyForm(quillPolicy) : ""}
        <div class="group"><button class="row primary" type="submit">${
          making ? "Make the account" : "Save"}</button></div>
        ${yourself || making ? "" :
          `<div class="group"><button class="row bad delete" type="button">Delete this account</button></div>`}
      </form>
    </main>`);
  wireShell();

  const form = app.querySelector("form.account");
  const say = (message) => toast(message);
  if (access) wireRulesForm(form, shelves);

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
        if (access) {
          await api("PUT", "/api/access/" + encodeURIComponent(user.username), { rules: rulesFrom(form, access.own) });
        }
        if (quillPolicy) {
          const said = {};
          for (const select of form.querySelectorAll(".quill-policy select")) said[select.name] = select.value;
          await api("PUT", "/api/quills/policy/" + encodeURIComponent(user.username), said);
        }
      }
      toast(making ? "Account made" : "Saved");
      replace(sideHash("users"));
      await renderRoute();
    } catch (err) {
      button.disabled = false;
      say(err.message);
    }
  });

  const remove = form.querySelector(".delete");
  if (remove) {
    remove.addEventListener("click", async () => {
      const sure = await ask(
        `Delete ${user.username}?\n\nSigning in stops at once. Their notes and `
        + "files stay on the disc, under their name.",
      );
      if (!sure) return;
      try {
        await api("DELETE", userUrl(user.username));
        toast(`Deleted ${user.username}`);
        replace(sideHash("users"));
        await renderRoute();
      } catch (err) {
        say(err.message);
      }
    });
  }
}

registerScreen("admin", renderAdmin);
registerScreen("adminuser", renderUser);
for (const [key, label, icon] of SIDES) {
  registerTab({ name: "admin." + key, label, icon, href: () => sideHash(key), admin: true });
}
// Once per load, on whichever screen comes first: whether the rail gets its
// section is the server's to say, and an account made an administrator —
// or no longer one — since the last load is told so here.
let asked = false;
onShell(() => {
  if (!session.token || asked) return;
  asked = true;
  whoami().catch(() => {});
});
// Signing out as one person and in as another must not leave the first
// person's answer behind.
onSignOut(() => { me = null; asked = false; });
