/* Circles, for an administrator: who may use which data (docs/CIRCLES.md).

   The fourth section of Administration. A circle is a named set of people
   — Parents, Kids, Sales — and, for each kind of data, what they may do
   with it: write, read, or nothing. Somebody's access is the most any of
   their circles gives, so there is no deny to explain: children are not
   given less, parents are given more.

   One circle's page is one form, like an account's: its name, whether new
   accounts go into it, its people as ticks, and its data. The data is set
   the way people think of it, by domain — Tasks, Calendars, Customers —
   and stored the way the gate checks it, per datamodel: choosing Read on
   Calendars writes read on calendar and on event. A domain opens to its
   datamodels when they should differ, and "Everything" at the top is `*`,
   which reaches datamodels installed later too.

   A datamodel left "as everything" has no line of its own and follows `*`.
   One given its own line keeps it when `*` changes: a named rule beats `*`. */

import {
  api, app, esc, nav, registerScreen, renderRoute, replace, store, toast, wireShell,
} from "./core.js";

export const EVERY = "*";
// What a circle gives on a datamodel, as the menus say it.
export const ACCESS = [
  ["write", "Write"],
  ["read", "Read"],
  ["none", "Nothing"],
];
const SAID = Object.fromEntries(ACCESS);
// A datamodel with no line of its own: whatever Everything gives.
const FOLLOW = "";
const MIXED = "mixed";

const circleUrl = (id) => "/api/circles/" + encodeURIComponent(id);
const plural = (n, word, many = word + "s") => `${n} ${n === 1 ? word : many}`;

/** Back to the list, on the Circles side of Administration. */
async function backToCircles() {
  store.set("admin.side", "circles");
  replace("#/admin");
  await renderRoute();
}

// -- what a circle says, in a line -------------------------------------------------------
/** "Everything: Write · Task: Read", for a row's second line. */
export function rulesSaid(rules, labels = {}) {
  const order = Object.keys(rules).filter((m) => m !== EVERY).sort();
  if (EVERY in rules) order.unshift(EVERY);
  if (!order.length) return "No data yet";
  return order.map((m) => `${m === EVERY ? "Everything" : labels[m] || m}: ${SAID[rules[m]] || rules[m]}`).join(" · ");
}

/** The circles each person is in, by username. */
export function circlesByPerson(circles) {
  const found = {};
  for (const circle of circles) {
    for (const name of circle.members) (found[name] = found[name] || []).push(circle.name);
  }
  return found;
}

// -- the list, in the panel ------------------------------------------------------------------
export async function drawCircles(panel) {
  const [circles, users] = await Promise.all([api("GET", "/api/circles"), api("GET", "/api/users")]);
  const placed = circlesByPerson(circles);
  const adrift = users.filter((u) => !placed[u.username]).map((u) => u.username);
  panel.innerHTML = `
    <p class="note">A circle is a set of people and what they may do with each
      kind of data. Everybody gets the most any of their circles gives; somebody
      in no circle signs in to nothing.</p>
    ${adrift.length ? `<p class="note warn">In no circle, so reaching no data:
      ${esc(adrift.join(", "))}.</p>` : ""}
    <p class="group-label">${plural(circles.length, "circle")}</p>
    <div class="group">${circles.map(circleRow).join("")}</div>`;
}

function circleRow(circle) {
  const people = circle.members.length ? circle.members.join(", ") : "nobody";
  return `<a class="row circle-row" href="#/admincircle/${encodeURIComponent(circle.id)}">
    <span class="main"><span class="title">${esc(circle.name)}</span>
    <span class="meta"><span class="preview">${esc(people)} · ${esc(rulesSaid(circle.rules))}</span></span></span>
    ${circle.default ? `<span class="role-chip circle-default">Default</span>` : ""}</a>`;
}

// -- the domains -----------------------------------------------------------------------------
/** A domain's name from its id: "calendars" is Calendars, "crm" is CRM. */
function domainLabel(id) {
  if (!id) return "Other";
  const words = id.replace(/[._-]+/g, " ");
  return words.length <= 3 ? words.toUpperCase() : words.charAt(0).toUpperCase() + words.slice(1);
}

