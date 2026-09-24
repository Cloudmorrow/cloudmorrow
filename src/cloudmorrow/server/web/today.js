/* Today: the front page. The time, the weather, a line to think on, and
   what the calendar has for the day — the four things worth a glance
   before you go into any of the tabs.

   The clock is the phone's own and ticks here; the rest is one call to
   `/api/today`, which the server answers from its config (where the
   weather is for) and its list of quotes (which one is the day's). The
   events are the calendar's, asked for the way its own screen asks, and
   left out altogether when that tab is switched off. */

import {
  api, app, esc, featureOff, heading, nav, pixelArt, pixelIcon, registerScreen, registerTab,
  setHome, tabs, wireShell,
} from "./core.js";

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

// The calendar's own row, fetched when it is first wanted rather than
// imported at the top: a module evaluates the moment it is imported, and
// the calendar's tab would then be registered before this one.
const calendar = () => import("./calendar.js");

async function eventsSection(events) {
  if (events === null) return "";   // the calendar is switched off, or unreachable
  const { eventRow, inOrder } = await calendar();
  const rows = inOrder(events);
  return `<p class="group-label on-today">On today <a href="#/calendar">Calendar</a></p>` + (
    rows.length
      ? `<div class="group">${rows.map(eventRow).join("")}</div>`
      : `<p class="empty small"><b>Nothing on</b>The day is yours.</p>`);
}

// -- the screen -------------------------------------------------------------------
async function renderToday() {
  const [todayResult, eventsResult] = await Promise.allSettled([
    api("GET", "/api/today"),
    featureOff("calendar") ? Promise.resolve(null) : api("GET", "/api/calendar/events"),
  ]);
  const today = todayResult.status === "fulfilled" ? todayResult.value : null;
  const events = eventsResult.status === "fulfilled" ? eventsResult.value : null;
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
      ${await eventsSection(events)}
    </main>` + tabs("today");
  wireShell();
  startClock(app.querySelector(".clock .time"), app.querySelector(".clock .date"));
}

registerScreen("today", renderToday);
registerTab({ name: "today", label: "Today", icon: pixelIcon("today"), href: () => "#/today" });
// Where an empty address goes: here, before any tab. Not a feature, so
// nobody's switch takes it away.
setHome("today");
