"""Change your password: the dialog your name in the header opens."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, Static

from cloudmorrow.tui.screens.modals import Modal


class PasswordModal(Modal[bool]):
    """Change your password: the one you have, and the one you want, twice.

    The dialog makes the call itself, through *change*, so a wrong current
    password is said here, with the fields still filled in, rather than after
    the box has closed. Dismisses True once the server has taken the new one.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    MIN_LENGTH = 8
    FIELDS = ("#current-password", "#new-password", "#repeat-password")

    def __init__(self, change: Any, *, username: str = "") -> None:
        super().__init__()
        self._change = change
        self._username = username

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal", id="password-modal"):
            yield Label("Change password", classes="modal-title")
            if self._username:
                yield Static(f"[dim]for [b]{self._username}[/][/]", classes="modal-detail")
            yield Input(placeholder="current password", password=True, id="current-password")
            yield Input(
                placeholder=f"new password — at least {self.MIN_LENGTH} characters",
                password=True,
                id="new-password",
            )
            yield Input(placeholder="new password, again", password=True, id="repeat-password")
            yield Static("", id="password-error", classes="modal-detail")
            with Horizontal(classes="modal-buttons"):
                yield Button("Change", variant="primary", id="change")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#current-password", Input).focus()

    def _say(self, message: str) -> None:
        from cloudmorrow.tui.theme import BAD

        self.query_one("#password-error", Static).update(f"[{BAD}]{message}[/]" if message else "")

    def _collect(self) -> tuple[str, str] | None:
        current = self.query_one("#current-password", Input).value
        new = self.query_one("#new-password", Input).value
        repeat = self.query_one("#repeat-password", Input).value
        if not current:
            self._say("Type your current password first.")
            self.query_one("#current-password", Input).focus()
            return None
        if len(new) < self.MIN_LENGTH:
            self._say(f"The new password needs at least {self.MIN_LENGTH} characters.")
            self.query_one("#new-password", Input).focus()
            return None
        if new != repeat:
            self._say("The two new passwords are not the same.")
            self.query_one("#repeat-password", Input).focus()
            return None
        return current, new

    async def _submit(self) -> None:
        from cloudmorrow.client.api import ApiError

        collected = self._collect()
        if collected is None:
            return
        self._say("")
        try:
            await self._change(*collected)
        except ApiError as exc:
            if exc.status_code == 403:
                self._say("That is not your current password.")
                field = self.query_one("#current-password", Input)
                field.value = ""
                field.focus()
            else:
                self._say(str(exc))
            return
        self.dismiss(True)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter moves down the fields, and submits from the last one."""
        event.stop()
        field_id = f"#{event.input.id}"
        if field_id != self.FIELDS[-1]:
            self.query_one(self.FIELDS[self.FIELDS.index(field_id) + 1], Input).focus()
            return
        await self._submit()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "change":
            await self._submit()
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)
