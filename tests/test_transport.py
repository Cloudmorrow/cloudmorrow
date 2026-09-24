"""Nothing crosses a wire in the clear: the server refuses it, the clients refuse it."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cloudmorrow.agent.client import AgentApiError, AgentClient
from cloudmorrow.agent.config import AgentConfig
from cloudmorrow.client.api import ApiError, CloudmorrowClient
from cloudmorrow.client.config import ClientConfig
from cloudmorrow.server.app import create_app
from cloudmorrow.server.config import ServerConfig
from cloudmorrow.server.transport import HSTS
from cloudmorrow.transport import InsecureUrlError, check_url, is_local_url


def test_require_tls_follows_the_public_url(tmp_path):
    base = dict(notes_dir=tmp_path / "n", data_dir=tmp_path / "d", secret_key="k" * 48)
    assert ServerConfig(**base, public_url="https://cm.example").tls_required
    assert not ServerConfig(**base, public_url="http://cm.example").tls_required
    assert not ServerConfig(**base).tls_required
    assert ServerConfig(**base, require_tls=True).tls_required
    assert not ServerConfig(**base, public_url="https://cm.example", require_tls=False).tls_required


@pytest.fixture()
def strict(config, users) -> TestClient:
    config.public_url = "https://cm.example"
    return TestClient(create_app(config))


def test_a_plain_request_from_off_the_box_is_refused(strict):
    # What the proxy would send for a request that reached it over plain http.
    got = strict.get("/api/health", headers={"x-forwarded-proto": "http"})
    assert got.status_code == 426
    assert got.json()["detail"].startswith("this server is reached over https only")


def test_a_call_from_this_machine_with_no_proxy_header_is_let_through(strict):
    # The test client is that: no wire, no proxy.
    assert strict.get("/api/health").status_code == 200


def test_a_tls_request_is_answered_with_hsts(strict):
    got = strict.get("/api/health", headers={"x-forwarded-proto": "https"})
    # uvicorn's proxy-header handling is not in the test client, so the
    # header alone does not make the scheme https there ...
    if got.status_code == 200:
        assert got.headers.get("strict-transport-security") in (HSTS, None)
    # ... but a request that is https end to end gets the header.
    over_tls = TestClient(strict.app, base_url="https://testserver")
    got = over_tls.get("/api/health")
    assert got.status_code == 200
    assert got.headers["strict-transport-security"] == HSTS


def test_without_require_tls_plain_is_fine(client):
    assert client.get("/api/health", headers={"x-forwarded-proto": "http"}).status_code == 200


def test_which_urls_a_client_will_talk_to():
    assert check_url("https://cm.example") == "https://cm.example"
    assert check_url("http://localhost:8787") == "http://localhost:8787"
    assert check_url("http://127.0.0.1:8787") == "http://127.0.0.1:8787"
    assert is_local_url("http://[::1]:8787") and is_local_url("http://box.localhost")
    with pytest.raises(InsecureUrlError) as caught:
        check_url("http://192.168.10.10:8787")
    assert "allow_insecure_http" in str(caught.value)
    assert check_url("http://192.168.10.10:8787", allow_insecure=True)


def test_the_tui_client_refuses_a_plain_address_unless_told():
    with pytest.raises(ApiError, match="plain http"):
        CloudmorrowClient(ClientConfig(api_url="http://192.168.10.10:8787"))
    CloudmorrowClient(ClientConfig(api_url="http://192.168.10.10:8787", allow_insecure_http=True))
    CloudmorrowClient(ClientConfig(api_url="http://127.0.0.1:8787"))


def test_the_agent_refuses_a_plain_address_unless_told():
    with pytest.raises(AgentApiError, match="plain http"):
        AgentClient(AgentConfig(server_url="http://192.168.10.10:8787"))
    AgentClient(AgentConfig(server_url="http://192.168.10.10:8787", allow_insecure_http=True))
