/* The chess kit's pieces: flat, seen from the front, drawn on a 45 × 45
   square — white ones light with a dark line round them, black ones dark
   with their details picked out in light. Cloudmorrow's own drawings.

   `sprite()` is one hidden <svg> of <symbol>s, put on the page once;
   `piece(letter)` is a piece that uses it, and `thumb(board)` a board
   small enough for a list row. */

const LINE = "#2b2b2b";
const COLOURS = {
  w: { fill: "#fafaf5", stroke: LINE, detail: LINE },
  b: { fill: "#3a3a3a", stroke: LINE, detail: "#ecece4" },
};

// Each piece: the shapes filled (body), and the lines drawn over them (detail).
const SHAPES = {
  p: {
    body: [
      '<circle cx="22.5" cy="12.5" r="5.2"/>',
      '<path d="M16.5 33.5c.6-6.2 3.2-9.8 4.4-13.2h3.2c1.2 3.4 3.8 7 4.4 13.2z"/>',
      '<ellipse cx="22.5" cy="20.3" rx="5.4" ry="1.9"/>',
      '<rect x="12.5" y="33.5" width="20" height="5" rx="2.5"/>',
    ],
    detail: [],
  },
  r: {
    body: [
      '<path d="M15 33.5 16.2 18h12.6L30 33.5z"/>',
      '<path d="M13 18V9.5h4v3.2h3.4V9.5h4.2v3.2H28V9.5h4V18z"/>',
      '<rect x="10.5" y="33.5" width="24" height="5" rx="2"/>',
    ],
    detail: ['<path d="M16 21h13M15.4 30h14.2" fill="none"/>'],
  },
  n: {
    body: [
      '<path d="M15.5 33.5c-.3-5 2.2-8.4 5.6-10.6-2.8.2-5 .9-7.2 2.2-1.7 1-3.6-.4-3.1-2.3.7-2.8 2.6-5.2 5-7.8.8-2.2 2-4.2 3.6-5.7l.5-3.3 2.6 2.4c6.4 1 10.9 6 11.3 13.6.3 4.8-.4 8.6-1.5 11.5z"/>',
      '<rect x="11.5" y="33.5" width="22" height="5" rx="2.5"/>',
    ],
    detail: [
      '<circle cx="19" cy="13.2" r="1.15" stroke="none" fill="currentColor"/>',
      '<path d="M23.8 9.8c4 2.2 6.3 6.6 6.3 13.4" fill="none"/>',
      '<path d="M12.6 22.4l1.4-.4" fill="none"/>',
    ],
  },
  b: {
    body: [
      '<circle cx="22.5" cy="5.6" r="2.1"/>',
      '<path d="M22.5 7.6c-5 3.9-6.9 8.4-6 11.6.6 2.2 2.8 3.4 6 3.4s5.4-1.2 6-3.4c.9-3.2-1-7.7-6-11.6z"/>',
      '<path d="M16.5 33.5c.5-4.6 2.4-7.6 3.4-9.6h5.2c1 2 2.9 5 3.4 9.6z"/>',
      '<ellipse cx="22.5" cy="23.4" rx="6" ry="2"/>',
      '<rect x="11.5" y="33.5" width="22" height="5" rx="2.5"/>',
    ],
    detail: ['<path d="M24.6 11.4 21 16.6" fill="none"/>'],
  },
  q: {
    body: [
      '<path d="M13.4 33.5 10.6 16.4l6.4 8.2-.4-11.4 5.9 10.6 5.9-10.6-.4 11.4 6.4-8.2-2.8 17.1z"/>',
      '<circle cx="10.3" cy="14.4" r="2.2"/><circle cx="16.5" cy="11.2" r="2.2"/><circle cx="22.5" cy="9.6" r="2.2"/>',
      '<circle cx="28.5" cy="11.2" r="2.2"/><circle cx="34.7" cy="14.4" r="2.2"/>',
      '<rect x="10.5" y="33.5" width="24" height="5" rx="2.5"/>',
    ],
    detail: ['<path d="M14.2 29.8h16.6" fill="none"/>'],
  },
  k: {
    body: [
      '<path d="M13.6 33.5c-1.8-6.4-4.2-10.6-1.6-14 2.6-3.2 7.6-1.4 10.5 4.2 2.9-5.6 7.9-7.4 10.5-4.2 2.6 3.4.2 7.6-1.6 14z"/>',
      '<path d="M19.6 23.3c0-4.6 1.2-7.4 2.9-8.6 1.7 1.2 2.9 4 2.9 8.6z"/>',
      '<rect x="10.5" y="33.5" width="24" height="5" rx="2.5"/>',
    ],
    detail: ['<path d="M14.2 29.8h16.6" fill="none"/>'],
    cross: '<path d="M22.5 3.6v9.2M18.6 7.4h7.8" fill="none" stroke-width="2.4" stroke-linecap="round"/>',
  },
};

