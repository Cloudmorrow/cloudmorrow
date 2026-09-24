"""The dialog that makes a channel: what it is called, and who is in it.

Making a channel is two questions, not one. The name is the easy half; the
half that matters is who can see it, and that has exactly two answers on this
server — everybody, or the people you pick. Asking only for a name meant the
terminal could make one kind of channel and the phone could make both, so
this is the same form the web app puts on a screen, in a box.

Public first, because a house server's rooms are mostly everybody's, and
because a channel that turns out too open is a smaller mistake than one
nobody can find. Picking Private brings up the list of people; picking Public
puts it away again, since everybody is in a public channel by definition and
a list of who to add would be a list of everybody.

Dismisses with {"name", "topic", "kind", "members"}, or None when cancelled.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    Input,
    Label,
    RadioButton,
    RadioSet,
    SelectionList,
    Static,
)

from cloudmorrow.tui.screens.modals import Modal
from cloudmorrow.tui.theme import BAD, MUTED

PUBLIC = "public"
PRIVATE = "private"

KIND_NOTES: dict[str, str] = {
    PUBLIC: (
        "Everybody on this server is in it and can write in it. Nobody has to "
        "be added, and nobody can leave."
    ),
    PRIVATE: (
        "Only the people you tick, and you. They are added rather than invited "
        "— they are told, and they can leave."
    ),
}
NOBODY = (
    "There is nobody else with an account yet. A private channel would be "
    "yours alone; you can add people to it later."
)


class NewChannelModal(Modal[dict | None]):
    """Name a channel, say who can see it, and tick the ones who can.

    *people* is everyone there is to add — the `/api/chat/people` rows,
    `{"username", "display_name"}` — which the pane fetches before opening
    this, because a dialog that asks the server something is a dialog that
    can appear empty and fill in afterwards.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, people: list[dict] | None = None) -> None:
        super().__init__()
        self.people = people or []

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal modal-wide", id="channel-modal"):
            yield Label("New channel", classes="modal-title")
            yield Input(placeholder="name, e.g. homelab", id="channel-name")
            yield Input(placeholder="topic — what it is for (optional)", id="channel-topic")
            yield Static(f"[{MUTED}]who can see it[/]", classes="pane-title")
            with RadioSet(id="channel-kind"):
                yield RadioButton("Public", id="kind-public", value=True)
                yield RadioButton("Private", id="kind-private")
            yield Static(f"[{MUTED}]{KIND_NOTES[PUBLIC]}[/]", id="channel-kind-note")
            with Vertical(id="channel-people"):
                yield Static(f"[{MUTED}]who is in it[/]", classes="pane-title")
                if self.people:
                    yield SelectionList[str](
                        *[
                            (self._label(person), person["username"])
                            for person in self.people
                        ],
                        id="channel-members",
                    )
                    yield Static(
                        f"[{MUTED}]Space ticks the one you are on.[/]",
                        id="channel-people-note",
                    )
                else:
                    yield Static(f"[{MUTED}]{NOBODY}[/]", id="channel-people-note")
            yield Static("", id="channel-complaint")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Create", variant="primary", id="create")

    @staticmethod
    def _label(person: dict) -> str:
        """Their name, with the account name behind it when they differ."""
        username = str(person.get("username", ""))
        shown = str(person.get("display_name") or "").strip()
        return f"{shown} ({username})" if shown and shown != username else username

    def on_mount(self) -> None:
        self._fit()
        self.query_one("#channel-name", Input).focus()

    # -- the kind chosen, and what it means -----------------------------------
    @property
    def kind(self) -> str:
        pressed = self.query_one("#channel-kind", RadioSet).pressed_button
        return PRIVATE if pressed is not None and pressed.id == "kind-private" else PUBLIC

    def _fit(self) -> None:
        """Show the people list for a private channel, and hide it for a public one."""
        kind = self.kind
        self.query_one("#channel-kind-note", Static).update(f"[{MUTED}]{KIND_NOTES[kind]}[/]")
        self.query_one("#channel-people", Vertical).display = kind == PRIVATE

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        event.stop()
        self._fit()

    # -- answering it ----------------------------------------------------------
    def _say(self, complaint: str) -> None:
        self.query_one("#channel-complaint", Static).update(f"[{BAD}]{complaint}[/]")

    def _members(self) -> list[str]:
        if self.kind != PRIVATE or not self.people:
            # Everybody is in a public channel already, so there is nobody to
            # send; a tick made before switching back to Public is not one.
            return []
        return list(self.query_one("#channel-members", SelectionList).selected)

    def _collect(self) -> dict | None:
        name = self.query_one("#channel-name", Input).value.strip()
        if not name:
            self._say("A channel needs a name.")
            self.query_one("#channel-name", Input).focus()
            return None
        return {
            "name": name,
            "topic": self.query_one("#channel-topic", Input).value.strip(),
            "kind": self.kind,
            "members": self._members(),
        }

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter moves down the form rather than making half a channel.

        The name is the first thing typed and the last thing you want enter
        to act on: who can see the channel is below it, and a room made public
        by pressing enter too early is a room you cannot make private again.
        """
        event.stop()
        if event.input.id == "channel-name":
            self.query_one("#channel-topic", Input).focus()
            return
        self.query_one("#channel-kind", RadioSet).focus()

    def action_create(self) -> None:
        collected = self._collect()
        if collected is not None:
            self.dismiss(collected)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "create":
            self.action_create()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
