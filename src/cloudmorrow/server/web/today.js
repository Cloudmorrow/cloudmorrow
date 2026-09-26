/* Today: the front page. The time, the weather, a line to think on, and
   what the calendar has for the day — the four things worth a glance
   before you go into any of the tabs.

   The clock is the phone's own and ticks here; the rest is one call to
   `/api/today`, which the server answers from its config (where the
   weather is for) and its list of quotes (which one is the day's). The
   events are those of any installed Quill with a `calendar` screen, asked
   for through the record API the way that screen asks, and left out
   altogether when there is none, or it is switched off. */

import {
  api, app, esc, featureOff, heading, nav, pixelArt, pixelIcon, registerScreen, registerTab,
  setHome, tabs, wireShell,
} from "./core.js";
import { sheetHash } from "./kit.js";
import { bindingsOf, eventRow, inOrder, occasion, today as todayIso } from "./kit_calendar.js";

// -- the weather, in eight dots ----------------------------------------------
// The same drawing as the tab icons: the app's marks are pixels. The
// server names one of these for the WMO code it got, and the night gets
// the moon rather than the sun.
const SKY = {
  sun: [
    "X..XX..X",
    "........",
    "..XXXX..",
    "X.XXXX.X",
    "X.XXXX.X",
    "..XXXX..",
    "........",
    "X..XX..X",
  ],
  moon: [
    "...XXXX.",
    ".XXX....",
    "XX......",
    "XX......",
    "XX......",
    "XX......",
    ".XXX....",
    "...XXXX.",
  ],
  "part-cloud": [
    "....X..X",
    ".....XX.",
    "....XXXX",
    "..XXXX..",
    ".XXXXXX.",
    "XXXXXXX.",
    "XXXXXXX.",
    "........",
  ],
  "part-moon": [
    ".....XX.",
    "....XX..",
    "....XX.X",
    "..XXXXX.",
    ".XXXXXX.",
    "XXXXXXX.",
    "XXXXXXX.",
    "........",
  ],
  cloud: [
    "........",
    "...XXX..",
    "..XXXXX.",
    ".XXXXXXX",
    "XXXXXXXX",
    "XXXXXXXX",
    ".XXXXXX.",
    "........",
  ],
  fog: [
    "........",
    "XXXXXXXX",
    "........",
    ".XXXXXX.",
    "........",
    "XXXXXXXX",
    "........",
    ".XXXX...",
  ],
  rain: [
    "...XXX..",
    ".XXXXXX.",
    "XXXXXXXX",
    ".XXXXXX.",
    "........",
    ".X..X..X",
    "X..X..X.",
    "........",
  ],
  sleet: [
    "...XXX..",
    ".XXXXXX.",
    "XXXXXXXX",
    ".XXXXXX.",
    "........",
    ".X..X..X",
    "........",
    "X..X..X.",
  ],
  snow: [
    "...XXX..",
    ".XXXXXX.",
    "XXXXXXXX",
    ".XXXXXX.",
    "........",
    "X..X..X.",
    "........",
    "..X..X.X",
  ],
  storm: [
    "...XXX..",
    ".XXXXXX.",
    "XXXXXXXX",
    ".XXXXXX.",
    "....X...",
    "...XX...",
    "....X...",
    "...X....",
  ],
};
const sky = (glyph) => pixelArt(SKY[glyph] || SKY.cloud, "pixel-icon sky");

// -- the clock ---------------------------------------------------------------
// One interval for the page, started when it is drawn and stopped the
// moment its elements are gone: a screen that is not on the page has no
// business ticking.
let ticker = null;
const timeNow = () => new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
const dateNow = () => new Date().toLocaleDateString(undefined, {
  weekday: "long", day: "numeric", month: "long", year: "numeric",
});

function startClock(timeEl, dateEl) {
  clearInterval(ticker);
  ticker = setInterval(() => {
    if (!app.contains(timeEl)) { clearInterval(ticker); ticker = null; return; }
    const time = timeNow();
    if (timeEl.textContent !== time) timeEl.textContent = time;
    const date = dateNow();
    if (dateEl.textContent !== date) dateEl.textContent = date;
  }, 1000);
}

// -- the cards ----------------------------------------------------------------
const degrees = (n) => (n == null ? "–" : `${Math.round(n)}°`);

