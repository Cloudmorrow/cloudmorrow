/* Administration, Backups: everything on the server into a bucket every day, and back.

   The sixth side of Administration (admin.js). Three things on it: where
   backups go — an S3 bucket, Amazon's or anybody's who speaks the same —
   and when, and what; the last run, with Back up now and its log; and
   what is in the bucket, each backup a row, and on each a sheet with its
   parts to tick and Restore — and, on a drive or a share, a look inside,
   folder by folder, to pick single files as they were that day, or save a
   copy of one. A backup or a restore runs on the server
   for as long as it takes, so this page asks every two seconds how it is
   going and writes the lines as they come, and when a restore brings the
   database back the server restarts itself, as an update does, and the
   page waits for it the same way. Every question is a sheet (dialog.js);
   the secret key is typed once and never shown again. */

import { api, apiRaw, esc, toast } from "./core.js";
import { ask, openSheet } from "./dialog.js";

// The parts a backup is made of, and the words for each. The keys are the
// server's (backups.py, PARTS).
const PARTS = [
  ["database", "Database", "Accounts, circles, roles, every record, the settings and the secrets, which Quills are installed."],
  ["drives", "Everybody's files", "Each person's drive: My Files with their notes in it. Only what changed since the day before goes up."],
  ["shares", "Shares", "Every share, wherever its folder is. Only what changed goes up."],
  ["quills", "Quills", "The installed Quills, people's own, the datamodels and the runtimes fetched for them."],
  ["keys", "Keys", "The token signing key, the identity key and the push key."],
];
const PART_LABELS = Object.fromEntries(PARTS.map(([key, label]) => [key, label]));
const POLL = 2000;
const HEALTH_WAIT = 90 * 1000;

/** Bytes, said short. */
export function sizeOf(count) {
  let size = Number(count) || 0;
  for (const unit of ["B", "kB", "MB", "GB", "TB"]) {
    if (size < 1000 || unit === "TB") return unit === "B" ? `${size.toFixed(0)} B` : `${size.toFixed(1)} ${unit}`;
    size /= 1000;
  }
  return `${count} B`;
}

/** A moment, as the rows say it: 23 Oct 2026, 03:00. */
const whenSaid = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
};

