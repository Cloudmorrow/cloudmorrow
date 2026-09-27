/* Me → Pair a device: a phone or a computer onto this cloud's private mesh.

   For everybody, not only administrators: whoever signs in may enroll their
   own devices, and see and remove them. The mesh is Tailscale's technology
   with the cloud's own coordination server, so a phone uses the ordinary
   Tailscale app pointed at that server — the QR code carries its address —
   and its sign-in page asks for a six-character code, which is what this
   screen hands out. A code is good once, for ten minutes, and is labelled
   with who asked and for which device, so the device is theirs in the list.

   A computer is simpler still: the client installer does it with
   `--private`, asking this cloud for a key after signing in. The key is
   here as well, for a machine that already has tailscale.

   While private access is off there is nothing to pair with, and the
   screen says so rather than offering buttons that would only fail. */

import qrcode from "./qrcode.js";
import {
  api, app, esc, icons, nav, previousHash, registerScreen, seconds, toast, wireShell,
} from "./core.js";
import { drawDevices, toAccess } from "./accessadmin.js";

/** The row on Me that leads here. */
export const pairRow = () => `<div class="group"><a class="row pair-link" href="#/pair">
  <span class="main"><span class="title">Pair a device</span>
  <span class="meta"><span class="preview">Your phone or computer, onto this cloud's private network</span></span></span>
  ${icons.chevronRight}</a></div>`;

/** A QR code as an SVG, drawn from the matrix: crisp at any size, no image file.
    Dark modules on white with the quiet zone the standard asks for, whatever
    the theme, because a camera reads contrast, not a palette. */
export function qrSvg(text, label = "") {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  const n = qr.getModuleCount();
  const quiet = 4;
  let path = "";
  for (let r = 0; r < n; r += 1) {
    for (let c = 0; c < n; c += 1) {
      if (qr.isDark(r, c)) path += `M${c + quiet} ${r + quiet}h1v1h-1z`;
    }
  }
  const size = n + quiet * 2;
  return `<svg class="qr" viewBox="0 0 ${size} ${size}" role="img" aria-label="${esc(label || text)}"
    shape-rendering="crispEdges" xmlns="http://www.w3.org/2000/svg">
    <rect width="${size}" height="${size}" fill="#fff"/><path d="${path}" fill="#000"/></svg>`;
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied");
  } catch {
    // Plain http, or a browser that says no: the text is selectable anyway.
    toast("Select it and copy it by hand");
  }
}

const until = (stamp) => {
  const at = seconds(stamp);
  return at ? new Date(at * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : "";
};

async function renderPair() {
  const [me, status] = await Promise.all([api("GET", "/api/auth/me"), api("GET", "/api/access")]);
  const from = previousHash();
  const back = from && from !== "#/pair" ? from : "#/me";
  const head = nav({ back, backLabel: back === "#/me" ? "Me" : "Back", title: "Pair a device" });

  if (!status.private || !status.private.on) {
    app.innerHTML = head + `
      <main class="pair">
        <h1 class="large">Pair a device</h1>
        <p class="empty mascot"><b>Private access is off</b>
          This cloud is not on a private network, so there is nothing to pair a
          device with.${status.public && status.public.on
            ? ` It is reached at ${esc(status.host)} from anywhere.` : ""}</p>
        ${me.is_admin
          ? `<div class="group"><button class="row ghost-row to-access" type="button">Turn it on in Administration → Access</button></div>`
          : `<p class="note">An administrator turns it on in Administration → Access.</p>`}
      </main>`;
    wireShell();
    const to = app.querySelector(".to-access");
    if (to) to.addEventListener("click", toAccess);
    return;
  }

  const login = status.private.login_server;
  // The cloud's real address, not wherever this page was opened from (a
  // local address, say): the computer being enrolled may be anywhere.
  const install = `curl -fsSL ${status.address || location.origin}/install.sh | sh -s -- --private`;
  app.innerHTML = head + `
    <main class="pair">
      <h1 class="large">Pair a device</h1>
      <p class="note">Enrolled devices reach <b>${esc(status.host)}</b> from anywhere,
        over a private network only they are on.</p>

      <p class="group-label">A phone</p>
      <div class="group pair-steps">
        <div class="row"><span class="step">1</span><span class="main">Install the
          <b>Tailscale</b> app from the App Store or Google Play.</span></div>
        <div class="row pair-qr-row"><span class="step">2</span><span class="main">In its settings,
          choose <b>Use an alternate server</b> (on iPhone: tap the account, then
          <i>Log in to a different server</i>) and scan this, or type the address.
          <span class="pair-qr">${qrSvg(login, "The login server: " + login)}</span>
          <code class="pair-url">${esc(login)}</code></span></div>
        <div class="row"><span class="step">3</span><span class="main">Sign in. The page it
          opens asks for a pairing code: get one here, and type it in.</span></div>
      </div>
      <form class="pair-code-form">
        <div class="group">
          <label class="row pair-device"><span class="main">This device is</span>
            <input name="device" value="phone" maxlength="60" autocomplete="off"></label>
        </div>
        <div class="pair-code" hidden aria-live="polite"></div>
        <div class="group"><button class="row primary" type="submit">Get a pairing code</button></div>
      </form>

      <p class="group-label">A computer</p>
      <div class="group">
        <div class="row pair-computer"><span class="main">Run this on the computer. It installs
          Cloudmorrow, signs you in, and asks before it installs tailscale and joins.
          <code class="pair-command">${esc(install)}</code></span></div>
        <div class="row access-buttons">
          <button class="access-button ghost copy-install" type="button">Copy the command</button>
          <button class="access-button ghost get-key" type="button">It has tailscale: get a key</button>
        </div>
        <div class="pair-key" hidden></div>
      </div>

      <p class="group-label">Your devices</p>
      <div class="group access-devices"><p class="note">…</p></div>
    </main>`;
  wireShell();

  const form = app.querySelector(".pair-code-form");
  const shown = form.querySelector(".pair-code");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      const got = await api("POST", "/api/access/mesh/pair", { device: form.elements.device.value.trim() });
      const expires = until(got.expires_at);
      shown.innerHTML = `<p class="code" aria-label="Pairing code">${esc(got.code)}</p>
        <p class="expires">Good once${expires ? `, until ${esc(expires)}` : ", for ten minutes"}.</p>`;
      shown.hidden = false;
      button.textContent = "Get another code";
    } catch (err) {
      toast(err.message, 4000);
    }
    button.disabled = false;
  });

  app.querySelector(".copy-install").addEventListener("click", () => copy(install));
  app.querySelector(".get-key").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const got = await api("POST", "/api/access/mesh/key", { device: "a computer" });
      const command = `sudo tailscale up --login-server ${got.login_server} --authkey ${got.key}`;
      const box = app.querySelector(".pair-key");
      const expires = until(got.expires_at);
      box.innerHTML = `<div class="row pair-computer"><span class="main">A key for one computer,
        good once${expires ? ` until ${esc(expires)}` : ""}. On it, run:
        <code class="pair-command">${esc(command)}</code></span></div>
        <div class="row access-buttons"><button class="access-button ghost copy-key" type="button">Copy</button></div>`;
      box.hidden = false;
      box.querySelector(".copy-key").addEventListener("click", () => copy(command));
    } catch (err) {
      toast(err.message, 4000);
    }
    button.disabled = false;
  });

  drawDevices(app.querySelector(".access-devices"), false);
}

registerScreen("pair", renderPair);
