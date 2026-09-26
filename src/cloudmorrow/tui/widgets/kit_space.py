"""Spaces in the terminal's kit: making one, and who is in one.

A space is a record more than one person may be in — a calendar, a channel
(docs/QUILLS.md, *Spaces*): personal, its owner's alone; shared, its owner's
and its members'; public, everybody's. Any kit pane that draws things in
spaces uses these rather than its own:

- `NewSpaceModal` asks for a name, the space's other plain fields, who can
  see it, and — for a shared one — who is in it. It dismisses with
  `{"name", "fields", "scope", "members"}`; `make_space` then makes it.
- `SpaceModal` is a space's people: who can see it, who is in it, adding
  somebody, taking somebody out, and leaving. It talks to the server itself,
  as the record sheet does, and says what went wrong with the dialog open.
- `PickPersonModal` is one person out of a list: whom to write to, whom to add.

A screen may say how its spaces are made in `made_as`: scope (or `direct`, a
shared space found-or-made between you and the person you pick) → the fields
a space gets that way. `made_as`, `is_between`, `people_in` and `space_name`
read it; a space made between people is called after whoever else is in it.

Nothing here knows what a space is for: the words come from the datamodel's
label and the screen, and `scope`, `members`, `owner` and `can_manage` are
what the record API sends for every space.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    OptionList,
    RadioButton,
    RadioSet,
    Select,
    Static,
)
from textual.widgets.option_list import Option

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.screens.modals import ConfirmModal, Modal
from cloudmorrow.tui.theme import BAD, MUTED, SECOND
from cloudmorrow.tui.widgets.kit import safe_id, title_of

# What each scope is called, and means, to the person choosing it.
SCOPE_WORDS = {
    "shared": ("Shared", "only the people you pick; they are added, not invited, and can leave"),
    "public": ("Everybody's", "everyone here sees it and can put things in it; nobody leaves"),
    "personal": ("Yours", "only you"),
}
# Longer words about a space — a topic, a description — are asked for when it
# is made; a short string is more often something the screen sets itself.
TYPED_KINDS = ("text", "markdown")


# -- reading a space ---------------------------------------------------------------------
def made_as(screen: dict | None) -> dict[str, dict]:
    """How the screen says spaces are made: scope (or `direct`) → the fields it sets."""
    return dict((screen or {}).get("made_as") or {})


def is_between(screen: dict | None, space: dict | None) -> bool:
    """Is this a space made between people, named for whoever else is in it?"""
    marks = made_as(screen).get("direct") or {}
    fields = (space or {}).get("fields") or {}
    return bool(marks) and space is not None and all(fields.get(k) == v for k, v in marks.items())


def people_in(space: dict) -> list[str]:
    """Everybody in a space: its owner, then the people added to it."""
    return [space.get("owner", ""), *(space.get("members") or [])]


def space_name(model: dict, space: dict, screen: dict | None, me: str) -> str:
    """What a space is called, to whoever is looking."""
    if is_between(screen, space):
        others = [who for who in people_in(space) if who != me]
        return ", ".join(others) or me
    fields = space.get("fields") or {}
    return str(fields.get(model.get("title") or "name") or "").strip() or "Untitled"


def scope_said(record: dict) -> str:
    """Who can see a space, in a few words."""
    scope = record.get("scope")
    if scope == "personal":
        return "only you"
    if scope == "public":
        return "everyone"
    count = len(record.get("members") or []) + 1
    return f"{count} {'person' if count == 1 else 'people'}"


def person_label(person: dict) -> str:
    """Their name, with the account name behind it when they differ."""
    username = str(person.get("username", ""))
    shown = str(person.get("display_name") or "").strip()
    return f"{shown} ({username})" if shown and shown != username else username


def scopes_for(model: dict, screen: dict | None = None) -> list[str]:
    """The scopes a new space may be made as: `made_as`'s, in its order, else the
    datamodel's shared and public ones — a personal space is seeded, not made."""
    scopes = list(model.get("scopes") or ["shared"])
    made = [how for how in made_as(screen) if how != "direct"]
    wanted = made or [s for s in scopes if s != "personal"]
    return [s for s in wanted if s in scopes] or ["shared"]


def scope_label(model: dict, screen: dict | None, scope: str) -> str:
    """A scope's name: the label of the enum value `made_as` gives it, when it gives one."""
    for name, value in (made_as(screen).get(scope) or {}).items():
        field = next((f for f in model.get("fields", []) if f["name"] == name), None)
        if field and field.get("kind") == "enum" and value in field.get("values", []):
            labels = field.get("labels") or field["values"]
            return str(labels[field["values"].index(value)])
    return SCOPE_WORDS.get(scope, (scope.title(), ""))[0]


def _escape(text: object) -> str:
    return str(text or "").replace("[", r"\[")


