/* A box to write Markdown in, drawn as it reads.

   Each line is a <div> drawn by markdown_rules.js: headings large, bold
   bold, a list with its bullets, a task with its box. The marks are still
   there, as spans, and the line the caret is on shows them — that is the
   line you are editing — while every other line hides them. Tick a task's
   box to tick it.

   It stands in for a <textarea>: `value`, `selectionStart`/`selectionEnd`,
   `setSelectionRange`, `placeholder` and `readOnly` are the same, so the
   page (pictures.js) handles it as one. What it keeps is the text: the DOM
   is drawn again from that after every change, the caret carried across
   by its place in the text. So the browser's own undo, which remembers
   DOM, is replaced with one that remembers text. */

import { continueLine, isListLine, renderLines, toggleTask } from "./markdown_rules.js";

const UNDO_PAUSE = 1000;  // typing within this of the last change is the same step

export function markdownArea(text, onChange) {
  const el = document.createElement("div");
  el.className = "body md";
  el.contentEditable = "true";
  el.spellcheck = true;
  el.setAttribute("role", "textbox");
  el.setAttribute("aria-multiline", "true");

  let placeholder = "";
  let composing = false;
  let history = [];
  let step = -1;
  let lastPush = 0;

  // -- the text, out of the DOM and back -------------------------------------
  // The lines are the box's children. Whatever the browser leaves between
  // them — a bare text node after select-all and typing, a <br> — joins the
  // line it is next to, so nothing typed is ever lost to the reading.
  const groups = () => {
    const out = [];
    let open = null;
    for (const node of el.childNodes) {
      const block = node.nodeType === 1 && /^(DIV|P)$/.test(node.tagName);
      if (block) { out.push({ nodes: [node] }); open = null; }
      else {
        if (!open) { open = { nodes: [] }; out.push(open); }
        open.nodes.push(node);
      }
    }
    if (!out.length) out.push({ nodes: [] });
    return out;
  };
  const groupText = (g) => g.nodes.map((n) => (n.nodeName === "BR" ? "" : n.textContent)).join("").replace(/\n/g, "");
  const readLines = () => groups().map(groupText);
  const read = () => readLines().join("\n");

  // Where (node, offset) is, counted in the text.
  function offsetOf(node, offset) {
    const gs = groups();
    let total = 0;
    let top = node;
    if (node === el) top = el.childNodes[offset] || null;
    else while (top && top.parentNode !== el) top = top.parentNode;
    for (const g of gs) {
      const len = groupText(g).length;
      const at = top ? g.nodes.indexOf(top) : -1;
      if (at >= 0) {
        if (node === el) return total + g.nodes.slice(0, at).reduce((n, x) => n + x.textContent.length, 0);
        const range = document.createRange();
        range.setStart(g.nodes[0], 0);
        range.setEnd(node, offset);
        return total + Math.min(len, range.toString().replace(/\n/g, "").length);
      }
      total += len + 1;
    }
    return Math.max(0, total - 1);
  }

  // The (node, offset) a place in the text is at, in the drawn lines.
  function pointAt(offset) {
    const lines = [...el.children];
    let rest = offset;
    for (const line of lines) {
      const len = line.textContent.length;
      if (rest <= len) {
        const walk = document.createTreeWalker(line, NodeFilter.SHOW_TEXT);
        for (let t = walk.nextNode(); t; t = walk.nextNode()) {
          if (rest <= t.length) return [t, rest];
          rest -= t.length;
        }
        return [line, line.childNodes.length && line.lastChild.nodeName === "BR" ? 0 : line.childNodes.length];
      }
      rest -= len + 1;
    }
    const last = lines[lines.length - 1];
    return [last, last.childNodes.length];
  }

  function caret() {
    const sel = getSelection();
    if (!sel.rangeCount || !el.contains(sel.anchorNode)) return null;
    const a = offsetOf(sel.anchorNode, sel.anchorOffset);
    const f = offsetOf(sel.focusNode, sel.focusOffset);
    return { start: Math.min(a, f), end: Math.max(a, f) };
  }

  function select(start, end = start) {
    const sel = getSelection();
    const range = document.createRange();
    range.setStart(...pointAt(start));
    range.setEnd(...pointAt(end));
    sel.removeAllRanges();
    sel.addRange(range);
    lightUp();
  }

  // -- drawing ---------------------------------------------------------------
  function draw(value) {
    const lines = value.split("\n");
    const drawn = renderLines(lines);
    const have = [...el.childNodes];
    // Only the lines that changed are drawn again, so the browser's
    // spelling marks stay on the rest. An IME's word in progress is never
    // drawn over: nothing is read back until it is done (compositionend).
    const fresh = drawn.map((d, i) => {
      const old = have[i];
      const cls = "md-ln" + (d.cls ? " " + d.cls : "");
      if (old && old.nodeType === 1 && old.tagName === "DIV" && old.dataset.src === lines[i] && old.dataset.cls === cls
          && old.textContent === lines[i]) {
        return old;
      }
      const div = document.createElement("div");
      div.className = cls;
      div.dataset.src = lines[i];
      div.dataset.cls = cls;
      div.innerHTML = d.html || "<br>";
      return div;
    });
    if (fresh.length !== have.length || fresh.some((n, i) => n !== have[i])) el.replaceChildren(...fresh);
    const empty = value === "";
    if (empty && placeholder) fresh[0].dataset.placeholder = placeholder;
    else delete fresh[0].dataset.placeholder;
  }

  // The lines the selection touches show their marks.
  function lightUp() {
    const at = document.activeElement === el ? caret() : null;
    let first = -1;
    let last = -2;
    if (at) {
      const lines = readLines();
      let pos = 0;
      lines.forEach((line, i) => {
        const end = pos + line.length;
        if (first < 0 && at.start <= end) first = i;
        if (at.end >= pos) last = i;
        pos = end + 1;
      });
    }
    [...el.children].forEach((line, i) => line.classList.toggle("md-on", i >= first && i <= last));
  }

  // -- changes -----------------------------------------------------------------
  function remember(typing) {
    const now = Date.now();
    const entry = { text: read(), at: caret() || { start: 0, end: 0 } };
    if (typing && step > 0 && now - lastPush < UNDO_PAUSE) history[step] = entry;
    else { history = history.slice(0, step + 1); history.push(entry); step = history.length - 1; }
    lastPush = typing ? now : 0;
  }

  // What the browser typed, read back and drawn again.
  function sync() {
    const at = caret();
    const value = read();
    draw(value);
    if (at) select(at.start, at.end);
    remember(true);
    onChange();
  }

  // A change made here, not by the browser: text in place of start…end.
  function edit(start, end, insert, caretAt = start + insert.length) {
    const value = read();
    draw(value.slice(0, start) + insert + value.slice(end));
    select(caretAt);
    remember(false);
    onChange();
  }

  function travel(by) {
    const to = step + by;
    if (to < 0 || to >= history.length) return;
    step = to;
    draw(history[step].text);
    select(history[step].at.start, history[step].at.end);
    lastPush = 0;
    onChange();
  }

  const lineAround = (value, at) => {
    const start = value.lastIndexOf("\n", at - 1) + 1;
    const end = value.indexOf("\n", at);
    return { start, end: end < 0 ? value.length : end };
  };

  function enter() {
    const at = caret();
    if (!at) return;
    const value = read();
    const line = lineAround(value, at.start);
    const next = continueLine(value.slice(line.start, at.start), value.slice(at.end, line.end));
    if (next.clear) edit(line.start, line.start + next.length, "");
    else edit(at.start, at.end, next.insert);
  }

  function wrap(markText) {
    const at = caret();
    if (!at) return;
    const value = read();
    const inner = value.slice(at.start, at.end);
    edit(at.start, at.end, markText + inner + markText, at.start + markText.length + inner.length);
    if (inner) select(at.start + markText.length, at.start + markText.length + inner.length);
  }

  // Tab and Shift+Tab move a list item in and out by two spaces.
  function indent(out) {
    const at = caret();
    if (!at) return false;
    const value = read();
    const line = lineAround(value, at.start);
    const text = value.slice(line.start, line.end);
    if (!isListLine(text)) return false;
    if (!out) { edit(line.start, line.start, "  ", at.start + 2); return true; }
    const strip = Math.min(2, text.length - text.trimStart().length);
    if (strip) edit(line.start, line.start + strip, "", Math.max(line.start, at.start - strip));
    return true;
  }

  // -- the events ----------------------------------------------------------------
  el.addEventListener("beforeinput", (event) => {
    const type = event.inputType;
    if (type === "insertParagraph" || type === "insertLineBreak") { event.preventDefault(); enter(); }
    else if (type.startsWith("format")) event.preventDefault();
    else if (type === "historyUndo") { event.preventDefault(); travel(-1); }
    else if (type === "historyRedo") { event.preventDefault(); travel(1); }
  });
  el.addEventListener("input", () => { if (!composing) sync(); });
  el.addEventListener("compositionstart", () => { composing = true; });
  el.addEventListener("compositionend", () => { composing = false; sync(); });

  el.addEventListener("keydown", (event) => {
    if (event.isComposing) return;
    const mod = event.ctrlKey || event.metaKey;
    const key = event.key.toLowerCase();
    if (mod && key === "z") { event.preventDefault(); travel(event.shiftKey ? 1 : -1); }
    else if (mod && key === "y") { event.preventDefault(); travel(1); }
    else if (mod && key === "b") { event.preventDefault(); wrap("**"); }
    else if (mod && key === "i") { event.preventDefault(); wrap("*"); }
    else if (event.key === "Tab" && !mod && !event.altKey && indent(event.shiftKey)) event.preventDefault();
  });

  // Text comes in as text. A picture is left for the page to take.
  el.addEventListener("paste", (event) => {
    const data = event.clipboardData;
    if (!data || [...(data.files || [])].some((f) => /^image\//.test(f.type))) return;
    const pasted = data.getData("text/plain");
    event.preventDefault();
    const at = caret();
    if (at && pasted) edit(at.start, at.end, pasted.replace(/\r\n?/g, "\n"));
  });

  // A task's box ticks without moving the caret; a link opens with Ctrl or
  // ⌘ held, or with a plain click on a page that is only read.
  el.addEventListener("mousedown", (event) => {
    const box = event.target.closest && event.target.closest(".md-mk.md-box");
    const line = box && box.closest(".md-ln");
    if (!line || line.classList.contains("md-on") || !el.isContentEditable) return;
    event.preventDefault();
    const index = [...el.children].indexOf(line);
    const lines = readLines();
    const start = lines.slice(0, index).reduce((n, l) => n + l.length + 1, 0);
    const value = read();
    const had = caret();
    draw(value.slice(0, start) + toggleTask(lines[index]) + value.slice(start + lines[index].length));
    if (had) select(had.start, had.end);
    remember(false);
    onChange();
  });
  el.addEventListener("click", (event) => {
    const target = event.target.closest && event.target.closest(".md-link[data-href]");
    if (!target || !(event.ctrlKey || event.metaKey || !el.isContentEditable)) return;
    event.preventDefault();
    open(target.dataset.href, "_blank", "noopener");
  });

  el.addEventListener("focus", lightUp);
  el.addEventListener("blur", () => { for (const line of el.children) line.classList.remove("md-on"); });
  const onSelection = () => {
    if (!el.isConnected) { document.removeEventListener("selectionchange", onSelection); return; }
    if (document.activeElement === el && !composing) lightUp();
  };
  document.addEventListener("selectionchange", onSelection);

  // -- the textarea's face ------------------------------------------------------
  Object.defineProperties(el, {
    value: {
      get: read,
      set(v) { draw(String(v)); history = []; step = -1; remember(false); },
    },
    selectionStart: { get: () => (caret() || { start: 0 }).start },
    selectionEnd: { get: () => (caret() || { end: 0 }).end },
    placeholder: {
      get: () => placeholder,
      set(v) { placeholder = String(v || ""); draw(read()); },
    },
    readOnly: {
      get: () => !el.isContentEditable,
      set(v) { el.contentEditable = v ? "false" : "true"; },
    },
  });
  el.setSelectionRange = (start, end = start) => select(start, end);

  el.value = text;
  return el;
}
