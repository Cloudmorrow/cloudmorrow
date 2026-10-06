/* Me → Add a device: this cloud on a computer, a phone, or an assistant.

   For everybody, not only administrators. Nothing on it is a code or a
   key: every device signs in with the person's own name and password, at
   the address this page was opened at. */

import { qrSvg } from "./qr.js";
import {
  app, esc, icons, nav, previousHash, registerScreen, toast, wireShell,
} from "./core.js";

/** The row on Me that leads here. */
export const addDeviceRow = () => `<div class="group"><a class="row add-device-link" href="#/add-device">
  <span class="main"><span class="title">Add a device</span>
  <span class="meta"><span class="preview">This cloud on a computer, a phone, or an assistant</span></span></span>
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

function renderAddDevice() {
  const from = previousHash();
  const back = from && from !== "#/add-device" ? from : "#/me";
  const head = nav({ back, backLabel: back === "#/me" ? "Me" : "Back", title: "Add a device" });

  const base = window.location.origin;
  const install = `curl -fsSL ${base}/install.sh | sh`;

  app.innerHTML = head + `
    <main class="add-device">
      <h1 class="large">Add a device</h1>
      <p class="note">Everything signs in to <b>${esc(base)}</b> with your own name and password.</p>

      <p class="group-label">A computer</p>
      <div class="group">
        <div class="row add-computer"><span class="main">Run this in a terminal on the computer.
          It installs <code>cm</code>, the terminal app, and on a Linux desktop the Cloudmorrow app,
          and signs you in.
          <code class="add-command">${esc(install)}</code></span></div>
        <div class="row add-buttons">
          <button class="add-button copy-install" type="button">Copy the command</button>
        </div>
      </div>

      <p class="group-label">A phone</p>
      <div class="group add-steps">
        <div class="row add-qr-row"><span class="step">1</span><span class="main">Open this in the
          phone's browser: scan it, or type the address.
          <span class="add-qr">${qrSvg(base + "/app", "This cloud's address: " + base)}</span>
          <code class="add-url">${esc(base)}/app</code></span></div>
        <div class="row"><span class="step">2</span><span class="main">Sign in, then add it to the
          home screen (Share → <i>Add to Home Screen</i> on iPhone, the ⋮ menu on Android). It works
          like an app, with notifications.</span></div>
      </div>

      <p class="group-label">An assistant</p>
      <div class="group">
        <div class="row add-computer"><span class="main">Claude, or any assistant that speaks MCP,
          works with this cloud as you once you say yes. Its address:
          <code class="add-url">${esc(base)}/mcp</code></span></div>
      </div>
    </main>`;
  wireShell();

  app.querySelector(".copy-install").addEventListener("click", () => copy(install));
}

registerScreen("add-device", renderAddDevice);
