"""The dialog for a mount on a Linux machine that has no rclone.

It says what is missing and what would install it, and offers to. What it
offers is decided by `client.rclone`: the package manager here, with sudo
when that takes one — or, when there is none we know, where to read how.
Installing itself is the caller's job, because the terminal has to be handed
over for sudo to ask its question, and only the app can do that.
"""

from __future__ import annotations

import shlex

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Label, Static

from cloudmorrow.client import rclone
from cloudmorrow.tui.screens.modals import Modal


class InstallRcloneModal(Modal[bool]):
    """rclone is not here. Install it? True to go ahead, False to leave it."""

    BINDINGS = [("escape", "cancel", "Cancel"), ("y", "install", "Install"), ("n", "cancel", "No")]

    def __init__(self, command: list[str] | None) -> None:
        super().__init__()
        self._command = command

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Label("rclone is not installed", classes="modal-title")
            if self._command is None:
                yield Static(
                    f"{rclone.MISSING} No package manager I know is on this machine, so "
                    f"install it yourself — [b]{rclone.DOWNLOAD}[/] says how — and then "
                    f"Mount again.",
                    classes="modal-detail",
                    id="install-text",
                )
                with Horizontal(classes="modal-buttons"):
                    yield Button("Close", variant="primary", id="cancel")
                return
            yield Static(
                f"{rclone.MISSING} Install it now? The terminal takes over while this runs, "
                f"and sudo may ask for your password there.",
                classes="modal-detail",
                id="install-text",
            )
            yield Static(shlex.join(self._command), classes="command-block", id="install-command")
            with Horizontal(classes="modal-buttons"):
                yield Button("Install", variant="primary", id="install")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "install")

    def action_install(self) -> None:
        self.dismiss(self._command is not None)

    def action_cancel(self) -> None:
        self.dismiss(False)
