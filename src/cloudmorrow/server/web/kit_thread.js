/* The kit's `thread`: spaces, and what is said in them.

   A thread screen binds a `model` that lives in a space (`space`, the link
   field that says which), the field that is what was said (`body`), and
   optionally a field of the space to say under its name (`about`) and how
   spaces are made (`made_as`, see kit_space.js). From that alone it draws:

     the list      every space you can see, newest first, with what is
                   unread in each and the last line said; the ones made
                   between people are named for whoever else is in them
     a conversation  newest at the bottom, a rule for each day, one name
                   over each run of lines from one person, and a box to
                   write in; opening it marks the space seen

   On a phone they are one screen and then the other; on a computer, side
   by side. The addresses, under the screen's own:

     #/q/<quill>/<screen>              the list (a computer opens the last one beside it)
     #/q/<quill>/<screen>/<id>         one conversation
     #/q/<quill>/<screen>/<id>/about   what it is, and who is in it
     #/q/<quill>/<screen>/new          make one
     #/q/<quill>/<screen>/people       write to somebody

   There is no socket. An open conversation asks for what changed since the
   newest thing it has, every few seconds, and a push asks at once — for a
   household that is the whole of the real-time problem.

   Nothing in this file knows what a channel or a message is. */

import {
  api, app, esc, formatDate, heading, icons, nav, occupy, onShell, onSignOut, replace,
  renderRoute, seconds, session, store, tabs, toast, vacate, wireShell,
} from "./core.js";
import { onPush, refreshBadge, onBadge, lastCounts } from "./push.js";
import {
  isBetween, madeAs, recordsUrl, renderNewSpace, renderSpaceAbout, renderWriteTo, spaceMark,
  spaceName,
} from "./kit_space.js";

// How often an open conversation asks for what it has not got, and how
// much of one is read when it opens.
const POLL = 5000;
const PAGE = 100;
// Lines from one person this close together are one block with one name.
const RUN = 5 * 60;

const glyphs = {
  people: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.2"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0"/><path d="M16 5.3a3.2 3.2 0 0 1 0 5.4M17.5 14.2A5.5 5.5 0 0 1 20.5 19"/></svg>',
  send: '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M3.2 11.1 20 3.4c.8-.4 1.6.4 1.2 1.2L13.5 21c-.4.8-1.5.7-1.8-.1l-2.1-6-6-2.1c-.8-.3-.9-1.4-.4-1.7Z"/></svg>',
  info: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.6v.1"/></svg>',
};

// The same query desktop.css draws the rail with: a computer, not a phone on its side.
const desk = () => matchMedia("(min-width: 900px) and (min-height: 600px)").matches;

/** Everything a thread needs from its screen and datamodels. */
function shape(at) {
  const { quill, screen } = at;
  const model = quill.models[screen.model];
  const link = model.fields.find((f) => f.name === screen.space);
  const spaceModel = quill.models[link.to];
  return { model, link, spaceModel, body: screen.body || model.title };
}

const lastKey = (at) => "thread.open." + at.tab;
const draftKey = (at, id) => `thread.draft.${at.tab}.${id}`;
const plural = (label) => (/s$/i.test(label) ? label : label + "s");

export async function renderThread(at, arg) {
  stop();
  const s = shape(at);
  let [first = "", second = ""] = String(arg || "").split("/");
  // The record sheet of a space goes back to `…/spaces`: here that is the list.
  if (first === "spaces") first = "";
  const back = at.base;
  const backLabel = at.screen.label;
  const opened = (made) => { replace(`${at.base}/${encodeURIComponent(made.id)}`); renderRoute(); };
  if (first === "new") return renderNewSpace(at, s.spaceModel, { back, backLabel, opened });
  if (first === "people") return renderWriteTo(at, s.spaceModel, { back, backLabel, opened });
  if (first && second === "about") {
    return renderSpaceAbout(at, s.spaceModel, first, {
      back: `${at.base}/${encodeURIComponent(first)}`,
      backLabel: "Back",
      gone: () => { store.set(lastKey(at), null); replace(at.base); renderRoute(); },
    });
  }
  const spaces = await loadSpaces(at, s);
  let open = first;
  if (!open && desk()) {
    const remembered = store.get(lastKey(at));
    open = (spaces.find((x) => x.id === remembered) || spaces[0] || {}).id || "";
  }
  if (open && !spaces.some((x) => x.id === open)) {
    toast(`That ${s.spaceModel.label.toLowerCase()} is not one of yours`);
    store.set(lastKey(at), null);
    replace(at.base);
    return renderRoute();
  }
  if (!first) store.set(lastKey(at), desk() ? open || null : null);
  if (desk()) return drawSplit(at, s, spaces, open);
  if (open) return drawConversation(at, s, spaces, open, { phone: true });
  return drawList(at, s, spaces);
}

