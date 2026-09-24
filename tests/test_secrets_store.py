from __future__ import annotations

import os

import pytest

from cloudmorrow.server.crypto import (
    SealError,
    associated_data,
    load_or_create_key,
    seal,
    unseal,
)
from cloudmorrow.server.secrets import (
    InvalidEnvironmentError,
    InvalidSecretNameError,
    SecretStore,
    UnknownSecretError,
    validate_environment,
)

OWNER = "bram"
OTHER = "guest"
# No vault named: the default one, which everybody has.
NONE = ""


@pytest.fixture()
def store(tmp_path) -> SecretStore:
    return SecretStore(tmp_path / "cloudmorrow.db", os.urandom(32))


def test_set_and_get(store):
    secret, action = store.set(OWNER, NONE, "production", "API_KEY", "sk-live")
    assert action == "created"
    assert secret.length == len("sk-live")
    assert store.get(OWNER, NONE, "production", "API_KEY").value == "sk-live"


def test_setting_the_same_value_again_is_a_no_op(store):
    store.set(OWNER, NONE, "local", "K", "v")
    _, action = store.set(OWNER, NONE, "local", "K", "v")
    assert action == "unchanged"
    _, action = store.set(OWNER, NONE, "local", "K", "w")
    assert action == "updated"


def test_values_are_not_on_disk_in_the_clear(store):
    store.set(OWNER, NONE, "production", "API_KEY", "hunter2-in-the-clear")
    assert b"hunter2-in-the-clear" not in store.db_path.read_bytes()
    # The name is deliberately readable, so listing needs no key.
    assert b"API_KEY" in store.db_path.read_bytes()


def test_environments_are_separate(store):
    store.set(OWNER, NONE, "local", "DATABASE_URL", "sqlite://dev")
    store.set(OWNER, NONE, "production", "DATABASE_URL", "postgres://prod")
    assert store.get(OWNER, NONE, "local", "DATABASE_URL").value == "sqlite://dev"
    assert store.get(OWNER, NONE, "production", "DATABASE_URL").value == "postgres://prod"
    assert [e.environment for e in store.environments(OWNER, NONE)] == ["local", "production"]
    assert [e.secrets for e in store.environments(OWNER, NONE)] == [1, 1]


def test_vaults_and_owners_are_separate(store):
    store.set(OWNER, NONE, "local", "K", "in the default vault")
    store.set(OWNER, "home-lab", "local", "K", "in the vault")
    store.set(OTHER, NONE, "local", "K", "someone else's")
    assert store.get(OWNER, NONE, "local", "K").value == "in the default vault"
    assert store.get(OWNER, "default", "local", "K").value == "in the default vault"
    assert store.get(OWNER, "home-lab", "local", "K").value == "in the vault"
    assert store.get(OTHER, NONE, "local", "K").value == "someone else's"
    assert len(store.list(OWNER, NONE, "local")) == 1


def test_vaults_are_listed_with_what_they_hold(store):
    store.set(OWNER, NONE, "local", "A", "1")
    store.set(OWNER, "home", "local", "B", "2")
    store.set(OWNER, "home", "production", "C", "3")
    store.set(OTHER, "home", "local", "D", "4")
    listed = store.vaults(OWNER)
    assert [(v.vault, v.secrets, v.environments) for v in listed] == [
        ("default", 1, 1),
        ("home", 2, 2),
    ]
    assert store.get(OWNER, "home", "local", "B").vault == "home"


def test_deleting_a_vault_takes_every_environment_of_it(store):
    store.set(OWNER, "home", "local", "A", "1")
    store.set(OWNER, "home", "production", "B", "2")
    store.set(OWNER, NONE, "local", "C", "3")
    assert store.delete_vault(OWNER, "home") == 2
    assert store.vaults(OWNER) == [store.vaults(OWNER)[0]]
    assert store.vaults(OWNER)[0].vault == "default"


def test_a_vault_name_is_checked(store):
    from cloudmorrow.server.secrets import InvalidVaultError

    with pytest.raises(InvalidVaultError):
        store.set(OWNER, "Not A Vault", "local", "K", "v")


def test_listing_hides_values_unless_asked(store):
    store.set(OWNER, NONE, "local", "K", "v")
    assert store.list(OWNER, NONE, "local")[0].value is None
    assert store.list(OWNER, NONE, "local", reveal=True)[0].value == "v"


