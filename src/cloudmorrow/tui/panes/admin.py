"""Administration: the server itself, rather than anything in it.

Everything else in the app is your notes, your tasks, your secrets. This is
the box they sit on: who may sign in, and which parts of Cloudmorrow this
server offers at all. It is one menu on the top bar, and only administrators
see it; opening it puts the whole interface aside, because administering a
server is not a sixth tab of your own stuff.

Three sections so far:

- **Users.** Every account, with its role and its type. The role is what it
  may do — **Administrator**, **User**, or **DashboardDisplayer**, which may
  only show dashboards on a shared screen. The type is what is behind it: a
  **Human** signs in and types, an **Agent** is a program acting for someone,
  and a **SystemsUser** is the machinery itself — the screen in the hallway —
  with nobody behind it.
- **Features.** Notes, Tasks, Projects, Files. Switching one off takes its tab
  out of every client and closes its API — off here is off everywhere, not a
  hidden button.
- **Quills.** The catalog by category: install one after reading what it
  adds, or remove one, keeping its records. In admin_quills.py.
"""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import (
    Button,
    Checkbox,
    ContentSwitcher,
    DataTable,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Static,
)

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.panes.admin_quills import QuillsView
from cloudmorrow.tui.panes.base import Pane
from cloudmorrow.tui.screens.modals import ConfirmModal, Modal
from cloudmorrow.tui.theme import ACCENT, BAD, MUTED, SECOND, WARN
from cloudmorrow.tui.widgets.toolbar import Action

# What the server stores, and what it is called on screen.
ROLES: tuple[tuple[str, str], ...] = (
    ("administrator", "Administrator"),
    ("user", "User"),
    ("dashboard_displayer", "DashboardDisplayer"),
)
USER_TYPES: tuple[tuple[str, str], ...] = (
    ("human", "Human"),
    ("agent", "Agent"),
    ("systems_user", "SystemsUser"),
)
LABELS: dict[str, str] = {key: label for key, label in (*ROLES, *USER_TYPES)}
ROLE_NOTE = (
    "An administrator runs the server. A user has their own notes, tasks and "
    "secrets. A DashboardDisplayer may only show dashboards on a shared screen."
)
TYPE_NOTE = (
    "A human signs in and types. An agent is a program acting for someone. "
    "A SystemsUser is the machinery itself — a screen in the hallway, a "
    "service — with nobody behind it."
)
# The server asks for this much; saying so here beats a 422 from the API.
MIN_PASSWORD = 8


def _short(value: str | None, width: int = 16) -> str:
    return (value or "—")[:width].replace("T", " ")


