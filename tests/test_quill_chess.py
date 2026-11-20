"""The rules of chess (quill/chess.py), and what a manifest's chess screen must have.

The rules are what a Quill's code checks a move with before it keeps it, so
they are held to the published move counts (perft) of the five positions
every chess program is tested on, and to the moves as people write them.
"""

from __future__ import annotations

import datetime as dt
import shutil
import tomllib
from pathlib import Path

import pytest

from cloudmorrow.quill import chess as ch
from cloudmorrow.sandbox import SDK_FILES
from cloudmorrow.server.quills import QuillError, QuillRegistry
from tests.conftest import QUILL_CATALOG

CHESSBOARD = QUILL_CATALOG / "quill-chessboard"

PERFT = [
    ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", [20, 400, 8902]),
    ("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", [48, 2039]),
    ("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", [14, 191, 2812]),
    ("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", [6, 264]),
    ("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", [44, 1486]),
]


def perft(position: ch.Position, depth: int) -> int:
    if depth == 0:
        return 1
    moves = position.legal()
    if depth == 1:
        return len(moves)
    return sum(perft(position.apply(m), depth - 1) for m in moves)


@pytest.mark.parametrize(("fen", "counts"), PERFT)
def test_the_moves_counted_are_the_published_ones(fen, counts):
    position = ch.Position.from_fen(fen)
    assert [perft(position, d + 1) for d in range(len(counts))] == counts


def test_a_position_reads_and_writes_as_fen():
    assert ch.Position.start().fen() == ch.START
    fen = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
    assert ch.Position.from_fen(fen).fen() == fen
    with pytest.raises(ValueError):
        ch.Position.from_fen("not a board")


def test_moves_are_written_as_people_write_them():
    game = ch.Game()
    for move in ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O", "Be7"]:
        game.play(move)
    assert game.sans[-2:] == ["O-O", "Be7"]
    assert game.ucis[8] == "e1g1"
    assert game.numbered()[0] == (1, "e4", "e5")
    # Two knights that reach one square: the file says which.
    knights = ch.Position.from_fen("4k3/8/8/8/8/8/8/1N2KN2 w - - 0 1")
    assert knights.san(knights.parse("b1d2")) == "Nbd2"
    # Two rooks on one file: the rank says which.
    rooks = ch.Position.from_fen("4k3/R7/8/8/8/8/R7/4K3 w - - 0 1")
    assert rooks.san(rooks.parse("a2a4")) == "R2a4"
    # Promotion, and check.
    pawn = ch.Position.from_fen("4k3/1P6/8/8/8/8/8/4K3 w - - 0 1")
    assert pawn.san(ch.Move.from_uci("b7b8q")) == "b8=Q+"
    # Mate.
    mate = ch.Game(["f2f3", "e7e5", "g2g4"])
    mate.play("Qh4")
    assert mate.sans[-1] == "Qh4#"
    # In passing.
    passing = ch.Game(["e2e4", "a7a6", "e4e5", "d7d5"])
    assert passing.position.san(passing.parse("exd6")) == "exd6"


def test_a_move_is_read_however_it_is_typed():
    position = ch.Position.start()
    assert position.parse("Nf3").uci == "g1f3"
    assert position.parse("g1f3").uci == "g1f3"
    assert position.parse("nf3").uci == "g1f3"
    assert position.parse("e4!").uci == "e2e4"
    castle = ch.Position.from_fen("4k3/8/8/8/8/8/8/R3K2R w KQ - 0 1")
    assert castle.parse("0-0").uci == "e1g1"
    assert castle.parse("O-O-O").uci == "e1c1"
    promote = ch.Position.from_fen("4k3/1P6/8/8/8/8/8/4K3 w - - 0 1")
    assert promote.parse("b8=Q").uci == "b7b8q"
    assert promote.parse("b8N").uci == "b7b8n"
    assert promote.parse("b7b8").uci == "b7b8q"  # a promotion with nothing said is a queen
    assert promote.parse("b8").uci == "b7b8q"
    for nonsense in ("e5", "Qh5", "", "zz", "e2e5"):
        with pytest.raises(ValueError):
            position.parse(nonsense)


