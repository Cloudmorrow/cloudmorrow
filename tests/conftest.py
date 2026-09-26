from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cloudmorrow.client.config import ClientConfig
from cloudmorrow.server.app import create_app
from cloudmorrow.server.config import ServerConfig
from cloudmorrow.server.db import UserStore
from cloudmorrow.server.security import hash_password

ADMIN = ("bram", "supersecret1")
GUEST = ("guest", "guestsecret1")


@pytest.fixture(autouse=True)
def isolated_client_config(tmp_path_factory, monkeypatch):
    """Point the client's config dir somewhere disposable, for every test.

    The client writes credentials next to its config, so anything exercising
    a sign-in would otherwise land
    in the config of whoever is running the tests. Autouse because the test
    that needs this is always the one that forgot to ask for it.
    """
    monkeypatch.setenv(
        "CLOUDMORROW_CONFIG_DIR", str(tmp_path_factory.mktemp("client-config"))
    )


# A local copy of the Quill Catalog, so no test reaches the network.
QUILL_CATALOG = Path(__file__).parent / "fixtures" / "quills"


@pytest.fixture()
def config(tmp_path) -> ServerConfig:
    return ServerConfig(
        notes_dir=tmp_path / "notes",
        data_dir=tmp_path / "data",
        secret_key="test-signing-key-that-is-long-enough-for-hs256",
        token_ttl_hours=1,
        quill_catalog=str(QUILL_CATALOG),
    )


@pytest.fixture()
def users(config) -> UserStore:
    config.ensure_dirs()
    store = UserStore(config.db_path)
    store.create(ADMIN[0], hash_password(ADMIN[1]), is_admin=True)
    store.create(GUEST[0], hash_password(GUEST[1]))
    return store


@pytest.fixture()
def client(config, users) -> TestClient:
    return TestClient(create_app(config))


def token_for(client: TestClient, username: str, password: str) -> str:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture()
def auth(client) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}


@pytest.fixture()
def app(tmp_path, monkeypatch):
    """The real app with a fake server, and no stored session to resume."""
    # Imported here, so a server test does not load the terminal app.
    from cloudmorrow.tui.app import CloudmorrowApp
    from tests.tui_harness import FakeClient

    monkeypatch.setenv("CLOUDMORROW_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(CloudmorrowApp, "_resume_session", lambda self: None)
    instance = CloudmorrowApp(ClientConfig(api_url="http://test.invalid", vault="verticore"))
    instance.client = FakeClient()
    instance.username = "bram"
    return instance


@pytest.fixture()
def tasks_quill(client) -> TestClient:
    """The client, with the Tasks Quill installed from the local catalog."""
    client.app.state.cloudmorrow.quills.install_from_catalog("tasks")
    return client


@pytest.fixture()
def notes_quill(client) -> TestClient:
    """The client, with the Notes Quill installed from the local catalog."""
    client.app.state.cloudmorrow.quills.install_from_catalog("notes")
    return client
