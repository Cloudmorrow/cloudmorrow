/* Flows: when something happens, do these steps (docs/FLOWS.md).

   A flow is yours: a trigger and a list of steps, saved as a `flow` record
   and run as you, over the data your circles let you reach. The list of
   steps is linear and reorderable; a step may be told to run only when
   something gathered so far — an approval's answer, most often — says so,
   which is how a straight list still branches.

   The screen builds from what the server already knows: the datamodels
   for triggers and set/create steps, every installed Quill's actions with
   their forms for action steps, the roles for approval steps. Anything
   typed in a step may hold {{a.path}} into what the run has gathered. */

import {
  api, app, esc, mount, nav, recordsUrl, registerScreen, renderRoute, replace, toast, wireShell,
} from "./core.js";
import { ask } from "./dialog.js";

/** The row that leads here, for Me. */
export function flowsRow() {
  return `<div class="group"><a class="row flows-link" href="#/flows">
    <span class="main"><span class="title">Flows</span>
    <span class="meta"><span class="preview">When something happens, do these steps: ask a role, press a Quill's action, change a record</span></span></span>
    </a></div>`;
}

const KINDS = [
  ["action", "Press a Quill's action"],
  ["approval", "Ask a role for a yes or a no"],
  ["set", "Change a record"],
  ["create", "Make a record"],
  ["notify", "Tell somebody"],
  ["wait", "Wait"],
  ["stop", "Stop here"],
];
const KIND_LABEL = Object.fromEntries(KINDS);
const WHEN = [["created", "is made"], ["changed", "changes"], ["deleted", "is deleted"]];

/** "When a leave is made", for a row's second line. */
export function triggerSaid(trigger, labels = {}) {
  if (!trigger) return "Never";
  if (trigger.kind === "record") {
    const when = Array.isArray(trigger.when) ? trigger.when : [trigger.when || "created"];
    const said = when.map((w) => (WHEN.find(([k]) => k === w) || [w, w])[1]).join(" or ");
    let out = `When a ${labels[trigger.model] || trigger.model} ${said}`;
    if (trigger.field) out += ` (${trigger.field}${"value" in trigger && trigger.value !== "" ? ` = ${trigger.value}` : ""})`;
    return out;
  }
  if (trigger.kind === "action") return `When ${trigger.quill} · ${trigger.action} is pressed`;
  if (trigger.kind === "schedule") return `Every ${trigger.every}`;
  return "By hand";
}

// -- the list ------------------------------------------------------------------------------------
async function renderFlows() {
  const [flows, models] = await Promise.all([api("GET", recordsUrl("flow")), api("GET", "/api/datamodels")]);
  const labels = Object.fromEntries(models.map((m) => [m.id, (m.label || m.id).toLowerCase()]));
  mount(nav({ back: "#/me", backLabel: "Me", title: "Flows" }) + `
    <main class="flows">
      <h1 class="large">Flows</h1>
      <p class="note">A flow runs as you, over what you may reach, when its trigger fires.
        Each step may wait for an answer, and later steps may run only on one answer or the other.</p>
      <div class="group">${flows.length ? flows.map((flow) => `
        <a class="row flow-row" href="#/flow/${encodeURIComponent(flow.id)}">
          <span class="main"><span class="title">${esc(flow.fields.name)}</span>
          <span class="meta"><span class="preview">${esc(triggerSaid(flow.fields.trigger, labels))} · ${
            (flow.fields.steps || []).length} step${(flow.fields.steps || []).length === 1 ? "" : "s"}</span></span></span>
          ${flow.fields.on === false ? `<span class="role-chip">Off</span>` : ""}</a>`).join("")
        : `<p class="empty">No flows yet.</p>`}</div>
      <div class="group"><a class="row primary" href="#/flow/new">New flow</a></div>
    </main>`);
  wireShell();
}

// -- one flow ------------------------------------------------------------------------------------
const option = (value, label, chosen) =>
  `<option value="${esc(value)}"${String(value) === String(chosen) ? " selected" : ""}>${esc(label)}</option>`;
