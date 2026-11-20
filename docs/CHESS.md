# The chess kit

`kit = "chess"` is a chess board: games between the people on a cloud, or
against a computer the Quill plays, with a chess clock or without.
Cloudmorrow draws it on the web and the phone (a flat board seen from
above, the pieces moved by a press or a drag, the clocks ticking), in the
terminal (the board in text, a move typed) and on the command line
(`cm <quill> move <game> Nf3`). The rules are the core's, the same on every
surface: `quill/chess.py` in Python, `kit_chess_rules.js` in the browser.
What is kept, and what counts as a move, is the Quill's: its code checks
every move with the same rules before it keeps it.

## The screen

```toml
[[screens]]
id = "games"
kit = "chess"
label = "Chess"
model = "chess.game"              # the games
title = "name"
play = "play"                     # an action on a game, with a field `move`
start = "start"                   # an action on no record, with a field `opponent`
computers = "chess.computer"      # optional: the computers there are to play
```

The field names below are the kit's: the datamodels have them, with these
kinds, or `cm quill check` says which is missing.

### A game (`model`)

| field | kind | |
| --- | --- | --- |
| *title* | string | what it is called in lists: `anna – sara` |
| `white`, `black` | string | who plays each side: a person's username, or the computer's name |
| `moves` | json | the moves played from the usual start, each as a program writes it: `e2e4`, `e7e8q`, `e1g1` to castle |
| `computer` | string, optional | which side the computer plays, `white` or `black`; empty between people |
| `level` | int, optional | the computer's level when the game began, said beside its name |
| `clock` | int, optional | the seconds each side starts with; empty or 0 is no limit |
| `white_left`, `black_left` | int, optional | what each side had left after its last move, in milliseconds |
| `turn_at` | datetime, optional | since when the side to move has been thinking; empty until both have moved once, and once it is over: the clock stands then |
| `answer_at` | datetime, optional | when the computer's last move is to be seen: it works its move out at once and takes its time over it, as a person would; until then every surface shows it thinking, its last move kept back and its clock running down to what it will have left |
| `result` | string, optional | `1-0`, `0-1` or `1/2-1/2` once it is over |
| `reason` | string, optional | why: `checkmate`, `resigned`, `time`, `stalemate`, `agreed`, `repetition`, `fifty moves`, `material` |
| `draw` | string, optional | who has offered a draw, until it is taken, declined, or a move is made |

The side to move is the one the number of moves says; what a clock shows
now is `time_left(fields)` (`quill/chess.py`, and `timeLeft` in the
browser): the side to move's time less what has passed since `turn_at`.

### A computer (`computers`)

| field | kind | |
| --- | --- | --- |
| `name` | string | what it is called: Morrow |
| `level` | int, optional | how good it is now, said on the new-game sheet |

### The two actions

`play` is pressed on the game with `move` = a move, as `e2e4` or `Nf3`, or
one of these words:

| word | does |
| --- | --- |
| `resign` | the other side wins |
| `draw` | offers a draw, or takes the one offered |
| `decline` | turns the offered draw down |
| `time` | the side to move's clock has run out: the Quill checks it and ends the game |

`start` is pressed with `opponent` (a username, or the id of a computer's
record) and, when the action has them, `clock` and `colour` — enum fields
whose values and labels the kit offers as they are (`0`, `600`, `300` as
No limit, 10 minutes, 5 minutes; `random`, `white`, `black`). Without a
`colour` field nobody is asked: the Quill decides who has white (Chess has
the colours take turns from one game to the next at the same table), and
Rematch sends none. It answers `go("<screen>", game=<id>)`, and the new
game opens.

What the Quill does in them is its own; a Quill like Chess, in short:

```python
from cloudmorrow.quill.chess import Game, time_left

@action("play")
def play(ctx, game, move):
    board = Game(game.get("moves") or [])
    board.play(move)                      # ValueError: no move here
    ended = board.outcome()               # None, or Outcome("1-0", "checkmate")
    ctx.records.patch("chess.game", game.id, {"moves": board.ucis, **(ended._asdict() if ended else {})}, rev=game.rev)
```

