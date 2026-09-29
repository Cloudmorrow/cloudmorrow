/* Access, for an administrator: the three ways people reach this cloud.

   The fourth section of Administration. Home network is always there and
   only reported: the box announces itself as <name>.local whenever the
   config lets it. Public and private both hang off one name at the control
   server — larsens.cloudmorrow.com — so before there is a name the whole
   section is the one question, "which name?", and after it the two ways
   are switches under it, each with what its machinery says: the tunnel to
   the relay for public, tailscale and the enrolled devices for private.

   Every change goes to /api/access and the panel is drawn again from the
   answer, so what is on screen is what the server did, never what was
   hoped. The one amber button is the next step for this cloud as it
   stands; everything else is a switch, a ghost, or red for giving the
   name back. */

import { api, esc, formatDate, seconds, store, toast } from "./core.js";

// The zone a name will be in, before there is one to ask: the control
// server's host without its first label (relay.cloudmorrow.com →
// cloudmorrow.com). A hint only; the answer to a claim is the truth.
export function zoneOf(status) {
  if (status.zone) return status.zone;
  try {
    const host = new URL(status.control).hostname;
    return host.split(".").length > 2 ? host.slice(host.indexOf(".") + 1) : host;
  } catch { return ""; }
}

// What each state of the tunnel means to somebody who never saw a socket.
const TUNNEL = {
  off: ["Off", ""],
  connecting: ["Connecting to the relay…", "warn"],
  connected: ["Connected", "good"],
  waiting: ["Not connected — trying again", "warn"],
  refused: ["Refused by the relay — trying again later", "bad"],
  // Refused for good (a wrong token, public access off at the relay): not
  // tried again until something here changes.
  stopped: ["Refused by the relay — stopped", "bad"],
};
// tailscale's own states, in words.
const MESH = {
  Running: ["On the mesh", "good"],
  Stopped: ["Stopped", "warn"],
  NeedsLogin: ["Not signed in to the mesh", "warn"],
  NeedsMachineAuth: ["Waiting to be approved", "warn"],
  Starting: ["Starting…", "warn"],
  NoState: ["Not running", "warn"],
};

export function bytes(n) {
  const units = ["bytes", "KB", "MB", "GB", "TB"];
  let value = Number(n) || 0;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) { value /= 1000; unit += 1; }
  return unit ? `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}` : `${value} bytes`;
}

const when = (stamp) => {
  const at = seconds(stamp);
  return at ? formatDate(at) : "";
};

const fact = (label, value, tone = "") => `<div class="row access-fact">
  <span class="main">${esc(label)}</span>
  <span class="value${tone ? " " + tone : ""}">${esc(value)}</span></div>`;

const switchRow = (way, title, note, on, disabled = false) => `<label class="row feature-row">
  <span class="main"><span class="title">${esc(title)}</span>
  <span class="meta"><span class="preview">${esc(note)}</span></span></span>
  <input type="checkbox" data-way="${way}"${on ? " checked" : ""}${disabled ? " disabled" : ""}
    aria-label="${esc(title)}"></label>`;

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
  panel.innerHTML = status.enrolled ? enrolled(status) : unnamed(status);
  wire(panel, status);
}

function homeGroup(status) {
  const lan = status.lan || {};
  let note;
  if (!lan.on && lan.error) note = lan.error;
  else if (!lan.on) note = "Either access_lan is off in the server's config, or the server listens only on this machine and has no name yet.";
  else note = "Devices on the same network find it by this name, and go to it directly.";
  // The row is the name it answers to; the group label already says which way this is.
  return `<p class="group-label">Home network</p>
    <div class="group">
      <div class="row access-way"><span class="main"><span class="title access-host">${esc(lan.on ? lan.hostname : "Not announced")}</span>
        <span class="meta"><span class="preview">${esc(note)}</span></span></span>
        <span class="access-chip${lan.on ? " on" : ""}">${lan.on ? "On" : "Off"}</span></div>
      ${lan.on && lan.url && lan.url !== status.address ? fact("Opens at", lan.url) : ""}
      ${lan.on && lan.addresses && lan.addresses.length ? fact("Local address", lan.addresses.join(", ")) : ""}
    </div>`;
}

