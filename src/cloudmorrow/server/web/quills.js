/* The Quills: every tab the server has and this file does not know about.

   A Quill ships no screens of its own — it names a kit element and binds
   it to fields, and kit.js draws it. So this file is only the part in
   between: ask the server which Quills are installed, give each of their
   screens a tab, and hand the address bar's `#/q/…` and `#/r/…` to the kit.

     #/q/<quill>/<screen>              a screen: the board, the list
     #/q/<quill>/<screen>/<group>      a board, on one of its groups
     #/q/<quill>/<screen>/<g>/<sub>    a list, on a group and a subgroup
     #/r/<quill>/<screen>/<model>/<id> one record, on the record sheet

   The tabs sit where this file is imported in app.js — after Notes, where
   Tasks always was — through a slot core.js holds open for them, because
   the answer arrives after the bar is first drawn. What the server said
   last time is kept in local storage, like the feature switches, so that
   first bar is already right rather than growing a tab a beat later. */

import {
  api, go, onShell, onSignOut, pixelArt, pixelIcon, registerScreen, renderRoute, replace,
  session, store, tabSlot, toast,
} from "./core.js";
import { loadFeatures, redrawTabs } from "./features.js";
import { renderKitScreen, renderRecordSheet } from "./kit.js";

// A quill, for a Quill whose icon names nothing this app draws yet: the
// nib down at the left, the feather up to the right.
const QUILL_GLYPH = [
  "......XX",
  ".....X.X",
  "....X.X.",
  "...X.X..",
  "..X.X...",
  "..XX....",
  ".X......",
  "X.......",
];

const fillTabs = tabSlot();
let quills = [];
let loaded = null;   // the one request in flight, so a burst of screens asks once

const tabName = (quill, screen) => `${quill.id}.${screen.id}`;
export const screenHash = (quill, screen) =>
  `#/q/${encodeURIComponent(quill.id)}/${encodeURIComponent(screen.id)}`;

function place(list) {
  quills = list;
  fillTabs(list.flatMap((quill) => quill.screens.map((screen) => ({
    name: tabName(quill, screen),
    label: screen.label || quill.name,
    icon: pixelIcon(quill.icon) || pixelArt(QUILL_GLYPH),
    // The Quill is the feature: the administrator's switch and your own
    // take its tabs away together, as they did when Tasks was built in.
    feature: quill.id,
    href: () => screenHash(quill, screen),
  }))));
}

try { place(JSON.parse(store.get("quills") || "[]")); } catch { place([]); }

/** Ask the server which Quills there are, and put their tabs in the bar. */
export function loadQuills() {
  if (!session.token) return Promise.resolve(quills);
  loaded = loaded || (async () => {
    try {
      const list = await api("GET", "/api/quills");
      store.set("quills", JSON.stringify(list));
      place(list);
      redrawTabs();
      // The switches are asked about per tab, and these tabs are new since
      // the last time they were asked.
      await loadFeatures();
    } catch { /* offline: the tabs stay as they were last drawn */ }
    return quills;
  })();
  return loaded;
}

/** After an install or a removal: forget the answer and ask again. */
export function refreshQuills() {
  loaded = null;
  return loadQuills();
}

// -- the two addresses ----------------------------------------------------------
async function find(quillId, screenId) {
  // The cached answer draws the tabs; a screen wants the server's own.
  await loadQuills();
  const quill = quills.find((q) => q.id === quillId);
  const screen = quill && quill.screens.find((s) => s.id === screenId);
  if (screen) return { quill, screen, tab: tabName(quill, screen), base: screenHash(quill, screen) };
  toast(quill ? "That screen is gone" : "That Quill is not installed");
  replace("#/");
  await renderRoute();
  return null;
}

registerScreen("q", async (arg) => {
  // The rest is where on the screen: a board's group, a list's group and subgroup.
  const [quillId, screenId, ...group] = arg.split("/");
  const at = await find(quillId, screenId);
  if (at) await renderKitScreen(at, group.join("/"));
});

registerScreen("r", async (arg) => {
  const [quillId, screenId, model, id] = arg.split("/");
  const at = await find(quillId, screenId);
  if (!at) return;
  if (!at.quill.models[model] || !id) { go(at.base); return; }
  await renderRecordSheet(at, model, id, arg);
});

// -- keeping up -------------------------------------------------------------------
onShell(() => { if (session.token && !loaded) loadQuills(); });
onSignOut(() => {
  loaded = null;
  store.set("quills", null);
  place([]);
});
if (session.token) loadQuills();