class UserModal(Modal[dict | None]):
    """Make an account, or change one. The same dialog either way."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, heading: str, *, user: dict | None = None) -> None:
        super().__init__()
        self.heading = heading
        self.user = user or {}
        # Editing: the username is the account's name and does not change.
        self.editing = bool(user)

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal modal-wide", id="user-modal"):
            yield Label(self.heading, classes="modal-title")
            yield Input(
                value=str(self.user.get("username", "")),
                placeholder="username",
                id="user-username",
                disabled=self.editing,
            )
            yield Input(
                value=str(self.user.get("display_name", "")),
                placeholder="display name (optional)",
                id="user-display",
            )
            yield Input(
                placeholder=(
                    "new password (leave blank to keep)"
                    if self.editing
                    else f"password, {MIN_PASSWORD} characters or more"
                ),
                password=True,
                id="user-password",
            )
            yield Static(f"[{MUTED}]role[/]", classes="pane-title")
            with RadioSet(id="user-role"):
                for key, label in ROLES:
                    yield RadioButton(
                        label, id=f"role-{key}", value=self._role() == key
                    )
            yield Static(f"[{MUTED}]{ROLE_NOTE}[/]", id="user-role-note")
            yield Static(f"[{MUTED}]type[/]", classes="pane-title")
            with RadioSet(id="user-type"):
                for key, label in USER_TYPES:
                    yield RadioButton(
                        label, id=f"type-{key}", value=self._type() == key
                    )
            yield Static(f"[{MUTED}]{TYPE_NOTE}[/]", id="user-type-note")
            if self.editing:
                yield Checkbox(
                    "Can sign in",
                    value=bool(self.user.get("is_active", True)),
                    id="user-active",
                )
            yield Static("", id="user-complaint")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="primary", id="save")

    def on_mount(self) -> None:
        target = "#user-display" if self.editing else "#user-username"
        self.query_one(target, Input).focus()

    # -- the account being described ---------------------------------------
    def _role(self) -> str:
        return str(self.user.get("role") or "user")

    def _type(self) -> str:
        return str(self.user.get("user_type") or "human")

    def _chosen(self, group: str, options: tuple[tuple[str, str], ...]) -> str:
        pressed = self.query_one(f"#{group}", RadioSet).pressed_button
        if pressed is None or not pressed.id:
            return options[-1][0]
        return pressed.id.split("-", 1)[1]

    def _say(self, complaint: str) -> None:
        self.query_one("#user-complaint", Static).update(f"[{BAD}]{complaint}[/]")

    def _collect(self) -> dict | None:
        username = self.query_one("#user-username", Input).value.strip().lower()
        password = self.query_one("#user-password", Input).value
        if not username:
            self._say("An account needs a username.")
            return None
        if not self.editing and not password:
            self._say("A new account needs a password.")
            return None
        if password and len(password) < MIN_PASSWORD:
            self._say(f"A password is {MIN_PASSWORD} characters or more.")
            return None
        collected = {
            "username": username,
            "display_name": self.query_one("#user-display", Input).value.strip(),
            "password": password,
            "role": self._chosen("user-role", ROLES),
            "user_type": self._chosen("user-type", USER_TYPES),
        }
        if self.editing:
            collected["is_active"] = self.query_one("#user-active", Checkbox).value
        return collected

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_save()

    def action_save(self) -> None:
        collected = self._collect()
        if collected is not None:
            self.dismiss(collected)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "save":
            self.action_save()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class UsersView(Pane):
    """Every account on the server, and what it may do."""

    TAB_LABEL = "Users"
    SUMMARY = "who may sign in, and what they may do"
    BINDINGS = [
        ("n", "fire('new')", "New user"),
        ("e", "fire('edit')", "Edit"),
        ("d", "fire('remove')", "Delete"),
    ]
    ACTIONS = (
        Action("new", "New user", "n", variant="primary", hint="Add an account"),
        Action("edit", "Edit", "e", hint="Name, password, role and type"),
        Action("remove", "Delete", "d", variant="error"),
    )

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._users: list[dict] = []

    def content(self) -> ComposeResult:
        yield DataTable(id="admin-user-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        self.query_one("#admin-user-table", DataTable).add_columns(
            "ACCOUNT", "NAME", "ROLE", "TYPE", "SIGNS IN", "SINCE"
        )

    def on_show(self) -> None:
        self.reload()

    # -- data --------------------------------------------------------------
    @property
    def selected(self) -> dict | None:
        table = self.query_one("#admin-user-table", DataTable)
        if not self._users or not 0 <= table.cursor_row < len(self._users):
            return None
        return self._users[table.cursor_row]

    @work(exclusive=True, group="admin-users")
    async def reload(self) -> None:
        client = self.api
        if client is None:
            return
        try:
            self._users = await client.users()
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        table = self.query_one("#admin-user-table", DataTable)
        row = table.cursor_row
        table.clear()
        for user in self._users:
            table.add_row(*self._row(user))
        if self._users:
            table.move_cursor(row=min(max(row, 0), len(self._users) - 1))
        self.status(f"{len(self._users)} accounts", note=True)

    @staticmethod
    def _row(user: dict) -> tuple[str, ...]:
        role = str(user.get("role") or ("administrator" if user.get("is_admin") else "user"))
        kind = str(user.get("user_type") or "human")
        colours = {
            "administrator": ACCENT,
            "dashboard_displayer": SECOND,
            "agent": WARN,
            "systems_user": SECOND,
        }
        return (
            f"[b]{user['username']}[/]",
            user.get("display_name") or f"[{MUTED}]—[/]",
            f"[{colours.get(role, MUTED)}]{LABELS.get(role, role)}[/]",
            f"[{colours.get(kind, MUTED)}]{LABELS.get(kind, kind)}[/]",
            "yes" if user.get("is_active", True) else f"[{BAD}]no[/]",
            _short(user.get("created_at")),
        )

    # -- actions -----------------------------------------------------------
    def act_refresh(self) -> None:
        self.reload()

    def act_new(self) -> None:
        self.new_user()

    @work(group="ui")
    async def new_user(self) -> None:
        wanted = await self.app.push_screen_wait(UserModal("New user"))
        if wanted is None:
            return
        try:
            user = await self.api.create_user(
                wanted["username"],
                wanted["password"],
                display_name=wanted["display_name"],
                role=wanted["role"],
                user_type=wanted["user_type"],
            )
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        role = user.get("role", "user")
        self.status(f"Added {user['username']} as {LABELS.get(role, role)}.")
        self.reload()

    def act_edit(self) -> None:
        self.edit_user()

    @work(group="ui")
    async def edit_user(self) -> None:
        user = self.selected
        if user is None:
            self.status("No account selected.", error=True)
            return
        wanted = await self.app.push_screen_wait(
            UserModal(f"Edit {user['username']}", user=user)
        )
        if wanted is None:
            return
        fields: dict[str, object] = {
            "display_name": wanted["display_name"],
            "role": wanted["role"],
            "user_type": wanted["user_type"],
            "is_active": wanted["is_active"],
        }
        # A blank password box means "leave it alone", not "no password".
        if wanted["password"]:
            fields["password"] = wanted["password"]
        try:
            await self.api.update_user(user["username"], **fields)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.status(f"Saved {user['username']}.")
        self.reload()

    def act_remove(self) -> None:
        self.remove_user()

    @work(group="ui")
    async def remove_user(self) -> None:
        user = self.selected
        if user is None:
            return
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(
                "Delete this account?",
                detail=(
                    f"[b]{user['username']}[/]\n"
                    "Signing in stops at once. Their notes and files stay on "
                    "the disc, under their name."
                ),
                confirm_label="Delete",
            )
        )
        if not confirmed:
            return
        try:
            await self.api.delete_user(user["username"])
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.status(f"Deleted {user['username']}.")
        self.reload()


class FeaturesView(Pane):
    """What this server offers. A tick box each, and off means off."""

    TAB_LABEL = "Features"
    SUMMARY = "what this server offers"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # What the server last told us, keyed by feature.
        self._features: dict[str, dict] = {}

    def content(self) -> ComposeResult:
        yield Static(
            f"[{MUTED}]Switching a feature off takes its tab out of every client "
            f"and closes its part of the API.[/]",
            id="admin-features-note",
        )
        yield VerticalScroll(id="admin-feature-list")

    def on_show(self) -> None:
        self.reload()

    @work(exclusive=True, group="admin-features")
    async def reload(self) -> None:
        client = self.api
        if client is None:
            return
        try:
            features = await client.features()
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self._features = {feature["key"]: feature for feature in features}
        box = self.query_one("#admin-feature-list", VerticalScroll)
        await box.remove_children()
        for feature in features:
            await box.mount(self._row(feature))

    @staticmethod
    def _row(feature: dict) -> Vertical:
        turned = ""
        if feature.get("changed_by"):
            state = "on" if feature["enabled"] else "off"
            turned = (
                f"  ·  switched {state} by {feature['changed_by']}"
                f" {_short(feature.get('updated_at'))}"
            )
        row = Vertical(
            Checkbox(
                feature["label"], value=feature["enabled"], id=f"feature-{feature['key']}"
            ),
            Static(f"[{MUTED}]{feature['description']}{turned}[/]", classes="feature-note"),
            classes="feature-row",
        )
        return row

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Only a tick from you goes to the server; drawing one does not."""
        event.stop()
        box_id = event.checkbox.id or ""
        if not box_id.startswith("feature-"):
            return
        key = box_id[len("feature-") :]
        known = self._features.get(key)
        if known is None or event.value == known["enabled"]:
            return
        self.switch(key, event.value)

    @work(group="admin-features-write")
    async def switch(self, key: str, enabled: bool) -> None:
        try:
            feature = await self.api.set_feature(key, enabled)
        except ApiError as exc:
            self.status(str(exc), error=True)
            self.reload()
            return
        self._features[key] = feature
        self.status(
            f"{feature['label']} is "
            + ("on." if feature["enabled"] else "off — its tab is gone everywhere.")
        )
        # The tab strip behind this panel follows. It is asked for again
        # rather than set from this list: the strip is what *this account*
        # has, and an account can have switched off for itself something
        # the server has just switched back on.
        again = getattr(self.screen, "ask_the_server", None)
        if callable(again):
            again()
            return
        applier = getattr(self.screen, "apply_features", None)
        if callable(applier):
            applier([row["key"] for row in self._features.values() if row["enabled"]])


