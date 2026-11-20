"""A chess board's reads and words, as the terminal and the command line have them.

The rules are cloudmorrow.quill.chess's; the bindings quill/screens.py's
`chess_fields`. What is here is what both surfaces say the same way: whose
move it is, who won, the clock choices the start action offers, a game
named by the start of its id or its name, the computers there are to play,
and the board drawn as text. A move is never written here: it is the
screen's `play` action, pressed with it, and the Quill's code that keeps it.
"""

from __future__ import annotations

from cloudmorrow.quill import chess as ch
from cloudmorrow.quill.screens import chess_fields

# The pieces as a terminal draws them: one shape, coloured by side.
GLYPH = {"k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟"}
# And as plain text, where colour is not there: white's hollow, black's filled.
OUTLINE = {"K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙"}
# How a clock may be typed, beside the start action's own values.
CLOCK_WORDS = {
    "none": 0,
    "no": 0,
    "nolimit": 0,
    "unlimited": 0,
    "off": 0,
    "0": 0,
}


class Chess:
    """One chess screen's bindings, and the reads made on them."""

    def __init__(self, api, quill: dict, screen: dict) -> None:
        self.api = api
        self.quill = quill
        self.spec = screen
        models = quill.get("models") or {}
        self.model: dict = models.get(screen["model"]) or {"id": screen["model"], "fields": []}
        self.bound = chess_fields(screen, self.model, models)
        self.game_model: str = self.bound["game"]
        self.computer_model: str = self.bound["computers"] if self.bound["computers"] in models else ""
        self.title: str = self.bound["title"]
        actions = {a.get("id"): a for a in quill.get("actions") or []}
        self.play_action: dict | None = actions.get(self.bound["play"])
        self.start_action: dict | None = actions.get(self.bound["start"])

    # -- reading -----------------------------------------------------------------
    async def games(self) -> list[dict]:
        """Every game, the one changed last first."""
        found = await self.api.records(self.game_model)
        return sorted(found, key=lambda r: str(r.get("updated_at") or r.get("created_at") or ""), reverse=True)

    async def game(self, game_id: str) -> dict:
        return await self.api.record(self.game_model, game_id)

    async def computers(self) -> list[dict]:
        if not self.computer_model:
            return []
        return await self.api.records(self.computer_model)

    # -- the start action's form -------------------------------------------------
    def choices(self, name: str) -> list[tuple[str, str]]:
        """An enum field of the start action as (value, label) pairs; [] when it has none."""
        fields = (self.start_action or {}).get("fields") or []
        field = next((f for f in fields if f.get("name") == name), None) if isinstance(fields, list) else None
        if field is None and isinstance(fields, dict):
            field = fields.get(name)
        if not field or not field.get("values"):
            return []
        values = [str(v) for v in field["values"]]
        labels = [str(v) for v in field.get("labels") or values]
        return list(zip(values, labels + values[len(labels) :], strict=False))

    def default(self, name: str) -> str:
        fields = (self.start_action or {}).get("fields") or []
        field = next((f for f in fields if f.get("name") == name), None) if isinstance(fields, list) else None
        return str((field or {}).get("default") or "")

    def clock_value(self, typed: str) -> str:
        """`5m`, `10`, `600`, `none` → the start action's value for it. ValueError for anything else."""
        word = str(typed).strip().lower().replace(" ", "").replace("minutes", "m").replace("min", "m")
        if word in CLOCK_WORDS:
            seconds = CLOCK_WORDS[word]
        else:
            try:
                if word.endswith("m"):
                    seconds = int(float(word[:-1]) * 60)
                elif word.endswith("s"):
                    seconds = int(word[:-1])
                else:
                    number = int(word)
                    seconds = number * 60 if number < 60 else number
            except ValueError:
                raise ValueError(f"{typed!r} is no time: none, 5m or 10m") from None
        offered = [v for v, _ in self.choices("clock")]
        if offered and str(seconds) not in offered:
            said = ", ".join(label for _, label in self.choices("clock"))
            raise ValueError(f"the games here are {said}")
        return str(seconds)


