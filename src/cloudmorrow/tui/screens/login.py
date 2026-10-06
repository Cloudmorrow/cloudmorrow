"""Sign-in screen — and the first thing you see, so it carries the logo."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Static

from cloudmorrow.agent.setup import ensure_agent
from cloudmorrow.client.api import ApiError, CloudmorrowClient
from cloudmorrow.client.config import StoredCredentials
from cloudmorrow.logo import TAGLINE, mark_for_width, wordmark
from cloudmorrow.palette import BAD, MUTED
from cloudmorrow.tui.widgets.bottombar import BottomBar


class LoginScreen(Screen):
    """Collects server URL, username and password."""

    def compose(self) -> ComposeResult:
        with Vertical(id="centre-column"):
            yield Static(wordmark(), id="logo")
            yield Static(f"[italic {MUTED}]{TAGLINE}[/]", id="tagline")
            with Vertical(id="login-box"):
                yield Input(
                    value=self.app.client_config.api_url,
                    placeholder="https://cm.hl.bramlabs.io",
                    id="api-url",
                )
                yield Input(placeholder="username", id="username")
                yield Input(placeholder="password", password=True, id="password")
                yield Button("Sign in", variant="primary", id="signin")
                yield Static("", id="login-status")
        yield BottomBar()

    def on_mount(self) -> None:
        self._fit_logo()
        username = self.app.stored_username or ""
        self.query_one("#username", Input).value = username
        target = "#password" if username else "#username"
        self.query_one(target, Input).focus()

    def on_resize(self) -> None:
        self._fit_logo()

    def _fit_logo(self) -> None:
        self.query_one("#logo", Static).update(mark_for_width(self.size.width))

    def show_error(self, message: str) -> None:
        """Called by the app when a session could not be resumed."""
        self._status(message, error=True)

    def _status(self, message: str, *, error: bool = False) -> None:
        style = BAD if error else MUTED
        self.query_one("#login-status", Static).update(f"[{style}]{message}[/]")

    def on_input_submitted(self) -> None:
        self.submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "signin":
            self.submit()

    def submit(self) -> None:
        api_url = self.query_one("#api-url", Input).value.strip().rstrip("/")
        username = self.query_one("#username", Input).value.strip()
        password = self.query_one("#password", Input).value
        if not (api_url and username and password):
            self._status("Server, username and password are all required.", error=True)
            return
        self._status("Signing in…")
        self._sign_in(api_url, username, password)

    @work(exclusive=True)
    async def _sign_in(self, api_url: str, username: str, password: str) -> None:
        config = self.app.client_config
        if api_url != config.api_url:
            config.api_url = api_url
            config.save()
        client = CloudmorrowClient(config)
        try:
            session = await client.login(username, password)
        except ApiError as exc:
            await client.aclose()
            self._status(str(exc), error=True)
            self.query_one("#password", Input).value = ""
            return
        StoredCredentials(
            api_url=config.api_url,
            username=session.username,
            access_token=session.access_token,
            expires_at=session.expires_at,
        ).save()
        # Registering this machine is part of signing in, not a chore.
        self._status("Setting up this machine…")
        await ensure_agent(client)
        await self.app.start_session(client, session.username)
