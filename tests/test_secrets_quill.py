"""The Secrets Quill: secrets served as records, the store they stay in, and never an assistant.

The store and `/api/secrets` are foundation and have their own tests
(test_secrets_store.py, test_secrets_api.py). These are the Quill's half:
the `vaults` backend answering the record API in the one envelope, the
value kept out of every listing, the `secret` datamodel refused to every
assistant tool, and a server from before the Quill getting it at boot.
"""

from __future__ import annotations

import pytest

from cloudmorrow.server.datamodels import DatamodelError, parse_datamodel
from cloudmorrow.server.quilljobs import SECRETS_QUILL, boot, read_meta
from cloudmorrow.server.quills import QuillRegistry
from cloudmorrow.server.records import Principal, RecordStore, Refused
from cloudmorrow.server.standard import choices, choose
from tests.conftest import ADMIN, GUEST, QUILL_CATALOG, token_for
from tests.test_mcp import call, connect


@pytest.fixture()
def api(secrets_quill):
    headers = {"Authorization": f"Bearer {token_for(secrets_quill, *ADMIN)}"}

    def call_(method, path, body=None, *, expect=200, who=headers):
        response = secrets_quill.request(method, path, json=body, headers=who)
        assert response.status_code == expect, response.text
        return response.json() if response.content else None

    call_.client = secrets_quill
    call_.headers = headers
    return call_


def put(api, key, value, env="local", vault="default"):
    api("PUT", f"/api/secrets/item/{key}?vault={vault}", {"environment": env, "value": value})


# -- the record API ---------------------------------------------------------------------
def test_a_secret_set_by_cm_secret_is_a_record_without_its_value_in_a_listing(api):
    put(api, "DATABASE_URL", "postgres://x", "production", "work")
    put(api, "API_KEY", "abc123")
    listed = api("GET", "/api/records/secret")
    assert [(r["fields"]["vault"], r["fields"]["environment"], r["fields"]["key"]) for r in listed] == [
        ("default", "local", "API_KEY"),
        ("work", "production", "DATABASE_URL"),
    ]
    # Described, never handed over: the value is null in every listing.
    assert all(r["fields"]["value"] is None for r in listed)
    assert listed[0]["fields"]["length"] == 6
    assert listed[0]["model"] == "secret" and listed[0]["written_by"] == "secrets"
    # Reading one is how a value is asked for.
    one = api("GET", f"/api/records/secret/{listed[1]['id']}")
    assert one["fields"]["value"] == "postgres://x"


def test_a_listing_is_filtered_by_vault_and_environment(api):
    put(api, "A", "1", "local", "work")
    put(api, "B", "2", "production", "work")
    put(api, "C", "3", "local", "home")
    keys = lambda query: [r["fields"]["key"] for r in api("GET", f"/api/records/secret?{query}")]  # noqa: E731
    assert keys("vault=work") == ["A", "B"]
    assert keys("vault=work&environment=production") == ["B"]
    assert keys("environment=local") == ["C", "A"]
    api("GET", "/api/records/secret?value=1", expect=400)


def test_a_secret_made_as_a_record_is_the_one_cm_secret_reads(api):
    made = api("POST", "/api/records/secret",
               {"fields": {"key": "TOKEN", "value": "s3cret", "environment": "staging"}}, expect=201)
    assert made["fields"] == {"vault": "default", "environment": "staging", "key": "TOKEN",
                              "value": "s3cret", "length": 6}
    read = api("GET", "/api/secrets/item/TOKEN?env=staging")
    assert read["value"] == "s3cret"
    # Twice is a mistake, not a quiet overwrite.
    api("POST", "/api/records/secret", {"fields": {"key": "TOKEN", "environment": "staging"}}, expect=400)
    api("POST", "/api/records/secret", {"fields": {"key": "not a name"}}, expect=400)
    api("POST", "/api/records/secret", {"fields": {"key": "X", "length": 3}}, expect=400)


def test_a_secret_is_changed_moved_and_deleted_as_a_record(api):
    made = api("POST", "/api/records/secret", {"fields": {"key": "TOKEN", "value": "one"}}, expect=201)
    changed = api("PATCH", f"/api/records/secret/{made['id']}",
                  {"fields": {"value": "two"}, "rev": made["rev"]})
    assert changed["fields"]["value"] == "two" and changed["rev"] != made["rev"]
    # The old rev is a conflict, not a loss.
    stale = api("PATCH", f"/api/records/secret/{made['id']}",
                {"fields": {"value": "three"}, "rev": made["rev"]}, expect=409)
    assert stale["detail"]["current"]["fields"]["value"] == "two"
    moved = api("PATCH", f"/api/records/secret/{made['id']}",
                {"fields": {"vault": "work", "environment": "production"}})
    assert (moved["fields"]["vault"], moved["fields"]["environment"], moved["fields"]["value"]) == (
        "work", "production", "two")
    api("GET", f"/api/records/secret/{made['id']}", expect=404)
    assert api("GET", "/api/secrets/item/TOKEN?env=production&vault=work")["value"] == "two"
    api("DELETE", f"/api/records/secret/{moved['id']}", expect=204)
    assert api("GET", "/api/records/secret") == []


