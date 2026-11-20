/* The kit's `chess`: games of chess, drawn from the screen's bindings alone.

   A chess screen names the games (`model`, with the kit's own field names:
   docs/CHESS.md), the Quill's action a move is played with (`play`, its
   field `move`), the one a game is started with (`start`: `opponent`, and
   the choices its `clock` and `colour` fields offer), and, optionally, the
   computers there are to play (`computers`: a name and a level each).

     #/q/<quill>/<screen>              the games, newest first, with New
     #/q/<quill>/<screen>/<id>         one game at the board
     #/q/<quill>/<screen>/game=<id>    the same, as a Quill's `go` says it

   The board is seen from above, white at the bottom unless you play black.
   A piece is moved by pressing it and then where it goes, or by dragging
   it there; where it may go is dotted, the last move is lit, a king in
   check glows. A pawn reaching the end asks what it becomes. Every move is
   checked here by the rules (kit_chess_rules.js) and again by the Quill's
   code, which keeps it; a move it refuses is taken back.

   The clocks tick here from what the game keeps (what each side had left
   after its last move, and since when the side to move has been
   thinking); the one whose time runs out is told to the Quill, which
   checks it. The other player's move arrives by the change feed. On a
   computer the games are down the left, the board in the middle, the
   clocks and the moves beside it; on a phone the games, then the board. */

import {
  api, app, esc, formatDate, heading, icons, mount, nav, occupy, recordsUrl, replace, seconds, session, tabs,
  toast, vacate, wireShell,
} from "./core.js";
import { mayWrite } from "./kit.js";
import { peopleList, run } from "./actions.js";
import { ask, openSheet } from "./dialog.js";
import { listenChanges } from "./changes.js";
import {
  clockText, DRAWN, Game, nameOf, PROMOTIONS, saidOf, shownMoves, thinking, timeLeft, uciOf, WHITE_WINS,
} from "./kit_chess_rules.js";
import { kindOf, play, setSound, soundOn, wake } from "./kit_chess_sound.js";
import { piece, pieceName, sprite, thumb } from "./kit_chess_pieces.js";

const desk = () => matchMedia("(min-width: 900px) and (min-height: 600px)").matches;
const POLL = 5000;          // how often a game is asked for when the change feed is down
const TICK = 100;           // how often the running clock is drawn again
const LOW = 20000;          // under this, a clock is red
const HOW = {
  checkmate: "by checkmate", resigned: "by resignation", time: "on time", stalemate: "by stalemate",
  agreed: "by agreement", repetition: "by repetition", "fifty moves": "by the fifty-move rule",
  material: "for want of material",
};

// -- the screen's bindings ---------------------------------------------------------------
function bindingsOf(at) {
  const { quill, screen } = at;
  const model = quill.models[screen.model];
  const actions = quill.actions || [];
  return {
    model,
    title: screen.title || model.title,
    play: actions.find((a) => a.id === screen.play) || null,
    start: actions.find((a) => a.id === screen.start) || null,
    computers: screen.computers ? quill.models[screen.computers] || null : null,
  };
}

let live = null;   // {stop} while a chess screen is up

function stop() {
  if (live) live.stop();
  live = null;
}

function holdUntilLeft() {
  const mine = live;
  const hold = { stays: () => false, leave: async () => { if (live === mine) stop(); vacate(hold); }, flush: () => {} };
  occupy(hold);
}

export async function renderChess(at, arg) {
  stop();
  sprite();
  // A Quill's `go("games", game=<id>)` arrives as parameters: that game, at its own address.
  if (arg && arg.includes("=")) {
    const id = new URLSearchParams(arg).get("game");
    replace(id ? `${at.base}/${encodeURIComponent(id)}` : at.base);
    arg = id || "";
  }
  const b = bindingsOf(at);
  const [records, people] = await Promise.all([api("GET", recordsUrl(b.model.id)), peopleList()]);
  const names = new Map(people.map((p) => [p.username, p.display_name || p.username]));
  const s = { at, b, names, games: records, open: arg || "" };
  if (desk()) return drawDesk(s);
  if (!arg) return drawList(s);
  return drawPhoneGame(s);
}

// -- who is who ----------------------------------------------------------------------------
const me = () => session.user;
const sideOf = (f) => {
  if (f.white === me() && f.computer !== "white") return "w";
  if (f.black === me() && f.computer !== "black") return "b";
  return "";
};
const nameIn = (s, f, side) => {
  const who = side === "w" ? f.white : f.black;
  if (f.computer === (side === "w" ? "white" : "black")) return who;
  if (who === me()) return "You";
  return s.names.get(who) || who;
};
const opponentOf = (s, f) => {
  const mine = sideOf(f);
  if (!mine) return `${nameIn(s, f, "w")} – ${nameIn(s, f, "b")}`;
  return nameIn(s, f, mine === "w" ? "b" : "w");
};
const clockSaid = (f) => (f.clock ? `${Math.round(Number(f.clock) / 60)} min` : "No limit");

