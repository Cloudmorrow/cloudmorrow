"""The workspace: a tab strip, and one pane's worth of it below.

A tab for each kind of thing there is: your notes, your tasks, your days,
the chat, your secrets, your files. Secrets has your vaults down the left
and the picked one's keys beside them, and Files has two tabs of its own:
this machine's backups, and the fileshares on the server. Your machines are not a tab
either: the agents enrol themselves at sign-in and get on with it, and what
they have done is behind the bell.

An administrator has one more thing on the top bar: Administration, which
puts the whole workspace aside for the server's own panel — the accounts on
it, and which of these tabs it offers at all. A feature switched off
there loses its tab here, for everybody.

Everything here is clickable — the tabs, the rows, the buttons above each pane
— and everything clickable also has a key. Neither way is the "real" one, so
the key is written on the thing it works: beside the tab, on the Settings
button, beside the bell. The bar at the bottom carries a few of the rest.
"""

from __future__ import annotations

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, ContentSwitcher, Static, Tab, Tabs

from cloudmorrow.cli import dev
from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.panes.admin import AdminPanel
from cloudmorrow.tui.panes.base import Pane
from cloudmorrow.tui.panes.calendar import CalendarPane
from cloudmorrow.tui.panes.chat import ChatPane
from cloudmorrow.tui.panes.files import FilesPane
from cloudmorrow.tui.panes.notes import NotesPane
from cloudmorrow.tui.panes.secrets import SecretsPane
from cloudmorrow.tui.panes.tasks import TasksPane
from cloudmorrow.tui.screens.modals import PasswordModal
from cloudmorrow.tui.screens.notifications import (
    NOTIFICATIONS,
    NotificationsScreen,
    bell_label,
    unread_count,
)
from cloudmorrow.tui.screens.settings import SettingsScreen
from cloudmorrow.tui.theme import ACCENT, BAD, MUTED, WARN
from cloudmorrow.tui.widgets.bottombar import BottomBar

PANES: tuple[type[Pane], ...] = (
    NotesPane, TasksPane, CalendarPane, ChatPane, SecretsPane, FilesPane,
)

# How often the bell asks the server whether anything happened.
BELL_POLL = 60.0

# Which server feature each tab belongs to.
FEATURE_OF: dict[str, str] = {
    "notes": "notes",
    "tasks": "tasks",
    "calendar": "calendar",
    "chat": "chat",
    "secrets": "secrets",
    "files": "files",
}


