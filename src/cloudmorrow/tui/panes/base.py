"""What every pane in the workspace has in common.

A pane owns one view of the user's stuff. It gets told when to fetch again and
when it becomes visible, and it never has to care which of the two happened —
`reload()` is the only entry point.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical

from cloudmorrow.tui.widgets.toolbar import Action, Toolbar


class Pane(Vertical):
    """One tab's worth of workspace."""

    # Shown in the tab strip, with the key that brings it to the front beside
    # it — the strip is where that key is advertised, so the two live together.
    TAB_LABEL = "Pane"
    TAB_KEY = ""
    # Buttons across the top; each one fires `act_<id>`.
    ACTIONS: tuple[Action, ...] = ()

    def compose(self) -> ComposeResult:
        if self.ACTIONS:
            yield Toolbar(list(self.ACTIONS), id=f"{self.id}-toolbar")
        yield from self.content()

    def content(self) -> ComposeResult:
        """The pane's own widgets, below the toolbar."""
        return iter(())

    # -- the workspace talks to a pane through these -----------------------
    def reload(self) -> None:
        """Fetch and redraw. Called on mount and on refresh."""

    def on_show(self) -> None:
        """The pane just became the visible one."""

    # -- helpers -----------------------------------------------------------
    @property
    def api(self):
        """The API client. None until the session is up."""
        return getattr(self.app, "client", None)

    def status(self, message: str = "", *, error: bool = False) -> None:
        setter = getattr(self.screen, "set_status", None)
        if callable(setter):
            setter(message, error=error)

    def fire(self, name: str) -> None:
        """Run one of the pane's actions, whether a button or a key asked."""
        handler = getattr(self, f"act_{name}", None)
        if callable(handler):
            handler()

    def action_fire(self, name: str) -> None:
        """The same, reached from a key binding."""
        self.fire(name)

    def on_toolbar_fired(self, event: Toolbar.Fired) -> None:
        event.stop()
        self.fire(event.action)
