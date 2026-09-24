/* The formatting bar: select some words, and the Markdown for them.

   It knows nothing about notes or tasks and neither knows about it. Both
   put their body in a `textarea.body` inside an `.editor`, and both already
   listen for `input` on it to grow the box and start the save timer — so
   this watches the document for a selection in one of those, and when it
   has made an edit it dispatches `input` and lets the editor do the rest.
   That is the whole coupling: one selector and one event.

   The edits are returned as a replacement over a range rather than a whole
   new value, so they can go in through `insertText`, which keeps the
   browser's own undo stack. Setting `.value` would throw it away, and
   undo after a mis-tap is the first thing anyone reaches for.

   Everything above the bar is a pure function of (text, start, end), which
   is what `tests/test_format.py` runs — under node, without a browser. */

// -- the marks ---------------------------------------------------------------------
// Wrapped round the selection. Order matters for the two that begin with the
// same character: a `*` must not mistake the outside of `**bold**` for its own.
const WRAPS = { bold: "**", italic: "*", strike: "~~", code: "`" };

// Put at the head of every line the selection touches. A line carries one of
// these at a time, so applying one takes off whichever is already there —
// which is what makes a bullet into a checkbox in one tap.
// `make` writes one, `has` recognises one already written — which is not the
// same question: a list that starts at 3. is still a numbered list.
const PREFIXES = {
  bullet: { make: () => "- ", has: /^[-*+] $/ },
  numbered: { make: (index) => `${index + 1}. `, has: /^\d+\. $/ },
  check: { make: () => "- [ ] ", has: /^- \[[ xX]\] $/ },
  quote: { make: () => "> ", has: /^> $/ },
};
// Anything the line prefixes may find in front of a line and should replace,
// longest first so "- [ ] " is not read as "- " with a stray box after it.
const ANY_PREFIX = /^(\s*)(- \[[ xX]\] |[-*+] |\d+\. |> )?/;
const HEADING = /^(\s*)(#{1,6} )?/;
// What a heading becomes when you ask for one again. Three is as deep as a
// note goes before the levels stop meaning anything.
const HEADING_CYCLE = ["# ", "## ", "### ", ""];

export const ACTIONS = [
  { name: "bold", label: "B", title: "Bold" },
  { name: "italic", label: "I", title: "Italic" },
  { name: "strike", label: "S", title: "Strikethrough" },
  { name: "code", label: "<>", title: "Code" },
  { name: "heading", label: "H", title: "Heading" },
  { name: "bullet", label: "•", title: "Bulleted list" },
  { name: "numbered", label: "1.", title: "Numbered list" },
  { name: "check", label: "[ ]", title: "Checklist" },
  { name: "quote", label: "“", title: "Quote" },
  { name: "link", label: "link", title: "Link" },
];

const LINK_URL = "url";

// -- the edits ---------------------------------------------------------------------
// Each returns {from, to, insert, start, end}: swap text[from..to] for
// `insert`, then leave the selection at [start, end] of the result.

function wrapEdit(marker, text, start, end) {
  const selected = text.slice(start, end);
  const before = text.slice(0, start);
  const after = text.slice(end);
  const width = marker.length;

  // Already wrapped, with the marks inside the selection: take them off.
  if (selected.length >= width * 2 && selected.startsWith(marker) && selected.endsWith(marker)) {
    const bare = selected.slice(width, -width);
    return { from: start, to: end, insert: bare, start, end: start + bare.length };
  }
  // Already wrapped, with the marks just outside it. A single `*` has to
  // check it is not looking at the inside of a `**`, or asking for italic
  // on bold text would quietly turn it into italic text.
  const doubled = width === 1 && (before.endsWith(marker + marker) || after.startsWith(marker + marker));
  if (!doubled && before.endsWith(marker) && after.startsWith(marker)) {
    return {
      from: start - width, to: end + width, insert: selected,
      start: start - width, end: end - width,
    };
  }
  // Not wrapped. With nothing selected the caret lands between the marks,
  // ready to type into.
  return {
    from: start, to: end, insert: marker + selected + marker,
    start: start + width, end: start + width + selected.length,
  };
}

// The whole of every line the selection touches, since a prefix belongs to a
// line and not to the part of it somebody happened to drag over.
function lineSpan(text, start, end) {
  const from = text.lastIndexOf("\n", start - 1) + 1;
  const stop = text.indexOf("\n", end);
  return { from, to: stop === -1 ? text.length : stop };
}

function prefixEdit(name, text, start, end) {
  const span = lineSpan(text, start, end);
  const lines = text.slice(span.from, span.to).split("\n");
  const mark = PREFIXES[name];
  const found = lines.map((line) => (line.match(ANY_PREFIX) || [])[2] || "");
  const written = lines.filter((line) => line.trim());
  // Off again when every line that has anything on it already carries this
  // mark. Blank lines do not count, or one trailing newline would stop the
  // bar ever toggling off.
  const already = written.length > 0 && lines.every(
    (line, index) => !line.trim() || mark.has.test(found[index]));
  // Numbered from the lines that get one, so a blank line in the middle does
  // not eat a number.
  let counted = 0;
  const insert = lines.map((line, index) => {
    const [, indent = ""] = line.match(ANY_PREFIX) || [];
    const body = line.slice(indent.length + found[index].length);
    if (already || !line.trim()) return indent + body;
    return indent + mark.make(counted++) + body;
  }).join("\n");
  return { from: span.from, to: span.to, insert, start: span.from, end: span.from + insert.length };
}

function headingEdit(text, start, end) {
  const span = lineSpan(text, start, end);
  const lines = text.slice(span.from, span.to).split("\n");
  // The first line decides, and the rest follow it, so a block of lines does
  // not end up at different depths.
  const [, , current = ""] = lines[0].match(HEADING) || [];
  const next = HEADING_CYCLE[(HEADING_CYCLE.indexOf(current) + 1) % HEADING_CYCLE.length];
  const insert = lines.map((line) => {
    const [, indent = "", found = ""] = line.match(HEADING) || [];
    return indent + next + line.slice(indent.length + found.length);
  }).join("\n");
  return { from: span.from, to: span.to, insert, start: span.from, end: span.from + insert.length };
}

function linkEdit(text, start, end) {
  const selected = text.slice(start, end);
  const insert = `[${selected}](${LINK_URL})`;
  // The selection lands on the placeholder, so the address is what you type.
  const at = start + selected.length + 3;
  return { from: start, to: end, insert, start: at, end: at + LINK_URL.length };
}

export function edit(name, text, start, end) {
  if (WRAPS[name]) return wrapEdit(WRAPS[name], text, start, end);
  if (PREFIXES[name]) return prefixEdit(name, text, start, end);
  if (name === "heading") return headingEdit(text, start, end);
  if (name === "link") return linkEdit(text, start, end);
  throw new Error(`no such format: ${name}`);
}

// What the text becomes. The bar does not use this — it edits through the
// browser so that undo keeps working — but it is the whole of the meaning of
// an edit, and it is what the tests read.
export function applied(name, text, start, end) {
  const step = edit(name, text, start, end);
  return {
    text: text.slice(0, step.from) + step.insert + text.slice(step.to),
    start: step.start,
    end: step.end,
  };
}

// -- the bar -------------------------------------------------------------------------
const BODY = ".editor textarea.body";

function build() {
  const bar = document.createElement("div");
  bar.className = "format";
  bar.innerHTML = `<div class="format-row">` + ACTIONS.map((a) =>
    `<button type="button" data-format="${a.name}" aria-label="${a.title}" title="${a.title}">` +
    `<span>${a.label}</span></button>`).join("") + `</div>`;
  document.body.append(bar);

  // pointerdown, not click, and prevented: a tap anywhere on the bar must not
  // take the focus out of the box, or the selection it is about to act on
  // would be gone before the handler ran.
  bar.addEventListener("pointerdown", (event) => event.preventDefault());
  bar.addEventListener("click", (event) => {
    const button = event.target.closest("[data-format]");
    if (button) run(button.dataset.format);
  });
  return bar;
}

function area() {
  const active = document.activeElement;
  return active && active.matches && active.matches(BODY) ? active : null;
}

function run(name) {
  const box = area();
  if (!box) return;
  const step = edit(name, box.value, box.selectionStart, box.selectionEnd);
  box.focus();
  box.setSelectionRange(step.from, step.to);
  // insertText keeps the undo stack; the fallback does not, and is only
  // there for anything that has dropped execCommand entirely.
  let inserted = false;
  try {
    inserted = Boolean(document.execCommand) && document.execCommand("insertText", false, step.insert);
  } catch {
    inserted = false;
  }
  if (!inserted) {
    box.value = box.value.slice(0, step.from) + step.insert + box.value.slice(step.to);
  }
  box.setSelectionRange(step.start, step.end);
  // What the editor already listens for: grow the box, start the save timer.
  box.dispatchEvent(new Event("input", { bubbles: true }));
}

// The keyboard covers the bottom of the window, and the window does not
// shrink for it — so the bar is moved up by however much of it is hidden.
function sit(bar) {
  const view = window.visualViewport;
  if (!view) return;
  // `bottom` for the keyboard, so `transform` is left free for the slide.
  const covered = window.innerHeight - view.height - view.offsetTop;
  bar.style.bottom = `${Math.max(0, Math.round(covered))}px`;
}

export function start() {
  const bar = build();
  const show = () => {
    const box = area();
    const selected = box && box.selectionStart !== box.selectionEnd;
    if (selected) sit(bar);
    bar.classList.toggle("up", Boolean(selected));
  };
  document.addEventListener("selectionchange", show);
  document.addEventListener("focusout", () => setTimeout(show, 0));
  if (window.visualViewport) {
    for (const event of ["resize", "scroll"]) {
      window.visualViewport.addEventListener(event, () => {
        if (bar.classList.contains("up")) sit(bar);
      });
    }
  }
}

// Imported by node for the tests, where there is no document to wire up.
if (typeof document !== "undefined") start();
