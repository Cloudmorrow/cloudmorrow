/* Local backups: folders on your computers, copied into My Files by their
   agents and kept up to date.

   The page lists your machines and the folders backed up from each —
   where each lands under My Files, how often, and how the last pass went
   — with Run now and Remove on each, and Add a folder. Adding one needs a
   machine that can do the copying: this computer, in the desktop app with
   its agent running (the folder is picked in the system's own dialog), or
   any machine of yours whose agent is online (the folder is typed). With
   neither, the page says what is needed and the button is off.

   It reaches the Files list through the grid's hook — Local backups… in
   the “…” beside the title — and knows the core's `/api/syncs` and
   `/api/agents`, and the desktop bridge, and nothing of the Quill.

     #/localbackups    the page */

import {
  api, app, esc, formatDate, go, mount, nav, previousHash, registerScreen, seconds, toast, wireShell,
} from "./core.js";
import { ask, askText } from "./dialog.js";
import { choose } from "./actions.js";
import { call, desktop } from "./desktopbridge.js";
import { registerGridHook } from "./kit_grid.js";

const PAGE = "#/localbackups";
const EVERY = [[15, "Every 15 minutes"], [60, "Every hour"], [360, "Every 6 hours"], [1440, "Every day"]];
const everySaid = (minutes) => {
  const known = EVERY.find(([m]) => m === minutes);
  if (known) return known[1].toLowerCase();
  return minutes % 60 ? `every ${minutes} minutes` : `every ${minutes / 60} hours`;
};

registerGridHook({
  async groups({ model }) {
    if (model.id !== "share") return null;
    return { menu: () => [{ label: "Local backups…", run: () => go(PAGE) }] };
  },
});

/** One of a few, in the sheet: resolves the value picked, or never, like Cancel. */
const pickOne = (title, options) =>
  new Promise((resolve) => choose(title, options.map(([value, label]) => ({ label, run: () => resolve(value) }))));

