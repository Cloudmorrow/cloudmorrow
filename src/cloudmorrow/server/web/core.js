/* The shell everything else hangs on: who is signed in, how the server is
   spoken to, which screen the address bar names, and the bars above and
   below it.

   A feature is a file of its own. It imports what it needs from here,
   registers its screens with `registerScreen` and its tab with
   `registerTab`, and is listed once in app.js. Nothing in this file knows
   what the features are. */

export const app = document.getElementById("app");
const toastEl = document.getElementById("toast");
export const VERSION = app.dataset.version;
// What this cloud is called, from the server config; the page's title and
// the sign-in screen say it, so the people on a server see their own cloud by name.
export const CLOUD_NAME = app.dataset.name || "Cloudmorrow";
export const SAVE_DELAY = 900;
export const SEARCH_DELAY = 250;

// -- storage ------------------------------------------------------------------
export const store = {
  get(key) {
    try { return localStorage.getItem("cm." + key); } catch { return null; }
  },
  set(key, value) {
    try {
      if (value == null) localStorage.removeItem("cm." + key);
      else localStorage.setItem("cm." + key, value);
    } catch { /* private mode: the session lasts while the page does */ }
  },
};

// Who is signed in. The token lives in local storage for as long as the
// server says it is good; the username stays so the next sign-in is one field.
export const session = { token: store.get("token"), user: store.get("user") || "" };

// -- talking to the server -----------------------------------------------------
export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : "request failed");
    this.status = status;
    this.detail = detail;
  }
}

export const authHeaders = () => (session.token ? { Authorization: "Bearer " + session.token } : {});

export async function api(method, path, body, { keepalive = false } = {}) {
  const headers = authHeaders();
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      keepalive,
    });
  } catch {
    throw new ApiError(0, "Could not reach the server");
  }
  if (res.status === 401 && session.token) {
    signOut("Your session ended. Sign in again.");
    throw new ApiError(401, "signed out");
  }
  if (res.status === 204) return null;
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw new ApiError(res.status, data && data.detail !== undefined ? data.detail : data);
  return data;
}

export const encodePath = (path) => path.split("/").map(encodeURIComponent).join("/");

// -- helpers --------------------------------------------------------------------
export const esc = (s) => String(s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

// What a title may be as a file name: no slashes, nothing hidden, not silly long.
export function fileStem(title) {
  return title
    .replace(/[\\/]/g, "-")
    .replace(/[\x00-\x1f]/g, "")
    .replace(/\s+/g, " ")
    .replace(/^\.+/, "")
    .trim()
    .slice(0, 80)
    .trim();
}

export function formatDate(seconds, { long = false } = {}) {
  const date = new Date(seconds * 1000);
  if (long) {
    return date.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })
      + " at " + date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((startOfToday - new Date(date.getFullYear(), date.getMonth(), date.getDate())) / 86400000);
  if (days <= 0) return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (days === 1) return "Yesterday";
  if (days < 7) return date.toLocaleDateString(undefined, { weekday: "long" });
  return date.toLocaleDateString(undefined, { day: "2-digit", month: "2-digit", year: "numeric" });
}

// Which stretch of time something belongs to, for the headings in a long
// list: the recent ones by how many days ago, the rest of this year by
// month, and earlier years each by year.
export function sectionOf(seconds) {
  const date = new Date(seconds * 1000);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((startOfToday - new Date(date.getFullYear(), date.getMonth(), date.getDate())) / 86400000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return "Last 7 Days";
  if (days < 30) return "Last 30 Days";
  if (date.getFullYear() === now.getFullYear()) return date.toLocaleDateString(undefined, { month: "long" });
  return String(date.getFullYear());
}

// ISO stamps from the server, as the seconds `formatDate` wants.
export function seconds(stamp) {
  const ms = Date.parse(stamp || "");
  return Number.isNaN(ms) ? null : ms / 1000;
}

let toastTimer = null;
export function toast(message, ms = 2200) {
  toastEl.textContent = message;
  toastEl.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastEl.hidden = true; }, ms);
}

