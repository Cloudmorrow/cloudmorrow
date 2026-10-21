/* Markdown, a line at a time, for the page you write in (markdown.js).

   Every line is drawn from its own text, with the marks — the `## `, the
   `**`, the `[`…`](url)` — kept in the line as spans of their own. The page
   hides them on every line but the one you are on, so what you read is the
   rendered text and what you edit is the Markdown. Nothing is ever taken
   out: a line's text is its textContent, letter for letter, which is what
   lets the caret and the saved file stay the Markdown that was typed.

   The terminal draws the same way (tui/markdown_render.py); these are its
   rules, in HTML. Pure: no DOM, so they run under node in the tests. */

const FENCE = /^(\s*)(```|~~~)\s*([\w+-]*)\s*$/;
const HEADING = /^(#{1,6})(\s+)(.*)$/;
const RULE = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;
const QUOTE = /^(\s*)((?:>\s?)+)(.*)$/;
const TASK = /^(\s*)([-*+]\s+\[([ xX])\]\s+)(.*)$/;
const BULLET = /^(\s*)([-*+]\s+)(.*)$/;
const NUMBER = /^(\s*)(\d+[.)]\s+)(.*)$/;
const TABLE = /^\s*\|.*\|\s*$/;

const INLINE = new RegExp([
  String.raw`(?<esc>\\[\\\x60*_{}\[\]()#+\-.!~>|])`,
  String.raw`(?<code>\x60+)(?<codeBody>.+?)\k<code>`,
  String.raw`!\[(?<imgAlt>[^\]]*)\]\((?<imgUrl>[^)]*)\)`,
  String.raw`\[(?<linkText>[^\]]*)\]\((?<linkUrl>[^)\s]*)\)`,
  String.raw`(?<bold>\*\*|__)(?<boldBody>.+?)\k<bold>`,
  String.raw`~~(?<strikeBody>.+?)~~`,
  String.raw`(?<em>[*_])(?<emBody>[^\s*_](?:.*?[^\s*_])?)\k<em>`,
  String.raw`<(?<autolink>[a-z][a-z0-9+.-]*:\/\/[^>\s]+)>`,
  String.raw`(?<bare>https?:\/\/[^\s<>()]+[^\s<>().,;:!?'"])`,
  String.raw`(?<![\w#])(?<tag>#[A-Za-z][\w/-]*)`,
].join("|"));

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const mark = (s) => (s ? `<span class="md-mk">${esc(s)}</span>` : "");
// A link opens only to the web or to mail; anything else is text.
const safeUrl = (url) => (/^(https?:|mailto:)/i.test(url) ? url : "");
const link = (url, inner) => {
  const href = safeUrl(url);
  return href ? `<span class="md-link" data-href="${esc(href)}">${inner}</span>` : `<span class="md-link">${inner}</span>`;
};

/** A line's words, with the inline marks as spans. */
export function inline(raw) {
  let out = "";
  let pos = 0;
  const re = new RegExp(INLINE.source, "g");
  for (let m = re.exec(raw); m; m = re.exec(raw)) {
    out += esc(raw.slice(pos, m.index));
    const g = m.groups;
    if (g.esc) out += mark("\\") + esc(g.esc[1]);
    else if (g.code) out += mark(g.code) + `<code>${esc(g.codeBody)}</code>` + mark(g.code);
    else if (g.imgAlt !== undefined) out += mark("![") + `<span class="md-link">${esc(g.imgAlt)}</span>` + mark(`](${g.imgUrl})`);
    else if (g.linkText !== undefined) out += mark("[") + link(g.linkUrl, inline(g.linkText)) + mark(`](${g.linkUrl})`);
    else if (g.bold) out += mark(g.bold) + `<strong>${inline(g.boldBody)}</strong>` + mark(g.bold);
    else if (g.strikeBody) out += mark("~~") + `<s>${inline(g.strikeBody)}</s>` + mark("~~");
    else if (g.em) out += mark(g.em) + `<em>${inline(g.emBody)}</em>` + mark(g.em);
    else if (g.autolink) out += mark("<") + link(g.autolink, esc(g.autolink)) + mark(">");
    else if (g.bare) out += link(g.bare, esc(g.bare));
    else if (g.tag) out += `<span class="md-tag">${esc(g.tag)}</span>`;
    pos = m.index + m[0].length;
  }
  return out + esc(raw.slice(pos));
}

/** For each line, whether it is inside a fenced code block; the fences are not. */
export function codeStates(lines) {
  let inside = false;
  return lines.map((line) => {
    if (FENCE.test(line)) { inside = !inside; return false; }
    return inside;
  });
}

// A mark that stands for something when it is hidden: a bullet, a box.
const glyph = (text, kind) => `<span class="md-mk md-glyph ${kind}">${esc(text)}</span>`;

/** One line: {cls, html}. `code` says it is inside a fenced block. */
export function renderLine(raw, code = false) {
  if (code) return { cls: "md-code", html: esc(raw) };
  if (FENCE.test(raw)) return { cls: "md-fence", html: esc(raw) };
  let m = HEADING.exec(raw);
  if (m) return { cls: `md-h${m[1].length}`, html: mark(m[1] + m[2]) + inline(m[3]) };
  if (RULE.test(raw)) return { cls: "md-rule", html: mark(raw) };
  m = QUOTE.exec(raw);
  if (m) return { cls: "md-quote", html: esc(m[1]) + mark(m[2]) + inline(m[3]) };
  m = TASK.exec(raw);
  if (m) {
    const done = m[3] !== " ";
    return { cls: done ? "md-task md-done" : "md-task", html: esc(m[1]) + glyph(m[2], done ? "md-box md-ticked" : "md-box") + inline(m[4]) };
  }
  m = BULLET.exec(raw);
  if (m) return { cls: "md-item", html: esc(m[1]) + glyph(m[2], "md-dot") + inline(m[3]) };
  m = NUMBER.exec(raw);
  if (m) return { cls: "md-item", html: esc(m[1]) + `<span class="md-num">${esc(m[2])}</span>` + inline(m[3]) };
  if (TABLE.test(raw)) return { cls: "md-table", html: raw.split("|").map(inline).join(`<span class="md-pipe">|</span>`) };
  return { cls: "", html: inline(raw) };
}

/** Every line of a body, the fences followed from the top. */
export function renderLines(lines) {
  const code = codeStates(lines);
  return lines.map((line, i) => renderLine(line, code[i]));
}

// -- what the keys do -------------------------------------------------------------
const LIST = /^(\s*)(?:([-*+])\s+\[[ xX]\]\s+|([-*+])\s+|(\d+)([.)])\s+|(>\s?))/;

/** What Enter writes after `before` (the line up to the caret): the next
    item's mark, or — on an item with nothing in it — the end of the list,
    as {clear: true}. A line that is no list gets a bare newline. */
export function continueLine(before, after = "") {
  const m = LIST.exec(before);
  if (!m) return { insert: "\n" };
  if (!before.slice(m[0].length).trim() && !after.trim()) return { clear: true, length: m[0].length };
  const [, indent, taskMark, bullet, number, delim, quote] = m;
  if (taskMark) return { insert: `\n${indent}${taskMark} [ ] ` };
  if (bullet) return { insert: `\n${indent}${bullet} ` };
  if (number) return { insert: `\n${indent}${Number(number) + 1}${delim} ` };
  return { insert: `\n${indent}${quote}` };
}

/** A task line ticked or unticked; any other line as it is. */
export function toggleTask(line) {
  const m = TASK.exec(line);
  if (!m) return line;
  const at = m[1].length + m[2].indexOf("[") + 1;
  return line.slice(0, at) + (m[3] === " " ? "x" : " ") + line.slice(at + 1);
}

/** Whether Tab indents this line: a list item does, anything else moves on. */
export const isListLine = (line) => TASK.test(line) || BULLET.test(line) || NUMBER.test(line);
