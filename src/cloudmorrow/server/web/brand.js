/* /brand — the look Cloudmorrow wears, painted rather than described.

   It began as three proposals side by side. The brand guide (in the
   cloudmorrow-web repository: brand/index.html and brand/tokens.css) chose
   between them: CATHODE's glass, with the blue of the cloud and the amber
   of the hedgehog in place of its cyan and violet. What is left here is
   that one look, as the app, the CLI and the terminal app have it. The
   other two are in the history.

   The page is deliberately standalone: it imports nothing from core.js and
   needs no sign-in, so it can be opened on a phone and shown to somebody
   without touching the app. The look is one entry in THEMES below, and
   everything on the page — swatches, mockups, contrast figures, the
   palette.py and CSS it matches — is generated from that entry, so there
   is no second copy of a colour here to drift out of step.

   The idea being tested: pixels for the marks, real type for the words. The
   wordmark and the headings are drawn dot by dot from a 5x7 font, because
   that is the retro bit worth keeping; everything you actually read is set
   in the system's own faces, because a pixel font at 15px is a crossword. */

// -- the 5x7 font ------------------------------------------------------------------
// The eleven letters of CLOUDMORROW are copied from core.js so the mark on this
// page is the mark in the app; the rest are drawn to match — round letters
// keep their corners off, stems are one dot wide, every glyph is five wide
// and seven tall. If a theme wins, this block is what moves into core.js.
const FONT = {
  A: [".XXX.", "X...X", "X...X", "XXXXX", "X...X", "X...X", "X...X"],
  B: ["XXXX.", "X...X", "X...X", "XXXX.", "X...X", "X...X", "XXXX."],
  C: [".XXX.", "X...X", "X....", "X....", "X....", "X...X", ".XXX."],
  D: ["XXX..", "X..X.", "X...X", "X...X", "X...X", "X..X.", "XXX.."],
  E: ["XXXXX", "X....", "X....", "XXXX.", "X....", "X....", "XXXXX"],
  F: ["XXXXX", "X....", "X....", "XXXX.", "X....", "X....", "X...."],
  G: [".XXX.", "X...X", "X....", "X.XXX", "X...X", "X...X", ".XXX."],
  H: ["X...X", "X...X", "X...X", "XXXXX", "X...X", "X...X", "X...X"],
  I: ["XXXXX", "..X..", "..X..", "..X..", "..X..", "..X..", "XXXXX"],
  J: ["..XXX", "...X.", "...X.", "...X.", "...X.", "X..X.", ".XX.."],
  K: ["X...X", "X..X.", "X.X..", "XX...", "X.X..", "X..X.", "X...X"],
  L: ["X....", "X....", "X....", "X....", "X....", "X....", "XXXXX"],
  M: ["X...X", "XX.XX", "X.X.X", "X.X.X", "X...X", "X...X", "X...X"],
  N: ["X...X", "XX..X", "X.X.X", "X..XX", "X...X", "X...X", "X...X"],
  O: [".XXX.", "X...X", "X...X", "X...X", "X...X", "X...X", ".XXX."],
  P: ["XXXX.", "X...X", "X...X", "XXXX.", "X....", "X....", "X...."],
  Q: [".XXX.", "X...X", "X...X", "X...X", "X.X.X", "X..X.", ".XX.X"],
  R: ["XXXX.", "X...X", "X...X", "XXXX.", "X.X..", "X..X.", "X...X"],
  S: [".XXXX", "X....", "X....", ".XXX.", "....X", "....X", "XXXX."],
  T: ["XXXXX", "..X..", "..X..", "..X..", "..X..", "..X..", "..X.."],
  U: ["X...X", "X...X", "X...X", "X...X", "X...X", "X...X", ".XXX."],
  V: ["X...X", "X...X", "X...X", "X...X", "X...X", ".X.X.", "..X.."],
  W: ["X...X", "X...X", "X...X", "X.X.X", "X.X.X", "XX.XX", "X...X"],
  X: ["X...X", "X...X", ".X.X.", "..X..", ".X.X.", "X...X", "X...X"],
  Y: ["X...X", "X...X", ".X.X.", "..X..", "..X..", "..X..", "..X.."],
  Z: ["XXXXX", "....X", "...X.", "..X..", ".X...", "X....", "XXXXX"],
  0: [".XXX.", "X..XX", "X.X.X", "X.X.X", "X.X.X", "XX..X", ".XXX."],
  1: ["..X..", ".XX..", "..X..", "..X..", "..X..", "..X..", ".XXX."],
  2: [".XXX.", "X...X", "....X", "...X.", "..X..", ".X...", "XXXXX"],
  3: ["XXXXX", "...X.", "..XX.", "....X", "....X", "X...X", ".XXX."],
  4: ["...X.", "..XX.", ".X.X.", "X..X.", "XXXXX", "...X.", "...X."],
  5: ["XXXXX", "X....", "XXXX.", "....X", "....X", "X...X", ".XXX."],
  6: ["..XX.", ".X...", "X....", "XXXX.", "X...X", "X...X", ".XXX."],
  7: ["XXXXX", "....X", "...X.", "..X..", ".X...", ".X...", ".X..."],
  8: [".XXX.", "X...X", "X...X", ".XXX.", "X...X", "X...X", ".XXX."],
  9: [".XXX.", "X...X", "X...X", ".XXXX", "....X", "...X.", ".XX.."],
  ".": [".....", ".....", ".....", ".....", ".....", "..XX.", "..XX."],
  "-": [".....", ".....", ".....", ".XXX.", ".....", ".....", "....."],
  "/": ["....X", "....X", "...X.", "..X..", ".X...", "X....", "X...."],
  "'": ["..X..", "..X..", ".....", ".....", ".....", ".....", "....."],
  "!": ["..X..", "..X..", "..X..", "..X..", "..X..", ".....", "..X.."],
  "?": [".XXX.", "X...X", "....X", "...X.", "..X..", ".....", "..X.."],
};

