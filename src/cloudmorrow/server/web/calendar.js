/* Calendar: the month, the day under it, and the calendars behind both.

   Five screens. The month, which is where you land and where a day is
   picked; an event, which is what it says and the way to change it; the
   form that makes one; the list of calendars; and a calendar's own page,
   for who is in it and the way out.

   Every calendar you can see is drawn at once, each event in the colour of
   the calendar it is on — because a calendar you have to switch between is
   a calendar that lets you double-book yourself. The list of calendars is
   for sharing them, not for hiding them.

   The times are the times on the wall. The server stores what somebody
   typed and converts nothing, so `<input type="time">` can hand its value
   straight over and get the same one back; see `server/calendar.py`. */

import {
  api, app, esc, heading, icons, nav, onSignOut, pixelIcon, registerScreen, registerTab,
  renderRoute, replace, session, store, tabs, toast, wireShell,
} from "./core.js";

const calendarUrl = (slug) => "/api/calendar/calendars/" + encodeURIComponent(slug);
const eventUrl = (id) => "/api/calendar/events/" + encodeURIComponent(id);

let calendars = [];
let people = [];

// Which calendar a new event goes in, remembered between visits: on a phone
// it is nearly always the same one, and picking it every time is a tax.
const lastUsed = () => store.get("calendar.in") || "";

// -- the icons this feature draws ------------------------------------------------
const glyphs = {
  left: '<svg width="11" height="18" viewBox="0 0 11 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M8.5 1.5 2 9l6.5 7.5"/></svg>',
  right: '<svg width="11" height="18" viewBox="0 0 11 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 1.5 9 9l-6.5 7.5"/></svg>',
  clock: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 6.5V12l3.5 2.5"/></svg>',
  pin: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s7-6.2 7-11a7 7 0 1 0-14 0c0 4.8 7 11 7 11z"/><circle cx="12" cy="10" r="2.6"/></svg>',
  people: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.2"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0"/><path d="M16 5.3a3.2 3.2 0 0 1 0 5.4M17.5 14.2A5.5 5.5 0 0 1 20.5 19"/></svg>',
};

// -- days, the way this file counts them -------------------------------------------
// Everything here is an ISO date string. A Date is only ever a calculator:
// it is made at noon, so no amount of daylight saving can shift the day out
// from under it, and it is turned back into a string before it is used.
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

/** The weeks a month is drawn in, whole, Monday first — the ends belong to
    the months either side, and are there so the rows are rows. */
export function weeksOf(day) {
  const first = dateOf(monthOf(day) + "-01");
  const start = dateOf(iso(first));
  start.setDate(1 - ((first.getDay() + 6) % 7));
  const weeks = [];
  for (let week = 0; week < 6; week += 1) {
    const days = [];
    for (let step = 0; step < 7; step += 1) {
      days.push(iso(start));
      start.setDate(start.getDate() + 1);
    }
    weeks.push(days);
    // Six rows only when the month needs them; five is the common case and
    // the sixth would be a row of somebody else's days.
    if (week >= 3 && monthOf(days[6]) > monthOf(day)) break;
  }
  return weeks;
}

