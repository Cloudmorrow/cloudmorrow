/* /brand — three ways Cloudmorrow could look, painted rather than described.

   The page is deliberately standalone: it imports nothing from core.js and
   needs no sign-in, so it can be opened on a phone, shown to somebody, and
   thrown away without touching the app. Each theme is one entry in THEMES
   below; everything on the page — swatches, mockups, contrast figures, the
   palette.py and CSS to paste — is generated from that entry, so there is
   no second copy of a colour anywhere to drift out of step.

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

// -- the three -----------------------------------------------------------------------
// Twelve slots, because that is exactly what palette.py already names and
// what the Textual theme is built from. A theme that cannot fill all twelve
// is a mood board, not a theme.
const THEMES = [
  {
    key: "cathode",
    name: "CATHODE",
    lede: "A colour monitor at two in the morning. Blue-black glass, phosphor " +
      "cyan for the thing you are on, and a gradient that runs cyan through " +
      "indigo into magenta across the banner, the ramp and the tabs.",
    why: "The retro is in the glow, not in the shapes — so nothing has to be " +
      "hard to read to earn it. Cyan and violet sit far apart in hue, which " +
      "keeps “the current thing” and “a link” from ever being confused. The " +
      "wordmark is the one place that arc is walked back: 154° of hue across " +
      "a dense field of dots on a dark ground is what makes a logo hard to " +
      "look at, so it gets 59° at half the chroma instead.",
    colors: {
      INK: "#14171f", SURFACE: "#1f242e", PANEL: "#272d39",
      LINE: "#333a48", LINE_BRIGHT: "#4a5364",
      TEXT: "#dfe5f0", MUTED: "#99a1b3",
      ACCENT: "#4fe3d7", SECOND: "#a78bfa",
      GOOD: "#5ce89b", WARN: "#ffc857", BAD: "#ff6b81",
    },
    gradient: ["#4fe3d7", "#7c8cf8", "#f472b6"],
    // Untouched: on the banner's hairlines and the ramp it is the best thing
    // here. It is only the dense fields it cannot be trusted with.
    markGradient: ["#3fbdb4", "#4886c9", "#6d74c6"],
    barGradient: ["#4fe3d7", "#7c8cf8", "#f472b6"],
    markStyle: "gradient",
    bar: { bg: "#1c212b", ink: "#dfe5f0", muted: "#99a1b3", accent: "#4fe3d7", bad: "#ff6b81" },
    onAccent: "#0e1117",
    scheme: "dark",
    radius: "14px",
  },
  {
    key: "amber",
    name: "AMBER DECK",
    lede: "The warm one. An amber phosphor terminal bolted to a 1970s hi-fi: " +
      "tobacco-dark panels, an orange accent, and one cold teal so that names " +
      "and links have somewhere to stand.",
    why: "Warm palettes usually fall apart at the status colours, because " +
      "amber, gold and red all crowd together. This one spends its cold end " +
      "on SECOND and keeps WARN a pale gold, well clear of the orange accent.",
    colors: {
      INK: "#151009", SURFACE: "#1e1810", PANEL: "#281f16",
      LINE: "#3c3022", LINE_BRIGHT: "#5c4a33",
      TEXT: "#f2e6d4", MUTED: "#a99781",
      ACCENT: "#ff8a3d", SECOND: "#5bc8b8",
      GOOD: "#8fd96b", WARN: "#f2c14e", BAD: "#ff5a5a",
    },
    gradient: ["#f2c14e", "#ff8a3d", "#e0457b"],
    barGradient: ["#f2c14e", "#ff8a3d", "#e0457b"],
    markStyle: "gradient",
    bar: { bg: "#0d0904", ink: "#f2e6d4", muted: "#a99781", accent: "#ff8a3d", bad: "#ff5a5a" },
    onAccent: "#0d0904",
    scheme: "dark",
    radius: "16px",
  },
  {
    key: "riso",
    name: "RISO",
    lede: "Daylight. Warm paper and near-black ink, with the two overprinted " +
      "inks of a risograph — a red that is almost orange, a flat process blue " +
      "— and a sun-to-violet gradient for the marks.",
    why: "It keeps the bright page you already have but drops the grey-green " +
      "cast, and it is the only one of the three that survives being read " +
      "outdoors. The bar stays ink-dark, so the frame round the page is intact.",
    colors: {
      INK: "#f5efe3", SURFACE: "#fffaf0", PANEL: "#eae2d2",
      LINE: "#d9cdb6", LINE_BRIGHT: "#b9a889",
      TEXT: "#1e1b18", MUTED: "#756c60",
      ACCENT: "#c03522", SECOND: "#2f5fb8",
      GOOD: "#2e7d4f", WARN: "#a86a06", BAD: "#b8231f",
    },
    gradient: ["#f5a623", "#e2513a", "#7b3fa0"],
    barGradient: ["#ffc25c", "#ff7f5c", "#c08ce0"],
    markStyle: "gradient",
    bar: { bg: "#26221d", ink: "#f5efe3", muted: "#a89e92", accent: "#f5a623", bad: "#ff8f7a" },
    onAccent: "#fffaf0",
    scheme: "light",
    radius: "16px",
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

// -- what you paste ---------------------------------------------------------------------
// The whole point of the page: pick one, and these two blocks are the change.
// Generated from the theme, so what you copy is what you saw.
const SLOTS = ["INK", "SURFACE", "PANEL", "LINE", "LINE_BRIGHT", "TEXT", "MUTED",
  "ACCENT", "SECOND", "GOOD", "WARN", "BAD"];
const SLOT_NOTES = {
  INK: "the page", SURFACE: "panels on it", PANEL: "panels on those",
  LINE: "borders", LINE_BRIGHT: "borders that want noticing", TEXT: "",
  MUTED: "", ACCENT: "the brand, and the current thing", SECOND: "names and links",
  GOOD: "", WARN: "", BAD: "",
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

function cssFor(t) {
  const c = t.colors;
  return `/* src/cloudmorrow/server/web/base.css — ${t.name.toLowerCase()} */\n:root {\n` +
    `  --bg: ${c.INK};\n  --card: ${c.SURFACE};\n  --card-2: ${c.PANEL};\n` +
    `  --line: ${c.LINE};\n  --line-bright: ${c.LINE_BRIGHT};\n` +
    `  --ink: ${c.TEXT};\n  --muted: ${c.MUTED};\n` +
    `  --accent: ${c.ACCENT};\n  --accent-ink: ${t.onAccent};\n  --second: ${c.SECOND};\n` +
    `  --field: ${c.PANEL};\n` +
    `  --good: ${c.GOOD};\n  --warn: ${c.WARN};\n  --bad: ${c.BAD};\n` +
    `  --bar: ${t.bar.bg};\n  --bar-ink: ${t.bar.ink};\n` +
    `  --bar-muted: ${t.bar.muted};\n  --bar-accent: ${t.bar.accent};\n` +
    `  --bar-bad: ${t.bar.bad};\n` +
    `  --brand: linear-gradient(100deg, ${t.gradient.join(", ")});\n` +
    `  --brand-mark: linear-gradient(100deg, ${markStops(t).join(", ")});\n` +
    `  --brand-bar: linear-gradient(100deg, ${t.barGradient.join(", ")});\n` +
    `  --radius: ${t.radius};\n  color-scheme: ${t.scheme};\n}\n`;
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
        <p class="note">The gradient runs everywhere it did before — across the banner
          above, the ramp, the tabs. It is only the wordmark that gets a quieter fill,
          because a wordmark is a dense field of dots rather than a few hairlines, and a
          wide hue arc across one on a dark ground never lets the eye settle. Three ways
          to fill it:</p>
        <div class="mark-row">${Object.entries(MARK_STYLES).map(([key, style]) => `
          <div class="mark-try${key === t.markStyle ? " on" : ""}">
            <div class="mark-box">${pixelWord("CLOUDMORROW", style.paint(t))}</div>
            <b>${style.label}</b><span>${style.note}</span>
          </div>`).join("")}</div>
      </div>

      <div class="panel">
        <h3>Twelve slots</h3>
        <p class="note">The names are the ones <code>palette.py</code> already uses, so a
          theme is a drop-in — the TUI reads them through the Textual theme and the CLI
          imports them directly.</p>
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
          <h3>What you paste</h3>
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
    pixelWord("CLOUDMORROW", { stops: ["#4fc4bd", "#5f8fd0", "#8f84cc"] });
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
