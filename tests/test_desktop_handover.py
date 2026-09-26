"""One sign-in per computer: the desktop app's window and the stored token.

The window starts with the token `cloudmorrow login` stored, writes back a
sign-in made in it, and ends the machine's sign-in when its own ends — but
never one the terminal app made since.
"""

from __future__ import annotations

import re

from cloudmorrow.agent.config import AgentConfig
from cloudmorrow.agent.setup import SetupResult
from cloudmorrow.client.config import ClientConfig, StoredCredentials
from cloudmorrow.desktop.bridge import Bridge
from cloudmorrow.server.routes.web import WEB

API = "https://cloud.example"


class FakeApi:
    async def aclose(self) -> None:
        pass


def make_bridge(enrolled: list | None = None) -> Bridge:
    async def enrol(api):
        if enrolled is not None:
            enrolled.append(api)
        return SetupResult(True, True, "desk")

    return Bridge(ClientConfig(api_url=API), api_factory=lambda config: FakeApi(), enrol=enrol)


def test_the_window_starts_with_the_stored_sign_in():
    StoredCredentials(api_url=API, username="bram", access_token="tok-cli").save()
    assert make_bridge().session() == {"token": "tok-cli", "user": "bram"}


def test_a_sign_in_for_another_cloud_is_not_handed_over():
    StoredCredentials(api_url="https://other.example", username="bram", access_token="x").save()
    assert make_bridge().session() == {"token": "", "user": ""}


def test_nothing_stored_means_the_window_asks():
    assert make_bridge().session() == {"token": "", "user": ""}


def test_a_sign_in_in_the_window_signs_the_terminal_app_in(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDMORROW_AGENT_CONFIG", str(tmp_path / "agent.toml"))
    enrolled: list = []
    answer = make_bridge(enrolled).signed_in("tok-web", "bram", "2026-10-01T00:00:00")
    assert answer == {"saved": True, "agent": "desk"}
    stored = StoredCredentials.load()
    assert (stored.api_url, stored.username, stored.access_token, stored.expires_at) == (
        API, "bram", "tok-web", "2026-10-01T00:00:00",
    )
    # As `cloudmorrow login` does: this machine becomes an agent.
    assert len(enrolled) == 1


def test_an_enrolled_machine_is_not_enrolled_again(tmp_path, monkeypatch):
    path = tmp_path / "agent.toml"
    monkeypatch.setenv("CLOUDMORROW_AGENT_CONFIG", str(path))
    AgentConfig(server_url=API, agent_token="agent-tok", name="desk").save(path)
    enrolled: list = []
    assert make_bridge(enrolled).signed_in("tok-web", "bram") == {"saved": True, "agent": ""}
    assert enrolled == []


def test_signing_out_in_the_window_signs_the_machine_out():
    StoredCredentials(api_url=API, username="bram", access_token="tok-web").save()
    assert make_bridge().signed_out("tok-web") == {"cleared": True}
    assert StoredCredentials.load() is None


def test_but_not_a_sign_in_the_terminal_app_made_since():
    StoredCredentials(api_url=API, username="sam", access_token="tok-newer").save()
    assert make_bridge().signed_out("tok-web") == {"cleared": False}
    assert StoredCredentials.load().access_token == "tok-newer"


# -- the page's half ----------------------------------------------------------------


def test_the_shell_tells_whoever_asks_about_a_sign_in():
    core = (WEB / "core.js").read_text()
    assert "export function onSignIn(fn)" in core
    sign_in = core[core.index("export function signIn(data)"):core.index("export function signOut")]
    assert "for (const fn of signInHooks) fn(data);" in sign_in


def test_the_page_hands_its_sign_in_across_both_ways():
    bridge = (WEB / "desktopbridge.js").read_text()
    # The stored one is asked for, and taken, when the bridge arrives…
    assert 'call("session")' in bridge
    assert re.search(r"signIn\(\{ access_token: stored\.token", bridge)
    # …and the window's own sign-ins and sign-outs go back.
    assert 'call("signed_in", data.access_token, data.user.username' in bridge
    assert 'call("signed_out", token)' in bridge
