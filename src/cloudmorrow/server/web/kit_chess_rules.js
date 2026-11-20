/* The rules of chess, for the kit's `chess` screen: the same as
   quill/chess.py, which the terminal, the command line and a Quill's code
   use. Pure: no page, no server — node runs it in the tests.

   A game is the moves played from the start, each as a program writes it
   (`e2e4`, `e7e8q`, `e1g1`). From them: the position, what may be played,
   the moves as people write them (`Nf3`, `O-O`, `e8=Q#`), how it ended,
   and the clock (docs/CHESS.md).

   The board is 64 squares, a1 = 0, h1 = 7, a8 = 56; a piece is a letter,
   white's in capitals, black's small; an empty square is "". A move is
   {from, to, promote}. */

export const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
export const FILES = "abcdefgh";
export const PROMOTIONS = "qrbn";
export const WHITE_WINS = "1-0", BLACK_WINS = "0-1", DRAWN = "1/2-1/2";

export const squareOf = (name) => FILES.indexOf(name[0]) + 8 * (Number(name[1]) - 1);
export const nameOf = (sq) => FILES[sq % 8] + String(Math.floor(sq / 8) + 1);
export const colourOf = (piece) => (piece === piece.toUpperCase() ? "w" : "b");
const isUpper = (p) => p !== "" && p === p.toUpperCase();
const isLower = (p) => p !== "" && p === p.toLowerCase();

function steps(deltas) {
  const out = [];
  for (let sq = 0; sq < 64; sq++) {
    const f = sq % 8, r = Math.floor(sq / 8);
    out.push(deltas.filter(([df, dr]) => f + df >= 0 && f + df < 8 && r + dr >= 0 && r + dr < 8)
      .map(([df, dr]) => (r + dr) * 8 + f + df));
  }
  return out;
}
function rays(df, dr) {
  const out = [];
  for (let sq = 0; sq < 64; sq++) {
    const ray = [];
    let f = sq % 8 + df, r = Math.floor(sq / 8) + dr;
    while (f >= 0 && f < 8 && r >= 0 && r < 8) { ray.push(r * 8 + f); f += df; r += dr; }
    out.push(ray);
  }
  return out;
}
const KNIGHT = steps([[1, 2], [2, 1], [2, -1], [1, -2], [-1, -2], [-2, -1], [-2, 1], [-1, 2]]);
const KING = steps([[1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0], [-1, -1], [0, -1], [1, -1]]);
const STRAIGHT = [rays(1, 0), rays(-1, 0), rays(0, 1), rays(0, -1)];
const DIAGONAL = [rays(1, 1), rays(-1, 1), rays(1, -1), rays(-1, -1)];
const PAWN_TAKES = { w: steps([[-1, 1], [1, 1]]), b: steps([[-1, -1], [1, -1]]) };
// king, rook, where the king goes, where the rook goes, what must be empty, what must be safe
const CASTLING = {
  K: [4, 7, 6, 5, [5, 6], [4, 5, 6]],
  Q: [4, 0, 2, 3, [1, 2, 3], [4, 3, 2]],
  k: [60, 63, 62, 61, [61, 62], [60, 61, 62]],
  q: [60, 56, 58, 59, [57, 58, 59], [60, 59, 58]],
};
const LOSES = { 0: "Q", 4: "KQ", 7: "K", 56: "q", 60: "kq", 63: "k" };

export const uciOf = (m) => nameOf(m.from) + nameOf(m.to) + (m.promote || "");
export function moveOf(text) {
  const t = String(text || "").trim().toLowerCase();
  if (!/^[a-h][1-8][a-h][1-8][qrbn]?$/.test(t)) return null;
  return { from: squareOf(t.slice(0, 2)), to: squareOf(t.slice(2, 4)), promote: t.slice(4) };
}
const same = (a, b) => a.from === b.from && a.to === b.to && (a.promote || "") === (b.promote || "");

