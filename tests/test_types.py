"""The types catalogue: what kinds of data there are, and who reaches each."""

from __future__ import annotations

from cloudmorrow.server.features import FEATURES, USES
from cloudmorrow.server.types import BY_KEY, FIELD_KINDS, FOUNDATION, SCOPES, TYPES, catalogue
from tests.conftest import GUEST, token_for


def test_the_foundation_is_the_servers_own():
    foundation = {t.key for t in TYPES if t.provided_by == FOUNDATION}
    assert {"user", "secret", "file", "share", "machine", "notification"} <= foundation
    # Everything else is an app's, and that app exists.
    for t in TYPES:
        if t.provided_by != FOUNDATION:
            assert t.provided_by in USES, t.key


def test_every_app_declares_types_the_catalogue_knows():
    for feature in FEATURES:
        assert feature.uses, feature.key
        for key in feature.uses:
            assert key in BY_KEY, (feature.key, key)


def test_a_type_is_well_formed():
    for t in TYPES:
        assert set(t.scopes) <= SCOPES
        for f in t.fields:
            assert f.kind in FIELD_KINDS
            if f.kind == "ref":
                assert f.ref in BY_KEY
        assert set(t.sealed) <= {f.name for f in t.fields}


def test_secrets_are_never_the_assistants():
    assert BY_KEY["secret"].assistant is False
    assert BY_KEY["note"].assistant is True


def test_the_catalogue_says_who_uses_what():
    rows = {row["key"]: row for row in catalogue(USES)}
    # An app uses what it provides, whether or not it said so.
    assert rows["note"]["used_by"] == ["notes"]
    # A foundation type is used by whoever asked for it, and nobody by default.
    assert rows["user"]["used_by"] == ["calendar", "chat"]
    # Secrets is a Quill now: the installed Quills say so, on the features list.
    assert rows["secret"]["used_by"] == []
    assert rows["secret"]["foundation"] is True
    assert rows["note"]["foundation"] is False


def test_the_types_are_on_the_api(client, auth):
    assert client.get("/api/types").status_code == 401
    listed = client.get("/api/types", headers=auth).json()
    by_key = {row["key"]: row for row in listed}
    assert list(by_key)[:2] == ["user", "secret"]
    assert by_key["secret"]["sealed"] == ["value"]
    assert by_key["event"]["fields"][0] == {
        "name": "calendar",
        "kind": "ref",
        "description": "",
        "ref": "calendar",
    }
    # Boards and tasks are datamodels in the record store now, not here.
    assert "task" not in by_key
    # Anybody signed in may read it: it is what this server is.
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    assert client.get("/api/types", headers=guest).status_code == 200


def test_the_apps_say_which_types_they_use(tasks_quill, secrets_quill, auth):
    listed = {row["key"]: row for row in tasks_quill.get("/api/server/features", headers=auth).json()}
    assert listed["tasks"]["types"] == ["board", "task"]
    assert listed["secrets"]["types"] == ["secret"]