// The wordmark, in the dots the home-screen icon is drawn in: five wide,
// seven tall, each dot a rounded square with a gap around it. Drawn inline
// as SVG, so it is there the moment the page is and never shifts.
const GLYPHS = {
  B: ["XXXX.", "X...X", "X...X", "XXXX.", "X...X", "X...X", "XXXX."],
  R: ["XXXX.", "X...X", "X...X", "XXXX.", "X.X..", "X..X.", "X...X"],
  A: [".XXX.", "X...X", "X...X", "XXXXX", "X...X", "X...X", "X...X"],
  M: ["X...X", "XX.XX", "X.X.X", "X.X.X", "X...X", "X...X", "X...X"],
  C: [".XXX.", "X...X", "X....", "X....", "X....", "X...X", ".XXX."],
  L: ["X....", "X....", "X....", "X....", "X....", "X....", "XXXXX"],
  O: [".XXX.", "X...X", "X...X", "X...X", "X...X", "X...X", ".XXX."],
  U: ["X...X", "X...X", "X...X", "X...X", "X...X", "X...X", ".XXX."],
  D: ["XXX..", "X..X.", "X...X", "X...X", "X...X", "X..X.", "XXX.."],
  W: ["X...X", "X...X", "X...X", "X.X.X", "X.X.X", "XX.XX", "X...X"],
};
export function wordmark(text = "CLOUDMORROW") {
  const letters = [...text].filter((c) => GLYPHS[c]);
  let dots = "";
  letters.forEach((letter, i) => {
    GLYPHS[letter].forEach((row, y) => {
      [...row].forEach((cell, x) => {
        if (cell === "X") dots += `<rect x="${i * 6 + x + 0.08}" y="${y + 0.08}" width="0.84" height="0.84" rx="0.14"/>`;
      });
    });
  });
  return `<svg class="wordmark" viewBox="0 0 ${letters.length * 6 - 1} 7" fill="currentColor" role="img" aria-label="${text}">${dots}</svg>`;
}

// The icons every tab is drawn with: eight dots across, because a glyph
// needs the room a letter does not, and outlines one dot thick so they
// carry the weight of the type beside them. Same drawing as the wordmark
// above — the app's marks are pixels and its words are not.
//
// Nine, for the places the app can take you. Two of them —
// secrets, settings — have no screen here yet; they are in the set because
// the set is the thing, and the terminal app already has them.
const PIXELS = {
  notes: [
    "XXXXXXXX",
    "X......X",
    "X.XXXX.X",
    "X......X",
    "X.XXXX.X",
    "X......X",
    "X.XXX..X",
    "XXXXXXXX",
  ],
  tasks: [
    "........",
    "......X.",
    ".....XX.",
    "X...XX..",
    "XX.XX...",
    ".XXX....",
    "..X.....",
    "........",
  ],
  files: [
    ".XXX....",
    "X...X...",
    "XXXXXXXX",
    "X......X",
    "X......X",
    "X......X",
    "X......X",
    "XXXXXXXX",
  ],
  secrets: [
    "........",
    ".XX..XX.",
    ".XX..XX.",
    "........",
    "........",
    ".XX..XX.",
    ".XX..XX.",
    "........",
  ],
  settings: [
    "...X....",
    "XXXXXXXX",
    "...X....",
    "........",
    ".....X..",
    "XXXXXXXX",
    ".....X..",
    "........",
  ],
  // Rounded at the top and with a tail under it, because the square box
  // with lines in it is already notes and these sit next to each other.
  chat: [
    ".XXXXXX.",
    "X......X",
    "X.XXXX.X",
    "X......X",
    "X.XX...X",
    "XXXXXXXX",
    "..XX....",
    ".XX.....",
  ],
  // Two hangers, a rule under them and a week of squares: a calendar, in
  // the one place the app draws a glyph rather than a letter.
  calendar: [
    ".X....X.",
    "XXXXXXXX",
    "X......X",
    "X.XX.X.X",
    "X......X",
    "X.X.XX.X",
    "X......X",
    "XXXXXXXX",
  ],
  me: [
    "...XX...",
    "..XXXX..",
    "..XXXX..",
    "...XX...",
    "........",
    "..XXXX..",
    ".XXXXXX.",
    "XXXXXXXX",
  ],
  // The sun coming up over a line: today, before it is anything else.
  today: [
    "...XX...",
    "........",
    ".X.XX.X.",
    "..XXXX..",
    ".XXXXXX.",
    "XXXXXXXX",
    "........",
    "XXXXXXXX",
  ],
};
/** Eight-by-eight rows of `X` and `.`, drawn as the tab icons are. A
    feature with a glyph of its own — the weather — hands its rows here. */
