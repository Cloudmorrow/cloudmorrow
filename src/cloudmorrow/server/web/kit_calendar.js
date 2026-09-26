/* The kit's `calendar`: a month and the day under it on the phone, a week
   or a month on a computer — drawn from the screen's bindings alone.

   A calendar screen names a model whose records are things that happen,
   and which of its fields say when:

     starts, ends   two moments (datetime or date fields, indexed)
     all_day        optional: a bool, for things that take whole days
     space          the link to the spaces they are in: every one you can
                    see is drawn at once, each in its own colour
     colour         optional: a field of the space naming its colour
     subtitle       optional: one more field, said under the title

   Every space you can see is drawn at once, because a calendar you have to
   switch between is a calendar that lets you double-book yourself. The list
   of spaces is for sharing them, not for hiding them; it is kit_space.js.

   Times are the times on the wall. A moment with no zone is stored as it was
   typed and drawn as it is, so ten o'clock is ten o'clock in June and in
   October; a bare date is a whole day, and the end of a whole-day thing is
   the last day it is on. A moment that does come with a zone is shown in
   the reader's own time. */

import {
  api, app, esc, heading, icons, nav, renderRoute, replace, store, tabs, toast, wireShell,
} from "./core.js";
import { sheetHash } from "./kit.js";
import { renderNewSpace, renderSpaceList } from "./kit_space.js";

const recordsUrl = (model, id) =>
  "/api/records/" + encodeURIComponent(model) + (id ? "/" + encodeURIComponent(id) : "");

// The colours a space can be, by name: the record says "violet", and the
// stylesheet and the terminal each know what violet looks like.
export const COLOURS = ["cyan", "violet", "green", "amber", "rose"];

const glyphs = {
  left: '<svg width="11" height="18" viewBox="0 0 11 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M8.5 1.5 2 9l6.5 7.5"/></svg>',
  right: '<svg width="11" height="18" viewBox="0 0 11 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 1.5 9 9l-6.5 7.5"/></svg>',
  people: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.2"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0"/><path d="M16 5.3a3.2 3.2 0 0 1 0 5.4M17.5 14.2A5.5 5.5 0 0 1 20.5 19"/></svg>',
};

// -- days, the way this file counts them -------------------------------------------
// Everything here is an ISO date string. A Date is only ever a calculator:
// made at noon, so no daylight saving can shift the day out from under it,
// and turned back into a string before it is used.
export const iso = (date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

export const dateOf = (day) => {
  const [y, m, d] = String(day).slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d, 12);
};

export const today = () => iso(new Date());

export function addDays(day, days) {
  const date = dateOf(day);
  date.setDate(date.getDate() + days);
  return iso(date);
}

export function addMonths(day, months) {
  const date = dateOf(day);
  const wanted = date.getMonth() + months;
  date.setDate(1);
  date.setMonth(wanted);
  return iso(date);
}

export const monthOf = (day) => day.slice(0, 7);

/** The Monday of the week *day* is in, and the six days after it. */
export function weekOf(day) {
  const first = addDays(day, -((dateOf(day).getDay() + 6) % 7));
  return Array.from({ length: 7 }, (_, step) => addDays(first, step));
}

/** The weeks a month is drawn in, whole, Monday first — the ends belong to
    the months either side, and are there so the rows are rows. */
export function weeksOf(day) {
  const weeks = [];
  let start = weekOf(monthOf(day) + "-01")[0];
  for (let week = 0; week < 6; week += 1) {
    const days = weekOf(start);
    weeks.push(days);
    start = addDays(start, 7);
    // Six rows only when the month needs them: the sixth would otherwise be
    // a row of somebody else's days.
    if (week >= 3 && monthOf(days[6]) > monthOf(day)) break;
  }
  return weeks;
}

/** A stored moment as the wall clock here says it: a zone is converted, a
    wall-clock time and a bare date are left exactly as they are. */