# -- what a game says ---------------------------------------------------------------
def moves_of(fields: dict) -> list[str]:
    """The moves to draw: the computer's last kept back while it is still thinking it over."""
    return ch.shown_moves(fields)


def game_of(fields: dict) -> ch.Game:
    """The game the moves make; a move the rules refuse ends it there."""
    game = ch.Game()
    for move in moves_of(fields):
        try:
            game.play(ch.Move.from_uci(move))
        except ValueError:
            break
    return game


def side_of(fields: dict, me: str) -> str:
    """The side *me* plays: w, b, or "" for somebody looking on."""
    if fields.get("white") == me and fields.get("computer") != "white":
        return "w"
    if fields.get("black") == me and fields.get("computer") != "black":
        return "b"
    return ""


def name_of(fields: dict, side: str) -> str:
    return str(fields.get("white" if side == "w" else "black") or ("White" if side == "w" else "Black"))


def opponent(fields: dict, me: str) -> str:
    """Who *me* plays against; both names for somebody looking on."""
    side = side_of(fields, me)
    if not side:
        return f"{name_of(fields, 'w')} – {name_of(fields, 'b')}"
    other = name_of(fields, "b" if side == "w" else "w")
    if fields.get("computer") and fields.get("level"):
        return f"{other} · level {fields['level']}"
    return other


def time_said(fields: dict) -> str:
    """The time control: No limit, 10 min, 5 min."""
    seconds = int(fields.get("clock") or 0)
    if not seconds:
        return "No limit"
    if seconds % 60 == 0:
        return f"{seconds // 60} min"
    return f"{seconds} s"


def status(fields: dict, me: str, game: ch.Game | None = None) -> str:
    """Your move, Sara to move, You won by checkmate, Drawn by repetition."""
    side = side_of(fields, me)
    result = str(fields.get("result") or "")
    if result:
        said = ch.said(result, str(fields.get("reason") or ""))
        if result == ch.DRAWN:
            return said
        winner = "w" if result == ch.WHITE_WINS else "b"
        how = said.split(" ", 2)[2] if said.count(" ") >= 2 else ""
        if side:
            who = "You won" if winner == side else f"{name_of(fields, winner)} won"
        else:
            who = f"{name_of(fields, winner)} won"
        return f"{who} {how}".strip()
    game = game or game_of(fields)
    turn = game.turn
    offered = str(fields.get("draw") or "")
    if offered and offered != me and side:
        return f"{offered} offers a draw"
    if ch.thinking(fields):
        return f"{name_of(fields, turn)} is thinking"
    if side and turn == side:
        return "Your move"
    return f"{name_of(fields, turn)} to move"


def mine_to_move(fields: dict, me: str) -> bool:
    side = side_of(fields, me)
    return bool(side) and not fields.get("result") and game_of(fields).turn == side


def board_lines(position: ch.Position, *, flip: bool = False, last: ch.Move | None = None) -> list[str]:
    """The board as plain text: ranks down the left, files along the foot, white's pieces hollow."""
    ranks = range(8) if flip else range(7, -1, -1)
    files = range(7, -1, -1) if flip else range(8)
    lit = {last.frm, last.to} if last else set()
    lines = []
    for r in ranks:
        cells = []
        for f in files:
            sq = r * 8 + f
            piece = position.board[sq]
            mark = OUTLINE.get(piece, GLYPH.get(piece, "")) if piece else ("·" if (r + f) % 2 else " ")
            cells.append(f"[{mark}]" if sq in lit else f" {mark} ")
        lines.append(f"{r + 1} " + "".join(cells))
    lines.append("  " + "".join(f" {ch.FILES[f]} " for f in files))
    return lines


def numbered(game: ch.Game) -> list[str]:
    """The moves as a score sheet: `1. e4 e5`."""
    return [f"{n}. {w} {b}".rstrip() for n, w, b in game.numbered()]
