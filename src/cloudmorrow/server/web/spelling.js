/* Spelling: the words an editor marks, and what to do about them.

   The browser's own checker is off in every editor that writes words —
   a document, a note — and this is what checks instead, once a person
   switches it on (the gear on the screen, or #/spelling): the server's
   dictionaries (server/spelling.py, the catalog's languages), so a phone
   and a computer mark the same words, in the language the person chose,
   with the words they added kept on them rather than in one browser.

   A marked word is not the usual red wave: a tinted word with a bar
   under it (spelling.css). Right-click it, or hold a finger on it, and
   the suggestions come up, with Add to dictionary and Ignore. Select
   some lines and do the same, and the lines can be checked in another
   language: the part is marked at its left edge with the language and
   an ×, which takes the part back to the default language. A document
   keeps a part as `lang` on its blocks; a note keeps it as comment lines,
   `<!-- lang: de -->` … `<!-- /lang -->`, which anything that renders
   Markdown leaves out (markdown_rules.js, quill/docs.py).

   Two editors are checked here, each through a small adapter: the
   document's page of blocks (kit_docs.js) and the Markdown boxes of the
   editor (markdown.js, pictures.js). Each hands over its root and how it
   changes text; the checking, the marking, the menus and the gutter are
   the same. What is sent to the server is words, a screenful at a time,
   never a page. */

import { api, app, esc, mount, nav, onSignOut, previousHash, homeHash, registerScreen, toast, wireShell } from "./core.js";
import { choose, contextMenus } from "./actions.js";
import { langLine } from "./markdown_rules.js";

const PASS_DELAY = 700;      // after the last change, before the words are checked
const BATCH = 400;           // words a request carries at most
const MARK = "spell-miss";
const LANG = /^[a-z]{2,3}(-[a-z]{2})?$/;
// A word: letters, with apostrophes and hyphens inside it.
const WORD = /[\p{L}\p{M}][\p{L}\p{M}'’]*(?:-[\p{L}\p{M}][\p{L}\p{M}'’]*)*/gu;
// What is never a word to check: an address, a mail, a number in letters.
const NOT_WORDS = /(?:https?:\/\/|www\.)\S+|\S+@\S+\.\S+/g;

// -- the person's setting, and the languages -----------------------------------------
let setting = null;      // {check, language, words}, once asked for
let known = null;        // {languages: [{id, label, ready}], problem}
const asked = { setting: null, languages: null };

/** The person's spelling setting, asked for once: {check, language, words}. */
export async function spellingSetting() {
  if (setting) return setting;
  if (!asked.setting) asked.setting = api("GET", "/api/auth/spelling").then((s) => { setting = s; return s; });
  return asked.setting;
}

async function saveSetting(patch) {
  const current = await spellingSetting();
  setting = await api("PUT", "/api/auth/spelling", { ...current, ...patch });
  return setting;
}

/** The languages the server can check: {languages, problem}, asked for once. */
export async function spellingLanguages() {
  if (known) return known;
  if (!asked.languages) asked.languages = api("GET", "/api/spelling/languages").then((k) => { known = k; return k; });
  return asked.languages;
}

onSignOut(() => { setting = null; known = null; asked.setting = null; asked.languages = null; caches.clear(); });

const languageLabel = (id) => ((known && known.languages.find((l) => l.id === id)) || { label: id.toUpperCase() }).label;

// The language to start with when none was chosen: the browser's, when the
// server has it, else the first the server has.
function guessLanguage(languages) {
  const ids = new Set(languages.map((l) => l.id));
  const mine = String(navigator.language || "").toLowerCase().replace("_", "-");
  if (ids.has(mine)) return mine;
  const short = mine.split("-")[0];
  if (ids.has(short)) return short;
  const near = languages.find((l) => l.id.split("-")[0] === short);
  return near ? near.id : (languages[0] || { id: "" }).id;
}

/** The gear's target on a screen that writes words: the spelling settings. */
export const spellingLink = () => ({ label: "Spelling", href: "#/spelling" });

