from __future__ import annotations

from tests.conftest import ADMIN, GUEST, token_for


def test_health_needs_no_auth(client):
    payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert payload["users"] == 2


def test_records_require_auth(client):
    assert client.get("/api/records/file?share=my-files").status_code == 401


def test_bad_password_is_rejected(client):
    response = client.post("/api/auth/login", json={"username": ADMIN[0], "password": "wrong-password"})
    assert response.status_code == 401


def test_login_and_me(client, auth):
    me = client.get("/api/auth/me", headers=auth).json()
    assert me["username"] == ADMIN[0]
    assert me["is_admin"] is True


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
    assert client.post("/api/auth/login", json={"username": GUEST[0], "password": GUEST[1]}).status_code == 401


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
        client.post("/api/auth/login", json={"username": ADMIN[0], "password": "brand-new-secret"}).status_code == 200
    )