class WorkspaceScreen(Screen):
    """One screen, a tab strip, and whichever pane is showing."""

    # The tabs and the two top-bar buttons wear their own keys, so they are
    # bound but not listed: the bottom bar is for what is not written anywhere else.
    BINDINGS = [
        *(
            Binding(pane.TAB_KEY, f"show_pane('{pane.TAB_LABEL.lower()}')", pane.TAB_LABEL,
                    show=False)
            for pane in PANES
        ),
        Binding("f9", "administration", "Administration", show=False),
        Binding("ctrl+g", "settings", "Settings", show=False),
        Binding("f8", "notifications", "Notifications", show=False),
        ("ctrl+r", "refresh", "Refresh"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._message = ""
        self._error = False
        # Whether the account signed in may administer the server. Asked on
        # mount; until the answer comes back the menu is not there.
        self._admin = False
        # The tabs this server offers, once it has said. None means we have
        # not asked yet, and every key still works.
        self._showing: list[str] | None = None

    # -- layout ------------------------------------------------------------
    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static(self._topbar_text(), id="topbar-left")
            with Horizontal(id="topbar-right"):
                # First on the right, left of Settings, and only for admins:
                # shown when the server says the account is one.
                admin = Button(
                    "⚑ Administration  f9", id="open-admin", compact=True, flat=True
                )
                admin.tooltip = "The server: its accounts, and what it offers"
                admin.display = False
                yield admin
                settings = Button("⚙ Settings  ^g", id="open-settings", compact=True, flat=True)
                settings.tooltip = "This machine, and its Omarchy config"
                yield settings
                account = Button(self._account_text(), id="topbar-account", compact=True, flat=True)
                account.tooltip = "Change your password"
                yield account
                # Last of all, hard against the right edge: the bell.
                bell = Button(
                    bell_label(self.app.unread),
                    id="open-notifications",
                    compact=True,
                    flat=True,
                )
                bell.tooltip = "What the machines have been up to"
                yield bell
        with Vertical(id="main"):
            # The workspace, and the administration panel that replaces it.
            # One of the two is showing; never both.
            with Vertical(id="workspace-view"):
                yield Tabs(
                    *(Tab(self._tab_label(pane), id=self._tab_id(pane)) for pane in PANES),
                    # Notes sits first in the strip, and is where you land.
                    active="tab-notes",
                    id="nav",
                )
                with ContentSwitcher(id="panes", initial="pane-notes"):
                    for pane in PANES:
                        yield pane(id=self._pane_id(pane))
                # What is here when an account has switched every tab off.
                nothing = Static(
                    f"[{MUTED}]Every tab is switched off for this account.[/]\n"
                    f"[{MUTED}]Settings — ^g — is where they come back.[/]",
                    id="nothing-showing",
                )
                nothing.display = False
                yield nothing
            panel = AdminPanel(id="admin-view")
            panel.display = False
            yield panel
        yield BottomBar()

    @staticmethod
    def _key(pane: type[Pane]) -> str:
        return pane.TAB_LABEL.lower()

    @staticmethod
    def _tab_label(pane: type[Pane]) -> Text:
        """The name, and the key that brings it here, dimmed behind it."""
        label = Text(pane.TAB_LABEL)
        label.append(f"  {pane.TAB_KEY}", style="dim")
        return label

    @classmethod
    def _tab_id(cls, pane: type[Pane]) -> str:
        return f"tab-{cls._key(pane)}"

    @classmethod
    def _pane_id(cls, pane: type[Pane]) -> str:
        return f"pane-{cls._key(pane)}"

    def _topbar_text(self) -> str:
        # The name, and nothing else. Running from a checkout looks exactly
        # like running the installed client, which is a good way to wonder
        # why an edit did nothing.
        badge = f" [b {WARN}]dev[/]" if dev.checkout() else ""
        return f" [b {ACCENT}]◈ cloudmorrow[/]{badge}"

    def _account_text(self) -> str:
        user = getattr(self.app, "username", "") or "?"
        host = self.app.client_config.api_url.replace("https://", "").replace("http://", "")
        return f"{user}@{host}"

    def on_mount(self) -> None:
        # The bell is about the machines, not about the tab you are on, so it
        # keeps its own clock rather than waiting for a refresh.
        self.count_unread()
        self.set_interval(BELL_POLL, self.count_unread)
        # Who is signed in, and what this server offers. Both come from the
        # server, so the strip is drawn for what is really there.
        self.ask_the_server()

    # -- what this server is -----------------------------------------------
    @work(exclusive=True, group="whoami")
    async def ask_the_server(self) -> None:
        """Is this account an administrator, and which features are on?"""
        client = self.app.client
        if client is None:
            return
        try:
            me = await client.me()
        except ApiError:
            # Nothing here is worth a red line in the status bar: the tabs
            # work, and whatever is wrong will show up where it is asked for.
            me = {}
        self._admin = bool(me.get("is_admin"))
        self.query_one("#open-admin", Button).display = self._admin
        # This account's own list rather than the server's: it is already
        # narrowed to what this server offers and carries what the account
        # has switched off for itself, so one call answers both questions.
        try:
            features = await client.my_features()
        except ApiError:
            return
        self.apply_features([row["key"] for row in features if row["enabled"]])

    def apply_features(self, enabled: list[str]) -> None:
        """Show the tabs this account has, and hide the rest.

        Called on mount, when an administrator switches one, and when you
        switch one of your own in Settings — so a feature turned off is gone
        from the strip without a restart.
        """
        tabs = self.query_one("#nav", Tabs)
        showing = []
        for pane in PANES:
            key = self._key(pane)
            feature = FEATURE_OF.get(key)
            if feature is None or feature in enabled:
                tabs.show(self._tab_id(pane))
                showing.append(key)
            else:
                tabs.hide(self._tab_id(pane))
        self._showing = showing
        # Switch the last one off in Settings and there is no tab to stand
        # on: say so, rather than leaving a pane up that nothing points at.
        self.query_one("#panes", ContentSwitcher).display = bool(showing)
        self.query_one("#nothing-showing", Static).display = not showing
        # Standing on a tab that has just gone: move to the first one left.
        current = self.query_one("#panes", ContentSwitcher).current or ""
        if showing and current[len("pane-") :] not in showing:
            self.action_show_pane(showing[0])

    # -- administration ----------------------------------------------------
    def action_administration(self) -> None:
        """f9: into the panel, and out of it again."""
        if not self._admin:
            return
        if self.query_one("#admin-view", AdminPanel).display:
            self.close_admin()
        else:
            self.open_admin()

    def open_admin(self) -> None:
        self.query_one("#workspace-view", Vertical).display = False
        panel = self.query_one("#admin-view", AdminPanel)
        panel.display = True
        self.query_one("#open-admin", Button).add_class("-open")
        panel.reload()
        self.set_status()

    def close_admin(self) -> None:
        self.query_one("#admin-view", AdminPanel).display = False
        self.query_one("#workspace-view", Vertical).display = True
        self.query_one("#open-admin", Button).remove_class("-open")
        self.set_status()

    def on_admin_panel_closed(self, event: AdminPanel.Closed) -> None:
        event.stop()
        self.close_admin()

    @property
    def admin_showing(self) -> bool:
        return bool(self.query_one("#admin-view", AdminPanel).display)

    # -- status ------------------------------------------------------------
    def set_status(self, message: str = "", *, error: bool = False) -> None:
        self._message, self._error = message, error
        self.redraw_status()

    def redraw_status(self) -> None:
        detail = ""
        pane = self.active_pane if not self.admin_showing else None
        getter = getattr(pane, "status_detail", None)
        if callable(getter):
            detail = getter()
        colour = BAD if self._error else MUTED
        message = f"[{colour}]{self._message}[/]" if self._message else ""
        parts = [part for part in (detail, message) if part]
        self.query_one(BottomBar).set_text("  ".join(parts))

    # -- notifications -----------------------------------------------------
    def refresh_bell(self) -> None:
        """Redraw the bell — the app calls this when the count changes."""
        unread = self.app.unread
        bell = self.query_one("#open-notifications", Button)
        bell.label = bell_label(unread)
        bell.set_class(bool(unread), "has-unread")

    @work(exclusive=True, group="bell")
    async def count_unread(self) -> None:
        client = self.app.client
        if client is None:
            return
        try:
            notes = await client.notifications(limit=NOTIFICATIONS, unread=True)
        except ApiError:
            # A bell that cannot count is not worth a message in the status
            # bar; whatever went wrong will show up where it was asked for.
            return
        self.app.set_unread(unread_count(notes))

    def action_notifications(self) -> None:
        self.open_notifications()

    def open_notifications(self) -> None:
        self.app.push_screen(NotificationsScreen(), self._notifications_closed)

    def _notifications_closed(self, _result: None) -> None:
        """Marking them read in there is what usually empties the bell."""
        self.count_unread()

    # -- panes -------------------------------------------------------------
    @property
    def active_pane(self) -> Pane | None:
        switcher = self.query_one("#panes", ContentSwitcher)
        current = switcher.current
        return switcher.query_one(f"#{current}", Pane) if current else None

    def action_show_pane(self, key: str) -> None:
        if self._showing is not None and key not in self._showing:
            # The feature is switched off on this server; its key does nothing.
            return
        if self.admin_showing:
            self.close_admin()
        self.query_one("#nav", Tabs).active = f"tab-{key}"

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        event.stop()
        if event.tab is None or not (event.tab.id or "").startswith("tab-"):
            # A pane with tabs of its own is answered there; only the strip
            # across the top switches panes.
            return
        self.query_one("#panes", ContentSwitcher).current = (
            f"pane-{event.tab.id[len('tab-') :]}"
        )
        self.set_status()

    # -- settings ----------------------------------------------------------
    def action_settings(self) -> None:
        self.open_settings()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "open-admin":
            event.stop()
            self.action_administration()
        elif event.button.id == "open-settings":
            event.stop()
            self.open_settings()
        elif event.button.id == "open-notifications":
            event.stop()
            self.open_notifications()
        elif event.button.id == "topbar-account":
            event.stop()
            self.open_password()

    # -- the account -------------------------------------------------------
    def open_password(self) -> None:
        """Your name on the bar is the way to your password."""
        self.app.push_screen(
            PasswordModal(self.app.client.change_password, username=self.app.username),
            self._password_closed,
        )

    def _password_closed(self, changed: bool) -> None:
        if changed:
            self.set_status("Password changed.")

    def open_settings(self) -> None:
        # A callback rather than push_screen_wait: nothing here needs to wait
        # on the answer, and a worker parked for as long as the screen is open
        # is a worker that is in the way.
        self.app.push_screen(SettingsScreen(), self._settings_closed)

    def _settings_closed(self, _result: None) -> None:
        """The feature boxes in there are this account's, and so is the strip."""
        self.ask_the_server()

    def action_refresh(self) -> None:
        if self.admin_showing:
            self.query_one("#admin-view", AdminPanel).reload()
            return
        pane = self.active_pane
        if pane is not None:
            pane.reload()
        self.count_unread()
