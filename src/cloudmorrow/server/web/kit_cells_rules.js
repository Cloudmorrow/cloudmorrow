/* The sheet kit's arithmetic, for the browser: a sheet's cells and their
   formulas — the same rules as quill/cells.py, which the terminal and the
   command line follow, held to the same cases by one test (docs/CELLS.md).
   Pure: nothing here touches the page or the server.

   A sheet is a `.cell` file: its text is one JSON object with `cells` in
   it, one entry per cell that has something in it, keyed by the cell's
   name: {"cells": {"A1": "Rent", "B1": "1200", "B4": "=SUM(B1:B3)"}}. What
   is kept is what was typed; what it is — a number, a formula, text — is
   worked out on reading.

   A value is a number, a string, a boolean, null (blank) or an Error. */

const REF = /^\$?([A-Za-z]{1,3})\$?([0-9]+)$/;
const NUMBER = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?%?$/;

export const LEAST_ROWS = 20;
export const LEAST_COLS = 8;

// -- names -------------------------------------------------------------------------
export function colName(index) {
  let name = "";
  let n = index + 1;
  while (n > 0) {
    const rest = (n - 1) % 26;
    name = String.fromCharCode(65 + rest) + name;
    n = Math.floor((n - 1) / 26);
  }
  return name;
}

export function colIndex(name) {
  let index = 0;
  for (const ch of name.toUpperCase()) index = index * 26 + (ch.charCodeAt(0) - 64);
  return index - 1;
}

/** `B2` (or `$B$2`) → [row 1, col 1], counted from zero; null for no cell. */
export function parseRef(text) {
  const match = REF.exec(String(text || "").trim());
  if (!match) return null;
  const row = parseInt(match[2], 10) - 1;
  if (row < 0) return null;
  return [row, colIndex(match[1])];
}

export const refName = (row, col) => `${colName(col)}${row + 1}`;

// -- the cells ----------------------------------------------------------------------
const isObject = (v) => !!v && typeof v === "object" && !Array.isArray(v);

/** The cells of a `.cell` file, by name, as typed: the file's text, or the
    object it holds — {cells: {…}}, or the cells alone; anything else is an
    empty sheet. */
export function parseCells(value) {
  let cells = value;
  if (typeof value === "string") {
    try { cells = value.trim() ? JSON.parse(value) : {}; }
    catch { return {}; }
  }
  if (isObject(cells) && isObject(cells.cells)) cells = cells.cells;
  if (!isObject(cells)) return {};
  const found = {};
  for (const [key, raw] of Object.entries(cells)) {
    const at = parseRef(key);
    if (!at || raw === null || raw === undefined) continue;
    const value = String(raw);
    if (value.trim()) found[refName(...at)] = value;
  }
  return found;
}

export function sortKey(name) {
  return parseRef(name) || [0, 0];
}

const byPlace = (a, b) => {
  const [ra, ca] = sortKey(a);
  const [rb, cb] = sortKey(b);
  return ra - rb || ca - cb;
};

/** The cells as they are written: those with something, by row then column. */
export function orderedCells(cells) {
  const ordered = {};
  for (const name of Object.keys(cells).sort(byPlace)) {
    if (String(cells[name]).trim()) ordered[name] = cells[name];
  }
  return ordered;
}

/** A `.cell` file's text: one JSON object with the cells in it, a cell a
    line, by row then column — the same bytes quill/cells.py writes. */
export const fileText = (cells) => JSON.stringify({ cells: orderedCells(cells) }, null, 2) + "\n";

/** [rows, cols] the sheet is drawn with: what is used, with room beyond it. */
export function extent(cells) {
  let rows = 0;
  let cols = 0;
  for (const name of Object.keys(cells)) {
    const at = parseRef(name);
    if (at) { rows = Math.max(rows, at[0] + 1); cols = Math.max(cols, at[1] + 1); }
  }
  return [Math.max(LEAST_ROWS, rows + 5), Math.max(LEAST_COLS, cols + 2)];
}