/** Where a game stands, as the person reads it: Your move, Sara to move, You won by checkmate. */
function standing(s, f) {
  const mine = sideOf(f);
  if (f.result) {
    const how = HOW[f.reason] || "";
    if (f.reason === "aborted") return "Aborted";
    if (f.result === DRAWN) return `Drawn ${how}`.trim();
    const winner = f.result === WHITE_WINS ? "w" : "b";
    if (!mine) return saidOf(f.result, f.reason);
    return winner === mine ? `You won ${how}`.trim() : `${opponentOf(s, f)} won ${how}`.trim();
  }
  const turn = (f.moves || []).length % 2 === 0 ? "w" : "b";
  if (mine && turn === mine) return "Your move";
  return `${nameIn(s, f, turn)} to move`;
}

// -- the games --------------------------------------------------------------------------
function groupsOf(s) {
  const yours = [], theirs = [], over = [];
  const newest = (x, y) => String(y.updated_at || "").localeCompare(String(x.updated_at || ""));
  for (const r of [...s.games].sort(newest)) {
    const f = r.fields;
    if (f.result) over.push(r);
    else if (sideOf(f) && ((f.moves || []).length % 2 === 0 ? "w" : "b") === sideOf(f)) yours.push(r);
    else theirs.push(r);
  }
  return [["Your move", yours], ["Waiting", theirs], ["Finished", over]].filter(([, list]) => list.length);
}

function gameRow(s, r) {
  const f = r.fields;
  const g = new Game(f.moves || []);
  const changed = seconds(r.updated_at || r.created_at);
  const lit = r.id === s.open ? " current" : "";
  const said = standing(s, f);
  const tone = said === "Your move" ? " yours" : "";
  return `<a class="row cg-row${lit}" href="${s.at.base}/${encodeURIComponent(r.id)}" data-id="${esc(r.id)}">
    <span class="cg-row-board">${thumb(g.position.board, sideOf(f) === "b")}</span>
    <span class="main"><span class="title">${esc(opponentOf(s, f))}${f.level && f.computer ? ` <span class="cg-level">Level ${esc(String(f.level))}</span>` : ""}</span>
      <span class="meta"><span class="cg-standing${tone}">${esc(said)}</span><span class="preview">${esc(clockSaid(f))}${
        changed ? ` · ${esc(formatDate(changed))}` : ""}</span></span></span>${icons.chevronRight}</a>`;
}

function listing(s) {
  const groups = groupsOf(s);
  const writes = !!s.b.start && mayWrite(s.b.model);
  if (!groups.length) {
    return `<p class="empty"><b>No games yet</b>${writes ? "Start one with the button at the top: against somebody here, or the computer." : ""}</p>`;
  }
  return groups.map(([label, list]) =>
    `<p class="group-label">${esc(label)}</p><div class="group">${list.map((r) => gameRow(s, r)).join("")}</div>`).join("");
}

function headActions(s) {
  if (!s.b.start || !mayWrite(s.b.model)) return "";
  return `<button class="compose cg-new" aria-label="New game">${icons.compose}</button>`;
}

function wireList(s) {
  const pen = app.querySelector(".cg-new");
  if (pen) pen.addEventListener("click", () => newGame(s));
}

function drawList(s) {
  const { at } = s;
  mount(nav({ title: at.screen.label }) + `
    <main class="kit-chess">
      ${heading(at.screen.label, headActions(s))}
      <div class="listing">${listing(s)}</div>
    </main>` + tabs(at.tab));
  wireShell();
  wireList(s);
  const refresh = async () => {
    try {
      s.games = await api("GET", recordsUrl(s.b.model.id));
      const el = app.querySelector(".kit-chess .listing");
      if (el) el.innerHTML = listing(s);
    } catch { /* offline: the next one */ }
  };
  const feed = listenChanges((change) => { if (change.model === s.b.model.id) refresh(); });
  const timer = setInterval(() => { if (!feed.live) refresh(); }, POLL * 2);
  live = { stop: () => { clearInterval(timer); feed.stop(); } };
  holdUntilLeft();
}

// -- side by side, on a computer -----------------------------------------------------------
function drawDesk(s) {
  const { at } = s;
  mount(nav({ title: at.screen.label }) + `
    <main class="kit-chess split">
      <section class="cg-games">
        ${heading(at.screen.label, headActions(s))}
        <div class="listing">${listing(s)}</div>
      </section>
      <section class="cg-stage"></section>
    </main>` + tabs(at.tab));
  wireShell();
  wireList(s);
  const stage = app.querySelector(".cg-stage");
  const record = s.games.find((r) => r.id === s.open);
  if (!record) {
    stage.innerHTML = `<p class="empty cg-pick"><b>${s.games.length ? "Pick a game" : "No games yet"}</b>${
      s.b.start && mayWrite(s.b.model) ? "Or start a new one with the button at the top." : ""}</p>`;
    const refresh = async () => {
      try {
        s.games = await api("GET", recordsUrl(s.b.model.id));
        const el = app.querySelector(".cg-games .listing");
        if (el) el.innerHTML = listing(s);
      } catch { /* the next one */ }
    };
    const feed = listenChanges((change) => { if (change.model === s.b.model.id) refresh(); });
    live = { stop: () => feed.stop() };
    holdUntilLeft();
    return;
  }
  openBoard(s, stage, record);
}

