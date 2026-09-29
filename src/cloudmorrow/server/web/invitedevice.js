/* Me → Invite a device: a phone or a computer onto this cloud's mesh.

   For everybody, not only administrators: whoever is on the cloud may
   invite a device, and see and remove their own. An invite is a
   six-character code from the relay, good once, for ten minutes, and it
   says nothing about whose device it is for: the box keeps that.

   A computer runs the one-line installer from the cloud's name — it works
   off the mesh too, where the name shows the relay's landing page — which
   asks for the code, joins, and signs in. A phone uses the ordinary
   Tailscale app pointed at the cloud's login server — the QR code carries
   its address — and the page it opens asks for the code.

   Until the cloud is linked and on its mesh there is nothing to invite a
   device to, and the screen says so rather than offering a button that
   would only fail. */

import { qrSvg } from "./qr.js";
import {
  api, app, esc, icons, nav, previousHash, registerScreen, toast, wireShell,
} from "./core.js";
import { drawDevices, toAccess, until } from "./accessadmin.js";

/** The row on Me that leads here. */
export const inviteRow = () => `<div class="group"><a class="row invite-link" href="#/invite">
  <span class="main"><span class="title">Invite a device</span>
  <span class="meta"><span class="preview">A phone or a computer onto this cloud's mesh, to reach it from anywhere</span></span></span>
  ${icons.chevronRight}</a></div>`;

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied");
  } catch {
    // Plain http, or a browser that says no: the text is selectable anyway.
    toast("Select it and copy it by hand");
  }
}

async function renderInvite() {
  const [me, status] = await Promise.all([api("GET", "/api/auth/me"), api("GET", "/api/access")]);
  const from = previousHash();
  const back = from && from !== "#/invite" ? from : "#/me";
  const head = nav({ back, backLabel: back === "#/me" ? "Me" : "Back", title: "Invite a device" });

  if (!status.mesh || !status.mesh.on) {
    app.innerHTML = head + `
      <main class="invite">
        <h1 class="large">Invite a device</h1>
        <p class="empty mascot"><b>${status.linked ? "Not on its mesh yet" : "Not linked"}</b>
          ${status.linked
            ? "This cloud is linked, and still joining its mesh. Try again in a minute."
            : "This cloud is reached on the home network only, so there is no mesh to invite a device to."}</p>
        ${me.is_admin && !status.linked
          ? `<div class="group"><button class="row ghost-row to-access" type="button">Link it in Administration → Access</button></div>`
          : (status.linked ? "" : `<p class="note">An administrator links it in Administration → Access.</p>`)}
      </main>`;
    wireShell();
    const to = app.querySelector(".to-access");
    if (to) to.addEventListener("click", toAccess);
    return;
  }

  const login = status.mesh.login_server;
  const install = `curl -fsSL https://${status.host}/install.sh | sh`;
  app.innerHTML = head + `
    <main class="invite">
      <h1 class="large">Invite a device</h1>
      <p class="note">Devices on the mesh reach <b>${esc(status.host)}</b> from anywhere,
        over a private network only they are on. An invite lets one device in.</p>

      <div class="invite-code" hidden aria-live="polite"></div>
      <div class="group"><button class="row primary make-invite" type="button">Make an invite</button></div>

      <p class="group-label">A computer</p>
      <div class="group">
        <div class="row invite-computer"><span class="main">Run this on the computer. It installs
          Cloudmorrow, asks for the invite code, asks before it installs Tailscale,
          joins the mesh and signs you in.
          <code class="invite-command">${esc(install)}</code></span></div>
        <div class="row access-buttons">
          <button class="access-button ghost copy-install" type="button">Copy the command</button>
        </div>
      </div>

      <p class="group-label">A phone</p>
      <div class="group invite-steps">
        <div class="row"><span class="step">1</span><span class="main">Install the
          <b>Tailscale</b> app from the App Store or Google Play.</span></div>
        <div class="row invite-qr-row"><span class="step">2</span><span class="main">In its settings,
          choose <b>Use an alternate server</b> (on iPhone: tap the account, then
          <i>Log in to a different server</i>) and scan this, or type the address.
          <span class="invite-qr">${qrSvg(login, "The login server: " + login)}</span>
          <code class="invite-url">${esc(login)}</code></span></div>
        <div class="row"><span class="step">3</span><span class="main">Sign in. The page it
          opens asks for the invite code.</span></div>
      </div>

      <p class="group-label">Your devices</p>
      <div class="group access-devices"><p class="note">…</p></div>
    </main>`;
  wireShell();

  const make = app.querySelector(".make-invite");
  const shown = app.querySelector(".invite-code");
  make.addEventListener("click", async () => {
    make.disabled = true;
    try {
      const got = await api("POST", "/api/access/mesh/invite");
      const expires = until(got.expires_at);
      shown.innerHTML = `<p class="code" aria-label="Invite code">${esc(got.code)}</p>
        <p class="expires">For one device, once${expires ? `, until ${esc(expires)}` : ", for ten minutes"}.</p>`;
      shown.hidden = false;
      make.textContent = "Make another";
    } catch (err) {
      toast(err.message, 4000);
    }
    make.disabled = false;
  });
  app.querySelector(".copy-install").addEventListener("click", () => copy(install));

  drawDevices(app.querySelector(".access-devices"), false);
}

registerScreen("invite", renderInvite);
