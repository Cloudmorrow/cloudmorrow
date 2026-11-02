/* Notifications: what happened while you were not looking, behind the bell.

   The bell is in the bar's corner on every screen that is a tab, beside Me,
   whether anything is waiting or not; this is where it leads. The last fifty
   lines anyone left for you — a machine's sync, an approval asked, a flow's
   word, a Quill updated — newest first. Opening the list reads them all, the
   way the terminal app's bell does, and the count on the bell goes out.

   A browser that has not been asked yet is offered the banners at the top:
   on a computer, Chrome then pops each of these as it lands, and a click on
   one comes back here. */

import {
  api, app, esc, formatDate, homeHash, mount, nav, previousHash, registerScreen, seconds, sectionOf,
  wireShell,
} from "./core.js";
import { pushCard, refreshBadge, state as pushState, wirePushCard } from "./push.js";

// The words of what the bell has to say, row by row.
function noteRow(note) {
  const at = seconds(note.created_at);
  const meta = [note.machine, at ? formatDate(at) : ""].filter(Boolean).map(esc).join(" · ");
  return `<div class="row note-row${note.unread ? " is-new" : ""}">
    <span class="main"><span class="title">${esc(note.title)}</span>
    ${note.body ? `<span class="note-body">${esc(note.body)}</span>` : ""}
    <span class="meta"><span class="preview">${meta}</span></span></span></div>`;
}

function grouped(notes) {
  const sections = [];
  for (const note of notes) {
    const title = sectionOf(seconds(note.created_at) || 0);
    let section = sections.find((s) => s.title === title);
    if (!section) sections.push(section = { title, notes: [] });
    section.notes.push(note);
  }
  return sections.map((s) =>
    `<p class="group-label">${esc(s.title)}</p><div class="group">${s.notes.map(noteRow).join("")}</div>`).join("");
}

async function renderNotifications() {
  const notes = await api("GET", "/api/notifications?limit=50");
  const from = previousHash();
  const back = from && from !== "#/notifications" ? from : homeHash();
  // Offered until it is on: asking, or saying where it was turned off.
  const offer = ["default", "denied"].includes(pushState()) ? pushCard() : "";
  mount(nav({ back, backLabel: "Back", title: "Notifications" }) + `
    <main class="notifications">
      <h1 class="large">Notifications</h1>
      ${offer}
      ${notes.length ? grouped(notes)
        : `<p class="empty"><b>Nothing yet</b>What the machines and the Quills have to tell you lands here.</p>`}
    </main>`);
  wireShell();
  wirePushCard(app);
  if (notes.some((n) => n.unread)) {
    try { await api("POST", "/api/notifications/read", {}); } catch { /* read next time */ }
    refreshBadge();
  }
}

registerScreen("notifications", renderNotifications);