// A word in dots. `fill` is a paint — a colour or a url(#id) at a gradient —
// and the viewBox is in dot units, so the caller sizes it with CSS alone and
// the mark stays crisp at any size without a single raster asset.
let markSeq = 0;
function pixelWord(text, paint) {
  // One group of dots per letter, so a two-tone fill can split between two
  // of them rather than halfway through a stem.
  const letters = [];
  let x = 0;
  for (const ch of [...text.toUpperCase()]) {
    if (ch === " ") { x += 3; continue; }
    const glyph = FONT[ch];
    if (!glyph) continue;
    let dots = "";
    glyph.forEach((row, y) => {
      [...row].forEach((cell, dx) => {
        if (cell === "X") dots += `<rect x="${x + dx + 0.08}" y="${y + 0.08}" width="0.84" height="0.84" rx="0.16"/>`;
      });
    });
    letters.push(dots);
    x += 6;
  }
  const width = Math.max(x - 1, 1);

  let defs = "";
  let body;
  if (paint.stops) {
    // Each gradient needs an id of its own; two marks sharing one would
    // share a single paint.
    const id = `g${++markSeq}`;
    defs = `<defs><linearGradient id="${id}" x1="0" y1="0" x2="1" y2="0.6">` +
      paint.stops.map((c, i) => `<stop offset="${(i / (paint.stops.length - 1) * 100).toFixed(0)}%" stop-color="${c}"/>`).join("") +
      `</linearGradient></defs>`;
    body = `<g fill="url(#${id})">${letters.join("")}</g>`;
  } else if (paint.split) {
    body = `<g fill="${paint.a}">${letters.slice(0, paint.split).join("")}</g>` +
      `<g fill="${paint.b}">${letters.slice(paint.split).join("")}</g>`;
  } else {
    body = `<g fill="${paint.color}">${letters.join("")}</g>`;
  }
  return `<svg class="mark" viewBox="0 0 ${width} 7" role="img" aria-label="${text}">${defs}${body}</svg>`;
}

// Three ways to fill a mark.
//
// A gradient that is a pleasure on the thin strokes of the ASCII banner can
// be painful across a wordmark, because the wordmark is a dense field of
// dots rather than a few hairlines — and a wide hue arc on a dark ground
// (cyan at one end, magenta at the other) makes the two ends focus at
// different apparent depths, so the eye never settles. Hence `markGradient`:
// the same idea walked back to a short arc at lower chroma, for the big
// marks only. The page's own gradient is untouched and still runs across
// the banner, the ramp and the chips, where it does no harm.
const markStops = (t) => t.markGradient || t.gradient;
const MARK_STYLES = {
  gradient: { label: "Gradient", note: "short arc, lower chroma", paint: (t) => ({ stops: markStops(t) }) },
  flat: { label: "Flat", note: "the accent, nothing else", paint: (t) => ({ color: t.colors.ACCENT }) },
  // CLOUD|MORROW: the two words, each in one colour.
  twoTone: { label: "Two tone", note: "CLOUD, then MORROW", paint: (t) => ({ split: 5, a: t.colors.ACCENT, b: t.colors.SECOND }) },
};
const themeMark = (t, text = "CLOUDMORROW") => pixelWord(text, MARK_STYLES[t.markStyle].paint(t));

