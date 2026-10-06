/* The desktop app: this page in a window of its own, with the computer behind it.

   `cloudmorrow app` opens this same page in the system's web view and puts
   an object beside it, `window.pywebview.api`, that is the client running
   on the computer: it can mount a share, open a folder, say whether the
   agent is running. This file finds that object and hands it to the
   features that have something to offer with it; everywhere else — a
   phone, a browser tab — it finds nothing, and nothing here does anything.

   pywebview puts the object there a moment after the page has started,
   and says so with `pywebviewready`. By then the first screen is already
   drawn, so once it is here the screen is drawn again, this time with the
   buttons only the desktop app has.

   It is also where the window's sign-in meets the machine's. The token
   `cloudmorrow login` stored is the one the window starts with, so nobody
   signs in twice on one computer; a sign-in in the window is handed back,
   so the terminal app is signed in by it too; and signing out here signs
   the machine out, when it is the window's own sign-in that ends.

   A feature asks `desktop()` whether it is in the app, and `call()` to ask
   it something: every answer is an object, and a refusal is `{error}` in
   words fit to show, never a thrown exception. */

import {
  esc, occupied, onSignIn, onSignOut, parseHash, route, session, signIn, signOut, toast,
} from "./core.js";
import { registerGridHook } from "./kit_grid.js";

let bridge = null;
// The token this window holds, as the machine last heard of it — so the
// hand-over does not echo back, and a sign-out names the sign-in it ends.
let known = null;

/** The bridge when this page is in the desktop app; null everywhere else. */
export const desktop = () => bridge;

/** Ask the computer something. Always an object; `{error}` when it said no. */
export async function call(method, ...args) {
  if (!bridge || typeof bridge[method] !== "function") return { error: "Only in the desktop app" };
  try {
    const answer = await bridge[method](...args);
    return answer && typeof answer === "object" ? answer : { error: "No answer from this computer" };
  } catch (err) {
    return { error: (err && err.message) || String(err) };
  }
}

// -- one sign-in for the machine ----------------------------------------------------
/** At start the machine's sign-in wins: it is the latest from either side. */
async function handOver() {
  const stored = await call("session");
  if (stored.error) return false;
  if (stored.token && stored.token !== session.token) {
    known = stored.token;
    signIn({ access_token: stored.token, user: { username: stored.user } });
    return true;
  }
  if (!stored.token && session.token) {
    // Signed out on the command line since the window last ran. `known`
    // is left empty, so the sign-out below is not told to the machine.
    known = null;
    signOut("Signed out.");
    return true;
  }
  known = session.token;
  return false;
}

onSignIn((data) => {
  if (!bridge || data.access_token === known) return;
  known = data.access_token;
  call("signed_in", data.access_token, data.user.username, data.expires_at || "");
});

onSignOut(() => {
  if (!bridge || !known) return;
  const token = known;
  known = null;
  call("signed_out", token);
});

// -- shares, on this computer -------------------------------------------------------------
// Under each share in a grid of them (the Files Quill's), a line of its
// own: where it is mounted here and the way to it, or the button that
// mounts it. Only the desktop app draws it — a browser cannot mount
// anything — and it is the same mount the terminal app and `cm share mount`
// make, so all three agree on what is mounted. The grid asks every hook
// about its groups and knows nothing of this; this knows the `share`
// datamodel, which is the core's, and nothing of the Quill.
// Mounting is Cloud blue: a strong choice, but not the one thing the
// screen is for.
function mountLine(share, mounted) {
  const name = share.id;
  const here = mounted[name] || {};
  let words;
  let buttons = "";
  if (here.mounted) {
    words = "Mounted at " + here.path;
    buttons = `<button class="desk-button ghost" data-open="${esc(here.path)}">Open folder</button>` +
      `<button class="desk-button ghost" data-unmount="${esc(name)}">Unmount</button>`;
  } else if (share.fields.kind === "machine" && !share.fields.online) {
    words = "Not mounted — its machine is offline";
  } else {
    words = "Not mounted on this computer";
    buttons = `<button class="desk-button cloud" data-mount="${esc(name)}">Mount on this computer</button>`;
  }
  return `<div class="row mount-row${here.mounted ? " on" : ""}">` +
    `<span class="main"><span class="meta"><span class="preview">${esc(words)}</span></span></span>` +
    (buttons ? `<span class="mount-actions">${buttons}</span>` : "") + `</div>`;
}