// -- the spaces ------------------------------------------------------------------------
async function loadSpaces(at, s) {
  const spaces = await api("GET", recordsUrl(s.spaceModel.id));
  // Newest activity first; one nobody has written in yet sorts by when it
  // was made, which is the same question.
  const when = (x) => seconds((x.last && x.last.created_at) || x.created_at) || 0;
  return spaces.sort((a, b) => when(b) - when(a));
}

const unreadPill = (n) => (n ? `<span class="unread">${n > 99 ? "99+" : n}</span>` : "");

function spaceRow(at, s, space, active) {
  const two = isBetween(at.screen, space);
  const last = space.last;
  const line = last
    ? (two || last.owner !== session.user ? (two ? "" : `${last.owner}: `) : "You: ") + last.title
    : (at.screen.about && space.fields[at.screen.about]) || "Nothing said yet";
  const when = seconds((last && last.created_at) || space.created_at);
  return `<a class="row space-row${space.unread ? " has-unread" : ""}${space.id === active ? " current" : ""}"
      href="${at.base}/${encodeURIComponent(space.id)}" data-id="${esc(space.id)}">
    ${spaceMark(s.spaceModel, space, at.screen)}
    <span class="main">
      <span class="title">${esc(spaceName(s.spaceModel, space, at.screen))}</span>
      <span class="meta"><span class="preview">${esc(line)}</span></span>
    </span>
    <span class="aside">${when ? `<span class="date">${esc(formatDate(when))}</span>` : ""}${unreadPill(space.unread)}</span>
  </a>`;
}

function spaceGroups(at, s, spaces, active) {
  const rooms = spaces.filter((x) => !isBetween(at.screen, x));
  const two = spaces.filter((x) => isBetween(at.screen, x));
  if (!spaces.length) {
    return `<p class="empty mascot"><b>Nothing here yet</b>Make a ${esc(s.spaceModel.label.toLowerCase())}, and it will show up here.</p>`;
  }
  const group = (label, list) => (list.length
    ? `<p class="group-label">${esc(label)}</p><div class="group">${list.map((x) => spaceRow(at, s, x, active)).join("")}</div>` : "");
  return group(plural(s.spaceModel.label), rooms) + group("Direct", two);
}

function headActions(at, s) {
  const direct = madeAs(at.screen).direct;
  return (direct ? `<a class="button write-to" href="${at.base}/people" aria-label="New message">${glyphs.people}</a>` : "") +
    `<a class="compose" href="${at.base}/new" aria-label="New ${esc(s.spaceModel.label.toLowerCase())}">${icons.compose}</a>`;
}

function drawList(at, s, spaces) {
  app.innerHTML = nav({ title: at.screen.label }) + `
    <main class="kit-thread">
      ${heading(at.screen.label, headActions(at, s))}
      <div class="listing">${spaceGroups(at, s, spaces, "")}</div>
    </main>` + tabs(at.tab);
  wireShell();
  const timer = setInterval(async () => {
    if (document.visibilityState !== "visible") return;
    try {
      const fresh = await loadSpaces(at, s);
      const listing = app.querySelector(".kit-thread .listing");
      if (listing) listing.innerHTML = spaceGroups(at, s, fresh, "");
    } catch { /* offline: the next tick tries again */ }
  }, POLL * 3);
  live = { stop: () => clearInterval(timer), catchUp: () => {} };
  holdUntilLeft();
}

