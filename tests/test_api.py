from __future__ import annotations

from tests.conftest import ADMIN, GUEST, token_for


def test_health_needs_no_auth(client):
    payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert payload["users"] == 2


def test_notes_require_auth(client):
    assert client.get("/api/notes/tree").status_code == 401


def test_bad_password_is_rejected(client):
    response = client.post(
        "/api/auth/login", json={"username": ADMIN[0], "password": "wrong-password"}
    )
    assert response.status_code == 401


def test_login_and_me(client, auth):
    me = client.get("/api/auth/me", headers=auth).json()
    assert me["username"] == ADMIN[0]
    assert me["is_admin"] is True


def test_note_lifecycle(client, auth):
    created = client.post(
        "/api/notes/file", json={"path": "work/plan", "content": "# Plan\n"}, headers=auth
    )
    assert created.status_code == 201
    assert created.json()["path"] == "work/plan.md"

    tree = client.get("/api/notes/tree", headers=auth).json()
    assert tree["children"][0]["name"] == "work"
    assert tree["children"][0]["children"][0]["name"] == "plan.md"

    rev = created.json()["rev"]
    updated = client.put(
        "/api/notes/file/work/plan.md",
        json={"content": "# Plan\n\n- [ ] ship it\n", "rev": rev},
        headers=auth,
    )
    assert updated.status_code == 200
    assert "ship it" in client.get("/api/notes/file/work/plan.md", headers=auth).json()["content"]

    moved = client.post(
        "/api/notes/move", json={"src": "work/plan.md", "dest": "done/plan.md"}, headers=auth
    )
    assert moved.json()["path"] == "done/plan.md"

    assert client.delete("/api/notes/done/plan.md", headers=auth).status_code == 204
    assert client.get("/api/notes/file/done/plan.md", headers=auth).status_code == 404


def test_stale_write_returns_conflict(client, auth):
    created = client.post("/api/notes/file", json={"path": "n.md", "content": "one"}, headers=auth)
    stale_rev = created.json()["rev"]
    client.put("/api/notes/file/n.md", json={"content": "two"}, headers=auth)
    conflict = client.put(
        "/api/notes/file/n.md", json={"content": "three", "rev": stale_rev}, headers=auth
    )
    assert conflict.status_code == 409
    detail = conflict.json()["detail"]
    assert detail["error"] == "conflict"
    assert detail["content"] == "two"


def test_path_traversal_is_refused(client, auth):
    assert (
        client.put(
            "/api/notes/file/../../escape.md", json={"content": "nope"}, headers=auth
        ).status_code
        in (400, 404)
    )
    assert client.post(
        "/api/notes/file", json={"path": "../escape.md", "content": "nope"}, headers=auth
    ).status_code == 400


def test_users_have_separate_note_trees(client, auth):
    client.post("/api/notes/file", json={"path": "private.md", "content": "mine"}, headers=auth)
    guest_auth = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    assert client.get("/api/notes/tree", headers=guest_auth).json()["children"] == []
    assert client.get("/api/notes/file/private.md", headers=guest_auth).status_code == 404


def test_shared_notes_mode(config, users):
    from fastapi.testclient import TestClient

    from cloudmorrow.server.app import create_app

    config.per_user_dirs = False
    shared = TestClient(create_app(config))
    admin_auth = {"Authorization": f"Bearer {token_for(shared, *ADMIN)}"}
    guest_auth = {"Authorization": f"Bearer {token_for(shared, *GUEST)}"}
    shared.post("/api/notes/file", json={"path": "team.md", "content": "ours"}, headers=admin_auth)
    assert shared.get("/api/notes/file/team.md", headers=guest_auth).json()["content"] == "ours"


def test_user_administration(client, auth):
    created = client.post(
        "/api/users",
        json={"username": "deploy", "password": "deploysecret1", "display_name": "Deploy bot"},
        headers=auth,
    )
    assert created.status_code == 201
    assert created.json()["username"] == "deploy"
    assert {u["username"] for u in client.get("/api/users", headers=auth).json()} == {
        "bram",
        "guest",
        "deploy",
    }
    assert client.delete("/api/users/deploy", headers=auth).status_code == 204


def test_non_admin_cannot_manage_users(client):
    guest_auth = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    assert client.get("/api/users", headers=guest_auth).status_code == 403
    assert (
        client.post(
            "/api/users",
            json={"username": "x", "password": "passwordpassword"},
            headers=guest_auth,
        ).status_code
        == 403
    )


def test_deactivated_user_cannot_log_in(client, users):
    users.update(GUEST[0], is_active=False)
    assert (
        client.post(
            "/api/auth/login", json={"username": GUEST[0], "password": GUEST[1]}
        ).status_code
        == 401
    )


def test_change_own_password(client, auth):
    assert (
        client.post(
            "/api/auth/password",
            json={"current_password": ADMIN[1], "new_password": "brand-new-secret"},
            headers=auth,
        ).status_code
        == 204
    )
    assert (
        client.post(
            "/api/auth/login", json={"username": ADMIN[0], "password": "brand-new-secret"}
        ).status_code
        == 200
    )
