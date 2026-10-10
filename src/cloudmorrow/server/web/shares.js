/* Fileshares in the app: making one, and who has it.

   A share is a folder on the server with a name. Anybody makes one, and it
   is theirs: the folder of that name in the Shares folder there, shared
   with the people and circles they pick — each to change what is in it, or
   only to read it. An administrator may also share with everybody, and
   point a share at another directory on the server, which is checked as it
   is typed: what cannot be shared is said, and so is what is wrong with
   its permissions, before anything is made.

   The Files Quill draws the shares, with the kit's grid; this adds to that
   list through `registerGridHook` — a New share button above it, and under
   each share whose it is and who has it, which opens the share's own page.
   It knows the core's `share` datamodel and the `/api/shares` routes, and
   nothing of the Quill.

     #/share           a new share
     #/share/<name>    one share: whose, who has it, where it is */

import {
  api, app, back, esc, nav, previousHash, registerScreen, replace, renderRoute, session, toast, wireShell,
} from "./core.js";
import { registerGridHook } from "./kit_grid.js";

const shareUrl = (name, rest = "") => "/api/shares/" + encodeURIComponent(name) + rest;
// What somebody may do in a share, as the menus say it.
const ACCESS = [["", "Not shared"], ["write", "Can change"], ["read", "Can read"]];
const accessSaid = (access) => (access === "read" ? "can read" : "can change");

/** Where Back goes: wherever we came from, else Files. */
const backTo = () => previousHash() || "#/";

/** Who a share is shared with, in a few words. */
function sharedWith(share) {
  const members = share.members || [];
  if (!members.length) return "Not shared with anybody yet";
  return "Shared with " + members.map((m) => m.label || m.who).join(", ");
}

// -- under each share in the Files list ---------------------------------------------------
registerGridHook({
  async groups({ model }) {
    if (model.id !== "share") return null;
    return {
      top: () => `<div class="group share-new"><a class="row primary" href="#/share">New share</a></div>`,
      after: (share) => {
        if (share.fields.kind === "drive") return "";
        const mine = share.fields.can_manage;
        const words = mine
          ? (share.fields.shared_with ? `Shared with ${share.fields.shared_with}` : "Only you so far")
          : `${share.fields.owner}'s — you ${accessSaid(share.fields.access)}`;
        return `<a class="row share-who" href="#/share/${encodeURIComponent(share.id)}">
          <span class="main"><span class="meta"><span class="preview">${esc(words)}</span></span></span>
          <span class="said">${mine ? "Sharing" : "Details"}</span></a>`;
      },
    };
  },
});

// -- who to share with: one menu per person, circle, and everybody --------------------------
/** The rows of menus, each set to what *members* give. */
function whoRows(candidates, members = []) {
  const given = new Map(members.map((m) => [`${m.kind}:${String(m.who).toLowerCase()}`, m.access]));
  const menu = (kind, who, label, detail = "") => {
    const chosen = given.get(`${kind}:${String(who).toLowerCase()}`) || "";
    return `<label class="row who-row">
      <span class="main"><span class="title">${esc(label)}</span>${
        detail ? `<span class="meta"><span class="preview">${esc(detail)}</span></span>` : ""}</span>
      <select data-kind="${esc(kind)}" data-who="${esc(who)}" aria-label="${esc(label)}">${ACCESS.map(([value, said]) =>
        `<option value="${value}"${value === chosen ? " selected" : ""}>${said}</option>`).join("")}</select>
    </label>`;
  };
  const everyone = candidates.everyone
    ? `<p class="group-label">Everybody</p><div class="group">${
      menu("everyone", "*", "Everybody on this server", "Today's accounts and every one made later")}</div>` : "";
  const circles = (candidates.circles || []).length
    ? `<p class="group-label">Circles</p><div class="group">${candidates.circles.map((c) =>
      menu("circle", c.id, c.name, "Whoever is in it, now and later")).join("")}</div>` : "";
  const people = `<p class="group-label">People</p><div class="group">${(candidates.people || []).map((p) =>
    menu("user", p.username, p.display_name || p.username, p.display_name && p.display_name !== p.username ? p.username : ""))
    .join("") || `<p class="empty"><b>Nobody else yet</b>You can share with people once they have accounts.</p>`}</div>`;
  return everyone + circles + people;
}

/** What the menus say, as members. */
function chosenMembers(root) {
  return [...root.querySelectorAll("select[data-kind]")]
    .filter((s) => s.value)
    .map((s) => ({ kind: s.dataset.kind, who: s.dataset.who, access: s.value }));
}

