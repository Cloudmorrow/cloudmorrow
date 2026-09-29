"""The kit's pieces in the terminal: the board's lanes and cards.

A Quill never ships a screen of its own (docs/QUILLS.md), so everything the
terminal draws for one is decided from two things the server hands over: the
screen's bindings (`model`, `lane`, `title`, …) and the datamodels behind
them. Reading those is tui/kitdata.py's; nothing in here knows what a task
or a board is.

The board itself: lanes, and the cards you drag between them. A card is
picked up by pressing the mouse on it and dropped wherever the pointer is when
the button comes back up — including partway down a lane, which is what
decides the order. Nothing moves until the drop, so a drag that ends outside
the board leaves the card where it was.

Dragging is not the only way, because it never is here: a focused card moves
with `[` and `]`, goes to the done lane with space, and opens with enter. The
mouse is a first-class way to use this, not the only one.
"""

from __future__ import annotations

import re

from rich.text import Text
from textual import events
from textual.containers import Vertical, VerticalScroll
from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import DataTable, Static

from cloudmorrow.tui.kitdata import days_left, subtask_progress
from cloudmorrow.tui.theme import ACCENT, GOOD, MUTED, SECOND, TEXT, WARN

# How far the pointer must travel before a press becomes a drag rather than a
# click. Without it, a twitchy click would move the card a lane.
DRAG_THRESHOLD = 1
# What a widget id may be made of. Record ids and enum values come from
# somebody else's Quill, so they are made safe before they become one.
_UNSAFE_ID = re.compile(r"[^A-Za-z0-9_-]")


def safe_id(value: object) -> str:
    return _UNSAFE_ID.sub("_", str(value))


class RecordCard(Static, can_focus=True):
    """One record on a board. Click to open, press and drag to move."""

    BINDINGS = [
        ("enter", "open", "Open"),
        ("left_square_bracket", "shift(-1)", "Move left"),
        ("right_square_bracket", "shift(1)", "Move right"),
        ("space", "tick", "Done"),
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

    class Ticked(Message):
        """Space: to the done lane, or back out of it."""

        def __init__(self, record: dict) -> None:
            self.record = record
            super().__init__()

    def __init__(
        self, record: dict, *, title: str, body: str | None = None, movable: bool = True, subtitle: str = "", **kwargs
    ) -> None:
        super().__init__(**kwargs)
        # The screen's subtitle fields, already said: "Acme · 12000".
        self.subtitle = subtitle
        # Not `task`: Textual's MessagePump already owns that name, for the
        # asyncio task a widget runs on.
        self.record = record
        self.title_field = title
        self.body_field = body
        # A card on a board you may only read opens, and goes nowhere.
        self.movable = movable
        self._pressed_at: tuple[int, int] | None = None
        self._dragging = False
        self.update(self.render_card())

    @property
    def fields(self) -> dict:
        return self.record.get("fields") or {}

    def render_card(self) -> Text:
        """Title, then whatever is worth knowing without opening it."""
        text = Text()
        title = self.fields.get(self.title_field)
        text.append(str(title) if title not in (None, "") else "(untitled)", style=f"bold {TEXT}")
        if self.subtitle:
            text.append("\n" + self.subtitle, style=SECOND)
        body = str(self.fields.get(self.body_field) or "") if self.body_field else ""
        ticked, total = subtask_progress(body)
        meta: list[tuple[str, str]] = []
        if total:
            done = ticked == total
            meta.append((f"{ticked}/{total} subtasks", GOOD if done else SECOND))
        elif body.strip():
            meta.append(("notes", MUTED))
        left = days_left(self.record.get("expires_at"))
        if left is not None:
            # A record an expire job will take is on a clock, and saying so is
            # the difference between tidy and lost.
            meta.append(
                (
                    "goes today" if left == 0 else f"{left}d left",
                    WARN if left <= 1 else MUTED,
                )
            )
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
        if self._pressed_at is None or not self.movable:
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
    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Moving and ticking are not there on a card that cannot move."""
        return self.movable or action not in ("shift", "tick")

    def action_open(self) -> None:
        self.post_message(self.Opened(self.record))

    def action_shift(self, delta: int) -> None:
        self.post_message(self.Shifted(self.record, delta))

    def action_tick(self) -> None:
        self.post_message(self.Ticked(self.record))


class Lane(Vertical):
    """One lane — one value of the screen's enum field — and the cards in it."""

    def __init__(self, value: str, label: str, *, note: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.value = value
        self.label = label
        # Said beside the count when the lane has cards: "kept a week".
        self.note = note
        self.records: list[dict] = []
        self._key = safe_id(value)

    def compose(self):
        yield Static("", id=f"lane-head-{self._key}", classes="lane-head")
        yield VerticalScroll(id=f"lane-body-{self._key}", classes="lane-body")

    @property
    def body(self) -> VerticalScroll:
        return self.query_one(f"#lane-body-{self._key}", VerticalScroll)

    async def show(
        self,
        records: list[dict],
        *,
        title: str,
        body: str | None,
        movable: bool = True,
        said=None,
    ) -> None:
        """Redraw this lane's cards, in the order the server gave them.

        Awaited rather than fired off: removing children is deferred, and a
        card mounted before the old one of the same id has gone is a duplicate
        id — which is a crash, not a cosmetic problem.
        """
        self.records = records
        head = self.query_one(f"#lane-head-{self._key}", Static)
        heading = Text(self.label, style=f"bold {ACCENT}")
        heading.append(f"  {len(records)}", style=MUTED)
        if self.note and records:
            heading.append(f"   {self.note}", style=MUTED)
        head.update(heading)
        lane_body = self.body
        await lane_body.remove_children()
        await lane_body.mount_all(
            RecordCard(
                record,
                title=title,
                body=body,
                movable=movable,
                subtitle=said(record) if said else "",
                id=f"card-{safe_id(record['id'])}",
                classes="record-card",
            )
            for record in records
        )

    def cards(self) -> list[RecordCard]:
        return list(self.body.query(RecordCard))

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


def settle_widths(table: DataTable) -> None:
    """Draw a table again once its columns know how wide they are.

    A DataTable measures new rows when it is next idle, but a frame drawn
    before then is cached at the old widths — which, after a table that was
    empty, is the width of the header: "Middl". Writing one cell back as it
    was is the public way to make it draw afresh.
    """
    if table.row_count:
        table.update_cell_at(Coordinate(0, 0), table.get_cell_at(Coordinate(0, 0)), update_width=True)


def neighbour_lane(values: list[str], value: str, delta: int) -> str:
    """The lane *delta* steps along, clamped at the ends of the board."""
    if value not in values:
        return values[0] if values else value
    index = values.index(value) + delta
    return values[max(0, min(index, len(values) - 1))]