const select = (name, options, chosen, { blank = "" } = {}) =>
  `<select data-name="${esc(name)}">${blank ? option("", blank, chosen) : ""}${options.map(([v, l]) => option(v, l, chosen)).join("")}</select>`;
const input = (name, value, placeholder = "") =>
  `<input data-name="${esc(name)}" value="${esc(value == null ? "" : typeof value === "object" ? JSON.stringify(value) : value)}" placeholder="${esc(placeholder)}">`;
const field = (label, control) => `<label class="row"><span class="main">${esc(label)}</span>${control}</label>`;

/** What the run has gathered that a step may read, as the hint under a step. */
function hints(flow, index, models) {
  const out = ["owner", "now"];
  const t = flow.trigger || {};
  if (t.kind === "record" || t.kind === "manual") {
    out.push("trigger.record.id", "trigger.record.owner");
    const model = models.find((m) => m.id === t.model);
    for (const f of (model && model.fields) || []) out.push(`trigger.record.fields.${f.name}`);
  }
  if (t.kind === "action") out.push("trigger.by", "trigger.record.id", "trigger.result.<key>");
  for (const step of flow.steps.slice(0, index)) {
    if (step.kind === "approval") out.push("approval.status", "approval.note", "approval.by");
    if (step.kind === "action") out.push(`steps.${step.id}.<key>`);
    if (step.kind === "create" || step.kind === "set") out.push(`steps.${step.id}.id`);
  }
  return out;
}

function stepBody(step, flow, index, { models, quills, roles }) {
  const modelOptions = models.map((m) => [m.id, m.label || m.id]);
  switch (step.kind) {
    case "action": {
      const quill = quills.find((q) => q.id === step.quill);
      const actions = quill ? quill.actions || [] : [];
      const action = actions.find((a) => a.id === step.action);
      return field("Quill", select("quill", quills.map((q) => [q.id, q.name]), step.quill, { blank: "Which Quill?" }))
        + field("Action", select("action", actions.map((a) => [a.id, a.label]), step.action, { blank: "Which action?" }))
        + (action && action.on ? field(`Which ${action.on}`, input("record", step.record, "{{trigger.record.id}}")) : "")
        + (action ? action.fields.map((f) =>
          field(f.label + (f.required ? " *" : ""), input(`fields.${f.name}`, (step.fields || {})[f.name], f.kind))).join("") : "");
    }
    case "approval":
      return field("Ask", select("role", roles.map((r) => [r.id, r.name]), step.role, { blank: "Which role?" }))
        + field("Question", input("question", step.question, "Approve {{trigger.record.fields.title}}?"))
        + field("In circle", input("circle", step.circle, "optional"))
        + field("Due", input("due", step.due, "optional: a date, or {{…}}"));
    case "set":
      return field("Datamodel", select("model", modelOptions, step.model, { blank: "Which datamodel?" }))
        + field("Record", input("record", step.record, "{{trigger.record.id}}"))
        + fieldsOf(step, models.find((m) => m.id === step.model));
    case "create":
      return field("Datamodel", select("model", modelOptions, step.model, { blank: "Which datamodel?" }))
        + fieldsOf(step, models.find((m) => m.id === step.model));
    case "notify":
      return field("To", input("to", step.to, "a username, or {{trigger.record.owner}}"))
        + field("Or a role", select("role", roles.map((r) => [r.id, r.name]), step.role, { blank: "nobody by role" }))
        + field("Title", input("title", step.title, "What happened"))
        + field("Body", input("body", step.body, "optional"));
    case "wait":
      return field("For", input("for", step.for, "1d, 2h, 30m"))
        + field("Or until", input("until", step.until, "{{trigger.record.fields.starts}}"));
    default:
      return "";
  }
}

/** A row per field of the datamodel a set or create step writes, with its template. */
function fieldsOf(step, model) {
  if (!model) return "";
  const values = step.fields || {};
  return model.fields.filter((f) => !f.added_by || values[f.name] !== undefined).map((f) =>
    field(f.label + (f.required && step.kind === "create" ? " *" : ""),
      input(`fields.${f.name}`, values[f.name], f.kind === "enum" ? f.values.join(" | ") : f.kind))).join("");
}

