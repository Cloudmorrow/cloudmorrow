"""What every pane in the workspace has in common.

A pane owns one view of the user's stuff. It gets told when to fetch again and
when it becomes visible, and it never has to care which of the two happened —
`reload()` is the only entry point.

Every pane that stands on its own starts the same way: a header line — its
name in Sky, a few soft words about it, and on the right, faint, what it
counts and when it last heard from the server — then its row of buttons, of
which at most one is the amber primary action. A pane nested inside another
(the Files pane's own views) leaves the header to its parent.
"""

from __future__ import annotations

import datetime as dt

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from cloudmorrow.tui.theme import FAINT, MUTED, SKY
from cloudmorrow.tui.widgets.toolbar import Action, Toolbar


class Pane(Vertical):
    """One tab's worth of workspace."""

    # Shown on its card in the sidebar, with the key that brings it to the
    # front beside it — the card is where that key is advertised, so the two
    # live together.
    TAB_LABEL = "Pane"
    TAB_KEY = ""
    # A few words after the name in the header line, and on the card until
    # the pane has something live to say.
    SUMMARY = ""
    # Whether this pane draws the header line. Off for panes inside panes.
    HEAD = True
    # Buttons across the top; each one fires `act_<id>`.
    ACTIONS: tuple[Action, ...] = ()

    # When the pane last said something — which is when it last loaded.
    read_at: dt.datetime | None = None
    # How the pane is, said at the right of its header (see `status`).
    note: str = ""

    def compose(self) -> ComposeResult:
        if self.HEAD:
            with Horizontal(classes="pane-head"):
                yield Static(self._head_left(), classes="pane-name")
                yield Static("", classes="pane-read")
        if self.ACTIONS:
            yield Toolbar(list(self.ACTIONS), id=f"{self.id}-toolbar")
        yield from self.content()

    def content(self) -> ComposeResult:
        """The pane's own widgets, below the toolbar."""
        return iter(())

    def _head_left(self, room: int | None = None) -> Text:
        """The name, and the summary if it fits whole in *room* columns.

        A summary that does not fit is shortened at a word with "…", and
        dropped when even that would leave too little to read — never cut
        off mid-phrase without saying so.
        """
        text = Text(no_wrap=True)
        text.append(self.TAB_LABEL, style=f"bold {SKY}")
        summary = self.SUMMARY
        if summary and room is not None:
            space = room - len(self.TAB_LABEL) - 2
            if len(summary) > space:
                cut = summary[: max(0, space - 1)].rsplit(" ", 1)[0].rstrip(" ,;:·—")
                summary = f"{cut}…" if len(cut) >= 10 else ""
        if summary:
            text.append(f"  {summary}", style=MUTED)
        return text

    def refresh_head(self) -> None:
        """Redraw the header line: the note or counts on the right, then fit the left."""
        if not self.HEAD:
            return
        try:
            head = self.query_one(".pane-head", Horizontal)
            left = head.query_one(".pane-name", Static)
            right = head.query_one(".pane-read", Static)
        except Exception:
            return
        parts: list[Text] = []
        if self.note:
            parts.append(Text(self.note, style=MUTED))
        getter = getattr(self, "status_detail", None)
        detail = getter() if callable(getter) else ""
        if detail:
            parts.append(Text.from_markup(detail))
        if self.read_at is not None:
            parts.append(Text(f"read {self.read_at.strftime('%H:%M:%S')}", style=FAINT))
        text = Text(no_wrap=True)
        for index, part in enumerate(parts):
            if index:
                text.append("  ·  ", style=FAINT)
            text.append_text(part)
        right.update(text)
        width = head.size.width
        left.update(self._head_left(width - text.cell_len - 2 if width else None))

    def on_resize(self, _event) -> None:
        self.refresh_head()

    def card_status(self) -> tuple[str, str] | None:
        """(tone, line) for this pane's card in the sidebar, or None for its summary.

        Only what the pane already knows: a card never makes a request.
        """
        return None

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

    def status(self, message: str = "", *, error: bool = False, note: bool = False) -> None:
        """Say something. Once, in the right place.

        What happened — saved, moved, installed, failed — goes in the log
        along the bottom, with the time. A *note* is how the pane is rather
        than something that happened ("Nothing here yet", "2 accounts",
        "mounting…"): it sits at the right of the pane's header line until
        the pane says something else, and never reaches the log. An empty
        message clears the note. An error is always logged.
        """
        self.read_at = dt.datetime.now()
        if note or not message:
            self.note = "" if error else message
        setter = getattr(self.screen, "set_status", None)
        if callable(setter):
            setter(message if (error or not note) else "", error=error)

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