export async function drawBackups(panel) {
  let status;
  try {
    status = await api("GET", "/api/server/backup");
  } catch (err) {
    panel.innerHTML = `<p class="note">${esc(err.status === 404
      ? "This server is from before it could back itself up. Update it first."
      : err.message)}</p>`;
    return;
  }
  const s = status.settings;
  const part = ([key, label, note]) => `<label class="row feature-row">
    <span class="main"><span class="title">${esc(label)}</span>
    <span class="meta"><span class="preview">${esc(note)}</span></span></span>
    <input type="checkbox" name="parts" value="${key}"${s.parts.includes(key) ? " checked" : ""}></label>`;
  panel.innerHTML = `
    <form class="server-settings backup-settings">
      <p class="group-label">Where they go</p>
      <div class="group">
        <label class="row"><span class="main">Endpoint</span>
          <input name="endpoint" value="${esc(s.endpoint)}" placeholder="https://s3.eu-north-1.amazonaws.com"
            autocapitalize="none" autocorrect="off" spellcheck="false" inputmode="url"></label>
        <label class="row"><span class="main">Bucket</span>
          <input name="bucket" value="${esc(s.bucket)}" placeholder="my-cloud-backups"
            autocapitalize="none" autocorrect="off" spellcheck="false"></label>
        <label class="row"><span class="main">Folder</span>
          <input name="prefix" value="${esc(s.prefix)}" placeholder="optional"
            autocapitalize="none" autocorrect="off" spellcheck="false"></label>
        <label class="row"><span class="main">Region</span>
          <input name="region" value="${esc(s.region)}" placeholder="blank: Amazon's, else us-east-1"
            autocapitalize="none" autocorrect="off" spellcheck="false"></label>
        <label class="row"><span class="main">Access key</span>
          <input name="access_key" value="${esc(s.access_key)}" autocapitalize="none" autocorrect="off" spellcheck="false"></label>
        <label class="row"><span class="main">Secret key</span>
          <input name="secret_key" type="password" autocomplete="off"
            placeholder="${s.has_secret ? "kept — type to replace" : "the key's secret"}"></label>
      </div>
      <p class="note">Any store that speaks S3: Amazon, Hetzner, Backblaze, Cloudflare R2, Wasabi, a MinIO of
        your own. The secret is sealed on the server and never shown again. The database goes up sealed as
        it is on disk; files go up as they are, so give the bucket to nobody you would not give the disk.</p>
      <p class="group-label">When</p>
      <div class="group">
        <label class="row feature-row"><span class="main"><span class="title">Every day</span>
          <span class="meta"><span class="preview">Off, backups run only when you press Back up now.</span></span></span>
          <input type="checkbox" name="enabled"${s.enabled ? " checked" : ""}></label>
        <label class="row"><span class="main">At</span>
          <input name="time" type="time" value="${esc(s.time)}" required></label>
        <label class="row"><span class="main">Keep for</span>
          <span class="with-unit"><input name="keep_days" type="number" min="1" max="3650" value="${s.keep_days}" required
            inputmode="numeric"><span class="unit">days</span></span></label>
      </div>
      <p class="note">The server's own clock, in its time zone. Every day is a complete picture, but only what
        changed since the day before goes up, so a file is there as it was on each day kept. A daily backup
        older than the days kept is taken out of the bucket after the next one lands, and with it whatever no
        other day still needs.</p>
      <p class="group-label">What</p>
      <div class="group">${PARTS.map(part).join("")}
        <label class="row feature-row seal-key"><span class="main"><span class="title">The sealing key too</span>
          <span class="meta"><span class="preview">With the keys. Off, the database in the bucket opens with nothing in it;
            keep the key apart yourself. On, whoever holds the bucket holds everything.</span></span></span>
          <input type="checkbox" name="seal_key"${s.seal_key ? " checked" : ""}></label>
      </div>
      <div class="group"><button class="row primary" type="submit">Save</button></div>
      <div class="group"><button class="row try-bucket" type="button">Try the bucket</button></div>
    </form>
    <p class="group-label">Backing up</p>
    <div class="backup-status"></div>
    <div class="group"><button class="row primary back-up-now" type="button">Back up now</button></div>
    <div class="update-log backup-log" hidden></div>
    <p class="group-label">In the bucket</p>
    <div class="backup-list"><p class="note muted">Looking…</p></div>`;

  const form = panel.querySelector("form.backup-settings");
  const statusBox = panel.querySelector(".backup-status");
  const log = panel.querySelector(".backup-log");
  const runButton = panel.querySelector(".back-up-now");
  const list = panel.querySelector(".backup-list");

  const changes = () => {
    const picked = [...form.querySelectorAll('input[name="parts"]:checked')].map((box) => box.value);
    const body = {
      endpoint: form.elements.endpoint.value.trim(),
      bucket: form.elements.bucket.value.trim(),
      prefix: form.elements.prefix.value.trim(),
      region: form.elements.region.value.trim(),
      access_key: form.elements.access_key.value.trim(),
      time: form.elements.time.value,
      keep_days: Number(form.elements.keep_days.value) || 30,
      parts: picked,
      seal_key: form.elements.seal_key.checked,
      enabled: form.elements.enabled.checked,
    };
    // A blank secret keeps the one the server has.
    if (form.elements.secret_key.value) body.secret_key = form.elements.secret_key.value;
    return body;
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const save = form.querySelector("button[type=submit]");
    save.disabled = true;
    try {
      status = await api("PATCH", "/api/server/backup", changes());
      form.elements.secret_key.value = "";
      form.elements.secret_key.placeholder = status.settings.has_secret ? "kept — type to replace" : "the key's secret";
      toast("Saved");
      drawStatus();
      drawList();
    } catch (err) {
      toast(err.message);
    } finally {
      save.disabled = false;
    }
  });

  form.querySelector(".try-bucket").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "Trying…";
    try {
      // What is in the form, saved first: trying what is not saved would try the wrong thing.
      status = await api("PATCH", "/api/server/backup", changes());
      form.elements.secret_key.value = "";
      const told = await api("POST", "/api/server/backup/test");
      toast(`The bucket answers: ${told.backups} backup${told.backups === 1 ? "" : "s"} there`);
      drawList();
    } catch (err) {
      toast(err.message, 5000);
    } finally {
      button.disabled = false;
      button.textContent = "Try the bucket";
    }
  });

  // -- what is going on -------------------------------------------------------------
  function drawStatus() {
    const last = status.last;
    const restore = status.last_restore;
    const line = (label, told) => {
      if (!told) return `<div class="row"><span class="main">${label}</span><span class="value muted">none yet</span></div>`;
      const verdict = told.ok ? `<span class="good">ok</span>` : `<span class="bad">failed</span>`;
      const size = (told.size ? ` · ${sizeOf(told.size)}` : "") + (told.size && told.added != null ? `, ${sizeOf(told.added)} new` : "");
      return `<div class="row"><span class="main"><span class="title">${label}</span>
        <span class="meta"><span class="preview">${esc(whenSaid(told.finished_at || told.started_at))}${size}${
          told.ok ? "" : " · " + esc(told.error || "")}</span></span></span>${verdict}</div>`;
    };
    const running = status.running
      ? `<div class="row"><span class="main"><span class="title">${status.running === "restore" ? "Restoring" : "Backing up"}…</span>
          <span class="meta"><span class="preview">${esc(status.step || "")}</span></span></span></div>`
      : "";
    const held = status.store && status.store.objects
      ? `<div class="row"><span class="main"><span class="title">In the store</span>
          <span class="meta"><span class="preview">${esc(sizeOf(status.store.bytes))} in ${status.store.objects.toLocaleString()} objects, every day's files once</span></span></span></div>`
      : "";
    statusBox.innerHTML = `<div class="group">${running}${line("Last backup", last)}${line("Last restore", restore)}${held}</div>`
      + (status.settings.configured ? "" : `<p class="note">Say where backups go, and Save, before backing up.</p>`);
    runButton.disabled = Boolean(status.running) || !status.settings.configured;
    runButton.textContent = status.running === "backup" ? "Backing up…" : "Back up now";
  }

  const writeLines = (lines) => {
    log.hidden = lines.length === 0;
    log.innerHTML = lines.map((text) => `<p class="${text.startsWith("Failed") ? "bad" : text.startsWith("Done") ? "good" : "muted"}">${esc(text)}</p>`).join("");
  };

  /** Ask the server how it goes until nothing runs; the log follows along. */
  async function follow(what) {
    while (panel.isConnected) {
      await new Promise((r) => setTimeout(r, POLL));
      try {
        status = await api("GET", "/api/server/backup");
      } catch (err) {
        // The server going away mid-restore is the restart; the page waits for it below.
        if (what === "restore") return null;
        toast(err.message);
        return null;
      }
      writeLines(status.lines);
      drawStatus();
      if (status.running !== what) return status;
    }
    return null;
  }

  runButton.addEventListener("click", async () => {
    runButton.disabled = true;
    try {
      status = await api("POST", "/api/server/backup/run", {});
    } catch (err) {
      toast(err.message, 5000);
      runButton.disabled = false;
      return;
    }
    writeLines([]);
    drawStatus();
    const done = await follow("backup");
    if (done && done.last && done.last.ok) toast("Backed up");
    drawList();
  });

  // -- what is in the bucket ----------------------------------------------------------------
  async function drawList() {
    if (!status.settings.configured) {
      list.innerHTML = `<p class="note muted">Nothing to look in yet.</p>`;
      return;
    }
    let found;
    try {
      found = await api("GET", "/api/server/backups");
    } catch (err) {
      list.innerHTML = `<p class="note">${esc(err.message)}</p>`;
      return;
    }
    if (!found.length) {
      list.innerHTML = `<p class="note muted">No backups in the bucket yet.</p>`;
      return;
    }
    list.innerHTML = `<div class="group">${found.map((b) => `
      <button class="row backup-row" type="button" data-stamp="${esc(b.stamp)}">
        <span class="main"><span class="title">${esc(whenSaid(b.made_at))}</span>
        <span class="meta"><span class="preview">${esc(sizeOf(b.size))}${b.format >= 2 ? `, ${esc(sizeOf(b.added))} new` : ""} · ${esc((b.parts || []).map((p) => PART_LABELS[p] || p).join(", "))}${
          b.drives ? ` · ${b.drives} drive${b.drives === 1 ? "" : "s"}` : ""}${
          b.shares ? ` · ${b.shares} share${b.shares === 1 ? "" : "s"}` : ""}</span></span></span>
        ${b.key_matches ? "" : `<span class="role-chip other-key">another key</span>`}
      </button>`).join("")}</div>`;
    for (const row of list.querySelectorAll(".backup-row")) {
      row.addEventListener("click", () => openBackup(row.dataset.stamp));
    }
  }

  async function openBackup(stamp) {
    let m;
    try {
      m = await api("GET", "/api/server/backups/" + encodeURIComponent(stamp));
    } catch (err) {
      toast(err.message);
      return;
    }
    const browsable = (m.cloudmorrow_backup || 1) >= 2;
    // Single files and folders picked inside a drive or a share: drives/bram/files/Notes/a.md, a folder with a slash.
    const picked = new Set();
    const box = (name, value, label, note, where = "") => `<div class="row feature-row">
      <span class="main"><span class="title">${esc(label)}</span>${note ? `<span class="meta"><span class="preview">${esc(note)}</span></span>` : ""}</span>
      ${where ? `<button type="button" class="browse-in" data-where="${esc(where)}" data-label="${esc(label)}">files…</button>` : ""}
      <input type="checkbox" name="${name}" value="${esc(value)}"></div>${
        where ? `<div class="browse-pane" data-where="${esc(where)}" hidden></div>` : ""}`;
    const group = (label, rows, all) => (rows ? `<p class="group-label">${label}${all ? ` <button type="button" class="all-of" data-all="${all}">all</button>` : ""}</p>
      <div class="group">${rows}</div>` : "");
    const drives = (m.drives || []).map((d) => box("drive", d.name, d.name, `${sizeOf(d.size)} · ${d.files} files`, browsable ? `drives/${d.name}` : "")).join("");
    const shares = (m.shares || []).map((s) => box("share", s.name, s.name, `${sizeOf(s.size)} · ${s.files} files`, browsable ? `shares/${s.name}` : "")).join("");
    const keyNote = m.key_matches
      ? ""
      : `<p class="note warn">Sealed with another key than this server's. Its rows open here only if the sealing key
          comes back with it (tick Keys, when the backup carries it) or the right key file is put in place first.</p>`;
    const oldNote = browsable ? "" : `<p class="note muted">From before single files could be looked at: whole drives and shares only.</p>`;
    const { sheet, close } = openSheet(
      `<form class="restore-form">
        <h2 class="act-sheet-title">${esc(whenSaid(m.made_at))}</h2>
        <p class="act-description">${esc(m.cloud || "")} · Cloudmorrow ${esc(m.version || "")} · ${esc(sizeOf(m.size))}${
          browsable ? `, ${esc(sizeOf(m.added || 0))} new that day` : ""} in ${esc(String(m.took || 0))} s
          · ${esc(m.by ? `by ${m.by}` : "")}</p>
        ${keyNote}${oldNote}
        <div class="restore-parts">
          ${m.database ? group("Database", box("database", "1", "Database", `${m.database.engine} · ${sizeOf(m.database.size)}`)) : ""}
          ${group("Files", drives, "drive")}
          ${group("Shares", shares, "share")}
          ${m.quills || m.keys ? group("Server", (m.quills ? box("quills", "1", "Quills", `${sizeOf(m.quills.size)} · ${m.quills.files} files`) : "")
            + (m.keys ? box("keys", "1", "Keys", (m.keys.files || []).join(", ")) : "")) : ""}
        </div>
        <p class="note picked-note" hidden></p>
        <div class="act-buttons">
          <button type="button" class="act-button" data-answer="no">Cancel</button>
          <button type="button" class="act-button" data-answer="delete">Delete</button>
          <button type="submit" class="act-button danger">Restore</button>
        </div>
      </form>`,
      "restore-sheet",
    );
    const form = sheet.querySelector("form");
    const pickedNote = form.querySelector(".picked-note");
    const sayPicked = () => {
      pickedNote.hidden = picked.size === 0;
      pickedNote.textContent = picked.size
        ? `${picked.size} single ${picked.size === 1 ? "file or folder" : "files and folders"} picked: ${[...picked].map((p) => p.split("/").slice(2).join("/")).join(", ")}`
        : "";
    };
    for (const button of form.querySelectorAll(".all-of")) {
      button.addEventListener("click", () => {
        const boxes = [...form.querySelectorAll(`input[name="${button.dataset.all}"]`)];
        const every = boxes.every((b) => b.checked);
        for (const b of boxes) b.checked = !every;
      });
    }

    // -- a look inside a drive or a share, folder by folder ------------------------------
    async function drawBrowse(pane, where, path) {
      pane.innerHTML = `<p class="note muted">Looking…</p>`;
      let told;
      try {
        told = await api("GET", `/api/server/backups/${encodeURIComponent(stamp)}/files?where=${encodeURIComponent(where)}&path=${encodeURIComponent(path)}`);
      } catch (err) {
        pane.innerHTML = `<p class="note warn">${esc(err.message)}</p>`;
        return;
      }
      const crumbs = [["", where.split("/")[1]], ...told.path.split("/").filter(Boolean).map((name, i, all) => [all.slice(0, i + 1).join("/"), name])];
      const crumbRow = crumbs.map(([to, name], i) => (i === crumbs.length - 1
        ? `<span class="crumb here">${esc(name)}</span>`
        : `<button type="button" class="crumb" data-path="${esc(to)}">${esc(name)}</button>`)).join(`<span class="sep">/</span>`);
      const rel = (name) => (told.path ? `${told.path}/${name}` : name);
      const pick = (name, folder) => `${where}/${rel(name)}${folder ? "/" : ""}`;
      const folders = told.folders.map((f) => `<div class="row browse-row">
        <input type="checkbox" data-pick="${esc(pick(f.name, true))}"${picked.has(pick(f.name, true)) ? " checked" : ""} aria-label="Pick the folder ${esc(f.name)}">
        <button type="button" class="main enter" data-path="${esc(rel(f.name))}"><span class="title">${esc(f.name)}/</span>
          <span class="meta"><span class="preview">${f.files} file${f.files === 1 ? "" : "s"} · ${esc(sizeOf(f.size))}</span></span></button></div>`).join("");
      const files = told.files.map((f) => `<div class="row browse-row">
        <input type="checkbox" data-pick="${esc(pick(f.name, false))}"${picked.has(pick(f.name, false)) ? " checked" : ""} aria-label="Pick ${esc(f.name)}">
        <span class="main"><span class="title">${esc(f.name)}</span>
          <span class="meta"><span class="preview">${esc(sizeOf(f.size))} · ${esc(whenSaid(f.modified))}</span></span></span>
        <button type="button" class="pull" data-path="${esc(pick(f.name, false))}" data-name="${esc(f.name)}" aria-label="Save a copy of ${esc(f.name)}">save</button></div>`).join("");
      pane.innerHTML = `<div class="crumbs">${crumbRow}</div>${folders}${files}${
        !folders && !files ? `<p class="note muted">Nothing in this folder that day.</p>` : ""}`;
      for (const crumb of pane.querySelectorAll(".crumb[data-path]")) {
        crumb.addEventListener("click", () => drawBrowse(pane, where, crumb.dataset.path));
      }
      for (const enter of pane.querySelectorAll(".enter")) {
        enter.addEventListener("click", () => drawBrowse(pane, where, enter.dataset.path));
      }
      for (const tick of pane.querySelectorAll("input[data-pick]")) {
        tick.addEventListener("change", () => {
          if (tick.checked) picked.add(tick.dataset.pick); else picked.delete(tick.dataset.pick);
          sayPicked();
        });
      }
      for (const pull of pane.querySelectorAll(".pull")) {
        pull.addEventListener("click", async () => {
          pull.disabled = true;
          try {
            const res = await apiRaw("GET", `/api/server/backups/${encodeURIComponent(stamp)}/file?path=${encodeURIComponent(pull.dataset.path)}`, { fail: "could not fetch the file" });
            const url = URL.createObjectURL(await res.blob());
            const a = document.createElement("a");
            a.href = url;
            a.download = pull.dataset.name;
            a.click();
            setTimeout(() => URL.revokeObjectURL(url), 10_000);
          } catch (err) {
            toast(err.message);
          } finally {
            pull.disabled = false;
          }
        });
      }
    }
    for (const button of form.querySelectorAll(".browse-in")) {
      button.addEventListener("click", () => {
        const pane = form.querySelector(`.browse-pane[data-where="${button.dataset.where.replace(/"/g, '\\"')}"]`);
        if (!pane) return;
        pane.hidden = !pane.hidden;
        button.textContent = pane.hidden ? "files…" : "close";
        if (!pane.hidden && !pane.dataset.drawn) {
          pane.dataset.drawn = "1";
          drawBrowse(pane, button.dataset.where, "");
        }
      });
    }

    form.querySelector('[data-answer="no"]').addEventListener("click", close);
    form.querySelector('[data-answer="delete"]').addEventListener("click", async () => {
      close();
      if (!(await ask(`Delete the backup from ${whenSaid(m.made_at)}?\n\nIt is taken out of the bucket, with whatever no other day still needs. The server is not touched.`))) return;
      try {
        await api("DELETE", "/api/server/backups/" + encodeURIComponent(stamp));
        toast("Deleted");
        drawList();
      } catch (err) {
        toast(err.message);
      }
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const ticked = (name) => [...form.querySelectorAll(`input[name="${name}"]:checked`)].map((b) => b.value);
      const choice = {
        database: ticked("database").length > 0,
        drives: ticked("drive"),
        shares: ticked("share"),
        paths: [...picked],
        quills: ticked("quills").length > 0,
        keys: ticked("keys").length > 0,
        restart: true,
        force: false,
      };
      if (!choice.database && !choice.drives.length && !choice.shares.length && !choice.paths.length && !choice.quills && !choice.keys) {
        toast("Tick what to restore");
        return;
      }
      close();
      const said = [];
      if (choice.database) said.push("the database");
      if (choice.drives.length) said.push(`the files of ${choice.drives.join(", ")}`);
      if (choice.shares.length) said.push(`the share${choice.shares.length === 1 ? "" : "s"} ${choice.shares.join(", ")}`);
      if (choice.paths.length) said.push(choice.paths.length === 1 ? choice.paths[0] : `${choice.paths.length} single files and folders`);
      if (choice.quills) said.push("the Quills");
      if (choice.keys) said.push("the keys");
      const restarts = choice.database || choice.quills || choice.keys;
      const sure = await ask(
        `Restore ${said.join(", ")} from ${whenSaid(m.made_at)}?\n\n`
        + "What the backup has goes over what is on the server now; what it does not have is left alone. "
        + (choice.database ? "A copy of today's database is kept on the server first. " : "")
        + (restarts ? "The server restarts afterwards; everybody is offline for a few seconds." : ""),
        { yes: "Restore", tone: "danger" },
      );
      if (!sure) return;
      try {
        status = await api("POST", `/api/server/backups/${encodeURIComponent(stamp)}/restore`, choice);
      } catch (err) {
        toast(err.message, 6000);
        return;
      }
      writeLines([]);
      drawStatus();
      const done = await follow("restore");
      const result = done ? done.last_restore : null;
      if (result && result.ok && !result.restarting) {
        toast(result.restart_blocked ? `Restored. Not restarted: ${result.restart_blocked}` : "Restored", 6000);
        return;
      }
      if (result && !result.ok) return;
      // Restarting, or already gone: wait for it to answer again, then come back on the fresh app.
      const waiting = document.createElement("p");
      waiting.className = "muted";
      waiting.textContent = "Restored. Restarting — waiting for the server to come back…";
      log.hidden = false;
      log.append(waiting);
      const back = await waitForServer();
      waiting.textContent = back ? "Back up. Reloading…" : "The server has not answered yet. It may still be starting; reload when it does.";
      waiting.className = back ? "good" : "warn";
      if (back) setTimeout(() => location.reload(), 1200);
    });
  }

  drawStatus();
  writeLines(status.lines || []);
  if (status.running) follow(status.running).then(() => drawList());
  drawList();
}

// The server going away and coming back: /api/health answers again.
async function waitForServer() {
  const deadline = Date.now() + HEALTH_WAIT;
  await new Promise((r) => setTimeout(r, 2500));
  while (Date.now() < deadline) {
    try {
      await api("GET", "/api/health?t=" + Date.now());
      return true;
    } catch { /* down: that is the restart */ }
    await new Promise((r) => setTimeout(r, 800));
  }
  return false;
}