/** Every day an event covers, so the month can put a dot on each of them. */
export function daysOf(event) {
  const days = [];
  let day = event.starts_at.slice(0, 10);
  const last = event.ends_at.slice(0, 10);
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

export const inOrder = (events) =>
  [...events].sort((a, b) =>
    (a.all_day === b.all_day ? 0 : a.all_day ? -1 : 1) || a.starts_at.localeCompare(b.starts_at));

const clock = (stamp) => (stamp.length > 10 ? stamp.slice(11, 16) : "");

/** How long a thing lasts, in the fewest words that are still true. */
export function whenSaid(event) {
  if (event.all_day) {
    return event.ends_at.slice(0, 10) === event.starts_at.slice(0, 10)
      ? "All day" : `All day, to ${longDay(event.ends_at.slice(0, 10))}`;
  }
  const start = clock(event.starts_at);
  if (event.ends_at.slice(0, 10) !== event.starts_at.slice(0, 10)) {
    return `${start} → ${longDay(event.ends_at.slice(0, 10))} ${clock(event.ends_at)}`;
  }
  return `${start} – ${clock(event.ends_at)}`;
}

const longDay = (day) =>
  dateOf(day).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
const monthName = (day) =>
  dateOf(day).toLocaleDateString(undefined, { month: "long", year: "numeric" });
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// -- the month -----------------------------------------------------------------------
async function loadCalendars() {
  calendars = await api("GET", "/api/calendar/calendars");
  if (!calendars.some((c) => c.slug === lastUsed())) {
    store.set("calendar.in", calendars.length ? calendars[0].slug : null);
  }
  return calendars;
}

const colourOf = (event) => `c-${event.colour || "cyan"}`;

function dayCell(day, events, { shown, picked }) {
  const classes = ["cell"];
  if (monthOf(day) !== shown) classes.push("away");
  if (day === today()) classes.push("today");
  if (day === picked) classes.push("picked");
  const ordered = inOrder(events);
  const dots = ordered.slice(0, 4)
    .map((event) => `<i class="dot ${colourOf(event)}"></i>`).join("");
  // The same events again, by name. A cell on a phone is 46 points tall
  // and a dot is all that fits; a cell on a computer has the height to
  // say what the day actually holds. One of the two is always hidden,
  // and which one is the stylesheet's business rather than this file's.
  const named = ordered.slice(0, 3).map((event) =>
    `<span class="on"><i class="dot ${colourOf(event)}"></i>` +
    `<span class="what">${esc(event.title)}</span></span>`).join("") +
    (ordered.length > 3 ? `<span class="more">${ordered.length - 3} more</span>` : "");
  return `<button class="${classes.join(" ")}" data-day="${day}">
    <span class="n">${Number(day.slice(8, 10))}</span>
    <span class="dots">${dots}</span>
    <span class="named">${named}</span></button>`;
}

export function eventRow(event) {
  return `<a class="row event" href="#/event/${event.id}">
    <i class="dot ${colourOf(event)}" aria-hidden="true"></i>
    <span class="main">
      <span class="title">${esc(event.title)}</span>
      <span class="meta"><span class="date">${esc(whenSaid(event))}</span>
      <span class="preview">${esc([event.location, event.calendar_name].filter(Boolean).join(" · "))}</span></span>
    </span>${icons.chevronRight}</a>`;
}

async function renderMonth(arg) {
  const picked = /^\d{4}-\d{2}-\d{2}$/.test(arg) ? arg : today();
  const weeks = weeksOf(picked);
  const [events] = await Promise.all([
    api("GET", `/api/calendar/events?from=${weeks[0][0]}&to=${weeks[weeks.length - 1][6]}`),
    calendars.length ? Promise.resolve(calendars) : loadCalendars(),
  ]);
  const filed = byDay(events);
  const shown = monthOf(picked);
  const onThatDay = inOrder(filed.get(picked) || []);

  app.innerHTML = nav({ title: "Calendar" }) + `
    <main class="calendar">
      ${heading("Calendar", `<button class="compose" aria-label="New event">${icons.compose}</button>`)}
      <div class="month-bar">
        <button class="step" data-month="-1" aria-label="Last month">${glyphs.left}</button>
        <h2>${esc(monthName(picked))}</h2>
        <button class="step" data-month="1" aria-label="Next month">${glyphs.right}</button>
        <a class="calendars-link" href="#/calendars" aria-label="Calendars">${glyphs.people}</a>
      </div>
      <div class="weekdays">${WEEKDAYS.map((d) => `<span>${d}</span>`).join("")}</div>
      <div class="month">${weeks.map((week) => week
        .map((day) => dayCell(day, filed.get(day) || [], { shown, picked })).join("")).join("")}</div>
      <p class="group-label day-label">${esc(longDay(picked))}
        ${picked === today() ? "" : `<button class="today-link">Today</button>`}</p>
      <div class="listing">${
        onThatDay.length
          ? `<div class="group">${onThatDay.map(eventRow).join("")}</div>`
          : `<p class="empty"><b>Nothing on</b>Tap the pencil to put something here.</p>`
      }</div>
    </main>` + tabs("calendar");
  wireShell();

  for (const cell of app.querySelectorAll(".month .cell")) {
    cell.addEventListener("click", () => go(cell.dataset.day));
  }
  for (const step of app.querySelectorAll(".step")) {
    go_month(step, picked);
  }
  const todayLink = app.querySelector(".today-link");
  if (todayLink) todayLink.addEventListener("click", () => go(today()));
  app.querySelector(".heading .compose").addEventListener("click", () => {
    location.hash = "#/eventnew/" + picked;
  });
}

function go(day) {
  replace("#/calendar/" + day);
  renderRoute();
}

function go_month(button, picked) {
  button.addEventListener("click", () => {
    const wanted = addMonths(picked, Number(button.dataset.month));
    // Landing on the same day of the next month, or its first: the month is
    // what moved, and the day is only where the list below starts.
    go(monthOf(wanted) === monthOf(today()) ? today() : wanted);
  });
}

// -- one event -------------------------------------------------------------------------
async function renderEvent(arg) {
  let event;
  try {
    event = await api("GET", eventUrl(arg));
  } catch (err) {
    if (err.status === 404 || err.status === 403) {
      toast(err.status === 403 ? "That is not yours to see" : "That event is gone");
      replace("#/calendar");
      return renderRoute();
    }
    throw err;
  }
  const day = event.starts_at.slice(0, 10);
  const back = "#/calendar/" + day;
  const facts = [
    [glyphs.clock, longDay(day) + " · " + whenSaid(event)],
    event.location && [glyphs.pin, event.location],
  ].filter(Boolean);

  app.innerHTML = nav({
    back, backLabel: "Calendar", title: event.title,
    right: `<a class="nav-link" href="#/eventedit/${event.id}">Edit</a>`,
  }) + `
    <main>
      <h1 class="large">${esc(event.title)}</h1>
      <div class="group">${facts.map(([icon, text]) =>
        `<div class="row has-icon"><span class="icon">${icon}</span>
         <span class="main">${esc(text)}</span></div>`).join("")}
        <div class="row has-icon"><span class="icon"><i class="dot ${colourOf(event)}"></i></span>
          <span class="main">${esc(event.calendar_name)}</span>
          <span class="said">${esc(event.created_by === session.user ? "you put it there" : event.created_by)}</span></div>
      </div>
      ${event.notes ? `<p class="group-label">Notes</p><div class="group"><div class="row note">${esc(event.notes)}</div></div>` : ""}
      <div class="group"><button class="row bad delete">Delete this event</button></div>
    </main>`;
  wireShell();

  app.querySelector(".delete").addEventListener("click", async () => {
    if (!confirm(`Delete “${event.title}”?`)) return;
    try {
      await api("DELETE", eventUrl(event.id));
      replace(back);
      renderRoute();
    } catch (err) { toast(err.message); }
  });
}

// -- making one, and changing one ---------------------------------------------------------
function eventForm(event, { day, heading, submit }) {
  const whole = !!event.all_day;
  const start = event.starts_at || day;
  const end = event.ends_at || "";
  const options = calendars.map((c) =>
    `<option value="${esc(c.slug)}"${c.slug === (event.calendar || lastUsed()) ? " selected" : ""}>${esc(c.name)}</option>`).join("");
  return nav({ back: "#/calendar/" + (start.slice(0, 10) || day), backLabel: "Calendar", title: heading }) + `
    <main>
      <h1 class="large">${esc(heading)}</h1>
      <form class="event-form">
        <div class="group">
          <label class="row"><input name="title" placeholder="What is happening"
            value="${esc(event.title || "")}" autocapitalize="sentences" required></label>
          <label class="row"><input name="location" placeholder="Where"
            value="${esc(event.location || "")}" autocapitalize="sentences"></label>
        </div>
        <div class="group">
          <label class="row"><span class="main">All day</span>
            <input type="checkbox" name="all_day"${whole ? " checked" : ""}></label>
          <label class="row"><span class="main">Starts</span>
            <span class="when">
              <input type="date" name="start_date" value="${esc(start.slice(0, 10))}" required>
              <input type="time" name="start_time" value="${esc(clock(start) || "09:00")}">
            </span></label>
          <label class="row"><span class="main">Ends</span>
            <span class="when">
              <input type="date" name="end_date" value="${esc((end || start).slice(0, 10))}">
              <input type="time" name="end_time" value="${esc(clock(end) || "10:00")}">
            </span></label>
        </div>
        <p class="group-label">Which calendar</p>
        <div class="group">
          <label class="row"><span class="main">Calendar</span>
            <select name="calendar">${options}</select></label>
        </div>
        <div class="group">
          <label class="row"><textarea name="notes" rows="3"
            placeholder="Anything else">${esc(event.notes || "")}</textarea></label>
        </div>
        <div class="group"><button class="row primary" type="submit">${esc(submit)}</button></div>
      </form>
    </main>`;
}

/** What the form means, as the API spells it — or a complaint. */
export function readForm(form) {
  const value = (name) => (form.elements[name] ? form.elements[name].value.trim() : "");
  const title = value("title");
  if (!title) return { error: "An event needs a title." };
  const whole = form.elements.all_day.checked;
  const startDate = value("start_date");
  if (!startDate) return { error: "An event needs a day." };
  const endDate = value("end_date") || startDate;
  const starts = whole ? startDate : `${startDate}T${value("start_time") || "09:00"}`;
  const ends = whole ? endDate : `${startDate}T${value("end_time") || value("start_time") || "10:00"}`;
  if (ends < starts) return { error: "It cannot end before it starts." };
  return {
    fields: {
      title,
      starts_at: starts,
      ends_at: ends,
      all_day: whole,
      location: value("location"),
      notes: form.elements.notes ? form.elements.notes.value.trim() : "",
    },
    calendar: value("calendar"),
  };
}

/** Moving the start drags the end along, so the event keeps its length;
 *  and the end cannot be put before the start, in either the clock or the
 *  calendar. A timed event stays inside its day, so an end that would run
 *  past midnight stops at the last minute of it. */
export function keepLength(form) {
  const { start_time: startTime, end_time: endTime, start_date: startDate, end_date: endDate } = form.elements;
  const minutes = (hhmm) => { const [h, m] = hhmm.split(":").map(Number); return h * 60 + m; };
  const hhmm = (n) => `${String(Math.floor(n / 60)).padStart(2, "0")}:${String(n % 60).padStart(2, "0")}`;
  const days = (iso) => Math.round(dateOf(iso).getTime() / 86400000);
  let lastStart = startTime.value;
  let lastDay = startDate.value;
  const fence = () => {
    endTime.min = startTime.value;
    endDate.min = startDate.value;
  };
  startTime.addEventListener("change", () => {
    if (startTime.value && lastStart && endTime.value) {
      const length = Math.max(0, minutes(endTime.value) - minutes(lastStart));
      endTime.value = hhmm(Math.min(minutes(startTime.value) + length, 24 * 60 - 1));
    }
    lastStart = startTime.value;
    fence();
  });
  endTime.addEventListener("change", () => {
    if (startTime.value && endTime.value && endTime.value < startTime.value) endTime.value = startTime.value;
  });
  startDate.addEventListener("change", () => {
    if (startDate.value && lastDay && endDate.value) {
      const length = Math.max(0, days(endDate.value) - days(lastDay));
      endDate.value = addDays(startDate.value, length);
    }
    lastDay = startDate.value;
    fence();
  });
  endDate.addEventListener("change", () => {
    if (startDate.value && endDate.value && endDate.value < startDate.value) endDate.value = startDate.value;
  });
  fence();
}

function wireForm(onSave) {
  const form = app.querySelector("form.event-form");
  const showTimes = () => {
    const whole = form.elements.all_day.checked;
    form.elements.start_time.hidden = whole;
    form.elements.end_time.hidden = whole;
    // An all-day event runs over days; a timed one stays inside one, so
    // there is nothing to say about its last day.
    form.elements.end_date.hidden = !whole;
  };
  form.elements.all_day.addEventListener("change", showTimes);
  showTimes();
  keepLength(form);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const read = readForm(form);
    if (read.error) { toast(read.error); return; }
    try {
      await onSave(read);
    } catch (err) { toast(err.message); }
  });
}

