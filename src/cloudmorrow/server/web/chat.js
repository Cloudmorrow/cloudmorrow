/* Chat: channels on one side, the people you write to directly on the other.

   Four screens. The list, which is both of those under a switch; a channel,
   which is the messages and the box you type in; the sheet for making a
   channel; and a channel's own page, for who is in it and the way out.

   There is no socket. A channel that is open asks for anything after the
   last id it has, every few seconds, and a push wakes it the moment one
   arrives — so the common case is instant and the fallback is a small
   request that usually answers with an empty list. For a house with a
   handful of people in it, that is the whole of the real-time problem, and
   it keeps the server a plain request-and-response thing that a phone on a
   train reconnects to without noticing. */

import {
  api, app, back, esc, formatDate, heading, icons, nav, onShell, onSignOut, pixelIcon,
  registerScreen, registerTab, renderRoute, replace, seconds, session, store, tabs, toast,
  wireShell,
} from "./core.js";
import { lastCounts, onBadge, onPush, refreshBadge } from "./push.js";

// How often an open channel asks for what it has not got. The push is what
// makes it prompt; this is the floor under a push that never came.
const POLL = 5000;

const channelUrl = (slug) => "/api/chat/channels/" + encodeURIComponent(slug);
const isDirect = (c) => c.kind === "direct";

let channels = [];
let people = [];
// The last screen you were on, so the tab goes back where you were.
const lastOpen = () => store.get("chat.open") || "";

// A message half typed is kept per channel, so tapping into another one and
// back does not throw it away.
const draftKey = (slug) => "chat.draft." + slug;

// -- the icons this feature draws -------------------------------------------------
const glyphs = {
  people: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.2"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0"/><path d="M16 5.3a3.2 3.2 0 0 1 0 5.4M17.5 14.2A5.5 5.5 0 0 1 20.5 19"/></svg>',
  send: '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M3.2 11.1 20 3.4c.8-.4 1.6.4 1.2 1.2L13.5 21c-.4.8-1.5.7-1.8-.1l-2.1-6-6-2.1c-.8-.3-.9-1.4-.4-1.7Z"/></svg>',
  info: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.6v.1"/></svg>',
};

// -- the list --------------------------------------------------------------------------
async function load() {
  channels = await api("GET", "/api/chat/channels");
  return channels;
}

const unreadPill = (n) => (n ? `<span class="unread">${n > 99 ? "99+" : n}</span>` : "");

function channelRow(c) {
  const when = c.last_message ? seconds(c.last_message.created_at) : seconds(c.created_at);
  const line = c.last_message
    ? (isDirect(c) ? "" : `${c.last_message.author}: `) + c.last_message.body
    : c.topic || "Nothing said yet";
  const mark = isDirect(c)
    ? `<span class="avatar" aria-hidden="true">${esc(c.name.charAt(0).toUpperCase() || "?")}</span>`
    : `<span class="hash" aria-hidden="true">#</span>`;
  return `<a class="row chat-row${c.unread ? " has-unread" : ""}" href="#/chat/${encodeURIComponent(c.slug)}">
    ${mark}
    <span class="main">
      <span class="title">${esc(c.name)}</span>
      <span class="meta"><span class="preview">${esc(line)}</span></span>
    </span>
    <span class="aside">${when ? `<span class="date">${esc(formatDate(when))}</span>` : ""}${unreadPill(c.unread)}</span>
  </a>`;
}

async function renderList(arg) {
  if (arg) return renderChannel(arg);
  store.set("chat.open", "");
  await load();
  const which = store.get("chat.side") === "direct" ? "direct" : "channels";
  const rooms = channels.filter((c) => !isDirect(c));
  const directs = channels.filter(isDirect);
  const showing = which === "direct" ? directs : rooms;
  const waiting = (list) => list.reduce((n, c) => n + c.unread, 0);

  app.innerHTML = nav({ title: "Chat" }) + `
    <main>
      ${heading("Chat", `<button class="compose" aria-label="${which === "direct" ? "New message" : "New channel"}">${icons.compose}</button>`)}
      <div class="sides">
        <button data-side="channels"${which === "channels" ? ' class="active"' : ""}>Channels${unreadPill(waiting(rooms))}</button>
        <button data-side="direct"${which === "direct" ? ' class="active"' : ""}>Direct${unreadPill(waiting(directs))}</button>
      </div>
      <div class="listing">${
        showing.length
          ? `<div class="group">${showing.map(channelRow).join("")}</div>`
          : `<p class="empty"><b>${which === "direct" ? "No messages yet" : "No channels yet"}</b>${
              which === "direct" ? "Tap the pencil to write to somebody." : "Tap the pencil to make one."
            }</p>`
      }</div>
    </main>` + tabs("chat");
  wireShell();

  for (const button of app.querySelectorAll(".sides button")) {
    button.addEventListener("click", () => {
      store.set("chat.side", button.dataset.side);
      renderList("");
    });
  }
  app.querySelector(".heading .compose").addEventListener("click", () => {
    location.hash = which === "direct" ? "#/chatpeople" : "#/chatnew";
  });
}