async def make_space(client: Any, model: dict, answers: dict, extra: dict | None = None) -> dict:
    """Make the space *NewSpaceModal* asked for, and put its people in it."""
    title = model.get("title") or "name"
    fields = {**(extra or {}), **(answers.get("fields") or {}), title: answers["name"]}
    made = await client.create_record(model["id"], fields, scope=answers["scope"])
    for username in answers.get("members") or []:
        made = await client.add_member(model["id"], made["id"], username)
    return made


# -- making one ----------------------------------------------------------------------------
class NewSpaceModal(Modal[dict | None]):
    """A name, its other fields, who can see it, and who is in it.

    *people* is everyone there is to add (`GET /api/people`), fetched by the
    pane before this opens, so the list is there the moment the box is;
    *screen* is the screen making it, whose `made_as` says what each scope
    is called and sets. Dismisses with `{"name", "fields", "scope",
    "members"}` — `fields` already holding the name — or None.
    """

    BINDINGS = [("escape", "cancel", "Cancel"), ("ctrl+s", "save", "Make it")]

    def __init__(self, model: dict, people: list[dict] | None = None, *, screen: dict | None = None) -> None:
        super().__init__()
        self.model = model
        self.people = people or []
        self.screen_spec = screen or {}
        self.scopes = scopes_for(model, self.screen_spec)
        self.noun = str(model.get("label") or model.get("id") or "space").lower()
        self.title_field = model.get("title") or "name"
        taken = {name for fields in made_as(self.screen_spec).values() for name in fields}
        self.extra = [
            f for f in model.get("fields", [])
            if f["name"] != self.title_field and f["name"] not in taken
            and f.get("kind") in TYPED_KINDS and not f.get("stamp")
        ]

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal modal-wide", id="new-space"):
            yield Label(f"New {self.noun}", classes="modal-title")
            yield Input(placeholder="Name", id="space-name")
            for field in self.extra:
                yield Input(
                    placeholder=f"{field.get('label') or field['name']} (optional)",
                    id=f"space-field-{safe_id(field['name'])}",
                )
            if len(self.scopes) > 1:
                yield Static(f"[{MUTED}]who can see it[/]", classes="pane-title")
                yield RadioSet(
                    *(
                        RadioButton(
                            f"{_escape(scope_label(self.model, self.screen_spec, s))}"
                            f"  [{MUTED}]{SCOPE_WORDS.get(s, ('', ''))[1]}[/]",
                            value=index == 0,
                            id=f"scope-{safe_id(s)}",
                        )
                        for index, s in enumerate(self.scopes)
                    ),
                    id="space-scope",
                    compact=True,
                )
            with Vertical(id="space-people"):
                yield Static(f"[{MUTED}]who is in it[/]", classes="pane-title")
                if not self.people:
                    yield Static(f"[{MUTED}]Nobody else yet — make an account for them first.[/]")
                with VerticalScroll(id="space-people-list"):
                    for person in self.people:
                        name = person.get("display_name") or person["username"]
                        yield Checkbox(
                            f"{_escape(name)}  [{MUTED}]{_escape(person['username'])}[/]",
                            id=f"person-{safe_id(person['username'])}",
                            compact=True,
                        )
            yield Static("", id="space-complaint", classes="modal-detail")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button(f"Make the {self.noun}", variant="primary", id="save")

    def on_mount(self) -> None:
        self.query_one("#space-name", Input).focus()
        self._show_people()

    def _scope(self) -> str:
        if len(self.scopes) == 1:
            return self.scopes[0]
        index = self.query_one("#space-scope", RadioSet).pressed_index
        return self.scopes[index] if 0 <= index < len(self.scopes) else self.scopes[0]

    @property
    def scope(self) -> str:
        return self._scope()

    def _show_people(self) -> None:
        self.query_one("#space-people").display = self._scope() == "shared"

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        event.stop()
        self._show_people()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in the name makes it, when there is nothing else to type;
        otherwise it moves on, rather than making half a space."""
        event.stop()
        if self.extra and event.input.id == "space-name":
            self.focus_next()
            return
        self.action_save()

    def action_save(self) -> None:
        name = self.query_one("#space-name", Input).value.strip()
        if not name:
            self.query_one("#space-complaint", Static).update(f"[{BAD}]It needs a name.[/]")
            self.query_one("#space-name", Input).focus()
            return
        scope = self._scope()
        # A tick made before switching away from a shared one is not one.
        members = []
        if scope == "shared":
            members = [
                person["username"]
                for person in self.people
                if self.query_one(f"#person-{safe_id(person['username'])}", Checkbox).value
            ]
        fields = {**(made_as(self.screen_spec).get(scope) or {}), self.title_field: name}
        for field in self.extra:
            value = self.query_one(f"#space-field-{safe_id(field['name'])}", Input).value.strip()
            if value:
                fields[field["name"]] = value
        self.dismiss({"name": name, "fields": fields, "scope": scope, "members": members})

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "save":
            self.action_save()
        else:
            self.dismiss(None)


# -- who is in one ---------------------------------------------------------------------------
class SpaceModal(Modal[str | None]):
    """A space's people: who is in it, adding and taking out, and leaving.

    Dismisses with "left" when you left it, "changed" when anybody was added
    or taken out, and None when nothing happened.
    """

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, client: Any, model: dict, space: dict, people: list[dict], *, me: str) -> None:
        super().__init__()
        self.client = client
        self.model = model
        self.space = space
        self.people = people
        self.me = me
        self.changed = False
        self.noun = str(model.get("label") or model.get("id") or "space").lower()

    @property
    def shared(self) -> bool:
        return self.space.get("scope") == "shared"

    @property
    def inside(self) -> list[str]:
        return people_in(self.space)

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal modal-wide", id="space-modal"):
            yield Label(title_of(self.space, self.model), classes="modal-title", id="space-title")
            yield Static("", id="space-scope-line", classes="modal-detail")
            yield VerticalScroll(id="space-members")
            with Horizontal(id="space-add"):
                yield Select([], prompt="Share it with…", id="space-add-who", compact=True)
                yield Button("Add", id="space-add-button", compact=True)
            yield Static("", id="space-complaint", classes="modal-detail")
            with Horizontal(classes="modal-buttons"):
                yield Button(f"Leave this {self.noun}", variant="error", id="space-leave")
                yield Button("Close", variant="primary", id="close")

    async def on_mount(self) -> None:
        await self.draw()

    async def draw(self) -> None:
        owner = self.space["owner"]
        whose = "you made it" if owner == self.me else f"{_escape(owner)} made it"
        self.query_one("#space-scope-line", Static).update(
            f"[{MUTED}]{scope_said(self.space)}"
            + ("" if self.space.get("scope") == "public" else f" · {whose}")
            + "[/]"
        )
        box = self.query_one("#space-members", VerticalScroll)
        await box.remove_children()
        box.display = self.shared
        for name in self.inside:
            said = f"[{SECOND}]{_escape(name)}[/]" if name == self.me else _escape(name)
            if name == owner:
                said += f"  [{MUTED}]made it[/]"
            parts: list = [Static(said, classes="space-member-name")]
            if self.space.get("can_manage") and name != owner:
                parts.append(Button("Take out", id=f"out-{safe_id(name)}",
                                    classes="space-take-out", compact=True))
            await box.mount(Horizontal(*parts, classes="space-member"))
        outside = [p for p in self.people if p["username"] not in self.inside]
        may_add = self.shared and (self.space.get("can_manage") or self.me in self.inside)
        adder = self.query_one("#space-add")
        adder.display = bool(may_add and outside)
        self.query_one("#space-add-who", Select).set_options(
            [(p.get("display_name") or p["username"], p["username"]) for p in outside]
        )
        self.query_one("#space-leave", Button).display = self.shared and owner != self.me

    def _say(self, message: str) -> None:
        self.query_one("#space-complaint", Static).update(f"[{BAD}]{message}[/]" if message else "")

    async def _refresh(self) -> None:
        self.space = await self.client.record(self.model["id"], self.space["id"])
        await self.draw()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button = event.button.id or ""
        if button == "close":
            self.action_close()
        elif button == "space-add-button":
            await self.add()
        elif button == "space-leave":
            self.app.push_screen(
                ConfirmModal(
                    f"Leave {title_of(self.space, self.model)}?",
                    detail="You will stop seeing what is in it. Somebody in it can add you back.",
                    confirm_label="Leave",
                ),
                self._leave,
            )
        elif button.startswith("out-"):
            name = next((n for n in self.inside if f"out-{safe_id(n)}" == button), None)
            if name is not None:
                await self.take_out(name)

    async def add(self) -> None:
        chosen = self.query_one("#space-add-who", Select)
        if chosen.is_blank():
            self._say("Pick somebody first.")
            return
        try:
            self.space = await self.client.add_member(
                self.model["id"], self.space["id"], str(chosen.value)
            )
        except ApiError as exc:
            self._say(str(exc))
            return
        self.changed = True
        self._say("")
        await self.draw()

    async def take_out(self, username: str) -> None:
        try:
            await self.client.remove_member(self.model["id"], self.space["id"], username)
            await self._refresh()
        except ApiError as exc:
            self._say(str(exc))
            return
        self.changed = True

    async def _leave(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        try:
            await self.client.remove_member(self.model["id"], self.space["id"], self.me)
        except ApiError as exc:
            self._say(str(exc))
            return
        self.dismiss("left")

    def action_close(self) -> None:
        self.dismiss("changed" if self.changed else None)


# -- one person ------------------------------------------------------------------------------
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


__all__ = [
    "NewSpaceModal", "PickPersonModal", "SpaceModal", "is_between", "made_as", "make_space",
    "people_in", "person_label", "scope_label", "scope_said", "scopes_for", "space_name",
]