function drawPhoneGame(s) {
  const { at } = s;
  const record = s.games.find((r) => r.id === s.open);
  mount(nav({ back: at.base, backLabel: at.screen.label, title: record ? opponentOf(s, record.fields) : at.screen.label }) +
    `<main class="kit-chess phone"><section class="cg-stage"></section></main>` + tabs(at.tab));
  wireShell();
  const stage = app.querySelector(".cg-stage");
  if (!record) {
    stage.innerHTML = `<p class="empty"><b>That game is not here</b>It may have been deleted.</p>`;
    return;
  }
  openBoard(s, stage, record);
}

// -- one game ---------------------------------------------------------------------------------
function openBoard(s, stage, record) {
  const g = {
    s,
    record,
    fields: record.fields,
    game: new Game(shownMoves(record.fields)),
    mine: sideOf(record.fields),
    selected: -1,
    targets: [],
    viewing: null,          // a move number looked back at, or null for now
    pending: false,         // a move sent, its answer not back
    thinking: false,        // the computer is working out its answer
    claimed: false,         // the fallen flag has been told
    animate: null,          // {from, to} for the move to slide in
    drag: null,
    promo: null,
    ended: !!record.fields.result,   // the end has been heard, or was before the game was opened
  };
  g.flipped = g.mine === "b";
  stage.innerHTML = `<div class="cg-room">
    <div class="cg-play">
      <div class="cg-bar top"></div>
      <div class="cg-board" role="grid" aria-label="Chess board"><div class="cg-squares"></div><div class="cg-marks"></div><div class="cg-pieces"></div></div>
      <div class="cg-bar bottom"></div>
    </div>
    <aside class="cg-side">
      <div class="cg-head"><p class="cg-status" role="status"></p><button class="cg-sound" aria-pressed="false"></button></div>
      <div class="cg-moves" aria-label="Moves"></div>
      <div class="cg-steps"></div>
      <div class="cg-buttons"></div>
    </aside></div>`;
  g.root = stage;
  g.board = stage.querySelector(".cg-board");
  wireBoard(g);
  wireSound(g);
  holdBack(g);
  drawAll(g);

  const reload = async () => {
    try {
      const fresh = await api("GET", recordsUrl(s.b.model.id, g.record.id));
      take(g, fresh);
    } catch { /* offline, or gone: the next one */ }
  };
  g.reload = reload;
  const feed = listenChanges((change) => {
    if (change.model !== s.b.model.id) return;
    if (change.id === g.record.id && !g.pending) reload();
    refreshList(s);
  });
  const ticker = setInterval(() => tick(g), TICK);
  const poller = setInterval(() => { if (!feed.live && !g.pending) reload(); }, POLL);
  live = { stop: () => { clearInterval(ticker); clearInterval(poller); clearTimeout(g.held); feed.stop(); closePromo(g); } };
  holdUntilLeft();
}

async function refreshList(s) {
  const el = app.querySelector(".cg-games .listing");
  if (!el) return;
  try {
    s.games = await api("GET", recordsUrl(s.b.model.id));
    el.innerHTML = listing(s);
  } catch { /* the next one */ }
}

/** The computer's move is kept back until the game says it is to be seen
    (`answer_at`): until then it is thinking, its clock running; then the
    move is played on the board, as if it had just been made. */
function holdBack(g) {
  clearTimeout(g.held);
  const held = thinking(g.fields);
  g.thinking = held > 0;
  if (held) g.held = setTimeout(() => take(g, g.record), held + 20);
}

/** A fresher copy of the game from the server: drawn, the newest move slid in and heard. */
function take(g, fresh) {
  const before = g.game.moves.length;
  g.record = fresh;
  g.fields = fresh.fields;
  holdBack(g);
  g.game = new Game(shownMoves(g.fields));
  const after = g.game.moves.length;
  if (after > before && after) {
    const last = g.game.moves[after - 1];
    g.animate = { from: last.from, to: last.to };
    play(kindOf(g.game.sans[after - 1]));
  }
  // The end is heard once, after the move that ended it.
  if (g.fields.result && !g.thinking && !g.ended) { g.ended = true; setTimeout(() => play("end"), 250); }
  if (g.viewing !== null && g.viewing >= after) g.viewing = null;
  if (!g.fields.result) g.claimed = false;
  g.selected = -1;
  g.targets = [];
  drawAll(g);
  const index = g.s.games.findIndex((r) => r.id === fresh.id);
  if (index >= 0) g.s.games[index] = fresh;
}

