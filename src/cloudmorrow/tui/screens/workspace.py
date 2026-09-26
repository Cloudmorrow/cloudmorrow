"""The workspace: a header, a sidebar of places, one panel, and a log.

    ▄▀▀▀▄ █     ▄▀▀▀▄ …        BRAM'S CLOUD · cloudmorrow
    (the pixel wordmark)       bram@cm.example.org   ⚙ Settings ^g
                               server ● connected    🔔 1  f8
    YOUR CLOUD        ╭──────────────────────────────────────────╮
    ╭ Notes ───────╮  │ Notes  your notes, in Markdown   read 12:03 │
    │ ● 12 notes   │  │ [New note ^n]  Rename  Delete              │
    ╰───────── f1 ╯  │ …                                          │
    QUILLS            ╰──────────────────────────────────────────╯
    ╭ Tasks ───────╮  ╭ LOG ─────────────────────────────────────╮
    │ ● 3 to do    │  │ 12:03:04 omarchy config changed on desktop │
    ╰───────── f2 ╯  ╰──────────────────────────────────────────╯
    ADMINISTRATION     ^r Refresh   ^c Quit
      Users  f9

The layout is borrowed, in spirit, from the release console we like for its
plainness: a place per card down the left, each saying how it is; one rounded
panel for the place you are on; a strip of what happened along the bottom;
the keys on the last line.

Down the left: YOUR CLOUD — notes, your days, the chat, your secrets —
then QUILLS, a card for every screen of every Quill this server has
installed (Tasks is the first), drawn from the kit by tui/panes/kit.py. Those
are asked for after sign-in rather than built in, so installing one in
Administration puts its card here without a restart. An administrator has a
third section, ADMINISTRATION, whose entries put the server's own panel —
accounts, features, Quills — in place of the workspace. A feature switched
off there loses its card here, for everybody.

Everything here is clickable — the cards, the rows, the buttons — and
everything clickable also has a key. Neither way is the "real" one, so the
key is written on the thing it works: on the card, on the Settings button,
beside the bell. The line at the bottom carries a few of the rest.
"""

from __future__ import annotations

import json

from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, ContentSwitcher, Static

from cloudmorrow.cli import dev
from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.panes.admin import AdminPanel
from cloudmorrow.tui.panes.base import Pane
from cloudmorrow.tui.panes.calendar import CalendarPane
from cloudmorrow.tui.panes.chat import ChatPane
from cloudmorrow.tui.panes.kit import pane_for, screen_key
# Shares on this machine: mounted here or not, on any grid of shares.
from cloudmorrow.tui import sharemounts  # noqa: F401
from cloudmorrow.tui.panes.notes import NotesPane
from cloudmorrow.tui.panes.secrets import SecretsPane
from cloudmorrow.tui.screens.modals import PasswordModal
from cloudmorrow.tui.screens.notifications import (
    NOTIFICATIONS,
    NotificationsScreen,
    bell_label,
    unread_count,
)
from cloudmorrow.tui.screens.settings import SettingsScreen
from cloudmorrow.tui.theme import MUTED
from cloudmorrow.tui.widgets.bottombar import BottomBar
from cloudmorrow.tui.widgets.header import Header
from cloudmorrow.tui.widgets.logstrip import LogStrip
from cloudmorrow.tui.widgets.sidebar import NavCard, SectionLabel

PANES: tuple[type[Pane], ...] = (
    NotesPane, CalendarPane, ChatPane, SecretsPane,
)

# The function keys no built-in card has, handed to Quill cards in the order
# they appear. f2 was Tasks' before Tasks was a Quill, and still is; f5 was
# Files', which is the second Quill a server has.
QUILL_KEYS: tuple[str, ...] = ("f2", "f5", "f4", "f10", "f11", "f12")

# How often the bell asks the server whether anything happened.
BELL_POLL = 60.0

