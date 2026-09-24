/* Tasks: a board, as the TUI has it — three lanes, left to right. On the
   phone the lanes are stacked, and the circle on a row is the short way
   through them: tap to finish a task, tap again to take it back. A task's
   own screen has the lane control and the body. */

import {
  SAVE_DELAY, api, app, back, esc, formatDate, heading, icons, nav, occupy, onSignOut,
  pixelIcon, registerScreen, registerTab, renderRoute, replace, seconds, setStatus, store,
  tabs, toast, vacate, wireShell,
} from "./core.js";
import { installCard } from "./install.js";

const LANES = [["todo", "To Do"], ["doing", "Doing"], ["done", "Done"]];

let boards = [];
const boardUrl = (slug) => "/api/boards/" + encodeURIComponent(slug);
const taskUrl = (slug, id) => boardUrl(slug) + "/tasks/" + id;
const byPosition = (a, b) => a.position - b.position;

async function loadBoards() {
  boards = await api("GET", "/api/boards");
}

// The board you asked for, else the one you had open, else the first.
function boardFor(slug) {
  return boards.find((b) => b.slug === (slug || store.get("board"))) || boards[0];
}

// What a row can say about a task besides its title: how many of its
// `- [ ]` lines are ticked, and the first line that is not one.
function taskMeta(body) {
  let preview = "";
  let done = 0;
  let total = 0;
  for (const line of (body || "").split("\n")) {
    const box = /^\s*[-*]\s+\[([ xX])\]/.exec(line);
    if (box) {
      total += 1;
      if (box[1] !== " ") done += 1;
    } else if (!preview && line.trim()) {
      preview = line.trim().replace(/^#+\s*/, "");
    }
  }
  return { preview, done, total };
}

const circle = (lane) => `<span class="check ${lane}">${lane === "done" ? icons.tick : ""}</span>`;

// Whether a card is worth making draggable. A phone has the circle and the
// lane control and no way to drag anything, and `draggable` on a touch
// screen is only something for a long press to catch on.
const canDrag = () => matchMedia("(hover: hover) and (pointer: fine)").matches;

// -- the board -----------------------------------------------------------------
async function renderTasks(slug) {
  await loadBoards();
  const board = boardFor(slug);
  store.set("board", board.slug);
  let tasks;
  try { tasks = await api("GET", boardUrl(board.slug) + "/tasks"); }
  catch (err) {
    if (err.status === 404) { toast("That board is gone"); replace("#/tasks"); return renderRoute(); }
    throw err;
  }
  // The boards, and on the end of them the way to start another. The row
  // is there even with one board: that last chip is what it is for then.
  const chips = `<div class="chips">${boards.map((b) =>
    `<a class="chip${b.slug === board.slug ? " active" : ""}" href="#/tasks/${encodeURIComponent(b.slug)}">${esc(b.title)}</a>`).join("")}` +
    `<button class="chip new-board" type="button">+ New board</button></div>`;
  app.innerHTML = nav({ title: board.title }) + `
    <main>
      ${heading(board.title, `<button class="compose" aria-label="New task">${icons.compose}</button>`)}
      ${chips}
      <form class="add">${circle("todo")}<input placeholder="Add a task" autocapitalize="sentences" enterkeyhint="done"></form>
      <div class="install-slot">${installCard()}</div>
      <div class="listing"></div>
    </main>` + tabs("tasks");
  wireShell();
  const listing = app.querySelector(".listing");
  const form = app.querySelector("form.add");
  const input = form.querySelector("input");

  const taskRow = (t) => {
    const { preview, done, total } = taskMeta(t.body);
    const meta = (total ? `<span class="date">${done} of ${total}</span>` : "") +
      (preview ? `<span class="preview">${esc(preview)}</span>` : "");
    return `<div class="row task lane-${esc(t.lane)}" data-task="${t.id}"${canDrag() ? ` draggable="true"` : ""}>
      <button class="tick" data-id="${t.id}" aria-label="${t.lane === "done" ? "Not done" : "Done"}">${circle(t.lane)}</button>
      <a class="main" href="#/task/${encodeURIComponent(board.slug)}/${t.id}">
        <span class="title">${esc(t.title)}</span>${meta ? `<span class="meta">${meta}</span>` : ""}</a></div>`;
  };
  const show = () => {
    if (!tasks.length) {
      listing.innerHTML = `<p class="empty"><b>Nothing to do</b>Add a task above.</p>`;
      return;
    }
    // Each lane is wrapped, which the phone cannot tell — a plain block
    // around what was already there — and which a computer lays out as
    // the three columns the TUI has. A lane with nothing in it is hidden
    // rather than skipped, because on a board of columns an empty one is
    // still somewhere to drop a card.
    listing.innerHTML = `<div class="board">` + LANES.map(([lane, label]) => {
      const rows = tasks.filter((t) => t.lane === lane).sort(byPosition);
      return `<div class="lane${rows.length ? "" : " lane-empty"}" data-lane="${lane}">` +
        `<p class="group-label">${label}</p>` +
        (rows.length
          ? `<div class="group">${rows.map(taskRow).join("")}</div>`
          : `<div class="group nothing">Nothing here</div>`) +
        `</div>`;
    }).join("") + `</div>`;
    for (const button of listing.querySelectorAll(".tick")) {
      button.addEventListener("click", () => toggle(Number(button.dataset.id)));
    }
    wireDragging();
  };
  const toggle = async (id) => {
    const task = tasks.find((t) => t.id === id);
    if (!task) return;
    try {
      const moved = await api("POST", taskUrl(board.slug, id) + "/move", { lane: task.lane === "done" ? "todo" : "done" });
      tasks = tasks.map((t) => (t.id === id ? moved : t));
      show();
    } catch (err) { toast(err.message); }
  };

  // -- dragging a card ------------------------------------------------------
  // What the mouse has instead of the circle and the lane control, and the
  // same move the TUI's own drag ends in. The whole board comes back after
  // it rather than the one card: moving a card renumbers the lane it left
  // and the lane it landed in.
  let dragged = null;

  // Where in the lane it would go: the number of the *other* cards whose
  // middle is above the pointer. The server takes the card out before it
  // puts it back, so the card being dragged is not one of them.
  const indexAt = (lane, y) => [...lane.querySelectorAll(".row.task")]
    .filter((row) => Number(row.dataset.task) !== dragged)
    .filter((row) => {
      const box = row.getBoundingClientRect();
      return box.top + box.height / 2 < y;
    }).length;

  const moveTo = async (id, lane, index) => {
    try {
      await api("POST", taskUrl(board.slug, id) + "/move", { lane, index });
      tasks = await api("GET", boardUrl(board.slug) + "/tasks");
      show();
    } catch (err) { toast(err.message); }
  };

  function wireDragging() {
    if (!canDrag()) return;
    for (const row of listing.querySelectorAll(".row.task")) {
      row.addEventListener("dragstart", (event) => {
        dragged = Number(row.dataset.task);
        row.classList.add("dragging");
        event.dataTransfer.effectAllowed = "move";
        // Firefox starts no drag at all without something on the transfer.
        event.dataTransfer.setData("text/plain", row.dataset.task);
      });
      row.addEventListener("dragend", () => {
        dragged = null;
        row.classList.remove("dragging");
        for (const lane of listing.querySelectorAll(".over")) lane.classList.remove("over");
      });
    }
    for (const lane of listing.querySelectorAll(".lane")) {
      lane.addEventListener("dragover", (event) => {
        if (dragged === null) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        lane.classList.add("over");
      });
      lane.addEventListener("dragleave", (event) => {
        if (!lane.contains(event.relatedTarget)) lane.classList.remove("over");
      });
      lane.addEventListener("drop", (event) => {
        if (dragged === null) return;
        event.preventDefault();
        lane.classList.remove("over");
        moveTo(dragged, lane.dataset.lane, indexAt(lane, event.clientY));
      });
    }
  }

  show();

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const title = input.value.trim();
    if (!title) return;
    input.value = "";
    try {
      tasks.push(await api("POST", boardUrl(board.slug) + "/tasks", { title }));
      show();
    } catch (err) {
      input.value = title;
      toast(err.message);
    }
  });
  app.querySelector(".heading .compose").addEventListener("click", () => input.focus());
  app.querySelector(".new-board").addEventListener("click", newBoard);
}