const turnOf = (g) => g.game.turn;
const isLive = (g) => !g.fields.result;
const myTurn = (g) => isLive(g) && !!g.mine && turnOf(g) === g.mine && !g.pending && !g.thinking && g.viewing === null;
const shownPosition = (g) => g.game.positions[g.viewing === null ? g.game.positions.length - 1 : g.viewing];

function drawAll(g) {
  drawBoard(g);
  drawBars(g);
  drawSide(g);
}

// The display square of a board square, and back: row 0 is the top.
const placeOf = (g, sq) => {
  const file = sq % 8, rank = Math.floor(sq / 8);
  return g.flipped ? { col: 7 - file, row: rank } : { col: file, row: 7 - rank };
};
const squareAtPlace = (g, col, row) => (g.flipped ? row * 8 + (7 - col) : (7 - row) * 8 + col);

function drawBoard(g) {
  const pos = shownPosition(g);
  const index = g.viewing === null ? g.game.moves.length - 1 : g.viewing - 1;
  const last = index >= 0 ? g.game.moves[index] : null;
  const checked = pos.inCheck() ? pos.king(pos.turn) : -1;
  let squares = "";
  for (let row = 0; row < 8; row++) {
    for (let col = 0; col < 8; col++) {
      const sq = squareAtPlace(g, col, row);
      const light = (sq % 8 + Math.floor(sq / 8)) % 2 === 1;
      const cls = ["cg-sq", light ? "light" : "dark"];
      if (last && (sq === last.from || sq === last.to)) cls.push("last");
      if (sq === g.selected) cls.push("selected");
      if (sq === checked) cls.push("check");
      const rankMark = col === 0 ? `<span class="cg-rank">${Math.floor(sq / 8) + 1}</span>` : "";
      const fileMark = row === 7 ? `<span class="cg-file">${"abcdefgh"[sq % 8]}</span>` : "";
      squares += `<div class="${cls.join(" ")}" data-sq="${sq}" role="gridcell" aria-label="${nameOf(sq)}${
        pos.board[sq] ? ", " + pieceName(pos.board[sq]) : ""}">${rankMark}${fileMark}</div>`;
    }
  }
  g.board.querySelector(".cg-squares").innerHTML = squares;
  // Where the chosen piece may go: a dot on an empty square, a ring round a piece to take.
  g.board.querySelector(".cg-marks").innerHTML = g.targets.map((sq) => {
    const { col, row } = placeOf(g, sq);
    const takes = !!pos.board[sq] || (pos.board[g.selected] || "").toLowerCase() === "p" && sq === pos.ep;
    return `<span class="cg-mark ${takes ? "cg-ring" : "cg-dot"}" style="--col:${col};--row:${row}"></span>`;
  }).join("");
  let pieces = "";
  pos.board.forEach((letter, sq) => {
    if (!letter) return;
    const { col, row } = placeOf(g, sq);
    pieces += `<div class="cg-piece" data-sq="${sq}" style="--col:${col};--row:${row}">${piece(letter)}</div>`;
  });
  const layer = g.board.querySelector(".cg-pieces");
  layer.innerHTML = pieces;
  g.board.classList.toggle("movable", myTurn(g));
  // The move just made slides from where it was.
  if (g.animate && g.viewing === null) {
    const { from, to } = g.animate;
    g.animate = null;
    const el = layer.querySelector(`.cg-piece[data-sq="${to}"]`);
    if (el) {
      const start = placeOf(g, from);
      el.classList.add("still");
      el.style.setProperty("--col", start.col);
      el.style.setProperty("--row", start.row);
      el.getBoundingClientRect();
      const end = placeOf(g, to);
      el.classList.remove("still");
      el.style.setProperty("--col", end.col);
      el.style.setProperty("--row", end.row);
    }
  }
}

function avatar(g, side) {
  const f = g.fields;
  const who = side === "w" ? f.white : f.black;
  const computer = f.computer === (side === "w" ? "white" : "black");
  const letter = String(nameIn(g.s, f, side) === "You" ? who : nameIn(g.s, f, side)).trim().charAt(0).toUpperCase() || "?";
  return `<span class="cg-avatar ${side === "w" ? "white" : "black"}${computer ? " computer" : ""}"${
    computer ? "" : ` data-photo="${esc(who)}"`}>${computer ? piece(side === "w" ? "N" : "n") : esc(letter)}</span>`;
}

function barHtml(g, side) {
  const f = g.fields;
  const name = nameIn(g.s, f, side);
  const level = f.computer === (side === "w" ? "white" : "black") && f.level ? `<span class="cg-level">Level ${esc(String(f.level))}</span>` : "";
  const taken = capturedBy(g, side);
  return `${avatar(g, side)}<span class="cg-who"><span class="cg-name">${esc(name)}${level}</span>` +
    `<span class="cg-taken">${taken}</span></span>` +
    (f.clock ? `<span class="cg-clock" data-side="${side}"></span>` : "");
}

