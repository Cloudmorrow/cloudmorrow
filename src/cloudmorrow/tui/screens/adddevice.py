"""Add a device (from Settings): this cloud on a computer, a phone, or an assistant.

The terminal's Me → Add a device, the same as the web app's
(server/web/adddevice.js). Nothing on it is a code or a key: every device
signs in with the person's own name and password, at the address this
terminal signed in to.
"""

from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, Static

from cloudmorrow.qrtext import qr_markup
from cloudmorrow.tui.screens.modals import Modal


def add_device_text(signed_in_to: str) -> str:
    """What the dialog says, for a test to read."""
    base = signed_in_to.rstrip("/")
    lines = [
        f"Everything signs in to [b]{escape(base)}[/] with your own name and password.",
        "",
        "[b]A computer[/] runs this in a terminal; it installs Cloudmorrow and signs you in:",
        f"  {escape(f'curl -fsSL {base}/install.sh | sh')}",
        "",
        "[b]A phone[/] opens this in its browser, signs in, and adds it to the home screen:",
        f"  {escape(base)}/app",
        "",
    ]
    picture = qr_markup(f"{base}/app")
    if picture:
        lines += ["  " + line for line in picture.splitlines()] + [""]
    lines += ["[b]An assistant[/] that speaks MCP works with the cloud as you, at:", f"  {escape(base)}/mcp"]
    return "\n".join(lines)


class AddDeviceModal(Modal[None]):
    """The command, the address, and a QR code of it."""

    BINDINGS = [("escape", "close", "Close")]
    DEFAULT_CSS = """
    #add-device-body { height: auto; max-height: 34; }
    #add-device-text { height: auto; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal modal-wide", id="add-device-modal"):
            yield Label("Add a device", classes="modal-title")
            with VerticalScroll(id="add-device-body"):
                yield Static(add_device_text(self._base()), id="add-device-text")
            with Horizontal(classes="modal-buttons"):
                yield Button("Close", variant="primary", id="close")

    def _base(self) -> str:
        config = getattr(self.app, "client_config", None)
        return getattr(config, "api_url", "") or ""

    def on_mount(self) -> None:
        self.query_one("#add-device-body", VerticalScroll).can_focus = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
