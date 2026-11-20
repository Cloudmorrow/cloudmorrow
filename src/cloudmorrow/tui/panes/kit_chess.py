"""The kit's `chess` in the terminal: the games, then one board (docs/CHESS.md).

It opens on the games, the one moved in last first, each with whom it is
against, how long each side has, and how it stands — Your move, Sara to
move, You won by checkmate. New asks whom against (the screen's computers,
then the people on the cloud), how long and which colour, and presses the
screen's `start` action.

A game opens its board: green and cream squares seen from above, the
person's own side at the foot (turned round when they play black), the last
move lit and a king in check marked. The other side's clock is above the
board and the person's below it, ticking each second while it runs; when the
side to move's reaches nothing, the flag is claimed (`play` with `time`)
once. The moves are beside it, numbered as a score sheet.

A move is typed into the box under the board (m goes there, escape back) — as a person writes it
(`Nf3`, `O-O`, `exd5`, `e8=Q`) or as a program does (`g1f3`) — or made by
clicking a piece and then where it goes, the squares it may go to dotted.
Either way it is the screen's `play` action that keeps it: the Quill's code
checks it, and a computer answers there. r resigns, d offers a draw or takes
the one offered. The open game is read again every few seconds, so the
other side's move arrives by itself.
"""

from __future__ import annotations

from rich.text import Text
from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, ContentSwitcher, DataTable, Input, Label, RadioButton, RadioSet, Static

from cloudmorrow.client import chess as cc
from cloudmorrow.client.api import ApiError
from cloudmorrow.quill import chess as ch
from cloudmorrow.tui.panes.kit import KitPane
from cloudmorrow.tui.quill_actions import run_action
from cloudmorrow.tui.screens.modals import ConfirmModal, Modal
from cloudmorrow.tui.theme import ACCENT, BAD, GOOD, MUTED
from cloudmorrow.tui.widgets.toolbar import Action
from cloudmorrow.tui.words import escape, plural

# The board's colours: a green and a cream, the last move lit, a check marked.
LIGHT = "#ECEBD2"
DARK = "#7A9A57"
LIGHT_LIT = "#F3EC8C"
DARK_LIT = "#BDCB55"
CHECKED = "#D9534F"
PICKED = "#E8C547"
TAKES = "#E39B7B"
INK = "#1F1F1F"
# A piece as a printed diagram has it: white's hollow, black's filled, both in ink.
WHITE_GLYPH = {"K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙"}
BLACK_GLYPH = {"k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟"}
# How often the clocks are drawn, and the open game read again.
TICK_SECONDS = 0.25
POLL_SECONDS = 3.0

IN_LIST = frozenset({"new_record", "open", "delete_record", "refresh"})
IN_BOARD = frozenset({"back", "new_record", "resign", "draw", "refresh"})


def glyph(piece: str) -> str:
    return WHITE_GLYPH.get(piece) or BLACK_GLYPH.get(piece) or " "


def board_text(
    position: ch.Position,
    *,
    flip: bool = False,
    last: ch.Move | None = None,
    picked: int = -1,
    targets: frozenset[int] = frozenset(),
    cell: tuple[int, int] = (6, 3),
) -> Text:
    """The board, *cell* columns by rows a square, with the ranks down the left and the files under it."""
    width, height = cell
    lit = {last.frm, last.to} if last else set()
    king = position.king(position.turn) if position.in_check() else -1
    ranks = list(range(8)) if flip else list(range(7, -1, -1))
    files = list(range(7, -1, -1)) if flip else list(range(8))
    out = Text(no_wrap=True)
    for r in ranks:
        for line in range(height):
            middle = line == height // 2
            out.append(f"{r + 1} " if middle else "  ", style=MUTED)
            for f in files:
                sq = r * 8 + f
                light = (r + f) % 2 == 1
                ground = (LIGHT_LIT if light else DARK_LIT) if sq in lit else (LIGHT if light else DARK)
                if sq == king:
                    ground = CHECKED
                if sq == picked:
                    ground = PICKED
                piece = position.board[sq]
                mark = " "
                if middle and piece:
                    mark = glyph(piece)
                elif middle and sq in targets:
                    mark = "•"
                left = (width - 1) // 2
                cellout = " " * left + mark + " " * (width - left - 1)
                style = f"bold {INK} on {ground}"
                if middle and not piece and sq in targets:
                    style = f"{'#5C7A3E' if light else '#43592C'} on {ground}"
                elif middle and piece and sq in targets:
                    style = f"bold {INK} on {TAKES}"
                out.append(cellout, style=style)
            out.append("\n")
    out.append("  ", style=MUTED)
    for f in files:
        left = (width - 1) // 2
        out.append(" " * left + ch.FILES[f] + " " * (width - left - 1), style=MUTED)
    return out