// -- what the server said about words --------------------------------------------------
// By language: a word → whether it is wrong. Asked once per word per session.
const caches = new Map();
const cacheFor = (lang) => {
  if (!caches.has(lang)) caches.set(lang, new Map());
  return caches.get(lang);
};
// Words let through this session, on every page (Ignore).
const ignored = new Set();

function skipWord(word) {
  if (word.length < 2) return true;
  // An acronym, or a word of capitals, is not a spelling.
  if (word === word.toUpperCase() && word !== word.toLowerCase()) return true;
  return false;
}

const own = () => new Set((setting && setting.words) || []);

/** The words among *words* that are wrong in *lang*, after asking the server
    about the ones not asked before. */
async function wrongOnes(lang, words, status) {
  const cache = cacheFor(lang);
  const unknown = [...new Set(words.filter((w) => !cache.has(w)))];
  for (let at = 0; at < unknown.length; at += BATCH) {
    const batch = unknown.slice(at, at + BATCH);
    let answer;
    try {
      answer = await api("POST", "/api/spelling/check", { language: lang, words: batch });
    } catch (err) {
      status(err.status === 503 ? "Spelling: " + err.message : "");
      return null;
    }
    const wrong = new Set(answer.wrong);
    for (const w of batch) cache.set(w, wrong.has(w));
  }
  const mine = own();
  return new Set(words.filter((w) => cache.get(w) && !mine.has(w) && !ignored.has(w)));
}

// -- words in a block ----------------------------------------------------------------------
// The text nodes of *block* that hold words to check: not a Markdown mark,
// not code, and — in a list item — not the item's nested list, which is
// blocks of its own.
function textNodes(block, skip) {
  const out = [];
  const walk = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
  for (let node = walk.nextNode(); node; node = walk.nextNode()) {
    if (!node.data.trim() || skip(node, block)) continue;
    out.push(node);
  }
  return out;
}

