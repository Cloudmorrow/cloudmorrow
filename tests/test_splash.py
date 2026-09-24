"""The logo at the start: up long enough to read, and not a moment longer."""

from __future__ import annotations

from time import monotonic

import pytest

from cloudmorrow.client.config import ClientConfig
from cloudmorrow.tui.app import SPLASH_DWELL, CloudmorrowApp
from cloudmorrow.tui.screens.login import LoginScreen
from cloudmorrow.tui.screens.splash import SplashScreen
from cloudmorrow.tui.screens.workspace import WorkspaceScreen
from tests.tui_harness import FakeClient


@pytest.fixture()
def fresh_app(tmp_path, monkeypatch) -> CloudmorrowApp:
    """The app as it starts for real — no stored session, so it asks you in."""
    monkeypatch.setenv("CLOUDMORROW_CONFIG_DIR", str(tmp_path / "config"))
    return CloudmorrowApp(ClientConfig(api_url="http://test.invalid"))


async def test_the_logo_is_held_before_the_login_screen(fresh_app):
    started = monotonic()
    async with fresh_app.run_test(size=(100, 30)) as pilot:
        assert isinstance(fresh_app.screen, SplashScreen)
        while not isinstance(fresh_app.screen, LoginScreen):
            assert monotonic() - started < 5, "the login screen never came"
            await pilot.pause()
        # It went by only after the logo had its moment.
        assert monotonic() - started >= SPLASH_DWELL


async def test_a_session_that_is_already_up_waits_for_the_logo_too(fresh_app, monkeypatch):
    """A stored token comes back in milliseconds; the logo still gets its moment."""
    monkeypatch.setattr(CloudmorrowApp, "_resume_session", lambda self: None)
    async with fresh_app.run_test(size=(100, 30)) as pilot:
        assert isinstance(fresh_app.screen, SplashScreen)
        started = monotonic()
        fresh_app._splash_at = started
        await fresh_app.start_session(FakeClient(), "bram")
        assert monotonic() - started >= SPLASH_DWELL
        assert isinstance(fresh_app.screen, WorkspaceScreen)
        await pilot.pause()