export function wall(stamp) {
  const text = String(stamp || "");
  if (!/(Z|[+-]\d\d:?\d\d)$/.test(text) || text.length <= 10) return text.slice(0, 16);
  const ms = Date.parse(text);
  if (Number.isNaN(ms)) return text.slice(0, 16);
  const d = new Date(ms);
  const pad = (n) => String(n).padStart(2, "0");
  return `${iso(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const clock = (stamp) => (stamp.length > 10 ? stamp.slice(11, 16) : "");
const minutes = (stamp) => (stamp.length > 10 ? Number(stamp.slice(11, 13)) * 60 + Number(stamp.slice(14, 16)) : 0);

/** Every day a thing covers, so a month can put a dot on each of them. */
export function daysOf(event) {
  const days = [];
  let day = event.starts.slice(0, 10);
  const last = event.ends.slice(0, 10);
  for (let guard = 0; guard < 400; guard += 1) {
    days.push(day);
    if (day >= last) break;
    day = addDays(day, 1);
  }
  return days;
}

export function byDay(events) {
  const filed = new Map();
  for (const event of events) {
    for (const day of daysOf(event)) {
      if (!filed.has(day)) filed.set(day, []);
      filed.get(day).push(event);
    }
  }
  return filed;
}

/** Whole days first, then the rest in the order the day happens. */
export const inOrder = (events) =>
  [...events].sort((a, b) =>
    (a.allDay === b.allDay ? 0 : a.allDay ? -1 : 1) || a.starts.localeCompare(b.starts));

export const longDay = (day) =>
  dateOf(day).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
const shortDay = (day) =>
  dateOf(day).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
const monthName = (day) =>
  dateOf(day).toLocaleDateString(undefined, { month: "long", year: "numeric" });
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** How long a thing lasts, in the fewest words that are still true. */
export function whenSaid(event) {
  if (event.allDay) {
    return event.ends.slice(0, 10) === event.starts.slice(0, 10)
      ? "All day" : `All day, to ${longDay(event.ends.slice(0, 10))}`;
  }
  const start = clock(event.starts);
  if (event.ends.slice(0, 10) !== event.starts.slice(0, 10)) {
    return `${start} → ${shortDay(event.ends.slice(0, 10))} ${clock(event.ends)}`;
  }
  return event.ends === event.starts ? start : `${start} – ${clock(event.ends)}`;
}

// -- the screen's bindings ------------------------------------------------------------
/** What a calendar screen is drawn from, read out of its bindings once. */
export function bindingsOf(quill, screen) {
  const model = quill.models[screen.model];
  const spaceField = model.fields.find((f) => f.name === screen.space);
  const spaceModel = spaceField ? quill.models[spaceField.to] : null;
  return {
    model,
    spaceField: screen.space,
    spaceModel,
    colour: screen.colour || "",
    title: screen.title || model.title,
    subtitle: screen.subtitle || "",
    starts: screen.starts,
    ends: screen.ends,
    allDay: screen.all_day || "",
  };
}

/** One record as a thing on a calendar: its times on the wall, and its space. */
export function occasion(b, record, spaces) {
  const f = record.fields;
  const starts = wall(f[b.starts]);
  const ends = wall(f[b.ends]) || starts;
  const space = spaces.get(f[b.spaceField]);
  return {
    id: record.id,
    record,
    title: String(f[b.title] || "").trim() || "Untitled",
    subtitle: b.subtitle && f[b.subtitle] ? String(f[b.subtitle]) : "",
    starts,
    ends: ends < starts ? starts : ends,
    allDay: b.allDay ? !!f[b.allDay] : starts.length === 10,
    colour: colourOf(b, space),
    spaceName: space ? String(space.fields[b.spaceModel.title] || "") : "",
  };
}

export const colourOf = (b, space) => {
  const named = space && b.colour ? space.fields[b.colour] : "";
  return COLOURS.includes(named) ? named : COLOURS[0];
};

/** Everything that overlaps the days from *first* to *last*, across every
    space you can see: one call, with a range on each of the two moments. */
export async function eventsBetween(b, first, last) {
  const query = `?${encodeURIComponent(b.starts + "__lte")}=${encodeURIComponent(last + "T23:59")}` +
    `&${encodeURIComponent(b.ends + "__gte")}=${encodeURIComponent(first)}`;
  return api("GET", recordsUrl(b.model.id) + query);
}

/** One event as a row: its colour, its title, and when and where. */
export function eventRow(href, event) {
  const meta = [event.subtitle, event.spaceName].filter(Boolean).join(" · ");
  return `<a class="row event" href="${href}">
    <i class="dot c-${event.colour}" aria-hidden="true"></i>
    <span class="main">
      <span class="title">${esc(event.title)}</span>
      <span class="meta"><span class="date">${esc(whenSaid(event))}</span>${
        meta ? `<span class="preview">${esc(meta)}</span>` : ""}</span>
    </span>${icons.chevronRight}</a>`;
}

// -- the screen ---------------------------------------------------------------------------
const aOr = (label) => (/^[aeiou]/i.test(label) ? "an " : "a ") + label.toLowerCase();
const wide = () => matchMedia("(min-width: 1180px) and (min-height: 600px)").matches;

export async function renderCalendar(at, arg) {
  const { quill, screen } = at;
  const b = bindingsOf(quill, screen);
  const dot = (space) => `<i class="dot c-${colourOf(b, space)}" aria-hidden="true"></i>`;
  if (arg === "spaces") {
    return renderSpaceList(at, b.spaceModel, { dot, back: at.base, backLabel: screen.label });
  }
  if (arg === "newspace") {
    return renderNewSpace(at, b.spaceModel, {
      back: `${at.base}/spaces`,
      // A new one is a colour that is not on the screen yet, while there is one.
      fields: async (spaces) => {
        if (!b.colour) return {};
        const taken = new Set(spaces.map((s) => s.fields[b.colour]));
        return { [b.colour]: COLOURS.find((c) => !taken.has(c)) || COLOURS[spaces.length % COLOURS.length] };
      },
    });
  }
  if (/^r_/.test(arg)) {
    // A space, by its id: where "you were added to…" lands. Its own page.
    replace(sheetHash(at, b.spaceModel.id, arg));
    return renderRoute();
  }

  const remembered = `kit.${at.tab}`;
  const picked = /^\d{4}-\d{2}-\d{2}$/.test(arg) ? arg : today();
  const view = wide() ? (store.get(remembered + ".view") || "week") : "month";
  const days = view === "week" ? weekOf(picked) : weeksOf(picked).flat();

  const [spaceList, records] = await Promise.all([
    api("GET", recordsUrl(b.spaceModel.id)),
    eventsBetween(b, days[0], days[days.length - 1]),
  ]);
  const spaces = new Map(spaceList.map((s) => [s.id, s]));
  const events = records.map((r) => occasion(b, r, spaces));
  const filed = byDay(events);
  const href = (event) => sheetHash(at, b.model.id, event.id);

  // Where a new one goes: the space you last put something in, else your own.
  let target = spaces.get(store.get(remembered + ".in")) ||
    spaceList.find((s) => s.scope === "personal") || spaceList[0] || null;

  const title = view === "week"
    ? `${shortDay(days[0])} – ${shortDay(days[6])}`
    : monthName(picked);
  const switcher = wide()
    ? `<div class="segments views" role="radiogroup" aria-label="View">${["week", "month"].map((v) =>
      `<button type="button" role="radio" data-view="${v}"${v === view ? ' class="active" aria-checked="true"' : ' aria-checked="false"'}>${v === "week" ? "Week" : "Month"}</button>`).join("")}</div>`
    : "";
  const actions = `<a class="button" href="${at.base}/spaces" aria-label="${esc(b.spaceModel.label)}s">${glyphs.people}</a>` +
    `<button class="compose" aria-label="New ${esc(b.model.label.toLowerCase())}">${icons.compose}</button>`;
  // What to type, and that a time in front of it is when: on a phone the
  // day is the one lit below, and the room is for the typing.
  const hint = wide()
    ? `Add ${aOr(b.model.label)} on ${shortDay(picked)} — “10:00 Dentist”, or a whole day`
    : `Add ${aOr(b.model.label)} — “10:00 Dentist”`;
  const addLine = `<form class="add kit-add">
      <input placeholder="${esc(hint)}" autocapitalize="sentences" enterkeyhint="done">
      ${spaceList.length > 1 ? `<select class="kit-in" aria-label="In which ${esc(b.spaceModel.label.toLowerCase())}">${spaceList.map((s) =>
        `<option value="${esc(s.id)}"${s === target ? " selected" : ""}>${esc(String(s.fields[b.spaceModel.title] || ""))}</option>`).join("")}</select>` : ""}
    </form>`;
  const onThatDay = inOrder(filed.get(picked) || []);
  const dayList = `<p class="group-label day-label">${esc(longDay(picked))}
      ${picked === today() ? "" : `<button class="today-link" type="button">Today</button>`}</p>
    <div class="listing">${onThatDay.length
      ? `<div class="group">${onThatDay.map((e) => eventRow(href(e), e)).join("")}</div>`
      : `<p class="empty"><b>Nothing on</b>Add something above, and it will show up here.</p>`}</div>`;

  app.innerHTML = nav({ title: screen.label }) + `
    <main class="kit-calendar view-${view}">
      ${heading(screen.label, actions)}
      <div class="month-bar">
        <button class="step" data-step="-1" aria-label="Back">${glyphs.left}</button>
        <h2>${esc(title)}</h2>
        <button class="step" data-step="1" aria-label="On">${glyphs.right}</button>
        ${switcher}
      </div>
      ${addLine}
      ${view === "week" ? weekGrid(days, filed, picked, href) + dayList
        : monthGrid(picked, filed) + dayList}
    </main>` + tabs(at.tab);
  wireShell();

  const go = (day) => { replace(`${at.base}/${day}`); renderRoute(); };
  for (const cell of app.querySelectorAll("[data-day]")) {
    cell.addEventListener("click", (event) => {
      if (event.target.closest("a")) return;
      go(cell.dataset.day);
    });
  }
  for (const step of app.querySelectorAll(".step")) {
    step.addEventListener("click", () => {
      const by = Number(step.dataset.step);
      if (view === "week") { go(addDays(picked, 7 * by)); return; }
      const wanted = addMonths(picked, by);
      // The month is what moved; the day is only where the list starts.
      go(monthOf(wanted) === monthOf(today()) ? today() : wanted);
    });
  }
  for (const button of app.querySelectorAll(".views button")) {
    button.addEventListener("click", () => {
      store.set(remembered + ".view", button.dataset.view);
      renderRoute();
    });
  }
  const todayLink = app.querySelector(".today-link");
  if (todayLink) todayLink.addEventListener("click", () => go(today()));

  const form = app.querySelector("form.kit-add");
  const input = form.querySelector("input");
  const pick = form.querySelector(".kit-in");
  if (pick) pick.addEventListener("change", () => { target = spaces.get(pick.value); store.set(remembered + ".in", pick.value); });
  app.querySelector(".heading .compose").addEventListener("click", () => input.focus());
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    if (!target) { toast(`No ${b.spaceModel.label.toLowerCase()} to put it in`); return; }
    input.value = "";
    try {
      await api("POST", recordsUrl(b.model.id), { fields: { ...newFields(b, picked, text), [b.spaceField]: target.id } });
      store.set(remembered + ".in", target.id);
      renderRoute();
    } catch (err) {
      input.value = text;
      toast(err.message);
    }
  });
}

/** What "10:00 Dentist" on a day means: an hour from ten. Without a time, a
    whole day — or, where the screen has no whole days, nine o'clock. */
export function newFields(b, day, text) {
  const timed = /^(\d{1,2})[:.](\d{2})\s+(.+)$/.exec(text);
  if (timed && Number(timed[1]) < 24 && Number(timed[2]) < 60) {
    const start = Number(timed[1]) * 60 + Number(timed[2]);
    const end = Math.min(start + 60, 24 * 60 - 1);
    const hhmm = (n) => `${String(Math.floor(n / 60)).padStart(2, "0")}:${String(n % 60).padStart(2, "0")}`;
    const fields = { [b.title]: timed[3].trim(), [b.starts]: `${day}T${hhmm(start)}`, [b.ends]: `${day}T${hhmm(end)}` };
    if (b.allDay) fields[b.allDay] = false;
    return fields;
  }
  if (b.allDay) return { [b.title]: text, [b.starts]: day, [b.ends]: day, [b.allDay]: true };
  return { [b.title]: text, [b.starts]: `${day}T09:00`, [b.ends]: `${day}T10:00` };
}

// -- the month ---------------------------------------------------------------------------
function monthGrid(picked, filed) {
  const shown = monthOf(picked);
  const cell = (day) => {
    const classes = ["cell"];
    if (monthOf(day) !== shown) classes.push("away");
    if (day === today()) classes.push("today");
    if (day === picked) classes.push("picked");
    const ordered = inOrder(filed.get(day) || []);
    // A dot each on a phone, where a cell is a thumb wide; the titles on a
    // computer, where it is tall enough to say what the day holds. One of
    // the two is always hidden, and which is the stylesheet's business.
    const dots = ordered.slice(0, 4).map((e) => `<i class="dot c-${e.colour}"></i>`).join("");
    const named = ordered.slice(0, 3).map((e) =>
      `<span class="on"><i class="dot c-${e.colour}"></i><span class="what">${esc(e.title)}</span></span>`).join("") +
      (ordered.length > 3 ? `<span class="more">${ordered.length - 3} more</span>` : "");
    return `<button class="${classes.join(" ")}" data-day="${day}" type="button">
      <span class="n">${Number(day.slice(8, 10))}</span>
      <span class="dots">${dots}</span>
      <span class="named">${named}</span></button>`;
  };
  return `<div class="weekdays">${WEEKDAYS.map((d) => `<span>${d}</span>`).join("")}</div>
    <div class="month">${weeksOf(picked).flat().map(cell).join("")}</div>`;
}

// -- the week ----------------------------------------------------------------------------
// Seven columns of the day's hours, with whole-day things in a strip along
// the top. The hours drawn are the working day, stretched to whatever the
// week holds outside it.
const HOUR = 44;   // pixels an hour is tall: a half-hour title still fits

function weekGrid(days, filed, picked, href) {
  const timed = days.flatMap((day) => (filed.get(day) || []).filter((e) => !e.allDay));
  let first = 8;
  let last = 18;
  for (const e of timed) {
    if (e.starts.slice(0, 10) >= days[0]) first = Math.min(first, Math.floor(minutes(e.starts) / 60));
    if (e.ends.slice(0, 10) <= days[6]) last = Math.max(last, Math.ceil(minutes(e.ends) / 60));
  }
  last = Math.min(24, Math.max(last, first + 1));
  const hours = Array.from({ length: last - first }, (_, i) => first + i);

  const head = days.map((day) =>
    `<button type="button" class="day-head${day === today() ? " today" : ""}${day === picked ? " picked" : ""}" data-day="${day}">
      <span class="wd">${WEEKDAYS[(dateOf(day).getDay() + 6) % 7]}</span><span class="n">${Number(day.slice(8, 10))}</span></button>`).join("");
  const whole = days.map((day) => {
    const list = inOrder((filed.get(day) || []).filter((e) => e.allDay));
    return `<div class="whole" data-day="${day}">${list.map((e) =>
      `<a class="chip-event c-${e.colour}" href="${href(e)}" title="${esc(e.title)}">${esc(e.title)}</a>`).join("")}</div>`;
  }).join("");
  const columns = days.map((day) => {
    const list = (filed.get(day) || []).filter((e) => !e.allDay);
    // A thing that runs past midnight is drawn on each day it touches, cut
    // to that day.
    const pieces = list.map((e) => ({
      e,
      from: e.starts.slice(0, 10) < day ? 0 : minutes(e.starts),
      to: e.ends.slice(0, 10) > day ? 24 * 60 : Math.max(minutes(e.ends), minutes(e.starts) + 15),
    })).sort((a, b) => a.from - b.from || b.to - a.to);
    // Side by side when they overlap: each takes the first free column,
    // and a run of overlapping things shares the width between them.
    const ends = [];
    let run = [];
    let runEnd = -1;
    const settle = () => { for (const p of run) p.of = Math.max(...run.map((q) => q.col)) + 1; };
    for (const p of pieces) {
      if (p.from >= runEnd) { settle(); run = []; ends.length = 0; }
      let col = ends.findIndex((end) => end <= p.from);
      if (col === -1) { col = ends.length; ends.push(p.to); } else ends[col] = p.to;
      p.col = col;
      run.push(p);
      runEnd = Math.max(runEnd, p.to);
    }
    settle();
    const blocks = pieces.map((p) => {
      const top = Math.max(0, (p.from - first * 60) / 60 * HOUR);
      const height = Math.max(20, (Math.min(p.to, last * 60) - Math.max(p.from, first * 60)) / 60 * HOUR - 2);
      const short = Math.min(p.to, last * 60) - Math.max(p.from, first * 60) < 45 ? " short" : "";
      return `<a class="block${short} c-${p.e.colour}" href="${href(p.e)}" style="top:${top}px;height:${height}px;left:calc(${p.col} * 100% / ${p.of});width:calc(100% / ${p.of} - 3px)">
        <span class="when">${esc(clock(p.e.starts.slice(0, 10) < day ? `${day}T00:00` : p.e.starts))}</span>
        <span class="what">${esc(p.e.title)}</span></a>`;
    }).join("");
    let now = "";
    if (day === today()) {
      const at = new Date();
      const m = at.getHours() * 60 + at.getMinutes();
      if (m >= first * 60 && m <= last * 60) now = `<i class="now" style="top:${(m - first * 60) / 60 * HOUR}px"></i>`;
    }
    return `<div class="col${day === today() ? " today" : ""}" data-day="${day}">${blocks}${now}</div>`;
  }).join("");
  return `<div class="week" style="--hour:${HOUR}px;--hours:${hours.length}">
    <div class="corner"></div>${head}
    <div class="corner whole-label">all day</div>${whole}
    <div class="hours">${hours.map((h) => `<span>${String(h).padStart(2, "0")}:00</span>`).join("")}</div>${columns}
  </div>`;
}

// -- the record sheet, for a calendar's records ---------------------------------------------
/** What the sheet does differently on a calendar screen: whole days are
    dates rather than times, moving the start keeps the length, and a
    space's colour is a row of swatches rather than a word to type. */
export function calendarSheet(at, model) {
  const b = bindingsOf(at.quill, at.screen);
  if (model.id === b.spaceModel.id && b.colour) {
    return {
      widget(f, value) {
        if (f.name !== b.colour) return null;
        const on = COLOURS.includes(value) ? value : COLOURS[0];
        return `<span class="swatches" role="radiogroup" aria-label="${esc(f.label)}">` +
          `<input type="hidden" data-field="${esc(f.name)}" value="${esc(on)}">` +
          COLOURS.map((c) => `<button type="button" class="swatch c-${c}${c === on ? " on" : ""}" data-colour="${c}" aria-label="${c}" aria-checked="${c === on}" role="radio"></button>`).join("") +
          `</span>`;
      },
      wire(box) {
        for (const button of box.querySelectorAll(".swatch")) {
          button.addEventListener("click", () => {
            const holder = button.closest(".swatches");
            for (const other of holder.querySelectorAll(".swatch")) other.classList.toggle("on", other === button);
            const hidden = holder.querySelector("input");
            hidden.value = button.dataset.colour;
            hidden.dispatchEvent(new Event("change"));
          });
        }
      },
    };
  }
  if (model.id !== b.model.id) return null;
  return {
    parent: (record) => {
      const day = wall(record.fields[b.starts]).slice(0, 10);
      return day ? `${at.base}/${day}` : "";
    },
    widget(f, value) {
      // A whole day is a date, so its box is a date box.
      if ((f.name === b.starts || f.name === b.ends) && String(value || "").length === 10) {
        return `<input type="date" data-field="${esc(f.name)}" aria-label="${esc(f.label)}" value="${esc(value)}">`;
      }
      return null;
    },
    /** The fields to send, after what this screen knows about time. */
    adjust(out, record) {
      const was = record.fields;
      const start0 = wall(was[b.starts]);
      const end0 = wall(was[b.ends]) || start0;
      if (b.allDay && b.allDay in out) {
        // Whole days keep the days and drop the times; a timed thing gets
        // an hour from nine on the day it was on.
        const first = String(out[b.starts] || start0).slice(0, 10);
        const lastDay = String(out[b.ends] || end0).slice(0, 10);
        if (out[b.allDay]) {
          out[b.starts] = first;
          out[b.ends] = lastDay < first ? first : lastDay;
        } else {
          out[b.starts] = `${first}T09:00`;
          out[b.ends] = `${first}T10:00`;
        }
        return { out, redraw: true };
      }
      if (b.starts in out && !(b.ends in out) && out[b.starts] && start0) {
        // Moving the start drags the end along: an hour at ten, moved to
        // half eleven, is an hour at half eleven.
        out[b.ends] = shifted(end0, start0, out[b.starts]);
        return { out, redraw: true };
      }
      if (b.ends in out && out[b.ends] && String(out[b.ends]) < String(out[b.starts] || start0)) {
        out[b.ends] = out[b.starts] || start0;
        return { out, redraw: true };
      }
      return { out, redraw: false };
    },
  };
}

/** *end*, moved by as much as the start moved from *was* to *now*. */
function shifted(end, was, now) {
  if (was.length === 10 || now.length === 10) {
    const days = Math.round((dateOf(now) - dateOf(was)) / 86400000);
    return end.length === 10 ? addDays(end, days) : `${addDays(end.slice(0, 10), days)}${end.slice(10)}`;
  }
  const ms = (s) => new Date(s.slice(0, 16)).getTime();
  const moved = new Date(ms(end) + (ms(now) - ms(was)));
  const pad = (n) => String(n).padStart(2, "0");
  return `${iso(moved)}T${pad(moved.getHours())}:${pad(moved.getMinutes())}`;
}
