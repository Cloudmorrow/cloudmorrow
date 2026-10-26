/* The document kit's model, for the browser: a document's blocks and their
   runs — the same rules as quill/docs.py, held to the same cases by one
   test (docs/DOCS.md). Pure: nothing here touches the page or the server.

   A document is a `.docs` file: one JSON object with `blocks` in it. A
   block is a paragraph, a heading (level 1 to 3), a bullet or numbered
   item (with a level), a quote, or a table (rows of cells of runs); a run
   is text and what is true of it: bold, italic, underline, strike, a
   link. Nothing else is kept. */

export const KINDS = ["paragraph", "heading", "bullet", "numbered", "quote", "table"];
export const FLAGS = ["bold", "italic", "underline", "strike"];
export const ALIGNS = ["center", "right", "justify"];

const isObject = (v) => !!v && typeof v === "object" && !Array.isArray(v);

// -- runs -----------------------------------------------------------------------------
/** One run: its text, and only what is true of it, in a fixed order. */
export function run(text, what = {}) {
  const out = { text: String(text) };
  for (const flag of FLAGS) if (what[flag]) out[flag] = true;
  if (what.link) out.link = String(what.link);
  return out;
}

function cleanRun(value) {
  if (typeof value === "string") return value ? run(value) : null;
  if (!isObject(value) || typeof value.text !== "string" || !value.text) return null;
  return run(value.text, value);
}

const sameStyle = (a, b) => [...FLAGS, "link"].every((k) => (a[k] || undefined) === (b[k] || undefined));

/** Runs cleaned, and neighbours alike joined. */
export function mergeRuns(runs) {
  const out = [];
  for (const raw of Array.isArray(runs) ? runs : []) {
    const one = cleanRun(raw);
    if (!one) continue;
    if (out.length && sameStyle(out[out.length - 1], one)) out[out.length - 1].text += one.text;
    else out.push(one);
  }
  return out;
}

export const runsText = (runs) => (runs || []).map((r) => r.text || "").join("");

// -- blocks ----------------------------------------------------------------------------
/** One block, in a fixed order of keys: kind, level, align, then runs or rows. */
export function block(kind, runs = [], { level = 0, align = "", rows = [] } = {}) {
  const out = { kind };
  if (kind === "heading") out.level = Math.min(3, Math.max(1, Math.trunc(level) || 1));
  else if ((kind === "bullet" || kind === "numbered") && level) out.level = Math.max(0, Math.trunc(level));
  if (ALIGNS.includes(align) && kind !== "table") out.align = align;
  if (kind === "table") {
    out.rows = rows.map((row) => row.map((cell) => ({ runs: mergeRuns(isObject(cell) ? cell.runs : cell) })));
  } else {
    out.runs = mergeRuns(runs);
  }
  return out;
}

function cleanBlock(value) {
  if (!isObject(value) || !KINDS.includes(value.kind)) return null;
  if (value.kind === "table") {
    let rows = (Array.isArray(value.rows) ? value.rows : []).filter(Array.isArray);
    if (!rows.length) return null;
    const width = Math.max(...rows.map((r) => r.length));
    rows = rows.map((row) => row.concat(Array.from({ length: width - row.length }, () => ({ runs: [] }))));
    return block("table", [], { rows });
  }
  const level = Number.isInteger(value.level) ? value.level : 0;
  const align = typeof value.align === "string" ? value.align : "";
  return block(value.kind, Array.isArray(value.runs) ? value.runs : [], { level, align });
}

/** A block's words alone; a table's cells by tabs, its rows by lines. */
export function blockText(one) {
  if (one.kind === "table") return one.rows.map((row) => row.map((c) => runsText(c.runs)).join("\t")).join("\n");
  return runsText(one.runs);
}

// -- the file --------------------------------------------------------------------------
export function parseBlocks(value) {
  let data = value;
  if (typeof value === "string") {
    try { data = value.trim() ? JSON.parse(value) : {}; }
    catch { return []; }
  }
  if (isObject(data) && Array.isArray(data.blocks)) data = data.blocks;
  if (!Array.isArray(data)) return [];
  return data.map(cleanBlock).filter(Boolean);
}

/** A `.docs` file's text: one JSON object with the blocks in it — the same
    bytes quill/docs.py writes. */
export const fileText = (blocks) => JSON.stringify({ blocks }, null, 2) + "\n";

export class Doc {
  constructor(blocks = []) { this.blocks = blocks.map(cleanBlock).filter(Boolean); }
  /** From a `.docs` file's text (a file record's `text` field). */
  static fromText(value) { return new Doc(parseBlocks(value)); }
  /** The `.docs` file's text, for writing back. */
  toText() { return fileText(this.blocks); }
  /** The words alone, a block a line. */
  get text() { return this.blocks.map(blockText).join("\n"); }
  get words() { return this.text.split(/\s+/).filter(Boolean).length; }
}

/** The first words after the title: what a list shows under a document's name. */
export function preview(doc, chars = 120) {
  let lines = doc.blocks.map((b) => blockText(b).trim()).filter(Boolean);
  if (lines.length > 1 && doc.blocks.length && doc.blocks[0].kind === "heading") lines = lines.slice(1);
  const text = lines.join(" ");
  return text.length > chars ? text.slice(0, chars - 1) + "…" : text;
}
