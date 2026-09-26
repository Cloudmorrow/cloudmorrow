/* Which of the app you want: a switch per feature, in Me.

   There are two switches on every feature and only one of them is yours.
   An administrator's takes the feature off this server for everybody; this
   one takes its tab off your own screens, here and in the terminal alike.
   So the list below is only ever what the server offers — a feature
   switched off up there is not in it at all, because a tick box you cannot
   have an opinion about is worse than no tick box.

   It hides rather than forbids: the API still answers you, and a link
   straight to a hidden screen still works. That is the difference between
   a preference and a feature, and it is deliberate — a preference that
   locked you out would be a mistake with no way back from the phone you
   made it on.

   The answers are fetched once per load and kept in local storage by
   core.js, so the tab bar is drawn right the moment the page is rather
   than a tab disappearing a beat after you look at it. */

import {
  api, esc, gatedFeatures, onShell, onSignOut, session, setFeaturesOff, store, tabs, toast,
} from "./core.js";

let features = [];
// Whether this session has asked yet. One ask covers signing in, since the
// first screen after it goes through the shell like any other.
let asked = false;
// What was last handed to the shell, so a redraw happens when the answer
// moves and not otherwise. Held here rather than read back out of storage,
// which is allowed to be a hole in the ground in a private window.
let handed = store.get("features.off") || "";

/** Redraw the bar at the bottom in place, keeping the tab you are on. */
export function redrawTabs() {
  const bar = document.querySelector(".tabs");
  if (!bar) return;
  const active = bar.querySelector(".tab.active");
  bar.outerHTML = tabs(active ? active.dataset.tab : "");
}

/** Ask the server what this account has, tell the shell, and redraw if it moved. */
export async function loadFeatures() {
  if (!session.token) return features;
  try {
    features = await api("GET", "/api/me/features");
  } catch {
    return features;   // offline: the tabs stay as they were last drawn
  }
  apply();
  return features;
}

/** Hand the answers to the shell, and redraw the bar when they have changed. */
function apply() {
  const on = new Set(features.filter((f) => f.enabled).map((f) => f.key));
  // What the server left out is off as surely as what it said was off: a
  // feature an administrator has switched off never reaches this list.
  const off = gatedFeatures().filter((key) => !on.has(key));
  setFeaturesOff(off);
  if (off.join(",") === handed) return;
  handed = off.join(",");
  redrawTabs();
}

// -- the card in Me -------------------------------------------------------------
export function featuresCard() {
  if (!features.length) return "";
  // A feature with no tab here is one the terminal app has and this one
  // does not — Projects, today. The switch is still yours to throw, so the
  // row says where it lands rather than being left out or lying.
  const here = new Set(gatedFeatures());
  return `<p class="group-label">What your cloud shows you</p>
    <div class="group features-card">${features.map((feature) => {
      const where = here.has(feature.key) ? "" : " · only in the terminal app";
      return `
      <label class="row feature">
        <span class="main"><span class="title">${esc(feature.label)}</span>
        <span class="meta"><span class="preview">${esc(feature.description + where)}</span></span></span>
        <input type="checkbox" data-feature="${esc(feature.key)}"${feature.enabled ? " checked" : ""}>
      </label>`;
    }).join("")}</div>
    <p class="features-note">A tab each. Switching one off takes it out of this
      app and the terminal one alike; nothing of yours is deleted, and it comes
      back here.</p>`;
}

/** Wire whatever `featuresCard` put on the page. Safe to call when it did not. */
export function wireFeaturesCard(root = document) {
  for (const box of root.querySelectorAll(".features-card input[type=checkbox]")) {
    box.addEventListener("change", async () => {
      const key = box.dataset.feature;
      const wanted = box.checked;
      box.disabled = true;
      try {
        const feature = await api("PATCH", "/api/me/features/" + encodeURIComponent(key),
          { enabled: wanted });
        features = features.map((f) => (f.key === key ? feature : f));
        // The bar at the bottom is drawn from the same answer, so it is
        // redrawn in place rather than waiting for the next screen.
        apply();
        toast(feature.enabled ? `${feature.label} is back` : `${feature.label} is off`);
      } catch (err) {
        box.checked = !wanted;
        toast(err.message);
      } finally {
        box.disabled = false;
      }
    });
  }
}

// A different account on the same phone has different answers, and until it
// says so the safe assumption is that it has everything.
onSignOut(() => {
  features = [];
  asked = false;
  handed = "";
  setFeaturesOff([]);
});

// -- keeping up -----------------------------------------------------------------
// Once per session, on whichever screen comes first after signing in, and
// again whenever the app comes back to the front — which is when an
// administrator's switch, thrown while the phone was in a pocket, arrives.
onShell(() => {
  if (!session.token || asked) return;
  asked = true;
  loadFeatures();
});

addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && session.token) loadFeatures();
});

if (session.token) loadFeatures();