/** The pieces this side has taken, small, and what it is ahead by. */
function capturedBy(g, side) {
  const pos = shownPosition(g);
  const count = (letter) => pos.board.filter((p) => p === letter).length;
  const full = { p: 8, n: 2, b: 2, r: 2, q: 1 };
  const worth = { p: 1, n: 3, b: 3, r: 5, q: 9 };
  let out = "", mine = 0, theirs = 0;
  for (const kind of ["q", "r", "b", "n", "p"]) {
    const theirLetter = side === "w" ? kind : kind.toUpperCase();
    const myLetter = side === "w" ? kind.toUpperCase() : kind;
    const gone = Math.max(0, full[kind] - count(theirLetter));
    for (let i = 0; i < gone; i++) out += piece(theirLetter, "cg-small");
    mine += count(myLetter) * worth[kind];
    theirs += count(theirLetter) * worth[kind];
  }
  return out + (mine > theirs ? `<span class="cg-ahead">+${mine - theirs}</span>` : "");
}

function drawBars(g) {
  const bottom = g.flipped ? "b" : "w";
  const top = bottom === "w" ? "b" : "w";
  g.root.querySelector(".cg-bar.top").innerHTML = barHtml(g, top);
  g.root.querySelector(".cg-bar.bottom").innerHTML = barHtml(g, bottom);
  tick(g, true);
}

/** The clocks, drawn again; the flag told when the side to move has none left. */
function tick(g, force = false) {
  const f = g.fields;
  if (!f.clock) return;
  const left = timeLeft(f);
  if (!left) return;
  const running = isLive(g) && f.turn_at ? turnOf(g) : "";
  for (const el of g.root.querySelectorAll(".cg-clock")) {
    const side = el.dataset.side;
    const text = clockText(left[side]);
    if (force || el.textContent !== text) el.textContent = text;
    el.classList.toggle("running", running === side);
    el.classList.toggle("low", left[side] < LOW);
  }
  if (running && left[running] <= 0 && !g.claimed && g.mine && g.s.b.play) {
    g.claimed = true;
    run(g.s.at.quill, g.s.b.play, { record: g.record.id, fields: { move: "time" }, showError: () => {} })
      .then(() => g.reload());
  }
}

function drawSide(g) {
  const f = g.fields;
  const status = g.root.querySelector(".cg-status");
  let said = g.thinking ? "" : standing(g.s, f);
  if (g.thinking || (g.pending && f.computer)) said = `${nameIn(g.s, f, g.mine === "w" ? "b" : "w")} is thinking…`;
  else if (isLive(g) && f.draw && f.draw !== me() && g.mine) said = `${nameIn(g.s, f, g.mine === "w" ? "b" : "w")} offers a draw`;
  else if (isLive(g) && f.draw === me()) said = "You offered a draw";
  status.textContent = said;
  status.className = "cg-status" + (said === "Your move" ? " yours" : "") + (f.result ? " over" : "");

  const moves = g.root.querySelector(".cg-moves");
  const at = g.viewing === null ? g.game.moves.length : g.viewing;
  moves.innerHTML = g.game.numbered().length
    ? `<ol>${g.game.numbered().map(([n, white, black]) =>
      `<li><span class="cg-n">${n}.</span>${moveCell(white, 2 * n - 1, at)}${black ? moveCell(black, 2 * n, at) : "<span></span>"}</li>`).join("")}</ol>`
    : `<p class="cg-none">${g.mine === "w" && isLive(g) ? "White moves first: that is you." : "No moves yet."}</p>`;
  if (g.viewing === null) moves.scrollTop = moves.scrollHeight;
  for (const button of moves.querySelectorAll("[data-ply]")) {
    button.addEventListener("click", () => look(g, Number(button.dataset.ply)));
  }
  const steps = g.root.querySelector(".cg-steps");
  const n = g.game.moves.length;
  steps.innerHTML = n ? [["first", "«", 0], ["back", "‹", Math.max(0, at - 1)], ["on", "›", Math.min(n, at + 1)], ["last", "»", n]]
    .map(([name, glyph, to]) => `<button class="act-button cg-step" data-to="${to}" aria-label="${
      { first: "The start", back: "A move back", on: "A move on", last: "Now" }[name]}"${to === at ? " disabled" : ""}>${glyph}</button>`).join("") : "";
  for (const button of steps.querySelectorAll("[data-to]")) button.addEventListener("click", () => look(g, Number(button.dataset.to)));

  const buttons = g.root.querySelector(".cg-buttons");
  const out = [];
  if (isLive(g) && g.mine && g.s.b.play) {
    if (f.draw && f.draw !== me()) {
      out.push(`<button class="act-button primary" data-word="draw">Accept draw</button>`, `<button class="act-button" data-word="decline">Decline</button>`);
    } else if (f.draw !== me()) {
      out.push(`<button class="act-button" data-word="draw">Offer draw</button>`);
    }
    out.push(`<button class="act-button danger" data-word="resign">Resign</button>`);
  }
  if (!isLive(g) && g.s.b.start && mayWrite(g.s.b.model)) {
    if (g.mine) out.push(`<button class="act-button primary" data-again>Rematch</button>`);
    out.push(`<button class="act-button" data-new>New game</button>`);
  }
  buttons.innerHTML = out.join("");
  for (const button of buttons.querySelectorAll("[data-word]")) button.addEventListener("click", () => word(g, button.dataset.word, button));
  const again = buttons.querySelector("[data-again]");
  if (again) again.addEventListener("click", () => rematch(g, again));
  const fresh = buttons.querySelector("[data-new]");
  if (fresh) fresh.addEventListener("click", () => newGame(g.s));
}