// -- values ---------------------------------------------------------------------------
export class CellError {
  constructor(code) { this.code = code; }
  toString() { return this.code; }
}
export const DIV0 = new CellError("#DIV/0!");
export const REF_ERR = new CellError("#REF!");
export const NAME_ERR = new CellError("#NAME?");
export const VALUE_ERR = new CellError("#VALUE!");
export const CIRC = new CellError("#CIRC!");
export const NA = new CellError("#N/A");
const NUM_ERR = new CellError("#NUM!");

export const isError = (v) => v instanceof CellError;
const isNumber = (v) => typeof v === "number";
const isBool = (v) => typeof v === "boolean";

/** What a cell's text is, when it is not a formula. */
export function literal(raw) {
  const text = String(raw || "");
  if (!text.trim()) return null;
  if (text.startsWith("'")) return text.slice(1);
  const stripped = text.trim();
  const upper = stripped.toUpperCase();
  if (upper === "TRUE") return true;
  if (upper === "FALSE") return false;
  if (NUMBER.test(stripped)) {
    if (stripped.endsWith("%")) return Number(stripped.slice(0, -1)) / 100;
    return Number(stripped);
  }
  return text;
}

export const isFormula = (raw) => String(raw || "").startsWith("=");

// What a formula may end in and still want a reference: `=`, an operator,
// `(`, a comma, a colon. There the arrows point one out (point mode).
const WANTS_REF = new Set("=+-*/^&<>(,;:");

// Whether a cell's name may go where this (typed so far) ends.
export function wantsRef(text) {
  const typed = String(text || "").replace(/\s+$/, "");
  return isFormula(typed) && WANTS_REF.has(typed[typed.length - 1]);
}

// `B1` for one cell; `B1:C3` for two corners, whichever way round.
export function rangeName(one, other) {
  const [top, bottom] = [Math.min(one[0], other[0]), Math.max(one[0], other[0])];
  const [left, right] = [Math.min(one[1], other[1]), Math.max(one[1], other[1])];
  const first = refName(top, left);
  return top === bottom && left === right ? first : `${first}:${refName(bottom, right)}`;
}

/** A number to ten significant figures, without a trailing `.0`. */
export function numberText(x) {
  if (!Number.isFinite(x)) return "#NUM!";
  if (Number.isInteger(x) && Math.abs(x) < 1e21) return String(x);
  const rounded = Number(x.toPrecision(10));
  if (rounded === 0) return "0";
  if (Number.isInteger(rounded)) return String(rounded);
  return String(rounded);
}

/** A value as a cell shows it. */
export function display(value) {
  if (value === null || value === undefined) return "";
  if (isError(value)) return value.code;
  if (isBool(value)) return value ? "TRUE" : "FALSE";
  if (isNumber(value)) return numberText(value);
  return String(value);
}

export function toNumber(value) {
  if (value === null || value === undefined) return 0;
  if (isError(value)) return value;
  if (isBool(value)) return value ? 1 : 0;
  if (isNumber(value)) return value;
  const text = String(value).trim();
  const got = text ? literal(text) : null;
  return isNumber(got) ? got : VALUE_ERR;
}

const toText = display;

function truth(value) {
  if (isError(value)) return value;
  if (value === null || value === undefined) return false;
  if (isBool(value)) return value;
  if (isNumber(value)) return value !== 0;
  const upper = String(value).trim().toUpperCase();
  if (upper === "TRUE") return true;
  if (upper === "FALSE") return false;
  return VALUE_ERR;
}

// -- the tokens -------------------------------------------------------------------------
const TOKEN = /\s*(?:(?<number>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)|(?<string>"(?:[^"]|"")*")|(?<name>\$?[A-Za-z_][A-Za-z0-9_.]*\$?[0-9]*)|(?<op><>|<=|>=|[-+*/^&=<>%(),:]))/y;

class FormulaError extends Error {
  constructor(error) { super(error.code); this.error = error; }
}

