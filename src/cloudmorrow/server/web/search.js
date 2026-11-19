/* Search: one field in the middle of the screen, for everything.

   `/` or Ctrl K (⌘K on a Mac) opens it from anywhere, and so does the bar
   at the foot of the rail. What comes first is the apps — every Quill, and
   the screens inside one — so the quickest way to Tasks is `/ ta Enter`.
   Under them, once two letters are typed, the things in them by name: the
   notes, tasks, files and the rest each Quill lists, asked of the record
   API with its own `q`, a handful per Quill.

   ↑ and ↓ walk the list, Enter opens the one lit, Esc puts it away. */

import { api, appList, esc, icons, pixelIcon, recordsUrl, session } from "./core.js";
import { quillList, screenHash } from "./quills.js";

// Kits whose records are not "a thing by name" but lines in a conversation.
const NOT_LISTED = new Set(["data", "thread", "conversation"]);
const PER_QUILL = 5;
const WAIT_MS = 160;
const MAX_SHARES = 8;

export const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");
/** The other key, as this computer writes it. */
export const OTHER_KEY = isMac ? "⌘K" : "Ctrl K";

let open = null;   // { backdrop, field, list, hits, lit, asked }

// -- what is searched -----------------------------------------------------------------
/** Every app and every screen in one, each with where it goes. */
function apps() {
  const out = [];
  for (const t of appList().apps) {
    out.push({ kind: "app", label: t.label, icon: typeof t.icon === "function" ? t.icon() : t.icon, href: t.href(false) });
    for (const s of t.screens || []) {
      out.push({ kind: "app", label: s.label, within: t.label, icon: s.icon || t.icon, href: s.href(false) });
    }
  }
  return out;
}

/** How well *label* answers *q*: 3 it starts so, 2 a word in it does, 1 it holds it. */
function score(label, q) {
  const l = label.toLowerCase();
  if (l.startsWith(q)) return 3;
  if (l.split(/[\s›/._-]+/).some((w) => w.startsWith(q))) return 2;
  return l.includes(q) ? 1 : 0;
}

function matchingApps(q) {
  const all = apps();
  if (!q) return all.filter((a) => !a.within);
  return all
    .map((a) => ({ a, s: Math.max(score(a.label, q), a.within ? score(a.within, q) - 1 : 0) }))
    .filter((x) => x.s > 0)
    .sort((x, y) => y.s - x.s || (x.a.within ? 1 : 0) - (y.a.within ? 1 : 0))
    .map((x) => x.a);
}

/** The Quills' lists: for each datamodel, the first screen that shows it. */
function lists() {
  const out = [];
  for (const quill of quillList()) {
    const seen = new Set();
    for (const screen of quill.screens) {
      if (screen.admin || screen.settings || !screen.model || NOT_LISTED.has(screen.kit)) continue;
      const model = quill.models && quill.models[screen.model];
      if (!model || seen.has(screen.model)) continue;
      if (Array.isArray(model.can) && !model.can.includes("search")) continue;
      seen.add(screen.model);
      out.push({ quill, screen, model, title: screen.title || model.title });
    }
  }
  // A screen that says where (Notes: the Notes folder of My Files) asks
  // first, so a note is Notes' rather than Files' as well.
  return out.sort((a, b) => (b.screen.where ? 1 : 0) - (a.screen.where ? 1 : 0));
}

const nameOf = (record, title, suffix) => {
  const f = record.fields || {};
  let v = f[title] ?? f.title ?? f.name;
  if (typeof v !== "string") return "";
  // A note is "Party", not "Party.md": the screen says the suffix it hides.
  for (const end of [].concat(suffix || [])) if (v.toLowerCase().endsWith(end)) v = v.slice(0, -end.length);
  return v.trim();
};

/** Where a screen's records are asked for: what it says, or — a screen
    grouped by share, as Files is, which lists a share at a time — each
    share you can open, My Files first. */
async function wheres(screen) {
  if (screen.where || screen.group !== "share") return [screen.where || {}];
  const shares = await api("GET", recordsUrl("share")).catch(() => []);
  const open = (shares || []).filter((s) => s.fields && s.fields.browsable !== false).slice(0, MAX_SHARES);
  return open.length ? open.map((s) => ({ share: s.id })) : [{ share: "my-files" }];
}

async function records(q) {
  const asked = lists().map(async (l) => {
    const each = await Promise.allSettled((await wheres(l.screen)).map((where) =>
      api("GET", recordsUrl(l.screen.model) + "?" + new URLSearchParams({ ...where, q }))));
    const found = each.flatMap((s) => (s.status === "fulfilled" ? s.value || [] : []));
    return found
      .map((r) => ({ r, name: nameOf(r, l.title, l.screen.suffix) }))
      .filter((x) => x.name)
      .sort((x, y) => score(y.name, q) - score(x.name, q))
      .slice(0, PER_QUILL)
      .map(({ r, name }) => ({
        key: `${l.screen.model}/${r.id}`,
        kind: "record",
        label: name,
        within: l.quill.name,
        icon: pixelIcon(l.screen.icon) || pixelIcon(l.quill.icon),
        href: `#/r/${encodeURIComponent(l.quill.id)}/${encodeURIComponent(l.screen.id)}/` +
          `${encodeURIComponent(l.screen.model)}/${encodeURIComponent(r.id)}`,
      }));
  });
  const settled = await Promise.allSettled(asked);
  const seen = new Set();
  return settled.flatMap((s) => (s.status === "fulfilled" ? s.value : []))
    .filter((hit) => !seen.has(hit.key) && seen.add(hit.key));
}