const SPEAKER = {
  on: '<svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7.5h3l4-3.5v12l-4-3.5H3z"/><path d="M13.5 7a4 4 0 0 1 0 6M15.8 4.8a7 7 0 0 1 0 10.4"/></svg>',
  off: '<svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7.5h3l4-3.5v12l-4-3.5H3z"/><path d="m13.5 7.5 5 5M18.5 7.5l-5 5"/></svg>',
};

function wireSound(g) {
  const button = g.root.querySelector(".cg-sound");
  const show = () => {
    const on = soundOn();
    button.innerHTML = on ? SPEAKER.on : SPEAKER.off;
    button.setAttribute("aria-pressed", String(on));
    button.setAttribute("aria-label", on ? "Sound on" : "Sound off");
    button.title = on ? "Sound on" : "Sound off";
  };
  button.addEventListener("click", () => { setSound(!soundOn()); show(); if (soundOn()) play("move"); });
  show();
}

const moveCell = (san, ply, at) =>
  `<button class="cg-move${ply === at ? " now" : ""}" data-ply="${ply}">${esc(san)}</button>`;

function look(g, ply) {
  g.viewing = ply >= g.game.moves.length ? null : ply;
  g.selected = -1;
  g.targets = [];
  drawAll(g);
}

async function word(g, said, button) {
  if (said === "resign" && !(await ask("Resign this game?", { yes: "Resign", tone: "danger" }))) return;
  button.disabled = true;
  await run(g.s.at.quill, g.s.b.play, { record: g.record.id, fields: { move: said } });
  await g.reload();
}

// -- moving ---------------------------------------------------------------------------------
function squareFromPoint(g, x, y) {
  const box = g.board.getBoundingClientRect();
  const col = Math.floor(((x - box.left) / box.width) * 8);
  const row = Math.floor(((y - box.top) / box.height) * 8);
  if (col < 0 || col > 7 || row < 0 || row > 7) return -1;
  return squareAtPlace(g, col, row);
}

function choose(g, sq) {
  const pos = g.game.position;
  g.selected = sq;
  g.targets = [...new Set(pos.legal().filter((m) => m.from === sq).map((m) => m.to))];
  drawBoard(g);
}

function unchoose(g) {
  if (g.selected < 0) return;
  g.selected = -1;
  g.targets = [];
  drawBoard(g);
}

const own = (g, sq) => {
  const p = g.game.position.board[sq];
  return !!p && (p === p.toUpperCase() ? "w" : "b") === g.mine;
};

// The board listens, not the pieces: they are drawn again, the board stays.
function wireBoard(g) {
  const board = g.board;
  board.addEventListener("pointerdown", (event) => {
    wake();
    if (event.button !== 0 || g.promo) return;
    const sq = squareFromPoint(g, event.clientX, event.clientY);
    if (sq < 0) return;
    if (!myTurn(g)) {
      if (g.viewing !== null) look(g, g.game.moves.length);
      return;
    }
    if (g.selected >= 0 && g.targets.includes(sq)) {
      event.preventDefault();
      tryMove(g, g.selected, sq, true);
      return;
    }
    if (!own(g, sq)) { unchoose(g); return; }
    event.preventDefault();
    const again = g.selected === sq;
    choose(g, sq);
    const el = board.querySelector(`.cg-piece[data-sq="${sq}"]`);
    const box = el ? el.getBoundingClientRect() : null;
    // Where the pointer is on the piece: the piece's middle goes under the pointer as it is dragged.
    const middle = box ? { x: box.left + box.width / 2, y: box.top + box.height / 2 } : { x: event.clientX, y: event.clientY };
    g.drag = { from: sq, el, x: event.clientX, y: event.clientY, middle, moved: false, again, id: event.pointerId };
    board.setPointerCapture(event.pointerId);
  });
  board.addEventListener("pointermove", (event) => {
    const d = g.drag;
    if (!d || d.id !== event.pointerId) return;
    if (!d.moved && Math.hypot(event.clientX - d.x, event.clientY - d.y) < 4) return;
    d.moved = true;
    if (d.el) {
      d.el.classList.add("dragging");
      d.el.style.transform = `translate(${event.clientX - d.middle.x}px, ${event.clientY - d.middle.y}px)`;
    }
    const over = squareFromPoint(g, event.clientX, event.clientY);
    for (const el of board.querySelectorAll(".cg-sq.over")) el.classList.remove("over");
    if (g.targets.includes(over)) {
      const el = board.querySelector(`.cg-sq[data-sq="${over}"]`);
      if (el) el.classList.add("over");
    }
  });
  const end = (event) => {
    const d = g.drag;
    if (!d || d.id !== event.pointerId) return;
    g.drag = null;
    if (board.hasPointerCapture(event.pointerId)) board.releasePointerCapture(event.pointerId);
    for (const el of board.querySelectorAll(".cg-sq.over")) el.classList.remove("over");
    // Put down where it was picked up: straight back, without sliding there.
    if (d.el) {
      d.el.classList.add("still");
      d.el.classList.remove("dragging");
      d.el.style.transform = "";
      d.el.getBoundingClientRect();
      d.el.classList.remove("still");
    }
    if (!d.moved) {
      // A second press on the chosen piece lets it go.
      if (d.again && event.type === "pointerup") unchoose(g);
      return;
    }
    const to = squareFromPoint(g, event.clientX, event.clientY);
    if (event.type === "pointerup" && g.targets.includes(to)) tryMove(g, d.from, to, false);
  };
  board.addEventListener("pointerup", end);
  board.addEventListener("pointercancel", end);
}