// -- the icons ---------------------------------------------------------------------
// The same dots as the font, on an 8x8 grid because a glyph needs the extra
// room a letter does not. Outlines one dot thick, to match the weight of the
// type beside them. Six, which is every place the app can take you.
const ICONS = {
  notes: [
    "XXXXXXXX",
    "X......X",
    "X.XXXX.X",
    "X......X",
    "X.XXXX.X",
    "X......X",
    "X.XXX..X",
    "XXXXXXXX",
  ],
  tasks: [
    "........",
    "......X.",
    ".....XX.",
    "X...XX..",
    "XX.XX...",
    ".XXX....",
    "..X.....",
    "........",
  ],
  files: [
    ".XXX....",
    "X...X...",
    "XXXXXXXX",
    "X......X",
    "X......X",
    "X......X",
    "X......X",
    "XXXXXXXX",
  ],
  secrets: [
    "........",
    ".XX..XX.",
    ".XX..XX.",
    "........",
    "........",
    ".XX..XX.",
    ".XX..XX.",
    "........",
  ],
  settings: [
    "...X....",
    "XXXXXXXX",
    "...X....",
    "........",
    ".....X..",
    "XXXXXXXX",
    ".....X..",
    "........",
  ],
  // Rounded at the top and with a tail under it, because the square box
  // with lines in it is already notes and these sit next to each other.
  chat: [
    ".XXXXXX.",
    "X......X",
    "X.XXXX.X",
    "X......X",
    "X.XX...X",
    "XXXXXXXX",
    "..XX....",
    ".XX.....",
  ],
  // Two hangers, a rule under them and a week of squares.
  calendar: [
    ".X....X.",
    "XXXXXXXX",
    "X......X",
    "X.XX.X.X",
    "X......X",
    "X.X.XX.X",
    "X......X",
    "XXXXXXXX",
  ],
  me: [
    "...XX...",
    "..XXXX..",
    "..XXXX..",
    "...XX...",
    "........",
    "..XXXX..",
    ".XXXXXX.",
    "XXXXXXXX",
  ],
  today: [
    "...XX...",
    "........",
    ".X.XX.X.",
    "..XXXX..",
    ".XXXXXX.",
    "XXXXXXXX",
    "........",
    "XXXXXXXX",
  ],
};

function pixelIcon(name, extraClass = "") {
  const grid = ICONS[name];
  let dots = "";
  grid.forEach((row, y) => {
    [...row].forEach((cell, x) => {
      if (cell === "X") dots += `<rect x="${x + 0.08}" y="${y + 0.08}" width="0.84" height="0.84" rx="0.16"/>`;
    });
  });
  return `<svg class="icon ${extraClass}" viewBox="0 0 8 8" fill="currentColor" aria-hidden="true">${dots}</svg>`;
}

// -- how legible a pair is ---------------------------------------------------------
// Printed on the page rather than promised in a comment: "retro but still
// functional" is a claim about contrast, so the page does the arithmetic in
// front of you. WCAG relative luminance, same as any checker.
function luminance(hex) {
  const n = parseInt(hex.slice(1), 16);
  const channels = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}
function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (hi + 0.05) / (lo + 0.05);
}
const ratio = (a, b) => contrast(a, b).toFixed(1) + ":1";
// AA is 4.5 for body text, 3.0 for large text and UI shapes.
const grade = (a, b) => (contrast(a, b) >= 4.5 ? "pass" : contrast(a, b) >= 3 ? "large" : "fail");

