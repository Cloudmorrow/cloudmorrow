"""Roles, user types, and switching a server feature off.

The API half of the Administration panel: what an administrator may change
about an account, and what happens to a feature's endpoints when it is off.
"""

from __future__ import annotations

from cloudmorrow.server.db import UserStore, connect
from cloudmorrow.server.security import hash_password
from tests.conftest import ADMIN, GUEST, token_for


def headers(client, who) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(client, *who)}"}


# -- roles and types -------------------------------------------------------
def test_an_account_has_a_role_and_a_type(client, auth):
    listed = client.get("/api/users", headers=auth).json()
    by_name = {user["username"]: user for user in listed}
    assert by_name["bram"]["role"] == "administrator"
    assert by_name["guest"]["role"] == "user"
    assert by_name["guest"]["user_type"] == "human"


def test_a_screen_on_the_wall_is_a_systems_user_that_displays_dashboards(client, auth):
    created = client.post(
        "/api/users",
        headers=auth,
        json={
            "username": "hallway",
            "password": "supersecret1",
            "role": "dashboard_displayer",
            "user_type": "systems_user",
        },
    )
    assert created.status_code == 201, created.text
    account = created.json()
    assert account["role"] == "dashboard_displayer"
    assert account["user_type"] == "systems_user"
    # It may sign in, and it is not an administrator.
    assert account["is_admin"] is False
    signed_in = client.post(
        "/api/auth/login", json={"username": "hallway", "password": "supersecret1"}
    )
    assert signed_in.status_code == 200
    assert signed_in.json()["user"]["role"] == "dashboard_displayer"


def test_the_role_decides_what_is_admin(client, auth):
    promoted = client.patch(
        "/api/users/guest", headers=auth, json={"role": "administrator"}
    ).json()
    assert promoted["is_admin"] is True
    # And the guest can now read the user list they could not read before.
    assert client.get("/api/users", headers=headers(client, GUEST)).status_code == 200
    demoted = client.patch("/api/users/guest", headers=auth, json={"role": "user"}).json()
    assert demoted["is_admin"] is False


def test_an_admin_cannot_demote_themselves_by_role_either(client, auth):
    refused = client.patch(f"/api/users/{ADMIN[0]}", headers=auth, json={"role": "user"})
    assert refused.status_code == 400
    assert "demote" in refused.json()["detail"]


def test_a_role_that_is_not_a_role_is_refused(client, auth):
    refused = client.post(
        "/api/users",
        headers=auth,
        json={"username": "nina", "password": "supersecret1", "role": "wizard"},
    )
    assert refused.status_code == 400
    assert "role must be one of" in refused.json()["detail"]


def test_an_account_from_before_roles_existed_keeps_its_rights(config, tmp_path):
    """The flag was the truth once; the migration makes the role match it."""
    config.ensure_dirs()
    store = UserStore(config.db_path)
    store.create("bram", hash_password("supersecret1"), is_admin=True)
    # Put the database back the way it looked before the column existed.
    with connect(config.db_path) as conn:
        conn.execute("ALTER TABLE users DROP COLUMN role")
    reopened = UserStore(config.db_path)
    user = reopened.require("bram")
    assert user.role == "administrator"
    assert user.is_admin is True


# -- features --------------------------------------------------------------
def test_every_feature_is_on_to_begin_with(client, auth):
    listed = client.get("/api/server/features", headers=auth).json()
    # The catalogue grows with the app; these four are the ones with tabs.
    assert {"notes", "tasks", "secrets", "files"} <= {row["key"] for row in listed}
    assert all(row["enabled"] for row in listed)
    assert all(row["label"] and row["changed_by"] == "" for row in listed)


def test_a_switched_off_feature_closes_its_api(client, auth):
    assert client.get("/api/boards", headers=auth).status_code == 200
    switched = client.patch(
        "/api/server/features/tasks", headers=auth, json={"enabled": False}
    )
    assert switched.status_code == 200
    assert switched.json()["changed_by"] == ADMIN[0]

    refused = client.get("/api/boards", headers=auth)
    assert refused.status_code == 403
    assert refused.json()["detail"] == "Tasks is switched off on this server"
    # The rest of the server is untouched.
    assert client.get("/api/notes/tree", headers=auth).status_code == 200

    client.patch("/api/server/features/tasks", headers=auth, json={"enabled": True})
    assert client.get("/api/boards", headers=auth).status_code == 200


def test_secrets_are_a_feature_of_their_own(client, auth):
    """Switching Secrets off closes every secrets call, vaults included."""
    client.patch("/api/server/features/secrets", headers=auth, json={"enabled": False})
    assert client.get("/api/secrets", headers=auth).status_code == 403
    assert client.get("/api/secrets/vaults", headers=auth).status_code == 403


def test_only_an_administrator_may_switch_one(client):
    guest = headers(client, GUEST)
    # A plain user reads the list — a client has to know which tabs to draw.
    assert client.get("/api/server/features", headers=guest).status_code == 200
    refused = client.patch(
        "/api/server/features/notes", headers=guest, json={"enabled": False}
    )
    assert refused.status_code == 403


def test_a_feature_nobody_has_heard_of_is_a_404(client, auth):
    refused = client.patch(
        "/api/server/features/telepathy", headers=auth, json={"enabled": False}
    )
    assert refused.status_code == 404
