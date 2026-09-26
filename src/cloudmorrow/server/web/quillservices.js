/* What a Quill's code is doing on this server, for an administrator.

   Drawn into two places Administration already has. On the Quills side,
   under the catalog, a group of every service that is meant to be running
   and how it is — running, restarting, stopped — each a link to its Quill's
   sheet. On an installed Quill's sheet, everything: each service's state,
   since when, how it last exited and the last lines of its log; each `run`
   job and when it last ran; each webhook's address with its secret, to copy
   into whatever sends it; who it all runs as; and the three things to do to
   running code — restart it, give it a new token, give a webhook a new
   secret. None of those is the sheet's one amber button: that stays
   Install. */

import { api, esc, toast } from "./core.js";

const url = (id) => "/api/quillservices/" + encodeURIComponent(id);
const STATES = { running: "good", restarting: "warn", stopped: "" };

async function rows() {
  try { return await api("GET", "/api/quillservices"); } catch { return []; }
}

const chip = (state) =>
  `<span class="quill-chip run-state ${STATES[state] || ""}">${esc(state)}</span>`;

/** Under the catalog: every service that should be up, and whether it is. */
export async function drawRunningList(panel) {
  const found = (await rows()).filter((q) => (q.services || []).some((s) => !s.scheduled));
  if (!found.length) return;
  const items = found.flatMap((q) => q.services.filter((s) => !s.scheduled).map((s) =>
    `<a class="row quill-row" href="#/adminquill/${encodeURIComponent(q.id)}">
      <span class="main"><span class="title">${esc(q.name)} · ${esc(s.id)}</span>
      <span class="meta"><span class="preview">${esc(s.problem || `since ${s.since}`)}</span></span></span>
      ${chip(s.state)}</a>`));
  panel.insertAdjacentHTML("beforeend",
    `<p class="group-label">Running on this server</p><div class="group">${items.join("")}</div>`);
}

/** On an installed Quill's sheet: its running code, and what can be done to it. */
export async function drawRunning(holder, id) {
  const quill = (await rows()).find((q) => q.id === id);
  if (!quill) { holder.innerHTML = ""; return; }
  const fact = (title, note = "", right = "") => `<div class="row sheet-fact">
    <span class="main"><span class="title">${title}</span>${note ? `<span class="meta"><span class="preview">${note}</span></span>` : ""}</span>${right}</div>`;
  const reach = (quill.reach || []).join(", ") || "nothing";
  const who = quill.runs_as
    ? `Runs as ${esc(quill.runs_as)}, and can read and write only: ${esc(reach)}.`
    : "Runs as nobody: whoever installed it is gone. Install it again to run it as you.";

  const services = (quill.services || []).map((s) => {
    const exit = s.last_exit === null || s.last_exit === undefined ? ""
      : ` · last exit ${esc(String(s.last_exit))}${s.restarts ? `, ${esc(String(s.restarts))} restarts` : ""}`;
    const how = s.scheduled ? "started by its job" : esc(s.problem || `since ${s.since}`);
    const log = (s.log || []).length
      ? `<pre class="run-log">${esc(s.log.join("\n"))}</pre>` : "";
    return fact(`${esc(s.id)} <code>${esc((s.command || []).join(" "))}</code>`, how + exit,
      s.scheduled ? "" : chip(s.state)) + log;
  });
  const jobs = (quill.jobs || []).map((j) => fact(`Job ${esc(j.id)}`,
    `runs ${esc(j.service)} every ${esc(j.every)} · last ${esc(j.last_started || "never yet")}`
      + (j.last_exit === null || j.last_exit === undefined ? "" : `, exit ${esc(String(j.last_exit))}`),
    j.running ? chip("running") : ""));
  const hooks = (quill.webhooks || []).map((h) => {
    const address = `${h.url}?token=${h.secret}`;
    const what = h.model ? `makes a ${esc(h.model)}` : `goes to ${esc(h.forward)}`;
    const signed = h.signature ? `, or signed in ${esc(h.signature)} with the secret` : "";
    return `<div class="row sheet-fact hook" data-hook="${esc(h.id)}">
      <span class="main"><span class="title">Webhook ${esc(h.id)}</span>
      <span class="meta"><span class="preview">${what}${signed}</span></span>
      <code class="hook-address">${esc(address)}</code></span>
      <span class="hook-buttons">
        <button type="button" class="chip-button copy-hook" data-address="${esc(address)}">Copy</button>
        <button type="button" class="chip-button rotate-hook">New secret</button>
      </span></div>`;
  });

  holder.innerHTML = `
    <p class="group-label">Running now</p>
    <div class="group">${[fact("Who it runs as", esc(who)), ...services, ...jobs].join("")}</div>
    ${hooks.length ? `<p class="group-label">Webhook addresses</p><div class="group">${hooks.join("")}</div>
      <p class="shelf-note">Give the sender the whole address; the secret in it is what lets it in.</p>` : ""}
    <div class="group">
      <button class="row restart-quill" type="button">Restart its services</button>
      <button class="row rotate-token" type="button">Give it a new token</button>
    </div>`;

  const again = () => drawRunning(holder, id);
  const act = async (what, done) => {
    try { await what(); toast(done); await again(); } catch (err) { toast(err.message); }
  };
  holder.querySelector(".restart-quill").addEventListener("click", () =>
    act(() => api("POST", url(id) + "/restart"), "Restarting"));
  holder.querySelector(".rotate-token").addEventListener("click", () => {
    if (!confirm("Give it a new token?\n\nThe one it has stops working now, and its services restart with the new one.")) return;
    act(() => api("POST", url(id) + "/token"), "New token; its services are restarting");
  });
  holder.querySelectorAll(".copy-hook").forEach((button) => button.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(button.dataset.address); toast("Copied"); }
    catch (err) { toast(err.message || "Could not copy"); }
  }));
  holder.querySelectorAll(".rotate-hook").forEach((button) => button.addEventListener("click", () => {
    const hook = button.closest("[data-hook]").dataset.hook;
    if (!confirm(`A new secret for ${hook}?\n\nWhatever sends it needs the new address from now.`)) return;
    act(() => api("POST", `${url(id)}/webhooks/${encodeURIComponent(hook)}/secret`), "New secret");
  }));
}