// -- the look --------------------------------------------------------------------------
// The slots palette.py names, because that is what the Textual theme and the
// CLI are built from. A theme that cannot fill every one of them
// is a mood board, not a theme.
const THEMES = [
  {
    key: "cloud",
    name: "CLOUD",
    lede: "The app's own blue-black glass, with the two colours of the logo: " +
      "the blue of the cloud the hedgehog sits on, and the amber of the " +
      "hedgehog. Blue is the platform — links, the tab you are on, the chosen " +
      "thing. Amber is the person — the one action on a screen, and names.",
    why: "The neutrals carry nine tenths of every screen and did not change. " +
      "Sky and Lens sit far apart in hue, so the current thing and the thing " +
      "that is yours are never confused, and warn moved from yellow to orange " +
      "so that it can never be taken for amber. Cloud is too dark to read as " +
      "text on Ink, so it is only ever a fill, with white on it.",
    colors: {
      NIGHT: "#0b0d12", INK: "#14171f", SURFACE: "#1f242e", PANEL: "#272d39",
      LINE: "#333a48", LINE_BRIGHT: "#4a5364",
      TEXT: "#dfe5f0", MUTED: "#99a1b3", FAINT: "#667085",
      DEEP: "#0a3f75", CLOUD: "#1c70b1", PUFF: "#3685bd", SKY: "#5aa6e0",
      LENS: "#e0a84c", ACTION: "#e0a84c", ACTION_INK: "#14171f",
      GOOD: "#5ce89b", WARN: "#ff9f5a", BAD: "#ff6b81",
      ACCENT: "#5aa6e0", SECOND: "#e0a84c",
    },
    // The cloud from its shadow to the sky, for the banner and the ramp.
    gradient: ["#0a3f75", "#1c70b1", "#5aa6e0"],
    // The same run started a step in, for a dense field of dots: Deep on
    // Ink is a colour you have to be told is there.
    markGradient: ["#1c70b1", "#3685bd", "#5aa6e0"],
    barGradient: ["#1c70b1", "#3685bd", "#5aa6e0"],
    // The app draws its wordmark in Sky, flat, as the guide asks.
    markStyle: "flat",
    bar: { bg: "#1c212b", ink: "#dfe5f0", muted: "#99a1b3", accent: "#5aa6e0", bad: "#ff6b81" },
    onAccent: "#14171f",
    // Blue as a fill: white on Cloud, lit to Puff, pressed to Deep.
    fill: { bg: "#1c70b1", ink: "#ffffff", hover: "#3685bd", pressed: "#0a3f75" },
    // Amber as a fill: the one action, Ink on Lens, its bottom edge Fur.
    action: { bg: "#e0a84c", ink: "#14171f", edge: "#c18635" },
    scheme: "dark",
    radius: "14px",
    radiusControl: "10px",
  },
];

// -- the mockups -----------------------------------------------------------------------
// A theme is only worth anything applied, so each one is shown twice: on the
// phone, where the app lives, and in a terminal, where the CLI and the TUI
// do. Both are dumb markup painted by the theme's own variables.

const SMALL_LOGO = [
  "  ___                  ___ _             _",
  " | _ )_ _ __ _ _ __   / __| |___ _  _ __| |",
  " | _ \\ '_/ _` | '  \\ | (__| / _ \\ || / _` |",
  " |___/_| \\__,_|_|_|_| \\___|_\\___/\\_,_\\__,_|",
].join("\n");

const NOTES = [
  ["Kitchen rebuild", "yesterday", "Ordered the worktop — 40mm oak, six weeks"],
  ["Server rack", "Tue", "Swapped the fans, 12dB quieter under load"],
  ["Reading", "12 Sep", "Finished the Le Guin, started the Gibson"],
];

function phoneMock(t) {
  const rows = NOTES.map(([title, when, preview]) => `
    <div class="m-row">
      <span class="m-chip">${pixelIcon("notes")}</span>
      <span class="m-text"><b>${title}</b><span>${when} · ${preview}</span></span>
    </div>`).join("");
  return `
    <figure class="phone">
      <div class="screen">
        <div class="m-bar">${pixelWord("CLOUDMORROW", { stops: t.barGradient })}</div>
        <div class="m-body">
          <h4 class="m-title">Notes</h4>
          <div class="m-group">${rows}</div>
          <div class="m-pills">
            <span class="m-pill on">All</span><span class="m-pill">Boards</span><span class="m-pill">Shared</span>
          </div>
        </div>
        <div class="m-tabs">${["notes", "tasks", "me"].map((name, i) =>
          `<span class="m-tab${i === 0 ? " on" : ""}">${pixelIcon(name)}` +
          `<span>${name[0].toUpperCase()}${name.slice(1)}</span></span>`).join("")}
        </div>
      </div>
      <figcaption>the app</figcaption>
    </figure>`;
}

