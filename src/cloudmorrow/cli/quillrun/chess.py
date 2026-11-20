"""A `chess` board: the games, one of them shown, a move played.

A game is named by the start of its id or its name; an opponent by their
username, or a computer's name (Morrow). A move is typed as a person writes
it (`Nf3`, `O-O`, `exd5`) or as a program does (`g1f3`), and goes to the
screen's `play` action: the Quill's code checks it and keeps it, and a
computer answers there. New is the screen's `start` action.
"""

from __future__ import annotations

import json

from rich.markup import escape
from rich.table import Table

# quillrun.out, .console and .emit, looked up as they print: see screen.py.
from cloudmorrow.cli import quillrun
from cloudmorrow.cli.common import fail
from cloudmorrow.cli.quillrun.actions import _effects
from cloudmorrow.cli.quillrun.screen import Screen, _find, _short
from cloudmorrow.client import chess as cc
from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.console import TITLE
from cloudmorrow.quill import chess as ch

WORDS = ("new", "resign", "draw")


async def _me(api: CloudmorrowClient) -> str:
    return str((await api.me()).get("username") or "")


def _clocks_said(fields: dict) -> list[str]:
    left = ch.time_left(fields)
    if left is None:
        return []
    return [
        f"{cc.name_of(fields, 'w')} {ch.clock_text(left['w'])}",
        f"{cc.name_of(fields, 'b')} {ch.clock_text(left['b'])}",
    ]


async def _press(api: CloudmorrowClient, board: cc.Chess, action: dict | None, record: str, fields: dict, plain: bool):
    if action is None:
        fail(f"{board.quill['id']} has no action for that on this screen")
    effects = await api.quill_action(board.quill["id"], action["id"], record=record, fields=fields)
    errors = [e for e in effects if e.get("effect") == "error"]
    if errors and not plain:
        fail(str(errors[0].get("text") or "it was refused"))
    await _effects(api, board.quill, [e for e in effects if e.get("effect") != "go"], record, plain)
    return effects


async def _show(api: CloudmorrowClient, board: cc.Chess, record: dict, me: str, plain: bool) -> None:
    fields = record.get("fields") or {}
    if plain:
        quillrun.emit(json.dumps(record, indent=2) + "\n")
        return
    game = cc.game_of(fields)
    side = cc.side_of(fields, me)
    last = game.moves[-1] if game.moves else None
    name = escape(str(fields.get(board.title) or record["id"]))
    head = f"[b]{name}[/] [dim]{cc.time_said(fields)} · {_short(record['id'])}[/]"
    quillrun.console.print(head)
    for line in cc.board_lines(game.position, flip=side == "b", last=last):
        quillrun.console.print(escape(line), highlight=False)
    clocks = _clocks_said(fields)
    if clocks:
        quillrun.console.print("[dim]clock[/] " + escape("   ".join(clocks)))
    sheet = cc.numbered(game)
    if sheet:
        quillrun.console.print("[dim]moves[/] " + escape("  ".join(sheet)))
    quillrun.console.print(f"[b]{escape(cc.status(fields, me, game))}[/]")


async def _act_chess(
    api: CloudmorrowClient, screen: Screen, action: str, args: list[str], plain: bool, timing: dict
) -> None:
    board = cc.Chess(api, screen.quill, screen.spec)
    command = f"cm {screen.quill['id']}"
    me = await _me(api)
    if action == "list":
        games = await board.games()
        if plain:
            quillrun.emit(json.dumps(games, indent=2) + "\n")
            return
        table = Table(title=screen.spec.get("label") or screen.quill["name"], title_style=TITLE)
        for column in ("id", "against", "time", "moves", "status"):
            table.add_column(column, style="dim" if column == "id" else None)
        for record in games:
            f = record.get("fields") or {}
            table.add_row(
                _short(record["id"]),
                escape(cc.opponent(f, me)),
                cc.time_said(f),
                str((len(cc.moves_of(f)) + 1) // 2),
                escape(cc.status(f, me)),
            )
        quillrun.out.print(table)
        return
    if action == "new":
        if not args:
            fail(f"against whom? {command} new <person or Morrow> [--clock 5m] [--colour white]")
        wanted = args[0]
        computers = await board.computers()
        found = next(
            (
                c
                for c in computers
                if c["id"] == wanted or str((c.get("fields") or {}).get("name") or "").casefold() == wanted.casefold()
            ),
            None,
        )
        fields = {"opponent": found["id"] if found else wanted}
        clock = timing.get("clock")
        if clock is not None and str(clock) != "":
            try:
                fields["clock"] = board.clock_value(str(clock))
            except ValueError as exc:
                fail(str(exc))
        elif board.choices("clock"):
            fields["clock"] = board.default("clock") or board.choices("clock")[0][0]
        colour = str(timing.get("colour") or "").strip().lower()
        if colour:
            offered = [v for v, _ in board.choices("colour")]
            if offered and colour not in offered:
                fail("--colour is " + ", ".join(offered))
            fields["colour"] = colour
        elif board.choices("colour"):
            fields["colour"] = board.default("colour") or board.choices("colour")[0][0]
        effects = await _press(api, board, board.start_action, "", fields, plain)
        if plain:
            return
        made = next((e for e in effects if e.get("effect") == "go"), None)
        game_id = str(((made or {}).get("params") or {}).get("game") or "")
        if game_id:
            await _show(api, board, await board.game(game_id), me, plain)
        return
    if not args:
        fail(f"which game? {command} {action} <game> …")
    record = _find(await board.games(), args[0], board.title)
    if action == "show":
        await _show(api, board, record, me, plain)
        return
    if action in ("move", "resign", "draw"):
        if action == "move":
            if len(args) < 2:
                fail(f"which move? {command} move <game> Nf3")
            word = " ".join(args[1:])
            # Checked here first, so a typo is said without a round trip.
            game = cc.game_of(record.get("fields") or {})
            try:
                game.parse(word)
            except ValueError as exc:
                fail(str(exc))
        else:
            word = action
        await _press(api, board, board.play_action, record["id"], {"move": word}, plain)
        if not plain:
            await _show(api, board, await board.game(record["id"]), me, plain)
        return
    fail(f"{action!r}: a chess board does list, show, new, move, resign and draw")
