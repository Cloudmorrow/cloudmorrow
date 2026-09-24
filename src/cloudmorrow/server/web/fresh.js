/* Following a deploy: the page replaces itself once the server has moved on.

   An app on a phone's home screen is opened, hidden and opened again for
   weeks without ever being loaded, so a deploy reaches it only when it is
   force closed. This asks the server which deploy it is serving — when the
   app comes back to the front, and now and then while it is up — and a
   different answer than this page was built from is a reload.

   Words being written outrank a new version: an editor holding unsaved text
   is left alone, and the check comes round again. */

import { app, occupied } from "./core.js";

// The deploy this page was built from. The server puts the same string in
// every asset URL, so a different one means these files are last week's.
const BUILT = app.dataset.deploy || "";

// While the app is up, and at most this often when it is woken — switching
// back and forth between apps should not be a stream of requests.
const EVERY = 10 * 60 * 1000;
const GAP = 30 * 1000;

let asked = 0;

async function serving() {
  try {
    const res = await fetch("/app/version", { cache: "no-store" });
    if (!res.ok) return "";
    const body = await res.json();
    return typeof body.deploy === "string" ? body.deploy : "";
  } catch {
    // Offline, or the server is part way through a restart. Not news.
    return "";
  }
}

export async function checkForUpdate({ force = false } = {}) {
  if (!BUILT || document.visibilityState !== "visible") return false;
  if (!force && Date.now() - asked < GAP) return false;
  asked = Date.now();
  const now = await serving();
  if (!now || now === BUILT || occupied()) return false;
  location.reload();
  return true;
}

addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") checkForUpdate();
});
// Coming back from the back/forward cache does not always change visibility,
// and on a phone that is exactly how the app is reopened.
addEventListener("pageshow", (event) => {
  if (event.persisted) checkForUpdate({ force: true });
});
setInterval(checkForUpdate, EVERY);
