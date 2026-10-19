"""What `cm login` says when the sign-in did not happen, and what a proxy's 502 is called."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from typer.testing import CliRunner

from cloudmorrow.cli import main as cli_main
from cloudmorrow.client.api import ApiError, AuthError, CloudmorrowClient
from cloudmorrow.client.config import ClientConfig

SERVER = "https://cm.example.net"


class RefusingClient:
    """A client whose sign-in is refused the way the server does it."""

    error: ApiError = AuthError("invalid username or password", status_code=401)

    def __init__(self, config) -> None:
        self.config = config

    async def login(self, username, password):
        raise self.error

    async def aclose(self) -> None: ...

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None: ...


@pytest.fixture()
def refused(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(cli_main, "CloudmorrowClient", RefusingClient)
    monkeypatch.setattr(cli_main.getpass, "getpass", lambda prompt="": "pw")
    return RefusingClient


def _login(args: list[str]) -> tuple[int, str]:
    result = CliRunner().invoke(cli_main.app, ["login", "--server", SERVER, "--no-agent", *args])
    # Rich wraps at the terminal's width; the words are what is being checked.
    return result.exit_code, " ".join(result.output.split())


def test_a_wrong_name_or_password_says_where_and_what_a_username_is(refused):
    code, out = _login(["-u", "cm"])
    assert code == 1
    assert f"Not signed in to {SERVER}: invalid username or password" in out
    assert "does not say which" in out
    assert "You gave cm" in out
    assert "account's name on this cloud" in out
    assert "not an email address" in out
    assert "Administration" in out


def test_too_many_wrong_passwords_says_waiting_is_the_only_way(refused):
    refused.error = ApiError("too many wrong passwords; try again in 12 minutes", status_code=429)
    code, out = _login(["-u", "jimmi"])
    assert code == 1
    assert "try again in 12 minutes" in out
    assert "does not get through any sooner" in out


def test_a_proxy_with_nothing_behind_it_is_named_as_such(refused):
    refused.error = ApiError.behind_proxy(SERVER, 502)
    code, out = _login(["-u", "jimmi"])
    assert code == 1
    assert "the Cloudmorrow server behind it does not" in out
    assert "HTTP 502 from its reverse proxy" in out
    assert "down, or the proxy points at the wrong address" in out


def test_any_other_refusal_keeps_the_servers_words(refused):
    refused.error = ApiError("this server is reached over https only", status_code=426)
    code, out = _login(["-u", "jimmi"])
    assert code == 1
    assert f"Not signed in to {SERVER}: this server is reached over https only" in out


# -- the client, when a reverse proxy answers for a server it cannot reach ----------------
def _client_answering(status: int, body: str, content_type: str) -> CloudmorrowClient:
    api = CloudmorrowClient(ClientConfig(api_url=SERVER))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body, headers={"content-type": content_type})

    api._client = httpx.AsyncClient(base_url=SERVER, transport=httpx.MockTransport(handler))
    return api


def test_a_proxys_502_is_told_apart_from_the_servers_own():
    api = _client_answering(502, "<html>502 Bad Gateway</html>", "text/html")
    with pytest.raises(ApiError) as caught:
        asyncio.run(api.me())
    assert caught.value.status_code == 502
    assert "Cloudmorrow server behind it does not" in str(caught.value)
    assert "<html>" not in str(caught.value)


def test_the_servers_own_503_keeps_its_words():
    api = _client_answering(503, '{"detail":"no supervisor on this server"}', "application/json")
    with pytest.raises(ApiError) as caught:
        asyncio.run(api.me())
    assert str(caught.value) == "no supervisor on this server"
