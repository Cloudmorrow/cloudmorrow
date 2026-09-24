"""First boot from the browser: a server with nobody on it is set up on its
first visit, and never again."""

from __future__ import annotations

from fastapi.testclient import TestClient

from cloudmorrow.server.app import create_app
from cloudmorrow.server.db import UserStore
from tests.conftest import ADMIN, token_for


def fresh(config) -> TestClient:
    config.ensure_dirs()
    return TestClient(create_app(config))


def test_a_fresh_server_sends_every_front_door_to_setup(config):
    with fresh(config) as client:
        for path in ("/", "/install", "/app"):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 307, path
            assert response.headers["location"] == "/setup"
        page = client.get("/setup")
        assert page.status_code == 200
        assert "Name your cloud" in page.text
        assert 'value="Cloudmorrow"' in page.text
        assert client.get("/api/health").json()["setup"] is True
        # The assets the app needs are still there, and the API still answers.
        assert client.get("/app/manifest.webmanifest").status_code == 200
        assert client.get("/install.sh").status_code == 200


def test_setup_names_the_cloud_and_makes_the_administrator(config):
    with fresh(config) as client:
        response = client.post(
            "/api/setup",
            json={"name": "  The   Larsens ", "username": "alice", "password": "longenough"},
        )
        assert response.status_code == 201, response.text
        assert response.json() == {"name": "The Larsens", "username": "alice"}

        store = UserStore(config.db_path)
        assert store.require("alice").is_admin
        assert config.notes_root("alice").is_dir()

        health = client.get("/api/health").json()
        assert health["name"] == "The Larsens"
        assert health["setup"] is False
        assert "<title>The Larsens</title>" in client.get("/app").text
        assert client.get("/app/manifest.webmanifest").json()["name"] == "The Larsens"

        # And it can sign in with what it typed.
        token = token_for(client, "alice", "longenough")
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert me["username"] == "alice"


def test_setup_is_over_once_anybody_exists(config):
    with fresh(config) as client:
        client.post(
            "/api/setup", json={"name": "Home", "username": "alice", "password": "longenough"}
        )
        again = client.post(
            "/api/setup", json={"name": "Mine", "username": "mallory", "password": "longenough"}
        )
        assert again.status_code == 409
        assert client.get("/setup", follow_redirects=False).headers["location"] == "/app"
        assert client.get("/", follow_redirects=False).status_code == 200
        assert UserStore(config.db_path).count() == 1


def test_setup_refuses_what_the_server_would(config):
    with fresh(config) as client:
        bad_name = client.post(
            "/api/setup", json={"name": "   ", "username": "alice", "password": "longenough"}
        )
        assert bad_name.status_code in (400, 422)
        bad_user = client.post(
            "/api/setup", json={"name": "Home", "username": "-alice", "password": "longenough"}
        )
        assert bad_user.status_code == 400
        assert "username" in bad_user.json()["detail"]
        short = client.post(
            "/api/setup", json={"name": "Home", "username": "alice", "password": "short"}
        )
        assert short.status_code == 422
        # Nothing was made along the way, so setup is still open.
        assert UserStore(config.db_path).count() == 0
        assert client.get("/setup").status_code == 200


def test_the_name_in_the_page_is_text_not_markup(config):
    config.name = "<b>Larsens</b>"
    with fresh(config) as client:
        page = client.get("/setup").text
        assert "<b>Larsens</b>" not in page
        assert "&lt;b&gt;Larsens&lt;/b&gt;" in page


def test_an_administrator_can_rename_the_cloud_later(client, auth):
    assert client.get("/api/server/settings", headers=auth).json() == {"name": "Cloudmorrow"}
    renamed = client.patch("/api/server/settings", json={"name": "Number 12"}, headers=auth)
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Number 12"
    assert client.get("/api/health").json()["name"] == "Number 12"
    assert client.get("/").text.count("Number 12") >= 2
    # The app's own name wins over the config's from then on.
    assert client.get("/app/manifest.webmanifest").json()["short_name"] == "Number 12"


def test_only_an_administrator_renames_it(client):
    from tests.conftest import GUEST

    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    assert client.get("/api/server/settings", headers=guest).status_code == 200
    forbidden = client.patch("/api/server/settings", json={"name": "Mine"}, headers=guest)
    assert forbidden.status_code == 403
    assert client.patch("/api/server/settings", json={"name": "Mine"}).status_code == 401
    admin = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    assert client.patch("/api/server/settings", json={"name": " "}, headers=admin).status_code in (
        400,
        422,
    )