async function renderNewEvent(arg) {
  const day = /^\d{4}-\d{2}-\d{2}$/.test(arg) ? arg : today();
  if (!calendars.length) await loadCalendars();
  if (!calendars.length) { toast("No calendar to put it in"); replace("#/calendar"); return renderRoute(); }
  app.innerHTML = eventForm({}, { day, heading: "New event", submit: "Put it in" });
  wireShell();
  wireForm(async ({ fields, calendar }) => {
    const made = await api("POST", calendarUrl(calendar) + "/events", fields);
    store.set("calendar.in", calendar);
    replace("#/calendar/" + made.starts_at.slice(0, 10));
    renderRoute();
  });
}

async function renderEditEvent(arg) {
  if (!calendars.length) await loadCalendars();
  const event = await api("GET", eventUrl(arg));
  app.innerHTML = eventForm(event, {
    day: event.starts_at.slice(0, 10), heading: "Edit event", submit: "Save",
  });
  wireShell();
  wireForm(async ({ fields, calendar }) => {
    await api("PATCH", eventUrl(event.id), { ...fields, calendar });
    replace("#/event/" + event.id);
    renderRoute();
  });
}

// -- the calendars themselves ----------------------------------------------------------
const KIND_SAID = {
  personal: "Only you",
  public: "Everybody is in it",
  shared: (c) => `${c.members.length} ${c.members.length === 1 ? "person" : "people"}`,
};

