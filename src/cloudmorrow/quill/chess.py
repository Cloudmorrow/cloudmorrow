"""The rules of chess, for the kit's `chess` screens and the Quills that draw them.

A game is kept as the moves played, each as the long algebraic a program
reads (`e2e4`, `e7e8q`, `e1g1` for castling short), from the usual start.
Everything else — the position, whose move it is, what may be played, the
moves as people write them (`Nf3`, `exd5`, `O-O`, `e8=Q#`), how it ended —
is worked out from them here, and the same in the browser
(web/kit_chess_rules.js). A Quill's code imports this to check a move
before it keeps it: `from cloudmorrow.quill.chess import Game`.

    game = Game(["e2e4", "e7e5"])
    game.legal()                 # every move there is, as Move
    move = game.parse("Nf3")     # or "g1f3"; ValueError when it is no move here
    game.play(move)
    game.sans                    # ["e4", "e5", "Nf3"]
    game.outcome()               # None, or Outcome("1-0", "checkmate")

The board is 64 squares, a1 = 0, h1 = 7, a8 = 56; a piece is a letter,
white's in capitals (`PNBRQK`), black's small; an empty square is "".

The clock (`time_left`) is the kit's own sums over a game's fields
(docs/CHESS.md): what each side has left, as of the last move, and since
when the side to move has been thinking.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import NamedTuple

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
FILES = "abcdefgh"
PROMOTIONS = "qrbn"

# What a game ends in, and why (docs/CHESS.md): the kit says these.
WHITE_WINS, BLACK_WINS, DRAWN = "1-0", "0-1", "1/2-1/2"
REASONS = (
    "checkmate",
    "resigned",
    "time",
    "stalemate",
    "agreed",
    "repetition",
    "fifty moves",
    "material",
    "aborted",
)


def square(name: str) -> int:
    """`e4` → 28."""
    if len(name) != 2 or name[0] not in FILES or name[1] not in "12345678":
        raise ValueError(f"{name!r} is no square")
    return FILES.index(name[0]) + 8 * (int(name[1]) - 1)


def name_of(sq: int) -> str:
    """28 → `e4`."""
    return FILES[sq % 8] + str(sq // 8 + 1)


def white(piece: str) -> bool:
    return piece.isupper()


def colour_of(piece: str) -> str:
    return "w" if piece.isupper() else "b"


# -- where pieces reach, worked out once ----------------------------------------------
def _steps(deltas) -> list[list[int]]:
    out = []
    for sq in range(64):
        f, r = sq % 8, sq // 8
        out.append([(r + dr) * 8 + f + df for df, dr in deltas if 0 <= f + df < 8 and 0 <= r + dr < 8])
    return out


def _rays(df: int, dr: int) -> list[list[int]]:
    out = []
    for sq in range(64):
        f, r, ray = sq % 8 + df, sq // 8 + dr, []
        while 0 <= f < 8 and 0 <= r < 8:
            ray.append(r * 8 + f)
            f, r = f + df, r + dr
        out.append(ray)
    return out


KNIGHT = _steps(((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2)))
KING = _steps(((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)))
STRAIGHT = [_rays(1, 0), _rays(-1, 0), _rays(0, 1), _rays(0, -1)]
DIAGONAL = [_rays(1, 1), _rays(-1, 1), _rays(1, -1), _rays(-1, -1)]
# The squares a pawn of each colour on a square takes on.
PAWN_TAKES = {"w": _steps(((-1, 1), (1, 1))), "b": _steps(((-1, -1), (1, -1)))}
# What a castling right needs: the king's and rook's squares, where they go, what must be empty, what must be safe.
CASTLING = {
    "K": (4, 7, 6, 5, (5, 6), (4, 5, 6)),
    "Q": (4, 0, 2, 3, (1, 2, 3), (4, 3, 2)),
    "k": (60, 63, 62, 61, (61, 62), (60, 61, 62)),
    "q": (60, 56, 58, 59, (57, 58, 59), (60, 59, 58)),
}
# A right goes when anything leaves or arrives on one of these squares.
LOSES = {0: "Q", 4: "KQ", 7: "K", 56: "q", 60: "kq", 63: "k"}


class Move(NamedTuple):
    """From one square to another; `promote` is the piece a pawn becomes, small (`q`), or ""."""

    frm: int
    to: int
    promote: str = ""

    @property
    def uci(self) -> str:
        return name_of(self.frm) + name_of(self.to) + self.promote

    @classmethod
    def from_uci(cls, text: str) -> Move:
        text = text.strip().lower()
        if len(text) not in (4, 5) or (len(text) == 5 and text[4] not in PROMOTIONS):
            raise ValueError(f"{text!r} is no move")
        return cls(square(text[:2]), square(text[2:4]), text[4:])


class Outcome(NamedTuple):
    result: str  # 1-0, 0-1 or 1/2-1/2
    reason: str  # one of REASONS


# -- a position ---------------------------------------------------------------------
@dataclass(slots=True)
class Position:
    board: list[str]
    turn: str = "w"
    castling: str = "KQkq"
    ep: int = -1  # the square a pawn may be taken on in passing, or -1
    halfmove: int = 0  # since the last capture or pawn move
    fullmove: int = 1

    @classmethod
    def start(cls) -> Position:
        return cls.from_fen(START)

    @classmethod
    def from_fen(cls, fen: str) -> Position:
        parts = fen.split()
        if len(parts) < 4:
            raise ValueError(f"{fen!r} is no position")
        board = [""] * 64
        rows = parts[0].split("/")
        if len(rows) != 8:
            raise ValueError(f"{fen!r} is no position")
        for i, row in enumerate(rows):
            f = 0
            for ch in row:
                if ch.isdigit():
                    f += int(ch)
                elif ch.lower() in "pnbrqk" and f < 8:
                    board[(7 - i) * 8 + f] = ch
                    f += 1
                else:
                    raise ValueError(f"{fen!r} is no position")
        return cls(
            board,
            "b" if parts[1] == "b" else "w",
            "" if parts[2] == "-" else parts[2],
            -1 if parts[3] == "-" else square(parts[3]),
            int(parts[4]) if len(parts) > 4 else 0,
            int(parts[5]) if len(parts) > 5 else 1,
        )

    def fen(self) -> str:
        rows = []
        for r in range(7, -1, -1):
            row, empty = "", 0
            for f in range(8):
                piece = self.board[r * 8 + f]
                if piece:
                    row += (str(empty) if empty else "") + piece
                    empty = 0
                else:
                    empty += 1
            rows.append(row + (str(empty) if empty else ""))
        ep = name_of(self.ep) if self.ep >= 0 else "-"
        return f"{'/'.join(rows)} {self.turn} {self.castling or '-'} {ep} {self.halfmove} {self.fullmove}"

    def key(self) -> str:
        """What makes two positions the same one, for repetition: the board, the move, the rights."""
        return " ".join(self.fen().split()[:4])

    def copy(self) -> Position:
        return Position(self.board[:], self.turn, self.castling, self.ep, self.halfmove, self.fullmove)

    # -- seeing ---------------------------------------------------------------------
    def king(self, side: str) -> int:
        want = "K" if side == "w" else "k"
        try:
            return self.board.index(want)
        except ValueError:
            return -1

    def attacked(self, sq: int, by: str) -> bool:
        """Whether a piece of side *by* attacks the square."""
        b = self.board
        pawn, knight, king, rook, bishop, queen = "PNKRBQ" if by == "w" else "pnkrbq"
        other = "b" if by == "w" else "w"
        for s in PAWN_TAKES[other][sq]:
            if b[s] == pawn:
                return True
        for s in KNIGHT[sq]:
            if b[s] == knight:
                return True
        for s in KING[sq]:
            if b[s] == king:
                return True
        for rays in STRAIGHT:
            for s in rays[sq]:
                p = b[s]
                if p:
                    if p == rook or p == queen:
                        return True
                    break
        for rays in DIAGONAL:
            for s in rays[sq]:
                p = b[s]
                if p:
                    if p == bishop or p == queen:
                        return True
                    break
        return False

    def in_check(self, side: str | None = None) -> bool:
        side = side or self.turn
        k = self.king(side)
        return k >= 0 and self.attacked(k, "b" if side == "w" else "w")

    # -- moving -----------------------------------------------------------------------
    def pseudo(self) -> list[Move]:
        """Every move the pieces make, before asking whether it leaves the king in check."""
        b, side, out = self.board, self.turn, []
        mine = str.isupper if side == "w" else str.islower
        for sq in range(64):
            p = b[sq]
            if not p or not mine(p):
                continue
            kind = p.lower()
            if kind == "p":
                self._pawn(sq, out)
            elif kind == "n":
                out.extend(Move(sq, t) for t in KNIGHT[sq] if not b[t] or not mine(b[t]))
            elif kind == "k":
                out.extend(Move(sq, t) for t in KING[sq] if not b[t] or not mine(b[t]))
            else:
                rays = STRAIGHT if kind == "r" else DIAGONAL if kind == "b" else STRAIGHT + DIAGONAL
                for ray in rays:
                    for t in ray[sq]:
                        q = b[t]
                        if not q:
                            out.append(Move(sq, t))
                            continue
                        if not mine(q):
                            out.append(Move(sq, t))
                        break
        self._castles(out)
        return out

    def _pawn(self, sq: int, out: list[Move]) -> None:
        b = self.board
        if self.turn == "w":
            step, home, last, theirs = 8, 1, 7, str.islower
        else:
            step, home, last, theirs = -8, 6, 0, str.isupper

        def add(to: int) -> None:
            if to // 8 == last:
                out.extend(Move(sq, to, p) for p in PROMOTIONS)
            else:
                out.append(Move(sq, to))

        one = sq + step
        if 0 <= one < 64 and not b[one]:
            add(one)
            two = one + step
            if sq // 8 == home and not b[two]:
                out.append(Move(sq, two))
        for t in PAWN_TAKES[self.turn][sq]:
            if (b[t] and theirs(b[t])) or t == self.ep:
                add(t)

    def _castles(self, out: list[Move]) -> None:
        side, b = self.turn, self.board
        enemy = "b" if side == "w" else "w"
        for right in self.castling:
            if (right.isupper()) != (side == "w"):
                continue
            k, r, kto, _rto, empty, safe = CASTLING[right]
            king, rook = ("K", "R") if side == "w" else ("k", "r")
            if b[k] != king or b[r] != rook or any(b[s] for s in empty):
                continue
            if any(self.attacked(s, enemy) for s in safe):
                continue
            out.append(Move(k, kto))

    def apply(self, move: Move) -> Position:
        """The position after *move*, which the caller knows to be one of `pseudo()`'s."""
        b = self.board[:]
        frm, to, promote = move
        piece = b[frm]
        kind = piece.lower()
        captured = b[to]
        b[frm] = ""
        ep = -1
        if kind == "p":
            if to == self.ep:  # in passing: the pawn taken is beside, not on, the square
                b[to - 8 if piece == "P" else to + 8] = ""
                captured = "p"
            if abs(to - frm) == 16:
                mid = (frm + to) // 2
                theirs = "p" if piece == "P" else "P"
                if any(b[s] == theirs for s in PAWN_TAKES[colour_of(piece)][mid]):
                    ep = mid
            if promote:
                piece = promote.upper() if piece == "P" else promote
        elif kind == "k" and abs(to - frm) == 2:
            for k, r, kto, rto, _e, _s in CASTLING.values():
                if k == frm and kto == to:
                    b[rto], b[r] = b[r], ""
        b[to] = piece
        castling = self.castling
        for sq in (frm, to):
            for gone in LOSES.get(sq, ""):
                castling = castling.replace(gone, "")
        return Position(
            b,
            "b" if self.turn == "w" else "w",
            castling,
            ep,
            0 if kind == "p" or captured else self.halfmove + 1,
            self.fullmove + (1 if self.turn == "b" else 0),
        )

    def legal(self) -> list[Move]:
        side = self.turn
        out = []
        for move in self.pseudo():
            after = self.apply(move)
            if not after.in_check(side):
                out.append(move)
        return out

    def push(self, move: Move | str) -> Position:
        """The position after a legal move; ValueError for anything else."""
        if isinstance(move, str):
            move = self.parse(move)
        if move not in self.legal():
            raise ValueError(f"{move.uci} is no move here")
        return self.apply(move)

    # -- writing moves as people do -----------------------------------------------------
    def san(self, move: Move, legal: list[Move] | None = None) -> str:
        """The move as a person writes it: `Nf3`, `exd5`, `O-O`, `e8=Q+`, `Qh7#`."""
        legal = self.legal() if legal is None else legal
        piece = self.board[move.frm]
        kind = piece.lower()
        if kind == "k" and abs(move.to - move.frm) == 2:
            text = "O-O" if move.to > move.frm else "O-O-O"
        else:
            takes = bool(self.board[move.to]) or (kind == "p" and move.to == self.ep)
            if kind == "p":
                text = (FILES[move.frm % 8] + "x" if takes else "") + name_of(move.to)
                if move.promote:
                    text += "=" + move.promote.upper()
            else:
                text = kind.upper()
                rivals = [m for m in legal if m.to == move.to and m.frm != move.frm and self.board[m.frm] == piece]
                if rivals:
                    same_file = any(m.frm % 8 == move.frm % 8 for m in rivals)
                    same_rank = any(m.frm // 8 == move.frm // 8 for m in rivals)
                    if not same_file:
                        text += FILES[move.frm % 8]
                    elif not same_rank:
                        text += str(move.frm // 8 + 1)
                    else:
                        text += name_of(move.frm)
                text += ("x" if takes else "") + name_of(move.to)
        after = self.apply(move)
        if after.in_check():
            text += "#" if not after.legal() else "+"
        return text

    def parse(self, text: str) -> Move:
        """A move as typed — `Nf3`, `g1f3`, `O-O`, `0-0`, `exd5`, `e8=Q`, `e7e8q` — or ValueError."""
        said = text.strip().rstrip("+#!?").replace("0", "O")
        if not said:
            raise ValueError("no move")
        legal = self.legal()
        low = said.lower().replace("=", "")
        if len(low) in (4, 5) and low[0] in FILES and low[1] in "12345678" and low[2] in FILES and low[3] in "12345678":
            move = Move.from_uci(low)
            if move in legal:
                return move
            # A promotion typed without the piece is a queen.
            if not move.promote and Move(move.frm, move.to, "q") in legal:
                return Move(move.frm, move.to, "q")
            raise ValueError(f"{text.strip()} is no move here")
        if said.upper() in ("O-O", "O-O-O"):
            for move in legal:
                if self.board[move.frm].lower() == "k" and abs(move.to - move.frm) == 2:
                    if (move.to > move.frm) == (said.upper() == "O-O"):
                        return move
            raise ValueError(f"{text.strip()} is no move here")
        bare = said.replace("x", "").replace("=", "").replace("-", "")
        found = [m for m in legal if self.san(m, legal).rstrip("+#").replace("x", "").replace("=", "") == bare]
        if not found and bare[:1] in "nrqk":  # a piece typed small: nf3
            bare = bare[0].upper() + bare[1:]
            found = [m for m in legal if self.san(m, legal).rstrip("+#").replace("x", "").replace("=", "") == bare]
        if len(found) == 1:
            return found[0]
        if not found and bare and bare[0] in FILES and bare[-1] in "12345678":
            # A pawn reaching the last rank with nothing said becomes a queen.
            queened = [m for m in legal if m.promote == "q" and self.board[m.frm].lower() == "p"]
            queened = [m for m in queened if self.san(m, legal).rstrip("+#").replace("x", "").startswith(bare)]
            if len(queened) == 1:
                return queened[0]
        raise ValueError(f"{text.strip()} is " + ("more than one move here" if found else "no move here"))

    # -- how it stands --------------------------------------------------------------------
    def insufficient(self) -> bool:
        """Neither side can mate: kings alone, a king and one knight or bishop, or bishops all on one colour."""
        rest = [(sq, p) for sq, p in enumerate(self.board) if p and p.lower() != "k"]
        if any(p.lower() in "pqr" for _sq, p in rest):
            return False
        if len(rest) <= 1:
            return True
        if all(p.lower() == "b" for _sq, p in rest):
            shades = {(sq % 8 + sq // 8) % 2 for sq, _p in rest}
            return len(shades) == 1
        return False


# -- a game ------------------------------------------------------------------------------
class Game:
    """The moves played from the start, and every position on the way."""

    def __init__(self, moves: list[str] | None = None, start: str = START) -> None:
        self.positions = [Position.from_fen(start)]
        self.moves: list[Move] = []
        self.sans: list[str] = []
        for text in moves or []:
            self.play(text)

    @property
    def position(self) -> Position:
        return self.positions[-1]

    @property
    def turn(self) -> str:
        return self.position.turn

    @property
    def ucis(self) -> list[str]:
        return [m.uci for m in self.moves]

    def legal(self) -> list[Move]:
        return self.position.legal()

    def parse(self, text: str) -> Move:
        return self.position.parse(text)

    def play(self, move: Move | str) -> Move:
        """Play a legal move — a Move, its uci, or as a person writes it. ValueError when it is none."""
        pos = self.position
        if isinstance(move, str):
            move = pos.parse(move)
        legal = pos.legal()
        if move not in legal:
            raise ValueError(f"{move.uci} is no move here")
        self.sans.append(pos.san(move, legal))
        self.moves.append(move)
        self.positions.append(pos.apply(move))
        return move

    def repeated(self) -> int:
        """How many times the position on the board has stood, this time included."""
        key = self.position.key()
        return sum(1 for p in self.positions if p.key() == key)

    def outcome(self) -> Outcome | None:
        """How the board alone ends it: checkmate, stalemate, material, fifty moves, repetition."""
        pos = self.position
        if not pos.legal():
            if pos.in_check():
                return Outcome(BLACK_WINS if pos.turn == "w" else WHITE_WINS, "checkmate")
            return Outcome(DRAWN, "stalemate")
        if pos.insufficient():
            return Outcome(DRAWN, "material")
        if pos.halfmove >= 100:
            return Outcome(DRAWN, "fifty moves")
        if self.repeated() >= 3:
            return Outcome(DRAWN, "repetition")
        return None

    def numbered(self) -> list[tuple[int, str, str]]:
        """The moves in pairs, as a score sheet has them: (1, "e4", "e5"), (2, "Nf3", "")."""
        out = []
        for i in range(0, len(self.sans), 2):
            out.append((i // 2 + 1, self.sans[i], self.sans[i + 1] if i + 1 < len(self.sans) else ""))
        return out


def lost_on_time(side: str, position: Position) -> Outcome:
    """The side whose flag fell loses — unless the other has nothing left to mate with."""
    other = "b" if side == "w" else "w"
    mine = [p for p in position.board if p and colour_of(p) == other and p.lower() != "k"]
    if not mine or (len(mine) == 1 and mine[0].lower() in "nb"):
        return Outcome(DRAWN, "time")
    return Outcome(WHITE_WINS if side == "b" else BLACK_WINS, "time")


# -- the clock ----------------------------------------------------------------------------
def _when(value) -> dt.datetime | None:
    if not value:
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    try:
        when = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.UTC)


def time_left(fields: dict, now: dt.datetime | None = None) -> dict[str, int] | None:
    """What each side has left, in milliseconds, now — or None for a game with no clock.

    `white_left` and `black_left` are as of the last move; the side to move
    has been thinking since `turn_at`, which is empty until both sides have
    moved once and after the game is over: the clock stands then."""
    if not fields.get("clock"):
        return None
    full = int(fields["clock"]) * 1000
    left = {
        "w": int(fields.get("white_left") if fields.get("white_left") is not None else full),
        "b": int(fields.get("black_left") if fields.get("black_left") is not None else full),
    }
    since = _when(fields.get("turn_at"))
    if since is None or fields.get("result"):
        return left
    side = "w" if len(fields.get("moves") or []) % 2 == 0 else "b"
    now = now or dt.datetime.now(dt.UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.UTC)
    left[side] = max(0, left[side] - int((now - since).total_seconds() * 1000))
    return left


def clock_text(ms: int) -> str:
    """5:00, 0:42, and tenths under ten seconds: 0:07.3."""
    ms = max(0, int(ms))
    if ms < 10_000:
        return f"0:{ms // 1000:02d}.{ms % 1000 // 100}"
    total = (ms + 999) // 1000
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def said(result: str, reason: str) -> str:
    """How a game ended, in words: White won by checkmate, Drawn by repetition."""
    if result == WHITE_WINS:
        who = "White won"
    elif result == BLACK_WINS:
        who = "Black won"
    else:
        who = "Drawn"
    how = {
        "checkmate": "by checkmate",
        "resigned": "by resignation",
        "time": "on time",
        "stalemate": "by stalemate",
        "agreed": "by agreement",
        "repetition": "by repetition",
        "fifty moves": "by the fifty-move rule",
        "material": "for want of material",
        "aborted": "— aborted",
    }.get(reason, "")
    return f"{who} {how}".strip()
