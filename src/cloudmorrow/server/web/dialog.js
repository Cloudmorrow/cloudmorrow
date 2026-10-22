/* Asking, on the page: yes or no, and a line to type.

   Never the browser's own windows. Those are the browser's, not this app's:
   they look like nothing else on the page, on a phone they are another
   app's face, and the desktop app has no window for them at all. Every
   question here comes up in the same sheet the grid's choices and a
   Quill's actions use — from the bottom on a phone, a dialog in the middle
   on a computer (desktop.css) — and answers a promise, so a handler reads
   `if (!(await ask(...))) return;` where it once asked the browser.

   A question's first paragraph is the question; what follows a blank line
   is the small print under it. The yes button says the question's verb
   when it starts with one worth saying — Delete, Remove, Leave, Update,
   Install, Promote — and the three that take something away are red. */

import { esc } from "./core.js";

// The verbs a yes button can say for itself, and the tone each takes.
const VERBS = { Delete: "danger", Remove: "danger", Leave: "danger", Update: "fill", Install: "fill", Promote: "fill" };

/** The sheet a question comes up in. Tapping outside it, or Escape, is no: `dismissed` hears about it. */
export function openSheet(inner, className = "", dismissed = () => {}) {
  const backdrop = document.createElement("div");
  backdrop.className = "sheet-backdrop act-backdrop";
  backdrop.innerHTML = `<div class="sheet act-sheet ${className}" role="dialog" aria-modal="true">${inner}</div>`;
  document.body.appendChild(backdrop);
  const close = () => {
    backdrop.remove();
    removeEventListener("keydown", onKey);
    removeEventListener("hashchange", onLeave);
  };
  const dismiss = () => { close(); dismissed(); };
  // Leaving the screen leaves its sheet: a form for a list that is gone is no.
  const onLeave = () => { if (backdrop.isConnected) dismiss(); };
  addEventListener("hashchange", onLeave);
  const onKey = (event) => {
    // Only the sheet on top: a question over a form is answered first.
    if (event.key === "Escape" && [...document.querySelectorAll(".act-backdrop")].pop() === backdrop) dismiss();
  };
  addEventListener("keydown", onKey);
  backdrop.addEventListener("click", (event) => { if (event.target === backdrop) dismiss(); });
  return { backdrop, sheet: backdrop.firstElementChild, close };
}

function said(text) {
  const [question, ...rest] = String(text).split("\n\n");
  const more = rest.join("\n\n").trim();
  return { question: question.trim(), more };
}

function wording(question, yes, tone) {
  const verb = question.split(/\s+/)[0].replace(/[^A-Za-z]/g, "");
  return { yes: yes || (VERBS[verb] ? verb : "OK"), tone: tone || VERBS[verb] || "neutral" };
}

/** Yes or no, in a sheet: resolves true on yes, false on no, outside, or Escape. */
export function ask(text, { yes = "", tone = "" } = {}) {
  const { question, more } = said(text);
  const say = wording(question, yes, tone);
  return new Promise((resolve) => {
    const { backdrop, sheet, close } = openSheet(
      `<p class="act-question">${esc(question)}</p>` +
      (more ? `<p class="act-description">${esc(more)}</p>` : "") +
      `<div class="act-buttons"><button type="button" class="act-button" data-answer="no">Cancel</button>` +
      `<button type="button" class="act-button ${say.tone === "danger" ? "danger" : "fill"}" data-answer="yes">${esc(say.yes)}</button></div>`,
      "act-ask", () => resolve(false));
    backdrop.addEventListener("click", (event) => {
      const button = event.target.closest("[data-answer]");
      if (!button) return;
      close();
      resolve(button.dataset.answer === "yes");
    });
    sheet.querySelector('[data-answer="yes"]').focus();
  });
}

/** A line to type, in a sheet: resolves what was typed, or null for no — as the browser's prompt did. */
export function askText(text, value = "", { yes = "OK", placeholder = "", long = false } = {}) {
  const { question, more } = said(text);
  const current = value == null ? "" : String(value);
  const field = long
    ? `<textarea class="act-input long" rows="4" aria-label="${esc(question)}">${esc(current)}</textarea>`
    : `<input class="act-input" value="${esc(current)}" placeholder="${esc(placeholder)}" aria-label="${esc(question)}"` +
      ` autocapitalize="sentences" autocorrect="off" spellcheck="false">`;
  return new Promise((resolve) => {
    const { sheet, close } = openSheet(
      `<form class="act-text">` +
      `<p class="act-question">${esc(question)}</p>` +
      (more ? `<p class="act-description">${esc(more)}</p>` : "") +
      field +
      `<div class="act-buttons"><button type="button" class="act-button" data-answer="no">Cancel</button>` +
      `<button type="submit" class="act-button fill">${esc(yes)}</button></div></form>`,
      "act-ask", () => resolve(null));
    const form = sheet.querySelector("form");
    const input = form.querySelector(".act-input");
    form.addEventListener("submit", (event) => { event.preventDefault(); close(); resolve(input.value); });
    form.querySelector('[data-answer="no"]').addEventListener("click", () => { close(); resolve(null); });
    input.focus();
    if (!long) input.select();
  });
}