/** The datamodels, shelved by domain. A Quill's own datamodel with no domain
    is shelved under the Quill that brought it. */
export function domainsOf(models) {
  const shelves = new Map();
  for (const model of models) {
    const id = model.domain || (model.source && model.source !== "foundation" ? model.source : "");
    if (!shelves.has(id)) shelves.set(id, { id, label: domainLabel(id), models: [] });
    shelves.get(id).models.push(model);
  }
  return [...shelves.values()].sort((a, b) => (!a.id) - (!b.id) || a.label.localeCompare(b.label));
}

/** What a domain's menu shows: its datamodels' one answer, or mixed. */
export function domainValue(rules, models) {
  const values = new Set(models.map((m) => (m.id in rules ? rules[m.id] : FOLLOW)));
  return values.size === 1 ? [...values][0] : MIXED;
}

function menu(name, chosen, { follow = true, mixed = false, label = "" } = {}) {
  const options = [
    ...(follow ? [[FOLLOW, "As everything"]] : []),
    ...ACCESS,
    ...(mixed ? [[MIXED, "Mixed"]] : []),
  ];
  return `<select name="${esc(name)}" aria-label="${esc(label)}">${options.map(([value, said]) =>
    `<option value="${esc(value)}"${value === chosen ? " selected" : ""}${
      value === MIXED ? " disabled" : ""}>${esc(said)}</option>`).join("")}</select>`;
}

export function rulesForm(rules, shelves) {
  const every = rules[EVERY] || "none";
  return `<div class="group rules">
      <div class="row rule-row"><span class="main"><span class="title">Everything</span>
        <span class="meta"><span class="preview">Every datamodel, and ones installed later</span></span></span>
        ${menu("rule:*", every, { follow: false, label: "Everything" })}</div>
    </div>` + shelves.map((shelf) => {
    const value = domainValue(rules, shelf.models);
    return `<details class="group rules domain" data-domain="${esc(shelf.id)}">
      <summary class="row rule-row"><span class="main"><span class="title">${esc(shelf.label)}</span>
        <span class="meta"><span class="preview">${esc(shelf.models.map((m) => m.label || m.id).join(", "))}</span></span></span>
        ${menu("domain:" + shelf.id, value, { mixed: true, label: shelf.label })}</summary>
      ${shelf.models.map((m) => `<div class="row rule-row model-row">
        <span class="main"><span class="title">${esc(m.label || m.id)}</span>
        <span class="meta"><span class="preview">${esc(m.id)}</span></span></span>
        ${menu("rule:" + m.id, m.id in rules ? rules[m.id] : FOLLOW, { label: m.label || m.id })}</div>`).join("")}
    </details>`;
  }).join("");
}

/** A domain's menu sets every datamodel under it; a datamodel's own menu
    puts the domain's at their one answer, or at mixed. */
export function wireRulesForm(form, shelves) {
  for (const details of form.querySelectorAll("details.domain")) {
    const shelf = shelves.find((s) => s.id === details.dataset.domain);
    const top = details.querySelector("summary select");
    const own = [...details.querySelectorAll(".model-row select")];
    // A menu inside a summary would open and shut the domain on every tap.
    top.addEventListener("click", (event) => event.preventDefault());
    top.addEventListener("change", () => {
      for (const select of own) select.value = top.value;
    });
    for (const select of own) {
      select.addEventListener("change", () => {
        top.value = domainValue(rulesFrom(form, {}), shelf.models);
      });
    }
  }
}

/** The rules the form says, over the ones it does not show (a datamodel from
    a Quill since removed keeps its line). */
export function rulesFrom(form, before) {
  const rules = { ...before };
  for (const select of form.querySelectorAll("select[name^='rule:']")) {
    const model = select.name.slice("rule:".length);
    delete rules[model];
    if (model === EVERY) {
      if (select.value !== "none") rules[EVERY] = select.value;
    } else if (select.value !== FOLLOW) {
      rules[model] = select.value;
    }
  }
  return rules;
}

