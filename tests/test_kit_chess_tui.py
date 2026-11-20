"""The kit's `chess` in the terminal: the games, then a board (docs/CHESS.md).

Drawn from the Chessboard fixture's screen, against the fake server's record
store; the screen's `play` and `start` actions are answered here the way the
fixture's code answers them: a move the rules allow is kept, a new game is
made and gone to.
"""

from __future__ import annotations

import copy
import datetime as dt
import tempfile
from pathlib import Path

from textual.widgets import DataTable, Input, RadioSet, Static

from cloudmorrow.quill import chess as ch
from cloudmorrow.server.quills import QuillRegistry
from cloudmorrow.tui.panes.kit_chess import BoardView, ChessPane, NewGameModal, board_text
from cloudmorrow.tui.screens.modals import ConfirmModal
from tests.conftest import QUILL_CATALOG
from tests.tui_harness import feature_row, settle, start
from tests.tui_quills import record_row

CHESSBOARD = QUILL_CATALOG / "quill-chessboard"
GAME = "chessboard.game"


def chessboard_quill() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        registry = QuillRegistry(Path(tmp) / "quills", Path(tmp) / "datamodels")
        quill = registry.plan(CHESSBOARD, QUILL_CATALOG / "datamodels")
    return copy.deepcopy(quill)


def with_chessboard(app, *, clock: int = 0, moves: list[str] | None = None, **game) -> None:
    client = app.client
    client.quill_list.append(chessboard_quill())
    client.feature_list.append(feature_row("chessboard", "Chessboard"))
    fields = {"table": "r_t", "name": "bram – guest", "white": "bram", "black": "guest", "moves": moves or []}
    if clock:
        fields.update(clock=clock, white_left=clock * 1000, black_left=clock * 1000)
    fields.update(game)
    client.record_store[GAME] = [
        record_row(GAME, "r_g1", 0, **fields),
        record_row(
            GAME,
            "r_old",
            1,
            name="ada – bram",
            white="ada",
            black="bram",
            moves=["f2f3", "e7e5", "g2g4", "d8h4"],
            result="0-1",
            reason="checkmate",
        ),
    ]
    client.record_store["chessboard.computer"] = [record_row("chessboard.computer", "r_c", 0, name="Computer", level=3)]
    client.pressed = []

    async def quill_action(quill_id, action_id, *, record="", fields=None):
        fields = dict(fields or {})
        client.pressed.append((quill_id, action_id, record, fields))
        if action_id == "start":
            made = await client.create_record(
                GAME, {"table": "r_t", "name": "new", "white": "bram", "black": fields["opponent"], "moves": []}
            )
            return [{"effect": "go", "screen": "games", "params": {"game": made["id"]}}]
        row = next(r for r in client.record_store[GAME] if r["id"] == record)
        word = fields["move"]
        if word == "resign":
            await client.update_record(GAME, record, {"result": "0-1", "reason": "resigned"})
            return [{"effect": "toast", "text": "You resigned"}]
        if word in ("draw", "time"):
            return [{"effect": "toast", "text": word}]
        game = ch.Game(row["fields"]["moves"])
        try:
            game.play(word)
        except ValueError as exc:
            return [{"effect": "error", "text": str(exc)}]
        await client.update_record(GAME, record, {"moves": game.ucis})
        return []

    client.quill_action = quill_action


async def open_board(app, pilot) -> ChessPane:
    screen = await start(app, pilot)
    await pilot.click("#nav-chessboard")
    await settle(app, pilot)
    return screen.query_one(ChessPane)


async def open_game(app, pilot) -> ChessPane:
    pane = await open_board(app, pilot)
    pane.query_one("#cs-games", DataTable).move_cursor(row=0)
    pane.act_open()
    await settle(app, pilot)
    return pane


def plain(widget: Static) -> str:
    return str(widget.render())


# -- the board, drawn ----------------------------------------------------------------------------
def test_the_board_has_white_at_the_foot_unless_turned():
    text = board_text(ch.Position.start(), cell=(3, 1)).plain.splitlines()
    assert text[0].startswith("8 ") and "♜" in text[0] and text[7].startswith("1 ") and "♔" in text[7]
    assert text[8].split() == list("abcdefgh")
    turned = board_text(ch.Position.start(), flip=True, cell=(3, 1)).plain.splitlines()
    assert turned[0].startswith("1 ") and turned[8].split() == list("hgfedcba")


def test_the_squares_it_may_go_to_are_dotted():
    text = board_text(ch.Position.start(), picked=12, targets=frozenset({20, 28}), cell=(3, 1)).plain.splitlines()
    assert text[5].count("•") == 1 and text[4].count("•") == 1


