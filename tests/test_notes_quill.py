"""Notes as a Quill: the kit's `editor`, and what the record API grew for it.

Notes stay the sealed Markdown files they always were, and /api/notes stays
the foundation `cm note`, WebDAV and the assistant's notes tools reach. What
moved is the screens: the Notes Quill names an `editor` bound to the `note`
datamodel, and every surface draws it from the record API — with folders,
search, previews and pictures, which a backend may answer for any datamodel.
"""

from __future__ import annotations

import pytest

from cloudmorrow.server.db import connect
from cloudmorrow.server.features import FEATURE_KEYS, Feature, FeatureStore
from cloudmorrow.server.quilljobs import (
    SEEDED,
    adopt_builtins,
    adopted_key,
    boot,
    read_meta,
    write_meta,
)
from cloudmorrow.server.quills import KIT_READY, QuillError, QuillRegistry
from cloudmorrow.server.records import RecordStore
from cloudmorrow.server.standard import choices, choose
from tests.conftest import GUEST, QUILL_CATALOG, token_for

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


@pytest.fixture()
def api(notes_quill):
    client = notes_quill
    from tests.conftest import ADMIN

    headers = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}

    def call(method, path, body=None, *, expect=200, who=headers, **kwargs):
        response = client.request(method, path, json=body, headers=who, **kwargs)
        assert response.status_code == expect, response.text
        if not response.content:
            return None
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response.content

    call.client = client
    call.headers = headers
    return call


def note(api, path, body="", expect=201):
    return api("POST", "/api/records/note", {"fields": {"path": path, "body": body}}, expect=expect)


# -- the Quill ---------------------------------------------------------------------
def test_notes_is_a_quill_with_one_editor_screen(api):
    quills = api("GET", "/api/quills")
    notes = next(q for q in quills if q["id"] == "notes")
    assert [(s["kit"], s["model"], s["body"], s["path"]) for s in notes["screens"]] == [
        ("editor", "note", "body", "path")
    ]
    # What the record API does for notes besides the five calls.
    assert notes["models"]["note"]["can"] == ["search", "folders", "attachments"]
    assert "editor" in KIT_READY


def test_notes_are_no_longer_a_built_in_feature_but_keep_their_switch(api):
    assert "notes" not in FEATURE_KEYS
    features = {row["key"]: row for row in api("GET", "/api/server/features")}
    assert features["notes"]["label"] == "Notes"
    api("PATCH", "/api/server/features/notes", {"enabled": False})
    # Off means off everywhere: the records, and the old notes API with them.
    api("GET", "/api/records/note", expect=403)
    refused = api("GET", "/api/notes/tree", expect=403)
    assert refused["detail"] == "Notes is switched off on this server"
    api("PATCH", "/api/server/features/notes", {"enabled": True})
    api("GET", "/api/records/note")


def test_an_editor_screen_needs_a_markdown_body(tmp_path):
    registry = QuillRegistry(tmp_path / "q", tmp_path / "m", str(QUILL_CATALOG))
    folder = tmp_path / "jotter"
    folder.mkdir()
    (folder / "quill.toml").write_text(
        '[quill]\nid = "jotter"\nname = "Jotter"\nversion = "0.1.0"\n'
        '[uses]\ndatamodels = ["note"]\n'
        '[[screens]]\nid = "jot"\nkit = "editor"\nmodel = "note"\ntitle = "title"\nbody = "title"\n'
    )
    with pytest.raises(QuillError, match="wants markdown"):
        registry.install(folder, QUILL_CATALOG / "datamodels")


def test_the_quill_goes_first_whenever_it_was_installed(client, auth):
    state = client.app.state.cloudmorrow
    state.quills.install_from_catalog("tasks")
    state.quills.install_from_catalog("notes")
    # Where the catalog puts it, not when it came: Notes has always been
    # the first tab, and a server that had Tasks first keeps Notes first.
    assert [q["id"] for q in client.get("/api/quills", headers=auth).json()] == ["notes", "tasks"]


# -- the welcome note ---------------------------------------------------------------
def test_somebody_with_no_notes_gets_the_welcome_note_once(api):
    listed = api("GET", "/api/records/note")
    assert [n["fields"]["path"] for n in listed] == ["welcome"]
    welcome = api("GET", f"/api/records/note/{listed[0]['id']}")
    assert welcome["fields"]["body"].startswith("# Welcome to Cloudmorrow")
    # A file, as every note is.
    assert "live** markdown editor" in api("GET", "/api/notes/file/welcome.md")["content"]
    assert len(api("GET", "/api/records/note")) == 1