function tokenize(text) {
  const tokens = [];
  let pos = 0;
  while (pos < text.length) {
    if (text.slice(pos).trim() === "") break;
    TOKEN.lastIndex = pos;
    const match = TOKEN.exec(text);
    if (!match) throw new FormulaError(VALUE_ERR);
    pos = TOKEN.lastIndex;
    const kind = Object.keys(match.groups).find((k) => match.groups[k] !== undefined);
    tokens.push([kind, match.groups[kind]]);
  }
  return tokens;
}

// -- the tree ---------------------------------------------------------------------------
// A node is an array: ["num", 1], ["str", "x"], ["bool", true], ["ref", row, col],
// ["range", r0, c0, r1, c1], ["call", NAME, [args]], ["neg", node], ["pct", node],
// ["op", symbol, left, right].
class Parser {
  constructor(text) { this.tokens = tokenize(text); this.pos = 0; }
  peek() { return this.pos < this.tokens.length ? this.tokens[this.pos] : null; }
  take(kind, value) {
    const token = this.peek();
    if (!token || (kind && token[0] !== kind) || (value !== undefined && token[1] !== value)) {
      throw new FormulaError(VALUE_ERR);
    }
    this.pos += 1;
    return token;
  }
  isOp(...symbols) {
    const token = this.peek();
    return !!token && token[0] === "op" && symbols.includes(token[1]);
  }
  parse() {
    const node = this.comparison();
    if (this.peek()) throw new FormulaError(VALUE_ERR);
    return node;
  }
  comparison() {
    let node = this.concat();
    while (this.isOp("=", "<>", "<", ">", "<=", ">=")) node = ["op", this.take()[1], node, this.concat()];
    return node;
  }
  concat() {
    let node = this.additive();
    while (this.isOp("&")) { this.take(); node = ["op", "&", node, this.additive()]; }
    return node;
  }
  additive() {
    let node = this.term();
    while (this.isOp("+", "-")) node = ["op", this.take()[1], node, this.term()];
    return node;
  }
  term() {
    let node = this.power();
    while (this.isOp("*", "/")) node = ["op", this.take()[1], node, this.power()];
    return node;
  }
  power() {
    let node = this.unary();
    while (this.isOp("^")) { this.take(); node = ["op", "^", node, this.unary()]; }
    return node;
  }
  unary() {
    if (this.isOp("-")) { this.take(); return ["neg", this.unary()]; }
    if (this.isOp("+")) { this.take(); return this.unary(); }
    return this.postfix();
  }
  postfix() {
    let node = this.primary();
    while (this.isOp("%")) { this.take(); node = ["pct", node]; }
    return node;
  }
  primary() {
    const token = this.peek();
    if (!token) throw new FormulaError(VALUE_ERR);
    const [kind, text] = token;
    if (kind === "number") { this.take(); return ["num", Number(text)]; }
    if (kind === "string") { this.take(); return ["str", text.slice(1, -1).replace(/""/g, '"')]; }
    if (kind === "op" && text === "(") {
      this.take();
      const node = this.comparison();
      this.take("op", ")");
      return node;
    }
    if (kind === "name") {
      this.take();
      const upper = text.toUpperCase();
      if (upper === "TRUE") return ["bool", true];
      if (upper === "FALSE") return ["bool", false];
      if (this.isOp("(")) {
        this.take();
        const args = [];
        if (!this.isOp(")")) {
          args.push(this.comparison());
          while (this.isOp(",")) { this.take(); args.push(this.comparison()); }
        }
        this.take("op", ")");
        return ["call", upper.replace(/\$/g, ""), args];
      }
      const at = parseRef(text);
      if (!at) throw new FormulaError(NAME_ERR);
      if (this.isOp(":")) {
        this.take();
        const other = parseRef(this.take("name")[1]);
        if (!other) throw new FormulaError(REF_ERR);
        return ["range", Math.min(at[0], other[0]), Math.min(at[1], other[1]),
                Math.max(at[0], other[0]), Math.max(at[1], other[1])];
      }
      return ["ref", at[0], at[1]];
    }
    throw new FormulaError(VALUE_ERR);
  }
}

