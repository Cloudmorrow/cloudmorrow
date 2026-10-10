"""The dialogs of a grid of shares: a new fileshare, who has one, a command to copy, and a notice.

tui/sharemounts.py is what mounts and makes shares from the terminal, and
these are the only dialogs it has that nothing else does. They sit on
`Modal`, so the arrows answer them like every other dialog here.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, Static

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


def _who_hint(candidates: dict) -> str:
    """Who there is to share with, in a line or two, for under the field."""
    people = [p.get("username", "") for p in candidates.get("people") or []]
    circles = [f"circle:{c.get('name', '')}" for c in candidates.get("circles") or []]
    names = people + circles + (["everyone"] if candidates.get("everyone") else [])
    shown = ", ".join(names[:12]) + (", …" if len(names) > 12 else "")
    lines = [
        "[dim]Names, circle:NAME"
        + (", everyone" if candidates.get("everyone") else "")
        + " — commas between them, (read) after one who may only read.[/]"
    ]
    if shown:
        lines.append(f"[dim]On this server:[/] {shown}")
    return "\n".join(lines)


class ShareModal(Modal[dict | None]):
    """A new fileshare: its name, who it is shared with, and — for an
    administrator — where on the server it is.

    A share is the folder of its name in the Shares folder on the server,
    and *candidates* says where that is and who there is to share it with
    ({"directory", "people", "circles", "everyone"}). An administrator sees
    the path filled in as the name is typed, and may change it to share a
    directory elsewhere on the server; what is wrong with it is the
    server's to say when the share is made. *folders* is what is in the
    Shares folder unshared, for an administrator. Dismisses with {"name",
    "path", "members", "description"}, or None.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, *, admin: bool, candidates: dict | None = None, folders: dict | None = None) -> None:
        super().__init__()
        self.admin = admin
        self.candidates = candidates or {}
        self.folders = folders or {}
        self.directory = str(self.candidates.get("directory") or self.folders.get("directory") or "")
        # The path follows the name until somebody types in it.
        self._path_typed = False
        self._filling = False

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal modal-wide"):
            yield Label("New fileshare", classes="modal-title")
            yield Input(placeholder="name — lowercase, digits and dashes", id="share-name")
            yield Static("", classes="modal-detail", id="share-name-hint")
            yield Input(placeholder="the directory on the server", id="share-path")
            yield Static("", classes="modal-detail", id="share-path-hint")
            yield Input(placeholder="share with — e.g. ann, circle:kids (read)", id="share-with")
            yield Static(_who_hint(self.candidates), classes="modal-detail", id="share-with-hint")
            yield Input(placeholder="description (optional)", id="share-description")
            with Horizontal(classes="modal-buttons"):
                yield Button("Create", variant="primary", id="create")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        path = self.query_one("#share-path", Input)
        path.display = self.admin
        self.query_one("#share-path-hint", Static).display = self.admin
        self._fit()
        self.query_one("#share-name", Input).focus()

    def _default_path(self, name: str) -> str:
        return f"{self.directory.rstrip('/')}/{name}" if self.directory and name else ""

    def _fit(self) -> None:
        directory = self.directory or "the Shares folder"
        self.query_one("#share-name-hint", Static).update(
            f"[dim]The folder of this name in [/]{directory}[dim] on the server, made if it is not there. "
            "It is yours; whoever you share it with mounts it by this name.[/]"
        )
        if self.admin:
            unshared = [str(name) for name in self.folders.get("folders") or []]
            lines = ["[dim]Change the path to share another directory on the server instead.[/]"]
            if unshared:
                lines.append("[dim]In the Shares folder and not shared yet: [/]" + ", ".join(unshared))
            self.query_one("#share-path-hint", Static).update("\n".join(lines))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "share-name" and self.admin and not self._path_typed:
            self._filling = True
            self.query_one("#share-path", Input).value = self._default_path(event.value.strip().lower())
        elif event.input.id == "share-path":
            if self._filling:
                self._filling = False
            else:
                self._path_typed = True

    def _collect(self) -> dict | None:
        from cloudmorrow.client.members import parse

        name = self.query_one("#share-name", Input).value.strip().lower()
        if not name:
            self.query_one("#share-name", Input).focus()
            return None
        path = self.query_one("#share-path", Input).value.strip() if self.admin else ""
        if path == self._default_path(name):
            path = ""
        return {
            "name": name,
            "path": path,
            "members": parse(self.query_one("#share-with", Input).value),
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


class MembersModal(Modal[str | None]):
    """Who a share is shared with, as one line to edit: `ann, circle:kids (read)`.

    Dismisses with the line as it was left, or None. What changed is the
    caller's to work out (`client.members.changes`) and ask for.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, name: str, line: str, candidates: dict | None = None) -> None:
        super().__init__()
        self._share = name
        self._line = line
        self.candidates = candidates or {}

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal modal-wide"):
            yield Label(f"Share {self._share} with", classes="modal-title")
            yield Input(value=self._line, placeholder="nobody but you", id="members-line")
            yield Static(_who_hint(self.candidates), classes="modal-detail")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#members-line", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.dismiss(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(self.query_one("#members-line", Input).value if event.button.id == "save" else None)

    def action_cancel(self) -> None:
        self.dismiss(None)
