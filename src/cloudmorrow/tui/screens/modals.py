"""Small modal dialogs: prompt, confirm, notice, conflict and search.

They all sit on `Modal`, which is where the keyboard manners live: the arrows
move between the things you can press and enter presses the one you are on, so
a dialog can be answered without reaching for the mouse or knowing that tab is
what moves focus.
"""

from __future__ import annotations

from typing import Any, TypeVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    ListItem,
    ListView,
    RadioButton,
    RadioSet,
    Static,
)

ReturnType = TypeVar("ReturnType")


class Modal(ModalScreen[ReturnType]):
    """A dialog you can answer with the arrow keys.

    Tab moves focus everywhere in Textual, and nowhere is that less discoverable
    than in a box with two buttons in it. The arrows do it here as well — and
    they reach the screen only when the focused widget has no use for them, so
    they still move the cursor inside an input and still move the selection in a
    list.
    """

    BINDINGS = [
        Binding("left,up", "focus_previous", "Previous", show=False),
        Binding("right,down", "focus_next", "Next", show=False),
    ]

    # Spelled out on the screen rather than left to the app's own actions of
    # the same name: focus moves inside this dialog, and the dialog is what
    # knows the order of it.
    def action_focus_next(self) -> None:
        self.focus_next()

    def action_focus_previous(self) -> None:
        self.focus_previous()


class PromptModal(Modal[str | None]):
    """Ask for a single line of text."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        title: str,
        *,
        value: str = "",
        placeholder: str = "",
        detail: str = "",
        password: bool = False,
    ) -> None:
        super().__init__()
        self._title = title
        self._value = value
        self._placeholder = placeholder
        self._detail = detail
        # A secret being typed should not sit on screen in the clear.
        self._password = password

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Label(self._title, classes="modal-title")
            if self._detail:
                yield Static(self._detail, classes="modal-detail")
            yield Input(
                value=self._value,
                placeholder=self._placeholder,
                password=self._password,
                id="prompt-input",
            )
            with Horizontal(classes="modal-buttons"):
                yield Button("OK", variant="primary", id="ok")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        field = self.query_one("#prompt-input", Input)
        field.focus()
        field.cursor_position = len(field.value)

    def _result(self, raw: str) -> str | None:
        # A password field takes what was typed; elsewhere a blank line means
        # "never mind", which is what every caller already assumes.
        return raw if self._password else (raw.strip() or None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(self._result(event.value))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self.dismiss(self._result(self.query_one("#prompt-input", Input).value))
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmModal(Modal[bool]):
    """Yes/no."""

    BINDINGS = [("escape", "cancel", "Cancel"), ("y", "confirm", "Yes"), ("n", "cancel", "No")]

    def __init__(self, title: str, *, detail: str = "", confirm_label: str = "Delete") -> None:
        super().__init__()
        self._title = title
        self._detail = detail
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Label(self._title, classes="modal-title")
            if self._detail:
                yield Static(self._detail, classes="modal-detail")
            with Horizontal(classes="modal-buttons"):
                yield Button(self._confirm_label, variant="error", id="confirm")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


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


class ConflictModal(Modal[str]):
    """The note changed on the server while we were editing it."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, path: str) -> None:
        super().__init__()
        self._path = path

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Label("Note changed on the server", classes="modal-title")
            yield Static(
                f"[b]{self._path}[/] was modified elsewhere since you opened it.",
                classes="modal-detail",
            )
            with Horizontal(classes="modal-buttons"):
                yield Button("Overwrite", variant="error", id="overwrite")
                yield Button("Reload theirs", variant="primary", id="reload")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id or "cancel")

    def action_cancel(self) -> None:
        self.dismiss("cancel")


class SearchModal(Modal[str | None]):
    """Full-text search across notes; dismisses with the chosen note path."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, search_callback: Any) -> None:
        super().__init__()
        self._search = search_callback
        self._paths: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal modal-wide"):
            yield Label("Search notes", classes="modal-title")
            yield Input(placeholder="text or file name…", id="search-input")
            with VerticalScroll(id="search-results-wrapper"):
                yield ListView(id="search-results")

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()

    async def on_input_changed(self, event: Input.Changed) -> None:
        query = event.value.strip()
        results_view = self.query_one("#search-results", ListView)
        await results_view.clear()
        self._paths = []
        if len(query) < 2:
            return
        try:
            payload = await self._search(query)
        except Exception as exc:  # surfaced in the list rather than crashing the modal
            await results_view.append(ListItem(Static(f"[red]{exc}[/]")))
            return
        for result in payload.get("results", []):
            first = result["matches"][0]["text"] if result["matches"] else ""
            self._paths.append(result["path"])
            await results_view.append(
                ListItem(Static(f"[b]{result['path']}[/]\n[dim]{first[:120]}[/]"))
            )

    def on_input_submitted(self) -> None:
        results_view = self.query_one("#search-results", ListView)
        if self._paths:
            results_view.focus()
            results_view.index = 0

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        index = event.list_view.index
        if index is not None and 0 <= index < len(self._paths):
            self.dismiss(self._paths[index])

    def action_cancel(self) -> None:
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


class TaskModal(Modal[dict | None]):
    """A task: its title, and the markdown underneath it.

    The same live editor the notes use, because a task's body is a small note
    — the detail, and the `- [ ]` lines that are its subtasks. Dismisses with
    {"title": ..., "body": ...}, or None when nothing is to be saved.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
    ]

    def __init__(self, heading: str, *, title: str = "", body: str = "") -> None:
        super().__init__()
        self._heading = heading
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        from cloudmorrow.tui.widgets.editor import LiveMarkdownEditor

        with Vertical(classes="modal modal-wide", id="task-modal"):
            yield Label(self._heading, classes="modal-title")
            yield Input(value=self._title, placeholder="What needs doing", id="task-title")
            yield Static(
                "[dim]Markdown below. `- [ ]` lines are the subtasks; ctrl+t ticks "
                "one. ctrl+s saves from anywhere in here.[/]",
                classes="modal-detail",
            )
            yield LiveMarkdownEditor(id="task-body")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        from cloudmorrow.tui.widgets.editor import LiveMarkdownEditor

        self.query_one("#task-body", LiveMarkdownEditor).load_text(self._body)
        field = self.query_one("#task-title", Input)
        field.focus()
        field.cursor_position = len(field.value)

    def _collect(self) -> dict | None:
        from cloudmorrow.tui.widgets.editor import LiveMarkdownEditor

        title = self.query_one("#task-title", Input).value.strip()
        if not title:
            # A task with no title is not a task; the editor stays open rather
            # than throwing away whatever body was typed under it.
            self.query_one("#task-title", Input).focus()
            return None
        return {"title": title, "body": self.query_one("#task-body", LiveMarkdownEditor).text}

    def action_save(self) -> None:
        result = self._collect()
        if result is not None:
            self.dismiss(result)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in the title moves to the body rather than saving half a task."""
        from cloudmorrow.tui.widgets.editor import LiveMarkdownEditor

        event.stop()
        self.query_one("#task-body", LiveMarkdownEditor).focus()

    def on_live_markdown_editor_save_requested(self, event) -> None:
        """ctrl+s inside the body saves the task.

        The editor swallows the key and asks for a save instead of letting it
        through, so without this the shortcut works in the title and dies in
        the body — which is where you are when you have finished typing.
        """
        event.stop()
        self.action_save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "save":
            self.action_save()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
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
                "[dim]Served from this machine by its agent, while the agent runs. "
                "Nothing is copied to the server.[/]"
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
