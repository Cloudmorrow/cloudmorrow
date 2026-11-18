"""The server is updating: a modal over everything until it is back.

The app hears the server say bye on the change feed (app.py, `listen`) the
moment it is told to stop — an update, over ssh or from the page. This
comes up then, with four blocks taking turns to hop, asks /api/health every
second and a half, and goes by itself when the server answers. Nothing is
pressed; Escape does nothing.
"""

from __future__ import annotations

import asyncio
from time import monotonic

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Label, Static

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.screens.modals import Modal

PROBE = 1.5
LONG = 90.0
BLOCKS = 4
BLOCK = "██"
COLOURS = ("#5aa6e0", "#3685bd", "#1c70b1", "#3685bd")
LONGER = "This is taking longer than usual. It carries on by itself when the server is back."


def frame(step: int) -> str:
    """Two lines of blocks, the one whose turn it is a line up."""
    up = step % (BLOCKS + 2)
    top, bottom = [], []
    for at in range(BLOCKS):
        block = f"[{COLOURS[at]}]{BLOCK}[/]"
        top.append(block if at == up else "  ")
        bottom.append("  " if at == up else block)
    return " ".join(top) + "\n" + " ".join(bottom)


class UpdatingModal(Modal[None]):
    """No buttons, nothing to answer: it goes when the server is back."""

    BINDINGS = [Binding("escape", "stay", show=False)]

    DEFAULT_CSS = """
    UpdatingModal { align: center middle; }
    UpdatingModal .updating-modal { width: 52; height: auto; padding: 1 3; align-horizontal: center; }
    UpdatingModal #updating-mark { width: auto; height: 2; margin-bottom: 1; }
    UpdatingModal .modal-title, UpdatingModal .modal-detail { width: 100%; text-align: center; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal updating-modal"):
            yield Static(frame(0), id="updating-mark")
            yield Label("The server is updating", classes="modal-title")
            yield Static(
                "Hold on for a sec — this carries on by itself when it is back.",
                classes="modal-detail",
                id="updating-more",
            )

    def on_mount(self) -> None:
        self._step = 0
        self.set_interval(0.18, self._hop)
        self.wait_for_the_server()

    def _hop(self) -> None:
        self._step += 1
        self.query_one("#updating-mark", Static).update(frame(self._step))

    def action_stay(self) -> None:
        """Escape: there is nothing to go back to until the server is."""

    @work(exclusive=True, group="updating")
    async def wait_for_the_server(self) -> None:
        since = monotonic()
        while True:
            await asyncio.sleep(PROBE)
            if monotonic() - since > LONG:
                self.query_one("#updating-more", Static).update(LONGER)
            client = self.app.client
            if client is None:
                break
            try:
                if (await client.health()).get("status") == "ok":
                    break
            except ApiError:
                continue
        self.dismiss(None)