# -- the games ---------------------------------------------------------------------------------------
async def test_the_games_are_listed_with_how_each_stands(app):
    with_chessboard(app)
    async with app.run_test(size=(150, 42)) as pilot:
        pane = await open_board(app, pilot)
        table = pane.query_one("#cs-games", DataTable)
        rows = [[str(c) for c in table.get_row_at(i)] for i in range(table.row_count)]
        assert rows[0][0] == "guest" and rows[0][3] == "Your move"
        assert rows[1][0] == "ada" and rows[1][3] == "You won by checkmate"
        assert pane.card_status() == ("news", "1 your move")


async def test_a_typed_move_is_played_and_kept(app):
    with_chessboard(app)
    async with app.run_test(size=(150, 42)) as pilot:
        pane = await open_game(app, pilot)
        assert pane.playing and "Your move" in plain(pane.query_one("#cs-head", Static))
        box = pane.query_one("#cs-move", Input)
        box.focus()
        box.value = "Nf3"
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.client.pressed[-1] == ("chessboard", "play", "r_g1", {"move": "g1f3"})
        assert app.client.record_store[GAME][0]["fields"]["moves"] == ["g1f3"]
        assert "guest to move" in plain(pane.query_one("#cs-head", Static))
        assert "1. Nf3" in plain(pane.query_one("#cs-moves", Static))


async def test_a_move_that_is_none_is_said_and_not_sent(app):
    with_chessboard(app)
    async with app.run_test(size=(150, 42)) as pilot:
        pane = await open_game(app, pilot)
        box = pane.query_one("#cs-move", Input)
        box.focus()
        box.value = "e5"
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.client.pressed == []


async def test_a_piece_is_clicked_then_where_it_goes(app):
    with_chessboard(app)
    async with app.run_test(size=(150, 42)) as pilot:
        pane = await open_game(app, pilot)
        pane.on_board_view_clicked(BoardView.Clicked(ch.square("e2")))
        assert pane.picked == ch.square("e2")
        pane.on_board_view_clicked(BoardView.Clicked(ch.square("e4")))
        await settle(app, pilot)
        assert app.client.record_store[GAME][0]["fields"]["moves"] == ["e2e4"]
        # Not your move now: a click does nothing.
        pane.on_board_view_clicked(BoardView.Clicked(ch.square("d2")))
        assert pane.picked == -1


async def test_black_plays_from_the_foot_and_waits_its_turn(app):
    with_chessboard(app, white="guest", black="bram")
    async with app.run_test(size=(150, 42)) as pilot:
        pane = await open_game(app, pilot)
        assert pane.side == "b" and pane.query_one("#cs-board", BoardView).flip
        assert "guest to move" in plain(pane.query_one("#cs-head", Static))
        pane.play(ch.Move.from_uci("e7e5"))
        await settle(app, pilot)
        assert app.client.pressed == []


async def test_the_clocks_are_drawn_and_a_fallen_flag_is_claimed_once(app):
    long_ago = (dt.datetime.now(dt.UTC) - dt.timedelta(minutes=10)).isoformat()
    with_chessboard(app, clock=300, moves=["e2e4", "e7e5"], turn_at=long_ago, black_left=250_000)
    app.client.record_store[GAME][0]["fields"].update(white="guest", black="bram")
    async with app.run_test(size=(150, 42)) as pilot:
        pane = await open_game(app, pilot)
        assert "4:10" in plain(pane.query_one("#cs-bottom", Static))  # yours: black's
        assert "0:00.0" in plain(pane.query_one("#cs-top", Static))
        pane.tick()
        pane.tick()
        await settle(app, pilot)
        assert [p[3] for p in app.client.pressed] == [{"move": "time"}]


async def test_resign_asks_first(app):
    with_chessboard(app)
    async with app.run_test(size=(150, 42)) as pilot:
        pane = await open_game(app, pilot)
        pane.act_resign()
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        await pilot.press("y")
        await settle(app, pilot)
        assert app.client.pressed[-1][3] == {"move": "resign"}
        assert "guest won by resignation" in plain(pane.query_one("#cs-head", Static))


async def test_new_asks_whom_against_how_long_and_which_colour(app):
    with_chessboard(app)
    async with app.run_test(size=(150, 42)) as pilot:
        pane = await open_board(app, pilot)
        pane.act_new_record()
        # The worker waits on the sheet: pauses, not settle, until it is answered.
        for _ in range(4):
            await pilot.pause()
        modal = app.screen
        assert isinstance(modal, NewGameModal)
        assert [label for _v, label in modal.opponents][:2] == ["Computer · level 3", "Guest (guest)"]
        assert [v for v, _ in modal.clocks] == ["0", "600", "300"]
        assert modal.query_one("#cs-new-clock", RadioSet).pressed_index == 1  # the action's default
        modal.dismiss({"opponent": "guest", "clock": "300", "colour": "white"})
        await settle(app, pilot)
        assert app.client.pressed[-1][1:] == ("start", "", {"opponent": "guest", "clock": "300", "colour": "white"})
        await settle(app, pilot)
        assert pane.playing and pane.game["fields"]["black"] == "guest"
