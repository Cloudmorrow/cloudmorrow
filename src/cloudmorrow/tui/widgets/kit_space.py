"""Spaces in the terminal's kit: making one, and picking the people in it.

A channel, a shared calendar — any datamodel that is a `space` — is made the
same way and has people put in it the same way, so the dialogs for both are
here once, for every kit pane that has spaces:

- `NewSpaceModal` asks what the space is called, its other plain fields, who
  can see it (a scope, named the way the screen's `made_as` names it), and,
  for a shared one, the people in it. It dismisses with
  `{"fields", "scope", "members"}`, ready for `create_record`, or None.
- `PickPersonModal` is a list of people to choose one from — whom to write
  to, whom to add. It dismisses with a username, or None.

And the words a pane needs about a space: `space_name` (what it is called to
the person looking, which for a space made between people is whoever else is
in it), `is_between`, `people_in`, `made_as`.

Nothing here knows what a channel is; it reads the datamodel and the screen.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    Input,
    Label,
    OptionList,
    RadioButton,
    RadioSet,
    SelectionList,
    Static,
)
from textual.widgets.option_list import Option

from cloudmorrow.tui.screens.modals import Modal
from cloudmorrow.tui.theme import BAD, MUTED

# What each scope means, said to the person choosing it.
SCOPE_WORDS: dict[str, tuple[str, str]] = {
    "public": ("Public", "Everybody on this server is in it and can write in it. Nobody leaves."),
    "shared": (
        "Private",
        "Only the people you tick, and you. They are added rather than invited — "
        "they are told, and they can leave.",
    ),
    "personal": ("Only you", "Nobody else sees it."),
}
NOBODY = "There is nobody else with an account yet; you can add people later."
TYPED_KINDS = ("string", "text", "markdown", "url", "email", "phone")


def made_as(screen: dict) -> dict[str, dict]:
    """How the screen says spaces are made: scope (or `direct`) → the fields it sets."""
    return dict(screen.get("made_as") or {})


def is_between(screen: dict, space: dict | None) -> bool:
    """Is this a space made between people, named for whoever else is in it?"""
    marks = made_as(screen).get("direct") or {}
    fields = (space or {}).get("fields") or {}
    return bool(marks) and space is not None and all(fields.get(k) == v for k, v in marks.items())


def people_in(space: dict) -> list[str]:
    """Everybody in a space: its owner, then the people added to it."""
    return [space.get("owner", ""), *(space.get("members") or [])]


def space_name(model: dict, space: dict, screen: dict, me: str) -> str:
    """What a space is called, to whoever is looking."""
    if is_between(screen, space):
        others = [who for who in people_in(space) if who != me]
        return ", ".join(others) or me
    fields = space.get("fields") or {}
    return str(fields.get(model.get("title") or "name") or "").strip() or "Untitled"


def person_label(person: dict) -> str:
    """Their name, with the account name behind it when they differ."""
    username = str(person.get("username", ""))
    shown = str(person.get("display_name") or "").strip()
    return f"{shown} ({username})" if shown and shown != username else username


def scopes_for(model: dict, screen: dict) -> list[str]:
    """The scopes a new space may be made as: `made_as`'s, else the datamodel's."""
    made = [how for how in made_as(screen) if how != "direct"]
    scopes = list(model.get("scopes") or ["shared"])
    return [s for s in (made or scopes) if s in scopes]


def scope_label(model: dict, screen: dict, scope: str) -> str:
    """A scope's name: the label of the enum value `made_as` gives it, when it gives one."""
    for name, value in (made_as(screen).get(scope) or {}).items():
        field = next((f for f in model.get("fields", []) if f["name"] == name), None)
        if field and field.get("kind") == "enum" and value in field.get("values", []):
            labels = field.get("labels") or field["values"]
            return str(labels[field["values"].index(value)])
    return SCOPE_WORDS.get(scope, (scope.title(), ""))[0]


