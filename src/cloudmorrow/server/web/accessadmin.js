/* Access, for an administrator: how people reach this cloud.

   The fifth section of Administration. The home network is always there
   and only reported: the box announces itself as <name>.local whenever the
   config lets it. The mesh needs the box linked to a cloudmorrow.com
   account, once: before that the section is one amber button, then a code
   to enter at cloudmorrow.com/link (with the link and a QR code of it,
   for the phone in your hand), and after it the name, the box on its
   mesh, and the devices on it — labelled here, on the box, and nowhere
   else. The name itself is chosen, and changed, on the website.

   Every change goes to /api/access and the panel is drawn again from the
   answer, so what is on screen is what the server did, never what was
   hoped. While a code waits the panel looks again every few seconds, and
   stops the moment it is not on screen. */

import { api, esc, formatDate, seconds, store, toast } from "./core.js";
import { qrSvg } from "./qr.js";

// tailscale's own states, in words.
const MESH = {
  Running: ["On the mesh", "good"],
  Stopped: ["Stopped", "warn"],
  NeedsLogin: ["Not signed in to the mesh", "warn"],
  NeedsMachineAuth: ["Waiting to be approved", "warn"],
  Starting: ["Starting…", "warn"],
  NoState: ["Not running", "warn"],
};

const when = (stamp) => {
  const at = seconds(stamp);
  return at ? formatDate(at) : "";
};

