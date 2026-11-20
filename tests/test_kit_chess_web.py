"""The chess board in the browser: wired in, generic, and its rules the same as Python's.

The board is driven in a browser, not from here. What a test can hold is
what goes wrong quietly: the kit not drawing a screen the server installs,
a word from one Quill in the code that draws all of them, an action the
board presses that the server would refuse — and the rules in
kit_chess_rules.js, which are pure and run here under node, held to the
same counts of positions as quill/chess.py (docs/CHESS.md).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from cloudmorrow.quill.chess import Game
from cloudmorrow.server.routes.web import WEB, asset_version
from tests.conftest import QUILL_CATALOG, js_code

CHESS_JS = (WEB / "kit_chess.js").read_text(encoding="utf-8")
RULES_JS = (WEB / "kit_chess_rules.js").read_text(encoding="utf-8")
PIECES_JS = (WEB / "kit_chess_pieces.js").read_text(encoding="utf-8")
CHESS_CSS = (WEB / "kit_chess.css").read_text(encoding="utf-8")
KIT_JS = (WEB / "kit.js").read_text(encoding="utf-8")
node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


# -- wired in ------------------------------------------------------------------------
def test_the_board_is_its_own_file_registered_from_the_kit(client):
    assert 'import { renderChess } from "./kit_chess.js";' in KIT_JS
    assert "chess: renderChess" in KIT_JS and '"chess"' in KIT_JS
    assert '@import "./kit_chess.css";' in (WEB / "app.css").read_text(encoding="utf-8")
    version = asset_version()
    for name in ("kit_chess.js", "kit_chess.css", "kit_chess_rules.js", "kit_chess_pieces.js"):
        assert client.get(f"/app/{version}/{name}").status_code == 200, name


def test_nothing_in_the_board_is_named_for_one_quill():
    """Field names are the kit's (white, moves, turn_at…); datamodels and labels the screen's."""
    for source, name in ((CHESS_JS, "kit_chess.js"), (RULES_JS, "rules"), (PIECES_JS, "pieces"), (CHESS_CSS, "css")):
        body = js_code(source) if name != "css" else re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
        for word in ("chessboard.", "chess.game", "chess.computer", "Morrow", "morrow"):
            assert word not in body, f"{name} names {word!r}"


def test_it_never_opens_a_browser_window():
    assert not re.search(r"(?<![.\w])(confirm|prompt|alert)\(", js_code(CHESS_JS))


def test_it_presses_only_the_screens_two_actions_with_the_kits_fields():
    code = js_code(CHESS_JS)
    assert "s.b.play" in code and "s.b.start" in code
    for word in ('"time"', "fields: { move: uciOf(played) }", "{ opponent: chosen.opponent }"):
        assert word in code, word
    assert ".access" not in code


# -- on a server -------------------------------------------------------------------------------
@pytest.fixture()
def chessboard(client, users):
    from tests.conftest import ADMIN, token_for

    state = client.app.state.cloudmorrow
    state.quills.install(QUILL_CATALOG / "quill-chessboard", QUILL_CATALOG / "datamodels")
    from cloudmorrow.server.security import hash_password

    users.create("sara", hash_password("sara-secret-1"), display_name="Sara")
    return (
        {"Authorization": f"Bearer {token_for(client, *ADMIN)}"},
        {"Authorization": f"Bearer {token_for(client, 'sara', 'sara-secret-1')}"},
    )


def test_the_screen_the_board_draws_is_installed_whole(client, chessboard):
    me, _ = chessboard
    quill = next(q for q in client.get("/api/quills", headers=me).json() if q["id"] == "chessboard")
    (screen,) = quill["screens"]
    assert (screen["kit"], screen["play"], screen["start"], screen["computers"]) == (
        "chess",
        "play",
        "start",
        "chessboard.computer",
    )
    # The computers come with the screen, as the board's new-game sheet lists them.
    assert {"chessboard.game", "chessboard.computer"} <= set(quill["models"])


def test_a_game_between_two_people_as_the_board_plays_it(client, chessboard):
    me, sara = chessboard
    started = client.post(
        "/api/quills/chessboard/actions/start",
        json={"fields": {"opponent": "sara", "clock": "300", "colour": "white"}},
        headers=me,
    )
    assert started.status_code == 200, started.text
    (went,) = [e for e in started.json()["effects"] if e["effect"] == "go"]
    game = went["params"]["game"]
    seen = client.get(f"/api/records/chessboard.game/{game}", headers=sara).json()["fields"]
    assert (seen["white"], seen["black"], seen["clock"], seen["white_left"]) == ("bram", "sara", 300, 300_000)
    for who, move in ((me, "e2e4"), (sara, "e7e5"), (me, "g1f3")):
        played = client.post(
            "/api/quills/chessboard/actions/play", json={"record": game, "fields": {"move": move}}, headers=who
        )
        assert played.status_code == 200, played.text
    moves = client.get(f"/api/records/chessboard.game/{game}", headers=me).json()["fields"]["moves"]
    assert moves == ["e2e4", "e7e5", "g1f3"] and Game(moves).sans == ["e4", "e5", "Nf3"]


# -- the rules, under node --------------------------------------------------------------------
RUNNER = """
import { Position, Game, clockText, timeLeft, saidOf } from "%s";
const calls = JSON.parse(process.argv[2]);
const perft = (p, d) => {
  let n = 0;
  for (const m of p.legal()) n += d > 1 ? perft(p.apply(m), d - 1) : 1;
  return n;
};
const out = calls.map(([name, ...args]) => {
  if (name === "perft") return perft(Position.fromFen(args[0]), args[1]);
  if (name === "sans") return new Game(args[0]).sans;
  if (name === "outcome") return new Game(args[0]).outcome();
  if (name === "fen") return new Game(args[0]).position.fen();
  if (name === "clockText") return clockText(args[0]);
  if (name === "timeLeft") return timeLeft(args[0], args[1]);
  if (name === "saidOf") return saidOf(args[0], args[1]);
  throw new Error(name);
});
console.log(JSON.stringify(out));
"""


def run(tmp_path, *calls):
    script = tmp_path / "rules.mjs"
    script.write_text(RUNNER % (WEB / "kit_chess_rules.js").as_uri(), encoding="utf-8")
    done = subprocess.run(["node", str(script), json.dumps(calls)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


PERFT = (
    ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 3, 8902),
    ("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 2, 2039),
    ("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 3, 2812),
    ("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", 3, 9467),
    ("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", 2, 1486),
)


@node
def test_the_browser_counts_the_positions_the_rules_book_does(tmp_path):
    got = run(tmp_path, *(["perft", fen, depth] for fen, depth, _ in PERFT))
    assert got == [want for _fen, _depth, want in PERFT]


@node
def test_the_browser_writes_and_ends_games_as_python_does(tmp_path):
    games = (
        ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4", "g8f6", "e1g1", "f8e7"],
        ["f2f3", "e7e5", "g2g4", "d8h4"],
        ["a2a4", "h7h6", "a4a5", "h6h5", "a5a6", "h5h4", "a6b7", "e7e6", "b7a8q"],
        ["g1f3", "g8f6", "f3g1", "f6g8", "g1f3", "g8f6", "f3g1", "f6g8"],
    )
    calls = [c for moves in games for c in (["sans", moves], ["fen", moves], ["outcome", moves])]
    got = run(tmp_path, *calls)
    for i, moves in enumerate(games):
        game = Game(moves)
        sans, fen, outcome = got[3 * i : 3 * i + 3]
        assert sans == game.sans and fen == game.position.fen()
        ended = game.outcome()
        assert outcome == (ended._asdict() if ended else None)


@node
def test_the_browser_clock_is_pythons(tmp_path):
    fields = {"clock": 300, "moves": ["e2e4", "e7e5"], "white_left": 290_000, "turn_at": "2026-11-20T10:00:00Z"}
    now = 1_795_168_805_000  # 2026-11-20T10:00:05Z, in ms
    left, short, long, said = run(
        tmp_path, ["timeLeft", fields, now], ["clockText", 7350], ["clockText", 61_000], ["saidOf", "0-1", "time"]
    )
    assert left == {"w": 285_000, "b": 300_000}
    assert (short, long, said) == ("0:07.3", "1:01", "Black won on time")