## The rules

`cloudmorrow.quill.chess` is in the SDK the sandbox has:

| | |
| --- | --- |
| `Game(moves)` | the moves played (uci), every position on the way; `.play(move)` (a `Move`, uci, or as people write it), `.legal()`, `.parse(text)`, `.sans`, `.ucis`, `.numbered()`, `.outcome()`, `.position` |
| `Position` | the board (64 squares, a1 = 0), whose move, the castling rights, the square taken in passing; `.legal()`, `.san(move)`, `.parse(text)`, `.in_check()`, `.fen()`, `Position.from_fen(...)` |
| `Move` | `frm`, `to`, `promote`; `.uci`, `Move.from_uci("e7e8q")` |
| `time_left(fields, now)`, `clock_text(ms)` | the clock |
| `thinking(fields, now)`, `shown_moves(fields, now)` | how long the computer's last move is still kept back (`answer_at`), and the moves to draw meanwhile |
| `lost_on_time(side, position)` | the side whose flag fell loses, unless the other has nothing to mate with: a draw |
| `said(result, reason)` | White won by checkmate, Drawn by repetition |

A game ends by itself on checkmate, stalemate, a position that has stood
three times, fifty moves each with no capture and no pawn moved, and when
neither side has enough left to mate. The browser's rules are the same and
are tested against the same counts of positions (perft).

## On each surface

| | phone | web | terminal | command line |
| --- | --- | --- | --- | --- |
| the games | your move first, then those waiting on the other side, then the finished ones, each with a small board | the same down the left, the open one lit | a table: who against, the time, where it stands | `cm <quill> list` |
| a game | the other player and their clock above the board, you and yours below, the moves under it, Offer draw and Resign; Rematch and New game once it is over | the board in the middle, the clocks with it, the moves and the buttons beside | the board in text, the clocks, the moves; a move typed | `cm <quill> show <game>` |
| moving | press a piece, then where it goes (dotted), or drag it; a pawn at the end asks what it becomes | the same, with a mouse | `e4`, `Nf3`, `e7e8q` typed and Enter | `cm <quill> move <game> Nf3` |
| the rest | | | `n` new game, `d` draw, `r` resign | `cm <quill> new <opponent> --clock 5m --colour white`, `draw`, `resign` |

On the web and the phone the board is heard: a wooden tap for a move, a
heavier knock for a capture, both pieces of a castle, a small bell with
check, a chime when it is over — made in the browser (Web Audio, no
files), woken by the first press on the board, and switched off with the
speaker beside the moves (the choice is the browser's own). A piece
dragged and put back where it stood stays there; only a square it may go
to is a move.

The board is drawn from above, white at the bottom unless you play black;
the last move is lit, a king in check glows, and the pieces each side has
taken are drawn beside its name with what it is ahead by. The clock runs
on every screen the game is open on, from the game's fields; the one whose
time runs out is told to the Quill (`time`), which checks it. The other
player's move arrives by the change feed. A new game made between people
tells the other one, with a push, when the game datamodel has a
`[[notify]]` rule — it lives in a space the two of them share.

## Where the code is

| | |
| --- | --- |
| the rules | `quill/chess.py` (also in the sandbox's SDK), web `kit_chess_rules.js` |
| what a screen binds | `quill/screens.py` (`chess_fields`), checked by `server/quills/checks.py` |
| the web and the phone | `kit_chess.js`, `kit_chess_pieces.js` (the pieces, drawn here), `kit_chess_sound.js` (the sounds, made here), `kit_chess.css` |
| the terminal | `tui/panes/kit_chess.py` |
| the command line | `cli/quillrun/chess.py` |
| a Quill to test with | `tests/fixtures/quills/quill-chessboard` |