def test_somebody_who_has_notes_gets_no_welcome(api):
    api("POST", "/api/notes/file", {"path": "mine.md", "content": "hello"}, expect=201)
    assert [n["fields"]["path"] for n in api("GET", "/api/records/note")] == ["mine"]


# -- previews and search ---------------------------------------------------------------
def test_a_listing_can_carry_a_line_of_each_note(api):
    note(api, "ideas/garden", "# garden\n\nRaised beds by the fence.\n")
    note(api, "photo", "![fence](img/x.png)\n\nThe fence, before.\n")
    rows = {n["fields"]["path"]: n for n in api("GET", "/api/records/note?previews=true")}
    assert rows["ideas/garden"]["preview"] == "Raised beds by the fence."
    # A picture is not something a list says.
    assert rows["photo"]["preview"] == "The fence, before."
    # Not asked for, not sent: a list of titles stays light.
    assert "preview" not in api("GET", "/api/records/note")[0]


def test_q_searches_names_and_every_line(api):
    note(api, "ideas/garden", "Raised beds by the fence.\nTomatoes in June.\n")
    note(api, "log", "Nothing about plants.\n")
    found = api("GET", "/api/records/note?q=tomatoes")
    assert [(n["fields"]["path"], n["preview"]) for n in found] == [("ideas/garden", "Tomatoes in June.")]
    by_name = api("GET", "/api/records/note?q=garden")
    assert [n["fields"]["path"] for n in by_name] == ["ideas/garden"]
    assert api("GET", "/api/records/note?q=nowhere") == []
    # And it narrows with a filter like any other listing.
    assert api("GET", "/api/records/note?q=tomatoes&folder=elsewhere") == []


def test_q_searches_the_record_store_too(tasks_quill, auth):
    client = tasks_quill
    board = client.get("/api/records/board", headers=auth).json()[0]
    for title, body in (("Fix the NAS", "swap the disk"), ("Buy bulbs", "E27, warm")):
        client.post("/api/records/task", headers=auth,
                    json={"fields": {"board": board["id"], "title": title, "body": body}})
    found = client.get("/api/records/task?q=DISK", headers=auth).json()
    assert [(t["fields"]["title"], t["preview"]) for t in found] == [("Fix the NAS", "swap the disk")]
    previews = client.get("/api/records/task?previews=true", headers=auth).json()
    assert {t["fields"]["title"]: t["preview"] for t in previews}["Buy bulbs"] == "E27, warm"


# -- folders ---------------------------------------------------------------------------
def test_folders_are_made_listed_renamed_and_deleted(api):
    note(api, "welcome-away", "")  # so the welcome note stays out of it
    assert api("POST", "/api/records/note/_folders", {"path": "Projects"}, expect=201) == {
        "path": "Projects", "name": "Projects",
    }
    api("POST", "/api/records/note/_folders", {"path": "Projects/Garden"}, expect=201)
    api("POST", "/api/records/note/_folders", {"path": "Projects"}, expect=400)
    note(api, "Projects/Garden/beds", "raised")
    folders = api("GET", "/api/records/note/_folders")
    assert [(f["path"], f["count"]) for f in folders] == [("Projects", 0), ("Projects/Garden", 1)]
    # Renaming a folder takes what is in it along.
    api("PATCH", "/api/records/note/_folders", {"path": "Projects", "to": "Plans"})
    assert [n["fields"]["path"] for n in api("GET", "/api/records/note?folder=Plans/Garden")] == [
        "Plans/Garden/beds"
    ]
    api("PATCH", "/api/records/note/_folders", {"path": "Plans", "to": "Plans/inside"}, expect=400)
    # Deleting one deletes everything in it.
    api("DELETE", "/api/records/note/_folders?path=Plans", expect=204)
    assert api("GET", "/api/records/note/_folders") == []
    assert [n["fields"]["path"] for n in api("GET", "/api/records/note")] == ["welcome-away"]


def test_folder_paths_are_kept_inside_and_off_the_pictures(api):
    api("POST", "/api/records/note/_folders", {"path": "../out"}, expect=400)
    api("POST", "/api/records/note/_folders", {"path": "img"}, expect=400)
    api("DELETE", "/api/records/note/_folders?path=nothing", expect=400)


def test_a_datamodel_without_folders_says_so(tasks_quill, auth):
    response = tasks_quill.get("/api/records/task/_folders", headers=auth)
    assert response.status_code == 400 and "no folders" in response.json()["detail"]


