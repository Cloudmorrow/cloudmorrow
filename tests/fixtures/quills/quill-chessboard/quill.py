"""Chessboard: the two buttons the chess kit presses, as simply as they go."""

from cloudmorrow.quill import action, error, go
from cloudmorrow.quill.chess import BLACK_WINS, WHITE_WINS, Game

GAME, TABLE, COMPUTER = "chessboard.game", "chessboard.table", "chessboard.computer"


@action("start")
def start(ctx, opponent, clock="600", colour="random"):
    me = ctx.user.username
    computers = {c.id: c for c in ctx.records.list(COMPUTER)}
    against = computers.get(opponent)
    them = against["name"] if against else opponent
    white, black = (them, me) if colour == "black" else (me, them)
    table = ctx.records.create(
        TABLE,
        name=f"{white} and {black}",
        kind="computer" if against else "people",
        scope="personal" if against else "shared",
        members=[] if against else [opponent],
    )
    seconds = int(clock or 0)
    fields = {"table": table.id, "name": f"{white} – {black}", "white": white, "black": black, "moves": []}
    if seconds:
        fields.update(clock=seconds, white_left=seconds * 1000, black_left=seconds * 1000)
    if against:
        fields.update(computer="white" if colour == "black" else "black", level=against.get("level") or 1)
    game = ctx.records.create(GAME, fields)
    return go("games", game=game.id)


@action("play")
def play(ctx, game, move):
    board = Game(list(game.get("moves") or []))
    if move == "resign":
        mine = "w" if game["white"] == ctx.user.username else "b"
        ctx.records.patch(GAME, game.id, result=BLACK_WINS if mine == "w" else WHITE_WINS, reason="resigned")
        return None
    try:
        board.play(move)
    except ValueError as exc:
        return error(str(exc))
    if game.get("computer") and board.legal() and not board.outcome():
        board.play(board.legal()[0])
    ended = board.outcome()
    fields = {"moves": board.ucis}
    if ended:
        fields.update(result=ended.result, reason=ended.reason)
    ctx.records.patch(GAME, game.id, fields)
    return None
