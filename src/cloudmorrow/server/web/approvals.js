/* Approvals: what waits for your answer, and what you asked (docs/FLOWS.md).

   One screen for every yes-or-no question on the server, whichever Quill
   or flow asked it, reached from Me. A question is asked of a role, so it
   waits for whoever holds the role today; the asker sees it under "Asked
   by you" until it is answered, and may withdraw it. */

import {
  api, app, esc, mount, nav, registerScreen, renderRoute, toast, wireShell,
} from "./core.js";

/** The row that leads here, for Me, with how many wait. */
export function approvalsRow(count = 0) {
  return `<div class="group"><a class="row approvals-link" href="#/approvals">
    <span class="main"><span class="title">Waiting for you</span>
    <span class="meta"><span class="preview">Questions asked of a role you hold, and what you asked others</span></span></span>
    ${count ? `<span class="count badge">${count}</span>` : ""}</a></div>`;
}

const when = (stamp) => (stamp ? new Date(stamp).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "");

function approvalRow(a, mine) {
  const f = a.fields;
  const about = f.about_title ? esc(f.about_title) + (f.about_model ? ` <span class="dim">(${esc(f.about_model)})</span>` : "") : "";
  const who = mine ? `asked of ${esc(f.role)}${f.circle ? " in " + esc(f.circle) : ""}` : `asked by ${esc(f.asked_by || a.owner)}`;
  const due = f.due ? ` · due ${esc(when(f.due))}` : "";
  const buttons = mine
    ? `<button type="button" class="act-chip" data-answer="withdrawn" data-id="${esc(a.id)}">Withdraw</button>`
    : `<button type="button" class="act-chip danger" data-answer="declined" data-id="${esc(a.id)}">Decline</button>
       <button type="button" class="act-chip primary" data-answer="approved" data-id="${esc(a.id)}">Approve</button>`;
  return `<div class="row approval-row">
    <span class="main"><span class="title">${esc(f.question)}</span>
    <span class="meta"><span class="preview">${about ? about + " · " : ""}${who}${due}</span></span></span>
    <span class="approval-buttons">${buttons}</span></div>`;
}

async function renderApprovals() {
  const found = await api("GET", "/api/approvals");
  mount(nav({ back: "#/me", backLabel: "Me", title: "Waiting for you" }) + `
    <main class="approvals">
      <h1 class="large">Waiting for you</h1>
      <div class="group">${found.waiting.length ? found.waiting.map((a) => approvalRow(a, false)).join("")
        : `<p class="empty">Nothing waits for your answer.</p>`}</div>
      <p class="group-label">Asked by you</p>
      <div class="group">${found.asked.length ? found.asked.map((a) => approvalRow(a, true)).join("")
        : `<p class="empty">Nothing you asked is open.</p>`}</div>
    </main>`);
  wireShell();
  app.querySelector("main").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-answer]");
    if (!button) return;
    const status = button.dataset.answer;
    let note = "";
    if (status !== "withdrawn") {
      note = prompt(status === "approved" ? "A word with the yes? (optional)" : "Why not? (optional)", "");
      if (note === null) return;
    }
    button.disabled = true;
    try {
      await api("POST", "/api/approvals/" + encodeURIComponent(button.dataset.id) + "/answer", { status, note });
      toast({ approved: "Approved", declined: "Declined", withdrawn: "Withdrawn" }[status]);
      await renderRoute();
    } catch (err) {
      button.disabled = false;
      toast(err.message);
    }
  });
}

registerScreen("approvals", renderApprovals);