function conditionRow(step, flow, index, models) {
  const c = step.only_if || {};
  const op = "equals" in c ? "equals" : "not_equals" in c ? "not_equals" : "";
  return `<div class="row condition">
    <span class="main">Only if</span>
    <input data-name="only_if.path" list="hints-${index}" value="${esc(c.path || "")}" placeholder="approval.status">
    ${select("only_if.op", [["", "always"], ["equals", "is"], ["not_equals", "is not"]], op)}
    <input data-name="only_if.value" value="${esc(c[op] == null ? "" : c[op])}" placeholder="approved">
    <datalist id="hints-${index}">${hints(flow, index, models).map((h) => `<option value="${esc(h)}">`).join("")}</datalist>
  </div>`;
}

function stepCard(step, flow, index, data) {
  return `<section class="group step" data-index="${index}" draggable="true">
    <div class="row step-head">
      <span class="grip" aria-hidden="true">⋮⋮</span>
      <span class="main"><span class="title">${index + 1}. ${esc(KIND_LABEL[step.kind] || step.kind)}</span>
      <span class="meta"><span class="preview">id ${esc(step.id)}</span></span></span>
      <button type="button" class="act-chip" data-move="-1" aria-label="Move up">↑</button>
      <button type="button" class="act-chip" data-move="1" aria-label="Move down">↓</button>
      <button type="button" class="act-chip danger" data-remove aria-label="Remove">×</button>
    </div>
    ${field("Kind", select("kind", KINDS, step.kind))}
    ${stepBody(step, flow, index, data)}
    ${step.kind === "stop" ? "" : conditionRow(step, flow, index, data.models)}
  </section>`;
}

function triggerBody(trigger, { models, quills }) {
  const kind = trigger.kind || "record";
  let out = field("Starts", select("kind", [
    ["record", "When a record is made or changes"], ["action", "When a Quill's action is pressed"],
    ["schedule", "On a schedule"], ["manual", "By hand only"]], kind));
  if (kind === "record") {
    const model = models.find((m) => m.id === trigger.model);
    const when = Array.isArray(trigger.when) ? trigger.when[0] : trigger.when || "created";
    out += field("Datamodel", select("model", models.map((m) => [m.id, m.label || m.id]), trigger.model, { blank: "Which datamodel?" }))
      + field("When it", select("when", WHEN, when));
    if (when === "changed" && model) {
      out += field("Field", select("field", model.fields.map((f) => [f.name, f.label || f.name]), trigger.field, { blank: "any field" }))
        + field("Becomes", input("value", trigger.value, "optional: approved"));
    }
  } else if (kind === "action") {
    const quill = quills.find((q) => q.id === trigger.quill);
    out += field("Quill", select("quill", quills.map((q) => [q.id, q.name]), trigger.quill, { blank: "Which Quill?" }))
      + field("Action", select("action", ((quill && quill.actions) || []).map((a) => [a.id, a.label]), trigger.action, { blank: "Which action?" }));
  } else if (kind === "schedule") {
    out += field("Every", input("every", trigger.every || "1d", "1d, 1h, 1w"));
  }
  return out;
}

function runRow(run) {
  const f = run.fields;
  const colour = { done: "ok", failed: "bad", waiting: "warn" }[f.status] || "";
  return `<div class="row run-row">
    <span class="main"><span class="title">${esc((f.started_at || run.created_at || "").slice(0, 16).replace("T", " "))}</span>
    <span class="meta"><span class="preview">step ${f.step || 0}${f.error ? " · " + esc(f.error) : ""}${
      f.status === "waiting" && f.waiting_on ? " · waiting for an answer" : ""}</span></span></span>
    <span class="role-chip ${colour}">${esc(f.status)}</span></div>`;
}