def test_secrets_are_their_owners_alone(api):
    made = api("POST", "/api/records/secret", {"fields": {"key": "MINE", "value": "x"}}, expect=201)
    guest = {"Authorization": f"Bearer {token_for(api.client, *GUEST)}"}
    api("GET", f"/api/records/secret/{made['id']}", who=guest, expect=404)
    assert api("GET", "/api/records/secret", who=guest) == []
    api("DELETE", f"/api/records/secret/{made['id']}", who=guest, expect=404)


def test_a_bad_id_is_not_found(api):
    api("GET", "/api/records/secret/s_%%%", expect=404)
    api("GET", "/api/records/secret/r_notasecret", expect=404)


def test_switched_off_the_records_and_the_old_api_close_together(api):
    api("PATCH", "/api/server/features/secrets", {"enabled": False})
    api("GET", "/api/records/secret", expect=403)
    api("GET", "/api/secrets", expect=403)


# -- a secret field ----------------------------------------------------------------------
def test_a_secret_field_is_a_string_never_indexed():
    head = {"datamodel": {"id": "thing"}}
    parsed = parse_datamodel({**head, "fields": {"name": {"kind": "string"},
                                                  "pin": {"kind": "string", "secret": True}}})
    assert parsed.by_name["pin"].to_dict()["secret"] is True
    for bad in ({"kind": "int", "secret": True}, {"kind": "string", "secret": True, "indexed": True},
                {"kind": "string", "secret": "yes"}):
        with pytest.raises(DatamodelError):
            parse_datamodel({**head, "fields": {"name": {"kind": "string"}, "pin": bad}})


def test_a_secret_field_in_the_record_store_is_not_in_a_listing_either(client, tmp_path):
    folder = tmp_path / "locker"
    (folder / "datamodels").mkdir(parents=True)
    (folder / "quill.toml").write_text(
        '[quill]\nid = "locker"\nname = "Locker"\nversion = "0.1.0"\n'
        '[[screens]]\nid = "codes"\nkit = "list"\nmodel = "locker.code"\ntitle = "name"\nsubtitle = "pin"\n'
    )
    (folder / "datamodels" / "code.toml").write_text(
        '[datamodel]\nid = "locker.code"\n[fields]\nname = { kind = "string" }\n'
        'pin = { kind = "string", secret = true }\n'
    )
    state = client.app.state.cloudmorrow
    state.quills.install(folder, QUILL_CATALOG / "datamodels")
    bram = Principal.person("bram")
    made = state.records.create(bram, "locker.code", {"name": "Bike", "pin": "1234"})
    assert state.records.list(bram, "locker.code")[0].fields["pin"] is None
    assert state.records.get(bram, "locker.code", made.id).fields["pin"] == "1234"


# -- never an assistant ------------------------------------------------------------------
def test_no_assistant_tool_reaches_a_secret(api):
    client = api.client
    put(api, "OPENAI_API_KEY", "sk-very-secret")
    secret_id = api("GET", "/api/records/secret")[0]["id"]
    token = connect(client)["access_token"]
    models = call(client, token, "list_datamodels")["structuredContent"]["datamodels"]
    assert "secret" not in {m["id"] for m in models}
    attempts = {
        "list_records": {},
        "get_record": {"id": secret_id},
        "create_record": {"fields": {"key": "STOLEN", "value": "x"}},
        "update_record": {"id": secret_id, "fields": {"value": "x"}},
        "move_record": {"id": secret_id, "fields": {"vault": "elsewhere"}},
        "delete_record": {"id": secret_id},
    }
    for tool, arguments in attempts.items():
        answer = call(client, token, tool, model="secret", **arguments)
        assert answer["isError"] is True, tool
        text = answer["content"][0]["text"]
        assert "never reach secret" in text, (tool, text)
        assert "sk-very-secret" not in text
    # Nothing an assistant tried touched the store.
    assert api("GET", "/api/secrets/item/OPENAI_API_KEY")["value"] == "sk-very-secret"
    assert [s["key"] for s in api("GET", "/api/secrets")] == ["OPENAI_API_KEY"]
    # And the name is not offered where the datamodels are listed for it.
    missing = call(client, token, "list_records", model="spaceship")
    assert "secret" not in missing["content"][0]["text"]