// -- side by side ----------------------------------------------------------------------
function drawSplit(at, s, spaces, open) {
  app.innerHTML = nav({ title: at.screen.label }) + `
    <main class="kit-thread split thread">
      <section class="spaces">
        ${heading(at.screen.label, headActions(at, s))}
        <div class="listing">${spaceGroups(at, s, spaces, open)}</div>
      </section>
      <section class="conversation"></section>
    </main>` + tabs(at.tab);
  wireShell();
  if (open) return drawConversation(at, s, spaces, open, { phone: false });
  app.querySelector(".conversation").innerHTML =
    `<p class="empty"><b>Pick one</b>Or start one with the pen.</p>`;
  live = { stop: () => {}, catchUp: () => {} };
  holdUntilLeft();
}

// -- one conversation ----------------------------------------------------------------------
let live = null;   // {stop, catchUp} while a thread screen is up

function stop() {
  if (live) live.stop();
  live = null;
}

// The core's hold on the screen: told when the address moves off it, so an
// open conversation stops asking for lines nobody is looking at.
function holdUntilLeft() {
  const mine = live;
  const hold = {
    stays: () => false,
    leave: async () => { if (live === mine) stop(); vacate(hold); },
    flush: () => {},
  };
  occupy(hold);
}

function dayOf(stamp) {
  const date = new Date(Date.parse(stamp));
  const today = new Date();
  const days = Math.round((new Date(today.getFullYear(), today.getMonth(), today.getDate()) -
    new Date(date.getFullYear(), date.getMonth(), date.getDate())) / 86400000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  return date.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long",
    year: date.getFullYear() === today.getFullYear() ? undefined : "numeric" });
}

function renderLines(lines, body, me) {
  if (!lines.length) return `<p class="empty"><b>Nothing said yet</b>Be the first.</p>`;
  let out = "";
  let day = "";
  let block = null;
  const close = () => { if (block) out += block.html + "</div>"; block = null; };
  for (const line of lines) {
    const when = seconds(line.created_at) || 0;
    const thisDay = dayOf(line.created_at);
    if (thisDay !== day) {
      close();
      day = thisDay;
      out += `<p class="day-rule"><span>${esc(day)}</span></p>`;
    }
    if (!block || block.owner !== line.owner || when - block.when > RUN) {
      close();
      const mine = line.owner === me;
      block = { owner: line.owner, when, html: `<div class="block${mine ? " mine" : ""}">` +
        `<p class="who"><b>${esc(mine ? "You" : line.owner)}</b><span class="date">${esc(formatDate(when))}</span></p>` };
    }
    block.when = when;
    const edited = line.updated_at !== line.created_at ? '<span class="edited">edited</span>' : "";
    block.html += `<p class="bubble${line.owner === me ? " own" : ""}" data-id="${esc(line.id)}"` +
      `${line.owner === me ? ' tabindex="0" role="button"' : ""}>${esc(line.fields[body] ?? "")}${edited}</p>`;
  }
  close();
  return out;
}