class NewSpaceModal(Modal[dict | None]):
    """Name a space, say who can see it, and tick the people who can.

    *people* is everyone there is to add (`GET /api/people`), fetched by the
    pane before this opens, so the list is there the moment the box is.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    NewSpaceModal #space-modal Input { margin-bottom: 1; }
    NewSpaceModal #space-scope {
        width: 100%; height: auto; layout: horizontal;
        border: none; padding: 0; background: transparent;
    }
    NewSpaceModal #space-scope RadioButton {
        width: auto; margin-right: 2; background: transparent; border: none; padding: 0;
    }
    NewSpaceModal #space-scope-note { height: auto; margin-bottom: 1; }
    NewSpaceModal #space-people { height: auto; }
    NewSpaceModal #space-members {
        height: auto; max-height: 8; border: none; padding: 0; background: transparent;
    }
    NewSpaceModal #space-people-note, NewSpaceModal #space-complaint { height: auto; }
    """

    def __init__(self, model: dict, screen: dict, people: list[dict] | None = None) -> None:
        super().__init__()
        self.model = model
        self.screen_spec = screen
        self.people = people or []
        self.scopes = scopes_for(model, screen)
        self.title_field = model.get("title") or "name"
        taken = {name for fields in made_as(screen).values() for name in fields}
        self.extra = [
            f for f in model.get("fields", [])
            if f["name"] != self.title_field and f["name"] not in taken
            and f.get("kind") in TYPED_KINDS and not f.get("stamp")
        ]

    @property
    def noun(self) -> str:
        return str(self.model.get("label") or self.model.get("id") or "space").lower()

    def compose(self) -> ComposeResult:
        title = next((f for f in self.model.get("fields", []) if f["name"] == self.title_field), {})
        with Vertical(classes="modal modal-wide", id="space-modal"):
            yield Label(f"New {self.noun}", classes="modal-title")
            yield Input(placeholder=str(title.get("label") or "Name").lower(), id="space-title")
            for field in self.extra:
                yield Input(
                    placeholder=f"{str(field.get('label') or field['name']).lower()} (optional)",
                    id=f"space-field-{field['name']}",
                )
            if len(self.scopes) > 1:
                yield Static(f"[{MUTED}]who can see it[/]", classes="pane-title")
                with RadioSet(id="space-scope"):
                    for index, scope in enumerate(self.scopes):
                        yield RadioButton(
                            scope_label(self.model, self.screen_spec, scope),
                            id=f"scope-{scope}",
                            value=index == 0,
                        )
            yield Static("", id="space-scope-note")
            with Vertical(id="space-people"):
                yield Static(f"[{MUTED}]who is in it[/]", classes="pane-title")
                if self.people:
                    yield SelectionList[str](
                        *[(person_label(p), p["username"]) for p in self.people],
                        id="space-members",
                    )
                    yield Static(f"[{MUTED}]Space ticks the one you are on.[/]", id="space-people-note")
                else:
                    yield Static(f"[{MUTED}]{NOBODY}[/]", id="space-people-note")
            yield Static("", id="space-complaint")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Create", variant="primary", id="create")

    def on_mount(self) -> None:
        self._fit()
        self.query_one("#space-title", Input).focus()

    @property
    def scope(self) -> str:
        if len(self.scopes) <= 1:
            return self.scopes[0] if self.scopes else "shared"
        pressed = self.query_one("#space-scope", RadioSet).pressed_button
        if pressed is None or not pressed.id:
            return self.scopes[0]
        return pressed.id.removeprefix("scope-")

    def _fit(self) -> None:
        """The people for a shared space, and not for any other."""
        scope = self.scope
        note = SCOPE_WORDS.get(scope, ("", ""))[1]
        self.query_one("#space-scope-note", Static).update(f"[{MUTED}]{note}[/]")
        self.query_one("#space-people", Vertical).display = scope == "shared"

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        event.stop()
        self._fit()

    def _members(self) -> list[str]:
        # A tick made before switching away from a shared space is not one.
        if self.scope != "shared" or not self.people:
            return []
        return list(self.query_one("#space-members", SelectionList).selected)

    def _collect(self) -> dict | None:
        name = self.query_one("#space-title", Input).value.strip()
        if not name:
            self.query_one("#space-complaint", Static).update(f"[{BAD}]A {self.noun} needs a name.[/]")
            self.query_one("#space-title", Input).focus()
            return None
        scope = self.scope
        fields = {self.title_field: name, **(made_as(self.screen_spec).get(scope) or {})}
        for field in self.extra:
            value = self.query_one(f"#space-field-{field['name']}", Input).value.strip()
            if value:
                fields[field["name"]] = value
        return {"fields": fields, "scope": scope, "members": self._members()}

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter moves down the form rather than making half a space.

        Who can see it is below the name, and a room made public by pressing
        enter too early is a room you cannot make private again.
        """
        event.stop()
        self.focus_next()

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


class PickPersonModal(Modal[str | None]):
    """One person out of a list: whom to write to, or whom to add."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    PickPersonModal #person-list { height: auto; max-height: 12; margin-bottom: 1; }
    """

    def __init__(self, title: str, people: list[dict], *, detail: str = "") -> None:
        super().__init__()
        self._title = title
        self.people = people
        self._detail = detail

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal", id="person-modal"):
            yield Label(self._title, classes="modal-title")
            if self._detail:
                yield Static(self._detail, classes="modal-detail")
            if self.people:
                yield OptionList(
                    *[Option(person_label(p), id=p["username"]) for p in self.people],
                    id="person-list",
                )
            else:
                yield Static(f"[{MUTED}]Nobody to pick.[/]")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        if self.people:
            self.query_one("#person-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(event.option.id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
