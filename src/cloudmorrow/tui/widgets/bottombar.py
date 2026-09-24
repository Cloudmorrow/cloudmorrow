"""The bar along the bottom: what is going on, and what you can press.

Status on the left — the pane's detail and the latest message — and on the
right, at most five of the keys that work right now, most specific first:
the focused widget's, then its pane's, then the screen's. Quit is always the
last of them. A notice, like the one that asks for ctrl+c a second time,
takes the left side over until it is cleared.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Static

from cloudmorrow.tui.theme import ACCENT, WARN

MAX_TIPS = 5
QUIT_ACTION = "confirm_quit"


class BottomBar(Horizontal):
    """Status text left, a few shortcut tips right."""

    DEFAULT_CSS = """
    BottomBar {
        dock: bottom;
        height: 1;
        background: $surface;
        padding: 0 1;
    }
    BottomBar > #statusbar {
        width: 1fr;
        color: $muted;
    }
    BottomBar > #shortcuts {
        width: auto;
        color: $muted;
        margin-left: 2;
    }
    """

    notice: reactive[str] = reactive("", init=False)

    def __init__(self) -> None:
        super().__init__()
        self._text = ""

    def compose(self) -> ComposeResult:
        yield Static("", id="statusbar")
        yield Static("", id="shortcuts")

    def on_mount(self) -> None:
        self.screen.bindings_updated_signal.subscribe(self, self._bindings_changed)
        self.call_after_refresh(self.redraw_tips)

    def _bindings_changed(self, _: Screen) -> None:
        self.redraw_tips()

    # -- the left side -----------------------------------------------------
    def set_text(self, markup: str) -> None:
        self._text = markup
        self._redraw_left()

    def watch_notice(self, _: str) -> None:
        self._redraw_left()

    def _redraw_left(self) -> None:
        shown = f"[{WARN}]{self.notice}[/]" if self.notice else self._text
        self.query_one("#statusbar", Static).update(shown)

    # -- the right side ----------------------------------------------------
    def tips(self) -> list[tuple[str, str]]:
        """(key, what it does) for the keys worth showing, at most MAX_TIPS."""
        quit_tip: tuple[str, str] | None = None
        tips: list[tuple[str, str]] = []
        seen: set[str] = set()
        for _, binding, enabled, _tooltip in self.screen.active_bindings.values():
            if not binding.show or not enabled or not binding.description:
                continue
            tip = (self.app.get_key_display(binding), binding.description)
            if binding.action == QUIT_ACTION:
                quit_tip = tip
                continue
            # Two keys for one thing — `n` and `ctrl+n` — earn one tip.
            if binding.description in seen:
                continue
            seen.add(binding.description)
            tips.append(tip)
        if quit_tip is not None:
            tips = tips[: MAX_TIPS - 1] + [quit_tip]
        return tips[:MAX_TIPS]

    def redraw_tips(self) -> None:
        markup = "   ".join(f"[b {ACCENT}]{key}[/] {what}" for key, what in self.tips())
        self.query_one("#shortcuts", Static).update(markup)
