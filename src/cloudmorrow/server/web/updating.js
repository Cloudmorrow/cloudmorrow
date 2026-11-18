/* The server, as the whole app hears it: going away for an update, and its
   Quills moving.

   One connection to the change feed for the app itself (changes.js), open
   for as long as somebody is signed in, whatever screen is up:

   - **bye**: the server is stopping, which on a server is an update almost
     every time. A sheet says so — The server is updating, hold on a sec —
     over everything, with a little animation, and asks which deploy is
     served (fresh.js) every second and a half until the server answers.
     Then fresh.js reloads the page if the server is serving a newer deploy (and leaves an editor with
     unsaved words alone), or the sheet just goes. Nothing is pressed: it
     comes and it goes by itself.
   - **quills**: a Quill came, went or was switched, here or by somebody. The
     menu is asked for again and drawn again (quills.js), and nothing else:
     the screen, a form being filled, a sheet that is open stay as they are.
     A tab that is new gets a moment of attention there. */

import { onShell, session } from "./core.js";
import { listenChanges } from "./changes.js";
import { checkForUpdate, serving } from "./fresh.js";
import { quillsMoved } from "./quills.js";

const PROBE = 1500;
// After this long it says it is taking a while, and keeps waiting.
const LONG = 90 * 1000;
// Everybody hears of a Quill at the same moment; they ask over a second or
// two rather than all at once.
const SPREAD = 1500;

let feed = null;
let sheet = null;
let moving = null;

function watch() {
  if (feed && feed.ended) feed = null;
  if (feed || !session.token) return;
  feed = listenChanges(() => {}, { onBye: hold, onNotice: heard });
}

function heard(name) {
  if (name !== "quills" || moving) return;
  moving = setTimeout(() => {
    moving = null;
    quillsMoved();
  }, Math.random() * SPREAD);
}

// -- the server is updating ---------------------------------------------------------
function hold() {
  if (sheet) return;
  sheet = document.createElement("div");
  sheet.className = "sheet-backdrop updating-backdrop";
  sheet.innerHTML =
    `<div class="sheet updating-sheet" role="alertdialog" aria-modal="true" aria-live="polite" aria-labelledby="updating-said">` +
    `<div class="updating-mark" aria-hidden="true"><i></i><i></i><i></i><i></i></div>` +
    `<p class="updating-said" id="updating-said">The server is updating</p>` +
    `<p class="updating-more">Hold on for a sec — this carries on by itself when it is back.</p>` +
    `</div>`;
  document.body.appendChild(sheet);
  if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
  probe(Date.now());
}

async function probe(since) {
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, PROBE));
    if (Date.now() - since > LONG && sheet) {
      sheet.querySelector(".updating-more").textContent =
        "This is taking longer than usual. It carries on by itself when the server is back.";
    }
    if (await serving()) break;
  }
  // A newer deploy is a new page; the same one is where it was.
  if (await checkForUpdate({ force: true })) return;
  if (sheet) sheet.remove();
  sheet = null;
}

// The shell is drawn on every screen once somebody is signed in — after a
// sign-in too, which goes on with replaceState and so with no hashchange.
onShell(watch);
addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") watch(); });
watch();
