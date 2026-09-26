"""Backends: notes served as records, while they stay files in the notes folder."""

from __future__ import annotations

import pytest

from tests.conftest import ADMIN, GUEST, QUILL_CATALOG, token_for

NOTES = """
[quill]
id = "notebook"
name = "Notebook"
version = "0.1.0"
[uses]
datamodels = ["note"]
[[screens]]
id = "notes"
kit = "list"
model = "note"
title = "title"
"""


@pytest.fixture()
def api(client, tmp_path):
    folder = tmp_path / "notebook"
    folder.mkdir()
    (folder / "quill.toml").write_text(NOTES)
    client.app.state.cloudmorrow.quills.install(folder, QUILL_CATALOG / "datamodels")
    headers = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}

    def call(method, path, body=None, *, expect=200, who=headers):
        response = client.request(method, path, json=body, headers=who)
        assert response.status_code == expect, response.text
        return response.json() if response.content else None

    call.client = client
    return call


def test_a_note_made_as_a_record_is_a_file_the_notes_api_reads(api):
    made = api("POST", "/api/records/note", {"fields": {"path": "ideas/garden", "body": "# Garden\n"}}, expect=201)
    assert made["fields"]["title"] == "garden" and made["fields"]["folder"] == "ideas"
    assert isinstance(made["rev"], str) and made["rev"]
    # The same note, through the API notes have always had.
    note = api("GET", "/api/notes/file/ideas/garden.md")
    assert note["content"] == "# Garden\n"
    listed = api("GET", "/api/records/note")
    assert [(n["fields"]["path"], n["fields"]["body"]) for n in listed] == [("ideas/garden", None)]
    assert [n["fields"]["title"] for n in api("GET", "/api/records/note?folder=ideas")] == ["garden"]


def test_a_note_is_edited_moved_and_deleted_as_a_record(api):
    made = api("POST", "/api/records/note", {"fields": {"path": "log", "body": "one\n"}}, expect=201)
    changed = api("PATCH", f"/api/records/note/{made['id']}", {"fields": {"body": "two\n"}, "rev": made["rev"]})
    assert changed["fields"]["body"] == "two\n"
    # The old rev is a conflict, not a loss.
    stale = api("PATCH", f"/api/records/note/{made['id']}", {"fields": {"body": "three\n"}, "rev": made["rev"]}, expect=409)
    assert stale["detail"]["current"]["fields"]["body"] == "two\n"
    moved = api("PATCH", f"/api/records/note/{changed['id']}", {"fields": {"path": "archive/log"}})
    assert moved["fields"]["folder"] == "archive"
    api("GET", f"/api/records/note/{made['id']}", expect=404)
    api("DELETE", f"/api/records/note/{moved['id']}", expect=204)
    assert api("GET", "/api/records/note") == []


def test_notes_are_their_owners_alone(api):
    made = api("POST", "/api/records/note", {"fields": {"path": "private", "body": "mine"}}, expect=201)
    guest = {"Authorization": f"Bearer {token_for(api.client, *GUEST)}"}
    api("GET", f"/api/records/note/{made['id']}", who=guest, expect=404)
    assert api("GET", "/api/records/note", who=guest) == []


def test_a_bad_id_or_path_is_refused_plainly(api):
    api("GET", "/api/records/note/n_%%%", expect=404)
    api("GET", "/api/records/note/r_notanote", expect=404)
    api("POST", "/api/records/note", {"fields": {"path": "../escape", "body": ""}}, expect=400)