async function renderFlow(id) {
  const making = !id || id === "new";
  const [models, quills, roles] = await Promise.all([
    api("GET", "/api/datamodels"), api("GET", "/api/quills"), api("GET", "/api/roles"),
  ]);
  const usable = quills.filter((q) => q.available !== false && (q.actions || []).length);
  const data = { models: models.filter((m) => !["flow", "flow_run"].includes(m.id)), quills: usable, roles };
  let record = null;
  let flow = { name: "", on: true, trigger: { kind: "record", when: ["created"] }, steps: [] };
  let runs = [];
  if (!making) {
    try {
      [record, runs] = await Promise.all([api("GET", recordsUrl("flow", id)), api("GET", recordsUrl("flow_run") + "?flow=" + encodeURIComponent(id) + "&_last=20")]);
    } catch {
      toast("No such flow");
      replace("#/flows");
      return renderRoute();
    }
    flow = { name: record.fields.name, on: record.fields.on !== false, trigger: record.fields.trigger || {}, steps: record.fields.steps || [], description: record.fields.description || "" };
  }
  let nextId = flow.steps.length + 1;
  const freshId = () => {
    let candidate;
    do candidate = `step${nextId++}`; while (flow.steps.some((s) => s.id === candidate));
    return candidate;
  };

  const draw = () => {
    mount(nav({ back: "#/flows", backLabel: "Flows", title: making ? "New flow" : flow.name || "Flow" }) + `
      <main class="flows flow-editor">
        <h1 class="large">${esc(making ? "New flow" : flow.name || "Flow")}</h1>
        <form class="account flow-form" novalidate>
          <div class="group">
            ${field("Name", `<input data-name="name" value="${esc(flow.name)}" placeholder="Leave requests" required>`)}
            <label class="row"><span class="main"><span class="title">Switched on</span></span>
              <input type="checkbox" data-name="on"${flow.on ? " checked" : ""}></label>
          </div>
          <p class="group-label">Trigger</p>
          <div class="group trigger">${triggerBody(flow.trigger, data)}</div>
          <p class="group-label">Steps</p>
          <div class="steps">${flow.steps.map((s, i) => stepCard(s, flow, i, data)).join("")}</div>
          <div class="group"><button type="button" class="row add-step">Add a step</button></div>
          <p class="note">Anything you type may hold <code>{{trigger.record.fields.title}}</code>, <code>{{approval.status}}</code>
            or <code>{{steps.step1.id}}</code>: what the run has gathered so far. The list under "Only if" shows what there is.</p>
          <p class="act-error" role="alert" hidden></p>
          <div class="group"><button class="row primary" type="submit">${making ? "Make the flow" : "Save"}</button></div>
          ${making ? "" : `<div class="group"><button class="row run-now" type="button">Run it now</button></div>
          <div class="group"><button class="row bad delete" type="button">Delete this flow</button></div>
          <p class="group-label">Runs</p>
          <div class="group">${runs.length ? runs.slice().reverse().map(runRow).join("") : `<p class="empty">It has not run yet.</p>`}</div>`}
        </form>
      </main>`);
    wireShell();
    wire();
  };

  const readInto = () => {
    const form = app.querySelector("form.flow-form");
    flow.name = form.querySelector('[data-name="name"]').value.trim();
    flow.on = form.querySelector('[data-name="on"]').checked;
    const trigger = {};
    for (const el of form.querySelectorAll(".trigger [data-name]")) {
      const value = el.value.trim();
      if (value !== "") trigger[el.dataset.name] = el.dataset.name === "when" ? [value] : value;
    }
    flow.trigger = trigger;
    flow.steps = [...form.querySelectorAll(".step")].map((card, i) => {
      const step = { id: flow.steps[i].id };
      for (const el of card.querySelectorAll("[data-name]")) {
        const name = el.dataset.name;
        const value = el.value.trim();
        if (name.startsWith("only_if.")) continue;
        if (name.startsWith("fields.")) {
          if (value !== "") (step.fields = step.fields || {})[name.slice(7)] = value;
        } else if (value !== "") step[name] = value;
      }
      const path = card.querySelector('[data-name="only_if.path"]');
      const op = card.querySelector('[data-name="only_if.op"]');
      if (path && op && op.value && path.value.trim()) {
        step.only_if = { path: path.value.trim(), [op.value]: card.querySelector('[data-name="only_if.value"]').value.trim() };
      }
      return step;
    });
  };

  const wire = () => {
    const form = app.querySelector("form.flow-form");
    const error = form.querySelector(".act-error");
    const showError = (text) => { error.textContent = text; error.hidden = !text; };
    // A change of shape — the kind of trigger or step, the datamodel, the
    // Quill — redraws the form around what was typed; a word typed does not.
    form.addEventListener("change", (event) => {
      const name = event.target.dataset.name;
      if (["kind", "model", "quill", "action", "when", "role"].includes(name)) { readInto(); draw(); }
    });
    form.querySelector(".add-step").addEventListener("click", () => {
      readInto();
      flow.steps.push({ id: freshId(), kind: "action" });
      draw();
    });
    form.querySelector(".steps").addEventListener("click", (event) => {
      const button = event.target.closest("[data-move], [data-remove]");
      if (!button) return;
      readInto();
      const index = Number(button.closest(".step").dataset.index);
      if (button.hasAttribute("data-remove")) flow.steps.splice(index, 1);
      else {
        const to = index + Number(button.dataset.move);
        if (to < 0 || to >= flow.steps.length) return;
        [flow.steps[index], flow.steps[to]] = [flow.steps[to], flow.steps[index]];
      }
      draw();
    });
    // Dragging a step's card onto another puts it there.
    let dragging = null;
    for (const card of form.querySelectorAll(".step")) {
      card.addEventListener("dragstart", (event) => { dragging = Number(card.dataset.index); event.dataTransfer.effectAllowed = "move"; });
      card.addEventListener("dragover", (event) => { event.preventDefault(); card.classList.add("over"); });
      card.addEventListener("dragleave", () => card.classList.remove("over"));
      card.addEventListener("drop", (event) => {
        event.preventDefault();
        const to = Number(card.dataset.index);
        if (dragging === null || dragging === to) return;
        readInto();
        const [moved] = flow.steps.splice(dragging, 1);
        flow.steps.splice(to, 0, moved);
        dragging = null;
        draw();
      });
    }
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      readInto();
      if (!flow.name) return showError("A flow needs a name.");
      const button = form.querySelector("button[type=submit]");
      button.disabled = true;
      try {
        const checked = await api("POST", "/api/flows/check", { trigger: flow.trigger, steps: flow.steps });
        if (!checked.ok) { showError(checked.problem); button.disabled = false; return; }
        const fields = { name: flow.name, on: flow.on, trigger: checked.trigger, steps: checked.steps };
        if (making) {
          const made = await api("POST", recordsUrl("flow"), { fields });
          toast(`${flow.name} is made`);
          replace("#/flow/" + encodeURIComponent(made.id));
          return renderRoute();
        }
        await api("PATCH", recordsUrl("flow", record.id), { fields, rev: record.rev });
        toast("Saved");
        return renderRoute();
      } catch (err) {
        button.disabled = false;
        showError(err.message);
      }
    });
    const runNow = form.querySelector(".run-now");
    if (runNow) {
      runNow.addEventListener("click", async () => {
        runNow.disabled = true;
        try {
          const run = await api("POST", "/api/flows/" + encodeURIComponent(record.id) + "/run", {});
          toast(run.fields.status === "failed" ? `Failed: ${run.fields.error}` : `Run ${run.fields.status}`);
          return renderRoute();
        } catch (err) {
          runNow.disabled = false;
          toast(err.message);
        }
      });
    }
    const remove = form.querySelector(".delete");
    if (remove) {
      remove.addEventListener("click", async () => {
        if (!await ask(`Delete ${flow.name}?\n\nIts runs go with it.`)) return;
        try {
          await api("DELETE", recordsUrl("flow", record.id));
          toast(`Deleted ${flow.name}`);
          replace("#/flows");
          return renderRoute();
        } catch (err) {
          toast(err.message);
        }
      });
    }
  };

  draw();
}

registerScreen("flows", renderFlows);
registerScreen("flow", renderFlow);
