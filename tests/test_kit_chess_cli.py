"""`cm <quill> …` for a chess board: games started, shown, played and given up, on a real server.

The Chessboard fixture's code keeps a move when the rules allow it, and its
computer answers with the first legal move it finds.
"""

from __future__ import annotations

import asyncio
import io

import httpx
import pytest
import typer
from fastapi.testclient import TestClient
from rich.console import Console

from cloudmorrow.cli import quillrun
from cloudmorrow.cli.quill import preview
from cloudmorrow.client import chess as cc
from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.client.config import ClientConfig
from cloudmorrow.server.app import create_app
from tests.conftest import ADMIN, GUEST, QUILL_CATALOG, token_for

CHESSBOARD = QUILL_CATALOG / "quill-chessboard"


@pytest.fixture()
def board(config, users) -> TestClient:
    config.quill_code = "trusted"
    client = TestClient(create_app(config))
    client.app.state.cloudmorrow.quills.install(CHESSBOARD, QUILL_CATALOG / "datamodels")
    return client


@pytest.fixture()
def cm(board, monkeypatch):
    def run(*argv: str, who=ADMIN, plain: bool = False, **timing) -> str:
        screen_out = Console(file=io.StringIO(), width=200, color_system=None)
        monkeypatch.setattr(quillrun, "out", screen_out)
        monkeypatch.setattr(quillrun, "console", screen_out)
        monkeypatch.setattr(quillrun, "emit", screen_out.file.write)
        api = CloudmorrowClient(ClientConfig(api_url="http://testserver"), token=token_for(board, *who))
        api._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=board.app), base_url="http://testserver")

        async def go() -> None:
            try:
                await quillrun.dispatch(api, "chessboard", argv[0], list(argv[1:]), plain=plain, timing=timing)
            finally:
                await api.aclose()

        asyncio.run(go())
        return screen_out.file.getvalue()

    return run


def games(client: TestClient, who=ADMIN) -> list[dict]:
    auth = {"Authorization": f"Bearer {token_for(client, *who)}"}
    return client.get("/api/records/chessboard.game", headers=auth).json()


def test_a_game_against_a_person_is_started_shown_and_played(cm, board):
    made = cm("new", "guest", clock="5m", colour="white")
    assert "Your move" in made and "5 min" in made
    (game,) = games(board)
    f = game["fields"]
    assert (f["white"], f["black"], f["clock"], f["white_left"]) == ("bram", "guest", 300, 300_000)
    short = game["id"][2:6]
    played = cm("move", short, "e4")
    assert "guest to move" in played and "1. e4" in played
    # The other side sees the same game, as theirs to move.
    assert "Your move" in cm("list", who=GUEST)
    assert "1. e4 e5" in cm("move", short, "e7e5", who=GUEST)
    listed = cm("list")
    assert "guest" in listed and "Your move" in listed
    shown = cm("show", short)
    # White at the foot: rank 1 is the last rank printed before the files.
    lines = shown.splitlines()
    files = next(i for i, line in enumerate(lines) if line.strip().startswith("a  b"))
    assert lines[files - 1].startswith("1 ") and lines[files - 8].startswith("8 ")
    assert "clock" in shown and "5:00" in shown


def test_a_move_that_is_no_move_is_said_without_asking_the_server(cm, board):
    cm("new", "guest", clock="none", colour="white")
    short = games(board)[0]["id"][2:6]
    with pytest.raises(typer.Exit):
        cm("move", short, "e5")
    assert games(board)[0]["fields"]["moves"] == []


def test_the_computer_is_played_by_its_name(cm, board):
    shown = cm("new", "computer", clock="none", colour="white")
    assert "Computer" in shown
    (game,) = games(board)
    assert game["fields"]["computer"] == "black"
    cm("move", game["id"][2:6], "d4")
    assert len(games(board)[0]["fields"]["moves"]) == 2  # it answered


def test_black_sees_the_board_turned_round(cm, board):
    cm("new", "guest", clock="none", colour="black")
    shown = cm("show", games(board)[0]["id"][2:6])
    lines = shown.splitlines()
    files = next(i for i, line in enumerate(lines) if line.strip().startswith("h  g"))
    assert lines[files - 1].startswith("8 ")


def test_resigning_ends_it(cm, board):
    cm("new", "guest", clock="none", colour="white")
    short = games(board)[0]["id"][2:6]
    said = cm("resign", short)
    assert "guest won by resignation" in said
    assert games(board)[0]["fields"]["result"] == "0-1"


def test_a_time_that_is_not_offered_is_refused(cm):
    with pytest.raises(typer.Exit):
        cm("new", "guest", clock="7m")
    with pytest.raises(typer.Exit):
        cm("new", "guest", colour="purple")


def test_the_chess_words_are_a_chess_boards():
    assert set(quillrun.CHESS_ONLY) <= set(quillrun.ACTIONS)


def test_plain_is_json(cm):
    cm("new", "guest", clock="none", colour="white")
    assert '"white": "bram"' in cm("list", plain=True)


def test_the_clock_choices_come_from_the_start_action(board):
    quill = board.app.state.cloudmorrow.quills.plan(CHESSBOARD, QUILL_CATALOG / "datamodels")
    chess = cc.Chess(None, quill, quill["screens"][0])
    assert chess.choices("clock") == [("0", "No limit"), ("600", "10 minutes"), ("300", "5 minutes")]
    assert chess.clock_value("5m") == "300" and chess.clock_value("10") == "600"
    assert chess.clock_value("none") == "0" and chess.clock_value("600") == "600"
    with pytest.raises(ValueError):
        chess.clock_value("3m")


def test_the_preview_draws_a_board(board):
    quill = board.app.state.cloudmorrow.quills.plan(CHESSBOARD, QUILL_CATALOG / "datamodels")
    sketch = preview(quill)
    assert "♚" in sketch and "Nf3" in sketch and "r resigns" in sketch


def test_what_a_game_says_to_each_side():
    fields = {"white": "bram", "black": "sara", "moves": ["e2e4"]}
    assert cc.status(fields, "bram") == "sara to move"
    assert cc.status(fields, "sara") == "Your move"
    assert cc.status(fields, "ole") == "sara to move"
    assert cc.status({**fields, "draw": "bram"}, "sara") == "bram offers a draw"
    assert cc.status({**fields, "result": "1-0", "reason": "checkmate"}, "bram") == "You won by checkmate"
    assert cc.status({**fields, "result": "1-0", "reason": "time"}, "sara") == "bram won on time"
    assert cc.status({**fields, "result": "1/2-1/2", "reason": "agreed"}, "sara") == "Drawn by agreement"
    computer = {"white": "bram", "black": "Morrow", "computer": "black", "level": 3, "moves": []}
    assert cc.opponent(computer, "bram") == "Morrow · level 3"
    assert cc.side_of(computer, "Morrow") == ""
    assert cc.time_said({"clock": 600}) == "10 min" and cc.time_said({}) == "No limit"
