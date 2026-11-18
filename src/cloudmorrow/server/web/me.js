/* Me: who you are signed in as, and the way out. */

import {
  VERSION, api, apiRaw, app, esc, homeHash, mount, nav, previousHash, registerScreen, seconds, session,
  setAdmin, signOut, store, toast, wireShell,
} from "./core.js";
import { featuresCard, loadFeatures, wireFeaturesCard } from "./features.js";
import { installCard } from "./install.js";
import { pushCard, wirePushCard } from "./push.js";
import { adminRow, isAdmin } from "./admin.js";
import { computerCard, wireComputerCard } from "./desktopbridge.js";
import { addDeviceRow } from "./adddevice.js";
import { myQuillsRow } from "./myquills.js";
import { approvalsRow } from "./approvals.js";
import { flowsRow } from "./flows.js";
import { ask } from "./dialog.js";
import { photoChanged } from "./photos.js";

const CAMERA = '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"><path d="M1 4h2.5L4.5 2.5h3L8.5 4H11v5.5H1z"/><circle cx="6" cy="6.6" r="1.7"/></svg>';
// What the browser sends up: the photo shrunk on the device first, so a
// phone's 5 MB picture is a few hundred kilobytes on the way. The server
// cuts it down to its own small square either way (photos.py).
const SEND_EDGE = 1024;

/** *file* shrunk to SEND_EDGE on its long side, as a JPEG; the file itself
    when this browser cannot draw it (a HEIC on most of them), for the server
    to try. Turned the way the camera held it, as the browser shows it. */
async function shrunk(file) {
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const scale = Math.min(1, SEND_EDGE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close?.();
    const blob = await new Promise((done) => canvas.toBlob(done, "image/jpeg", 0.9));
    return blob || file;
  } catch {
    return file;
  }
}

async function upload(me, file, slot) {
  slot.classList.add("busy");
  try {
    const body = await shrunk(file);
    const res = await apiRaw("PUT", "/api/auth/photo", {
      body, type: body.type || "application/octet-stream",
      fail: (code) => (code === 413 ? "That picture is too big." : "That picture could not be read. Try a JPEG or a PNG."),
    });
    const { photo } = await res.json();
    me.photo = photo;
    photoChanged(me.username, photo);
    toast("Photo saved.");
    renderMe();
  } catch (error) {
    toast(error.message || "The photo was not saved.", 4000);
  } finally {
    slot.classList.remove("busy");
  }
}


async function renderMe() {
  const [me, , waiting] = await Promise.all([
    api("GET", "/api/auth/me"), loadFeatures(), api("GET", "/api/approvals/count").catch(() => ({ waiting: 0 })),
  ]);
  session.user = me.username;
  store.set("user", session.user);
  setAdmin(me.is_admin);
  const name = me.display_name || me.username;
  const since = seconds(me.created_at);
  const facts = [
    ["Username", me.username],
    ["Role", me.is_admin ? "Admin" : "Member"],
    since && ["Member since", new Date(since * 1000).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })],
    ["Cloudmorrow", VERSION],
  ].filter(Boolean);
  // Opened from the corner of whatever screen you were on, so the way
  // out is back to it; on a fresh load there is nothing behind, and the
  // front page stands in.
  const from = previousHash();
  const back = from && from !== "#/me" ? from : homeHash();
  mount(nav({ back, backLabel: "Back", title: "Me" }) + `
    <main>
      <h1 class="large">Me</h1>
      <div class="who">
        <span class="photo-edit">
          <button type="button" class="avatar" data-photo="${esc(me.username)}"
            aria-label="${me.photo ? "Change your photo" : "Add a photo of yourself"}">${esc(name.trim().charAt(0).toUpperCase() || "?")}</button>
          <span class="badge" aria-hidden="true">${CAMERA}</span>
          <input type="file" accept="image/*" hidden>
        </span>
        <span class="text"><b>${esc(name)}</b>${esc(me.username)}${
          me.photo ? `<button type="button" class="remove-photo">Remove photo</button>` : ""}</span>
      </div>
      <div class="install-slot">${installCard()}</div>
      ${pushCard()}
      ${featuresCard()}
      <div class="group">${facts.map(([label, value]) =>
        `<div class="row"><span class="main">${esc(label)}</span><span class="value">${esc(value)}</span></div>`).join("")}</div>
      ${approvalsRow(waiting.waiting)}
      ${flowsRow()}
      ${computerCard()}
      ${addDeviceRow()}
      ${myQuillsRow()}
      ${isAdmin(me) ? adminRow() : ""}
      <div class="group"><button class="row signout">Sign out</button></div>
    </main>`);
  wireShell();
  wirePushCard(app);
  wireFeaturesCard(app);
  wireComputerCard(app);
  const slot = app.querySelector(".photo-edit");
  const picker = slot.querySelector("input[type=file]");
  slot.querySelector("button.avatar").addEventListener("click", () => picker.click());
  picker.addEventListener("change", () => { if (picker.files[0]) upload(me, picker.files[0], slot); });
  app.querySelector(".remove-photo")?.addEventListener("click", async () => {
    if (!(await ask("Remove your photo?\n\nYour initial is shown instead."))) return;
    try {
      await api("DELETE", "/api/auth/photo");
      photoChanged(me.username, "");
      renderMe();
    } catch (error) {
      toast(error.message || "The photo was not removed.", 4000);
    }
  });
  app.querySelector(".signout").addEventListener("click", () => signOut("Signed out."));
}

registerScreen("me", renderMe);
