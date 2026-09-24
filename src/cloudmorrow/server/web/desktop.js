/* The keys a computer has and a phone does not.

   Nothing here is a new way to do anything. Every key stands in for
   something already on the screen — the back button in the bar, the
   search field, the Compose button, the row you are on — so a screen
   without the thing does not answer the key, and there is nothing to
   learn that the screen does not already say.

     Esc      the sheet, or the field you are in, or the back button
     /        the search field
     n        the pen beside the title, whatever this screen makes one of
     j k      down and up the list
     ↑ ↓      the same, once the list has the keyboard
     Enter    opens the row it is on, which is the browser's own doing

   Held to the same query the stylesheet uses — a pointer with a keyboard
   beside it — so on a phone this file is one listener that returns. */

import { app } from "./core.js";

const desk = () => matchMedia("(min-width: 900px) and (min-height: 600px)").matches;

const FIELD = /^(INPUT|TEXTAREA|SELECT)$/;
const typing = (el) => !!el && (FIELD.test(el.tagName) || el.isContentEditable);

/** What Enter would open: the rows and tiles that are a link or a button. */
const items = () => [...app.querySelectorAll(
  "main a.row[href], main button.row:not(:disabled), main a.tile[href]")];

/** Move the keyboard down or up the list. `fromTop` may start one. */
function move(delta, fromTop) {
  const all = items();
  if (!all.length) return false;
  const here = all.indexOf(document.activeElement);
  if (here === -1) {
    // The arrows still scroll the page until the list has been entered,
    // which is what the page would do without this file.
    if (!fromTop) return false;
    all[delta > 0 ? 0 : all.length - 1].focus();
    return true;
  }
  all[Math.min(all.length - 1, Math.max(0, here + delta))].focus();
  return true;
}

function click(selector) {
  const el = app.querySelector(selector) || document.querySelector(selector);
  if (el) el.click();
  return !!el;
}

function search() {
  const field = app.querySelector(".search input");
  if (!field) return false;
  field.focus();
  field.select();
  return true;
}

addEventListener("keydown", (event) => {
  if (!desk() || event.defaultPrevented) return;
  if (event.metaKey || event.ctrlKey || event.altKey) return;

  // Escape is the only one that answers while you are writing, and all it
  // does is put the field down. The editors save on their own, so there
  // is nothing to lose by pressing it.
  if (event.key === "Escape") {
    if (document.querySelector(".sheet-backdrop .sheet-row.cancel")) {
      click(".sheet-backdrop .sheet-row.cancel");
    } else if (typing(document.activeElement)) {
      document.activeElement.blur();
    } else if (!click(".nav [data-back]")) {
      return;
    }
    event.preventDefault();
    return;
  }
  if (typing(document.activeElement)) return;

  let took = false;
  switch (event.key) {
    case "/": took = search(); break;
    case "n": took = click(".heading .compose") || click(".heading .add"); break;
    case "j": case "ArrowDown": took = move(1, event.key === "j"); break;
    case "k": case "ArrowUp": took = move(-1, event.key === "k"); break;
  }
  if (took) event.preventDefault();
});
