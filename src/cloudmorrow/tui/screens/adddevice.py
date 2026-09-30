"""Add a device (from Settings): this cloud on a computer, a phone, or an assistant.

The terminal's Me → Add a device, the same as the web app's
(server/web/adddevice.js). Nothing on it is a code or a key: every device
signs in with the person's own name and password, and on a linked cloud a
computer then joins the cloud's mesh by itself (client/autojoin.py). The
address is the cloud's real name once it is on its mesh, which opens from
anywhere, else the one this terminal signed in to.
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
from cloudmorrow.tui.theme import BAD, MUTED


def add_device_text(status: dict, signed_in_to: str = "") -> str:
    """What the dialog says, for a test to read."""
    on_mesh = bool((status.get("mesh") or {}).get("on"))
    base = f"https://{status.get('host')}" if on_mesh else signed_in_to.rstrip("/")
    lines = [f"Everything signs in to [b]{escape(base)}[/] with your own name and password."]
    if on_mesh:
        lines.append(f"[{MUTED}]From anywhere. A computer then joins the cloud's mesh by itself.[/]")
    elif not status.get("linked"):
        lines.append(f"[{MUTED}]On the home network; once an administrator links it, from anywhere too.[/]")
    lines += [
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
                yield Static("Looking…", id="add-device-text")
            with Horizontal(classes="modal-buttons"):
                yield Button("Close", variant="primary", id="close")

    def on_mount(self) -> None:
        self.query_one("#add-device-body", VerticalScroll).can_focus = False
        self.load()

    @work(exclusive=True, group="add-device")
    async def load(self) -> None:
        client = getattr(self.app, "client", None)
        if client is None:
            return
        text = self.query_one("#add-device-text", Static)
        try:
            status = await client.access()
        except ApiError as exc:
            text.update(f"[{BAD}]{escape(str(exc))}[/]")
            return
        config = getattr(self.app, "client_config", None)
        text.update(add_device_text(status, getattr(config, "api_url", "") or ""))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