export const until = (stamp) => {
  const at = seconds(stamp);
  return at ? new Date(at * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : "";
};

const fact = (label, value, tone = "") => `<div class="row access-fact">
  <span class="main">${esc(label)}</span>
  <span class="value${tone ? " " + tone : ""}">${esc(value)}</span></div>`;

// -- the panel --------------------------------------------------------------------
/** Access, into Administration's panel. */
export async function drawAccess(panel) {
  let status;
  try {
    status = await api("GET", "/api/access");
  } catch (err) {
    panel.innerHTML = `<p class="note">How this cloud is reached could not be read: ${esc(err.message)}</p>`;
    return;
  }
  panel.innerHTML = homeGroup(status) + (status.linked ? linked(status) : unlinked(status));
  wire(panel, status);
}

function homeGroup(status) {
  const lan = status.lan || {};
  const shown = lan.on && lan.announced;
  let note;
  if (lan.on && lan.error) note = lan.error;
  else if (!lan.on) note = "access_lan is off in the server's config: it does not announce itself.";
  else if (!shown) note = "It listens only on this machine, so there is nothing to announce.";
  else note = "Devices on the same network find it by this name, and go to it directly.";
  // The row is the name it answers to; the group label already says which way this is.
  return `<p class="group-label">Home network</p>
    <div class="group">
      <div class="row access-way"><span class="main"><span class="title access-host">${esc(shown ? lan.hostname : "Not announced")}</span>
        <span class="meta"><span class="preview">${esc(note)}</span></span></span>
        <span class="access-chip${shown ? " on" : ""}">${shown ? "On" : "Off"}</span></div>
      ${shown && lan.url && lan.url !== status.address ? fact("Opens at", lan.url) : ""}
      ${shown && lan.addresses && lan.addresses.length ? fact("Local address", lan.addresses.join(", ")) : ""}
    </div>`;
}

// Not linked: the one amber button, or the code it gave.
function unlinked(status) {
  const link = status.link;
  if (link) {
    const expires = until(link.expires_at);
    return `<p class="group-label">Linking</p>
      <div class="group access-linking">
        <div class="row access-link-steps"><span class="main">Open
          <a href="${esc(link.link)}" target="_blank" rel="noopener"><b>${esc(link.place)}</b></a>
          and enter this code. Sign in there, or make an account, and pick the name.</span></div>
        <div class="access-code" aria-live="polite">
          <p class="code" aria-label="Link code">${esc(link.code)}</p>
          <span class="access-qr">${qrSvg(link.link, "The link page, with the code filled in")}</span>
          <p class="expires">Or scan it with your phone. Good${expires ? ` until ${esc(expires)}` : " for fifteen minutes"};
            this page follows along.</p>
        </div>
        <div class="row access-buttons"><button class="access-button ghost" type="button" data-do="cancel">Stop waiting</button></div>
      </div>
      ${status.link_error ? `<p class="shelf-note warn">${esc(status.link_error)}</p>` : ""}`;
  }
  return `<p class="group-label">The mesh</p>
    <p class="note">Link this cloud to a cloudmorrow.com account, and the devices you
      invite reach it from anywhere, at a name of its own with a real certificate,
      over a private mesh only they are on. Nothing on the internet reaches it, and
      nothing about its people leaves it. Without it, the home network is all.</p>
    ${status.link_state === "expired" ? `<p class="shelf-note warn">The last code ran out before it was entered.</p>` : ""}
    <div class="group"><button class="row primary" type="button" data-do="link">Link to a cloudmorrow.com account</button></div>
    <p class="shelf-note">Through ${esc(status.control || "")}.</p>`;
}

function linked(status) {
  const mesh = status.mesh || {};
  const box = mesh.box || {};
  const [meshWords, meshTone] = !box.installed
    ? ["tailscale is not installed on this box", "bad"]
    : MESH[box.state] || [box.state || "Not answering", "warn"];
  const caddy = status.caddy || {};
  const said = mesh.on
    ? `Its devices reach it at https://${status.host}, from anywhere.`
    : "Linked, and joining its mesh.";
  return `<p class="group-label">The mesh</p>
    <div class="group">
      <div class="row access-way"><span class="main"><span class="title access-host">${esc(status.host)}</span>
        <span class="meta"><span class="preview">${esc(said)}</span></span></span>
        <span class="access-chip${mesh.on ? " on" : ""}">${mesh.on ? "On" : "Not yet"}</span></div>
      ${fact("This box", meshWords, meshTone)}
      ${mesh.address ? fact("Mesh address", mesh.address) : ""}
      ${mesh.login_server ? fact("Login server", mesh.login_server) : ""}
      ${status.setup_error ? fact("Last problem", status.setup_error, "bad") : ""}
      ${caddy.error ? fact("Certificate", caddy.error, "bad") : ""}
      ${mesh.on ? "" : `<div class="row access-buttons"><button class="access-button ghost" type="button" data-do="setup">Try again</button></div>`}
    </div>
    ${mesh.on ? `<p class="group-label">Devices on the mesh</p><div class="group access-devices"><p class="note">…</p></div>
      <div class="group"><a class="row primary" href="#/invite">Invite a device</a></div>` : ""}
    <p class="shelf-note">The name is chosen, and changed, on cloudmorrow.com, in My Clouds.
      Whose each device is stays on this box.</p>
    <div class="group"><button class="row bad" type="button" data-do="unlink">Unlink ${esc(status.host)}</button></div>`;
}

// -- what the buttons do ------------------------------------------------------------
function wire(panel, status) {
  const redraw = () => drawAccess(panel);
  // A call that changes things: its answer is the new status.
  const change = async (control, method, path, said) => {
    if (control) control.disabled = true;
    try {
      await api(method, path);
      if (said) toast(said);
    } catch (err) {
      toast(err.message, 4000);
    }
    await redraw();
  };
  const on = (what, fn) => {
    const button = panel.querySelector(`[data-do=${what}]`);
    if (button) button.addEventListener("click", () => fn(button));
  };

  on("link", (button) => {
    button.textContent = "Asking for a code…";
    change(button, "POST", "/api/access/link");
  });
  on("cancel", (button) => change(button, "DELETE", "/api/access/link"));
  on("setup", (button) => {
    button.textContent = "Trying…";
    change(button, "POST", "/api/access/setup", "On the mesh.");
  });
  on("unlink", (button) => {
    if (!confirm(`Unlink ${status.host}?\n\nThe name goes back, and every device on the mesh loses `
      + "its way in. The home network keeps working.")) return;
    change(button, "POST", "/api/access/unlink", "Unlinked. It is reached on the home network.");
  });

  // A code waiting: look again in a moment, while this panel is still the one on screen.
  if (status.link) {
    setTimeout(() => {
      if (panel.isConnected && panel.querySelector(".access-linking")) redraw();
    }, 3000);
  }

  const devices = panel.querySelector(".access-devices");
  if (devices) drawDevices(devices, true);
}

// -- devices on the mesh -------------------------------------------------------------
/** The devices on this cloud's mesh, with a way to remove each: everybody's
    for an administrator (Access), who can also say whose one is; the
    person's own on Invite a device. */
export async function drawDevices(group, everyone = false) {
  let found;
  try {
    found = (await api("GET", `/api/access/mesh/devices${everyone ? "?everyone=true" : ""}`)).devices;
  } catch (err) {
    group.innerHTML = `<p class="note">${esc(err.message)}</p>`;
    return;
  }
  if (!found.length) {
    group.innerHTML = `<div class="row"><span class="main"><span class="meta"><span class="preview">None yet.</span></span></span></div>`;
    return;
  }
  group.innerHTML = found.map((d) => {
    const seen = d.online ? "online" : (d.last_seen ? `last seen ${when(d.last_seen)}` : "offline");
    const title = d.label || "Nobody's yet";
    const bits = [d.address, seen].filter(Boolean).join(" · ");
    const say = everyone && !d.box
      ? `<button class="access-button ghost" type="button" data-label="${esc(d.id)}">${d.label ? "Rename" : "Say whose"}</button>` : "";
    const remove = d.box ? "" : `<button class="access-button ghost bad" type="button" data-id="${esc(d.id)}"
        data-name="${esc(d.label || d.address || d.id)}">Remove</button>`;
    return `<div class="row access-device">
      <span class="dot${d.online ? " on" : ""}" aria-hidden="true"></span>
      <span class="main"><span class="title${d.label ? "" : " unlabelled"}">${esc(title)}</span>
      <span class="meta"><span class="preview">${esc(bits)}</span></span></span>
      <span class="access-device-buttons">${say}${remove}</span></div>`;
  }).join("");
  for (const button of group.querySelectorAll("button[data-id]")) {
    button.addEventListener("click", async () => {
      if (!confirm(`Remove ${button.dataset.name}?\n\nIt can no longer reach this cloud until it is invited again.`)) return;
      button.disabled = true;
      try {
        await api("DELETE", "/api/access/mesh/devices/" + encodeURIComponent(button.dataset.id));
        toast(`${button.dataset.name} is removed`);
      } catch (err) { toast(err.message); }
      drawDevices(group, everyone);
    });
  }
  for (const button of group.querySelectorAll("button[data-label]")) {
    button.addEventListener("click", async () => {
      const device = found.find((d) => d.id === button.dataset.label) || {};
      const owner = prompt("Whose is it? (a username)", device.owner || "");
      if (owner === null) return;
      const name = prompt("What is it called?", device.device || "phone");
      if (name === null) return;
      try {
        await api("PUT", "/api/access/mesh/devices/" + encodeURIComponent(device.id), {
          owner: owner.trim(), device: name.trim(),
        });
      } catch (err) { toast(err.message); }
      drawDevices(group, everyone);
    });
  }
}

/** Open Administration on its Access side (Invite a device points here). */
export function toAccess() {
  store.set("admin.side", "access");
  location.hash = "#/admin";
}