// -- one circle ------------------------------------------------------------------------------
async function renderCircle(id) {
  const me = await api("GET", "/api/auth/me");
  if (!me.is_admin) {
    toast("Administration is for administrators");
    replace("#/me");
    return renderRoute();
  }
  const making = !id;
  const [circles, users, models] = await Promise.all([
    api("GET", "/api/circles"), api("GET", "/api/users"), api("GET", "/api/datamodels"),
  ]);
  let circle = { name: "", default: false, rules: {}, members: [] };
  if (!making) {
    circle = circles.find((c) => c.id === id);
    if (!circle) {
      toast("No such circle");
      return backToCircles();
    }
  }
  // The datamodels come from what this administrator reaches; somebody whose
  // own circles lack a `*` sees only part of the list, and is told so.
  const seesAll = circles.some((c) => c.members.includes(me.username) && c.rules[EVERY]);
  const shelves = domainsOf(models);

  app.innerHTML = nav({
    back: "#/admin",
    backLabel: "Admin",
    title: making ? "New circle" : circle.name,
  }) + `
    <main>
      <h1 class="large">${esc(making ? "New circle" : circle.name)}</h1>
      <form class="account circle-form">
        <div class="group">
          <label class="row"><span class="main">Name</span>
            <input name="name" placeholder="Kids" required value="${esc(circle.name)}"></label>
        </div>
        <div class="group"><label class="row">
          <span class="main"><span class="title">New accounts go here</span>
          <span class="meta"><span class="preview">The default circle. More than one may be.</span></span></span>
          <input type="checkbox" name="default"${circle.default ? " checked" : ""}></label></div>

        <p class="group-label">People</p>
        <div class="group choices">${users.map((u) => `
          <label class="row"><span class="main"><span class="title">${esc(u.username)}</span>
            ${u.display_name ? `<span class="meta"><span class="preview">${esc(u.display_name)}</span></span>` : ""}</span>
            <input type="checkbox" name="member" value="${esc(u.username)}"${
              circle.members.includes(u.username) ? " checked" : ""}></label>`).join("")}</div>

        <p class="group-label">Data</p>
        <p class="shelf-note">What the people in it may do with each kind of data.
          Open a domain to set its datamodels one by one.${seesAll ? "" : ` Only the
          datamodels your own circles reach are listed.`}</p>
        ${rulesForm(circle.rules, shelves)}

        <div class="group"><button class="row primary" type="submit">${
          making ? "Make the circle" : "Save"}</button></div>
        ${making ? "" :
          `<div class="group"><button class="row bad delete" type="button">Delete this circle</button></div>`}
      </form>
    </main>`;
  wireShell();

  const form = app.querySelector("form.circle-form");
  wireRulesForm(form, shelves);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = form.elements.name.value.trim();
    if (!name) return toast("A circle needs a name.");
    const rules = rulesFrom(form, circle.rules);
    const wanted = [...form.querySelectorAll("input[name=member]:checked")].map((b) => b.value);
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      if (making) {
        const made = await api("POST", "/api/circles", {
          name, rules, members: wanted, default: form.elements.default.checked,
        });
        toast(`${made.name} is made`);
      } else {
        await api("PATCH", circleUrl(circle.id), {
          name, rules, default: form.elements.default.checked,
        });
        const people = (who) => circleUrl(circle.id) + "/members/" + encodeURIComponent(who);
        for (const who of wanted.filter((w) => !circle.members.includes(w))) await api("PUT", people(who));
        for (const who of circle.members.filter((w) => !wanted.includes(w))) await api("DELETE", people(who));
        toast("Saved");
      }
      await backToCircles();
    } catch (err) {
      button.disabled = false;
      toast(err.message);
    }
  });

  const remove = form.querySelector(".delete");
  if (remove) {
    remove.addEventListener("click", async () => {
      const sure = confirm(
        `Delete ${circle.name}?\n\nIts people keep their other circles. Anybody `
        + "in no other circle reaches no data until they are put in one.",
      );
      if (!sure) return;
      try {
        await api("DELETE", circleUrl(circle.id));
        toast(`Deleted ${circle.name}`);
        await backToCircles();
      } catch (err) {
        toast(err.message);
      }
    });
  }
}

registerScreen("admincircle", renderCircle);