function weatherCard(today) {
  if (!today) {
    return `<div class="card weather off"><b>Weather</b><span>Could not reach the server.</span></div>`;
  }
  const w = today.weather;
  if (!w) {
    const why = today.weather_error
      ? esc(today.weather_error)
      : "Put <code>weather_place</code> in the server config and it is here.";
    return `<div class="card weather off"><b>${today.weather_error ? "No weather right now" : "No place set"}</b><span>${why}</span></div>`;
  }
  const facts = [
    w.feels_like != null && `Feels ${degrees(w.feels_like)}`,
    (w.high != null || w.low != null) && `${degrees(w.high)} / ${degrees(w.low)}`,
    w.rain_chance != null && `Rain ${Math.round(w.rain_chance)}%`,
    w.wind_ms != null && `Wind ${Math.round(w.wind_ms)} m/s`,
  ].filter(Boolean);
  const sun = w.sunrise && w.sunset ? `<span class="sun">↑ ${esc(w.sunrise)} · ↓ ${esc(w.sunset)}</span>` : "";
  return `<div class="card weather${w.stale ? " stale" : ""}">
    <div class="sky-wrap">${sky(w.glyph)}</div>
    <div class="reading">
      <span class="temp">${degrees(w.temperature)}</span>
      <span class="summary">${esc(w.summary)}${w.stale ? " · a while ago" : ""}</span>
      <span class="facts">${facts.map(esc).join(" · ")}</span>
      <span class="place">${esc(w.place)}${sun ? " · " : ""}${sun}</span>
    </div></div>`;
}

function quoteCard(today) {
  if (!today) return "";
  return `<blockquote class="card quote">
    <p>${esc(today.quote.text)}</p>
    <footer>${esc(today.quote.who)}</footer></blockquote>`;
}

// -- what is on today -----------------------------------------------------------------
// The calendar screens there are: every installed Quill's, as quills.js has
// them. Imported when asked rather than at the top: a module evaluates the
// moment it is imported, and the Quills' tabs would then come before these.
async function calendarScreens() {
  let quills = [];
  try { quills = await (await import("./quills.js")).loadQuills(); } catch { quills = []; }
  return quills.filter((q) => !featureOff(q.id)).flatMap((quill) => quill.screens
    .filter((screen) => screen.kit === "calendar" && quill.models[screen.model])
    .map((screen) => ({ quill, screen })));
}

/** Today's events from one calendar screen, drawn as its own rows are. */
async function todayFrom({ quill, screen }) {
  const b = bindingsOf(quill, screen);
  const day = todayIso();
  const at = { quill, screen };
  const base = `#/q/${encodeURIComponent(quill.id)}/${encodeURIComponent(screen.id)}`;
  const [spaces, records] = await Promise.all([
    api("GET", `/api/records/${encodeURIComponent(b.spaceModel.id)}`),
    api("GET", `/api/records/${encodeURIComponent(b.model.id)}?${encodeURIComponent(b.starts + "__lte")}=${day}T23:59` +
      `&${encodeURIComponent(b.ends + "__gte")}=${day}`),
  ]);
  const bySpace = new Map(spaces.map((s) => [s.id, s]));
  const rows = inOrder(records.map((r) => occasion(b, r, bySpace)));
  return `<p class="group-label on-today">On today <a href="${base}/${day}">${esc(screen.label || quill.name)}</a></p>` + (
    rows.length
      ? `<div class="group">${rows.map((e) => eventRow(sheetHash(at, b.model.id, e.id), e)).join("")}</div>`
      : `<p class="empty small"><b>Nothing on</b>The day is yours.</p>`);
}

async function eventsSection() {
  const drawn = await Promise.allSettled((await calendarScreens()).map(todayFrom));
  return drawn.filter((d) => d.status === "fulfilled").map((d) => d.value).join("");
}

// -- the screen -------------------------------------------------------------------
async function renderToday() {
  const [todayResult, eventsResult] = await Promise.allSettled([
    api("GET", "/api/today"),
    eventsSection(),
  ]);
  const today = todayResult.status === "fulfilled" ? todayResult.value : null;
  const events = eventsResult.status === "fulfilled" ? eventsResult.value : "";
  if (todayResult.status === "rejected") console.error(todayResult.reason);

  app.innerHTML = nav({ title: "Today" }) + `
    <main class="today">
      ${heading("Today")}
      <div class="now">
        <div class="card clock">
          <span class="time">${esc(timeNow())}</span>
          <span class="date">${esc(dateNow())}</span>
        </div>
        ${weatherCard(today)}
      </div>
      ${quoteCard(today)}
      ${events}
    </main>` + tabs("today");
  wireShell();
  startClock(app.querySelector(".clock .time"), app.querySelector(".clock .date"));
}

registerScreen("today", renderToday);
registerTab({ name: "today", label: "Today", icon: pixelIcon("today"), href: () => "#/today" });
// Where an empty address goes: here, before any tab. Not a feature, so
// nobody's switch takes it away.
setHome("today");