async function drawConversation(at, s, spaces, id, { phone }) {
  const space = spaces.find((x) => x.id === id);
  const name = spaceName(s.spaceModel, space, at.screen);
  const about = at.screen.about && !isBetween(at.screen, space) ? space.fields[at.screen.about] : "";
  const aboutHref = `${at.base}/${encodeURIComponent(id)}/about`;
  const composer = `
      <div class="messages" aria-live="polite"></div>
      <form class="composer">
        <textarea rows="1" placeholder="Message ${esc(name)}" enterkeyhint="send" autocapitalize="sentences"></textarea>
        <button type="submit" aria-label="Send">${glyphs.send}</button>
      </form>`;
  if (phone) {
    app.innerHTML = nav({
      back: at.base,
      backLabel: at.screen.label,
      title: name,
      right: `<a class="icon-button" href="${aboutHref}" aria-label="About ${esc(name)}">${glyphs.info}</a>`,
    }) + `<main class="kit-thread thread"><p class="about"><b>${esc(name)}</b>${about ? ` · ${esc(about)}` : ""}</p>${composer}</main>`;
    wireShell();
  } else {
    app.querySelector(".conversation").innerHTML = `
      <header class="conversation-head">
        <span class="main"><span class="title">${esc(name)}</span>${about ? `<span class="about">${esc(about)}</span>` : ""}</span>
        <a class="icon-button" href="${aboutHref}" aria-label="About ${esc(name)}">${glyphs.info}</a>
      </header>${composer}`;
  }
  const root = phone ? app : app.querySelector(".conversation");
  const list = root.querySelector(".messages");
  const form = root.querySelector("form.composer");
  const box = form.querySelector("textarea");
  const me = session.user;
  const where = `${encodeURIComponent(s.link.name)}=${encodeURIComponent(id)}`;
  let lines = [];
  try {
    lines = await api("GET", `${recordsUrl(s.model.id)}?${where}&_last=${PAGE}`);
  } catch (err) { toast(err.message); }
  const state = { lines, stopped: false, timer: null, ticks: 0 };
  const toBottom = () => { list.scrollTop = list.scrollHeight; };
  const paint = () => {
    const stuck = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
    list.innerHTML = renderLines(state.lines, s.body, me);
    if (stuck) toBottom();
  };
  list.innerHTML = renderLines(state.lines, s.body, me);
  toBottom();
  if (!phone) store.set(lastKey(at), id);

  const seen = async () => {
    try {
      await api("POST", recordsUrl(s.spaceModel.id, id, "/seen"));
      refreshBadge();
      const row = app.querySelector(`.space-row[data-id="${CSS.escape(id)}"]`);
      if (row) {
        row.classList.remove("has-unread");
        const pill = row.querySelector(".unread");
        if (pill) pill.remove();
      }
    } catch { /* it is marked again on the next line that arrives */ }
  };
  seen();

  // Anything changed since the newest thing on screen: new lines and edits.
  const merge = (fresh) => {
    if (!fresh.length) return false;
    const byId = new Map(state.lines.map((l) => [l.id, l]));
    let changed = false;
    for (const line of fresh) {
      const had = byId.get(line.id);
      if (!had || had.rev !== line.rev) { byId.set(line.id, line); changed = true; }
    }
    if (changed) {
      state.lines = [...byId.values()].sort((a, b) =>
        (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0));
    }
    return changed;
  };
  const catchUp = async () => {
    if (state.stopped || document.visibilityState !== "visible") return;
    const newest = state.lines.reduce((m, l) => (l.updated_at > m ? l.updated_at : m), "");
    try {
      const fresh = await api("GET", `${recordsUrl(s.model.id)}?${where}` +
        (newest ? `&_since=${encodeURIComponent(newest)}` : `&_last=${PAGE}`));
      if (merge(fresh)) {
        paint();
        await seen();
      }
      state.ticks += 1;
      // Beside the list, the other spaces' counts move too, less often.
      if (!phone && state.ticks % 3 === 0) {
        const listing = app.querySelector(".kit-thread .spaces .listing");
        if (listing) listing.innerHTML = spaceGroups(at, s, await loadSpaces(at, s), id);
      }
    } catch { /* offline: the next tick tries again */ }
  };
  state.timer = setInterval(catchUp, POLL);
  live = { stop: () => { state.stopped = true; clearInterval(state.timer); }, catchUp };
  holdUntilLeft();

  // -- writing ------------------------------------------------------------------
  box.value = store.get(draftKey(at, id)) || "";
  grow(box);
  if (!phone) box.focus();
  box.addEventListener("input", () => { grow(box); store.set(draftKey(at, id), box.value || null); });
  // Enter sends on a keyboard, and the return key on a phone is the send
  // key because `enterkeyhint` made it one. Shift+Enter is a new line.
  box.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = box.value.trim();
    if (!text) return;
    box.value = "";
    store.set(draftKey(at, id), null);
    grow(box);
    try {
      const sent = await api("POST", recordsUrl(s.model.id), { fields: { [s.link.name]: id, [s.body]: text } });
      merge([sent]);
      list.innerHTML = renderLines(state.lines, s.body, me);
      toBottom();
      // Beside the list, this one now leads it, with your line under its name.
      const listing = !phone && app.querySelector(".kit-thread .spaces .listing");
      if (listing) listing.innerHTML = spaceGroups(at, s, await loadSpaces(at, s), id);
    } catch (err) {
      // The words go back rather than being lost to a dropped connection.
      box.value = text;
      grow(box);
      toast(err.message);
    }
  });

  // -- your own lines: change them, or take them back -------------------------------
  list.addEventListener("click", (event) => {
    const bubble = event.target.closest(".bubble.own");
    if (!bubble) return;
    const line = state.lines.find((l) => l.id === bubble.dataset.id);
    if (line) ownLine(s, state, line, () => paint());
  });
}