# Which server feature each built-in card belongs to.
FEATURE_OF: dict[str, str] = {
    "notes": "notes",
    "calendar": "calendar",
    "chat": "chat",
    "secrets": "secrets",
}

# Below this many columns the sidebar narrows, and its cards become one line.
NARROW = 90


def _key(pane: type[Pane]) -> str:
    return pane.TAB_LABEL.lower()


class WorkspaceScreen(Screen):
    """One screen: the header, the sidebar, the panel, the log."""

    # Focus goes into the pane you are on, not to whatever happens to be
    # first in the tree — which, with every pane mounted, is a hidden one.
    AUTO_FOCUS = None

    # The cards and the header buttons wear their own keys, so they are bound
    # but not listed: the bottom line is for what is not written anywhere else.
    BINDINGS = [
        *(
            Binding(pane.TAB_KEY, f"show_pane('{_key(pane)}')", pane.TAB_LABEL, show=False)
            for pane in PANES
        ),
        # A Quill card's key is decided at run time, so each free key is bound
        # to "whichever Quill card has it".
        *(Binding(key, f"quill_key('{key}')", show=False) for key in QUILL_KEYS),
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
        # mount; until the answer comes back its section is not there.
        self._admin = False
        # The cards this server offers, once it has said. None means we have
        # not asked yet, and every key still works.
        self._showing: list[str] | None = None
        # The Quill cards there are now, by key, with what they were drawn
        # from — so a refresh only touches the ones that changed — and the
        # function key and the feature switch of each.
        self._quill_panes: dict[str, str] = {}
        self._quill_keys: dict[str, str] = {}
        self._feature_of: dict[str, str] = {}

    # -- layout ------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(
            owner=getattr(self.app, "username", "") or "",
            account=self._account_text(),
            bell=bell_label(self.app.unread),
            dev=bool(dev.checkout()),
        )
        with Horizontal(id="body"):
            with VerticalScroll(id="sidebar"):
                yield SectionLabel("Your cloud", id="nav-section-cloud")
                for pane in PANES:
                    yield NavCard(
                        _key(pane), pane.TAB_LABEL, tag=pane.TAB_KEY, id=f"nav-{_key(pane)}"
                    )
                quills = SectionLabel("Quills", id="nav-section-quills")
                quills.display = False
                yield quills
                admin = SectionLabel("Administration", "f9", id="nav-section-admin")
                admin.display = False
                yield admin
                for view in AdminPanel.VIEWS:
                    card = NavCard(
                        f"admin-{AdminPanel.key(view)}",
                        view.TAB_LABEL,
                        compact=True,
                        id=f"nav-admin-{AdminPanel.key(view)}",
                        classes="admin-card",
                    )
                    card.display = False
                    yield card
            with Vertical(id="main"):
                # The workspace, and the administration panel that replaces it.
                # One of the two is showing; never both.
                with Vertical(id="workspace-view"):
                    with ContentSwitcher(id="panes", initial="pane-notes"):
                        for pane in PANES:
                            yield pane(id=f"pane-{_key(pane)}")
                    # What is here when an account has switched everything off.
                    nothing = Static(
                        f"[{MUTED}]Nothing here yet. Every place is switched off for this "
                        f"account.[/]\n[{MUTED}]Settings — ^g — is where they come back.[/]",
                        id="nothing-showing",
                    )
                    nothing.display = False
                    yield nothing
                panel = AdminPanel(id="admin-view")
                panel.display = False
                yield panel
        yield LogStrip(id="log")
        yield BottomBar()

    def _account_text(self) -> str:
        user = getattr(self.app, "username", "") or "?"
        host = self.app.client_config.api_url.replace("https://", "").replace("http://", "")
        return f"{user}@{host}"

    def on_mount(self) -> None:
        self._mark_active("notes")
        self.call_after_refresh(self._focus_pane)
        self._fit(self.app.size.width, self.app.size.height)
        # The bell is about the machines, not about the card you are on, so it
        # keeps its own clock rather than waiting for a refresh.
        self.count_unread()
        self.set_interval(BELL_POLL, self.count_unread)
        # Who is signed in, and what this server offers. Both come from the
        # server, so the sidebar is drawn for what is really there.
        self.ask_the_server()

    def on_resize(self, event: events.Resize) -> None:
        self._fit(event.size.width, event.size.height)

    def _fit(self, width: int, height: int) -> None:
        """The shape for the terminal: the full mark or one line, cards or lines."""
        self.query_one(Header).fit(width)
        narrow = width < NARROW
        self.set_class(narrow, "-narrow")
        for card in self.query(NavCard):
            card.set_class(narrow, "-line")
            card.redraw()
        # A tall terminal has room for a third line of log.
        self.query_one(LogStrip).set_class(height >= 40, "-tall")

    # -- what this server is -----------------------------------------------
    @work(exclusive=True, group="whoami")
    async def ask_the_server(self) -> None:
        """Is this account an administrator, and which features are on?"""
        client = self.app.client
        if client is None:
            return
        header = self.query_one(Header)
        try:
            me = await client.me()
            header.set_health("up")
        except ApiError:
            # The server did not answer, and the header says so; nothing else
            # is worth a red line: whatever is wrong will show up where it is
            # asked for.
            me = {}
            header.set_health("down")
        self._admin = bool(me.get("is_admin"))
        self.query_one("#nav-section-admin").display = self._admin
        for card in self.query(".admin-card"):
            card.display = self._admin
        # The Quill cards before the switches, so the switches find them.
        await self.sync_quills()
        # This account's own list rather than the server's: it is already
        # narrowed to what this server offers and carries what the account
        # has switched off for itself, so one call answers both questions.
        try:
            features = await client.my_features()
        except ApiError:
            return
        self.apply_features([row["key"] for row in features if row["enabled"]])

    def _place_cards(self) -> list[NavCard]:
        """The cards for places in the workspace — not the administration ones."""
        return [card for card in self.query(NavCard) if not card.has_class("admin-card")]

    def apply_features(self, enabled: list[str]) -> None:
        """Show the cards this account has, and hide the rest.

        Called on mount, when an administrator switches one, and when you
        switch one of your own in Settings — so a feature turned off is gone
        from the sidebar without a restart.
        """
        showing = []
        for card in self._place_cards():
            key = card.nav_key
            feature = FEATURE_OF.get(key) or self._feature_of.get(key)
            on = feature is None or feature in enabled
            card.display = on
            if on:
                showing.append(key)
        self._showing = showing
        self.query_one("#nav-section-quills").display = any(
            key in showing for key in self._quill_panes
        )
        # Switch the last one off in Settings and there is no card to stand
        # on: say so, rather than leaving a pane up that nothing points at.
        self.query_one("#panes", ContentSwitcher).display = bool(showing)
        self.query_one("#nothing-showing", Static).display = not showing
        # Standing on a card that has just gone: move to the first one left.
        current = self.query_one("#panes", ContentSwitcher).current or ""
        if showing and current[len("pane-") :] not in showing:
            self.action_show_pane(showing[0])

    # -- Quill cards -------------------------------------------------------
    async def sync_quills(self) -> None:
        """One card and pane per screen of every installed Quill.

        Asked on sign-in and again whenever the features are (after an
        install or a removal in Administration, after Settings). A pane whose
        screen or datamodels did not change is left exactly as it is, cards
        and all; one that changed is drawn again, and one whose Quill went is
        taken out.
        """
        client = self.app.client
        if client is None:
            return
        try:
            quills = await client.quills()
        except ApiError:
            # Keep what is there: a Quill is not worth losing to a blip.
            return
        wanted: dict[str, tuple[dict, dict, str]] = {}
        for quill in quills:
            for screen in quill.get("screens") or []:
                signature = json.dumps(
                    [quill.get("version"), quill.get("jobs"), screen, quill.get("models")],
                    sort_keys=True,
                    default=str,
                )
                wanted[screen_key(quill, screen)] = (quill, screen, signature)
        for key, signature in list(self._quill_panes.items()):
            if key not in wanted or wanted[key][2] != signature:
                await self._drop_quill_pane(key)
        anchor: NavCard | SectionLabel = self.query_one("#nav-section-quills", SectionLabel)
        for key, (quill, screen, signature) in wanted.items():
            if key in self._quill_panes:
                anchor = self.query_one(f"#nav-{key}", NavCard)
                continue
            card = await self._add_quill_pane(key, quill, screen, after=anchor)
            if card is not None:
                self._quill_panes[key] = signature
                anchor = card

    def _free_key(self, key: str) -> str:
        """This card's function key: the one it had, or the first nobody has."""
        if key in self._quill_keys:
            return self._quill_keys[key]
        taken = set(self._quill_keys.values())
        free = next((k for k in QUILL_KEYS if k not in taken), "")
        if free:
            self._quill_keys[key] = free
        return free

    async def _add_quill_pane(
        self, key: str, quill: dict, screen: dict, *, after
    ) -> NavCard | None:
        if self.query(f"#pane-{key}") or self.query(f"#nav-{key}"):
            # Half there from a sync that was cut short by the next one.
            await self._drop_quill_pane(key)
        pane = pane_for(quill, screen, tab_key=self._free_key(key), id=f"pane-{key}")
        if pane is None:
            # A kit this terminal does not draw yet: no card, and no key held.
            self._quill_keys.pop(key, None)
            return None
        self._feature_of[key] = str(quill["id"])
        # Mounted hidden: the switcher only hides what it had at the start.
        pane.display = False
        await self.query_one("#panes", ContentSwitcher).mount(pane)
        card = NavCard(key, pane.TAB_LABEL, tag=pane.TAB_KEY, id=f"nav-{key}")
        card.set_class(self.has_class("-narrow"), "-line")
        card.set_status("none", str(quill.get("summary") or quill.get("name") or ""))
        await self.query_one("#sidebar", VerticalScroll).mount(card, after=after)
        # Its card says how it is from the start, not only once visited.
        pane.reload()
        return card

    async def _drop_quill_pane(self, key: str) -> None:
        switcher = self.query_one("#panes", ContentSwitcher)
        if switcher.current == f"pane-{key}":
            # Standing on it: step onto Notes before the floor goes.
            switcher.current = "pane-notes"
            self._mark_active("notes")
        for widget in [*self.query(f"#nav-{key}"), *switcher.query(f"#pane-{key}")]:
            await widget.remove()
        self._quill_panes.pop(key, None)
        self._feature_of.pop(key, None)
        self._quill_keys.pop(key, None)

    def action_quill_key(self, function_key: str) -> None:
        """One of the free function keys: the Quill card that holds it, if any."""
        key = next((k for k, f in self._quill_keys.items() if f == function_key), None)
        if key is not None and key in self._quill_panes:
            self.action_show_pane(key)

    # -- the sidebar -------------------------------------------------------
    def _mark_active(self, key: str) -> None:
        for card in self.query(NavCard):
            card.set_active(card.nav_key == key)

    def on_nav_card_chosen(self, event: NavCard.Chosen) -> None:
        event.stop()
        key = event.card.nav_key
        if key.startswith("admin-"):
            self.open_admin(key[len("admin-") :])
        else:
            self.action_show_pane(key)

    def refresh_cards(self) -> None:
        """Each card's line: what its pane knows, or its summary until then."""
        switcher = self.query_one("#panes", ContentSwitcher)
        for card in self._place_cards():
            try:
                pane = switcher.query_one(f"#pane-{card.nav_key}", Pane)
            except Exception:
                continue
            said = pane.card_status()
            if said is not None:
                card.set_status(*said)
            elif not card.status_line:
                card.set_status("none", pane.SUMMARY)

    # -- administration ----------------------------------------------------
    def action_administration(self) -> None:
        """f9: into the panel, and out of it again."""
        if not self._admin:
            return
        if self.query_one("#admin-view", AdminPanel).display:
            self.close_admin()
        else:
            self.open_admin()

    def open_admin(self, view: str = "") -> None:
        if not self._admin:
            return
        self.query_one("#workspace-view", Vertical).display = False
        panel = self.query_one("#admin-view", AdminPanel)
        was_showing = bool(panel.display)
        panel.display = True
        if view:
            panel.show_view(view)
        if not view or not was_showing:
            panel.reload()
        self._mark_active(f"admin-{panel.current}")
        self.set_status()

    def close_admin(self) -> None:
        self.query_one("#admin-view", AdminPanel).display = False
        self.query_one("#workspace-view", Vertical).display = True
        current = self.query_one("#panes", ContentSwitcher).current or "pane-notes"
        self._mark_active(current[len("pane-") :])
        self.set_status()

    def on_admin_panel_closed(self, event: AdminPanel.Closed) -> None:
        event.stop()
        self.close_admin()

    @property
    def admin_showing(self) -> bool:
        return bool(self.query_one("#admin-view", AdminPanel).display)

    # -- status ------------------------------------------------------------
    def set_status(self, message: str = "", *, error: bool = False) -> None:
        """Something happened: it goes in the log, once, with the time.

        An empty message says nothing and only redraws; a pane's notes about
        itself go to its own header line (see Pane.status) and never here.
        """
        self._message, self._error = message, error
        if message:
            self.query_one(LogStrip).say(message, "bad" if error else "text")
        self.redraw_status()

    def redraw_status(self) -> None:
        pane: Pane | None
        if self.admin_showing:
            pane = self.query_one("#admin-view", AdminPanel).active_view
        else:
            pane = self.active_pane
        if pane is not None:
            pane.refresh_head()
        self.refresh_cards()

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
            notes = await client.notifications(limit=NOTIFICATIONS)
        except ApiError:
            # A bell that cannot count is not worth a message; whatever went
            # wrong will show up where it was asked for.
            return
        self.query_one(LogStrip).notes(notes)
        self.app.set_unread(unread_count(notes))

    def action_notifications(self) -> None:
        self.open_notifications()

    def open_notifications(self) -> None:
        self.app.push_screen(NotificationsScreen(), self._notifications_closed)

    def on_log_strip_opened(self, event: LogStrip.Opened) -> None:
        event.stop()
        self.open_notifications()

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
        if not self.query(f"#pane-{key}"):
            return
        if self.admin_showing:
            self.close_admin()
        switcher = self.query_one("#panes", ContentSwitcher)
        if switcher.current != f"pane-{key}":
            switcher.current = f"pane-{key}"
        self._mark_active(key)
        self.set_status()
        self.call_after_refresh(self._focus_pane)

    def _focus_pane(self) -> None:
        """Put focus in the pane on show, so its keys work at once.

        Its first control that is not a button: the note tree, the table,
        the board's first card — where you would have clicked.
        """
        pane = self.active_pane
        if pane is None or self.admin_showing:
            return
        focused = self.focused
        if focused is not None and pane in focused.ancestors:
            return
        for widget in pane.query("*"):
            if widget.focusable and not isinstance(widget, Button):
                widget.focus()
                return

    # -- settings ----------------------------------------------------------
    def action_settings(self) -> None:
        self.open_settings()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "open-settings":
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
        """Your name in the header is the way to your password."""
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
        """The feature boxes in there are this account's, and so is the sidebar."""
        self.ask_the_server()

    def action_refresh(self) -> None:
        if self.admin_showing:
            self.query_one("#admin-view", AdminPanel).reload()
            return
        pane = self.active_pane
        if pane is not None:
            pane.reload()
        self.count_unread()
