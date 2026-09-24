"""Logo splash shown while we check the stored session."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static

from cloudmorrow import __version__
from cloudmorrow.logo import TAGLINE, mark_for_width, wordmark
from cloudmorrow.palette import MUTED


class SplashScreen(Screen):
    """Big logo, one status line."""

    def compose(self) -> ComposeResult:
        with Vertical(id="centre-column"):
            yield Static(wordmark(), id="logo")
            yield Static(f"[italic {MUTED}]{TAGLINE}  ·  v{__version__}[/]", id="tagline")
            yield Static(f"[{MUTED}]connecting…[/]", id="splash-status")

    def on_mount(self) -> None:
        self._fit_logo()

    def on_resize(self) -> None:
        self._fit_logo()

    def _fit_logo(self) -> None:
        self.query_one("#logo", Static).update(mark_for_width(self.size.width))

    def status(self, message: str) -> None:
        self.query_one("#splash-status", Static).update(f"[{MUTED}]{message}[/]")
