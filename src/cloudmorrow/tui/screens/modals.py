"""Small modal dialogs: prompt, confirm, conflict and search.

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
    """Full-text search; dismisses with the path of the page chosen."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, search_callback: Any, *, title: str = "Search notes") -> None:
        super().__init__()
        self._search = search_callback
        self._title = title
        self._paths: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal modal-wide"):
            yield Label(self._title, classes="modal-title")
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
            await results_view.append(ListItem(Static(f"[b]{result['path']}[/]\n[dim]{first[:120]}[/]")))

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