async function renderLocalBackups() {
  const [list, agents, here] = await Promise.all([
    api("GET", "/api/syncs"),
    api("GET", "/api/agents"),
    desktop() ? call("agent_status") : Promise.resolve(null),
  ]);
  const online = agents.filter((a) => a.online);
  // This computer, in the desktop app: its agent, as the server knows it.
  const thisOne = here && !here.error ? here : null;
  const thisAgent = thisOne ? agents.find((a) => a.name === thisOne.name) || null : null;
  const can = online.length > 0 || Boolean(thisOne && thisOne.running && thisAgent);
  const why = can ? "" : thisOne
    ? (thisOne.enrolled
      ? "This computer's agent is not running, so nothing here can do the copying. Run cloudmorrow login in a terminal, which starts it."
      : "This computer has no agent yet. Run cloudmorrow login in a terminal once: it enrols this computer and starts its agent.")
    : "Setting one up needs the desktop app on a computer, or the command line (cm) installed there with its agent running — cloudmorrow login starts it. No machine of yours is online now.";
  const machineRow = (a) => `<div class="row"><span class="main"><span class="title">${esc(a.name)}</span>` +
    `<span class="meta"><span class="preview">${esc(a.hostname && a.hostname !== a.name ? a.hostname : (a.platform || ""))}</span></span></span>` +
    `<span class="value ${a.online ? "good" : ""}">${a.online ? "Online" : (a.last_seen ? "Seen " + esc(formatDate(seconds(a.last_seen))) : "Never seen")}</span></div>`;
  const syncRow = (s) => {
    const agent = s.agent || {};
    const last = !s.last_run ? "Not run yet"
      : `${s.last_ok ? "Backed up" : "Failed"} ${formatDate(seconds(s.last_run))}${s.last_said ? " — " + s.last_said : ""}`;
    return `<div class="row sync-row${s.last_ok === false ? " bad" : ""}" data-id="${s.id}">
      <span class="main"><span class="title">${esc(s.path)}</span>
        <span class="meta"><span class="preview">To My Files/${esc(s.into)} · ${esc(everySaid(s.every_minutes))} · ${esc(agent.name || "?")}${agent.online ? "" : " (offline)"}</span></span>
        <span class="meta"><span class="preview last">${esc(last)}</span></span></span>
      <span class="sync-actions">
        <button type="button" class="desk-button ghost" data-run="${s.id}"${s.run_now ? " disabled" : ""}>${s.run_now ? "Waiting…" : "Run now"}</button>
        <button type="button" class="desk-button ghost" data-remove="${s.id}">Remove</button>
      </span></div>`;
  };
  mount(nav({ back: previousHash() || "#/", backLabel: "Files", title: "Local backups" }) + `
    <main class="local-backups">
      <h1 class="large">Local backups</h1>
      <p class="hint">A folder on one of your computers, copied into My Files by that computer's agent and kept up
        to date — every hour unless you say otherwise. What goes from the folder goes to the Trash here.</p>
      <div class="group-label">Your machines</div>
      ${agents.length ? `<div class="group">${agents.map(machineRow).join("")}</div>`
        : `<p class="hint">None yet. A computer where you run cloudmorrow login, or the desktop app, enrols itself.</p>`}
      <div class="group-label">Folders backed up</div>
      ${list.length ? `<div class="group">${list.map(syncRow).join("")}</div>`
        : `<p class="hint">No folder yet.</p>`}
      <div class="group"><button type="button" class="row primary add-sync"${can ? "" : " disabled"}>Add a folder</button></div>
      ${why ? `<p class="note warn">${esc(why)}</p>` : ""}
    </main>`);
  wireShell();

  app.querySelector(".add-sync").addEventListener("click", () => addSync(online, thisOne, thisAgent));
  for (const button of app.querySelectorAll("[data-run]")) {
    button.addEventListener("click", async () => {
      try {
        await api("POST", `/api/syncs/${button.dataset.run}/run`);
        toast("On the machine's next pass");
        renderLocalBackups();
      } catch (err) { toast(err.message); }
    });
  }
  for (const button of app.querySelectorAll("[data-remove]")) {
    button.addEventListener("click", async () => {
      const row = button.closest(".sync-row");
      const path = row.querySelector(".title").textContent;
      if (!await ask(`Stop backing up “${path}”?\n\nWhat was copied stays in My Files.`, { yes: "Stop", tone: "danger" })) return;
      try {
        await api("DELETE", `/api/syncs/${button.dataset.remove}`);
        renderLocalBackups();
      } catch (err) { toast(err.message); }
    });
  }
}

/** A folder added: on this computer, picked; on another machine, typed. */
async function addSync(online, thisOne, thisAgent) {
  const hereCan = Boolean(thisOne && thisOne.running && thisAgent);
  const choices = [
    ...(hereCan ? [[thisAgent, "This computer"]] : []),
    ...online.filter((a) => !thisAgent || a.id !== thisAgent.id).map((a) => [a, a.name]),
  ];
  if (!choices.length) return;
  const agent = choices.length === 1 ? choices[0][0] : await pickOne("Which machine?", choices);
  let path = "";
  if (hereCan && agent.id === thisAgent.id) {
    const picked = await call("pick_folder");
    if (picked.error) {
      if (picked.error !== "Nothing picked") toast(picked.error, 6000);
      return;
    }
    path = picked.path;
  } else {
    path = (await askText(`Folder on ${agent.name}`, "", { placeholder: "/home/you/Documents" }) || "").trim();
    if (!path) return;
  }
  const every = await pickOne("How often?", EVERY);
  try {
    await api("POST", "/api/syncs", { agent_id: agent.id, path, every_minutes: every });
    toast(`Backing up ${path}`);
    renderLocalBackups();
  } catch (err) { toast(err.message, 6000); }
}

registerScreen("localbackups", () => renderLocalBackups());