function tryMove(g, from, to, slide) {
  const pos = g.game.position;
  const options = pos.legal().filter((m) => m.from === from && m.to === to);
  if (!options.length) return;
  if (options.length > 1 || options[0].promote) {
    askPromotion(g, from, to, slide);
    return;
  }
  send(g, options[0], slide);
}

function askPromotion(g, from, to, slide) {
  closePromo(g);
  const { col, row } = placeOf(g, to);
  const colour = g.mine;
  const down = row === 0;   // the picker hangs from the edge the pawn reached
  const el = document.createElement("div");
  el.className = "cg-promo" + (down ? " down" : " up");
  el.style.setProperty("--col", col);
  el.innerHTML = PROMOTIONS.split("").map((p) => {
    const letter = colour === "w" ? p.toUpperCase() : p;
    return `<button data-piece="${p}" aria-label="${pieceName(letter)}">${piece(letter)}</button>`;
  }).join("") + `<button class="cg-promo-x" aria-label="Not this move"><svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m2.5 2.5 7 7M9.5 2.5l-7 7"/></svg></button>`;
  g.board.appendChild(el);
  g.promo = el;
  el.addEventListener("pointerdown", (event) => event.stopPropagation());
  el.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    closePromo(g);
    if (!button.dataset.piece) { unchoose(g); return; }
    send(g, { from, to, promote: button.dataset.piece }, slide);
  });
}

function closePromo(g) {
  if (g.promo) { g.promo.remove(); g.promo = null; }
}

/** Play it here at once, then have the Quill keep it; a refusal takes it back. */
async function send(g, move, slide) {
  const played = g.game.play(move);
  if (!played) return;
  play(kindOf(g.game.sans[g.game.sans.length - 1]));
  g.selected = -1;
  g.targets = [];
  g.pending = true;
  g.animate = slide ? { from: move.from, to: move.to } : null;
  const ended = g.game.outcome();
  if (g.fields.computer && !ended) g.thinking = true;
  // The clock this side used stops here; the other one's starts, as the Quill will keep it.
  const f = { ...g.fields, moves: g.game.moves.map(uciOf), draw: "" };
  if (f.clock && f.turn_at) {
    const left = timeLeft(g.fields);
    f[g.mine === "w" ? "white_left" : "black_left"] = left[g.mine];
  }
  if (f.clock && g.game.moves.length >= 2 && !ended) f.turn_at = new Date().toISOString();
  g.fields = f;
  drawAll(g);
  const failed = await run(g.s.at.quill, g.s.b.play, { record: g.record.id, fields: { move: uciOf(played) } });
  g.pending = false;
  if (failed) g.thinking = false;
  await g.reload();
  refreshList(g.s);
}

// -- a new game -------------------------------------------------------------------------------
const fieldIn = (action, name) => (action.fields || []).find((f) => f.name === name) || null;
const choicesOf = (field) => (field && field.values ? field.values.map((v, i) => [v, (field.labels && field.labels[i]) || v]) : []);

