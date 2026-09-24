"""A row of buttons that is also a row of shortcuts.

Every action in the workspace is a button you can click and a key you can
press, and this is what keeps the two spellings of it in one place: the button
label carries the key, and pressing the button runs the same action.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button


@dataclass(frozen=True, slots=True)
class Action:
    """One thing a pane can do."""

    id: str
    label: str
    key: str = ""
    variant: str = "default"
    # Shown in the tooltip; the label stays short.
    hint: str = ""


class Toolbar(Horizontal):
    """The buttons above a pane's content."""

    class Fired(Message):
        def __init__(self, action: str) -> None:
            self.action = action
            super().__init__()

    def __init__(self, actions: list[Action], **kwargs) -> None:
        super().__init__(**kwargs)
        self.actions = actions
        self.add_class("toolbar")

    def compose(self) -> ComposeResult:
        for action in self.actions:
            button = Button(
                f"{action.label}  {action.key}" if action.key else action.label,
                id=f"do-{action.id}",
                variant=action.variant,
                compact=True,
            )
            button.tooltip = action.hint or action.label
            yield button

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id and event.button.id.startswith("do-"):
            self.post_message(self.Fired(event.button.id[len("do-") :]))
