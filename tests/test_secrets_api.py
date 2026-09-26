from __future__ import annotations

import pytest

from cloudmorrow import dotenv
from tests.conftest import ADMIN, GUEST, token_for


@pytest.fixture(autouse=True)
def secrets_installed(secrets_quill):
    """Every test here talks to a server that has the Secrets Quill."""
    return secrets_quill


def vault_headers(auth: dict[str, str], vault: str) -> dict[str, str]:
    return {**auth, "X-Cloudmorrow-Vault": vault}


@pytest.fixture()
def plain(client) -> dict[str, str]:
    """Signed in, naming no vault: the default one."""
    return {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}


@pytest.fixture()
def auth(auth) -> dict[str, str]:
    """Signed in, in a vault of one's own."""
    return vault_headers(auth, "verticore")


def test_secrets_require_auth(client):
    assert client.get("/api/secrets").status_code == 401


def test_import_list_and_read(client, auth):
    imported = client.post(
        "/api/secrets/import",
        json={"environment": "production", "entries": {"API_KEY": "sk-live", "DEBUG": "false"}},
        headers=auth,
    )
    assert imported.status_code == 200
    assert imported.json()["added"] == ["API_KEY", "DEBUG"]

    listed = client.get("/api/secrets", params={"env": "production"}, headers=auth).json()
    assert [s["key"] for s in listed] == ["API_KEY", "DEBUG"]
    # A listing describes a secret without handing it over.
    assert [s["value"] for s in listed] == [None, None]
    assert listed[0]["length"] == len("sk-live")
    assert listed[0]["fingerprint"]

    revealed = client.get(
        "/api/secrets", params={"env": "production", "reveal": True}, headers=auth
    ).json()
    assert revealed[0]["value"] == "sk-live"

    one = client.get(
        "/api/secrets/item/API_KEY", params={"env": "production"}, headers=auth
    ).json()
    assert one["value"] == "sk-live"


def test_write_and_delete_one(client, auth):
    written = client.put(
        "/api/secrets/item/TOKEN", json={"value": "abc", "environment": "test"}, headers=auth
    )
    assert written.status_code == 200
    assert written.json()["environment"] == "test"
    assert client.delete(
        "/api/secrets/item/TOKEN", params={"env": "test"}, headers=auth
    ).status_code == 204
    assert client.get(
        "/api/secrets/item/TOKEN", params={"env": "test"}, headers=auth
    ).status_code == 404


def test_environments_are_listed_with_counts(client, auth):
    client.post(
        "/api/secrets/import",
        json={"environment": "local", "entries": {"A": "1", "B": "2"}},
        headers=auth,
    )
    client.post(
        "/api/secrets/import", json={"environment": "production", "entries": {"A": "9"}},
        headers=auth,
    )
    listed = client.get("/api/secrets/environments", headers=auth).json()
    assert [(e["environment"], e["secrets"]) for e in listed] == [("local", 2), ("production", 1)]


def test_export_is_a_dotenv_file_that_parses_back(client, auth):
    entries = {"API_KEY": "sk-live", "GREETING": "hello world", "EMPTY": ""}
    client.post(
        "/api/secrets/import", json={"environment": "production", "entries": entries},
        headers=auth,
    )
    exported = client.get("/api/secrets/export", params={"env": "production"}, headers=auth)
    assert exported.headers["cache-control"] == "no-store"
    assert dotenv.parse(exported.text) == entries

    as_json = client.get(
        "/api/secrets/export", params={"env": "production", "format": "json"}, headers=auth
    )
    assert as_json.json() == entries


def test_two_vaults_keep_their_own_copy_of_a_key(client, auth):
    """The same key name in two vaults is two secrets, not one."""
    other = vault_headers(auth, "home-lab")
    client.post(
        "/api/secrets/import",
        json={"environment": "local", "entries": {"DATABASE_URL": "for the homelab"}},
        headers=other,
    )
    client.post(
        "/api/secrets/import",
        json={"environment": "local", "entries": {"DATABASE_URL": "for verticore"}},
        headers=auth,
    )

    assert client.get("/api/secrets", params={"env": "local"}, headers=other).json()[0][
        "vault"
    ] == "home-lab"
    for headers, expected in ((other, "for the homelab"), (auth, "for verticore")):
        found = client.get(
            "/api/secrets/item/DATABASE_URL", params={"env": "local"}, headers=headers
        )
        assert found.json()["value"] == expected


def test_no_vault_named_means_the_default_one(client, plain):
    client.put("/api/secrets/item/K", json={"value": "v", "environment": "local"}, headers=plain)
    listed = client.get("/api/secrets", params={"env": "local"}, headers=plain).json()
    assert [(s["key"], s["vault"]) for s in listed] == [("K", "default")]
    # The same place, named.
    named = client.get(
        "/api/secrets", params={"env": "local", "vault": "default"}, headers=plain
    ).json()
    assert [s["key"] for s in named] == ["K"]
    assert client.get("/api/secrets", headers=vault_headers(plain, "empty")).json() == []


