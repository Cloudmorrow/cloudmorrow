"""Tasks: pick a board from the strip, and work the three lanes across it.

The boards are tabs above the board itself, with a `＋` at the end that makes
another — so which boards you have is visible at a glance rather than one
click down, and switching between them is one click rather than two. Everyone
has at least one, named after them until it is renamed.

Below the strip the board: ToDo, Doing, Done, left to right in the direction
work travels. New tasks start in ToDo. Done empties itself after a week, and
every card in it says how long it has left.

Boards are yours, like notes. Nothing selected elsewhere has anything to do
with what is on this tab.
"""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Tab, Tabs

from cloudmorrow.client.api import ApiError, AuthError
from cloudmorrow.server.tasks import DONE, LANES, TODO
from cloudmorrow.tui.panes.base import Pane
from cloudmorrow.tui.screens.modals import ConfirmModal, PromptModal, TaskModal
from cloudmorrow.tui.theme import MUTED
from cloudmorrow.tui.widgets.board import Lane, TaskCard, lane_under, neighbour_lane
from cloudmorrow.tui.widgets.toolbar import Action

# A board's tab is `board-<slug>`; `new` is a reserved slug, so no board can
# ever claim the id the ＋ tab uses.
TAB_PREFIX = "board-"
NEW_BOARD_TAB = "board-new"


def board_tab_id(slug: str) -> str:
    return f"{TAB_PREFIX}{slug}"