export function parseFormula(raw) {
  return new Parser(String(raw).slice(1)).parse();
}

/** Every cell a formula reads, by name. */
export function references(raw) {
  if (!isFormula(raw)) return [];
  let tree;
  try { tree = parseFormula(raw); } catch { return []; }
  const found = [];
  const walk = (node) => {
    const kind = node[0];
    if (kind === "ref") found.push(refName(node[1], node[2]));
    else if (kind === "range") {
      for (let r = node[1]; r <= node[3]; r += 1) for (let c = node[2]; c <= node[4]; c += 1) found.push(refName(r, c));
    } else if (kind === "call") node[2].forEach(walk);
    else if (kind === "neg" || kind === "pct") walk(node[1]);
    else if (kind === "op") { walk(node[2]); walk(node[3]); }
  };
  walk(tree);
  return found;
}

// -- the functions ----------------------------------------------------------------------
const flat = (args) => args.flatMap((a) => (Array.isArray(a) ? a : [a]));

function numbers(args, loose) {
  const out = [];
  for (const arg of args) {
    if (Array.isArray(arg)) {
      for (const v of arg) {
        if (isError(v)) return v;
        if (isNumber(v)) out.push(v);
      }
    } else {
      if (isError(arg)) return arg;
      if ((arg === null || arg === undefined) && loose) continue;
      const n = toNumber(arg);
      if (isError(n)) return n;
      out.push(n);
    }
  }
  return out;
}

const one = (args, index, fallback = null) => {
  if (index >= args.length) return fallback;
  const value = args[index];
  return Array.isArray(value) ? VALUE_ERR : value;
};
const firstError = (values) => values.find(isError) || null;

function criterion(crit) {
  if (isError(crit)) return crit;
  const text = typeof crit === "string" ? crit : display(crit);
  const match = /^(<>|<=|>=|=|<|>)(.*)$/.exec(text);
  const [symbol, rest] = match ? [match[1], match[2]] : ["=", text];
  const target = rest.trim() ? literal(rest.trim()) : null;
  return (value) => {
    if (symbol === "=" || symbol === "<>") {
      let same;
      if (target === null) same = value === null || value === undefined || value === "";
      else if (isNumber(target)) same = isNumber(value) && value === target;
      else if (isBool(target)) same = isBool(value) && value === target;
      else same = typeof value === "string" && value.toLowerCase() === String(target).toLowerCase();
      return symbol === "=" ? same : !same;
    }
    if (!isNumber(target) || !isNumber(value)) return false;
    return { "<": value < target, ">": value > target, "<=": value <= target, ">=": value >= target }[symbol];
  };
}

function round(x, places) {
  const factor = 10 ** places;
  const shifted = Math.abs(x) * factor;
  const rounded = Math.floor(shifted + 0.5 + 1e-9);
  return Math.sign(x) * (rounded / factor) || 0;
}

function power(x, y) {
  const out = x ** y;
  return Number.isFinite(out) ? out : NUM_ERR;
}

const sumOf = (nums) => nums.reduce((a, b) => a + b, 0);

function withNumbers(args, loose, fn) {
  const nums = numbers(args, loose);
  return isError(nums) ? nums : fn(nums);
}