class BoardView(Static):
    """The board, which tells the pane which square was clicked."""

    can_focus = True

    class Clicked(Message):
        def __init__(self, square: int) -> None:
            super().__init__()
            self.square = square

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.cell = (6, 3)
        self.flip = False

    def on_click(self, event: events.Click) -> None:
        width, height = self.cell
        col = (event.x - 2) // width
        row = event.y // height
        if not (0 <= col < 8 and 0 <= row < 8) or event.x < 2:
            return
        f = 7 - col if self.flip else col
        r = row if self.flip else 7 - row
        self.post_message(self.Clicked(r * 8 + f))


class NewGameModal(Modal[dict | None]):
    """Whom against, how long, which colour. Dismisses with the start action's fields, or None."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        opponents: list[tuple[str, str]],
        clocks: list[tuple[str, str]],
        colours: list[tuple[str, str]],
        *,
        clock: str = "",
        colour: str = "",
    ) -> None:
        super().__init__()
        self.opponents = opponents
        self.clocks = clocks
        self.colours = colours
        self.clock = clock
        self.colour = colour

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal modal-wide", id="cs-new"):
            yield Label("New game", classes="modal-title")
            yield Static(f"[{MUTED}]Against[/]", classes="modal-detail")
            with VerticalScroll(id="cs-new-who-box"):
                with RadioSet(id="cs-new-who"):
                    for i, (_value, label) in enumerate(self.opponents):
                        yield RadioButton(label, value=i == 0)
            if self.clocks:
                yield Static(f"[{MUTED}]Time[/]", classes="modal-detail")
                with RadioSet(id="cs-new-clock"):
                    for value, label in self.clocks:
                        yield RadioButton(label, value=value == (self.clock or self.clocks[0][0]))
            if self.colours:
                yield Static(f"[{MUTED}]You play[/]", classes="modal-detail")
                with RadioSet(id="cs-new-colour"):
                    for value, label in self.colours:
                        yield RadioButton(label, value=value == (self.colour or self.colours[0][0]))
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Start", id="start", variant="primary", disabled=not self.opponents)

    def on_mount(self) -> None:
        self.query_one("#cs-new-who", RadioSet).focus()

    def picked(self) -> dict:
        def value(selector: str, choices: list[tuple[str, str]]) -> str | None:
            found = self.query(selector)
            if not found or not choices:
                return None
            index = found.first(RadioSet).pressed_index
            return choices[max(0, index)][0]

        fields = {"opponent": value("#cs-new-who", self.opponents) or ""}
        clock = value("#cs-new-clock", self.clocks)
        if clock is not None:
            fields["clock"] = clock
        colour = value("#cs-new-colour", self.colours)
        if colour is not None:
            fields["colour"] = colour
        return fields

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "start" and self.opponents:
            self.dismiss(self.picked())
        else:
            self.dismiss(None)


class ChessPane(KitPane):
    """The games; then one board, played on."""

    BINDINGS = [
        *KitPane.BINDINGS,
        Binding("n", "fire('new_record')", "New game", show=False),
        Binding("escape", "fire('back')", "Games", show=False),
        Binding("r", "fire('resign')", "Resign", show=False),
        Binding("d", "fire('draw')", "Draw", show=False),
        Binding("m", "type_move", "Type a move", show=False),
        Binding("f5", "fire('refresh')", "Refresh", show=False),
    ]
    WRITING = KitPane.WRITING | {"resign", "draw"}

    DEFAULT_CSS = """
    ChessPane {
        #cs-views { height: 1fr; }
        #cs-list, #cs-game { height: 1fr; }
        #cs-games { height: 1fr; margin: 1 2 0 2; }
        #cs-head { height: 1; padding: 0 2; }
        #cs-play { height: 1fr; }
        #cs-left { width: auto; padding: 0 1 0 2; }
        #cs-board { width: auto; height: auto; }
        .cs-clock { height: 1; }
        #cs-move { width: 30; margin-top: 1; }
        #cs-right { width: 1fr; padding: 0 1; border-left: solid $line; }
        #cs-moves { height: 1fr; }
        .cs-title { height: 1; color: $muted; }
    }
    """

    def __init__(self, quill: dict, screen: dict, **kwargs) -> None:
        super().__init__(quill, screen, **kwargs)
        self.chess = cc.Chess(None, quill, screen)
        self.games: list[dict] = []
        # The game open on the board, and the rules' view of it.
        self.game: dict | None = None
        self.board = ch.Game()
        # A piece clicked, waiting for where it goes.
        self.picked = -1
        # What a Quill's `go` asked for: `game` opens that board.
        self.params: dict = {}
        # The flag claimed for this game at this many moves, so it is claimed once.
        self._claimed: tuple[str, int] | None = None
        self._pressing = False
        actions = [
            Action("new_record", "New game", "n", variant="primary"),
            Action("open", "Open", "enter"),
            Action("back", "Games", "esc"),
            Action("draw", "Draw", "d", hint="Offer a draw, or take the one offered"),
            Action("resign", "Resign", "r"),
            Action("delete_record", "Delete", "del"),
            Action("refresh", "Refresh", "f5"),
        ]
        self.ACTIONS = self.offer(actions)

    # -- where we are -------------------------------------------------------------------
    @property
    def playing(self) -> bool:
        return self.game is not None

    @property
    def fields(self) -> dict:
        return (self.game or {}).get("fields") or {}

    @property
    def side(self) -> str:
        return cc.side_of(self.fields, self.me)

    def fire(self, name: str) -> None:
        if name not in (IN_BOARD if self.playing else IN_LIST):
            return
        super().fire(name)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "fire" and parameters:
            if str(parameters[0]) not in (IN_BOARD if self.playing else IN_LIST):
                return False
        return super().check_action(action, parameters)

    # -- layout ---------------------------------------------------------------------------
    def content(self) -> ComposeResult:
        with ContentSwitcher(id="cs-views", initial="cs-list"):
            with Vertical(id="cs-list"):
                yield DataTable(id="cs-games", cursor_type="row", zebra_stripes=True)
            with Vertical(id="cs-game"):
                yield Static("", id="cs-head")
                with Horizontal(id="cs-play"):
                    with Vertical(id="cs-left"):
                        yield Static("", id="cs-top", classes="cs-clock")
                        yield BoardView("", id="cs-board")
                        yield Static("", id="cs-bottom", classes="cs-clock")
                        yield Input(placeholder="Your move: Nf3, O-O, e2e4", id="cs-move")
                    with Vertical(id="cs-right"):
                        yield Static("Moves", classes="cs-title")
                        yield Static("", id="cs-moves")

    def on_mount(self) -> None:
        self.query_one("#cs-games", DataTable).add_columns("AGAINST", "TIME", "MOVES", "STATUS")
        self._tick = self.set_interval(TICK_SECONDS, self.tick, pause=True)
        self._poll = self.set_interval(POLL_SECONDS, self.poll, pause=True)

    def card_status(self) -> tuple[str, str] | None:
        if not self.loaded:
            return None
        mine = [g for g in self.games if cc.mine_to_move(g.get("fields") or {}, self.me)]
        if mine:
            return "news", f"{len(mine)} your move"
        return "ok", plural(len(self.games), "game")

    def status_detail(self) -> str:
        if self.playing:
            return f"[{MUTED}]{escape(cc.status(self.fields, self.me, self.board))}[/]"
        return f"[{MUTED}]{plural(len(self.games), 'game')}[/]"

    def reload(self) -> None:
        self.chess.api = self.api
        if self.api is None:
            return
        wanted = str(self.params.pop("game", "") or "")
        if wanted:
            self.open_game({"id": wanted, "fields": {}})
            return
        if self.playing:
            self.load_game()
        else:
            self.load_games()

    def _show(self, view: str) -> None:
        self.query_one("#cs-views", ContentSwitcher).current = view
        for button in self.query(".toolbar Button"):
            action = (button.id or "")[len("do-") :]
            button.display = action in (IN_BOARD if view == "cs-game" else IN_LIST)
        if view == "cs-game":
            self._tick.resume()
            self._poll.resume()
        else:
            self._tick.pause()
            self._poll.pause()
        self.refresh_bindings()

    # -- the games ------------------------------------------------------------------------------
    @work(exclusive=True, group="chess")
    async def load_games(self, keep: str = "") -> None:
        try:
            self.games = await self.chess.games()
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        self.loaded = True
        self.draw_games(keep)
        self.status("" if self.games else "No games yet — n starts one.", note=True)

    def draw_games(self, keep: str = "") -> None:
        self._show("cs-list")
        table = self.query_one("#cs-games", DataTable)
        row = table.cursor_row
        table.clear()
        for record in self.games:
            f = record.get("fields") or {}
            said = cc.status(f, self.me)
            tone = ACCENT if said == "Your move" or said.endswith("offers a draw") else MUTED
            if said.startswith("You won"):
                tone = GOOD
            table.add_row(
                Text(cc.opponent(f, self.me), style="bold"),
                Text(cc.time_said(f), style=MUTED),
                Text(str((len(cc.moves_of(f)) + 1) // 2), style=MUTED),
                Text(said, style=tone),
                key=record["id"],
            )
        if keep:
            row = next((i for i, r in enumerate(self.games) if r["id"] == keep), row)
        if self.games:
            table.move_cursor(row=min(max(row, 0), len(self.games) - 1))
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        if event.data_table.id == "cs-games":
            self.act_open()

    def act_open(self) -> None:
        table = self.query_one("#cs-games", DataTable)
        if not self.games or not 0 <= table.cursor_row < len(self.games):
            return
        self.open_game(self.games[table.cursor_row])

    def open_game(self, game: dict) -> None:
        self.game = game
        self.board = cc.game_of(game.get("fields") or {})
        self.picked = -1
        self._show("cs-game")
        self.load_game()
        self.call_after_refresh(lambda: self.query_one("#cs-board", BoardView).focus())

    def action_type_move(self) -> None:
        """m: to the box a move is typed in."""
        box = self.query_one("#cs-move", Input)
        if self.playing and not box.disabled:
            box.focus()

    def act_back(self) -> None:
        box = self.query_one("#cs-move", Input)
        if box.has_focus:
            # Out of the box first: r and d are keys again.
            self.query_one("#cs-board", BoardView).focus()
            return
        keep = (self.game or {}).get("id", "")
        self.game = None
        self.picked = -1
        self.load_games(keep)

    def act_refresh(self) -> None:
        self.reload()

    def act_delete_record(self) -> None:
        table = self.query_one("#cs-games", DataTable)
        if not self.playing and 0 <= table.cursor_row < len(self.games):
            self.delete_game(self.games[table.cursor_row])

    @work(group="ui")
    async def delete_game(self, game: dict) -> None:
        if await self.confirm_delete(game):
            self.status("Deleted the game.")
            self.load_games()

    # -- one game -----------------------------------------------------------------------------------
    @work(exclusive=True, group="chess")
    async def load_game(self) -> None:
        if await self._fetch_game():
            self.draw_game()

    async def _fetch_game(self) -> bool:
        assert self.game is not None
        try:
            self.game = await self.chess.game(self.game["id"])
        except ApiError as exc:
            if exc.status_code == 404:
                self.game = None
                self.load_games()
                self.status(str(exc), error=True)
                return False
            await self.went_wrong(exc)
            return False
        self.board = cc.game_of(self.fields)
        return True

    def _cell(self) -> tuple[int, int]:
        room = self.size.height
        return (6, 3) if room == 0 or room >= 34 else (4, 2)

    def draw_game(self) -> None:
        if self.game is None:
            return
        self._show("cs-game")
        f = self.fields
        head = [
            f"[b {ACCENT}]{escape(cc.opponent(f, self.me))}[/]",
            f"[{MUTED}]{cc.time_said(f)}[/]",
        ]
        said = cc.status(f, self.me, self.board)
        tone = GOOD if said.startswith("You won") else BAD if f.get("result") and " won" in said else ACCENT
        head.append(f"[{tone}]{escape(said)}[/]")
        if f.get("draw") and f.get("draw") != self.me and self.side and not f.get("result"):
            head.append(f"[{MUTED}]d takes it[/]")
        self.query_one("#cs-head", Static).update("   ".join(head))
        self.draw_board()
        self.draw_clocks()
        sheet = cc.numbered(self.board)
        self.query_one("#cs-moves", Static).update(
            "\n".join(escape(line) for line in sheet) if sheet else f"[{MUTED}]No moves yet.[/]"
        )
        box = self.query_one("#cs-move", Input)
        box.disabled = not self.side or bool(f.get("result")) or not self.writes

    def draw_board(self) -> None:
        view = self.query_one("#cs-board", BoardView)
        view.cell = self._cell()
        view.flip = self.side == "b"
        targets = (
            frozenset(m.to for m in self.board.legal() if m.frm == self.picked) if self.picked >= 0 else frozenset()
        )
        view.update(
            board_text(
                self.board.position,
                flip=view.flip,
                last=self.board.moves[-1] if self.board.moves else None,
                picked=self.picked,
                targets=targets,
                cell=view.cell,
            )
        )

    def draw_clocks(self) -> None:
        f = self.fields
        mine = self.side or "w"
        theirs = "b" if mine == "w" else "w"
        left = ch.time_left(f)
        running = "" if f.get("result") or not f.get("turn_at") else self.board.turn

        def line(side: str) -> str:
            name = escape(cc.name_of(f, side))
            if left is None:
                return f"[b]{name}[/]"
            text = ch.clock_text(left[side])
            tone = BAD if left[side] < 20_000 and running == side else ACCENT if running == side else MUTED
            return f"[b]{name}[/]  [{tone} b]{text}[/]"

        self.query_one("#cs-top", Static).update(line(theirs))
        self.query_one("#cs-bottom", Static).update(line(mine))

    def tick(self) -> None:
        if self.game is None:
            return
        self.draw_clocks()
        f = self.fields
        left = ch.time_left(f)
        if left is None or f.get("result") or not f.get("turn_at") or not self.side:
            return
        turn = self.board.turn
        stamp = (self.game["id"], len(self.board.moves))
        if left[turn] <= 0 and self._claimed != stamp and not self._pressing:
            self._claimed = stamp
            self.press("time")

    def poll(self) -> None:
        if self.game is not None and not self._pressing:
            self.load_game()

    # -- moving -------------------------------------------------------------------------------------------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "cs-move":
            return
        event.stop()
        typed = event.value.strip()
        if not typed:
            return
        try:
            move = self.board.parse(typed)
        except ValueError as exc:
            self.status(str(exc), error=True)
            return
        event.input.value = ""
        self.play(move)

    def on_board_view_clicked(self, event: BoardView.Clicked) -> None:
        event.stop()
        if not self.side or self.fields.get("result") or self.board.turn != self.side:
            return
        piece = self.board.position.board[event.square]
        if self.picked >= 0:
            found = [m for m in self.board.legal() if m.frm == self.picked and m.to == event.square]
            if found:
                move = next((m for m in found if m.promote in ("", "q")), found[0])
                self.picked = -1
                self.play(move)
                return
        mine = piece and ch.colour_of(piece) == self.side
        self.picked = event.square if mine and event.square != self.picked else -1
        self.draw_board()

    def play(self, move: ch.Move) -> None:
        """Draw it at once, then have the Quill keep it."""
        if not self.side or self.board.turn != self.side:
            self.status("It is not your move.", error=True)
            return
        try:
            self.board.play(move)
        except ValueError as exc:
            self.status(str(exc), error=True)
            return
        self.draw_board()
        self.press(move.uci)

    @work(group="ui")
    async def press(self, word: str) -> None:
        action = self.chess.play_action
        if action is None or self.game is None:
            self.status("This board has no way to play.", error=True)
            return
        self._pressing = True
        try:
            await run_action(self.app, self.quill, action, record=self.game, values={"move": word}, ask=False)
        finally:
            self._pressing = False
        if self.game is not None and await self._fetch_game():
            self.draw_game()

    def act_resign(self) -> None:
        if self.playing and self.side and not self.fields.get("result"):
            self.resign()

    @work(group="ui")
    async def resign(self) -> None:
        yes = await self.app.push_screen_wait(
            ConfirmModal("Resign this game?", detail=f"[{MUTED}]It is lost.[/]", confirm_label="Resign")
        )
        if yes:
            self.press("resign")

    def act_draw(self) -> None:
        if self.playing and self.side and not self.fields.get("result"):
            self.press("draw")

    # -- a new game ------------------------------------------------------------------------------------------
    def act_new_record(self) -> None:
        if self.chess.start_action is not None:
            self.new_game()

    @work(group="ui")
    async def new_game(self) -> None:
        try:
            computers = await self.chess.computers()
            people = await self.api.people()
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        opponents: list[tuple[str, str]] = []
        for record in computers:
            f = record.get("fields") or {}
            label = str(f.get("name") or "Computer")
            if f.get("level"):
                label += f" · level {f['level']}"
            opponents.append((record["id"], label))
        for person in people:
            name = str(person.get("username") or "")
            if not name or name == self.me:
                continue
            shown = str(person.get("display_name") or person.get("name") or "")
            opponents.append((name, f"{shown} ({name})" if shown and shown != name else name))
        picked = await self.app.push_screen_wait(
            NewGameModal(
                opponents,
                self.chess.choices("clock"),
                self.chess.choices("colour"),
                clock=self.chess.default("clock"),
                colour=self.chess.default("colour"),
            )
        )
        if not picked:
            return
        await run_action(self.app, self.quill, self.chess.start_action, values=picked, ask=False)
