"""The other switch on a feature: the one in your own settings.

The server's switch is an administrator's and closes the API. This one is
yours, hides a tab, and is only ever offered for what the server already
offers — see `server/features.py`.
"""

from __future__ import annotations

import pytest

from cloudmorrow.server.features import FEATURE_KEYS
from tests.conftest import ADMIN, GUEST, token_for


@pytest.fixture()
def guest(client) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(client, *GUEST)}"}


def mine(client, auth) -> list[dict]:
    response = client.get("/api/me/features", headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def switch(client, auth, key: str, enabled: bool):
    return client.patch(f"/api/me/features/{key}", json={"enabled": enabled}, headers=auth)


def server_switch(client, auth, key: str, enabled: bool):
    response = client.patch(
        f"/api/server/features/{key}", json={"enabled": enabled}, headers=auth
    )
    assert response.status_code == 200, response.text
    return response.json()


# -- what you are offered ---------------------------------------------------------
def test_everything_is_on_for_a_fresh_account(client, auth):
    listed = mine(client, auth)
    assert [row["key"] for row in listed] == list(FEATURE_KEYS)
    assert all(row["enabled"] for row in listed)
    # It says what each one is, so a client need not carry its own copy.
    assert all(row["label"] and row["description"] for row in listed)


def test_a_feature_the_server_has_off_is_not_offered_at_all(tasks_quill, auth):
    client = tasks_quill
    server_switch(client, auth, "tasks", False)
    listed = mine(client, auth)
    assert "tasks" not in [row["key"] for row in listed]
    # Not listed as off — not listed. There is nothing to have a view about.
    assert switch(client, auth, "tasks", False).status_code == 404
    assert switch(client, auth, "tasks", True).status_code == 404


def test_an_unknown_feature_is_a_404(client, auth):
    assert switch(client, auth, "telepathy", False).status_code == 404


# -- switching one ----------------------------------------------------------------
def test_switching_one_off_is_remembered_and_reversible(client, auth):
    response = switch(client, auth, "secrets", False)
    assert response.status_code == 200
    assert response.json() == {
        "key": "secrets",
        "label": "Secrets",
        "description": "Vaults of keys and passwords, encrypted",
        "enabled": False,
    }
    assert {row["key"]: row["enabled"] for row in mine(client, auth)}["secrets"] is False
    assert switch(client, auth, "secrets", True).json()["enabled"] is True
    assert {row["key"]: row["enabled"] for row in mine(client, auth)}["secrets"] is True


def test_your_answer_is_yours_and_nobody_elses(notes_quill, auth, guest):
    client = notes_quill
    switch(client, auth, "notes", False)
    assert {row["key"]: row["enabled"] for row in mine(client, guest)}["notes"] is True


def test_it_hides_rather_than_forbids(notes_quill, auth):
    """A preference is not a feature switch: the API still answers you.

    Locking an account out of its own notes from the phone it just tapped a
    box on would be a mistake with no way back.
    """
    client = notes_quill
    assert switch(client, auth, "notes", False).status_code == 200
    assert client.get("/api/notes/tree", headers=auth).status_code == 200
    assert client.get("/api/records/note", headers=auth).status_code == 200


def test_the_server_switch_still_wins(tasks_quill, auth):
    client = tasks_quill
    switch(client, auth, "tasks", True)
    server_switch(client, auth, "tasks", False)
    assert client.get("/api/records/board", headers=auth).status_code == 403
    assert "tasks" not in [row["key"] for row in mine(client, auth)]
    # And it comes back as the account left it, not as the server found it.
    server_switch(client, auth, "tasks", True)
    assert {row["key"]: row["enabled"] for row in mine(client, auth)}["tasks"] is True


def test_what_you_switch_off_you_are_not_counted_for(chat_quill, auth, guest):
    """The badge is one person's, so it follows that person's switches."""
    client = chat_quill
    general = client.get("/api/records/channel", headers=auth).json()[0]
    client.post(
        "/api/records/message", json={"fields": {"channel": general["id"], "body": "morning"}},
        headers=guest,
    )
    assert client.get("/api/push/badge", headers=auth).json()["messages"] == 1
    switch(client, auth, "chat", False)
    assert client.get("/api/push/badge", headers=auth).json()["messages"] == 0
    # The guest still gets their own count, whatever this account decided.
    assert client.get("/api/push/badge", headers=guest).json()["messages"] == 0


def test_an_account_that_goes_takes_its_answers_with_it(client, auth, guest):
    switch(client, guest, "secrets", False)
    assert client.delete(f"/api/users/{GUEST[0]}", headers=auth).status_code == 204
    made = client.post(
        "/api/users",
        json={"username": GUEST[0], "password": "anothersecret1"},
        headers=auth,
    )
    assert made.status_code == 201, made.text
    again = {"Authorization": f"Bearer {token_for(client, GUEST[0], 'anothersecret1')}"}
    assert all(row["enabled"] for row in mine(client, again)), "a new account has everything"


# -- the two lists are different things ---------------------------------------------
def test_the_servers_own_list_is_unchanged_by_yours(client, auth):
    switch(client, auth, "secrets", False)
    server = {row["key"]: row["enabled"] for row in client.get(
        "/api/server/features", headers=auth
    ).json()}
    assert server["secrets"] is True, "your preference is not the server's setting"


def test_only_an_administrator_throws_the_servers_switch(notes_quill, guest):
    client = notes_quill
    assert client.patch(
        "/api/server/features/notes", json={"enabled": False}, headers=guest
    ).status_code == 403
    # But anybody may switch their own.
    assert switch(client, guest, "notes", False).status_code == 200


def test_the_store_answers_for_one_person(config, users):
    """`enabled_for` is the two switches and'ed, which is what a client draws."""
    from cloudmorrow.server.features import FeatureStore

    store = FeatureStore(config.db_path)
    assert store.enabled_for(ADMIN[0], "secrets") is True
    store.set_for(ADMIN[0], "secrets", False)
    assert store.enabled_for(ADMIN[0], "secrets") is False
    assert store.enabled_for(GUEST[0], "secrets") is True
    assert "secrets" not in store.enabled_keys_for(ADMIN[0])
    assert "secrets" in store.enabled_keys_for(GUEST[0])

    store.set("secrets", False, changed_by=ADMIN[0])
    assert store.enabled_for(GUEST[0], "secrets") is False
    assert "secrets" not in [row["key"] for row in store.list_for(GUEST[0])]