// A board wants only a name, as a folder does in Notes. The new one opens
// as soon as it exists, with nothing on it yet.
async function newBoard() {
  const title = (prompt("Board name") || "").trim();
  if (!title) return;
  try {
    const made = await api("POST", "/api/boards", { title });
    replace("#/tasks/" + encodeURIComponent(made.slug));
    renderRoute();
  } catch (err) {
    toast(err.status === 409 ? "You already have a board called that" : err.message);
  }
}

// -- a task ---------------------------------------------------------------------
let editor = null;

async function renderTask(arg) {
  const slash = arg.lastIndexOf("/");
  const slug = arg.slice(0, slash);
  const id = Number(arg.slice(slash + 1));
  if (!boards.length) await loadBoards();
  const board = boards.find((b) => b.slug === slug);
  let task = null;
  if (board) {
    try { task = (await api("GET", boardUrl(slug) + "/tasks")).find((t) => t.id === id) || null; }
    catch (err) { if (err.status !== 404) throw err; }
  }
  if (!task) { toast("That task is gone"); replace("#/tasks"); return renderRoute(); }
  const ed = { slug, id, task, dirty: false, saving: false, pending: false, timer: null };
  editor = ed;
  const hold = {
    stays: (name, a) => name === "task" && a === arg,
    leave: () => leaveEditor(ed),
    flush: () => { if (ed.dirty) { clearTimeout(ed.timer); saveTask(ed, { keepalive: true }); } },
  };
  occupy(hold);

  const parent = "#/tasks/" + encodeURIComponent(slug);
  const lanes = LANES.map(([lane, label]) =>
    `<button type="button" role="radio" data-lane="${lane}"${lane === task.lane ? ' class="active" aria-checked="true"' : ' aria-checked="false"'}>${label}</button>`).join("");
  app.innerHTML = nav({
    back: parent, backLabel: board.title, title: task.title,
    right: `<button class="done strong" hidden>Done</button><button class="delete" aria-label="Delete task">${icons.trash}</button>`,
  }) + `
    <main>
      <div class="editor">
        <input class="title" placeholder="Title" value="${esc(task.title)}" autocapitalize="sentences" enterkeyhint="next">
        <p class="stamp"><span class="when">${esc(formatDate(seconds(task.updated_at) || Date.now() / 1000, { long: true }))}</span><span class="status"></span></p>
        <div class="lanes" role="radiogroup" aria-label="Lane">${lanes}</div>
        <textarea class="body" placeholder="Notes, and subtasks as “- [ ]” lines…" rows="1">${esc(task.body)}</textarea>
      </div>
    </main>`;
  wireShell();
  app.querySelector(".nav").classList.add("lined");

  const titleEl = ed.titleEl = app.querySelector(".title");
  const bodyEl = ed.bodyEl = app.querySelector(".body");
  ed.statusEl = app.querySelector(".stamp .status");
  const done = app.querySelector(".done");
  const del = app.querySelector(".delete");
  const box = app.querySelector(".editor");

  const grow = ed.grow = () => { bodyEl.style.height = "auto"; bodyEl.style.height = bodyEl.scrollHeight + "px"; };
  grow();
  addEventListener("resize", grow);

  const changed = () => {
    ed.dirty = true;
    setStatus(ed, "");
    clearTimeout(ed.timer);
    ed.timer = setTimeout(() => saveTask(ed), SAVE_DELAY);
  };
  bodyEl.addEventListener("input", () => { grow(); changed(); });
  titleEl.addEventListener("input", changed);
  titleEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); bodyEl.focus(); bodyEl.setSelectionRange(0, 0); }
  });
  box.addEventListener("click", (event) => {
    if (event.target === box) { bodyEl.focus(); bodyEl.setSelectionRange(bodyEl.value.length, bodyEl.value.length); }
  });
  box.addEventListener("focusin", (event) => {
    if (event.target === titleEl || event.target === bodyEl) { done.hidden = false; del.hidden = true; }
  });
  box.addEventListener("focusout", () => {
    setTimeout(() => {
      if (!box.contains(document.activeElement)) { done.hidden = true; del.hidden = false; }
    }, 0);
    if (ed.dirty) { clearTimeout(ed.timer); saveTask(ed); }
  });
  done.addEventListener("click", () => document.activeElement && document.activeElement.blur());
  for (const button of app.querySelectorAll(".lanes button")) {
    button.addEventListener("click", async () => {
      const lane = button.dataset.lane;
      if (lane === ed.task.lane) return;
      try {
        ed.task = await api("POST", taskUrl(slug, id) + "/move", { lane });
      } catch (err) { toast(err.message); return; }
      for (const other of app.querySelectorAll(".lanes button")) {
        const on = other.dataset.lane === lane;
        other.classList.toggle("active", on);
        other.setAttribute("aria-checked", String(on));
      }
    });
  }
  del.addEventListener("click", async () => {
    if (!confirm(`Delete “${ed.task.title}”?`)) return;
    try {
      clearTimeout(ed.timer);
      ed.dirty = false;
      await api("DELETE", taskUrl(slug, id));
      vacate(hold);
      editor = null;
      back(parent);
    } catch (err) { toast(err.message); }
  });
}