export function pixelArt(rows, className = "pixel-icon") {
  let dots = "";
  rows.forEach((row, y) => {
    [...row].forEach((cell, x) => {
      if (cell === "X") dots += `<rect x="${x + 0.08}" y="${y + 0.08}" width="0.84" height="0.84" rx="0.16"/>`;
    });
  });
  return `<svg class="${className}" viewBox="0 0 8 8" fill="currentColor" aria-hidden="true">${dots}</svg>`;
}
/** The named icon, or nothing when there is no such name — a Quill names
    its own, and one this app has not drawn yet falls back to the caller's. */
export function pixelIcon(name) {
  return PIXELS[name] ? pixelArt(PIXELS[name]) : "";
}

// The icons more than one feature uses. A feature keeps its own beside it.
export const icons = {
  chevronLeft: '<svg width="14" height="22" viewBox="0 0 14 22" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M11 2 3 11l8 9"/></svg>',
  chevronRight: '<svg width="9" height="16" viewBox="0 0 9 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m1.5 1.5 6 6.5-6 6.5"/></svg>',
  search: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="6.8" cy="6.8" r="5"/><path d="m10.7 10.7 4 4"/></svg>',
  compose: '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6"/><path d="m17.5 3.5 3 3L11 16l-4 1 1-4z"/></svg>',
  trash: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>',
  tick: '<svg width="12" height="10" viewBox="0 0 12 10" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m1.5 5.5 3 3 6-7"/></svg>',
};

// -- what the features register ---------------------------------------------------
const screens = new Map();   // name in the hash → async (arg, extra) => renders it
const tabList = [];          // [{name, label, icon, href(active), feature}] as registered, or a slot
const shellHooks = [];       // run after every screen is put on the page
const signOutHooks = [];     // run when the session ends, to drop what was loaded
let home = "login";          // the screen an empty hash means, once signed in
let homeFeature = "";        // the feature that screen belongs to, if it is one

export function registerScreen(name, render) { screens.set(name, render); }
/** A tab. `feature` names the feature it belongs to; without one it is always there. */
export function registerTab(tab) { tabList.push(tab); }
/** A place in the tab order for tabs that arrive later — the Quills, which
    only the server knows. Held where it is called, so the order of app.js
    is still the order of the bar; returns the function that fills it. */
export function tabSlot() {
  const slot = { tabs: [] };
  tabList.push(slot);
  return (tabs) => { slot.tabs = tabs; };
}
const allTabs = () => tabList.flatMap((t) => t.tabs || [t]);
export function onShell(fn) { shellHooks.push(fn); }
export function onSignOut(fn) { signOutHooks.push(fn); }
export function setHome(name, feature = "") { home = name; homeFeature = feature; }

// -- which features this account has -----------------------------------------------
// Either switch can put one in here: the server's, thrown by an administrator,
// or your own in Me. A client cannot tell them apart and does not need to —
// off is off, and what is off has no tab.
//
// Kept in local storage so the first paint of the tab bar is already right.
// A bar that draws five tabs and takes one away a moment later is worse than
// a bar that is briefly out of date after somebody switches something.
let featuresOff = new Set((store.get("features.off") || "").split(",").filter(Boolean));

