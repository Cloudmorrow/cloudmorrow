/* Profile photos: the round mark beside a person, with their face in it.

   Every screen draws a person's mark the way it always did, an initial in a
   circle, and adds `data-photo="<username>"` to it (`avatar()` here does
   both). This module watches the page for those marks and lays the person's
   photo over the initial when they have one. A screen never waits for a
   picture, and somebody without one keeps their initial.

   The server keeps every photo as a 256-pixel square of a few kilobytes
   (photos.py), and its address carries the photo's stamp, so the browser
   keeps each one for good and a new photo is a new address. Which people
   have one comes in a single small list, asked for once per session. */

import { api, apiRaw, app, esc, onSignIn, onSignOut, session } from "./core.js";

let stamps = null;           // username -> stamp, once asked
let asking = null;           // the request for them, while it is out
const pictures = new Map();  // "username@stamp" -> a promise of an object URL

/** A person's round mark: their initial now, their photo when it comes. */
export function avatar(name, username, className = "avatar") {
  const initial = String(name || username || "").trim().charAt(0).toUpperCase() || "?";
  return `<span class="${esc(className)}" aria-hidden="true"${
    username ? ` data-photo="${esc(username)}"` : ""}>${esc(initial)}</span>`;
}

function whoHasOne() {
  if (stamps) return Promise.resolve(stamps);
  if (!asking) {
    asking = api("GET", "/api/people/photos")
      .then((found) => { stamps = found || {}; return stamps; })
      .catch(() => ({}))
      .finally(() => { asking = null; });
  }
  return asking;
}

function pictureOf(username, stamp) {
  const key = `${username}@${stamp}`;
  if (!pictures.has(key)) {
    const path = `/api/people/${encodeURIComponent(username)}/photo?v=${encodeURIComponent(stamp)}`;
    pictures.set(key, apiRaw("GET", path, { fail: "no photo" })
      .then((res) => res.blob())
      .then((blob) => URL.createObjectURL(blob))
      .catch(() => { pictures.delete(key); return ""; }));
  }
  return pictures.get(key);
}

/** Lay the photos over the marks under *root* that do not have one yet. */
export async function fillPhotos(root = app) {
  if (!session.token) return;
  const marks = [...root.querySelectorAll("[data-photo]")].filter((el) => el.dataset.filled !== el.dataset.photo);
  if (!marks.length) return;
  const known = await whoHasOne();
  for (const el of marks) {
    const who = el.dataset.photo;
    el.dataset.filled = who;
    const stamp = known[who];
    if (!stamp) { el.classList.remove("has-photo"); el.querySelector("img.photo")?.remove(); continue; }
    pictureOf(who, stamp).then((url) => {
      if (!url || el.dataset.photo !== who) return;
      let img = el.querySelector("img.photo");
      if (!img) {
        img = document.createElement("img");
        img.className = "photo";
        img.alt = "";
        img.decoding = "async";
        el.appendChild(img);
      }
      img.src = url;
      el.classList.add("has-photo");
    });
  }
}

/** Your own photo changed: *stamp* is the new one, or '' for none. */
export function photoChanged(username, stamp) {
  if (stamps) {
    if (stamp) stamps[username] = stamp;
    else delete stamps[username];
  }
  for (const el of document.querySelectorAll(`[data-photo="${CSS.escape(username)}"]`)) delete el.dataset.filled;
  fillPhotos(document);
}

// A screen is drawn by replacing what is in the app, so watching it for new
// marks is the one place this needs hooking in. Batched to a frame, so a
// long list being drawn is looked at once.
let queued = false;
new MutationObserver(() => {
  if (queued) return;
  queued = true;
  requestAnimationFrame(() => { queued = false; fillPhotos(document); });
}).observe(app, { childList: true, subtree: true });

function forget() {
  stamps = null;
  for (const url of pictures.values()) url.then((u) => u && URL.revokeObjectURL(u));
  pictures.clear();
}
onSignOut(forget);
onSignIn(() => { stamps = null; });
// Somebody else's new photo is seen on the next visit to the page, or
// within ten minutes while it stays open.
setInterval(() => {
  if (!session.token || document.hidden) return;
  stamps = null;
  for (const el of document.querySelectorAll("[data-photo]")) delete el.dataset.filled;
  fillPhotos(document);
}, 10 * 60 * 1000);
