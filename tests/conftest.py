from __future__ import annotations

import base64
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from cloudmorrow.client.config import ClientConfig
from cloudmorrow.server import database
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
    monkeypatch.setenv("CLOUDMORROW_CONFIG_DIR", str(tmp_path_factory.mktemp("client-config")))


# A local copy of the Quill Catalog, so no test reaches the network.
QUILL_CATALOG = Path(__file__).parent / "fixtures" / "quills"

# The suite runs on SQLite, and on PostgreSQL when this names a server:
# every test that opens a database file gets a schema of its own there
# instead (`database.stand_in`), so the same tests say the same things
# about both engines. What is SQLite's alone is marked `sqlite_only`.
POSTGRES_URL = os.environ.get("CLOUDMORROW_TEST_DATABASE_URL", "").strip()
sqlite_only = pytest.mark.skipif(bool(POSTGRES_URL), reason="what SQLite alone does")


@pytest.fixture(scope="session")
def postgres_database():
    """One database for the run, in C collation — so rows sort as SQLite sorts
    them, bytewise — dropped when the run is over."""
    if not POSTGRES_URL:
        yield ""
        return
    import psycopg

    name = "cm_test_" + secrets.token_hex(4)
    with psycopg.connect(POSTGRES_URL, autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {name} TEMPLATE template0 ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C'")
    yield urlsplit(POSTGRES_URL)._replace(path=f"/{name}", query="").geturl()
    with psycopg.connect(POSTGRES_URL, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE {name} WITH (FORCE)")


@pytest.fixture(autouse=True)
def database_engine(postgres_database, monkeypatch):
    """On PostgreSQL, a schema per database file the test opens; dropped after."""
    if not postgres_database:
        yield
        return
    import psycopg

    admin = psycopg.connect(postgres_database, autocommit=True)
    made: dict[str, database.Database] = {}
    schemas: list[str] = []

    def stand_in(path: Path) -> database.Database:
        key = str(path.expanduser().resolve())
        db = made.get(key)
        if db is None:
            schema = "t_" + secrets.token_hex(5)
            admin.execute(f"CREATE SCHEMA {schema}")
            schemas.append(schema)
            db = made[key] = database.open(f"{postgres_database}?options=-c%20search_path%3D{schema}", path=path)
        return db

    monkeypatch.setattr(database, "stand_in", stand_in)
    yield
    for db in made.values():
        database.forget(db)
    for schema in schemas:
        admin.execute(f"DROP SCHEMA {schema} CASCADE")
    admin.close()


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
def guest_auth(client) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(client, *GUEST)}"}


def basic(username: str, secret: str) -> dict[str, str]:
    """HTTP Basic headers, the way a WebDAV client signs in."""
    raw = base64.b64encode(f"{username}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


def js_code(source: str) -> str:
    """JavaScript with its comments taken out, so a test reads only the code."""
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)


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
def chat_quill(client) -> TestClient:
    """The client, with the Chat Quill installed from the local catalog."""
    client.app.state.cloudmorrow.quills.install_from_catalog("chat")
    return client


@pytest.fixture()
def notes_quill(client) -> TestClient:
    """The client, with the Notes Quill installed from the local catalog."""
    client.app.state.cloudmorrow.quills.install_from_catalog("notes")
    return client


@pytest.fixture()
def secrets_quill(client) -> TestClient:
    """The client, with the Secrets Quill installed from the local catalog."""
    client.app.state.cloudmorrow.quills.install_from_catalog("secrets")
    return client