async function newGame(s, given = {}) {
  const start = s.b.start;
  if (!start) return;
  const [people, computers] = await Promise.all([
    peopleList(),
    s.b.computers ? api("GET", recordsUrl(s.b.computers.id)).catch(() => []) : Promise.resolve([]),
  ]);
  const clock = fieldIn(start, "clock");
  const colour = fieldIn(start, "colour");
  const chosen = {
    opponent: given.opponent || (computers[0] ? computers[0].id : people[0] ? people[0].username : ""),
    clock: given.clock ?? (clock ? String(clock.default ?? choicesOf(clock)[0][0]) : ""),
    colour: given.colour || (colour ? String(colour.default ?? choicesOf(colour)[0][0]) : ""),
  };
  const opponentRow = (value, name, line, mark) =>
    `<button type="button" class="cg-opponent${value === chosen.opponent ? " active" : ""}" data-opponent="${esc(value)}" role="radio" aria-checked="${value === chosen.opponent}">` +
    `${mark}<span class="cg-who"><span class="cg-name">${esc(name)}</span><span class="cg-line">${esc(line)}</span></span></button>`;
  const rows = computers.map((c) => opponentRow(c.id, String(c.fields.name || "Computer"),
    c.fields.level ? `Level ${c.fields.level}${c.fields.won ? ` · you have beaten him ${c.fields.won} ${c.fields.won === 1 ? "time" : "times"}` : ""}` : "The computer",
    `<span class="cg-avatar computer">${piece("N", "cg-art")}</span>`))
    .concat(people.map((p) => opponentRow(p.username, p.display_name || p.username, `@${p.username}`,
      `<span class="cg-avatar" data-photo="${esc(p.username)}">${esc((p.display_name || p.username).charAt(0).toUpperCase())}</span>`)));
  const seg = (field, value) => field
    ? `<p class="group-label">${esc(field.label || field.name)}</p><div class="segments" role="radiogroup" data-choice="${esc(field.name)}">` +
      choicesOf(field).map(([v, text]) => `<button type="button" role="radio" data-value="${esc(v)}"${String(v) === String(value) ? ' class="active" aria-checked="true"' : ' aria-checked="false"'}>${esc(text)}</button>`).join("") + `</div>`
    : "";
  const { sheet, close } = openSheet(
    `<form class="act-form cg-new-sheet" novalidate>` +
    `<p class="act-sheet-title">${esc(start.label || "New game")}</p>` +
    `<p class="group-label">${esc(fieldIn(start, "opponent").label || "Against")}</p>` +
    `<div class="cg-opponents" role="radiogroup">${rows.join("") || `<p class="cg-none">There is nobody else here to play yet.</p>`}</div>` +
    seg(clock, chosen.clock) + seg(colour, chosen.colour) +
    `<p class="act-error" role="alert" hidden></p>` +
    `<div class="act-buttons"><button type="button" class="act-button" data-cancel>Cancel</button>` +
    `<button type="submit" class="act-button primary">Play</button></div></form>`, "act-form-sheet cg-sheet");
  const form = sheet.querySelector("form");
  form.querySelector("[data-cancel]").addEventListener("click", close);
  for (const button of form.querySelectorAll("[data-opponent]")) {
    button.addEventListener("click", () => {
      chosen.opponent = button.dataset.opponent;
      for (const b of form.querySelectorAll("[data-opponent]")) {
        b.classList.toggle("active", b === button);
        b.setAttribute("aria-checked", String(b === button));
      }
    });
  }
  for (const group of form.querySelectorAll("[data-choice]")) {
    for (const button of group.querySelectorAll("button")) {
      button.addEventListener("click", () => {
        chosen[group.dataset.choice] = button.dataset.value;
        for (const b of group.querySelectorAll("button")) {
          b.classList.toggle("active", b === button);
          b.setAttribute("aria-checked", String(b === button));
        }
      });
    }
  }
  const errorEl = form.querySelector(".act-error");
  const showError = (text) => { errorEl.textContent = text; errorEl.hidden = !text; };
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!chosen.opponent) { showError("Pick whom to play"); return; }
    const button = form.querySelector("[type=submit]");
    button.disabled = true;
    button.textContent = start.busy || "Starting";
    const fields = { opponent: chosen.opponent };
    if (clock) fields.clock = chosen.clock;
    if (colour) fields.colour = chosen.colour;
    const failed = await run(s.at.quill, start, { fields, showError });
    if (failed) { button.disabled = false; button.textContent = "Play"; return; }
    close();
  });
}

/** The same two again, the same clock: the colours the other way round, or as the Quill decides. */
function rematch(g, button) {
  const f = g.fields;
  const theirSide = g.mine === "w" ? "black" : "white";
  let opponent = g.mine === "w" ? f.black : f.white;
  const fields = { colour: g.mine === "w" ? "black" : "white" };
  if (!fieldIn(g.s.b.start, "colour")) delete fields.colour;
  if (fieldIn(g.s.b.start, "clock")) fields.clock = String(f.clock || 0);
  button.disabled = true;
  const go = async () => {
    if (f.computer === theirSide && g.s.b.computers) {
      const computers = await api("GET", recordsUrl(g.s.b.computers.id)).catch(() => []);
      const found = computers.find((c) => c.fields.name === opponent) || computers[0];
      if (found) opponent = found.id;
    }
    const failed = await run(g.s.at.quill, g.s.b.start, { fields: { ...fields, opponent } });
    if (failed) button.disabled = false;
  };
  go();
}