// No name yet: the one question, and the ways it is for.
function unnamed(status) {
  const zone = zoneOf(status);
  return `
    <p class="note">Three ways to reach this cloud. The home network needs
      nothing. Public and private both need a name, like
      <b>${esc(status.suggested_name || "larsens")}.${esc(zone)}</b>, which comes
      with a real certificate: phones get notifications and the home screen.</p>
    ${homeGroup(status)}
    <p class="group-label">A name, for public and private</p>
    <form class="access-claim">
      <div class="group">
        <label class="row access-name"><span class="main">Name</span>
          <input name="name" value="${esc(status.suggested_name || "")}" autocapitalize="none"
            autocorrect="off" spellcheck="false" maxlength="40" required>
          <span class="zone">.${esc(zone)}</span></label>
      </div>
      <div class="group choices">
        <label class="row"><input type="checkbox" name="public" checked>
          <span class="main"><span class="title">Public</span>
          <span class="meta"><span class="preview">Anybody with the address reaches the
            sign-in page, from anywhere. Through the relay; it cannot read a thing.</span></span></span></label>
        <label class="row"><input type="checkbox" name="private">
          <span class="main"><span class="title">Private</span>
          <span class="meta"><span class="preview">Only devices you enroll reach it, from
            anywhere. Needs tailscale on this box.</span></span></span></label>
      </div>
      <div class="group"><button class="row primary" type="submit">Claim ${
        esc(status.suggested_name || "a name")}.${esc(zone)}</button></div>
    </form>
    <p class="shelf-note">Names are kept at ${esc(status.control || "")}.</p>`;
}

// The next step, as the one amber button: nothing is on yet, so turn the
// first way on; private is on, so enroll a device; public alone, so go
// and use it.
function nextStep(status) {
  if (!status.public.on && !status.private.on) {
    return `<button class="row primary" type="button" data-do="public-on">Turn public access on</button>`;
  }
  if (status.private.on) return `<a class="row primary" href="#/pair">Pair a device</a>`;
  return `<a class="row primary" href="https://${esc(status.host)}" target="_blank" rel="noopener">Open ${esc(status.host)}</a>`;
}

function enrolled(status) {
  const tunnel = status.public.tunnel || {};
  const [tunnelWords, tunnelTone] = TUNNEL[tunnel.state] || [tunnel.state || "Unknown", ""];
  const priv = status.private;
  const mesh = priv.mesh || {};
  const [meshWords, meshTone] = !mesh.installed
    ? ["tailscale is not installed on this box", "warn"]
    : MESH[mesh.state] || [mesh.state || "Not answering", "warn"];
  const caddy = status.caddy || {};

  const publicFacts = status.public.on ? [
    fact("Tunnel", tunnelWords, tunnelTone),
    tunnel.connected_since ? fact("Connected since", when(tunnel.connected_since)) : "",
    fact("Reconnects", String(tunnel.reconnects || 0)),
    fact("Through it", `${bytes(tunnel.bytes_in)} in · ${bytes(tunnel.bytes_out)} out`),
    tunnel.error ? fact("Last problem", tunnel.error, "bad") : "",
  ].join("") : "";
  const privateFacts = priv.on ? [
    fact("This box", meshWords, meshTone),
    priv.address ? fact("Mesh address", priv.address) : "",
    priv.login_server ? fact("Login server", priv.login_server) : "",
    priv.error ? fact("Last problem", priv.error, "bad") : "",
  ].join("") : (priv.error ? fact("Last problem", priv.error, "bad") : "");

  return `
    <p class="group-label">The name</p>
    <div class="group">
      <div class="row access-way"><span class="main"><span class="title access-host">${esc(status.host)}</span>
        <span class="meta"><span class="preview">${esc(status.address ? `The app is at ${status.address}` : "Held, and used by neither way yet")}</span></span></span></div>
    </div>
    ${caddy.error ? `<p class="shelf-note warn">${esc(caddy.error)}</p>` : ""}
    ${homeGroup(status)}
    <p class="group-label">Public</p>
    <div class="group">
      ${switchRow("public", "Anybody with the address", "Reaches the sign-in page from anywhere, through the relay, which cannot read a thing.", status.public.on)}
      ${publicFacts}
    </div>
    <p class="group-label">Private</p>
    <div class="group">
      ${switchRow("private", "Only enrolled devices", "Reach it from anywhere, over the cloud's own mesh.", priv.on)}
      ${privateFacts}
    </div>
    ${priv.on ? `<p class="group-label">Enrolled devices</p><div class="group access-devices"><p class="note">…</p></div>` : ""}
    <div class="group">${nextStep(status)}</div>
    <p class="group-label">Change the name</p>
    <form class="access-rename"><div class="group">
      <label class="row access-name"><span class="main">New name</span>
        <input name="name" value="${esc(status.name)}" autocapitalize="none" autocorrect="off"
          spellcheck="false" maxlength="40" required>
        <span class="zone">.${esc(zoneOf(status))}</span></label>
      <div class="row access-buttons"><button class="access-button ghost" type="submit">Rename</button></div>
    </div></form>
    <div class="group"><button class="row bad" type="button" data-do="release">Give ${esc(status.host)} back</button></div>`;
}

