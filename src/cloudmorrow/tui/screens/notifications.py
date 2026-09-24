"""Notifications: what the machines have been up to, behind the bell.

The bell sits at the far right of the top bar on every screen of the
workspace, because a notification is not about the tab you happen to be on —
a config claimed on the desktop is news wherever you are standing. Ringing it
opens this, which is the whole of the feature: the list, and the one button
that says you have read it.
"""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, Static

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.screens.modals import Modal
from cloudmorrow.tui.theme import ACCENT, BAD, GOOD, MUTED

# How many of the server's notifications the modal shows.
NOTIFICATIONS = 50

# The bell, and the key that rings it — written beside it, the way the tabs
# and the Settings button carry theirs.
BELL = "🔔"
KEY = "f8"


def unread_count(notes: list[dict]) -> int:
    return sum(1 for note in notes if note.get("unread"))


def bell_label(unread: int) -> str:
    """What the top bar's bell says: the bell, the count if there is one, the key."""
    count = f" {unread}" if unread else ""
    return f"{BELL}{count}  {KEY}"


def _short(value: str | None, width: int = 16) -> str:
    return (value or "—")[:width].replace("T", " ")


def render(notes: list[dict]) -> str:
    """The list itself, so the bell and the modal draw it the same way."""
    if not notes:
        return f"[{MUTED}]Nothing has happened yet.[/]"
    colours = {"config.failed": BAD, "config.claimed": ACCENT, "config.updated": GOOD}
    lines = []
    for note in notes:
        colour = colours.get(note["kind"], MUTED)
        mark = f"[{ACCENT}]•[/]" if note["unread"] else " "
        where = f" [{MUTED}]{note['machine']}[/]" if note["machine"] else ""
        lines.append(
            f"{mark} [{MUTED}]{_short(note['created_at'], 16)}[/] "
            f"[{colour}]{note['title']}[/]{where}"
            + (f"\n    [{MUTED}]{note['body']}[/]" if note["body"] else "")
        )
    return "\n".join(lines)


class NotificationsScreen(Modal[None]):
    """The list of what the machines did, and a button to say you have seen it."""

    BINDINGS = [("escape", "close", "Close"), ("ctrl+r", "reload", "Refresh")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal modal-wide", id="notifications-modal"):
            yield Label("Notifications", classes="modal-title")
            # However long the list, the buttons keep their two rows.
            with VerticalScroll(id="notifications-body"):
                yield Static(f"[{MUTED}]…[/]", id="notifications-list")
            with Horizontal(classes="modal-buttons"):
                yield Button("Mark read", id="read")
                yield Button("Close", variant="primary", id="close")

    def on_mount(self) -> None:
        # The list is read, not operated: focus belongs on the buttons, so the
        # arrows move between them rather than scrolling underneath them.
        self.query_one("#notifications-body", VerticalScroll).can_focus = False
        self.query_one("#read", Button).focus()
        self.reload()

    @work(exclusive=True, group="notifications")
    async def reload(self) -> None:
        client = getattr(self.app, "client", None)
        if client is None:
            return
        target = self.query_one("#notifications-list", Static)
        try:
            notes = await client.notifications(limit=NOTIFICATIONS)
        except ApiError as exc:
            target.update(f"[{BAD}]{exc}[/]")
            return
        target.update(render(notes))
        # The bell behind this modal counts what the modal is showing.
        self.app.set_unread(unread_count(notes))

    def action_reload(self) -> None:
        self.reload()

    @work(group="notifications-write")
    async def mark_read(self) -> None:
        client = getattr(self.app, "client", None)
        if client is None:
            return
        try:
            await client.mark_notifications_read()
        except ApiError as exc:
            self.query_one("#notifications-list", Static).update(f"[{BAD}]{exc}[/]")
            return
        self.reload()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "read":
            self.mark_read()
        else:
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
