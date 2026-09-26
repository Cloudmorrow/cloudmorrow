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
  esc, occupied, onSignIn, onSignOut, parseHash, route, session, signIn, signOut,
} from "./core.js";

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
