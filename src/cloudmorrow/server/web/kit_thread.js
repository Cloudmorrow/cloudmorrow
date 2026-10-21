/* The kit's `thread`: spaces, and what is said in them.

   A thread screen binds a `model` that lives in a space (`space`, the link
   field that says which), the field that is what was said (`body`), and
   optionally a field of the space to say under its name (`about`) and how
   spaces are made (`made_as`, see kit_space.js). Four more are a team's:
   `reply_to` (a link of the model to itself: a line with it is a reply,
   drawn in a thread under its parent), `pinned` (a bool: kept at the top),
   `reactions` (a datamodel with a link to the model and an `emoji`: one
   record per person per line, toggled by tapping) and `mentions` (@name in
   a line tells that person; the box offers names as you type an @). A
   screen without them is the conversation it always was. From that it draws:

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
     #/q/<quill>/<screen>/<id>/t/<line>  a line's thread (beside the conversation on a computer)
     #/q/<quill>/<screen>/new          make one
     #/q/<quill>/<screen>/people       write to somebody

   Two datamodels, two kinds of writing (docs/CIRCLES.md): saying something
   is the lines' datamodel's, and on one you may only read, a conversation
   has no box to write in and your own lines are not yours to change;
   making a space, or writing to somebody, is the spaces' datamodel's.

   An open conversation listens to the change feed (changes.js) and asks
   for what changed since the newest thing it has when it hears of a line
   in its space; a push asks at once. While the feed is down it asks on a
   timer instead, every few seconds — for a household that is the whole of
   the real-time problem.

   Nothing in this file knows what a channel or a message is. */

import {
  api, app, esc, formatDate, heading, icons, mount, nav, occupy, onShell, onSignOut, recordsUrl,
  renderRoute, replace, seconds, session, store, tabs, toast, vacate, wireShell,
} from "./core.js";
import { onPush, refreshBadge, onBadge, lastCounts } from "./push.js";
import {
  isBetween, madeAs, people, renderNewSpace, renderSpaceAbout, renderWriteTo, spaceMark,
  spaceName,
} from "./kit_space.js";
import { mayWrite, plural } from "./kit.js";
import { listenChanges } from "./changes.js";
import { ask, askText } from "./dialog.js";