function terminalMock() {
  return `
    <figure class="term">
      <div class="screen">
        <div class="t-bar"><span class="t-dot"></span><span class="t-dot"></span><span class="t-dot"></span>
          <span class="t-name">cloudmorrow — zsh</span></div>
        <pre class="t-body"><span class="t-logo">${SMALL_LOGO}</span>
<span class="t-dim">own your data, choose your apps   ·   v0.9.2</span>

<span class="t-accent">❯</span> cloudmorrow status
<span class="t-accent">◈ cloudmorrow</span>  <span class="t-dim">up 6d 4h</span>            <span class="t-second">nuc.bram.cloud</span>
  notes      <span class="t-text">128</span> <span class="t-dim">synced, 2s ago</span>
  tasks      <span class="t-text">14</span> <span class="t-dim">open,</span> <span class="t-warn">3 overdue</span>
  machines   <span class="t-good">3 online</span><span class="t-dim">, 1 idle</span>
<span class="t-good">✓</span> everything in sync
<span class="t-bad">✗</span> backup.bram.cloud unreachable

<span class="t-accent">❯</span> <span class="t-cursor"> </span></pre>
      </div>
      <figcaption>the CLI and the TUI</figcaption>
    </figure>`;
}

// -- where it is ----------------------------------------------------------------------
// The two places the look is declared, as this page would write them. Generated
// from the theme, and held to palette.py and base.css by tests/test_brand_page.py,
// so what is shown is what the app has.
const SLOTS = ["NIGHT", "INK", "SURFACE", "PANEL", "LINE", "LINE_BRIGHT", "TEXT", "MUTED",
  "FAINT", "DEEP", "CLOUD", "PUFF", "SKY", "LENS", "ACTION", "ACTION_INK",
  "GOOD", "WARN", "BAD", "ACCENT", "SECOND"];
const SLOT_NOTES = {
  NIGHT: "behind the logo", INK: "the page", SURFACE: "panels on it", PANEL: "panels on those",
  LINE: "borders", LINE_BRIGHT: "borders that want noticing", TEXT: "",
  MUTED: "second text", FAINT: "labels, times", DEEP: "cloud in shadow: pressed",
  CLOUD: "the blue fill, white on it", PUFF: "cloud, lit: hover", SKY: "blue as text: where you are",
  LENS: "the one action, and names", ACTION: "", ACTION_INK: "text on the action",
  GOOD: "", WARN: "orange, never amber", BAD: "",
  ACCENT: "the old name for Sky", SECOND: "the old name for Lens",
};

function pythonFor(t) {
  const width = Math.max(...SLOTS.map((s) => s.length));
  const lines = SLOTS.map((slot) => {
    const note = SLOT_NOTES[slot];
    const left = `${slot.padEnd(width)} = "${t.colors[slot]}"`;
    return note ? `${left.padEnd(width + 13)}# ${note}` : left;
  });
  const gradients = `\n\n# The banner is tinted across these, dark end first.\nGRADIENT = (\n` +
    t.gradient.map((c) => `    "${c}",`).join("\n") + `\n)\n` + (t.markGradient ? (
      `\n# The wordmark across these: the same idea at a shorter hue arc and\n` +
      `# lower chroma, because a dense field of dots vibrates where a few\n` +
      `# hairlines of the same colours do not.\nMARK_GRADIENT = (\n` +
      t.markGradient.map((c) => `    "${c}",`).join("\n") + `\n)\n`) : "");
  return `# src/cloudmorrow/palette.py — ${t.name.toLowerCase()}\n\n` + lines.join("\n") + gradients;
}

// A theme without a fill or an action of its own fills with its accent.
const fillOf = (t) => t.fill ||
  { bg: t.colors.ACCENT, ink: t.onAccent, hover: t.colors.ACCENT, pressed: t.colors.ACCENT };
const actionOf = (t) => t.action || { bg: t.colors.ACCENT, ink: t.onAccent, edge: t.colors.ACCENT };

