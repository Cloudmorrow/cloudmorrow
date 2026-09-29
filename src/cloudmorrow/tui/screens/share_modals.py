"""The dialogs of a grid of shares: a new fileshare, a command to copy, and a notice.

tui/sharemounts.py is what mounts and makes shares from the terminal, and
these are the only dialogs it has that nothing else does. They sit on
`Modal`, so the arrows answer them like every other dialog here.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, RadioButton, RadioSet, Static

from cloudmorrow.tui.screens.modals import Modal


class NoticeModal(Modal[None]):
    """Something to read, and a Close button.

    The status bar is for a line said in passing; what does not fit on one
    — an error with a reason in it, a message with a next step — goes here.
    """

    BINDINGS = [("escape", "close", "Close"), ("enter", "close", "Close")]

    def __init__(self, title: str, detail: str) -> None:
        super().__init__()
        self._title = title
        self._detail = detail

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Label(self._title, classes="modal-title")
            yield Static(self._detail, classes="modal-detail", id="notice-text")
            with Horizontal(classes="modal-buttons"):
                yield Button("Close", variant="primary", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class CommandModal(Modal[None]):
    """Show a command to copy onto another machine."""

    BINDINGS = [("escape", "close", "Close"), ("enter", "close", "Close")]

    def __init__(self, title: str, command: str, *, note: str = "") -> None:
        super().__init__()
        self._title = title
        self._command = command
        self._note = note

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal modal-wide"):
            yield Label(self._title, classes="modal-title")
            yield Static(self._command, id="command-text", classes="command-block")
            if self._note:
                yield Static(self._note, classes="modal-detail")
            with Horizontal(classes="modal-buttons"):
                yield Button("Copy", variant="primary", id="copy")
                yield Button("Close", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "copy":
            # Textual writes to the terminal's clipboard via OSC 52; it works
            # over SSH in most terminals and is a no-op in the rest.
            self.app.copy_to_clipboard(self._command)
            self.app.say("Copied to the clipboard.")
            return
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class ShareModal(Modal[dict | None]):
    """A new fileshare: its name, and the directory on this machine behind it.

    A share serves a directory from the machine you are on — *this_machine*,
    which must be among *machines*, the caller's agents, or there is nothing
    here to serve it. There is no picking another machine: you share what is
    in front of you. An admin may put one on the server instead: the folder
    of that name in their Shares directory there, which *folders* describes
    — {"directory": where it is, "folders": what is in it unshared} — so
    the dialog can say what a name would pick up. Dismisses with {"kind",
    "name", "path", "machine", "description"}, or None.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        *,
        machines: list[dict],
        admin: bool,
        this_machine: str = "",
        folders: dict | None = None,
    ) -> None:
        super().__init__()
        self.admin = admin
        self.this_machine = this_machine
        self.enrolled = any(m.get("name") == this_machine for m in machines)
        self.folders = folders or {}

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Label("New fileshare", classes="modal-title")
            if self.admin:
                # This machine first, when it has an agent to serve the share.
                with RadioSet(id="share-kind"):
                    yield RadioButton(
                        f"On this machine ({self.this_machine})",
                        value=self.enrolled,
                        disabled=not self.enrolled,
                        id="kind-machine",
                    )
                    yield RadioButton("On the server", value=not self.enrolled, id="kind-server")
            yield Input(placeholder="name — lowercase, digits and dashes", id="share-name")
            yield Static("", classes="modal-detail", id="share-name-hint")
            yield Input(placeholder="the directory to share", id="share-path")
            yield Static("", classes="modal-detail", id="share-hint")
            yield Input(placeholder="description (optional)", id="share-description")
            with Horizontal(classes="modal-buttons"):
                yield Button("Create", variant="primary", id="create")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self._fit()
        self.query_one("#share-name", Input).focus()

    @property
    def kind(self) -> str:
        if not self.admin:
            return "machine"
        pressed = self.query_one("#share-kind", RadioSet).pressed_button
        return "server" if pressed is not None and pressed.id == "kind-server" else "machine"

    def _fit(self, complaint: str = "") -> None:
        """Say what the name and the path mean for the kind chosen.

        A machine share is a directory here, named for your other machines;
        a server share is the folder of that name in the Shares folder on the
        server, so there is no path to ask for. *complaint* is what is wrong
        with the path typed, said in red under it.
        """
        path = self.query_one("#share-path", Input)
        name_hint = self.query_one("#share-name-hint", Static)
        hint = self.query_one("#share-hint", Static)
        path.display = self.kind == "machine"
        if self.kind == "machine":
            name_hint.update(
                "[dim]What your other machines see it as: the name of the share, and "
                "of the folder it lands in when mounted.[/]"
            )
            path.placeholder = "the directory to share, e.g. ~/Music"
            lines = [
                "[dim]Served from this machine by its agent, while the agent runs. Nothing is copied to the server.[/]"
            ]
            if not self.enrolled:
                lines.append(
                    "[yellow]This machine has no agent, so nothing here can serve a share "
                    "— `cloudmorrow login` enrols it.[/]"
                )
            if complaint:
                lines.append(f"[red]{complaint}[/]")
            hint.update("\n".join(lines))
            hint.display = True
        else:
            directory = self.folders.get("directory") or "the Shares folder"
            unshared = [str(name) for name in self.folders.get("folders") or []]
            name_hint.update(
                f"[dim]Shares the folder of this name in [/]{directory}[dim] on the "
                f"server. It is made if it is not there; a folder already there is "
                f"shared as it is.[/]"
            )
            if unshared:
                names = ", ".join(f"[b]{name}[/]" for name in unshared)
                hint.update(f"[dim]In there and not shared yet: [/]{names}")
            hint.display = bool(unshared)

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        event.stop()
        self._fit()

    def _collect(self) -> dict | None:
        name = self.query_one("#share-name", Input).value.strip().lower()
        if not name:
            self.query_one("#share-name", Input).focus()
            return None
        kind = self.kind
        path = self.query_one("#share-path", Input).value.strip()
        if kind == "machine":
            if not self.enrolled:
                self._fit()
                return None
            if not path:
                self.query_one("#share-path", Input).focus()
                return None
            # The directory is on this machine, so whether it can be shared
            # is known here and now, before the server is asked.
            from cloudmorrow.client import sharing

            complaint = sharing.problem(path)
            if complaint:
                self._fit(complaint)
                self.query_one("#share-path", Input).focus()
                return None
            path = str(sharing.resolve(path))
        else:
            # A server share is named, not placed.
            path = ""
        return {
            "kind": kind,
            "name": name,
            "path": path,
            "machine": self.this_machine if kind == "machine" else "",
            "description": self.query_one("#share-description", Input).value.strip(),
        }

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        result = self._collect()
        if result is not None:
            self.dismiss(result)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "create":
            result = self._collect()
            if result is not None:
                self.dismiss(result)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