// -- the sheet ------------------------------------------------------------------------
function row(hit, i) {
  const where = hit.within ? `<span class="qs-within">${esc(hit.within)}</span>` : "";
  return `<a class="qs-hit${i === open.lit ? " lit" : ""}" href="${esc(hit.href)}" data-i="${i}" role="option"` +
    ` aria-selected="${i === open.lit}"><span class="qs-icon">${hit.icon || ""}</span>` +
    `<span class="qs-label">${esc(hit.label)}</span>${where}</a>`;
}

function draw() {
  const { hits, list } = open;
  const appHits = hits.filter((h) => h.kind === "app");
  const found = hits.filter((h) => h.kind === "record");
  let i = 0;
  const part = (title, part) =>
    part.length ? `<div class="qs-part">${title}</div>` + part.map((h) => row(h, i++)).join("") : "";
  const q = open.field.value.trim();
  const waiting = open.asking && q.length >= 2 ? `<div class="qs-note">Looking…</div>` : "";
  const nothing = !hits.length && !open.asking ? `<div class="qs-note">Nothing called “${esc(q)}”.</div>` : "";
  list.innerHTML = part("Apps", appHits) + part("In your apps", found) + waiting + nothing;
  const lit = list.querySelector(".qs-hit.lit");
  if (lit) lit.scrollIntoView({ block: "nearest" });
}

let timer = 0;
function typed() {
  const q = open.field.value.trim().toLowerCase();
  const asked = ++open.asked;
  open.hits = matchingApps(q);
  open.lit = 0;
  clearTimeout(timer);
  open.asking = q.length >= 2;
  draw();
  if (!open.asking) return;
  timer = setTimeout(async () => {
    const found = await records(q);
    if (!open || asked !== open.asked) return;
    open.hits = [...open.hits, ...found];
    open.asking = false;
    draw();
  }, WAIT_MS);
}

function go(i) {
  const hit = open && open.hits[i];
  if (!hit) return;
  closeSearch();
  location.hash = hit.href;
}

/** The search, in the middle of the screen. */
export function openSearch() {
  if (open) { open.field.focus(); open.field.select(); return; }
  if (!session.token) return;
  const backdrop = document.createElement("div");
  backdrop.className = "qs-backdrop";
  backdrop.innerHTML =
    `<div class="qs" role="dialog" aria-label="Search">` +
    `<label class="qs-field">${icons.search}<input type="search" placeholder="Search apps, files, notes…"` +
    ` autocomplete="off" spellcheck="false" aria-label="Search" aria-controls="qs-list"></label>` +
    `<div class="qs-list" id="qs-list" role="listbox"></div>` +
    `<div class="qs-foot"><span><kbd>↑</kbd><kbd>↓</kbd> to pick</span><span><kbd>Enter</kbd> to open</span>` +
    `<span><kbd>Esc</kbd> to close</span></div></div>`;
  document.body.append(backdrop);
  const field = backdrop.querySelector("input");
  const list = backdrop.querySelector(".qs-list");
  open = { backdrop, field, list, hits: [], lit: 0, asked: 0, asking: false };

  field.addEventListener("input", typed);
  field.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const n = open.hits.length;
      if (!n) return;
      open.lit = (open.lit + (event.key === "ArrowDown" ? 1 : -1) + n) % n;
      draw();
    } else if (event.key === "Enter") {
      event.preventDefault();
      go(open.lit);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      closeSearch();
    }
  });
  list.addEventListener("click", (event) => {
    const hit = event.target.closest(".qs-hit");
    if (!hit || event.metaKey || event.ctrlKey || event.shiftKey) return;
    event.preventDefault();
    go(Number(hit.dataset.i));
  });
  list.addEventListener("mousemove", (event) => {
    const hit = event.target.closest(".qs-hit");
    if (!hit || Number(hit.dataset.i) === open.lit) return;
    open.lit = Number(hit.dataset.i);
    list.querySelectorAll(".qs-hit").forEach((el) => {
      const on = el === hit;
      el.classList.toggle("lit", on);
      el.setAttribute("aria-selected", String(on));
    });
  });
  backdrop.addEventListener("mousedown", (event) => { if (event.target === backdrop) closeSearch(); });
  typed();
  field.focus();
}

export function closeSearch() {
  if (!open) return;
  clearTimeout(timer);
  open.backdrop.remove();
  open = null;
}

addEventListener("hashchange", closeSearch);

// -- the keys -------------------------------------------------------------------------
const FIELD = /^(INPUT|TEXTAREA|SELECT)$/;
const typing = (el) => !!el && (FIELD.test(el.tagName) || el.isContentEditable);

// In the capture phase, ahead of the screens' own keys and the browser's:
// Ctrl K would otherwise go to the address bar's search.
addEventListener("keydown", (event) => {
  if (event.defaultPrevented || !session.token) return;
  const k = event.key.toLowerCase();
  if (k === "k" && (isMac ? event.metaKey : event.ctrlKey) && !event.altKey && !event.shiftKey) {
    event.preventDefault();
    openSearch();
    return;
  }
  // `/` is whatever key makes it on this keyboard (Shift 7 on a Danish one).
  if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey && !typing(document.activeElement)) {
    event.preventDefault();
    openSearch();
  }
}, true);

// The bar at the foot of the rail (core.js draws it).
addEventListener("click", (event) => {
  if (!event.target.closest || !event.target.closest(".rail-search")) return;
  event.preventDefault();
  openSearch();
});
