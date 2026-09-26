"""The Cloudmorrow terminal app: sign in, and the workspace is what you get.

Nothing here is scoped to a vault. A vault is a thing you look at in the
Secrets tab — its environments and keys — not a mode the whole app is in.
"""

from __future__ import annotations

import asyncio
from time import monotonic

from textual import events, work
from textual.app import App
from textual.binding import Binding

from cloudmorrow.client.api import ApiError, AuthError, CloudmorrowClient, client_from_credentials
from cloudmorrow.client.config import ClientConfig, StoredCredentials, clear_credentials
from cloudmorrow.tui.screens.login import LoginScreen
from cloudmorrow.tui.screens.splash import SplashScreen
from cloudmorrow.tui.screens.workspace import WorkspaceScreen
from cloudmorrow.tui.theme import CLOUDMORROW_THEME
from cloudmorrow.tui.widgets.bottombar import BottomBar

# How long the second ctrl+c has to arrive after the first.
QUIT_WINDOW = 3.0
# How long the logo stays up at the start. A stored session comes back in a
# few milliseconds, and a logo gone in a few milliseconds is a flicker.
SPLASH_DWELL = 0.5


class CloudmorrowApp(App):
    """Your notes, your tasks, your secrets, your machines, your files."""

    # The panes' own furniture; the frame round them and the controls every
    # pane shares; and the kit — Quill screens, the record sheet, the Quills
    # admin. Later sheets win, so the frame's rules hold over the panes'.
    CSS_PATH = ["cloudmorrow.tcss", "chrome.tcss", "kit.tcss"]
    TITLE = "Cloudmorrow"
    SUB_TITLE = "your own cloud"
    # Textual's own extras — the command palette on ctrl+p and quit on
    # ctrl+q — are not this app's. Quitting is ctrl+c, pressed twice.
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("ctrl+c", "confirm_quit", "Quit", priority=True),
    ]

    def __init__(self, config: ClientConfig | None = None) -> None:
        super().__init__()
        # Before anything is mounted: the stylesheet is written against this
        # theme's variables, so it has to exist before the CSS is parsed.
        self.register_theme(CLOUDMORROW_THEME)
        self.theme = CLOUDMORROW_THEME.name
        self.client_config = config or ClientConfig.load()
        self.credentials = StoredCredentials.load()
        self.client: CloudmorrowClient | None = None
        self.username: str = ""
        # What the bell in the top bar is showing.
        self.unread: int = 0
        # Whether one ctrl+c has been pressed and the second is awaited.
        self._quit_armed = False
        # When the splash went up, so it can be held for a moment.
        self._splash_at = monotonic()

    # -- quitting ----------------------------------------------------------
    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # Textual binds ctrl+q to quit at the app level; this is where it is
        # switched off, since a binding cannot be removed, only refused.
        if action == "quit":
            return False
        return True

    def action_confirm_quit(self) -> None:
        """ctrl+c: the first press asks, the second — within a moment — quits."""
        if self._quit_armed:
            self.exit()
            return
        self._quit_armed = True
        self.say_notice("Press ctrl+c again to quit")
        self.set_timer(QUIT_WINDOW, self._disarm_quit)

    def _disarm_quit(self) -> None:
        self._quit_armed = False
        self.say_notice("")

    def say_notice(self, text: str) -> None:
        """Put *text* in the bottom bar of whichever screen has one showing."""
        for screen in reversed(self.screen_stack):
            bars = screen.query(BottomBar)
            if bars:
                bars.first().notice = text
                return

    @property
    def stored_username(self) -> str:
        return self.credentials.username if self.credentials else ""

    def on_text_selected(self, event: events.TextSelected) -> None:
        """Sweeping the mouse over text is copying it.

        Textual highlights what the pointer drags across and says so when the
        button comes up; there is no separate copy step, because a terminal has
        no menu to find one in. Selecting is the copy, and the status bar is
        the receipt. Escape clears the highlight without touching the clipboard.
        """
        text = self.screen.get_selected_text()
        if text and text.strip():
            self.copy_to_clipboard(text)
            self.say("Copied to the clipboard.")

    def say(self, message: str = "", *, error: bool = False) -> None:
        """Put a line in the log along the bottom, with the time.

        Everything that happens goes there — copied, saved, changed — and
        nothing is a toast. A notification is something else: a
        thing a machine sent, kept behind the bell. The bar is on the
        workspace, which may be under a dialog; a message from the dialog
        lands there and is read when the dialog closes.
        """
        for screen in self.screen_stack:
            setter = getattr(screen, "set_status", None)
            if callable(setter):
                setter(message, error=error)
                return

    def set_unread(self, count: int) -> None:
        """Remember how many notifications are unread, and redraw the bell.

        The whole stack, not just the top screen: the count usually changes
        while the notifications modal is open, and the bell it belongs to is
        on the workspace underneath it.
        """
        self.unread = count
        for screen in self.screen_stack:
            refresher = getattr(screen, "refresh_bell", None)
            if callable(refresher):
                refresher()

    def on_mount(self) -> None:
        self._splash_at = monotonic()
        self.push_screen(SplashScreen())
        self._resume_session()

    async def _let_the_logo_show(self) -> None:
        """Hold the splash until it has had its moment, then let it go."""
        if not isinstance(self.screen, SplashScreen):
            return
        left = SPLASH_DWELL - (monotonic() - self._splash_at)
        if left > 0:
            await asyncio.sleep(left)

    @work(exclusive=True)
    async def _resume_session(self) -> None:
        """Reuse the stored token when it still works, otherwise show the login."""
        splash = self.screen
        credentials = self.credentials
        if credentials is None or credentials.api_url.rstrip("/") != self.client_config.api_url:
            await self._show_login()
            return
        client = client_from_credentials(self.client_config, credentials)
        try:
            user = await client.me()
        except AuthError:
            await client.aclose()
            clear_credentials()
            await self._show_login("Session expired — sign in again.")
            return
        except ApiError as exc:
            await client.aclose()
            if isinstance(splash, SplashScreen):
                splash.status(str(exc))
            await self._show_login(str(exc))
            return
        await self.start_session(client, user["username"])

    async def _show_login(self, message: str = "") -> None:
        await self._let_the_logo_show()
        await self.switch_screen(LoginScreen())
        if message and isinstance(self.screen, LoginScreen):
            self.screen.show_error(message)

    async def start_session(self, client: CloudmorrowClient, username: str) -> None:
        if self.client is not None and self.client is not client:
            await self.client.aclose()
        await self._let_the_logo_show()
        self.client = client
        self.username = username
        # Whatever the CLI left in the config as its vault is the CLI's
        # business: nothing in here is scoped to one, the pane names it.
        client.vault = None
        self.sub_title = username
        await self.switch_screen(WorkspaceScreen())

    async def sign_out(self, message: str = "") -> None:
        clear_credentials()
        self.credentials = None
        if self.client is not None:
            await self.client.aclose()
            self.client = None
        self.username = ""
        await self._show_login(message)

    async def on_unmount(self) -> None:
        if self.client is not None:
            await self.client.aclose()


def run() -> None:
    CloudmorrowApp().run()