// -- one channel ----------------------------------------------------------------------
let thread = null;   // {slug, messages, timer} while a channel is on screen

function stopThread() {
  if (thread && thread.timer) clearInterval(thread.timer);
  thread = null;
}

function messageBlocks(messages, me) {
  // Consecutive lines by the same person, close together in time, are one
  // block with one name on it — which is how a conversation reads.
  const blocks = [];
  for (const message of messages) {
    const last = blocks[blocks.length - 1];
    const when = seconds(message.created_at) || 0;
    if (last && last.author === message.author && when - last.when < 300) {
      last.messages.push(message);
      last.when = when;
    } else {
      blocks.push({ author: message.author, mine: message.author === me, when, messages: [message] });
    }
  }
  return blocks;
}

function renderBlocks(messages, me) {
  if (!messages.length) {
    return `<p class="empty"><b>Nothing said yet</b>Be the first.</p>`;
  }
  return messageBlocks(messages, me).map((block) => `
    <div class="block${block.mine ? " mine" : ""}">
      <p class="who"><b>${esc(block.mine ? "You" : block.author)}</b>
        <span class="date">${esc(formatDate(block.when))}</span></p>
      ${block.messages.map((m) =>
        `<p class="bubble" data-id="${m.id}">${esc(m.body)}${
          m.edited_at ? '<span class="edited">edited</span>' : ""}</p>`).join("")}
    </div>`).join("");
}

async function renderChannel(slug) {
  stopThread();
  let channel;
  try {
    channel = await api("GET", channelUrl(slug));
  } catch (err) {
    if (err.status === 404 || err.status === 403) {
      toast(err.status === 403 ? "That channel is not yours" : "That channel is gone");
      replace("#/chat");
      return renderRoute();
    }
    throw err;
  }
  store.set("chat.open", slug);
  const messages = await api("GET", channelUrl(slug) + "/messages?limit=50");
  const me = session.user;

  app.innerHTML = nav({
    back: "#/chat",
    backLabel: "Chat",
    title: channel.name,
    right: `<a class="icon-button" href="#/chatinfo/${encodeURIComponent(slug)}" aria-label="About this channel">${glyphs.info}</a>`,
  }) + `
    <main class="thread">
      <div class="messages">${renderBlocks(messages, me)}</div>
      <form class="composer">
        <textarea rows="1" placeholder="Message ${esc(channel.name)}" enterkeyhint="send"
          autocapitalize="sentences"></textarea>
        <button type="submit" aria-label="Send">${glyphs.send}</button>
      </form>
    </main>`;
  wireShell();

  const list = app.querySelector(".messages");
  const form = app.querySelector("form.composer");
  const box = form.querySelector("textarea");
  thread = { slug, messages, timer: null };

  box.value = store.get(draftKey(slug)) || "";
  grow(box);
  const toBottom = () => { list.scrollTop = list.scrollHeight; };
  toBottom();
  await seen();

  box.addEventListener("input", () => {
    grow(box);
    store.set(draftKey(slug), box.value || null);
  });
  // Enter sends on a keyboard; on a phone the return key is the send key
  // because `enterkeyhint` made it one. Shift+Enter is a new line.
  box.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = box.value.trim();
    if (!body) return;
    box.value = "";
    store.set(draftKey(slug), null);
    grow(box);
    try {
      const sent = await api("POST", channelUrl(slug) + "/messages", { body });
      append([sent]);
      toBottom();
    } catch (err) {
      // Put the words back rather than losing them to a dropped connection.
      box.value = body;
      grow(box);
      toast(err.message);
    }
  });

  function append(fresh) {
    if (!thread || !fresh.length) return;
    const known = new Set(thread.messages.map((m) => m.id));
    const added = fresh.filter((m) => !known.has(m.id));
    if (!added.length) return;
    thread.messages = thread.messages.concat(added);
    const stuck = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
    list.innerHTML = renderBlocks(thread.messages, me);
    if (stuck) toBottom();
  }

  async function seen() {
    const top = thread && thread.messages.length
      ? thread.messages[thread.messages.length - 1].id : 0;
    try {
      await api("POST", channelUrl(slug) + "/read", { upto: top || null });
      refreshBadge();
    } catch { /* it will be marked again on the next line that arrives */ }
  }

  async function catchUp() {
    if (!thread || thread.slug !== slug || document.visibilityState !== "visible") return;
    const after = thread.messages.length ? thread.messages[thread.messages.length - 1].id : 0;
    try {
      const fresh = await api("GET", channelUrl(slug) + `/messages?after=${after}`);
      if (fresh.length) {
        append(fresh);
        await seen();
      }
    } catch { /* offline; the next tick tries again */ }
  }

  thread.timer = setInterval(catchUp, POLL);
  thread.catchUp = catchUp;
}

