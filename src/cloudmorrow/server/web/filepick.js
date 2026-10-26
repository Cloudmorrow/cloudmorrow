/* Picking a file from anywhere on the cloud: the shares, then the folders
   in one, then a file of the kind asked for.

   A screen over files in one folder — a document screen over Documents,
   a sheet screen — opens a file that lives somewhere else through this:
   the Open button asks here, and what is picked is opened by its record,
   wherever it is (kit_docs.js, kit_cells.js). The sheet is dialog.js's,
   so it looks like every other question the app asks; it starts where it
   was last, the shares the first time: My Files and the fileshares, as
   the `share` datamodel lists them, each with a line about whose it is.
   In a share, the folders come first and then the files whose name ends
   in one of the suffixes wanted; the rest are not shown, since they could
   not be opened. Nothing here is named for one Quill. */

import { api, esc, recordsUrl, toast } from "./core.js";
import { openSheet } from "./dialog.js";

const own = {
  share: '<svg width="22" height="18" viewBox="0 0 22 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="1.5" y="2" width="19" height="14" rx="2"/><path d="M1.5 7h19"/></svg>',
  folder: '<svg width="22" height="18" viewBox="0 0 22 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M1.5 3.5A1.5 1.5 0 0 1 3 2h5l2 2.5h9a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5H3a1.5 1.5 0 0 1-1.5-1.5z"/></svg>',
  file: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11.5 2H5a1.5 1.5 0 0 0-1.5 1.5v13A1.5 1.5 0 0 0 5 18h10a1.5 1.5 0 0 0 1.5-1.5V7z"/><path d="M11.5 2v5h5"/></svg>',
  up: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4 6 10l6 6"/></svg>',
};

// Where the picker was last: a share and a folder in it, or nothing for the shares.
let remembered = null;

const byName = (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
const endsWithOne = (name, suffixes) => {
  const lower = String(name || "").toLowerCase();
  return !suffixes.length || suffixes.some((s) => lower.endsWith(String(s).toLowerCase()));
};

const rowHtml = (icon, title, subtitle, attrs, kind = "") =>
  `<button type="button" class="pick-row${kind ? " " + kind : ""}" ${attrs}>` +
  `<span class="pick-icon">${icon}</span><span class="pick-main"><span class="pick-title">${esc(title)}</span>` +
  (subtitle ? `<span class="pick-sub">${esc(subtitle)}</span>` : "") + `</span></button>`;

/**
 * A file picked from anywhere: resolves its file record, or null for no.
 * `suffixes` says which files may be picked; `title` heads the sheet.
 */
export function pickFile({ suffixes = [], title = "Open", model = "file" } = {}) {
  return new Promise((resolve) => {
    const { backdrop, sheet, close } = openSheet(
      `<p class="act-sheet-title">${esc(title)}</p><p class="pick-where"></p>` +
      `<div class="pick-rows"><p class="pick-empty">Loading…</p></div>` +
      `<button type="button" class="sheet-row cancel">Cancel</button>`,
      "act-choose act-pick", () => resolve(null));
    const whereEl = sheet.querySelector(".pick-where");
    const rowsEl = sheet.querySelector(".pick-rows");
    let at = remembered ? { ...remembered } : null;
    let shown = 0;

    async function show() {
      const turn = ++shown;
      rowsEl.innerHTML = `<p class="pick-empty">Loading…</p>`;
      try {
        if (!at) {
          whereEl.textContent = "";
          const shares = await api("GET", recordsUrl("share"));
          if (turn !== shown) return;
          rowsEl.innerHTML = shares.filter((s) => s.fields.browsable !== false).map((s) =>
            rowHtml(own.share, s.fields.label || s.id, s.fields.about || "", `data-share="${esc(s.id)}"`)).join("")
            || `<p class="pick-empty">Nothing to open.</p>`;
          return;
        }
        whereEl.textContent = at.label + (at.folder ? " › " + at.folder.replace(/\//g, " › ") : "");
        const query = "?" + new URLSearchParams({ share: at.share, folder: at.folder }).toString();
        const entries = await api("GET", recordsUrl(model, "", query));
        if (turn !== shown) return;
        const folders = entries.filter((e) => e.fields.kind === "folder").map((e) => e.fields).sort(byName);
        const files = entries.filter((e) => e.fields.kind !== "folder" && endsWithOne(e.fields.name, suffixes))
          .map((e) => ({ ...e.fields, id: e.id })).sort(byName);
        const up = rowHtml(own.up, at.folder ? "Back" : "All places", "", 'data-up="1"', "up");
        rowsEl.innerHTML = up
          + folders.map((f) => rowHtml(own.folder, f.name, "", `data-folder="${esc(f.path)}"`)).join("")
          + files.map((f) => rowHtml(own.file, f.name, "", `data-id="${esc(f.id)}"`, "file")).join("")
          + (!folders.length && !files.length ? `<p class="pick-empty">Nothing to open here.</p>` : "");
      } catch (err) {
        if (turn !== shown) return;
        rowsEl.innerHTML = `<p class="pick-empty">${esc(err.message)}</p>`;
        if (at && err.status !== 401) { at = null; toast(err.message); show(); }
      }
    }

    backdrop.addEventListener("click", (event) => {
      const row = event.target.closest(".pick-row, .cancel");
      if (!row) return;
      if (row.classList.contains("cancel")) { close(); resolve(null); return; }
      if (row.dataset.share !== undefined) {
        at = { share: row.dataset.share, folder: "", label: row.querySelector(".pick-title").textContent };
        show();
      } else if (row.dataset.up !== undefined) {
        if (at.folder) at.folder = at.folder.includes("/") ? at.folder.slice(0, at.folder.lastIndexOf("/")) : "";
        else at = null;
        show();
      } else if (row.dataset.folder !== undefined) {
        at.folder = row.dataset.folder;
        show();
      } else if (row.dataset.id !== undefined) {
        remembered = { ...at };
        close();
        resolve({ id: row.dataset.id, name: row.querySelector(".pick-title").textContent, share: at.share, folder: at.folder });
      }
    });
    show();
  });
}