// How often an open conversation asks for what it has not got while the
// change feed is down, how seldom while it is up (a safety net, not the
// way news arrives), and how much of one is read when it opens.
const POLL = 5000;
const POLL_FED = 60000;
const PAGE = 100;
// Lines from one person this close together are one block with one name.
const RUN = 5 * 60;
// The reactions on offer: a short, fixed row, the same on every surface.
export const EMOJI = ["👍", "❤️", "😂", "🎉", "👀", "✅"];
// How a username reads in a line: after an @, at the start or after a space or bracket.
const MENTION = /(^|[\s(\[])@([a-z0-9][a-z0-9._-]*)/g;

const glyphs = {
  people: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.2"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0"/><path d="M16 5.3a3.2 3.2 0 0 1 0 5.4M17.5 14.2A5.5 5.5 0 0 1 20.5 19"/></svg>',
  send: '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M3.2 11.1 20 3.4c.8-.4 1.6.4 1.2 1.2L13.5 21c-.4.8-1.5.7-1.8-.1l-2.1-6-6-2.1c-.8-.3-.9-1.4-.4-1.7Z"/></svg>',
  info: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.6v.1"/></svg>',
  pin: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 17v5M5 17h14l-2-5V9l2-2V5H5v2l2 2v3z"/></svg>',
  close: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
};

// The same query desktop.css draws the rail with: a computer, not a phone on its side.
const desk = () => matchMedia("(min-width: 900px) and (min-height: 600px)").matches;

/** Everything a thread needs from its screen and datamodels. */
function shape(at) {
  const { quill, screen } = at;
  const model = quill.models[screen.model];
  const link = model.fields.find((f) => f.name === screen.space);
  const spaceModel = quill.models[link.to];
  // The team's four, each there or not: a reply's link, a pin's bool, the
  // reactions' datamodel (with its link to the lines and to the space), and
  // whether an @ means somebody.
  const reactions = screen.reactions && quill.models[screen.reactions];
  return {
    model, link, spaceModel, body: screen.body || model.title,
    says: mayWrite(model), makes: mayWrite(spaceModel),
    replyTo: screen.reply_to || "", pinned: screen.pinned || "", mentions: !!screen.mentions,
    reactions: reactions ? reactions.id : "",
    reactionLink: reactions ? (reactions.fields.find((f) => f.kind === "link" && f.to === model.id) || {}).name : "",
    reactionSpace: reactions ? reactions.in_space : "",
    reacts: reactions ? mayWrite(reactions) : false,
  };
}

const lastKey = (at) => "thread.open." + at.tab;
const draftKey = (at, id) => `thread.draft.${at.tab}.${id}`;
export async function renderThread(at, arg) {
  stop();
  const s = shape(at);
  let [first = "", second = "", third = ""] = String(arg || "").split("/");
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
  // …/<id>/t/<line>: the line's thread, beside the conversation or as a page.
  const thread = s.replyTo && second === "t" && third ? third : "";
  if (desk()) return drawSplit(at, s, spaces, open, thread);
  if (open && thread) return drawThreadPage(at, s, spaces, open, thread);
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
    return `<p class="empty mascot"><b>Nothing here yet</b>${s.makes
      ? `Make a ${esc(s.spaceModel.label.toLowerCase())}, and it will show up here.`
      : `When you are in a ${esc(s.spaceModel.label.toLowerCase())}, it will show up here.`}</p>`;
  }
  const group = (label, list) => (list.length
    ? `<p class="group-label">${esc(label)}</p><div class="group">${list.map((x) => spaceRow(at, s, x, active)).join("")}</div>` : "");
  return group(plural(s.spaceModel.label), rooms) + group("Direct", two);
}

function headActions(at, s) {
  if (!s.makes) return "";
  const direct = madeAs(at.screen).direct;
  return (direct ? `<a class="button write-to" href="${at.base}/people" aria-label="New message">${glyphs.people}</a>` : "") +
    `<a class="compose" href="${at.base}/new" aria-label="New ${esc(s.spaceModel.label.toLowerCase())}">${icons.compose}</a>`;
}

function drawList(at, s, spaces) {
  mount(nav({ title: at.screen.label }) + `
    <main class="kit-thread">
      ${heading(at.screen.label, headActions(at, s))}
      <div class="listing">${spaceGroups(at, s, spaces, "")}</div>
    </main>` + tabs(at.tab));
  wireShell();
  let asked = Date.now();
  const refresh = async () => {
    if (document.visibilityState !== "visible") return;
    asked = Date.now();
    try {
      const fresh = await loadSpaces(at, s);
      const listing = app.querySelector(".kit-thread .listing");
      if (listing) listing.innerHTML = spaceGroups(at, s, fresh, "");
    } catch { /* offline: the next tick tries again */ }
  };
  const feed = listenChanges((change) => {
    if (change.model === s.model.id || change.model === s.spaceModel.id) refresh();
  });
  const timer = setInterval(() => {
    if (feed.live && Date.now() - asked < POLL_FED) return;
    refresh();
  }, POLL * 3);
  live = { stop: () => { clearInterval(timer); feed.stop(); }, catchUp: refresh };
  holdUntilLeft();
}

// -- side by side ----------------------------------------------------------------------
function drawSplit(at, s, spaces, open, thread = "") {
  mount(nav({ title: at.screen.label }) + `
    <main class="kit-thread split thread${thread ? " with-thread" : ""}">
      <section class="spaces">
        ${heading(at.screen.label, headActions(at, s))}
        <div class="listing">${spaceGroups(at, s, spaces, open)}</div>
      </section>
      <section class="conversation"></section>
      ${thread ? '<section class="thread-panel"></section>' : ""}
    </main>` + tabs(at.tab));
  wireShell();
  if (open) return drawConversation(at, s, spaces, open, { phone: false, thread });
  app.querySelector(".conversation").innerHTML =
    `<p class="empty"><b>Pick one</b>${s.makes ? "Or start one with the pen." : "It opens here."}</p>`;
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

// A line's words, escaped, with every @name lit when the screen has mentions.
function renderBody(text, mentions) {
  const safe = esc(text ?? "");
  if (!mentions) return safe;
  return safe.replace(MENTION, (m, before, name) => `${before}<span class="mention">@${name}</span>`);
}

/** The reactions under each line: by line id, `[{emoji, count, mine, own}]`
    in the order the row offers them, then any other emoji somebody used. */
export function tally(reactions, linkName, me) {
  const byLine = new Map();
  for (const r of reactions) {
    const line = r.fields[linkName];
    const emoji = r.fields.emoji;
    if (!line || !emoji) continue;
    if (!byLine.has(line)) byLine.set(line, new Map());
    const row = byLine.get(line);
    if (!row.has(emoji)) row.set(emoji, { emoji, count: 0, mine: false, own: null });
    const cell = row.get(emoji);
    cell.count += 1;
    if (r.owner === me) { cell.mine = true; cell.own = r.id; }
  }
  const order = (e) => { const i = EMOJI.indexOf(e); return i < 0 ? EMOJI.length : i; };
  const out = new Map();
  for (const [line, row] of byLine) {
    out.set(line, [...row.values()].sort((a, b) => order(a.emoji) - order(b.emoji) || a.emoji.localeCompare(b.emoji)));
  }
  return out;
}

const chips = (cells, lineId) => cells.length
  ? `<span class="reactions" data-line="${esc(lineId)}">${cells.map((c) =>
    `<button type="button" class="reaction${c.mine ? " mine" : ""}" data-emoji="${esc(c.emoji)}"` +
    ` aria-pressed="${c.mine}">${esc(c.emoji)} ${c.count}</button>`).join("")}</span>` : "";

// *says*: whether you may write here, and so change your own lines.
// *extra* is the team's: {replyTo, pinned, mentions, reacted, replies, threadHref, inThread}.
function renderLines(lines, body, me, says = true, extra = {}) {
  const { replyTo = "", pinned = "", mentions = false, reacted = new Map(), replies = new Map(), threadHref = null,
    inThread = false } = extra;
  // In the conversation the replies are under their parents, not in the run.
  const shown = replyTo && !inThread ? lines.filter((l) => !l.fields[replyTo]) : lines;
  if (!shown.length) return `<p class="empty"><b>Nothing said yet</b>${says ? "Be the first." : ""}</p>`;
  let out = "";
  let day = "";
  let block = null;
  const close = () => { if (block) out += block.html + "</div>"; block = null; };
  for (const line of shown) {
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
    const own = says && line.owner === me;
    const isPinned = pinned && line.fields[pinned];
    const count = replies.get(line.id) || 0;
    block.html += `<p class="bubble${own ? " own" : ""}${isPinned ? " pinned" : ""}" data-id="${esc(line.id)}"` +
      ` tabindex="0" role="button">${isPinned ? `<span class="pin" title="Pinned">${glyphs.pin}</span>` : ""}` +
      `${renderBody(line.fields[body], mentions)}${edited}</p>`;
    const under = chips(reacted.get(line.id) || [], line.id) +
      (count && threadHref && !inThread
        ? `<a class="replies" href="${threadHref(line.id)}">${count} ${count === 1 ? "reply" : "replies"}</a>` : "");
    if (under) block.html += `<p class="under" data-line="${esc(line.id)}">${under}</p>`;
  }
  close();
  return out;
}

async function drawConversation(at, s, spaces, id, { phone, thread = "", page = false }) {
  const space = spaces.find((x) => x.id === id);
  const name = spaceName(s.spaceModel, space, at.screen);
  const about = at.screen.about && !isBetween(at.screen, space) ? space.fields[at.screen.about] : "";
  const aboutHref = `${at.base}/${encodeURIComponent(id)}/about`;
  const threadHref = s.replyTo ? (line) => `${at.base}/${encodeURIComponent(id)}/t/${encodeURIComponent(line)}` : null;
  // Read, the lines are there and the box to write in is not.
  const composer = (s.pinned ? '<div class="pinned-list" hidden></div>' : "") + `
      <div class="messages" aria-live="polite"></div>` + (s.says ? `
      <form class="composer">
        <textarea rows="1" placeholder="Message ${esc(name)}" enterkeyhint="send" autocapitalize="sentences"></textarea>
        <button type="submit" aria-label="Send">${glyphs.send}</button>
      </form>` : `
      <p class="composer-none">You can read what is said here, not write in it.</p>`);
  const pinButton = s.pinned ? `<button type="button" class="icon-button pins" aria-label="Pinned" hidden>${glyphs.pin}<span class="n"></span></button>` : "";
  if (phone && page) {
    // A thread as a page of its own: the conversation's machinery, the thread's screen.
    mount(nav({ back: `${at.base}/${encodeURIComponent(id)}`, backLabel: name, title: "Thread" }) +
      `<main class="kit-thread thread"></main>`);
    wireShell();
  } else if (phone) {
    mount(nav({
      back: at.base,
      backLabel: at.screen.label,
      title: name,
      right: pinButton + `<a class="icon-button" href="${aboutHref}" aria-label="About ${esc(name)}">${glyphs.info}</a>`,
    }) + `<main class="kit-thread thread"><p class="about"><b>${esc(name)}</b>${about ? ` · ${esc(about)}` : ""}</p>${composer}</main>`);
    wireShell();
  } else {
    app.querySelector(".conversation").innerHTML = `
      <header class="conversation-head">
        <span class="main"><span class="title">${esc(name)}</span>${about ? `<span class="about">${esc(about)}</span>` : ""}</span>
        ${pinButton}
        <a class="icon-button" href="${aboutHref}" aria-label="About ${esc(name)}">${glyphs.info}</a>
      </header>${composer}`;
  }
  const root = phone ? app : app.querySelector(".conversation");
  // On a thread page the conversation's own lines are kept off screen.
  const list = root.querySelector(".messages") || document.createElement("div");
  const form = page ? null : root.querySelector("form.composer");
  const box = form && form.querySelector("textarea");
  const me = session.user;
  const where = `${encodeURIComponent(s.link.name)}=${encodeURIComponent(id)}`;
  const reactWhere = s.reactions ? `${encodeURIComponent(s.reactionSpace)}=${encodeURIComponent(id)}` : "";
  let lines = [];
  let reactions = [];
  try {
    [lines, reactions] = await Promise.all([
      api("GET", `${recordsUrl(s.model.id)}?${where}&_last=${PAGE}`),
      s.reactions ? api("GET", `${recordsUrl(s.reactions)}?${reactWhere}`) : [],
    ]);
  } catch (err) { toast(err.message); }
  const state = { lines, reactions, stopped: false, timer: null, ticks: 0, asked: Date.now(), space, thread: null };
  const toBottom = () => { list.scrollTop = list.scrollHeight; };
  // What goes with the lines: the reactions tallied, the replies counted.
  const extras = (inThread = false) => {
    const replies = new Map();
    if (s.replyTo) {
      for (const l of state.lines) {
        const parent = l.fields[s.replyTo];
        if (parent) replies.set(parent, (replies.get(parent) || 0) + 1);
      }
    }
    return {
      replyTo: s.replyTo, pinned: s.pinned, mentions: s.mentions, threadHref, inThread, replies,
      reacted: s.reactions ? tally(state.reactions, s.reactionLink, me) : new Map(),
    };
  };
  const paintPins = () => {
    if (!s.pinned) return;
    const pinned = state.lines.filter((l) => l.fields[s.pinned]);
    const button = root.querySelector(".pins");
    if (button) {
      button.hidden = !pinned.length;
      button.querySelector(".n").textContent = pinned.length;
    }
    const panel = root.querySelector(".pinned-list");
    if (panel && !panel.hidden) {
      panel.innerHTML = `<p class="pinned-head"><b>Pinned</b></p>` +
        renderLines(pinned, s.body, me, false, { ...extras(true), reacted: new Map() });
    }
  };
  const paint = () => {
    const stuck = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
    list.innerHTML = renderLines(state.lines, s.body, me, s.says, extras());
    if (stuck) toBottom();
    paintPins();
    if (state.thread) state.thread.paint();
  };
  list.innerHTML = renderLines(state.lines, s.body, me, s.says, extras());
  toBottom();
  paintPins();
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
  // Reactions come and go, and a gone one is not in a `_since`: they are
  // read whole, a handful of small records, whenever one changed here.
  const freshReactions = async () => {
    if (!s.reactions) return false;
    const got = await api("GET", `${recordsUrl(s.reactions)}?${reactWhere}`);
    const before = JSON.stringify(state.reactions.map((r) => [r.id, r.rev]));
    const after = JSON.stringify(got.map((r) => [r.id, r.rev]));
    state.reactions = got;
    return before !== after;
  };
  const catchUp = async ({ reactions: wantReactions = true } = {}) => {
    if (state.stopped || document.visibilityState !== "visible") return;
    state.asked = Date.now();
    const newest = state.lines.reduce((m, l) => (l.updated_at > m ? l.updated_at : m), "");
    try {
      const fresh = await api("GET", `${recordsUrl(s.model.id)}?${where}` +
        (newest ? `&_since=${encodeURIComponent(newest)}` : `&_last=${PAGE}`));
      // A deleted line is not in a `_since` either: the feed says so (below).
      let changed = merge(fresh);
      if (wantReactions && await freshReactions()) changed = true;
      if (changed) {
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
  // The feed says when a line was said here, or this space changed; the
  // timer is for when the feed is down, and a slow check besides.
  const feed = listenChanges((change) => {
    if (change.space !== id && change.id !== id) return;
    if (change.action === "deleted" && change.model === s.model.id) {
      state.lines = state.lines.filter((l) => l.id !== change.id);
      paint();
    }
    catchUp({ reactions: !s.reactions || change.model === s.reactions || change.action === "deleted" });
  });
  state.timer = setInterval(() => {
    if (feed.live && Date.now() - state.asked < POLL_FED) return;
    catchUp();
  }, POLL);
  live = { stop: () => { state.stopped = true; clearInterval(state.timer); feed.stop(); }, catchUp };
  holdUntilLeft();

  // -- reacting, replying, pinning: a tap on a line -----------------------------------
  const react = async (lineId, emoji) => {
    if (!s.reactions || !s.reacts) return;
    const mine = state.reactions.find((r) => r.owner === me && r.fields[s.reactionLink] === lineId && r.fields.emoji === emoji);
    try {
      if (mine) {
        await api("DELETE", recordsUrl(s.reactions, mine.id));
        state.reactions = state.reactions.filter((r) => r.id !== mine.id);
      } else {
        const made = await api("POST", recordsUrl(s.reactions), {
          fields: { [s.reactionSpace]: id, [s.reactionLink]: lineId, emoji },
        });
        state.reactions = [...state.reactions, made];
      }
      paint();
    } catch (err) { toast(err.message); }
  };
  const pin = async (line) => {
    try {
      const changed = await api("PATCH", recordsUrl(s.model.id, line.id), { fields: { [s.pinned]: !line.fields[s.pinned] } });
      merge([changed]);
      paint();
    } catch (err) { toast(err.message); }
  };
  const lineMenu = (line, { inThread = false } = {}) => {
    const own = s.says && line.owner === me;
    const choices = [];
    if (s.replyTo && !inThread && !line.fields[s.replyTo] && threadHref) {
      choices.push({ label: "Reply in thread", run: () => { replace(threadHref(line.id)); renderRoute(); } });
    }
    if (s.reactions && s.reacts) {
      choices.push({ label: "React", run: () => openSheet(EMOJI.map((e) => ({ label: e, run: () => react(line.id, e) }))) });
    }
    if (s.pinned && (own || (state.space && state.space.can_manage))) {
      choices.push({ label: line.fields[s.pinned] ? "Unpin" : "Pin", run: () => pin(line) });
    }
    if (own) choices.push(...ownChoices(s, state, line, paint));
    if (choices.length) openSheet(choices);
  };
  const wireLines = (where, { inThread = false } = {}) => {
    where.addEventListener("click", (event) => {
      const chip = event.target.closest(".reaction");
      if (chip) {
        react(chip.closest(".reactions").dataset.line, chip.dataset.emoji);
        return;
      }
      if (event.target.closest("a.replies")) return;
      const bubble = event.target.closest(".bubble");
      if (!bubble) return;
      const line = state.lines.find((l) => l.id === bubble.dataset.id);
      if (line) lineMenu(line, { inThread });
    });
    where.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || !event.target.classList.contains("bubble")) return;
      const line = state.lines.find((l) => l.id === event.target.dataset.id);
      if (line) lineMenu(line, { inThread });
    });
  };
  wireLines(list);
  const pinsButton = root.querySelector(".pins");
  if (pinsButton) {
    pinsButton.addEventListener("click", () => {
      const panel = root.querySelector(".pinned-list");
      panel.hidden = !panel.hidden;
      paintPins();
    });
    wireLines(root.querySelector(".pinned-list"), { inThread: true });
  }

  // -- a line's thread, beside the conversation or as the page -------------------------
  if (thread && s.replyTo) {
    state.thread = await drawThread(at, s, state, { id, line: thread, me, merge, paint, wireLines, phone, extras, name });
  }

  // -- writing ------------------------------------------------------------------
  if (!form) return;
  box.value = store.get(draftKey(at, id)) || "";
  grow(box);
  if (!phone && !thread) box.focus();
  box.addEventListener("input", () => { grow(box); store.set(draftKey(at, id), box.value || null); });
  const suggest = s.mentions ? mentionSuggestions(box, form) : null;
  // Enter sends on a keyboard, and the return key on a phone is the send
  // key because `enterkeyhint` made it one. Shift+Enter is a new line.
  box.addEventListener("keydown", (event) => {
    if (suggest && suggest.keydown(event)) return;
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
      list.innerHTML = renderLines(state.lines, s.body, me, s.says, extras());
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
}

// -- a thread: the parent, its replies, and a box of its own ---------------------------
async function drawThread(at, s, state, { id, line, me, merge, paint, wireLines, phone, extras, name }) {
  const panel = phone ? app.querySelector("main.kit-thread") : app.querySelector(".thread-panel");
  if (!panel) return null;
  const backHref = `${at.base}/${encodeURIComponent(id)}`;
  // The parent and every reply, whatever page of the conversation they are on.
  try {
    const [parent, replies] = await Promise.all([
      api("GET", recordsUrl(s.model.id, line)),
      api("GET", `${recordsUrl(s.model.id)}?${encodeURIComponent(s.replyTo)}=${encodeURIComponent(line)}`),
    ]);
    merge([parent, ...replies]);
  } catch (err) {
    toast(err.message);
    replace(backHref);
    return renderRoute();
  }
  panel.innerHTML = (phone ? "" : `
      <header class="conversation-head thread-head">
        <span class="main"><span class="title">Thread</span><span class="about">in ${esc(name)}</span></span>
        <a class="icon-button" href="${backHref}" aria-label="Close the thread">${glyphs.close}</a>
      </header>`) + `
      <div class="messages thread-lines" aria-live="polite"></div>` + (s.says ? `
      <form class="composer">
        <textarea rows="1" placeholder="Reply…" enterkeyhint="send" autocapitalize="sentences"></textarea>
        <button type="submit" aria-label="Send">${glyphs.send}</button>
      </form>` : "");
  const list = panel.querySelector(".thread-lines");
  const form = panel.querySelector("form.composer");
  const box = form && form.querySelector("textarea");
  const mine = () => {
    const parent = state.lines.find((l) => l.id === line);
    const replies = state.lines.filter((l) => l.fields[s.replyTo] === line);
    return parent ? [parent, ...replies] : replies;
  };
  const thread = {
    paint: () => {
      const stuck = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
      list.innerHTML = renderLines(mine(), s.body, me, s.says, extras(true));
      if (stuck) list.scrollTop = list.scrollHeight;
    },
  };
  thread.paint();
  list.scrollTop = list.scrollHeight;
  wireLines(list, { inThread: true });
  if (!form) return thread;
  box.focus();
  box.addEventListener("input", () => grow(box));
  const suggest = s.mentions ? mentionSuggestions(box, form) : null;
  box.addEventListener("keydown", (event) => {
    if (suggest && suggest.keydown(event)) return;
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
    grow(box);
    try {
      const sent = await api("POST", recordsUrl(s.model.id), {
        fields: { [s.link.name]: id, [s.body]: text, [s.replyTo]: line },
      });
      merge([sent]);
      paint();
    } catch (err) {
      box.value = text;
      grow(box);
      toast(err.message);
    }
  });
  return thread;
}

// On a phone a thread is a page of its own, over the conversation.
function drawThreadPage(at, s, spaces, id, line) {
  // The conversation's own machinery, drawn into the page: lines, feed, writing.
  return drawConversation(at, s, spaces, id, { phone: true, thread: line, page: true });
}

// -- @name as you type ------------------------------------------------------------------
/** A short list of people under the box while an @ is being typed; Tab,
    Enter or a tap puts the name in. `keydown(event)` is true when it took the key. */
function mentionSuggestions(box, form) {
  const list = document.createElement("div");
  list.className = "mention-list";
  list.hidden = true;
  form.insertAdjacentElement("beforebegin", list);
  let names = null;
  let shown = [];
  let picked = 0;
  const typing = () => {
    const head = box.value.slice(0, box.selectionStart);
    const m = /(^|[\s(\[])@([a-z0-9._-]*)$/i.exec(head);
    return m ? { prefix: m[2].toLowerCase(), from: head.length - m[2].length - 1 } : null;
  };
  const hide = () => { list.hidden = true; shown = []; };
  const show = async () => {
    const at = typing();
    if (!at) return hide();
    if (!names) {
      try { names = await people(); } catch { names = []; }
    }
    shown = names.filter((p) => p.username.startsWith(at.prefix) ||
      (p.display_name || "").toLowerCase().startsWith(at.prefix)).slice(0, 6);
    if (!shown.length) return hide();
    picked = Math.min(picked, shown.length - 1);
    list.innerHTML = shown.map((p, i) => `<button type="button" class="mention-row${i === picked ? " picked" : ""}" data-i="${i}">` +
      `<b>@${esc(p.username)}</b>${p.display_name && p.display_name !== p.username ? ` <span>${esc(p.display_name)}</span>` : ""}</button>`).join("");
    list.hidden = false;
  };
  const take = (i) => {
    const at = typing();
    const who = shown[i];
    if (!at || !who) return hide();
    const after = box.value.slice(box.selectionStart);
    box.value = `${box.value.slice(0, at.from)}@${who.username} ${after}`;
    const caret = at.from + who.username.length + 2;
    box.setSelectionRange(caret, caret);
    box.dispatchEvent(new Event("input"));
    hide();
    box.focus();
  };
  box.addEventListener("input", () => { picked = 0; show(); });
  box.addEventListener("blur", () => setTimeout(hide, 150));
  list.addEventListener("mousedown", (event) => {
    const row = event.target.closest(".mention-row");
    if (row) { event.preventDefault(); take(Number(row.dataset.i)); }
  });
  return {
    keydown(event) {
      if (list.hidden) return false;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        picked = (picked + (event.key === "ArrowDown" ? 1 : shown.length - 1)) % shown.length;
        show();
        event.preventDefault();
        return true;
      }
      if (event.key === "Tab" || event.key === "Enter") { event.preventDefault(); take(picked); return true; }
      if (event.key === "Escape") { hide(); return true; }
      return false;
    },
  };
}

function ownChoices(s, state, line, repaint) {
  return [
    { label: "Edit", run: async () => {
      const text = (await askText("Edit your message", line.fields[s.body] || "", { long: true }) || "").trim();
      if (!text || text === line.fields[s.body]) return;
      try {
        const changed = await api("PATCH", recordsUrl(s.model.id, line.id), { fields: { [s.body]: text }, rev: line.rev });
        state.lines = state.lines.map((l) => (l.id === line.id ? changed : l));
        repaint();
      } catch (err) { toast(err.status === 409 ? "That changed somewhere else" : err.message); }
    } },
    { label: "Delete", bad: true, run: async () => {
      if (!await ask("Delete this message? It goes for everybody.")) return;
      try {
        await api("DELETE", recordsUrl(s.model.id, line.id));
        state.lines = state.lines.filter((l) => l.id !== line.id);
        repaint();
      } catch (err) { toast(err.message); }
    } },
  ];
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