// A one-line box that grows to the message and stops before it eats the
// screen. It grows upwards on its own: the composer is the last row of the
// thread's column, so a taller box takes the room from the messages above
// rather than pushing the page down.
const MAX_BOX = 140;

function grow(box) {
  box.style.height = "auto";
  const wanted = box.scrollHeight;
  box.style.height = Math.min(wanted, MAX_BOX) + "px";
  // Past that it scrolls inside itself; below it, never — a scrollbar on a
  // two-line message is the thing that made this look broken.
  box.style.overflowY = wanted > MAX_BOX ? "auto" : "hidden";
}

// -- making a channel ----------------------------------------------------------------
async function renderNew() {
  people = await api("GET", "/api/chat/people");
  app.innerHTML = nav({ back: "#/chat", backLabel: "Chat", title: "New channel" }) + `
    <main>
      <h1 class="large">New channel</h1>
      <form class="new-channel">
        <div class="group">
          <label class="row"><span class="main">Name</span>
            <input name="name" placeholder="homelab" autocapitalize="none" required></label>
          <label class="row"><span class="main">Topic</span>
            <input name="topic" placeholder="what it is for"></label>
        </div>
        <p class="group-label">Who can see it</p>
        <div class="group kinds">
          <label class="row"><input type="radio" name="kind" value="public" checked>
            <span class="main"><span class="title">Public</span>
            <span class="meta"><span class="preview">Everybody is in it, and can write in it.</span></span></span></label>
          <label class="row"><input type="radio" name="kind" value="private">
            <span class="main"><span class="title">Private</span>
            <span class="meta"><span class="preview">Only the people you pick. They are added, not invited.</span></span></span></label>
        </div>
        <div class="who-list" hidden>
          <p class="group-label">People</p>
          <div class="group">${people.map((p) => `
            <label class="row"><input type="checkbox" name="member" value="${esc(p.username)}">
              <span class="main">${esc(p.display_name || p.username)}</span></label>`).join("")
            || `<p class="empty"><b>Nobody else yet</b>Make an account for them first.</p>`}</div>
        </div>
        <div class="group"><button class="row primary" type="submit">Make the channel</button></div>
      </form>
    </main>`;
  wireShell();

  const form = app.querySelector("form.new-channel");
  const whoList = app.querySelector(".who-list");
  const showWho = () => {
    whoList.hidden = form.elements.kind.value !== "private";
  };
  for (const radio of form.querySelectorAll('input[name="kind"]')) {
    radio.addEventListener("change", showWho);
  }
  showWho();

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = form.elements.name.value.trim();
    if (!name) return;
    const members = [...form.querySelectorAll('input[name="member"]:checked')].map((b) => b.value);
    try {
      const made = await api("POST", "/api/chat/channels", {
        name,
        kind: form.elements.kind.value,
        topic: form.elements.topic.value.trim(),
        members,
      });
      store.set("chat.side", "channels");
      replace("#/chat/" + encodeURIComponent(made.slug));
      renderRoute();
    } catch (err) {
      toast(err.message);
    }
  });
}

// -- writing to a person ------------------------------------------------------------
async function renderPeople() {
  people = await api("GET", "/api/chat/people");
  app.innerHTML = nav({ back: "#/chat", backLabel: "Chat", title: "New message" }) + `
    <main>
      <h1 class="large">New message</h1>
      ${people.length ? `<div class="group">${people.map((p) => `
        <button class="row person" data-who="${esc(p.username)}">
          <span class="avatar" aria-hidden="true">${esc((p.display_name || p.username).charAt(0).toUpperCase())}</span>
          <span class="main"><span class="title">${esc(p.display_name || p.username)}</span>
          ${p.display_name ? `<span class="meta"><span class="preview">${esc(p.username)}</span></span>` : ""}</span>
          ${icons.chevronRight}</button>`).join("")}</div>`
        : `<p class="empty"><b>Nobody else yet</b>There is only your account on this server.</p>`}
    </main>`;
  wireShell();

  for (const button of app.querySelectorAll(".person")) {
    button.addEventListener("click", async () => {
      try {
        const made = await api("POST", "/api/chat/direct", { username: button.dataset.who });
        store.set("chat.side", "direct");
        replace("#/chat/" + encodeURIComponent(made.slug));
        renderRoute();
      } catch (err) { toast(err.message); }
    });
  }
}