def test_the_gate_refuses_an_assistant_before_the_backend_is_asked(api):
    store = api.client.app.state.cloudmorrow.records
    with pytest.raises(Refused):
        store.list(Principal.assistant("bram"), "secret")


# -- the standard quills and the boot -----------------------------------------------------
def test_secrets_is_a_standard_catalog_quill_now(config):
    options, _, _ = choices(config)
    by_id = {c.id: c for c in options}
    assert by_id["secrets"].kind == "quill"


def test_a_server_from_before_the_quill_gets_it_at_boot_once(config, users):
    registry = QuillRegistry(config.quills_dir, config.datamodels_dir, config.quill_catalog)
    # Chosen at install, from before the Quill: Tasks installed, Secrets built in.
    from cloudmorrow.server.quilljobs import SEEDED, write_meta

    write_meta(config.db_path, SEEDED, "tasks")
    registry.install_from_catalog("tasks")
    store = RecordStore(config.db_path, registry.models, registry.expiries)
    boot(config.db_path, registry, store)
    assert "secrets" in registry.quills
    assert read_meta(config.db_path, SECRETS_QUILL) == "installed"
    # Removed by an administrator afterwards, it stays removed.
    registry.uninstall("secrets")
    boot(config.db_path, registry, store)
    assert "secrets" not in registry.quills


def test_a_server_that_had_secrets_off_keeps_it_off(client, config):
    state = client.app.state.cloudmorrow
    # Switched off while it was built in: the row is under the same key.
    from cloudmorrow.server.db import connect as db_connect

    with db_connect(config.db_path) as conn:
        conn.execute(
            "INSERT INTO features (key, enabled, changed_by, updated_at) VALUES ('secrets', 0, 'bram', 'x')"
        )
    conn.close()
    boot(config.db_path, state.quills, state.records)
    assert "secrets" in state.quills.quills
    assert state.features.enabled("secrets") is False
    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    assert client.get("/api/secrets", headers=auth).status_code == 403


def test_an_installer_that_left_secrets_out_is_not_overruled_at_boot(config, users):
    registry = QuillRegistry(config.quills_dir, config.datamodels_dir, config.quill_catalog)
    choose(config, {"tasks"}, registry=registry)
    store = RecordStore(config.db_path, registry.models, registry.expiries)
    boot(config.db_path, registry, store)
    assert "secrets" not in registry.quills


# -- cm secrets, through the kit ---------------------------------------------------------
def test_cm_secrets_is_the_quill_and_cm_secret_is_as_it_was():
    from cloudmorrow.cli.main import _command_names
    from cloudmorrow.cli.quillrun import route

    names = _command_names()
    assert "secret" in names
    assert route(["secrets", "list"], names) == ["run-quill", "secrets", "list"]


async def test_cm_secrets_lists_by_vault_and_shows_a_value_only_when_asked(api, monkeypatch):
    from rich.console import Console

    from cloudmorrow.cli import quillrun
    from tests.test_agent_setup import api_for

    put(api, "API_KEY", "sk-hidden", "production", "work")
    put(api, "WIFI", "hunter2", "local", "home")
    printed = Console(record=True, width=120)
    monkeypatch.setattr(quillrun, "out", printed)
    monkeypatch.setattr(quillrun, "console", printed)
    client = api_for(api.client, api.headers["Authorization"].split()[1])
    try:
        screen = quillrun._screen(await client.quills(), "secrets", "")
        await quillrun._act(client, screen, "list", [], "", None, False)
        listing = printed.export_text()
        assert "API_KEY" in listing and "WIFI" in listing and "work" in listing
        assert "sk-hidden" not in listing and quillrun.MASK in listing

        await quillrun._act(client, screen, "list", [], "work/production", None, False)
        picked = printed.export_text()
        assert "API_KEY" in picked and "WIFI" not in picked

        await quillrun._act(client, screen, "show", ["API_KEY"], "", None, False)
        assert "sk-hidden" not in printed.export_text()
        await quillrun._act(client, screen, "show", ["API_KEY"], "", None, False, reveal=True)
        assert "sk-hidden" in printed.export_text()

        await quillrun._act(client, screen, "add", ["TOKEN", "value=t0k"], "home/local", None, False)
        assert api("GET", "/api/secrets/item/TOKEN?vault=home")["value"] == "t0k"
    finally:
        await client.aclose()


def test_a_search_finds_a_secret_by_its_key_and_never_by_its_value(api):
    put(api, "API_KEY", "findme-in-the-value")
    assert [r["fields"]["key"] for r in api("GET", "/api/records/secret?q=api")] == ["API_KEY"]
    assert api("GET", "/api/records/secret?q=findme") == []