class AdminPanel(Vertical):
    """The whole administration interface: one of its sections at a time.

    Which one is chosen from the ADMINISTRATION cards in the sidebar; the
    panel itself is only the switcher behind them.
    """

    class Closed(Message):
        """Back to the workspace."""

    VIEWS: tuple[type[Pane], ...] = (UsersView, FeaturesView, QuillsView)

    def compose(self) -> ComposeResult:
        with ContentSwitcher(id="admin-views", initial="admin-view-users"):
            for view in self.VIEWS:
                yield view(id=self._view_id(view))

    @staticmethod
    def key(view: type[Pane]) -> str:
        return view.TAB_LABEL.lower()

    @classmethod
    def _view_id(cls, view: type[Pane]) -> str:
        return f"admin-view-{cls.key(view)}"

    @property
    def current(self) -> str:
        """The section showing: users, features or quills."""
        return (self.query_one("#admin-views", ContentSwitcher).current or "")[
            len("admin-view-") :
        ]

    @property
    def active_view(self) -> Pane | None:
        switcher = self.query_one("#admin-views", ContentSwitcher)
        current = switcher.current
        return switcher.query_one(f"#{current}", Pane) if current else None

    def show_view(self, key: str) -> None:
        switcher = self.query_one("#admin-views", ContentSwitcher)
        if switcher.current != f"admin-view-{key}":
            switcher.current = f"admin-view-{key}"
        else:
            self.reload()

    def reload(self) -> None:
        view = self.active_view
        if view is not None:
            view.reload()