async function saveTask(ed, { keepalive = false } = {}) {
  if (!ed.dirty) return;
  if (ed.saving) { ed.pending = true; return; }
  ed.dirty = false;
  ed.saving = true;
  setStatus(ed, "Saving…");
  try {
    // A task with no title keeps the one it had.
    const title = ed.titleEl.value.trim() || ed.task.title;
    ed.task = await api("PATCH", taskUrl(ed.slug, ed.id), { title, body: ed.bodyEl.value }, { keepalive });
    const center = app.querySelector(".nav .center .text");
    if (center && editor === ed) center.textContent = ed.task.title;
    setStatus(ed, "Saved");
  } catch (err) {
    ed.dirty = true;
    setStatus(ed, "Not saved", true);
    if (err.status !== 401) toast(err.message);
  } finally {
    ed.saving = false;
    if (ed.pending) { ed.pending = false; ed.dirty = true; saveTask(ed); }
  }
}

async function leaveEditor(ed) {
  if (editor === ed) editor = null;
  clearTimeout(ed.timer);
  removeEventListener("resize", ed.grow);
  if (ed.dirty) await saveTask(ed);
  while (ed.saving) await new Promise((r) => setTimeout(r, 50));
}

// -- what this feature adds to the app ---------------------------------------------
registerScreen("tasks", renderTasks);
registerScreen("task", renderTask);
registerTab({
  name: "tasks", label: "Tasks", icon: pixelIcon("tasks"), feature: "tasks",
  href: () => "#/tasks",
});
onSignOut(() => { boards = []; });
