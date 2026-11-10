/* The apps, wherever the tabs are: favorites, the phone's More, the rail
   folded to its icons.

   core.js draws the tabs; this file answers what is pressed on them. An
   app — a Quill's tab, or Data — has a menu that marks it a favorite: on
   a computer the dots at the end of its row in the rail, or a right-click;
   on a phone a finger held on it, in the bar or in More. The rail's head
   folds the rail to a strip of icons and unfolds it again. */

import { adoptFavorites, api, app, appList, isFavorite, session, setFavorite, setRailFolded } from "./core.js";
import { contextMenus, menu } from "./actions.js";
import { openSheet } from "./dialog.js";

/** What an app's menu holds: Open, and the favorite switch. */
function choicesFor(el) {
  const name = el.dataset.tab;
  if (!name) return null;
  const href = el.getAttribute("href");
  const fav = isFavorite(name);
  return [
    { label: "Open", run: () => { location.hash = href; } },
    { label: fav ? "Remove from Favorites" : "Add to Favorites", run: () => setFavorite(name, !fav) },
  ];
}

// A right-click on an app in the rail, a finger held on one in the bar.
contextMenus(app, "nav.tabs > .tab.app, nav.tabs > .tab.copy", choicesFor);

// Ahead of core.js's own tab click (which lights the tab and follows it):
// the dots on a row, the fold and unfold at the rail's head, and More.
app.addEventListener("click", (event) => {
  const dots = event.target.closest("nav.tabs .tab-menu");
  if (dots) {
    event.preventDefault();
    event.stopPropagation();
    const box = dots.getBoundingClientRect();
    menu(choicesFor(dots.closest(".tab")) || [], { x: box.left, y: box.bottom + 4 });
    return;
  }
  if (event.target.closest("nav.tabs .rail-fold")) { setRailFolded(true); return; }
  if (event.target.closest("nav.tabs .rail-unfold")) { setRailFolded(false); return; }
  if (event.target.closest("nav.tabs > .tab.more")) {
    event.preventDefault();
    event.stopPropagation();
    openAll();
  }
}, true);

// The favorites are kept on you: what the server has is the bar's, asked
// when the page opens and whenever it comes back into view — marked on the
// phone, they are on the computer the next time you look at it.
function heardFavorites() {
  if (!session.token) return;
  api("GET", "/api/auth/me").then((me) => adoptFavorites(me.favorites)).catch(() => {});
}
heardFavorites();
addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") heardFavorites(); });

// -- More: every app, in a sheet -------------------------------------------------------
function tiles() {
  const { apps, favorites } = appList();
  const tile = (t) => {
    const fav = favorites.includes(t.name);
    return `<a class="app-tile${fav ? " fav" : ""}" data-tab="${t.name}" href="${t.href(false)}">` +
      `<span class="app-icon">${typeof t.icon === "function" ? t.icon() : t.icon}</span>` +
      `<span class="app-name">${t.label}</span>${fav ? `<span class="app-star" aria-label="Favorite">★</span>` : ""}</a>`;
  };
  return `<div class="app-grid">${apps.map(tile).join("")}</div>`;
}

function openAll() {
  const { sheet } = openSheet(
    `<p class="act-sheet-title">All apps</p>` +
    `<p class="act-description">Hold an app to add it to your favorites. Your favorites are the apps in the bar.</p>` +
    `<div class="app-list">${tiles()}</div>`, "app-sheet");
  const list = sheet.querySelector(".app-list");
  // A favorite marked here is starred here at once, as well as in the bar.
  contextMenus(list, ".app-tile", (el) => {
    const choices = choicesFor(el);
    if (!choices) return null;
    const fav = choices[1];
    return [choices[0], { ...fav, run: () => { fav.run(); list.innerHTML = tiles(); } }];
  });
}