function calendarRow(c) {
  const said = typeof KIND_SAID[c.kind] === "function" ? KIND_SAID[c.kind](c) : KIND_SAID[c.kind];
  return `<a class="row has-icon" href="#/calendarinfo/${encodeURIComponent(c.slug)}">
    <span class="icon"><i class="dot ${`c-${c.colour}`}"></i></span>
    <span class="main"><span class="title">${esc(c.name)}</span>
      <span class="meta"><span class="preview">${esc(said)}</span></span></span>
    ${icons.chevronRight}</a>`;
}

async function renderCalendars() {
  await loadCalendars();
  const mine = calendars.filter((c) => c.kind === "personal");
  const shared = calendars.filter((c) => c.kind === "shared");
  const open = calendars.filter((c) => c.kind === "public");
  const group = (label, rows) => (rows.length
    ? `<p class="group-label">${label}</p><div class="group">${rows.map(calendarRow).join("")}</div>` : "");

  app.innerHTML = nav({ back: "#/calendar", backLabel: "Calendar", title: "Calendars" }) + `
    <main>
      ${heading("Calendars", `<button class="compose" aria-label="New calendar">${icons.compose}</button>`)}
      ${group("Yours", mine)}${group("Shared", shared)}${group("Everybody's", open)}
    </main>`;
  wireShell();
  app.querySelector(".heading .compose").addEventListener("click", () => { location.hash = "#/calendarnew"; });
}