export class Position {
  constructor(board, turn = "w", castling = "KQkq", ep = -1, halfmove = 0, fullmove = 1) {
    Object.assign(this, { board, turn, castling, ep, halfmove, fullmove });
  }

  static fromFen(fen) {
    const parts = fen.trim().split(/\s+/);
    const board = new Array(64).fill("");
    parts[0].split("/").forEach((row, i) => {
      let f = 0;
      for (const ch of row) {
        if (/\d/.test(ch)) f += Number(ch);
        else { board[(7 - i) * 8 + f] = ch; f += 1; }
      }
    });
    return new Position(board, parts[1] === "b" ? "b" : "w", parts[2] && parts[2] !== "-" ? parts[2] : "",
      parts[3] && parts[3] !== "-" ? squareOf(parts[3]) : -1, Number(parts[4] || 0), Number(parts[5] || 1));
  }

  fen() {
    const rows = [];
    for (let r = 7; r >= 0; r--) {
      let row = "", empty = 0;
      for (let f = 0; f < 8; f++) {
        const p = this.board[r * 8 + f];
        if (p) { row += (empty ? String(empty) : "") + p; empty = 0; } else empty += 1;
      }
      rows.push(row + (empty ? String(empty) : ""));
    }
    return `${rows.join("/")} ${this.turn} ${this.castling || "-"} ${this.ep >= 0 ? nameOf(this.ep) : "-"} ${this.halfmove} ${this.fullmove}`;
  }

  key() { return this.fen().split(" ").slice(0, 4).join(" "); }

  king(side) { return this.board.indexOf(side === "w" ? "K" : "k"); }

  attacked(sq, by) {
    const b = this.board;
    const [pawn, knight, king, rook, bishop, queen] = by === "w" ? "PNKRBQ" : "pnkrbq";
    for (const s of PAWN_TAKES[by === "w" ? "b" : "w"][sq]) if (b[s] === pawn) return true;
    for (const s of KNIGHT[sq]) if (b[s] === knight) return true;
    for (const s of KING[sq]) if (b[s] === king) return true;
    for (const r of STRAIGHT) for (const s of r[sq]) { const p = b[s]; if (p) { if (p === rook || p === queen) return true; break; } }
    for (const r of DIAGONAL) for (const s of r[sq]) { const p = b[s]; if (p) { if (p === bishop || p === queen) return true; break; } }
    return false;
  }

  inCheck(side = this.turn) {
    const k = this.king(side);
    return k >= 0 && this.attacked(k, side === "w" ? "b" : "w");
  }

  pseudo() {
    const b = this.board, side = this.turn, out = [];
    const mine = side === "w" ? isUpper : isLower;
    for (let sq = 0; sq < 64; sq++) {
      const p = b[sq];
      if (!p || !mine(p)) continue;
      const kind = p.toLowerCase();
      if (kind === "p") this.pawn(sq, out);
      else if (kind === "n" || kind === "k") {
        for (const t of (kind === "n" ? KNIGHT : KING)[sq]) if (!b[t] || !mine(b[t])) out.push({ from: sq, to: t, promote: "" });
      } else {
        const lines = kind === "r" ? STRAIGHT : kind === "b" ? DIAGONAL : STRAIGHT.concat(DIAGONAL);
        for (const ray of lines) {
          for (const t of ray[sq]) {
            if (!b[t]) { out.push({ from: sq, to: t, promote: "" }); continue; }
            if (!mine(b[t])) out.push({ from: sq, to: t, promote: "" });
            break;
          }
        }
      }
    }
    this.castles(out);
    return out;
  }