/** Errors in red, warnings in amber: what is said about a directory. */
function notes(errors = [], warnings = []) {
  return errors.map((e) => `<p class="note bad">${esc(e)}</p>`).join("") +
    warnings.map((w) => `<p class="note warn">${esc(w)}</p>`).join("");
}

// -- a new share --------------------------------------------------------------------------
async function renderNewShare() {
  const candidates = await api("GET", "/api/shares/candidates");
  const admin = !!candidates.everyone;
  const directory = String(candidates.directory || "").replace(/\/+$/, "");
  const defaultPath = (name) => (directory && name ? `${directory}/${name}` : "");
  app.innerHTML = nav({ back: backTo(), backLabel: "Files", title: "New share" }) + `
    <main>
      <h1 class="large">New share</h1>
      <form class="share-form">
        <div class="group">
          <label class="row"><input name="name" placeholder="Name — lowercase, digits and dashes"
            aria-label="Name" autocapitalize="none" autocorrect="off" spellcheck="false" required></label>
          <label class="row"><input name="description" placeholder="What is in it (optional)" aria-label="Description"></label>
        </div>
        <p class="hint">A folder on the server, yours. Whoever you share it with sees it beside their own files,
          and mounts it by this name.</p>
        ${admin ? `<p class="group-label">Where on the server</p>
        <div class="group"><label class="row"><input name="path" aria-label="Directory on the server"
          placeholder="${esc(directory ? directory + "/…" : "/srv/…")}" autocapitalize="none" spellcheck="false"></label></div>
        <p class="hint">Its own folder in the Shares folder unless you change it. Change it to share a directory
          elsewhere on the server; it is checked as you type.</p>
        <div class="path-notes share-notes"></div>` : ""}
        ${whoRows(candidates)}
        <div class="group"><button class="row primary" type="submit">Make the share</button></div>
      </form>
    </main>`;
  wireShell();
  const form = app.querySelector("form.share-form");
  const nameInput = form.elements.name;
  const pathInput = form.elements.path;
  let pathTyped = false;
  let checking = 0;
  const check = async () => {
    if (!pathInput) return;
    const name = nameInput.value.trim().toLowerCase();
    const path = pathInput.value.trim();
    const shown = form.querySelector(".path-notes");
    if (!path || path === defaultPath(name)) { shown.innerHTML = ""; return; }
    const mine = ++checking;
    try {
      const found = await api("GET", "/api/shares/check?path=" + encodeURIComponent(path));
      if (mine === checking) shown.innerHTML = notes(found.errors, found.warnings);
    } catch (err) {
      if (mine === checking) shown.innerHTML = notes([err.message]);
    }
  };
  let timer = 0;
  nameInput.addEventListener("input", () => {
    if (pathInput && !pathTyped) pathInput.value = defaultPath(nameInput.value.trim().toLowerCase());
  });
  if (pathInput) {
    pathInput.addEventListener("input", () => {
      pathTyped = true;
      clearTimeout(timer);
      timer = setTimeout(check, 400);
    });
  }
  nameInput.focus();
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = nameInput.value.trim().toLowerCase();
    if (!name) return;
    const path = pathInput ? pathInput.value.trim() : "";
    const body = {
      name,
      description: form.elements.description.value.trim(),
      members: chosenMembers(form),
    };
    if (path && path !== defaultPath(name)) body.path = path;
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      const share = await api("POST", "/api/shares", body);
      toast(share.warnings && share.warnings.length ? `Made ${share.name} — check its folder` : `Made ${share.name}`,
        share.warnings && share.warnings.length ? 5000 : 2200);
      replace("#/share/" + encodeURIComponent(share.name));
      return renderRoute();
    } catch (err) {
      button.disabled = false;
      toast(err.message, 6000);
    }
  });
}

