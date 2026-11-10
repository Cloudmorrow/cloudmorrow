/* Notifications: what happened while you were not looking, behind the bell.

   The bell is in the bar's corner on every screen that is a tab, beside Me,
   whether anything is waiting or not; this is where it leads. The last fifty
   lines anyone left for you — a line written in a channel, a machine's sync,
   an approval asked, a flow's word, a Quill updated — newest first. A line
   that happened in a Quill opens it, and is read; opening the Quill's space
   reads its lines here too. The rest stay unread until **Mark all as read**,
   beside the title, puts the count on the bell out.

   A browser that has not been asked yet is offered the banners at the top:
   on a computer, Chrome then pops each of these as it lands, and a click on
   one comes back here. */

import {
  api, app, esc, formatDate, go, heading, homeHash, mount, nav, previousHash, registerScreen, seconds,
  sectionOf, toast, wireShell,
} from "./core.js";
import { pushCard, refreshBadge, state as pushState, wirePushCard } from "./push.js";

// The words of what the bell has to say, row by row.
function noteRow(note) {
  const at = seconds(note.created_at);
  const meta = [note.machine, at ? formatDate(at) : ""].filter(Boolean).map(esc).join(" · ");
  // Only a place in this app: `#/…`, never a link out.
  const opens = /^#\//.test(note.url || "");
  const tag = opens ? "a" : "div";
  return `<${tag} class="row note-row${note.unread ? " is-new" : ""}${opens ? " opens" : ""}" data-id="${note.id}"` +
    `${opens ? ` href="${esc(note.url)}"` : ""}>
    <span class="main"><span class="title">${esc(note.title)}</span>
    ${note.body ? `<span class="note-body">${esc(note.body)}</span>` : ""}
    <span class="meta"><span class="preview">${meta}</span></span></span></${tag}>`;
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
  const unread = notes.some((n) => n.unread);
  mount(nav({ back, backLabel: "Back", title: "Notifications" }) + `
    <main class="notifications">
      ${heading("Notifications", unread ? `<button type="button" class="read-all">Mark all as read</button>` : "")}
      ${offer}
      ${notes.length ? grouped(notes)
        : `<p class="empty"><b>Nothing yet</b>What the machines and the Quills have to tell you lands here.</p>`}
    </main>`);
  wireShell();
  wirePushCard(app);
  const main = app.querySelector("main.notifications");
  const readAll = main.querySelector(".read-all");
  if (readAll) {
    readAll.addEventListener("click", async () => {
      readAll.disabled = true;
      try {
        await api("POST", "/api/notifications/read", {});
      } catch {
        readAll.disabled = false;
        toast("They could not be marked read. Try again.");
        return;
      }
      for (const row of main.querySelectorAll(".note-row.is-new")) row.classList.remove("is-new");
      readAll.remove();
      refreshBadge();
    });
  }
  // A line is read when it is opened; one with nowhere to go, when tapped.
  main.addEventListener("click", async (event) => {
    const row = event.target.closest(".note-row");
    if (!row) return;
    const opens = row.classList.contains("opens");
    if (opens) event.preventDefault();
    if (row.classList.contains("is-new")) {
      row.classList.remove("is-new");
      try { await api("POST", "/api/notifications/read", { ids: [Number(row.dataset.id)] }); } catch { /* read next time */ }
      refreshBadge();
      if (readAll && readAll.isConnected && !main.querySelector(".note-row.is-new")) readAll.remove();
    }
    if (opens) go(row.getAttribute("href"));
  });
}

registerScreen("notifications", renderNotifications);