/** The words in a run of text: [{word, start, end}], addresses and mails left out. */
export function wordsIn(text) {
  const out = [];
  const skipped = [];
  for (const m of text.matchAll(NOT_WORDS)) skipped.push([m.index, m.index + m[0].length]);
  for (const m of text.matchAll(WORD)) {
    let word = m[0].replace(/['’]+$/, "");
    if (!word) continue;
    const start = m.index;
    const end = start + word.length;
    if (skipped.some(([a, b]) => start < b && end > a)) continue;
    if (skipWord(word)) continue;
    out.push({ word, start, end });
  }
  return out;
}

function unmark(block) {
  for (const span of block.querySelectorAll("." + MARK)) span.replaceWith(document.createTextNode(span.textContent));
  block.normalize();
}

// The caret, when it stands in a text node: {node, offset}; else null.
function caretNode() {
  const sel = getSelection();
  if (!sel || !sel.rangeCount || !sel.isCollapsed || !sel.focusNode || sel.focusNode.nodeType !== Node.TEXT_NODE) return null;
  return { node: sel.focusNode, offset: sel.focusOffset };
}

// The wrong words of *nodes* wrapped, except the one the caret is in: a
// word being typed is not wrong yet.
function mark(nodes, wrong, caret) {
  for (const node of nodes) {
    const at = caret && caret.node === node ? caret.offset : -1;
    const found = wordsIn(node.data).filter(({ word, start, end }) =>
      wrong.has(word) && !(at >= 0 && start <= at && at <= end));
    const length = node.data.length;
    if (found.length) {
      const pieces = [];
      let at = 0;
      for (const { word, start, end } of found) {
        if (start > at) pieces.push(document.createTextNode(node.data.slice(at, start)));
        const span = document.createElement("span");
        span.className = MARK;
        span.dataset.word = word;
        span.textContent = word;
        pieces.push(span);
        at = end;
      }
      if (at < length) pieces.push(document.createTextNode(node.data.slice(at)));
      node.replaceWith(...pieces);
    }
  }
}

// Where the caret is in *block*, as an offset in its text; -1 when it is not there.
function caretOffset(block) {
  const sel = getSelection();
  if (!sel || !sel.rangeCount || !sel.isCollapsed || !block.contains(sel.focusNode)) return -1;
  const range = document.createRange();
  range.setStart(block, 0);
  range.setEnd(sel.focusNode, sel.focusOffset);
  return range.toString().length;
}

// -- the checker on an editor ----------------------------------------------------------------
/**
 * Spelling on an editor, through its adapter:
 *   root        the element the words are in
 *   box         the `.editor` the gutter is drawn in
 *   editable    whether words can be put right
 *   blocks()    the units a language is per, in order: a document's blocks, a note's lines
 *   langOf(b)   a block's own language, "" for the default
 *   skip(node, block)  a text node not to check
 *   parts()     the parts in another language: [{lang, first, last}] over blocks()
 *   keep(block) the caret's place in a block, as a function that puts it back
 *   setLang(blocks, lang, {first, last}), clearPart(part)
 *   replace(span, text)   a marked word put right
 *   status(text)
 * Returns {detach, refresh}.
 */
export function attachSpelling(host) {
  const state = { on: false, lang: "", timer: null, composing: false, marking: false, caretBlock: null, gone: false };
  const gutter = document.createElement("div");
  gutter.className = "spell-gutter";
  gutter.setAttribute("aria-hidden", "true");

  const schedule = () => {
    if (!state.on || state.gone) return;
    clearTimeout(state.timer);
    state.timer = setTimeout(pass, PASS_DELAY);
  };

  // What the pass draws from: the blocks, each with the language it is checked in.
  const resolved = () => {
    const parts = host.parts();
    const blocks = host.blocks();
    return blocks.map((block, i) => {
      const part = parts.find((p) => p.first <= i && i <= p.last);
      return { block, lang: (part && part.lang) || state.lang };
    });
  };

  async function pass() {
    if (!state.on || state.gone || state.composing || state.marking) return;
    const items = resolved();
    const caret = items.find(({ block }) => caretOffset(block) >= 0);
    state.caretBlock = caret ? caret.block : null;
    const todo = [];
    for (const item of items) {
      const nodes = textNodes(item.block, host.skip);
      const text = nodes.map((n) => n.data).join("\n");
      const key = item.lang + "\u0000" + text;
      if (item.block.dataset.spelled === key) continue;
      todo.push({ ...item, nodes, key, words: nodes.flatMap((n) => wordsIn(n.data).map((w) => w.word)) });
    }
    drawParts(items);
    if (!todo.length) return;
    const byLang = new Map();
    for (const item of todo) {
      if (!byLang.has(item.lang)) byLang.set(item.lang, []);
      byLang.get(item.lang).push(...item.words);
    }
    const wrong = new Map();
    for (const [lang, words] of byLang) {
      const ready = known && known.languages.some((l) => l.id === lang && l.ready);
      if (!ready && words.length) host.status(`Getting the ${languageLabel(lang)} dictionary…`);
      const found = await wrongOnes(lang, words, host.status);
      if (!ready && found) { host.status(""); if (known) for (const l of known.languages) if (l.id === lang) l.ready = true; }
      if (state.gone) return;
      if (found) wrong.set(lang, found);
    }
    state.marking = true;
    try {
      for (const item of todo) {
        if (!item.block.isConnected || !wrong.has(item.lang)) continue;
        const keep = host.keep(item.block);
        const caret = caretNode();
        unmark(item.block);
        mark(textNodes(item.block, host.skip), wrong.get(item.lang), caret && caret.node.isConnected ? caret : null);
        item.block.dataset.spelled = item.key;
        keep();
      }
    } finally {
      state.marking = false;
    }
    drawParts(resolved());
  }

  // The parts in another language, marked at the left: the language at the
  // top of each, with the × that takes the part back.
  function drawParts(items) {
    const parts = host.parts();
    gutter.replaceChildren();
    if (!parts.length) { host.box.classList.remove("spelling-parts"); return; }
    host.box.classList.add("spelling-parts");
    const base = gutter.getBoundingClientRect();
    for (const part of parts) {
      const first = items[part.first] && items[part.first].block;
      const last = items[part.last] && items[part.last].block;
      if (!first || !last) continue;
      const top = first.getBoundingClientRect().top - base.top;
      const bottom = last.getBoundingClientRect().bottom - base.top;
      const el = document.createElement("div");
      el.className = "spell-part";
      el.style.top = `${Math.round(top)}px`;
      el.style.height = `${Math.max(18, Math.round(bottom - top))}px`;
      const name = languageLabel(part.lang);
      el.innerHTML = `<button type="button" class="spell-part-x" title="${esc(name)}: checked in ${esc(name)} to the end of the part. Press to use ${esc(languageLabel(state.lang))} again" aria-label="Stop checking this part in ${esc(name)}">` +
        `<span class="code">${esc(part.lang.split("-")[0])}</span><span class="x">×</span></button>`;
      el.querySelector("button").addEventListener("click", () => {
        if (!host.editable) return;
        host.clearPart(part);
        schedule();
      });
      gutter.appendChild(el);
    }
  }

  // -- the menus ----------------------------------------------------------------------
  async function wordChoices(span) {
    const word = span.dataset.word || span.textContent;
    const items = resolved();
    const here = items.find(({ block }) => block.contains(span));
    const lang = here ? here.lang : state.lang;
    let suggestions = [];
    try { suggestions = (await api("POST", "/api/spelling/suggest", { language: lang, word })).suggestions; }
    catch (err) { toast(err.message); }
    const choices = suggestions.slice(0, 6).map((text) => ({
      label: text,
      run: () => { if (host.editable) host.replace(span, text); },
    }));
    if (!choices.length) choices.push({ label: "No suggestions", run: () => {} });
    choices.push({ sep: true });
    choices.push({
      label: "Add to dictionary",
      run: async () => {
        try { await saveSetting({ words: [...own(), word] }); }
        catch (err) { toast(err.message); return; }
        forgetWord(word);
      },
    });
    choices.push({ label: "Ignore", run: () => { ignored.add(word); forgetWord(word); } });
    return choices;
  }

  // A word let through: every mark of it goes, on every block.
  function forgetWord(word) {
    for (const span of host.root.querySelectorAll("." + MARK)) {
      if ((span.dataset.word || span.textContent) === word) {
        const block = span.closest("[data-spelled]");
        span.replaceWith(document.createTextNode(span.textContent));
        if (block) { block.normalize(); delete block.dataset.spelled; }
      }
    }
    schedule();
  }

  // Lines selected: Copy, Cut, and the language they are checked in.
  function selectionChoices() {
    const sel = getSelection();
    if (!sel || !sel.rangeCount || sel.isCollapsed) return null;
    const range = sel.getRangeAt(0).cloneRange();
    if (!host.root.contains(range.commonAncestorContainer)) return null;
    const items = resolved();
    const touched = items.map((item, i) => (range.intersectsNode(item.block) ? i : -1)).filter((i) => i >= 0);
    if (!touched.length) return null;
    const first = touched[0];
    const last = touched[touched.length - 1];
    const inside = host.parts().find((p) => p.first <= last && first <= p.last);
    const reselect = () => { const s = getSelection(); s.removeAllRanges(); s.addRange(range); };
    const choices = [
      { label: "Copy", run: () => { reselect(); document.execCommand("copy"); } },
    ];
    if (host.editable) choices.push({ label: "Cut", run: () => { reselect(); document.execCommand("cut"); } });
    if (!host.editable) return choices;
    choices.push({ sep: true });
    choices.push({
      label: "Check spelling in…",
      run: () => {
        const languages = (known ? known.languages : []).filter((l) => l.id !== state.lang);
        if (!languages.length) { toast("No other language to check in"); return; }
        choose(`Check these lines in`, languages.map((l) => ({
          label: l.label,
          run: () => {
            const blocks = host.blocks();
            host.setLang(blocks.slice(first, last + 1), l.id, { first, last });
            schedule();
          },
        })));
      },
    });
    if (inside) {
      choices.push({
        label: `Check in ${languageLabel(state.lang)} again`,
        run: () => { host.clearPart(inside); schedule(); },
      });
    }
    return choices;
  }

  // -- wiring --------------------------------------------------------------------------
  const observer = new MutationObserver(() => { if (!state.marking) schedule(); });
  const onSelection = () => {
    if (state.gone || !state.on) return;
    const was = state.caretBlock;
    if (was && caretOffset(was) < 0) {
      // The caret left a block: the word it was in is a word now.
      delete was.dataset.spelled;
      state.caretBlock = null;
      schedule();
    }
  };
  const onResize = () => { if (state.on) drawParts(resolved()); };

  async function start() {
    let s;
    try { s = await spellingSetting(); } catch { return; }
    if (state.gone || !s.check) return;
    const k = await spellingLanguages().catch(() => ({ languages: [], problem: "" }));
    if (state.gone) return;
    if (!k.languages.length) {
      host.status(k.problem ? "Spelling: " + k.problem : "");
      return;
    }
    state.lang = (s.language && k.languages.some((l) => l.id === s.language)) ? s.language : guessLanguage(k.languages);
    if (state.lang !== s.language) saveSetting({ language: state.lang }).catch(() => {});
    state.on = true;
    host.box.classList.add("spelling-on");
    host.box.appendChild(gutter);
    observer.observe(host.root, { childList: true, characterData: true, subtree: true });
    document.addEventListener("selectionchange", onSelection);
    addEventListener("resize", onResize);
    host.root.addEventListener("compositionstart", () => { state.composing = true; });
    host.root.addEventListener("compositionend", () => { state.composing = false; schedule(); });
    contextMenus(host.root, "." + MARK, (span) => wordChoices(span), { blank: selectionChoices });
    pass();
  }
  start();

  return {
    refresh: schedule,
    detach() {
      state.gone = true;
      clearTimeout(state.timer);
      observer.disconnect();
      document.removeEventListener("selectionchange", onSelection);
      removeEventListener("resize", onResize);
    },
  };
}

// -- the document's adapter (kit_docs.js) ---------------------------------------------------
// A document's blocks are the elements of its page: a heading, a paragraph,
// a list item (its nested list is items of its own), a quote, a table. A
// part in another language is `lang` on each block, which the page draws
// as the element's own `lang`; blocks in a row with the same one are a part.
// The words are in these; a cell's are the cell's, a nested item's its own.
const DOC_BLOCKS = "h1, h2, h3, p, li, td";

export function attachDocument({ box, body, editable, changed, status }) {
  // The element a block's language is kept on: a quote's paragraph is the
  // quote's, a cell is the table's, everything else is its own.
  const unitOf = (el) => el.closest("table") || el.closest("blockquote") || el;
  const blocks = () => [...body.querySelectorAll(DOC_BLOCKS)].filter((el) => el.tagName === "TD" || !el.closest("td"));
  const langOf = (el) => {
    const lang = String(unitOf(el).getAttribute("lang") || "").toLowerCase();
    return LANG.test(lang) ? lang : "";
  };
  // Blocks in a row in the same language are one part.
  const parts = () => {
    const out = [];
    blocks().forEach((el, i) => {
      const lang = langOf(el);
      if (!lang) return;
      const last = out[out.length - 1];
      if (last && last.lang === lang && last.last === i - 1) last.last = i;
      else out.push({ lang, first: i, last: i });
    });
    return out;
  };
  return attachSpelling({
    root: body,
    box,
    editable,
    status,
    blocks,
    langOf,
    parts,
    // In a list item, the nested list's words are its own items'.
    skip: (node, block) => block.tagName === "LI" && node.parentElement.closest("li") !== block,
    keep: (block) => {
      const at = caretOffset(block);
      return () => { if (at >= 0) placeCaret(block, at); };
    },
    setLang(els, lang) {
      for (const el of els) unitOf(el).setAttribute("lang", lang);
      changed();
    },
    clearPart(part) {
      const all = blocks();
      for (let i = part.first; i <= part.last; i += 1) if (all[i]) unitOf(all[i]).removeAttribute("lang");
      changed();
    },
    replace(span, text) {
      const block = span.closest("[data-spelled]");
      span.replaceWith(document.createTextNode(text));
      if (block) { block.normalize(); delete block.dataset.spelled; }
      changed();
    },
  });
}

// The caret put at an offset in a block's text, after the block was drawn again.
function placeCaret(block, offset) {
  const walk = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
  let rest = offset;
  for (let node = walk.nextNode(); node; node = walk.nextNode()) {
    if (rest <= node.length) {
      const range = document.createRange();
      range.setStart(node, rest);
      range.collapse(true);
      const sel = getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      return;
    }
    rest -= node.length;
  }
}

// -- the Markdown editor's adapter (markdown.js, pictures.js) ----------------------------------
// A note's blocks are its lines, across every box of the page (the pictures
// between them are not words). A part in another language is the comment
// lines around it, drawn as the part's edges; the comment itself shows
// only on the line you are on, like every other mark.
export function attachMarkdown({ box, blocks: blocksEl, editable, changed, status }) {
  const areas = () => [...blocksEl.querySelectorAll(".md")];
  const lines = () => [...blocksEl.querySelectorAll(".md > .md-ln")];
  const said = (line) => langLine(line.dataset.src !== undefined ? line.dataset.src : line.textContent);
  const parts = () => {
    const out = [];
    let open = null;
    lines().forEach((line, i) => {
      const lang = said(line);
      if (lang === null) { if (open) open.last = i; return; }
      if (lang) { open = { lang, first: i, last: i, startLine: i, endLine: -1 }; out.push(open); }
      else if (open) { open.endLine = i; open.last = i; open = null; }
    });
    return out;
  };
  // Where a line is in its box's text: the box, and the offset its text starts at.
  const placeOf = (line) => {
    const area = line.parentElement;
    let offset = 0;
    for (const sibling of area.children) {
      if (sibling === line) break;
      offset += sibling.textContent.length + 1;
    }
    return { area, offset };
  };
  const lineText = (line) => (line.dataset.src !== undefined ? line.dataset.src : line.textContent);
  return attachSpelling({
    root: blocksEl,
    box,
    editable,
    status,
    blocks: lines,
    langOf: () => "",
    parts,
    // A mark, code, and the comment lines themselves are not words.
    skip: (node) => !!(node.parentElement && node.parentElement.closest(".md-mk, code, .md-code, .md-fence, .md-lang")),
    keep: (block) => {
      const area = block.parentElement;
      const at = area && document.activeElement === area ? [area.selectionStart, area.selectionEnd] : null;
      return () => { if (at) area.setSelectionRange(at[0], at[1]); };
    },
    setLang(els, lang, { first, last }) {
      const all = lines();
      // A part the lines were in goes first: parts do not nest.
      for (const part of parts().slice().reverse()) {
        if (part.first <= last && first <= part.last) removePart(part, all);
      }
      const fresh = lines();
      const firstLine = fresh[first];
      const lastLine = fresh[last];
      if (!firstLine || !lastLine) return;
      // The end first, so the start's offset still holds.
      const end = placeOf(lastLine);
      const endAt = end.offset + lineText(lastLine).length;
      end.area.replaceText(endAt, endAt, "\n<!-- /lang -->");
      const start = placeOf(firstLine);
      start.area.replaceText(start.offset, start.offset, `<!-- lang: ${lang} -->\n`);
      changed();
    },
    clearPart(part) {
      removePart(part, lines());
      changed();
    },
    replace(span, text) {
      const line = span.closest(".md-ln");
      const { area, offset } = placeOf(line);
      const range = document.createRange();
      range.setStart(line, 0);
      range.setEnd(span, 0);
      const at = offset + range.toString().length;
      area.replaceText(at, at + span.textContent.length, text);
      changed();
    },
  });

  // The comment lines of a part taken out of their boxes' text, end first.
  function removePart(part, all) {
    const endLine = part.endLine >= 0 ? all[part.endLine] : null;
    const startLine = all[part.startLine];
    for (const line of [endLine, startLine]) {
      if (!line) continue;
      const { area, offset } = placeOf(line);
      const length = lineText(line).length;
      const text = area.value;
      // The line and its newline: the one after it, or the one before at the end.
      const to = offset + length < text.length ? offset + length + 1 : offset + length;
      const from = offset + length < text.length ? offset : Math.max(0, offset - 1);
      area.replaceText(from, to, "", Math.min(from, area.selectionStart));
    }
  }
}

// -- the settings screen -------------------------------------------------------------------------
async function renderSpelling() {
  const [s, k] = await Promise.all([spellingSetting(), spellingLanguages().catch(() => ({ languages: [], problem: "" }))]);
  const from = previousHash();
  const back = from && from !== "#/spelling" ? from : homeHash();
  const language = k.languages.find((l) => l.id === s.language);
  const words = s.words || [];
  mount(nav({ back, backLabel: "Back", title: "Spelling" }) + `
    <main class="spelling">
      <h1 class="large">Spelling</h1>
      <p class="spelling-note">Your cloud checks the spelling in what you write, with its own dictionaries,
        the same on every phone and computer you sign in on. The browser's own checker is off.
        A language is fetched the first time you write in it.</p>
      ${k.problem ? `<p class="spelling-problem">${esc(k.problem)}</p>` : ""}
      <div class="group">
        <label class="row"><span class="main">Check spelling</span>
          <input type="checkbox" class="switch check"${s.check ? " checked" : ""}${k.languages.length ? "" : " disabled"}></label>
        <button type="button" class="row language"${k.languages.length ? "" : " disabled"}><span class="main">Language</span>
          <span class="value">${esc(language ? language.label : (s.language ? s.language : "Choose…"))}</span></button>
      </div>
      <p class="group-label">Words you added</p>
      <div class="group words">${words.length ? words.map((w) => `<div class="row"><span class="main">${esc(w)}</span>
          <button type="button" class="remove" data-word="${esc(w)}" aria-label="Remove ${esc(w)}">×</button></div>`).join("")
        : `<p class="empty">None yet. Right-click a marked word, or hold a finger on it, and choose Add to dictionary.</p>`}</div>
      <p class="spelling-note">Select some lines, right-click or hold, and they can be checked in another language;
        the part is marked at its left edge, with an × that takes it back.</p>
    </main>`);
  wireShell();
  const main = app.querySelector("main.spelling");
  main.querySelector(".check").addEventListener("change", async (event) => {
    const box = event.target;
    const wanted = box.checked;
    box.disabled = true;
    try {
      const patch = { check: wanted };
      if (wanted && !language) patch.language = guessLanguage(k.languages);
      await saveSetting(patch);
      toast(wanted ? "Spelling is checked" : "Spelling is not checked");
      if (patch.language) renderSpelling();
    } catch (err) { box.checked = !wanted; toast(err.message); }
    finally { box.disabled = false; }
  });
  main.querySelector(".language").addEventListener("click", () => {
    choose("Language", k.languages.map((l) => ({
      label: l.label + (l.summary && l.summary !== l.label ? ` · ${l.summary}` : ""),
      run: async () => {
        try { await saveSetting({ language: l.id }); renderSpelling(); }
        catch (err) { toast(err.message); }
      },
    })));
  });
  main.querySelector(".words").addEventListener("click", async (event) => {
    const button = event.target.closest(".remove");
    if (!button) return;
    try { await saveSetting({ words: words.filter((w) => w !== button.dataset.word) }); renderSpelling(); }
    catch (err) { toast(err.message); }
  });
}

registerScreen("spelling", renderSpelling);