class TasksPane(Pane):
    """The board, the strip of boards above it, and everything you can do to a card."""

    TAB_LABEL = "Tasks"
    TAB_KEY = "f2"
    BINDINGS = [
        ("ctrl+n", "fire('new_task')", "New task"),
        ("ctrl+b", "fire('new_board')", "New board"),
        ("delete", "fire('delete_task')", "Delete task"),
    ]
    ACTIONS = (
        Action("new_task", "New task", "^n", variant="primary", hint="Starts in ToDo"),
        Action("new_board", "New board", "^b"),
        Action("rename_board", "Rename board", "r"),
        Action("delete_board", "Delete board", "", hint="The board and every task on it"),
    )

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.boards: list[dict] = []
        self.board: str | None = None
        self.tasks: list[dict] = []
        # What the strip is showing, so it is only rebuilt when it is wrong.
        self._drawn: list[tuple[str, str]] = []

    # -- layout ------------------------------------------------------------
    def content(self) -> ComposeResult:
        with Horizontal(id="board-bar"):
            yield Tabs(id="board-nav")
        with Horizontal(id="lanes"):
            for lane in LANES:
                yield Lane(lane, id=f"lane-{lane}", classes="lane")

    def lane_widget(self, lane: str) -> Lane:
        return self.query_one(f"#lane-{lane}", Lane)

    def on_show(self) -> None:
        self.reload()

    # -- loading -----------------------------------------------------------
    @work(exclusive=True, group="tasks")
    async def reload(self) -> None:
        client = self.api
        if client is None:
            return
        try:
            self.boards = await client.boards()
        except AuthError:
            await self.app.sign_out(message="Session expired — sign in again.")
            return
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        slugs = {board["slug"] for board in self.boards}
        if self.board not in slugs:
            # The board went, or there was never one selected.
            self.board = self.boards[0]["slug"] if self.boards else None
        await self.draw_strip()
        await self.load_tasks()

    async def draw_strip(self) -> None:
        """One tab per board, then the ＋ that makes another.

        Rebuilding a Tabs activates whichever tab lands first, and moving the
        active one activates that — both of which would read as you choosing a
        board. Neither is, so the strip is redrawn with those muted and the
        loading is done here, in the order this method decides.
        """
        strip = self.query_one("#board-nav", Tabs)
        wanted = [(board["slug"], board["title"]) for board in self.boards]
        with self.prevent(Tabs.TabActivated, Tabs.Cleared):
            if wanted != self._drawn:
                await strip.clear()
                for slug, title in wanted:
                    await strip.add_tab(Tab(title, id=board_tab_id(slug)))
                await strip.add_tab(Tab("＋", id=NEW_BOARD_TAB))
                self._drawn = wanted
            if self.board is not None:
                strip.active = board_tab_id(self.board)

    def _restore_strip(self) -> None:
        """Put the highlight back on the board you are actually looking at."""
        strip = self.query_one("#board-nav", Tabs)
        with self.prevent(Tabs.TabActivated, Tabs.Cleared):
            strip.active = board_tab_id(self.board) if self.board else ""

    async def load_tasks(self) -> None:
        """Fill the lanes from the selected board, or empty them when there is none."""
        if self.board is None:
            self.tasks = []
            for lane in LANES:
                await self.lane_widget(lane).show([])
            self.status("No boards yet — New board starts one.")
            return
        try:
            self.tasks = await self.api.tasks(self.board)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        await self.draw_lanes()
        self.status("")

    async def draw_lanes(self) -> None:
        for lane in LANES:
            await self.lane_widget(lane).show(
                [task for task in self.tasks if task["lane"] == lane]
            )

    def status_detail(self) -> str:
        if self.board is None:
            return ""
        counts = "  ".join(
            f"{lane} {sum(1 for task in self.tasks if task['lane'] == lane)}"
            for lane in LANES
        )
        return f"[{MUTED}]{counts}[/]"

    # -- the strip ---------------------------------------------------------
    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        """Handled here so it never reaches the workspace's own tab strip."""
        event.stop()
        tab_id = (event.tab.id or "") if event.tab is not None else ""
        if tab_id == NEW_BOARD_TAB:
            # ＋ is a button wearing a tab's clothes: the strip goes back where
            # it was, and the new board — if there is one — selects itself.
            self._restore_strip()
            self.new_board()
            return
        if not tab_id.startswith(TAB_PREFIX):
            return
        slug = tab_id[len(TAB_PREFIX) :]
        if slug == self.board:
            return
        self.board = slug
        self.open_board()

    @work(group="ui")
    async def open_board(self) -> None:
        await self.load_tasks()

    # -- boards ------------------------------------------------------------
    def act_new_board(self) -> None:
        self.new_board()

    @work(group="ui")
    async def new_board(self) -> None:
        title = await self.app.push_screen_wait(
            PromptModal(
                "New board",
                placeholder="Home Lab",
                detail="[dim]Three lanes, always the same three. Boards are yours.[/]",
            )
        )
        if not title:
            # Nothing made; the strip was already put back before the prompt.
            return
        try:
            board = await self.api.create_board(title)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.board = board["slug"]
        self.reload()

    def act_rename_board(self) -> None:
        self.rename_board()

    @work(group="ui")
    async def rename_board(self) -> None:
        current = self._current_board()
        if current is None:
            self.status("no board selected", error=True)
            return
        title = await self.app.push_screen_wait(
            PromptModal("Rename board", value=current["title"])
        )
        if not title:
            return
        try:
            await self.api.rename_board(current["slug"], title)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.reload()

    def act_delete_board(self) -> None:
        self.delete_board()

    @work(group="ui")
    async def delete_board(self) -> None:
        current = self._current_board()
        if current is None:
            self.status("no board selected", error=True)
            return
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(
                f"Delete the board {current['title']}?",
                detail=(
                    f"[dim]Every task on it goes too — "
                    f"{len(self.tasks)} of them. Nothing else is touched.[/]"
                ),
            )
        )
        if not confirmed:
            return
        try:
            await self.api.delete_board(current["slug"])
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.board = None
        self.reload()

    def _current_board(self) -> dict | None:
        return next(
            (board for board in self.boards if board["slug"] == self.board), None
        )

    # -- tasks -------------------------------------------------------------
    def act_new_task(self) -> None:
        self.new_task()

    @work(group="ui")
    async def new_task(self) -> None:
        if self.board is None:
            self.status("make a board first", error=True)
            return
        written = await self.app.push_screen_wait(TaskModal("New task"))
        if not written:
            return
        try:
            await self.api.create_task(
                self.board, written["title"], body=written["body"]
            )
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        await self.load_tasks()
        self.status(f"added to {TODO}")

    def on_task_card_opened(self, event: TaskCard.Opened) -> None:
        event.stop()
        self.edit_task(event.record)

    @work(group="ui")
    async def edit_task(self, task: dict) -> None:
        written = await self.app.push_screen_wait(
            TaskModal("Task", title=task["title"], body=task.get("body", ""))
        )
        if not written:
            return
        try:
            await self.api.edit_task(
                self.board, int(task["id"]), title=written["title"], body=written["body"]
            )
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        await self.load_tasks()

    def act_delete_task(self) -> None:
        card = self._focused_card()
        if card is None:
            self.status("pick a task first — click one, or tab to it", error=True)
            return
        self.delete_task(card.record)

    @work(group="ui")
    async def delete_task(self, task: dict) -> None:
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(f"Delete {task['title']}?", detail="[dim]It is not recoverable.[/]")
        )
        if not confirmed:
            return
        try:
            await self.api.delete_task(self.board, int(task["id"]))
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        await self.load_tasks()

    def _focused_card(self) -> TaskCard | None:
        focused = self.screen.focused
        return focused if isinstance(focused, TaskCard) else None

    # -- moving ------------------------------------------------------------
    def on_task_card_dragging(self, event: TaskCard.Dragging) -> None:
        """Light up the lane the card would land in, so a drop is not a guess."""
        event.stop()
        target = lane_under(self.screen, event.x, event.y)
        for lane in LANES:
            self.lane_widget(lane).set_class(
                target is not None and target.lane == lane, "-drop-target"
            )

    def on_task_card_dropped(self, event: TaskCard.Dropped) -> None:
        event.stop()
        for lane in LANES:
            self.lane_widget(lane).remove_class("-drop-target")
        target = lane_under(self.screen, event.x, event.y)
        if target is None:
            # Dropped off the board. The card stays where it was.
            return
        index = target.index_at(event.y)
        if target.lane == event.record["lane"] and index == _position_of(event.record, self.tasks):
            return
        self.move_task(event.record, target.lane, index)

    def on_task_card_shifted(self, event: TaskCard.Shifted) -> None:
        """`[` and `]`: the same move, for when the mouse is not where you are."""
        event.stop()
        lane = neighbour_lane(event.record["lane"], event.delta)
        if lane == event.record["lane"]:
            return
        self.move_task(event.record, lane, None)

    @work(group="ui")
    async def move_task(self, task: dict, lane: str, index: int | None) -> None:
        try:
            await self.api.move_task(self.board, int(task["id"]), lane, index)
        except ApiError as exc:
            self.status(str(exc), error=True)
            # The board on screen no longer matches the server; ask again.
            await self.load_tasks()
            return
        await self.load_tasks()
        self._refocus(int(task["id"]))
        if lane == DONE:
            self.status("done — it goes in a week")

    def _refocus(self, task_id: int) -> None:
        """Keep the moved card focused, so `]` twice goes ToDo → Doing → Done."""
        try:
            self.query_one(f"#task-{task_id}", TaskCard).focus()
        except Exception:
            return


def _position_of(task: dict, tasks: list[dict]) -> int:
    """Where a task currently sits in its own lane."""
    same = [row for row in tasks if row["lane"] == task["lane"]]
    for index, row in enumerate(same):
        if row["id"] == task["id"]:
            return index
    return -1
