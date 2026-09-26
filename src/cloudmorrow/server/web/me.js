/* Me: who you are signed in as, and the way out. */

import {
  VERSION, api, app, esc, homeHash, nav, previousHash, registerScreen, seconds, session,
  signOut, store, wireShell,
} from "./core.js";
import { featuresCard, loadFeatures, wireFeaturesCard } from "./features.js";
import { installCard } from "./install.js";
import { pushCard, wirePushCard } from "./push.js";
import { adminRow, isAdmin } from "./admin.js";
import { computerCard, wireComputerCard } from "./desktopbridge.js";


async function renderMe() {
  const [me] = await Promise.all([api("GET", "/api/auth/me"), loadFeatures()]);
  session.user = me.username;
  store.set("user", session.user);
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
  app.innerHTML = nav({ back, backLabel: "Back", title: "Me" }) + `
    <main>
      <h1 class="large">Me</h1>
      <div class="who">
        <span class="avatar" aria-hidden="true">${esc(name.trim().charAt(0).toUpperCase() || "?")}</span>
        <span class="text"><b>${esc(name)}</b>${esc(me.username)}</span>
      </div>
      <div class="install-slot">${installCard()}</div>
      ${pushCard()}
      ${featuresCard()}
      <div class="group">${facts.map(([label, value]) =>
        `<div class="row"><span class="main">${esc(label)}</span><span class="value">${esc(value)}</span></div>`).join("")}</div>
      ${computerCard()}
      ${isAdmin(me) ? adminRow() : ""}
      <div class="group"><button class="row signout">Sign out</button></div>
    </main>`;
  wireShell();
  wirePushCard(app);
  wireFeaturesCard(app);
  wireComputerCard(app);
  app.querySelector(".signout").addEventListener("click", () => signOut("Signed out."));
}

registerScreen("me", renderMe);
