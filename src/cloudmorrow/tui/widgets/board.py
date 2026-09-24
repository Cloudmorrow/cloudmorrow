"""The board itself: three lanes, and the cards you drag between them.

A card is picked up by pressing the mouse on it and dropped wherever the
pointer is when the button comes back up — including partway down a lane,
which is what decides the order. Nothing moves until the drop, so a drag that
ends outside the board leaves the card where it was.

Dragging is not the only way, because it never is here: a focused card moves
with `[` and `]`, and opens with enter. The mouse is a first-class way to use
this, not the only one.
"""

from __future__ import annotations

import datetime as dt
import math
import re

from rich.text import Text
from textual import events
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Static

from cloudmorrow.server.tasks import DONE, LANE_TITLES, LANES, expires_at
from cloudmorrow.tui.theme import ACCENT, GOOD, MUTED, SECOND, TEXT, WARN

# A subtask is a checkbox line in the body, the same one the note editor ticks.
_SUBTASK_RE = re.compile(r"^\s*[-*+]\s+\[([ xX])\]\s", re.MULTILINE)
# How far the pointer must travel before a press becomes a drag rather than a
# click. Without it, a twitchy click would move the card a lane.
DRAG_THRESHOLD = 1


def subtask_progress(body: str) -> tuple[int, int]:
    """How many of a task's subtasks are ticked, and how many there are."""
    marks = _SUBTASK_RE.findall(body or "")
    return sum(1 for mark in marks if mark.lower() == "x"), len(marks)


def days_left(done_at: str | None) -> int | None:
    """Days before a finished task is swept, or None if it is not done.

    Rounded up, because part of a day is still a day you have: something
    finished five days ago goes in two, and saying "1d left" would be the
    truncation talking rather than the truth.
    """
    if not done_at:
        return None
    expiry = expires_at(done_at)
    if expiry is None:
        return None
    remaining = (expiry - dt.datetime.now(tz=dt.UTC)).total_seconds()
    if remaining <= 0:
        return 0
    return math.ceil(remaining / 86400)


class TaskCard(Static, can_focus=True):
    """One task. Click to open, press and drag to move."""

    BINDINGS = [
        ("enter", "open", "Open"),
        ("left_square_bracket", "shift(-1)", "Move left"),
        ("right_square_bracket", "shift(1)", "Move right"),
    ]

    class Opened(Message):
        """The card was clicked, or enter was pressed on it."""

        def __init__(self, record: dict) -> None:
            self.record = record
            super().__init__()

    class Dropped(Message):
        """A drag finished. Where it landed is the pane's business, not ours."""

        def __init__(self, record: dict, x: int, y: int) -> None:
            self.record = record
            self.x = x
            self.y = y
            super().__init__()

    class Dragging(Message):
        """The pointer moved while holding a card, so the board can show it."""

        def __init__(self, record: dict, x: int, y: int) -> None:
            self.record = record
            self.x = x
            self.y = y
            super().__init__()

    class Shifted(Message):
        """A keyboard request to move one lane left or right."""

        def __init__(self, record: dict, delta: int) -> None:
            self.record = record
            self.delta = delta
            super().__init__()

    def __init__(self, record: dict, **kwargs) -> None:
        super().__init__(**kwargs)
        # Not `task`: Textual's MessagePump already owns that name, for the
        # asyncio task a widget runs on.
        self.record = record
        self._pressed_at: tuple[int, int] | None = None
        self._dragging = False
        self.update(self.render_card())

    @property
    def task_id(self) -> int:
        return int(self.record["id"])

    def render_card(self) -> Text:
        """Title, then whatever is worth knowing without opening it."""
        text = Text()
        text.append(self.record["title"], style=f"bold {TEXT}")
        ticked, total = subtask_progress(self.record.get("body", ""))
        meta: list[tuple[str, str]] = []
        if total:
            done = ticked == total
            meta.append((f"{ticked}/{total} subtasks", GOOD if done else SECOND))
        elif (self.record.get("body") or "").strip():
            meta.append(("notes", MUTED))
        left = days_left(self.record.get("done_at"))
        if left is not None:
            # The Done lane empties itself, so a card in it is on a clock and
            # saying so is the difference between tidy and lost.
            meta.append((
                "goes today" if left == 0 else f"{left}d left",
                WARN if left <= 1 else MUTED,
            ))
        if meta:
            text.append("\n")
            for index, (label, style) in enumerate(meta):
                if index:
                    text.append("  ·  ", style=MUTED)
                text.append(label, style=style)
        return text

    # -- the mouse ---------------------------------------------------------
    def on_mouse_down(self, event: events.MouseDown) -> None:
        event.stop()
        self.focus()
        self._pressed_at = (int(event.screen_x), int(event.screen_y))
        self._dragging = False
        self.capture_mouse()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._pressed_at is None:
            return
        start_x, start_y = self._pressed_at
        travelled = abs(int(event.screen_x) - start_x) + abs(int(event.screen_y) - start_y)
        if not self._dragging and travelled <= DRAG_THRESHOLD:
            return
        self._dragging = True
        self.add_class("-dragging")
        self.post_message(self.Dragging(self.record, int(event.screen_x), int(event.screen_y)))

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._pressed_at is None:
            return
        event.stop()
        self.release_mouse()
        self._pressed_at = None
        self.remove_class("-dragging")
        if self._dragging:
            self._dragging = False
            self.post_message(self.Dropped(self.record, int(event.screen_x), int(event.screen_y)))
            return
        # It never became a drag, so it was a click.
        self.post_message(self.Opened(self.record))

    # -- the keyboard ------------------------------------------------------
    def action_open(self) -> None:
        self.post_message(self.Opened(self.record))

    def action_shift(self, delta: int) -> None:
        self.post_message(self.Shifted(self.record, delta))


