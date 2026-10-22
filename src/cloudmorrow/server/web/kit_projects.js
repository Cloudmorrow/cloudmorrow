/* Secrets as .env files, in the web app: a list of projects, and a list of
   secrets.

   A `list` screen that binds `vault` is projects (docs/QUILLS.md): each
   record names the vault its secrets are in, and `env_files` which file each
   environment was read from. Its record sheet gets a section with the
   vault's environments: each one's keys counted, its file named, a button
   to save it as that file, and one to read a .env file into it. Folders and
   git are a computer's (`cm <quill> update`), which the section says.

   A `list` of the foundational `secret` datamodel gets the same two buttons
   for the vault and environment on screen.

   Which file is which environment is the rule the command line follows
   (cloudmorrow/checkout.py): `.env.<name>` is `<name>`, `.env` is `local`,
   and an example or a template is not one. A value is never drawn here: it
   goes up in the file you picked and comes down in the file you save. */

import { api, apiRaw, esc, toast } from "./core.js";
import { askText } from "./dialog.js";
import { mayWrite } from "./kit.js";

const EXAMPLES = new Set(["example", "examples", "sample", "template", "dist", "defaults", "schema"]);
const NAME = /^[a-z0-9][a-z0-9._-]{0,31}$/;

/** Which environment a file of this name is, or null. */
export function environmentOf(name) {
  if (name === ".env") return "local";
  if (!name.startsWith(".env.")) return null;
  const rest = name.slice(5).toLowerCase();
  if (!rest || rest.split(".").some((part) => EXAMPLES.has(part)) || !NAME.test(rest)) return null;
  return rest;
}

/** The file an environment is saved as: the one it was read from, else `.env` or `.env.<it>`. */
export const fileFor = (environment, files = {}) =>
  files[environment] || (environment === "local" ? ".env" : `.env.${environment}`);

const vaultQuery = (vault, rest = "") => `?vault=${encodeURIComponent(vault)}${rest}`;

/** Every environment of a vault that holds something, with how many keys. */
export const environmentsOf = (vault) => api("GET", "/api/secrets/environments" + vaultQuery(vault));

/** Pick a .env file and read it into an environment: the one given, or the one its name says. */
export function importEnv(vault, environment = "") {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.addEventListener("change", async () => {
      const file = input.files && input.files[0];
      if (!file) { resolve(null); return; }
      let into = environment || environmentOf(file.name);
      if (!into) into = ((await askText(`Which environment is ${file.name}?`)) || "").trim().toLowerCase();
      if (!into) { resolve(null); return; }
      try {
        const result = await api("POST", "/api/secrets/import" + vaultQuery(vault),
          { text: await file.text(), environment: into });
        const changed = result.added.length + result.updated.length;
        toast(changed ? `${changed} ${changed === 1 ? "key" : "keys"} into ${into}` : `${into} had all of it already`);
        resolve({ environment: into, file: file.name, result });
      } catch (err) { toast(err.message); resolve(null); }
    });
    input.click();
  });
}

/** Save an environment as a .env file. */
export async function exportEnv(vault, environment, filename) {
  try {
    const res = await apiRaw("GET", "/api/secrets/export" + vaultQuery(vault, `&env=${encodeURIComponent(environment)}`));
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) { toast(err.message); }
}

/** A project's vault: the field, else its name made one, as checkout.py does. */
export function vaultOf(screen, model, record) {
  const set = String(record.fields[screen.vault] || "");
  if (set) return set;
  const name = String(record.fields[screen.title || model.title] || "").toLowerCase();
  return name.replace(/[^a-z0-9._-]+/g, "-").replace(/^[-._]+|[-._]+$/g, "").slice(0, 32).replace(/[-._]+$/, "") || "project";
}

// -- the project's sheet ---------------------------------------------------------------
/** What a list of projects adds to its record sheet (kit.js's SHEETS). */
export function projectsSheet(at, model) {
  const { screen } = at;
  if (!screen.vault || model.id !== screen.model) return null;
  return { section: (slot, record) => fillProject(at, model, record, slot) };
}