def test_listing_every_environment(store):
    store.set(OWNER, NONE, "local", "A", "1")
    store.set(OWNER, NONE, "production", "B", "2")
    assert [(s.environment, s.key) for s in store.list(OWNER, NONE)] == [
        ("local", "A"),
        ("production", "B"),
    ]


def test_import_reports_what_it_did(store):
    first = store.set_many(OWNER, NONE, "local", {"A": "1", "B": "2"})
    assert first.added == ["A", "B"]
    second = store.set_many(OWNER, NONE, "local", {"A": "1", "B": "changed", "C": "3"})
    assert (second.added, second.updated, second.unchanged) == (["C"], ["B"], ["A"])


def test_import_can_keep_what_is_there(store):
    store.set(OWNER, NONE, "local", "A", "original")
    result = store.set_many(OWNER, NONE, "local", {"A": "new", "B": "2"}, overwrite=False)
    assert result.skipped == ["A"]
    assert store.get(OWNER, NONE, "local", "A").value == "original"


def test_import_can_prune_to_match_the_file(store):
    store.set_many(OWNER, NONE, "local", {"A": "1", "B": "2"})
    result = store.set_many(OWNER, NONE, "local", {"A": "1"}, prune=True)
    assert result.removed == ["B"]
    assert [s.key for s in store.list(OWNER, NONE, "local")] == ["A"]


def test_a_dry_run_writes_nothing(store):
    store.set_many(OWNER, NONE, "local", {"A": "1", "B": "2"})
    result = store.set_many(OWNER, NONE, "local", {"A": "9", "C": "3"}, prune=True, dry_run=True)
    assert (result.added, result.updated, result.removed) == (["C"], ["A"], ["B"])
    assert result.dry_run is True
    assert {s.key for s in store.list(OWNER, NONE, "local")} == {"A", "B"}
    assert store.get(OWNER, NONE, "local", "A").value == "1"


def test_export_is_plain_pairs(store):
    store.set_many(OWNER, NONE, "production", {"B": "2", "A": "1"})
    assert store.export(OWNER, NONE, "production") == {"A": "1", "B": "2"}


def test_delete(store):
    store.set(OWNER, NONE, "local", "K", "v")
    store.delete(OWNER, NONE, "local", "K")
    assert store.get(OWNER, NONE, "local", "K") is None
    with pytest.raises(UnknownSecretError):
        store.delete(OWNER, NONE, "local", "K")


def test_delete_environment_and_scope(store):
    store.set_many(OWNER, "home-lab", "local", {"A": "1", "B": "2"})
    store.set_many(OWNER, "home-lab", "production", {"C": "3"})
    assert store.delete_environment(OWNER, "home-lab", "local") == 2
    assert store.delete_vault(OWNER, "home-lab") == 1
    assert store.environments(OWNER, "home-lab") == []


@pytest.mark.parametrize("environment", ["", "no spaces", "-leading", "e" * 33])
def test_bad_environments_are_rejected(environment):
    with pytest.raises(InvalidEnvironmentError):
        validate_environment(environment)


def test_environments_are_case_insensitive(store):
    store.set(OWNER, NONE, "Production", "K", "v")
    assert store.get(OWNER, NONE, "production", "K").value == "v"


@pytest.mark.parametrize("key", ["", "9LIVES", "has-dash", "has space", "a.b"])
def test_bad_keys_are_rejected(store, key):
    with pytest.raises(InvalidSecretNameError):
        store.set(OWNER, NONE, "local", key, "v")


def test_a_value_cannot_be_moved_to_another_row(tmp_path):
    """The seal is bound to owner, project, environment and key."""
    key = load_or_create_key(tmp_path / "secrets.key")
    blob = seal(key, "top secret", associated_data("bram", "", "production", "API_KEY"))
    assert unseal(key, blob, associated_data("bram", "", "production", "API_KEY")) == "top secret"
    for moved in (
        associated_data("guest", "", "production", "API_KEY"),
        associated_data("bram", "home-lab", "production", "API_KEY"),
        associated_data("bram", "", "local", "API_KEY"),
        associated_data("bram", "", "production", "OTHER_KEY"),
    ):
        with pytest.raises(SealError):
            unseal(key, blob, moved)


def test_the_key_file_is_private_and_stable(tmp_path):
    path = tmp_path / "secrets.key"
    key = load_or_create_key(path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert load_or_create_key(path) == key