function cssFor(t) {
  const c = t.colors;
  return `/* src/cloudmorrow/server/web/base.css — ${t.name.toLowerCase()} */\n:root {\n` +
    `  --bg: ${c.INK};\n  --card: ${c.SURFACE};\n  --card-2: ${c.PANEL};\n` +
    `  --line: ${c.LINE};\n  --line-bright: ${c.LINE_BRIGHT};\n` +
    `  --ink: ${c.TEXT};\n  --muted: ${c.MUTED};\n` +
    `  --accent: ${c.ACCENT};\n  --accent-ink: ${t.onAccent};\n` +
    `  --fill: ${fillOf(t).bg};\n  --fill-ink: ${fillOf(t).ink};\n` +
    `  --fill-hover: ${fillOf(t).hover};\n  --fill-pressed: ${fillOf(t).pressed};\n` +
    `  --action: ${actionOf(t).bg};\n  --action-ink: ${actionOf(t).ink};\n` +
    `  --action-edge: ${actionOf(t).edge};\n  --second: ${c.SECOND};\n` +
    `  --field: ${c.PANEL};\n` +
    `  --good: ${c.GOOD};\n  --warn: ${c.WARN};\n  --bad: ${c.BAD};\n` +
    `  --bar: ${t.bar.bg};\n  --bar-ink: ${t.bar.ink};\n` +
    `  --bar-muted: ${t.bar.muted};\n  --bar-accent: ${t.bar.accent};\n` +
    `  --bar-bad: ${t.bar.bad};\n` +
    `  --brand: linear-gradient(100deg, ${t.gradient.join(", ")});\n` +
    `  --brand-mark: linear-gradient(100deg, ${markStops(t).join(", ")});\n` +
    `  --brand-bar: linear-gradient(100deg, ${t.barGradient.join(", ")});\n` +
    `  --radius: ${t.radius};\n  --radius-control: ${t.radiusControl || t.radius};\n` +
    `  color-scheme: ${t.scheme};\n}\n`;
}

// -- putting a theme on the page -----------------------------------------------------
function swatches(t) {
  return SLOTS.map((slot) => {
    const value = t.colors[slot];
    // Light chips get dark type and the other way round, so every chip can
    // print its own hex on itself.
    const on = contrast(value, "#ffffff") >= contrast(value, "#000000") ? "#ffffff" : "#000000";
    return `<div class="swatch" style="background:${value};color:${on}">
      <b>${slot}</b><code>${value}</code></div>`;
  }).join("");
}

function readouts(t) {
  const c = t.colors;
  const pairs = [
    ["TEXT on INK", c.TEXT, c.INK],
    ["MUTED on INK", c.MUTED, c.INK],
    ["ACCENT on INK", c.ACCENT, c.INK],
    ["SECOND on SURFACE", c.SECOND, c.SURFACE],
    ["white on the blue fill", fillOf(t).ink, fillOf(t).bg],
    ["ink on the action", actionOf(t).ink, actionOf(t).bg],
    ["WARN on INK", c.WARN, c.INK],
    ["BAD on INK", c.BAD, c.INK],
  ];
  return pairs.map(([label, a, b]) =>
    `<li class="${grade(a, b)}"><span>${label}</span><b>${ratio(a, b)}</b></li>`).join("");
}