export const FUNCTIONS = {
  SUM: (args) => withNumbers(args, true, sumOf),
  AVERAGE: (args) => withNumbers(args, true, (nums) => (nums.length ? sumOf(nums) / nums.length : DIV0)),
  MIN: (args) => withNumbers(args, true, (nums) => (nums.length ? Math.min(...nums) : 0)),
  MAX: (args) => withNumbers(args, true, (nums) => (nums.length ? Math.max(...nums) : 0)),
  PRODUCT: (args) => withNumbers(args, true, (nums) => (nums.length ? nums.reduce((a, b) => a * b, 1) : 0)),
  COUNT: (args) => flat(args).filter(isNumber).length,
  COUNTA: (args) => flat(args).filter((v) => v !== null && v !== undefined && v !== "").length,
  IF: (args) => {
    if (!args.length) return VALUE_ERR;
    const cond = truth(one(args, 0));
    if (isError(cond)) return cond;
    return cond ? one(args, 1, true) : one(args, 2, false);
  },
  AND: (args) => {
    const values = flat(args);
    const err = firstError(values);
    if (err) return err;
    const tests = values.filter((v) => v !== null && typeof v !== "string").map(truth);
    return tests.length ? tests.every(Boolean) : VALUE_ERR;
  },
  OR: (args) => {
    const values = flat(args);
    const err = firstError(values);
    if (err) return err;
    const tests = values.filter((v) => v !== null && typeof v !== "string").map(truth);
    return tests.length ? tests.some(Boolean) : VALUE_ERR;
  },
  NOT: (args) => { const c = truth(one(args, 0)); return isError(c) ? c : !c; },
  ROUND: (args) => {
    const x = toNumber(one(args, 0));
    const places = toNumber(one(args, 1, 0));
    if (isError(x)) return x;
    if (isError(places)) return places;
    return round(x, Math.trunc(places));
  },
  ABS: (args) => { const x = toNumber(one(args, 0)); return isError(x) ? x : Math.abs(x); },
  INT: (args) => { const x = toNumber(one(args, 0)); return isError(x) ? x : Math.floor(x); },
  MOD: (args) => {
    const x = toNumber(one(args, 0));
    const y = toNumber(one(args, 1));
    if (isError(x)) return x;
    if (isError(y)) return y;
    if (y === 0) return DIV0;
    return x - y * Math.floor(x / y);
  },
  SQRT: (args) => {
    const x = toNumber(one(args, 0));
    if (isError(x)) return x;
    return x < 0 ? NUM_ERR : Math.sqrt(x);
  },
  POWER: (args) => {
    const x = toNumber(one(args, 0));
    const y = toNumber(one(args, 1));
    if (isError(x)) return x;
    if (isError(y)) return y;
    return power(x, y);
  },
  LEN: (args) => { const v = one(args, 0); return isError(v) ? v : toText(v).length; },
  CONCAT: (args) => { const values = flat(args); return firstError(values) || values.map(toText).join(""); },
  UPPER: (args) => { const v = one(args, 0); return isError(v) ? v : toText(v).toUpperCase(); },
  LOWER: (args) => { const v = one(args, 0); return isError(v) ? v : toText(v).toLowerCase(); },
  TRIM: (args) => { const v = one(args, 0); return isError(v) ? v : toText(v).split(/\s+/).filter(Boolean).join(" "); },
  IFERROR: (args) => { const v = one(args, 0); return isError(v) ? one(args, 1, "") : v; },
  COUNTIF: (args) => {
    if (args.length < 2) return VALUE_ERR;
    const values = Array.isArray(args[0]) ? args[0] : [args[0]];
    const test = criterion(args[1]);
    return isError(test) ? test : values.filter(test).length;
  },
  SUMIF: (args) => {
    if (args.length < 2) return VALUE_ERR;
    const values = Array.isArray(args[0]) ? args[0] : [args[0]];
    const summed = args.length > 2 && Array.isArray(args[2]) ? args[2] : values;
    const test = criterion(args[1]);
    if (isError(test)) return test;
    let total = 0;
    values.forEach((v, i) => { if (test(v) && i < summed.length && isNumber(summed[i])) total += summed[i]; });
    return total;
  },
};
FUNCTIONS.CONCATENATE = FUNCTIONS.CONCAT;

// -- comparing ----------------------------------------------------------------------
const blankLike = (other) => (typeof other === "string" ? "" : isBool(other) ? false : 0);
function rank(value) {
  if (isBool(value)) return [2, value ? 1 : 0];
  if (isNumber(value)) return [0, value];
  return [1, String(value).toLowerCase()];
}
export function compare(symbol, left, right) {
  let a = left;
  let b = right;
  if (a === null || a === undefined) a = blankLike(b);
  if (b === null || b === undefined) b = blankLike(a);
  const [ta, va] = rank(a);
  const [tb, vb] = rank(b);
  const order = ta - tb || (va < vb ? -1 : va > vb ? 1 : 0);
  switch (symbol) {
    case "=": return order === 0;
    case "<>": return order !== 0;
    case "<": return order < 0;
    case ">": return order > 0;
    case "<=": return order <= 0;
    default: return order >= 0;
  }
}