async function fillProject(at, model, record, slot) {
  const { screen, quill } = at;
  const vault = vaultOf(screen, model, record);
  const files = (screen.env_files && record.fields[screen.env_files]) || {};
  const writes = mayWrite(model);
  // The Quill's list of secrets, when it has one: each environment opens there.
  const secrets = (quill.screens || []).find((s) => s.model === "secret" && s.kit === "list");
  const draw = async () => {
    let found = [];
    try { found = await environmentsOf(vault); } catch (err) { slot.innerHTML = `<p class="data-note">${esc(err.message)}</p>`; return; }
    const row = (e) => {
      const name = e.environment;
      const title = secrets
        ? `<a class="title" href="#/q/${esc(quill.id)}/${esc(secrets.id)}/${encodeURIComponent(vault)}/${encodeURIComponent(name)}">${esc(name)}</a>`
        : `<span class="title">${esc(name)}</span>`;
      return `<div class="row project-env"><span class="main">${title}` +
        `<span class="meta"><span class="preview">${e.secrets} ${e.secrets === 1 ? "key" : "keys"} · ${esc(fileFor(name, files))}</span></span></span>` +
        `<button type="button" class="chip env-save" data-env="${esc(name)}">Save</button></div>`;
    };
    const command = `cm ${quill.id}`;
    slot.innerHTML = `<p class="group-label">Secrets · vault ${esc(vault)}</p>
      ${found.length ? `<div class="group kit-list">${found.map(row).join("")}</div>`
        : `<p class="data-note">Nothing in it yet. Read a .env file in, or run <code>${esc(command)} init</code> in the project's folder.</p>`}
      ${writes ? `<p><button type="button" class="chip env-import">Import .env</button></p>` : ""}
      <p class="data-note">On a computer: <code>${esc(command)} update</code> in the folder pulls it and writes these files,
        <code>${esc(command)} clone ${esc(vault)}</code> puts it on a new one.</p>`;
    for (const button of slot.querySelectorAll(".env-save")) {
      button.addEventListener("click", () => exportEnv(vault, button.dataset.env, fileFor(button.dataset.env, files)));
    }
    const add = slot.querySelector(".env-import");
    if (add) add.addEventListener("click", async () => {
      const done = await importEnv(vault);
      if (!done) return;
      // Which file it was, for saving it back under the same name.
      if (screen.env_files && files[done.environment] !== done.file) {
        files[done.environment] = done.file;
        try {
          const now = await api("GET", `/api/records/${encodeURIComponent(model.id)}/${encodeURIComponent(record.id)}`);
          await api("PATCH", `/api/records/${encodeURIComponent(model.id)}/${encodeURIComponent(record.id)}`,
            { fields: { [screen.env_files]: { ...(now.fields[screen.env_files] || {}), [done.environment]: done.file } }, rev: now.rev });
        } catch { /* the file name is a nicety; the secrets are in */ }
      }
      draw();
    });
  };
  await draw();
}

// -- a list of secrets -------------------------------------------------------------------
/** The buttons over a list of the foundational `secret`: the environment on screen, out as a file and in from one. */
export function secretsBar(model, writes) {
  if (model.id !== "secret") return "";
  return `<div class="secrets-bar">` +
    (writes ? `<button type="button" class="chip env-import">Import .env</button>` : "") +
    `<button type="button" class="chip env-save">Export .env</button></div>`;
}

/** Wire secretsBar's buttons. The vault and environment are the levels the
    list stands on, the server's defaults where it stands on none. */
export function wireSecretsBar(root, levels, chosen, after) {
  const add = root.querySelector(".secrets-bar .env-import");
  const save = root.querySelector(".secrets-bar .env-save");
  if (!add && !save) return;
  const at = (name, fallback) => {
    const i = levels.findIndex((f) => f.name === name);
    return (i >= 0 && chosen[i]) || fallback;
  };
  const where = () => ({ vault: at("vault", "default"), environment: at("environment", "local") });
  if (add) add.addEventListener("click", async () => {
    const { vault, environment } = where();
    if (await importEnv(vault, environment)) after();
  });
  if (save) save.addEventListener("click", () => {
    const { vault, environment } = where();
    exportEnv(vault, environment, fileFor(environment));
  });
}