async function renderNewCalendar() {
  people = await api("GET", "/api/calendar/people");
  app.innerHTML = nav({ back: "#/calendars", backLabel: "Calendars", title: "New calendar" }) + `
    <main>
      <h1 class="large">New calendar</h1>
      <form class="new-calendar">
        <div class="group">
          <label class="row"><input name="name" placeholder="Household"
            autocapitalize="sentences" required></label>
        </div>
        <p class="group-label">Who can see it</p>
        <div class="group kinds">
          <label class="row"><input type="radio" name="kind" value="shared" checked>
            <span class="main"><span class="title">Shared</span>
            <span class="meta"><span class="preview">Only the people you pick. They are added, not invited.</span></span></span></label>
          <label class="row"><input type="radio" name="kind" value="public">
            <span class="main"><span class="title">Everybody's</span>
            <span class="meta"><span class="preview">Everyone here sees it, and can put things in it.</span></span></span></label>
        </div>
        <div class="who-list">
          <p class="group-label">People</p>
          <div class="group">${people.map((p) => `
            <label class="row"><input type="checkbox" name="member" value="${esc(p.username)}">
              <span class="main">${esc(p.display_name || p.username)}</span></label>`).join("")
            || `<p class="empty"><b>Nobody else yet</b>Make an account for them first.</p>`}</div>
        </div>
        <div class="group"><button class="row primary" type="submit">Make the calendar</button></div>
      </form>
    </main>`;
  wireShell();

  const form = app.querySelector("form.new-calendar");
  const whoList = app.querySelector(".who-list");
  const showWho = () => { whoList.hidden = form.elements.kind.value !== "shared"; };
  for (const radio of form.querySelectorAll('input[name="kind"]')) {
    radio.addEventListener("change", showWho);
  }
  showWho();

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = form.elements.name.value.trim();
    if (!name) return;
    const members = [...form.querySelectorAll('input[name="member"]:checked')].map((b) => b.value);
    try {
      const made = await api("POST", "/api/calendar/calendars", {
        name, kind: form.elements.kind.value, members,
      });
      calendars = [];
      store.set("calendar.in", made.slug);
      replace("#/calendarinfo/" + encodeURIComponent(made.slug));
      renderRoute();
    } catch (err) { toast(err.message); }
  });
}

// -- a calendar's own page ---------------------------------------------------------------
const COLOURS = ["cyan", "violet", "green", "amber", "rose"];