// -- the sheet ------------------------------------------------------------------------
export class Sheet {
  constructor(cells = {}) {
    this.cells = { ...cells };
    this.cache = new Map();
    this.busy = new Set();
  }
  /** From a `.cell` file's text (a file record's `text` field). */
  static fromText(value) { return new Sheet(parseCells(value)); }
  /** The `.cell` file's text, for writing back. */
  toText() { return fileText(this.cells); }
  raw(name) { return this.cells[name] || ""; }
  /** What is typed into a cell; nothing clears it. */
  set(name, raw) {
    const at = parseRef(name);
    if (!at) throw new Error(`${name} is no cell`);
    const key = refName(...at);
    if (String(raw || "").trim()) this.cells[key] = String(raw);
    else delete this.cells[key];
    this.cache.clear();
  }
  get extent() { return extent(this.cells); }
  value(name) {
    const at = parseRef(name);
    if (!at) return REF_ERR;
    const key = refName(...at);
    if (this.cache.has(key)) return this.cache.get(key);
    const raw = this.cells[key] || "";
    let value;
    if (!isFormula(raw)) value = literal(raw);
    else if (this.busy.has(key)) return CIRC;
    else {
      this.busy.add(key);
      try { value = single(this.evaluate(parseFormula(raw))); }
      catch (err) { if (err instanceof FormulaError) value = err.error; else throw err; }
      finally { this.busy.delete(key); }
    }
    this.cache.set(key, value);
    return value;
  }
  shown(name) { return display(this.value(name)); }
  values() {
    const out = {};
    for (const name of Object.keys(this.cells).sort(byPlace)) out[name] = this.value(name);
    return out;
  }
  evaluate(node) {
    const kind = node[0];
    if (kind === "num" || kind === "str" || kind === "bool") return node[1];
    if (kind === "ref") return this.value(refName(node[1], node[2]));
    if (kind === "range") {
      const out = [];
      for (let r = node[1]; r <= node[3]; r += 1) for (let c = node[2]; c <= node[4]; c += 1) out.push(this.value(refName(r, c)));
      return out;
    }
    if (kind === "neg") { const x = toNumber(single(this.evaluate(node[1]))); return isError(x) ? x : -x; }
    if (kind === "pct") { const x = toNumber(single(this.evaluate(node[1]))); return isError(x) ? x : x / 100; }
    if (kind === "call") {
      const fn = FUNCTIONS[node[1]];
      if (!fn) return NAME_ERR;
      return fn(node[2].map((arg) => this.evaluate(arg)));
    }
    if (kind === "op") return operate(node[1], single(this.evaluate(node[2])), single(this.evaluate(node[3])));
    return VALUE_ERR;
  }
}

const single = (value) => (Array.isArray(value) ? VALUE_ERR : value);

function operate(symbol, left, right) {
  if (isError(left)) return left;
  if (isError(right)) return right;
  if (symbol === "&") return toText(left) + toText(right);
  if (["=", "<>", "<", ">", "<=", ">="].includes(symbol)) return compare(symbol, left, right);
  const x = toNumber(left);
  const y = toNumber(right);
  if (isError(x)) return x;
  if (isError(y)) return y;
  switch (symbol) {
    case "+": return x + y;
    case "-": return x - y;
    case "*": return x * y;
    case "/": return y === 0 ? DIV0 : x / y;
    case "^": return power(x, y);
    default: return VALUE_ERR;
  }
}

/** Every cell of a sheet, as shown: {name: text}, for a test to compare. */
export function shownCells(value) {
  const sheet = Sheet.fromText(value);
  const out = {};
  for (const name of Object.keys(sheet.cells).sort(byPlace)) out[name] = sheet.shown(name);
  return out;
}