def test_a_bad_vault_name_is_refused(client, auth):
    assert client.get("/api/secrets", headers=vault_headers(auth, "Not A Vault")).status_code == 400


def test_vaults_are_listed_with_what_they_hold(client, auth, plain):
    client.post(
        "/api/secrets/import", json={"environment": "local", "entries": {"A": "1", "B": "2"}},
        headers=auth,
    )
    client.put("/api/secrets/item/C", json={"value": "3", "environment": "local"}, headers=plain)
    listed = client.get("/api/secrets/vaults", headers=plain).json()
    assert [(v["vault"], v["secrets"], v["environments"]) for v in listed] == [
        ("default", 1, 1),
        ("verticore", 2, 1),
    ]


def test_secrets_belong_to_one_user(client, auth):
    client.post(
        "/api/secrets/import", json={"environment": "local", "entries": {"K": "mine"}},
        headers=auth,
    )
    # The guest has a vault of their own with the same name, and cannot see in.
    guest = vault_headers({"Authorization": f"Bearer {token_for(client, *GUEST)}"}, "verticore")
    assert client.get("/api/secrets", params={"env": "local"}, headers=guest).json() == []
    assert client.get(
        "/api/secrets/item/K", params={"env": "local"}, headers=guest
    ).status_code == 404


def test_prune_and_dry_run_over_the_wire(client, auth):
    client.post(
        "/api/secrets/import", json={"environment": "local", "entries": {"A": "1", "B": "2"}},
        headers=auth,
    )
    dry = client.post(
        "/api/secrets/import",
        json={"environment": "local", "entries": {"A": "1"}, "prune": True, "dry_run": True},
        headers=auth,
    ).json()
    assert dry["removed"] == ["B"] and dry["dry_run"] is True
    assert len(client.get("/api/secrets", params={"env": "local"}, headers=auth).json()) == 2

    client.post(
        "/api/secrets/import",
        json={"environment": "local", "entries": {"A": "1"}, "prune": True},
        headers=auth,
    )
    assert [
        s["key"] for s in client.get("/api/secrets", params={"env": "local"}, headers=auth).json()
    ] == ["A"]


def test_purging_an_environment(client, auth):
    client.post(
        "/api/secrets/import", json={"environment": "test", "entries": {"A": "1", "B": "2"}},
        headers=auth,
    )
    assert client.delete("/api/secrets/environment/test", headers=auth).json()["removed"] == 2
    assert client.get("/api/secrets", params={"env": "test"}, headers=auth).json() == []


def test_bad_environments_and_keys_are_refused(client, auth):
    assert client.get(
        "/api/secrets/item/K", params={"env": "NOT VALID"}, headers=auth
    ).status_code == 400
    assert client.put(
        "/api/secrets/item/9bad", json={"value": "x", "environment": "local"}, headers=auth
    ).status_code == 400


def test_deleting_a_vault_takes_its_secrets(client, auth):
    scoped = vault_headers(auth, "taxes")
    client.post(
        "/api/secrets/import", json={"environment": "local", "entries": {"K": "v"}},
        headers=scoped,
    )
    client.post(
        "/api/secrets/import", json={"environment": "production", "entries": {"K": "v"}},
        headers=scoped,
    )
    assert client.delete("/api/secrets/vault/taxes", headers=auth).json()["removed"] == 2
    assert client.get("/api/secrets", headers=scoped).json() == []
    # The vault it was called from is untouched.
    client.put("/api/secrets/item/MINE", json={"value": "v", "environment": "local"}, headers=auth)
    assert [v["vault"] for v in client.get("/api/secrets/vaults", headers=auth).json()] == [
        "verticore"
    ]


def test_an_agent_token_cannot_read_secrets(client, auth):
    token = client.post(
        "/api/agents/enroll-token", json={"label": "nas", "ttl_minutes": 60}, headers=auth
    ).json()["enrollment_token"]
    enrolled = client.post(
        "/api/agent/enroll", json={"enrollment_token": token, "name": "nas"}
    ).json()
    agent_auth = {"Authorization": f"Bearer {enrolled['agent_token']}"}
    refused = client.get("/api/secrets", params={"env": "local"}, headers=agent_auth)
    assert refused.status_code == 401


def test_admin_is_not_a_master_key(client, auth):
    """Being admin lets you manage users, not read their secrets."""
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    client.post(
        "/api/secrets/import", json={"environment": "local", "entries": {"K": "guest's"}},
        headers=guest,
    )
    assert ADMIN[0] != GUEST[0]
    assert client.get("/api/secrets", params={"env": "local"}, headers=auth).json() == []


def test_without_the_quill_the_vaults_are_closed(config, users):
    from fastapi.testclient import TestClient

    from cloudmorrow.server.app import create_app

    bare = TestClient(create_app(config))
    bare.app.state.cloudmorrow.quills.uninstall("secrets")  # left out at install
    headers = {"Authorization": f"Bearer {token_for(bare, *ADMIN)}"}
    refused = bare.get("/api/secrets", headers=headers)
    assert refused.status_code == 403
    assert "Administration, Quills" in refused.json()["detail"]