  pawn(sq, out) {
    const b = this.board;
    const [step, home, last, theirs] = this.turn === "w" ? [8, 1, 7, isLower] : [-8, 6, 0, isUpper];
    const add = (to) => {
      if (Math.floor(to / 8) === last) for (const p of PROMOTIONS) out.push({ from: sq, to, promote: p });
      else out.push({ from: sq, to, promote: "" });
    };
    const one = sq + step;
    if (one >= 0 && one < 64 && !b[one]) {
      add(one);
      const two = one + step;
      if (Math.floor(sq / 8) === home && !b[two]) out.push({ from: sq, to: two, promote: "" });
    }
    for (const t of PAWN_TAKES[this.turn][sq]) if ((b[t] && theirs(b[t])) || t === this.ep) add(t);
  }

  castles(out) {
    const side = this.turn, b = this.board, enemy = side === "w" ? "b" : "w";
    for (const right of this.castling) {
      if (isUpper(right) !== (side === "w")) continue;
      const [k, r, kto, , empty, safe] = CASTLING[right];
      const [king, rook] = side === "w" ? ["K", "R"] : ["k", "r"];
      if (b[k] !== king || b[r] !== rook || empty.some((s) => b[s])) continue;
      if (safe.some((s) => this.attacked(s, enemy))) continue;
      out.push({ from: k, to: kto, promote: "" });
    }
  }

  apply(move) {
    const b = this.board.slice();
    const { from, to, promote } = move;
    let piece = b[from];
    const kind = piece.toLowerCase();
    let captured = b[to];
    b[from] = "";
    let ep = -1;
    if (kind === "p") {
      if (to === this.ep) { b[piece === "P" ? to - 8 : to + 8] = ""; captured = "p"; }
      if (Math.abs(to - from) === 16) {
        const mid = (from + to) / 2;
        const theirs = piece === "P" ? "p" : "P";
        if (PAWN_TAKES[colourOf(piece)][mid].some((s) => b[s] === theirs)) ep = mid;
      }
      if (promote) piece = piece === "P" ? promote.toUpperCase() : promote;
    } else if (kind === "k" && Math.abs(to - from) === 2) {
      for (const [k, r, kto, rto] of Object.values(CASTLING)) if (k === from && kto === to) { b[rto] = b[r]; b[r] = ""; }
    }
    b[to] = piece;
    let castling = this.castling;
    for (const sq of [from, to]) for (const gone of LOSES[sq] || "") castling = castling.replace(gone, "");
    return new Position(b, this.turn === "w" ? "b" : "w", castling, ep,
      kind === "p" || captured ? 0 : this.halfmove + 1, this.fullmove + (this.turn === "b" ? 1 : 0));
  }

  legal() {
    const side = this.turn;
    return this.pseudo().filter((m) => !this.apply(m).inCheck(side));
  }

  san(move, legal = this.legal()) {
    const piece = this.board[move.from];
    const kind = piece.toLowerCase();
    let text;
    if (kind === "k" && Math.abs(move.to - move.from) === 2) text = move.to > move.from ? "O-O" : "O-O-O";
    else {
      const takes = !!this.board[move.to] || (kind === "p" && move.to === this.ep);
      if (kind === "p") {
        text = (takes ? FILES[move.from % 8] + "x" : "") + nameOf(move.to);
        if (move.promote) text += "=" + move.promote.toUpperCase();
      } else {
        text = kind.toUpperCase();
        const rivals = legal.filter((m) => m.to === move.to && m.from !== move.from && this.board[m.from] === piece);
        if (rivals.length) {
          const sameFile = rivals.some((m) => m.from % 8 === move.from % 8);
          const sameRank = rivals.some((m) => Math.floor(m.from / 8) === Math.floor(move.from / 8));
          if (!sameFile) text += FILES[move.from % 8];
          else if (!sameRank) text += String(Math.floor(move.from / 8) + 1);
          else text += nameOf(move.from);
        }
        text += (takes ? "x" : "") + nameOf(move.to);
      }
    }
    const after = this.apply(move);
    if (after.inCheck()) text += after.legal().length ? "+" : "#";
    return text;
  }