// -- what the buttons do ------------------------------------------------------------
function wire(panel, status) {
  const redraw = () => drawAccess(panel);
  // A call that changes the ways: its answer is the new status.
  const change = async (control, method, path, body, said) => {
    if (control) control.disabled = true;
    try {
      await api(method, path, body);
      if (said) toast(said);
    } catch (err) {
      toast(err.message, 4000);
    }
    await redraw();
  };

  const claim = panel.querySelector("form.access-claim");
  if (claim) {
    const button = claim.querySelector("button[type=submit]");
    const zone = zoneOf(status);
    claim.elements.name.addEventListener("input", () => {
      const name = claim.elements.name.value.trim().toLowerCase() || "a name";
      button.textContent = `Claim ${name}.${zone}`;
    });
    claim.addEventListener("submit", (event) => {
      event.preventDefault();
      const f = claim.elements;
      if (!f.public.checked && !f.private.checked) {
        toast("Choose public, private or both: a name nobody uses is not worth claiming.");
        return;
      }
      button.textContent = "Claiming…";
      change(button, "POST", "/api/access/name", {
        name: f.name.value.trim(), public: f.public.checked, private: f.private.checked,
      }, "The name is yours.");
    });
  }

  for (const box of panel.querySelectorAll("input[data-way]")) {
    box.addEventListener("change", () => {
      const way = box.dataset.way;
      const on = box.checked;
      if (!on && !confirm(way === "public"
        ? "Turn public access off?\n\nThe address stops answering for everybody outside the home network."
        : "Turn private access off?\n\nThis box leaves the mesh; enrolled devices stay enrolled but cannot reach it.")) {
        box.checked = true;
        return;
      }
      change(box, "PUT", `/api/access/${way}`, { on },
        `${way === "public" ? "Public" : "Private"} access is ${on ? "on" : "off"}.`);
    });
  }

  const publicOn = panel.querySelector("[data-do=public-on]");
  if (publicOn) publicOn.addEventListener("click", () =>
    change(publicOn, "PUT", "/api/access/public", { on: true }, "Public access is on."));

  const rename = panel.querySelector("form.access-rename");
  if (rename) rename.addEventListener("submit", (event) => {
    event.preventDefault();
    const name = rename.elements.name.value.trim();
    if (!name || name === status.name) return;
    change(rename.querySelector("button"), "PATCH", "/api/access/name", { name }, "Renamed.");
  });

  const release = panel.querySelector("[data-do=release]");
  if (release) release.addEventListener("click", () => {
    if (!confirm(`Give ${status.host} back?\n\nPublic and private access end, and every `
      + "enrolled device is forgotten. The home network keeps working.")) return;
    change(release, "DELETE", "/api/access/name", undefined, "The name is given back.");
  });

  const devices = panel.querySelector(".access-devices");
  if (devices) drawDevices(devices, true);
}

// -- enrolled devices ----------------------------------------------------------------
/** The devices on this cloud's mesh, with a way to remove each: everybody's
    for an administrator (Access), the person's own on Pair a device. */
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
    const bits = [everyone && d.owner ? d.owner : "", d.address, seen].filter(Boolean).join(" · ");
    return `<div class="row access-device">
      <span class="dot${d.online ? " on" : ""}" aria-hidden="true"></span>
      <span class="main"><span class="title">${esc(d.name || d.for || d.id)}</span>
      <span class="meta"><span class="preview">${esc(bits)}</span></span></span>
      <button class="access-button ghost bad" type="button" data-id="${esc(d.id)}"
        data-name="${esc(d.name || d.id)}">Remove</button></div>`;
  }).join("");
  for (const button of group.querySelectorAll("button[data-id]")) {
    button.addEventListener("click", async () => {
      if (!confirm(`Remove ${button.dataset.name}?\n\nIt can no longer reach this cloud until it is enrolled again.`)) return;
      button.disabled = true;
      try {
        await api("DELETE", "/api/access/mesh/devices/" + encodeURIComponent(button.dataset.id));
        toast(`${button.dataset.name} is removed`);
      } catch (err) { toast(err.message); }
      drawDevices(group, everyone);
    });
  }
}

/** Open Administration on its Access side (Pair a device points here). */
export function toAccess() {
  store.set("admin.side", "access");
  location.hash = "#/admin";
}