// -- a channel's own page ---------------------------------------------------------------
async function renderInfo(slug) {
  const channel = await api("GET", channelUrl(slug));
  const back = "#/chat/" + encodeURIComponent(slug);
  const mine = channel.created_by === session.user;
  people = isDirect(channel) ? [] : await api("GET", "/api/chat/people");
  const outside = people.filter((p) => !channel.members.includes(p.username));

  const facts = [
    ["Kind", { public: "Public — everybody is in it", private: "Private", direct: "Direct" }[channel.kind]],
    channel.topic && ["Topic", channel.topic],
    channel.created_by && !isDirect(channel) && ["Made by", channel.created_by],
  ].filter(Boolean);

  app.innerHTML = nav({ back, backLabel: channel.name, title: "About" }) + `
    <main>
      <h1 class="large">${esc(channel.name)}</h1>
      <div class="group facts">${facts.map(([label, value]) =>
        `<div class="row"><span class="main">${esc(label)}</span><span class="fact">${esc(value)}</span></div>`).join("")}</div>
      <p class="group-label">In here (${channel.members.length})</p>
      <div class="group members">${channel.members.map((who) =>
        `<div class="row"><span class="avatar" aria-hidden="true">${esc(who.charAt(0).toUpperCase())}</span>
         <span class="main">${esc(who)}${who === session.user ? " (you)" : ""}</span></div>`).join("")}</div>
      ${channel.kind === "private" && outside.length ? `
        <p class="group-label">Add somebody</p>
        <div class="group">${outside.map((p) => `
          <button class="row add-who" data-who="${esc(p.username)}">
            <span class="main">${esc(p.display_name || p.username)}</span>
            <span class="value">Add</span></button>`).join("")}</div>` : ""}
      ${channel.kind === "private" ? `<div class="group"><button class="row bad leave">Leave this channel</button></div>` : ""}
      ${mine && !isDirect(channel) ? `<div class="group"><button class="row bad delete">Delete this channel</button></div>` : ""}
    </main>`;
  wireShell();

  for (const button of app.querySelectorAll(".add-who")) {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await api("POST", channelUrl(slug) + "/members", { usernames: [button.dataset.who] });
        toast(`${button.dataset.who} is in`);
        renderInfo(slug);
      } catch (err) { toast(err.message); button.disabled = false; }
    });
  }
  const leave = app.querySelector(".leave");
  if (leave) {
    leave.addEventListener("click", async () => {
      if (!confirm(`Leave ${channel.name}? You will stop getting its messages.`)) return;
      try {
        await api("POST", channelUrl(slug) + "/leave");
        replace("#/chat");
        renderRoute();
      } catch (err) { toast(err.message); }
    });
  }
  const remove = app.querySelector(".delete");
  if (remove) {
    remove.addEventListener("click", async () => {
      if (!confirm(`Delete ${channel.name}? Everything said in it goes too.`)) return;
      try {
        await api("DELETE", channelUrl(slug));
        replace("#/chat");
        renderRoute();
      } catch (err) { toast(err.message); }
    });
  }
}

// -- the tab, and the pip on it -----------------------------------------------------------
function paintPip(counts) {
  const tab = document.querySelector('.tabs .tab[href^="#/chat"]');
  if (!tab) return;
  tab.classList.toggle("pipped", (counts.messages || 0) > 0);
}

registerScreen("chat", renderList);
registerScreen("chatnew", renderNew);
registerScreen("chatpeople", renderPeople);
registerScreen("chatinfo", renderInfo);
registerTab({
  name: "chat",
  feature: "chat",
  label: "Chat",
  icon: pixelIcon("chat"),
  // Tapping the tab you are on goes to the list; from elsewhere it returns
  // you to the channel you were last in, which is what a chat app does.
  href: (active) => (active || !lastOpen() ? "#/chat" : "#/chat/" + encodeURIComponent(lastOpen())),
});

onShell(() => paintPip(lastCounts()));
onBadge(paintPip);
// A push for the channel on screen is answered at once rather than on the
// next tick; one for another channel only moves the counts.
onPush(() => { if (thread && thread.catchUp) thread.catchUp(); });
onSignOut(() => { stopThread(); channels = []; people = []; });
addEventListener("hashchange", () => {
  const { hash } = location;
  if (thread && !hash.startsWith("#/chat/" + encodeURIComponent(thread.slug))) stopThread();
});