// -- one share ----------------------------------------------------------------------------
async function renderShare(name) {
  let share;
  try { share = await api("GET", shareUrl(name)); }
  catch (err) {
    if (err.status !== 404) throw err;
    toast(`There is no share called ${name}`);
    replace("#/");
    return renderRoute();
  }
  const mine = share.can_manage;
  const candidates = mine ? await api("GET", "/api/shares/candidates") : null;
  const admin = !!(candidates && candidates.everyone);
  const byName = (share.members || []).some((m) => m.kind === "user" && m.who === session.user);
  const whose = mine ? "Yours" : `${share.owner}'s — you ${accessSaid(share.access)}`;
  app.innerHTML = nav({ back: backTo(), backLabel: "Files", title: share.name }) + `
    <main>
      <h1 class="large">${esc(share.name)}</h1>
      <div class="group facts">
        <div class="row"><span class="main">Whose</span><span class="said">${esc(whose)}</span></div>
        ${share.description ? `<div class="row"><span class="main">About</span><span class="said">${esc(share.description)}</span></div>` : ""}
        <div class="row"><span class="main">Mount at</span><span class="value">${esc(share.url)}</span></div>
        ${share.path ? `<div class="row"><span class="main">On the server</span><span class="value">${esc(share.path)}</span></div>` : ""}
      </div>
      <div class="share-notes">${notes([], share.warnings)}</div>
      ${mine ? `<form class="share-form">
        ${whoRows(candidates, share.members)}
        <p class="hint">A change is made as you choose it. Nobody is asked to accept.</p>
        ${admin ? `<p class="group-label">Where on the server</p>
        <div class="group"><label class="row"><input name="path" value="${esc(share.path)}"
          aria-label="Directory on the server" autocapitalize="none" spellcheck="false"></label></div>
        <div class="path-notes share-notes"></div>
        <div class="group"><button class="row" type="button" data-move>Move it there</button></div>
        <p class="hint">Files are not moved: the share is pointed at the directory you give. Empty puts it back
          in its own folder in the Shares folder.</p>` : ""}
        <div class="group"><button class="row bad" type="button" data-remove>Remove the share</button></div>
      </form>` : `<p class="group-label">Shared with</p>
      <div class="group">${(share.members || []).map((m) =>
        `<div class="row"><span class="main">${esc(m.label || m.who)}</span><span class="said">${esc(accessSaid(m.access))}</span></div>`)
        .join("")}</div>
      ${byName ? `<div class="group"><button class="row bad" type="button" data-leave>Leave it</button></div>` : ""}`}
    </main>`;
  wireShell();
  const form = app.querySelector("form.share-form");
  if (form) {
    for (const select of form.querySelectorAll("select[data-kind]")) {
      select.addEventListener("change", async () => {
        const { kind, who } = select.dataset;
        try {
          if (select.value) {
            await api("PUT", shareUrl(share.name, "/members"), { kind, who, access: select.value });
          } else {
            await api("DELETE", shareUrl(share.name, `/members/${encodeURIComponent(kind)}/${encodeURIComponent(who)}`));
          }
          toast("Saved");
        } catch (err) {
          toast(err.message, 6000);
          return renderRoute();
        }
      });
    }
    const pathInput = form.elements.path;
    if (pathInput) {
      let timer = 0;
      pathInput.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(async () => {
          const path = pathInput.value.trim();
          const shown = form.querySelector(".path-notes");
          if (!path || path === share.path) { shown.innerHTML = ""; return; }
          try {
            const found = await api("GET", `/api/shares/check?path=${encodeURIComponent(path)}&share=${encodeURIComponent(share.name)}`);
            shown.innerHTML = notes(found.errors, found.warnings);
          } catch (err) { shown.innerHTML = notes([err.message]); }
        }, 400);
      });
      form.querySelector("[data-move]").addEventListener("click", async () => {
        try {
          await api("PATCH", shareUrl(share.name), { path: pathInput.value.trim() });
          toast("Moved");
          return renderRoute();
        } catch (err) { toast(err.message, 6000); }
      });
    }
    form.querySelector("[data-remove]").addEventListener("click", async () => {
      const others = (share.members || []).length ? ` Whoever it is shared with loses it too.` : "";
      if (!confirm(`Remove ${share.name}? Its files stay on the server.${others}`)) return;
      try {
        await api("DELETE", shareUrl(share.name));
        toast(`Removed ${share.name}`);
        back(backTo());
      } catch (err) { toast(err.message, 6000); }
    });
  }
  const leave = app.querySelector("[data-leave]");
  if (leave) {
    leave.addEventListener("click", async () => {
      if (!confirm(`Leave ${share.name}? ${share.owner} can share it with you again.`)) return;
      try {
        await api("DELETE", shareUrl(share.name, `/members/user/${encodeURIComponent(session.user)}`));
        toast(`Left ${share.name}`);
        back(backTo());
      } catch (err) { toast(err.message, 6000); }
    });
  }
}

registerScreen("share", (arg) => (arg ? renderShare(arg) : renderNewShare()));