def test_how_a_game_ends():
    mate = ch.Game(["f2f3", "e7e5", "g2g4", "d8h4"])
    assert mate.outcome() == ch.Outcome("0-1", "checkmate")
    stalemate = ch.Game(start="7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    assert stalemate.outcome() == ch.Outcome("1/2-1/2", "stalemate")
    assert ch.Game(start="4k3/8/8/8/8/8/8/3NK3 w - - 0 1").outcome() == ch.Outcome("1/2-1/2", "material")
    # Bishops on one colour cannot mate; on both they can.
    assert ch.Position.from_fen("2b1k3/8/8/8/8/8/8/2B1K3 w - - 0 1").insufficient() is False
    assert ch.Position.from_fen("4kb2/8/8/8/8/8/8/2B1K3 w - - 0 1").insufficient() is True
    fifty = ch.Game(start="4k3/8/8/8/8/8/8/R3K3 w - - 99 80")
    fifty.play("Ra2")
    assert fifty.outcome() == ch.Outcome("1/2-1/2", "fifty moves")
    repeated = ch.Game()
    for move in ["Nf3", "Nf6", "Ng1", "Ng8", "Nf3", "Nf6", "Ng1", "Ng8"]:
        repeated.play(move)
    assert repeated.repeated() == 3 and repeated.outcome() == ch.Outcome("1/2-1/2", "repetition")
    assert ch.Game(["e2e4"]).outcome() is None


def test_a_fallen_flag_loses_unless_the_other_cannot_mate():
    assert ch.lost_on_time("w", ch.Position.start()) == ch.Outcome("0-1", "time")
    bare = ch.Position.from_fen("4k3/8/8/8/8/8/8/Q3K3 w - - 0 1")
    # White's flag fell; black has only its king: a draw.
    assert ch.lost_on_time("w", bare) == ch.Outcome("1/2-1/2", "time")
    assert ch.lost_on_time("b", bare) == ch.Outcome("1-0", "time")


def test_the_clock():
    now = dt.datetime(2026, 11, 20, 12, 0, 0, tzinfo=dt.UTC)
    assert ch.time_left({}, now) is None
    fields = {"clock": 300, "moves": ["e2e4", "e7e5"], "white_left": 290_000, "black_left": 280_000}
    # Not running until there is a turn_at.
    assert ch.time_left(fields, now) == {"w": 290_000, "b": 280_000}
    fields["turn_at"] = (now - dt.timedelta(seconds=30)).isoformat()
    assert ch.time_left(fields, now) == {"w": 260_000, "b": 280_000}
    fields["turn_at"] = "2026-11-20T11:00:00Z"
    assert ch.time_left(fields, now)["w"] == 0
    # Over: the clock stands.
    assert ch.time_left({**fields, "result": "0-1"}, now)["w"] == 290_000
    assert ch.time_left({"clock": 600, "moves": []}, now) == {"w": 600_000, "b": 600_000}
    assert ch.clock_text(300_000) == "5:00"
    assert ch.clock_text(61_000) == "1:01"
    assert ch.clock_text(7_350) == "0:07.3"
    assert ch.clock_text(3_600_000) == "1:00:00"
    assert ch.said("1-0", "checkmate") == "White won by checkmate"
    assert ch.said("1/2-1/2", "repetition") == "Drawn by repetition"


def test_the_sandbox_gives_quill_code_the_rules():
    assert "chess.py" in SDK_FILES


# -- the manifest ----------------------------------------------------------------------
def _plan(tmp_path: Path, edit=None) -> dict:
    folder = tmp_path / "quill-chessboard"
    shutil.copytree(CHESSBOARD, folder)
    if edit is not None:
        manifest = folder / "quill.toml"
        text = manifest.read_text(encoding="utf-8")
        manifest.write_text(edit(text), encoding="utf-8")
    registry = QuillRegistry(tmp_path / "quills", tmp_path / "datamodels")
    return registry.plan(folder, QUILL_CATALOG / "datamodels")


def test_the_fixture_is_a_chess_board(tmp_path):
    plan = _plan(tmp_path)
    (screen,) = plan["screens"]
    assert screen["kit"] == "chess" and screen["play"] == "play" and screen["start"] == "start"
    assert tomllib.loads((CHESSBOARD / "quill.toml").read_text())["quill"]["category"] == "games"


@pytest.mark.parametrize(
    ("edit", "said"),
    [
        (lambda t: t.replace('play = "play"\n', ""), "play names one of its actions"),
        (lambda t: t.replace('start = "start"\n', ""), "start names one of its actions"),
        (lambda t: t.replace('play = "play"', 'play = "start"'), "play names one of its actions"),
        (lambda t: t.replace('move = { kind = "string", required = true }', 'word = "string"'), "with a field move"),
        (lambda t: t.replace("opponent = {", "against = {"), "with a field opponent"),
    ],
)
def test_a_chess_screen_without_its_actions_is_refused(tmp_path, edit, said):
    with pytest.raises(QuillError, match=said):
        _plan(tmp_path, edit)


def test_a_game_with_a_field_of_the_wrong_kind_is_refused(tmp_path):
    folder = tmp_path / "quill-chessboard"
    shutil.copytree(CHESSBOARD, folder)
    game = folder / "datamodels" / "game.toml"
    game.write_text(game.read_text().replace('moves = { kind = "json" }', 'moves = { kind = "string" }'))
    registry = QuillRegistry(tmp_path / "quills", tmp_path / "datamodels")
    with pytest.raises(QuillError, match="'moves' is a string; it wants json"):
        registry.plan(folder, QUILL_CATALOG / "datamodels")