function symbol(side, kind) {
  const c = COLOURS[side];
  const shape = SHAPES[kind];
  const cross = shape.cross ? `<g stroke="${c.stroke}">${shape.cross}</g>` : "";
  const details = shape.detail.length
    ? `<g stroke="${c.detail}" color="${c.detail}" stroke-width="1.4" stroke-linecap="round">${shape.detail.join("")}</g>` : "";
  return `<symbol id="cp-${side}${kind}" viewBox="3 1.5 39 39">` +
    `<g fill="${c.fill}" stroke="${c.stroke}" stroke-width="1.6" stroke-linejoin="round">${shape.body.join("")}</g>` +
    `${details}${cross}</symbol>`;
}

/** Every piece as a symbol, in one hidden svg: put on the page once. */
export function sprite() {
  if (document.getElementById("cp-sprite")) return;
  const holder = document.createElement("div");
  holder.innerHTML = `<svg id="cp-sprite" width="0" height="0" style="position:absolute" aria-hidden="true"><defs>` +
    ["w", "b"].flatMap((side) => Object.keys(SHAPES).map((kind) => symbol(side, kind))).join("") + `</defs></svg>`;
  document.body.appendChild(holder.firstElementChild);
}

export const pieceId = (letter) => `cp-${letter === letter.toUpperCase() ? "w" : "b"}${letter.toLowerCase()}`;

/** A piece, drawn from the sprite. */
export const piece = (letter, cls = "cg-art") =>
  `<svg class="${cls}" viewBox="0 0 1 1" aria-hidden="true"><use href="#${pieceId(letter)}" width="1" height="1"/></svg>`;

const NAMES = { p: "pawn", n: "knight", b: "bishop", r: "rook", q: "queen", k: "king" };
export const pieceName = (letter) => `${letter === letter.toUpperCase() ? "white" : "black"} ${NAMES[letter.toLowerCase()]}`;

/** A board for a list row: 8 × 8, white at the bottom unless *flipped*. */
export function thumb(board, flipped = false) {
  let squares = "", pieces = "";
  for (let row = 0; row < 8; row++) {
    for (let col = 0; col < 8; col++) {
      const sq = flipped ? row * 8 + (7 - col) : (7 - row) * 8 + col;
      const light = (sq % 8 + Math.floor(sq / 8)) % 2 === 1;
      if (!light) squares += `<rect x="${col}" y="${row}" width="1" height="1"/>`;
      if (board[sq]) pieces += `<use href="#${pieceId(board[sq])}" x="${col}" y="${row}" width="1" height="1"/>`;
    }
  }
  return `<svg class="cg-thumb" viewBox="0 0 8 8" aria-hidden="true"><rect class="cg-thumb-light" width="8" height="8"/>` +
    `<g class="cg-thumb-dark">${squares}</g>${pieces}</svg>`;
}