function section(t) {
  const c = t.colors;
  const el = document.createElement("section");
  el.className = "theme";
  el.id = t.key;
  // Everything below paints from these; nothing in brand.css names a colour.
  const vars = {
    "--bg": c.INK, "--card": c.SURFACE, "--card-2": c.PANEL,
    "--line": c.LINE, "--line-bright": c.LINE_BRIGHT,
    "--text": c.TEXT, "--muted": c.MUTED,
    "--accent": c.ACCENT, "--accent-ink": t.onAccent, "--second": c.SECOND,
    "--fill": fillOf(t).bg, "--fill-ink": fillOf(t).ink,
    "--good": c.GOOD, "--warn": c.WARN, "--bad": c.BAD,
    "--bar": t.bar.bg, "--bar-ink": t.bar.ink,
    "--bar-muted": t.bar.muted, "--bar-accent": t.bar.accent,
    "--radius": t.radius,
    "--brand": `linear-gradient(100deg, ${t.gradient.join(", ")})`,
    "--brand-mark": `linear-gradient(100deg, ${markStops(t).join(", ")})`,
    "--brand-bar": `linear-gradient(100deg, ${t.barGradient.join(", ")})`,
    "--glow-a": markStops(t)[0], "--glow-b": markStops(t)[markStops(t).length - 1],
  };
  for (const [k, v] of Object.entries(vars)) el.style.setProperty(k, v);

  el.innerHTML = `
    <div class="wrap">
      <header class="t-head">
        <h2>${themeMark(t, t.name)}<span class="sr">${t.name}</span></h2>
        <p class="lede">${t.lede}</p>
        <div class="ramp" aria-hidden="true"></div>
      </header>

      <div class="mocks">${phoneMock(t)}${terminalMock()}</div>

      <div class="panel">
        <h3>The icons</h3>
        <p class="note">Drawn on the same dots as the letters, eight across instead of
          five — a glyph needs the room a letter does not. Outlines one dot thick, so
          they carry the same weight as the type they sit beside.</p>
        <div class="icon-row">${Object.keys(ICONS).map((name) =>
          `<div class="icon-try">${pixelIcon(name)}<b>${name[0].toUpperCase()}${name.slice(1)}</b></div>`).join("")}</div>
      </div>

      <div class="panel">
        <h3>The mark</h3>
        <p class="note">The app's own 5×7 dot letters. In the app they are Sky, flat,
          which is what the guide asks for anywhere the mark is small or sits in a bar;
          the gradient is the cloud's, from shadow to sky, for the banner and the ramp.
          Three ways to fill it:</p>
        <div class="mark-row">${Object.entries(MARK_STYLES).map(([key, style]) => `
          <div class="mark-try${key === t.markStyle ? " on" : ""}">
            <div class="mark-box">${pixelWord("CLOUDMORROW", style.paint(t))}</div>
            <b>${style.label}</b><span>${style.note}</span>
          </div>`).join("")}</div>
      </div>

      <div class="panel">
        <h3>The slots</h3>
        <p class="note">The names are the ones <code>palette.py</code> uses, so this is the
          same palette the TUI reads through its Textual theme and the CLI imports
          directly. ACCENT and SECOND are the old names, kept so nothing had to be
          renamed; they are Sky and Lens.</p>
        <div class="swatches">${swatches(t)}</div>
      </div>

      <div class="split">
        <div class="panel">
          <h3>Still readable</h3>
          <p class="note">${t.why}</p>
          <ul class="readouts">${readouts(t)}</ul>
          <p class="key"><b class="pass">4.5:1+</b> body text · <b class="large">3:1+</b> large text and shapes</p>
        </div>
        <div class="panel code">
          <h3>Where it is</h3>
          <div class="codetabs" role="tablist">
            <button role="tab" aria-selected="true" data-code="py">palette.py</button>
            <button role="tab" aria-selected="false" data-code="css">base.css</button>
            <button class="copy" type="button">Copy</button>
          </div>
          <pre data-py="${escapeAttr(pythonFor(t))}" data-css="${escapeAttr(cssFor(t))}"></pre>
        </div>
      </div>
    </div>`;
  return el;
}

const escapeAttr = (s) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");

// -- wiring ------------------------------------------------------------------------------
function wireCode(root) {
  for (const panel of root.querySelectorAll(".panel.code")) {
    const pre = panel.querySelector("pre");
    const show = (which) => {
      pre.textContent = pre.dataset[which];
      for (const tab of panel.querySelectorAll("[data-code]")) {
        tab.setAttribute("aria-selected", String(tab.dataset.code === which));
      }
    };
    show("py");
    for (const tab of panel.querySelectorAll("[data-code]")) {
      tab.addEventListener("click", () => show(tab.dataset.code));
    }
    const copy = panel.querySelector(".copy");
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(pre.textContent);
        copy.textContent = "Copied";
      } catch {
        // No clipboard over plain http on a phone; select it so a long-press works.
        const range = document.createRange();
        range.selectNodeContents(pre);
        getSelection().removeAllRanges();
        getSelection().addRange(range);
        copy.textContent = "Selected";
      }
      setTimeout(() => { copy.textContent = "Copy"; }, 1600);
    });
  }
}

function build() {
  document.querySelector(".hero .mark-slot").innerHTML =
    pixelWord("CLOUDMORROW", { color: THEMES[0].colors.SKY });
  const jump = document.querySelector(".jump");
  const main = document.querySelector("main");
  for (const t of THEMES) {
    jump.insertAdjacentHTML("beforeend",
      `<a href="#${t.key}" style="--a:${t.gradient[0]};--b:${t.gradient[t.gradient.length - 1]}">${t.name}</a>`);
    main.append(section(t));
  }
  wireCode(main);
}

build();