def test_a_note_moves_by_its_title_and_folder_too(api):
    made = note(api, "draft", "words")
    renamed = api("PATCH", f"/api/records/note/{made['id']}", {"fields": {"title": "final"}})
    assert renamed["fields"]["path"] == "final"
    moved = api("PATCH", f"/api/records/note/{renamed['id']}", {"fields": {"folder": "done"}})
    assert moved["fields"]["path"] == "done/final" and moved["fields"]["body"] == "words"
    made = api("POST", "/api/records/note", {"fields": {"folder": "a", "title": "b"}}, expect=201)
    assert made["fields"]["path"] == "a/b"


# -- pictures, as the backend's attachments --------------------------------------------------
def test_a_picture_is_kept_beside_the_notes_and_read_back_both_ways(api):
    response = api.client.post(
        "/api/records/note/_attachments?filename=Holiday.png", content=PNG,
        headers={**api.headers, "Content-Type": "image/png"},
    )
    assert response.status_code == 201, response.text
    info = response.json()
    assert info["path"] == f"img/{info['name']}" and info["content_type"] == "image/png"
    back = api.client.get(f"/api/records/note/_attachments/{info['name']}", headers=api.headers)
    assert back.status_code == 200 and back.content == PNG
    assert back.headers["content-type"] == "image/png"
    # The same file the notes API has always served, so the terminal, WebDAV
    # and an older phone see it too.
    old = api.client.get(f"/api/notes/img/{info['name']}", headers=api.headers)
    assert old.content == PNG
    missing = api.client.get("/api/records/note/_attachments/nope.png", headers=api.headers)
    assert missing.status_code == 404


def test_what_is_not_a_picture_is_refused(api):
    response = api.client.post("/api/records/note/_attachments", content=b"hello",
                               headers=api.headers)
    assert response.status_code == 400


def test_pictures_are_their_owners_alone(api):
    info = api.client.post("/api/records/note/_attachments", content=PNG, headers=api.headers).json()
    guest = {"Authorization": f"Bearer {token_for(api.client, *GUEST)}"}
    assert api.client.get(f"/api/records/note/_attachments/{info['name']}", headers=guest).status_code == 404


# -- a server from before the move ---------------------------------------------------------
def _registry(config) -> QuillRegistry:
    return QuillRegistry(config.quills_dir, config.datamodels_dir, str(QUILL_CATALOG))


def test_a_server_that_had_notes_on_gets_the_quill_at_boot(config, users):
    db = config.db_path
    registry = _registry(config)
    registry.install_from_catalog("tasks")
    write_meta(db, SEEDED, "tasks")  # set up long ago, with Notes built in
    boot(db, registry, RecordStore(db, registry.models, registry.expiries))
    assert "notes" in registry.quills
    assert read_meta(db, adopted_key("notes")) == "installed"
    # Once: removed by an administrator afterwards, it stays removed.
    registry.uninstall("notes")
    assert adopt_builtins(db, registry) == []
    assert "notes" not in registry.quills


def test_a_server_that_had_notes_switched_off_is_left_without(config, users):
    db = config.db_path
    FeatureStore(db)
    with connect(db) as conn:  # a row from when it was built in
        conn.execute("INSERT INTO features (key, enabled, changed_by, updated_at)"
                     " VALUES ('notes', 0, 'bram', '2026-01-01T00:00:00+00:00')")
    conn.close()
    registry = _registry(config)
    write_meta(db, SEEDED, "tasks")
    assert adopt_builtins(db, registry) == []
    assert "notes" not in registry.quills
    # And were it installed by hand later, the old switch still means off.
    registry.install_from_catalog("notes")
    features = FeatureStore(db, lambda: [Feature("notes", "Notes", "")])
    assert features.enabled("notes") is False


def test_the_notes_that_were_there_are_the_notes_the_quill_shows(config, users, tmp_path):
    from fastapi.testclient import TestClient

    from cloudmorrow.server.app import create_app

    client = TestClient(create_app(config))
    from tests.conftest import ADMIN

    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    # Written the old way, before there was a Quill.
    client.post("/api/notes/file", headers=auth, json={"path": "old/plan.md", "content": "# plan\n"})
    state = client.app.state.cloudmorrow
    write_meta(config.db_path, SEEDED, "-")
    adopt_builtins(config.db_path, state.quills)
    listed = client.get("/api/records/note", headers=auth).json()
    assert [n["fields"]["path"] for n in listed] == ["old/plan"]


def test_choosing_at_install_is_final(config, users):
    """A new server that leaves Notes out is not given it by the boot work."""
    offered, _, _ = choices(config)
    assert {c.id: c.kind for c in offered}["notes"] == "quill"
    choose(config, {"tasks"})
    registry = _registry(config)
    assert adopt_builtins(config.db_path, registry) == []
    assert "notes" not in registry.quills
