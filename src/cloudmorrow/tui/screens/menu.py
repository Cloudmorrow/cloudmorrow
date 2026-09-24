"""A context menu: a few choices in a small box where the mouse was.

Right-click something and this opens beside it. Pick a line with the mouse or
the arrows and enter; escape, or a click anywhere else, closes it with
nothing chosen. Dismisses with the key of the chosen item, or None.
"""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from cloudmorrow.tui.screens.modals import Modal


class MenuModal(Modal[str | None]):
    """Choices at a spot on the screen. *items* are (key, label) pairs."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    MenuModal > OptionList {
        height: auto;
        border: round $primary;
        background: $surface;
        padding: 0 1;
    }
    """

    def __init__(self, items: list[tuple[str, str]], *, x: int, y: int) -> None:
        super().__init__()
        self._items = items
        self._x = x
        self._y = y

    def compose(self) -> ComposeResult:
        yield OptionList(*(Option(label, id=key) for key, label in self._items), id="context-menu")

    def on_mount(self) -> None:
        # The app's stylesheet centres every modal and dims what is under it;
        # a menu sits where you clicked, over an unchanged screen.
        self.styles.align_horizontal = "left"
        self.styles.align_vertical = "top"
        self.styles.background = "transparent"
        menu = self.query_one(OptionList)
        width = max(len(label) for _, label in self._items) + 6
        height = len(self._items) + 2
        menu.styles.width = width
        # Nudged back on screen when the click was near an edge.
        x = max(0, min(self._x, self.size.width - width))
        y = max(0, min(self._y, self.size.height - height))
        menu.styles.offset = (x, y)
        menu.highlighted = 0
        menu.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(event.option_id)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        """A press outside the box is the answer "none of these"."""
        menu = self.query_one(OptionList)
        if not menu.region.contains(int(event.screen_x), int(event.screen_y)):
            event.stop()
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