async function renderCalendarInfo(slug) {
  const calendar = await api("GET", calendarUrl(slug));
  people = calendar.kind === "personal" ? [] : await api("GET", "/api/calendar/people");
  const outside = people.filter((p) => !calendar.members.includes(p.username));
  const said = typeof KIND_SAID[calendar.kind] === "function"
    ? KIND_SAID[calendar.kind](calendar) : KIND_SAID[calendar.kind];

  app.innerHTML = nav({ back: "#/calendars", backLabel: "Calendars", title: calendar.name }) + `
    <main>
      <h1 class="large">${esc(calendar.name)}</h1>
      <div class="group">
        <div class="row"><span class="main">Who can see it</span><span class="said">${esc(said)}</span></div>
        ${calendar.owner ? `<div class="row"><span class="main">Made by</span><span class="said">${esc(calendar.owner)}</span></div>` : ""}
        <div class="row"><span class="main">Events</span><span class="said">${calendar.events}</span></div>
      </div>
      ${calendar.mine ? `<p class="group-label">Colour</p>
        <div class="group"><div class="row colours">${COLOURS.map((colour) =>
          `<button class="swatch c-${colour}${colour === calendar.colour ? " on" : ""}"
             data-colour="${colour}" aria-label="${colour}"></button>`).join("")}</div></div>` : ""}
      <p class="group-label">In it (${calendar.members.length})</p>
      <div class="group members">${calendar.members.map((who) =>
        `<div class="row"><span class="avatar" aria-hidden="true">${esc(who.charAt(0).toUpperCase())}</span>
         <span class="main">${esc(who)}${who === session.user ? " (you)" : ""}</span></div>`).join("")}</div>
      ${calendar.kind === "shared" && outside.length ? `
        <p class="group-label">Share it with</p>
        <div class="group">${outside.map((p) => `
          <button class="row add-who" data-who="${esc(p.username)}">
            <span class="main">${esc(p.display_name || p.username)}</span>
            <span class="said">Add</span></button>`).join("")}</div>` : ""}
      ${calendar.kind === "shared" && !calendar.mine
        ? `<div class="group"><button class="row bad leave">Leave this calendar</button></div>` : ""}
      ${calendar.mine && calendar.kind !== "personal"
        ? `<div class="group"><button class="row bad delete">Delete this calendar</button></div>` : ""}
    </main>`;
  wireShell();

  for (const swatch of app.querySelectorAll(".swatch")) {
    swatch.addEventListener("click", async () => {
      try {
        await api("PATCH", calendarUrl(slug), { colour: swatch.dataset.colour });
        calendars = [];
        renderCalendarInfo(slug);
      } catch (err) { toast(err.message); }
    });
  }
  for (const button of app.querySelectorAll(".add-who")) {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await api("POST", calendarUrl(slug) + "/members", { usernames: [button.dataset.who] });
        toast(`${button.dataset.who} is in`);
        renderCalendarInfo(slug);
      } catch (err) { toast(err.message); button.disabled = false; }
    });
  }
  const leave = app.querySelector(".leave");
  if (leave) {
    leave.addEventListener("click", async () => {
      if (!confirm(`Leave ${calendar.name}? You will stop seeing what is on it.`)) return;
      try {
        await api("POST", calendarUrl(slug) + "/leave");
        calendars = [];
        replace("#/calendars");
        renderRoute();
      } catch (err) { toast(err.message); }
    });
  }
  const remove = app.querySelector(".delete");
  if (remove) {
    remove.addEventListener("click", async () => {
      if (!confirm(`Delete ${calendar.name}? Everything on it goes too, for everybody.`)) return;
      try {
        await api("DELETE", calendarUrl(slug));
        calendars = [];
        replace("#/calendars");
        renderRoute();
      } catch (err) { toast(err.message); }
    });
  }
}

// -- what this feature adds to the app -------------------------------------------------------
registerScreen("calendar", renderMonth);
registerScreen("event", renderEvent);
registerScreen("eventnew", renderNewEvent);
registerScreen("eventedit", renderEditEvent);
registerScreen("calendars", renderCalendars);
registerScreen("calendarnew", renderNewCalendar);
registerScreen("calendarinfo", renderCalendarInfo);
registerTab({
  name: "calendar",
  feature: "calendar",
  label: "Calendar",
  icon: pixelIcon("calendar"),
  // Tapping the tab you are on comes back to today, which is what a
  // calendar's own icon does everywhere else.
  href: () => "#/calendar",
});
onSignOut(() => { calendars = []; people = []; });
