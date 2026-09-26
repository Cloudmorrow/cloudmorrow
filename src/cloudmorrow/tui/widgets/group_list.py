"""The group list: a list screen's groups, down the left, as the note tree is for notes.

A group is a row, the way a note is a leaf in a tree: its name, and how many
records are in it to the right. Click one, or press enter on it, and its
records open beside it. It is the kit's (tui/panes/kit_grouped.py), so it
knows nothing of what the groups are — vaults, customers, rooms.
"""

from __future__ import annotations

from typing import Any

from rich.cells import cell_len, set_cell_size
from rich.text import Text
from textual.message import Message
from textual.widgets import ListItem, ListView, Static

from cloudmorrow.tui.theme import ACCENT, MUTED, SECOND, TEXT

# How wide a row is before the list has been laid out: the column is 26
# columns, less the one of padding on each side of a row.
ROW_WIDTH = 24


class GroupRow(ListItem):
    """One group in the list. Holds its value so a click can say which."""

    def __init__(self, value: str, label: Text) -> None:
        super().__init__(Static(label))
        self.value = value


class GroupList(ListView):
    """The groups, one row each, in the order they were given."""

    BINDINGS = [
        ("n", "new_group", "New"),
    ]

    class Chosen(Message):
        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    class NewRequested(Message):
        pass

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # (value, label, count) for each row.
        self.groups: list[tuple[str, str, int]] = []
        self.current: str | None = None
        # The width the rows were cut to last time, so a resize that changes
        # nothing does not rebuild the list under you.
        self._drawn_width = 0

    def show(self, groups: list[tuple[str, str, int]], current: str | None) -> None:
        """Redraw the list. Keeps the selection on *current*."""
        self.groups = groups
        self.current = current
        self.clear()
        width = self.row_width()
        self._drawn_width = width
        rows = [
            GroupRow(value, self._label(label, value == current, count=count, width=width))
            for value, label, count in groups
        ]
        for row in rows:
            self.append(row)
        self.index = next((index for index, row in enumerate(rows) if row.value == current), 0)

    def row_width(self) -> int:
        """How many columns a row has, once the padding is taken off."""
        return self.size.width - 2 if self.size.width > 2 else ROW_WIDTH

    def on_resize(self) -> None:
        """A narrower column is a shorter name, so cut them again."""
        if self.groups and self.row_width() != self._drawn_width:
            self.show(self.groups, self.current)

    @staticmethod
    def _label(name: str, selected: bool, count: int = 0, width: int = ROW_WIDTH) -> Text:
        """One row, one line: the name, and how many records it holds, to the right."""
        tail = str(count) if count else ""
        marker = "▎" if selected else " "
        text = Text(marker, style=ACCENT if selected else "")
        room = max(1, width - 2 - (cell_len(tail) + 2 if tail else 0))
        shown = name if cell_len(name) <= room else set_cell_size(name, room - 1).rstrip() + "…"
        text.append(f" {shown}", style=f"bold {SECOND}" if selected else TEXT)
        if tail:
            text.append(" " * max(2, width - 2 - cell_len(shown) - cell_len(tail)))
            text.append(tail, style=MUTED)
        return text

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        if isinstance(event.item, GroupRow):
            self.post_message(self.Chosen(event.item.value))

    def action_new_group(self) -> None:
        self.post_message(self.NewRequested())