export const featureOff = (name) => !!name && featuresOff.has(name);
/** The feature keys the tabs are gated on — what the server is asked about. */
export const gatedFeatures = () => [...new Set(allTabs().map((t) => t.feature).filter(Boolean))];
export function setFeaturesOff(keys) {
  featuresOff = new Set(keys);
  store.set("features.off", [...featuresOff].join(",") || null);
}

const shownTabs = () => allTabs().filter((t) => !featureOff(t.feature));

/** Where an empty hash goes. Not into a tab this account has switched off. */
export function homeHash() {
  if (!featureOff(homeFeature)) return "#/" + home;
  const first = shownTabs()[0];
  return first ? first.href(false) : "#/today";
}

// -- who has the screen ------------------------------------------------------------
// An editor holds the screen while it has unsaved words. It says whether a
// hash is still its own, how to leave, and how to flush when the page is
// about to go away.
let occupant = null;
export function occupy(o) { occupant = o; }
export function vacate(o) { if (occupant === o) occupant = null; }
export const occupied = () => occupant !== null;

function flush() {
  if (occupant) occupant.flush();
}

// -- routing -------------------------------------------------------------------------
export function parseHash() {
  const hash = location.hash.replace(/^#\/?/, "");
  const slash = hash.indexOf("/");
  const name = slash === -1 ? hash : hash.slice(0, slash);
  let arg = slash === -1 ? "" : hash.slice(slash + 1);
  try { arg = arg.split("/").map(decodeURIComponent).join("/"); } catch { /* keep as typed */ }
  return { name: name || (session.token ? home : "login"), arg };
}

export const go = (hash) => { location.hash = hash; };
export const replace = (hash) => history.replaceState(null, "", hash);

// Where the back button leads. Prefer walking the history so the swipe-back
// gesture and the button agree; fall back to the parent when there is none.
const visited = [];
export function back(parentHash) {
  if (visited.length >= 2 && visited[visited.length - 2] === parentHash) history.back();
  else go(parentHash);
}
function remember(hash) {
  if (visited.length >= 2 && visited[visited.length - 2] === hash) visited.pop();
  else if (visited[visited.length - 1] !== hash) visited.push(hash);
}
export const previousHash = () => visited[visited.length - 2];
export const forgetHistory = () => { visited.length = 0; };

let rendering = Promise.resolve();
export function route() {
  rendering = rendering.then(renderRoute).catch((err) => {
    console.error(err);
    if (!(err instanceof ApiError && err.status === 401)) toast(err.message || "Something went wrong");
  });
}

export async function renderRoute() {
  const { name, arg } = parseHash();
  remember(location.hash);
  if (!session.token && name !== "login") { replace("#/login"); return renderRoute(); }
  if (occupant && !occupant.stays(name, arg)) {
    const leaving = occupant;
    occupant = null;
    await leaving.leave();
  }
  const render = screens.get(name) || screens.get(home);
  return render(arg);
}

// -- signing in and out ----------------------------------------------------------------
export function signIn(data) {
  session.token = data.access_token;
  session.user = data.user.username;
  store.set("token", session.token);
  store.set("user", session.user);
  forgetHistory();
  replace(homeHash());
  route();
}

export function signOut(message) {
  session.token = null;
  store.set("token", null);
  occupant = null;
  for (const fn of signOutHooks) fn();
  replace("#/login");
  screens.get("login")("", { message: message || "", bad: message !== "Signed out." });
}

// -- the shell -----------------------------------------------------------------------------
export function nav({ back: backTo, backLabel, title, right = "" }) {
  const left = backTo === undefined ? "" :
    `<button class="back" data-back="${esc(backTo)}">${icons.chevronLeft}${esc(backLabel)}</button>`;
  // Who you are, in the top corner of every screen that is a tab: the one
  // place that is the same on all of them. A screen with a back button is
  // inside something, and its corner is that something's to use.
  if (backTo === undefined) right += meLink();
  // What the window is called, for a browser with twenty tabs open. A
  // phone has no use for it and no way to see it; it costs one line.
  document.title = title ? `${title} · ${CLOUD_NAME}` : CLOUD_NAME;
  // The wordmark sits in the middle of the bar on every screen, and stays
  // put: the screen's title is the large one below, not something that
  // slides in beside it. The hidden span keeps the title for a feature
  // that sets it, for anything reading the page aloud, and — on a screen
  // wide enough that the wordmark has moved into the rail — for the eye.
  return `<header class="nav"><div class="left">${left}</div>` +
    `<div class="center">${wordmark()}` +
    `<span class="text">${esc(title)}</span></div><div class="right">${right}</div></header>`;
}

/** The way to Me, in the bar's right corner. */
export const meLink = () =>
  `<a class="button me-link" href="#/me" aria-label="Me">${pixelIcon("me")}</a>`;

// A screen's title, with what the screen makes beside it: the pen on a
// list of notes, the plus on a folder. Beside the title rather than in the
// bar, because the bar's corner belongs to Me and the title is the thing
// the button acts on. Any h1 in `main` is what the bar watches to grow its
// line, so this is still one.
export function heading(title, right = "") {
  return `<div class="heading"><h1 class="large">${esc(title)}</h1>` +
    (right ? `<div class="actions">${right}</div>` : "") + `</div>`;
}

// The tabs along the bottom. Every top-level screen has them; an editor
// does not, so the keyboard has the room. Tapping the tab you are on takes
// you to the top of it, as on a phone.
//
// On a screen wide enough the same markup is a rail down the left, and
// the wordmark moves to the head of it out of the middle of the bar.
// Which tab was last lit, for the screens that draw none of their own.
let lastTab = "";
export function tabs(active) {
  if (active) lastTab = active;
  return `<nav class="tabs"><div class="rail-head">${wordmark()}</div>` + shownTabs().map((t) =>
    `<a class="tab${t.name === active ? " active" : ""}" data-tab="${t.name}"` +
    ` href="${t.href(t.name === active)}"` +
    `${t.name === active ? ' aria-current="page"' : ""}>${t.icon}<span>${t.label}</span></a>`).join("") +
    `</nav>`;
}

// The bar shows its title, and a line, once the page's own title scrolls
// under it. Any h1 on the page, not only the large one: the month has its
// name in a bar of its own, and it is still the name of the screen.
function onScroll() {
  const header = app.querySelector(".nav");
  const large = app.querySelector("main h1");
  if (!header || !large) return;
  header.classList.toggle("lined", large.getBoundingClientRect().bottom < header.getBoundingClientRect().bottom);
}
addEventListener("scroll", onScroll, { passive: true });

export function wireShell() {
  // A screen that draws no tabs — an editor, a thread — drew none because
  // a phone keyboard needs the room. A computer does not, and a rail that
  // comes and goes is worse than no rail at all, so the bar goes in and
  // the shell says it was put there rather than asked for: the stylesheet
  // leaves it out everywhere but the rail.
  const own = !!app.querySelector(".tabs");
  if (!own) app.insertAdjacentHTML("beforeend", tabs(lastTab));
  app.classList.toggle("aside-tabs", !own);
  const header = app.querySelector(".nav");
  if (header && !app.querySelector("main h1")) header.classList.add("lined");
  onScroll();
  for (const button of app.querySelectorAll("[data-back]")) {
    button.addEventListener("click", () => back(button.dataset.back));
  }
  for (const fn of shellHooks) fn();
}

// The word after the date on an editor: Saving…, Saved, Not saved.
export function setStatus(ed, text, bad = false) {
  if (!ed.statusEl) return;
  ed.statusEl.textContent = text;
  ed.statusEl.classList.toggle("bad", bad);
}

// -- go ---------------------------------------------------------------------------------------
export function start() {
  addEventListener("hashchange", route);
  addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush();
    else if (!occupied() && session.token && parseHash().name !== "login") route();
  });
  addEventListener("pagehide", flush);
  if (!location.hash) replace(session.token ? homeHash() : "#/login");
  route();
}