function wireMounts(root) {
  // One at a time: a mount waits for rclone, and a second click meanwhile
  // would only be refused.
  const act = (button, busy, method, done) => button.addEventListener("click", async () => {
    for (const other of root.querySelectorAll(".mount-actions button")) other.disabled = true;
    button.textContent = busy;
    const answer = await call(method, button.dataset[method]);
    toast(answer.error || done(answer), answer.error ? 6000 : 2200);
    route();
  });
  for (const button of root.querySelectorAll("[data-mount]")) {
    act(button, "Mounting…", "mount", (answer) => "Mounted at " + answer.path);
  }
  for (const button of root.querySelectorAll("[data-unmount]")) {
    act(button, "Unmounting…", "unmount", () => "Unmounted");
  }
  for (const button of root.querySelectorAll("[data-open]")) {
    button.addEventListener("click", async () => {
      const answer = await call("open_folder", button.dataset.open);
      if (answer.error) toast(answer.error, 6000);
    });
  }
}

registerGridHook({
  // What this computer has mounted comes with the list, so the page is
  // drawn once with it rather than twice.
  async groups({ model }) {
    if (!bridge || model.id !== "share") return null;
    const here = await call("mounted_here");
    return { after: (share) => mountLine(share, here.mounts || {}), wire: wireMounts };
  },
});

// -- This computer, in Me --------------------------------------------------------------
/** A place for the group in Me. Nothing at all outside the desktop app. */
export const computerCard = () => (bridge ? `<div class="computer-slot"></div>` : "");

const agentWords = (agent) => {
  if (agent.error) return ["Not known", agent.error, ""];
  if (!agent.enrolled) return ["Not set up", "Nothing here serves a share or makes a backup yet", "warn"];
  if (agent.running === false) {
    return ["Stopped", `Enrolled as ${agent.name}, but not running`, "warn"];
  }
  if (agent.running == null) return ["Enrolled", `As ${agent.name}`, ""];
  return ["Running", `As ${agent.name} — serves this computer's shares`, "good"];
};

/** Fill in the group `computerCard` left room for. */
export async function wireComputerCard(root = document) {
  const slot = root.querySelector(".computer-slot");
  if (!slot) return;
  const [where, agent, version] = await Promise.all([
    call("platform"), call("agent_status"), call("version"),
  ]);
  const [state, line, tone] = agentWords(agent);
  const mount = where.mount || {};
  const mounting = mount.available
    ? [mount.tool === "finder" ? "Finder" : "rclone", "Shares mount in your file manager"]
    : ["Not yet", mount.detail || where.error || "Mounting is not available here"];
  const row = (title, meta, value, cls = "") =>
    `<div class="row"><span class="main"><span class="title">${esc(title)}</span>` +
    (meta ? `<span class="meta"><span class="preview">${esc(meta)}</span></span>` : "") +
    `</span><span class="value${cls ? " " + cls : ""}">${esc(value)}</span></div>`;
  slot.innerHTML = `<div class="group-label">This computer</div><div class="group computer">` +
    // The agent's name for it, and the host's own when that is different.
    row("Name", where.hostname !== where.machine ? where.hostname || "" : "", where.machine || "?") +
    row("Agent", line, state, tone) +
    row("Mounting", mounting[1], mounting[0], mount.available ? "" : "warn") +
    row("Desktop app", version.server || "", version.version || "?") +
    `</div>`;
}

// -- go -------------------------------------------------------------------------------------
async function ready() {
  const api = window.pywebview && window.pywebview.api;
  if (bridge || !api || typeof api.session !== "function") return;
  bridge = api;
  document.documentElement.dataset.desktop = "";
  const moved = await handOver();
  // Drawn again now that there is something to draw it with — unless
  // somebody is typing into it.
  if (!moved && session.token && !occupied() && parseHash().name !== "login") route();
}

if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.session === "function") ready();
else addEventListener("pywebviewready", ready);