  insufficient() {
    const rest = [];
    this.board.forEach((p, sq) => { if (p && p.toLowerCase() !== "k") rest.push([sq, p.toLowerCase()]); });
    if (rest.some(([, p]) => "pqr".includes(p))) return false;
    if (rest.length <= 1) return true;
    if (rest.every(([, p]) => p === "b")) return new Set(rest.map(([sq]) => (sq % 8 + Math.floor(sq / 8)) % 2)).size === 1;
    return false;
  }
}

/** The moves played, and every position on the way. A move that is no move stops it there. */
export class Game {
  constructor(moves = [], start = START) {
    this.positions = [Position.fromFen(start)];
    this.moves = [];
    this.sans = [];
    for (const text of moves || []) if (!this.play(text)) break;
  }

  get position() { return this.positions[this.positions.length - 1]; }
  get turn() { return this.position.turn; }
  legal() { return this.position.legal(); }

  /** Play a move — {from, to, promote} or its uci. The move, or null when it is none. */
  play(move) {
    const m = typeof move === "string" ? moveOf(move) : move;
    if (!m) return null;
    const pos = this.position;
    const legal = pos.legal();
    const found = legal.find((x) => same(x, m));
    if (!found) return null;
    this.sans.push(pos.san(found, legal));
    this.moves.push(found);
    this.positions.push(pos.apply(found));
    return found;
  }

  repeated() {
    const key = this.position.key();
    return this.positions.filter((p) => p.key() === key).length;
  }

  outcome() {
    const pos = this.position;
    if (!pos.legal().length) return pos.inCheck() ? { result: pos.turn === "w" ? BLACK_WINS : WHITE_WINS, reason: "checkmate" } : { result: DRAWN, reason: "stalemate" };
    if (pos.insufficient()) return { result: DRAWN, reason: "material" };
    if (pos.halfmove >= 100) return { result: DRAWN, reason: "fifty moves" };
    if (this.repeated() >= 3) return { result: DRAWN, reason: "repetition" };
    return null;
  }

  numbered() {
    const out = [];
    for (let i = 0; i < this.sans.length; i += 2) out.push([i / 2 + 1, this.sans[i], this.sans[i + 1] || ""]);
    return out;
  }
}

// -- the clock --------------------------------------------------------------------------------
/** What each side has left, in milliseconds, at `now` — or null for a game with no clock. */
export function timeLeft(fields, now = Date.now()) {
  if (!fields.clock) return null;
  const full = Number(fields.clock) * 1000;
  const left = {
    w: fields.white_left != null ? Number(fields.white_left) : full,
    b: fields.black_left != null ? Number(fields.black_left) : full,
  };
  const since = fields.turn_at ? Date.parse(fields.turn_at) : NaN;
  if (Number.isNaN(since) || fields.result) return left;
  const side = (fields.moves || []).length % 2 === 0 ? "w" : "b";
  left[side] = Math.max(0, left[side] - (now - since));
  return left;
}

/** 5:00, 0:42, and tenths under ten seconds: 0:07.3. */
export function clockText(ms) {
  ms = Math.max(0, Math.floor(ms));
  if (ms < 10000) return `0:${String(Math.floor(ms / 1000)).padStart(2, "0")}.${Math.floor((ms % 1000) / 100)}`;
  const total = Math.ceil(ms / 1000);
  const hours = Math.floor(total / 3600), minutes = Math.floor((total % 3600) / 60), secs = total % 60;
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}` : `${minutes}:${String(secs).padStart(2, "0")}`;
}

const HOW = {
  checkmate: "by checkmate", resigned: "by resignation", time: "on time", stalemate: "by stalemate",
  agreed: "by agreement", repetition: "by repetition", "fifty moves": "by the fifty-move rule",
  material: "for want of material", aborted: "— aborted",
};

/** How a game ended, in words: White won by checkmate. */
export function saidOf(result, reason) {
  const who = result === WHITE_WINS ? "White won" : result === BLACK_WINS ? "Black won" : "Drawn";
  return `${who} ${HOW[reason] || ""}`.trim();
}