class Lane(Vertical):
    """One of the three lanes, and the cards in it."""

    def __init__(self, lane: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.lane = lane
        self.tasks: list[dict] = []

    def compose(self):
        yield Static("", id=f"lane-head-{self.lane}", classes="lane-head")
        yield VerticalScroll(id=f"lane-body-{self.lane}", classes="lane-body")

    @property
    def body(self) -> VerticalScroll:
        return self.query_one(f"#lane-body-{self.lane}", VerticalScroll)

    async def show(self, tasks: list[dict]) -> None:
        """Redraw this lane's cards, in the order the server gave them.

        Awaited rather than fired off: removing children is deferred, and a
        card mounted before the old one of the same id has gone is a duplicate
        id — which is a crash, not a cosmetic problem.
        """
        self.tasks = tasks
        head = self.query_one(f"#lane-head-{self.lane}", Static)
        title = Text(LANE_TITLES[self.lane], style=f"bold {ACCENT}")
        title.append(f"  {len(tasks)}", style=MUTED)
        if self.lane == DONE and tasks:
            title.append("   kept a week", style=MUTED)
        head.update(title)
        body = self.body
        await body.remove_children()
        await body.mount_all(
            TaskCard(task, id=f"task-{task['id']}", classes="task-card") for task in tasks
        )

    def cards(self) -> list[TaskCard]:
        return list(self.body.query(TaskCard))

    def index_at(self, y: int) -> int:
        """Where a card dropped at screen row *y* belongs in this lane.

        Above a card's middle means before it, below means after — so the gap
        you are pointing at is the gap it lands in.
        """
        index = 0
        for card in self.cards():
            region = card.region
            if y >= region.y + region.height / 2:
                index += 1
        return index


def lane_under(screen, x: int, y: int) -> Lane | None:
    """The lane the pointer is over, if it is over one at all."""
    try:
        widget, _ = screen.get_widget_at(x, y)
    except Exception:
        # Outside the screen entirely: nothing was dropped on.
        return None
    for candidate in (widget, *widget.ancestors):
        if isinstance(candidate, Lane):
            return candidate
    return None


def neighbour_lane(lane: str, delta: int) -> str:
    """The lane *delta* steps along, clamped at the ends of the board."""
    index = LANES.index(lane) + delta
    return LANES[max(0, min(index, len(LANES) - 1))]