function ownLine(s, state, line, repaint) {
  openSheet([
    { label: "Edit", run: async () => {
      const text = (prompt("Edit your message", line.fields[s.body] || "") || "").trim();
      if (!text || text === line.fields[s.body]) return;
      try {
        const changed = await api("PATCH", recordsUrl(s.model.id, line.id), { fields: { [s.body]: text }, rev: line.rev });
        state.lines = state.lines.map((l) => (l.id === line.id ? changed : l));
        repaint();
      } catch (err) { toast(err.status === 409 ? "That changed somewhere else" : err.message); }
    } },
    { label: "Delete", bad: true, run: async () => {
      if (!confirm("Delete this message? It goes for everybody.")) return;
      try {
        await api("DELETE", recordsUrl(s.model.id, line.id));
        state.lines = state.lines.filter((l) => l.id !== line.id);
        repaint();
      } catch (err) { toast(err.message); }
    } },
  ]);
}

// A sheet from the bottom, the phone's way of asking which of a few things
// you meant. Tapping outside it, or Cancel, is no.
function openSheet(choices) {
  const backdrop = document.createElement("div");
  backdrop.className = "sheet-backdrop";
  backdrop.innerHTML = `<div class="sheet" role="menu">` +
    choices.map((c, i) => `<button class="sheet-row${c.bad ? " bad" : ""}" role="menuitem" data-choice="${i}"><span>${esc(c.label)}</span></button>`).join("") +
    `<button class="sheet-row cancel">Cancel</button></div>`;
  backdrop.addEventListener("click", (event) => {
    const row = event.target.closest("[data-choice]");
    backdrop.remove();
    if (row) choices[Number(row.dataset.choice)].run();
  });
  document.body.appendChild(backdrop);
}

// A one-line box that grows to the message and stops before it eats the
// screen; past that it scrolls inside itself, and below it never.
const MAX_BOX = 140;
function grow(box) {
  box.style.height = "auto";
  const wanted = box.scrollHeight;
  box.style.height = Math.min(wanted, MAX_BOX) + "px";
  box.style.overflowY = wanted > MAX_BOX ? "auto" : "hidden";
}

// -- the pip on a thread's tab -----------------------------------------------------------
// Something unread in any space lights the tab of every thread screen,
// when the list is not the screen you are on.
function paintPip(counts) {
  for (const tab of document.querySelectorAll(".tabs .tab[data-thread]")) {
    tab.classList.toggle("pipped", (counts.messages || 0) > 0);
  }
}
export function markThreadTabs(names) {
  for (const name of names) {
    const tab = document.querySelector(`.tabs .tab[data-tab="${CSS.escape(name)}"]`);
    if (tab) tab.dataset.thread = "1";
  }
  paintPip(lastCounts());
}

onBadge(paintPip);
// A push for the conversation on screen is answered at once rather than on
// the next tick; one for another only moves the counts.
onPush(() => { if (live) live.catchUp(); });
onSignOut(stop);
onShell(() => paintPip(lastCounts()));
