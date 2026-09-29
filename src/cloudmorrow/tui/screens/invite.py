"""Invite a device (from Settings): a phone or a computer onto the cloud's mesh.

The terminal's Me → Invite a device. Anybody signed in may make an invite
once the cloud is linked and on its mesh: a six-character code from the
relay, good once, for ten minutes, that says nothing about whose device it
is for. The dialog shows the code, the one-line installer a computer runs
(it asks for the code), and the login server a phone's Tailscale app is
pointed at, as a QR code. An invite is made when asked for, not when the
dialog opens, so looking costs nothing.
"""

from __future__ import annotations

from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, Static

from cloudmorrow.client.api import ApiError
from cloudmorrow.qrtext import qr_markup
from cloudmorrow.tui.screens.modals import Modal
from cloudmorrow.tui.theme import ACCENT, BAD, MUTED


def invite_text(status: dict, invite: dict | None = None) -> str:
    """What the dialog says, apart from it, for a test to read."""
    mesh = status.get("mesh") or {}
    if not mesh.get("on"):
        if status.get("linked"):
            return f"[{MUTED}]This cloud is linked, and still joining its mesh. Try again in a minute.[/]"
        return (
            f"[{MUTED}]This cloud is reached on the home network only, so there is no mesh to\n"
            f"invite a device to. An administrator links it in Administration → Access.[/]"
        )
    host = escape(status.get("host") or "")
    command = escape(f"curl -fsSL https://{status.get('host')}/install.sh | sh")
    lines = [f"Devices on the mesh reach [b]{host}[/] from anywhere.", ""]
    if invite:
        until = (invite.get("expires_at") or "").replace("T", " ")[11:16]
        lines += [
            f"      [b {ACCENT}]{escape(invite.get('code') or '')}[/]",
            f"  [{MUTED}]for one device, once{', until ' + until + ' UTC' if until else ', for ten minutes'}[/]",
            "",
        ]
    else:
        lines += [f"[{MUTED}]Make an invite, and give its code to the device.[/]", ""]
    lines += [
        "[b]A computer[/] runs this; it asks for the code, and for Tailscale:",
        f"  {command}",
        "",
        "[b]A phone[/]: the Tailscale app, [i]Use an alternate server[/], this address;",
        "the page it opens asks for the code.",
        f"  {escape(mesh.get('login_server') or '')}",
        "",
    ]
    picture = qr_markup(mesh.get("login_server") or "")
    if picture:
        lines += ["  " + line for line in picture.splitlines()]
    return "\n".join(lines)


class InviteModal(Modal[None]):
    """The code, the command, and the QR code of the login server."""

    BINDINGS = [("escape", "close", "Close"), ("i", "invite", "Make an invite")]
    DEFAULT_CSS = """
    #invite-body { height: auto; max-height: 34; }
    #invite-text { height: auto; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._status: dict = {}
        self._invite: dict | None = None

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal modal-wide", id="invite-modal"):
            yield Label("Invite a device", classes="modal-title")
            with VerticalScroll(id="invite-body"):
                yield Static("Looking…", id="invite-text")
            with Horizontal(classes="modal-buttons"):
                yield Button("Make an invite", variant="primary", id="make-invite", disabled=True)
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        self.query_one("#invite-body", VerticalScroll).can_focus = False
        self.load()

    @work(exclusive=True, group="invite")
    async def load(self) -> None:
        client = getattr(self.app, "client", None)
        if client is None:
            return
        try:
            self._status = await client.access()
        except ApiError as exc:
            self.query_one("#invite-text", Static).update(f"[{BAD}]{escape(str(exc))}[/]")
            return
        self._draw()

    def _draw(self) -> None:
        self.query_one("#invite-text", Static).update(invite_text(self._status, self._invite))
        button = self.query_one("#make-invite", Button)
        button.disabled = not (self._status.get("mesh") or {}).get("on")
        button.label = "Make another" if self._invite else "Make an invite"

    @work(exclusive=True, group="invite")
    async def make(self) -> None:
        client = getattr(self.app, "client", None)
        if client is None:
            return
        try:
            self._invite = await client.mesh_invite()
        except ApiError as exc:
            self.query_one("#invite-text", Static).update(f"[{BAD}]{escape(str(exc))}[/]")
            return
        self._draw()

    def action_invite(self) -> None:
        if not self.query_one("#make-invite", Button).disabled:
            self.make()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "make-invite":
            self.make()
        else:
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
