"""Notes as a Quill over files: a note is a Markdown file in the Notes folder.

Notes is an `editor` screen bound to the `file` datamodel, within the Notes
folder of the person's own drive, with `.md` saying which files are pages.
Nothing of its own: the core serves the files, their folders and the
pictures beside them, and every surface draws the kit's editor from the
record API. These hold that the Quill is declared so, that the welcome
note arrives as a file once, that folders and pictures are answered
within the root the screen names, and that a server from before the move
gets the Quill and keeps its switch.
"""

from __future__ import annotations

import pytest

from cloudmorrow.server.database import connect
from cloudmorrow.server.features import FEATURE_KEYS, Feature, FeatureStore
from cloudmorrow.server.quills import KIT_READY, QuillError, QuillRegistry
from cloudmorrow.server.quills.jobs import (
    SEEDED,
    adopt_builtins,
    adopted_key,
    boot,
    read_meta,
    write_meta,
)
from cloudmorrow.server.quills.standard import choices, choose
from cloudmorrow.server.records import RecordStore
from tests.conftest import GUEST, QUILL_CATALOG, token_for

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
IN_NOTES = "share=my-files&within=Notes"
PAGES = f"/api/records/file?{IN_NOTES}&suffix=.md"


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


def note(api, path, text="", expect=201):
    fields = {"share": "my-files", "path": f"Notes/{path}.md", "text": text}
    return api("POST", "/api/records/file", {"fields": fields}, expect=expect)


def paths(api, query=PAGES):
    return [f["fields"]["path"] for f in api("GET", query)]


# -- the Quill ---------------------------------------------------------------------
def test_notes_is_an_editor_over_the_markdown_files_in_the_notes_folder(api):
    quills = api("GET", "/api/quills")
    notes = next(q for q in quills if q["id"] == "notes")
    assert [(s["kit"], s["model"], s["body"], s["path"], s["where"], s["suffix"]) for s in notes["screens"]] == [
        ("editor", "file", "text", "path", {"share": "my-files", "within": "Notes"}, ".md")
    ]
    # Nothing of its own: the file datamodel (and the share it links to), which
    # does folders and pictures too.
    assert notes["models"].keys() == {"file", "share"}
    assert notes["models"]["file"]["can"] == ["search", "folders", "attachments", "content"]
    assert "editor" in KIT_READY


def test_notes_is_not_a_built_in_feature_but_keeps_its_switch(api):
    assert "notes" not in FEATURE_KEYS
    features = {row["key"]: row for row in api("GET", "/api/server/features")}
    assert features["notes"]["label"] == "Notes"
    api("PATCH", "/api/server/features/notes", {"enabled": False})
    # Off means off: with Notes the only Quill over files, the files close too.
    api("GET", PAGES, expect=403)
    api("PATCH", "/api/server/features/notes", {"enabled": True})
    api("GET", PAGES)


def test_an_editor_screen_needs_a_text_body_and_says_its_filters_plainly(tmp_path):
    registry = QuillRegistry(tmp_path / "q", tmp_path / "m", str(QUILL_CATALOG))
    folder = tmp_path / "jotter"
    folder.mkdir()
    head = '[quill]\nid = "jotter"\nname = "Jotter"\nversion = "0.1.0"\n[uses]\ndatamodels = ["file"]\n'
    screen = '[[screens]]\nid = "jot"\nkit = "editor"\nmodel = "file"\ntitle = "name"\n'
    (folder / "quill.toml").write_text(head + screen + 'body = "name"\n')
    with pytest.raises(QuillError, match="wants markdown or text"):
        registry.install(folder, QUILL_CATALOG / "datamodels")
    (folder / "quill.toml").write_text(head + screen + 'body = "text"\nwhere = "my-files"\n')
    with pytest.raises(QuillError, match="where is a table of filters"):
        registry.install(folder, QUILL_CATALOG / "datamodels")
    (folder / "quill.toml").write_text(head + screen + 'body = "text"\nsuffix = "md"\n')
    with pytest.raises(QuillError, match="suffix is a file suffix"):
        registry.install(folder, QUILL_CATALOG / "datamodels")


def test_the_quill_goes_first_whenever_it_was_installed(client, auth):
    state = client.app.state.cloudmorrow
    state.quills.install_from_catalog("tasks")
    state.quills.install_from_catalog("notes")
    # Where the catalog puts it, not when it came: Notes has always been
    # the first tab, and a server that had Tasks first keeps Notes first.
    assert [q["id"] for q in client.get("/api/quills", headers=auth).json()] == ["notes", "tasks"]


# -- the welcome note ---------------------------------------------------------------
def test_somebody_with_no_notes_gets_the_welcome_note_once(api, config):
    assert paths(api) == ["Notes/Welcome.md"]
    welcome = api("GET", PAGES)[0]
    page = api("GET", f"/api/records/file/{welcome['id']}")
    assert page["fields"]["text"].startswith("# Welcome")
    # A file, as every note is, where My Files and WebDAV find it.
    assert (config.notes_dir / "bram" / "files" / "Notes" / "Welcome.md").read_text().startswith("# Welcome")
    assert len(api("GET", PAGES)) == 1
    # Deleted, it does not come back: once is once.
    api("DELETE", f"/api/records/file/{welcome['id']}", expect=204)
    note(api, "mine", "hello")
    assert paths(api) == ["Notes/mine.md"]


def test_somebody_who_has_notes_gets_no_welcome(api, config):
    root = config.notes_dir / "bram" / "files" / "Notes"
    root.mkdir(parents=True, exist_ok=True)
    (root / "mine.md").write_text("hello")
    assert paths(api) == ["Notes/mine.md"]


def test_a_guest_gets_their_own_welcome_and_sees_nobody_elses(api):
    guest = {"Authorization": f"Bearer {token_for(api.client, *GUEST)}"}
    assert paths(api) == ["Notes/Welcome.md"]
    note(api, "private", "mine")
    assert paths(api) == ["Notes/private.md", "Notes/Welcome.md"]
    assert [f["fields"]["path"] for f in api("GET", PAGES, who=guest)] == ["Notes/Welcome.md"]


# -- folders, within the root -----------------------------------------------------------
def test_folders_are_made_listed_renamed_and_deleted_within_notes(api):
    assert api("POST", f"/api/records/file/_folders?{IN_NOTES}", {"path": "Notes/Projects"}, expect=201) == {
        "path": "Notes/Projects",
        "name": "Projects",
    }
    api("POST", f"/api/records/file/_folders?{IN_NOTES}", {"path": "Notes/Projects/Garden"}, expect=201)
    api("POST", f"/api/records/file/_folders?{IN_NOTES}", {"path": "Notes/Projects"}, expect=400)
    note(api, "Projects/Garden/beds", "raised")
    folders = api("GET", f"/api/records/file/_folders?{IN_NOTES}&suffix=.md")
    assert [(f["path"], f["count"]) for f in folders] == [("Notes/Projects", 0), ("Notes/Projects/Garden", 1)]
    # Renaming a folder takes what is in it along.
    api("PATCH", f"/api/records/file/_folders?{IN_NOTES}", {"path": "Notes/Projects", "to": "Notes/Plans"})
    assert paths(api, "/api/records/file?share=my-files&folder=Notes/Plans/Garden") == ["Notes/Plans/Garden/beds.md"]
    api(
        "PATCH",
        f"/api/records/file/_folders?{IN_NOTES}",
        {"path": "Notes/Plans", "to": "Notes/Plans/inside"},
        expect=400,
    )
    # Deleting one deletes everything in it.
    api("DELETE", f"/api/records/file/_folders?{IN_NOTES}&path=Notes/Plans", expect=204)
    assert api("GET", f"/api/records/file/_folders?{IN_NOTES}") == []
    assert paths(api) == ["Notes/Welcome.md"]


def test_folder_paths_are_kept_inside_the_share(api):
    api("POST", f"/api/records/file/_folders?{IN_NOTES}", {"path": "../out"}, expect=400)
    api("POST", f"/api/records/file/_folders?{IN_NOTES}", {"path": "Notes/.hidden"}, expect=400)
    api("DELETE", f"/api/records/file/_folders?{IN_NOTES}&path=Notes/nothing", expect=400)
    api("GET", "/api/records/file/_folders?share=my-files&within=Nowhere", expect=400)


def test_a_datamodel_without_folders_says_so(tasks_quill, auth):
    response = tasks_quill.get("/api/records/task/_folders", headers=auth)
    assert response.status_code == 400 and "no folders" in response.json()["detail"]


# -- pictures, as the backend's attachments within the root ----------------------------------
def test_a_picture_is_kept_beside_the_notes_and_read_back(api, config):
    response = api.client.post(
        f"/api/records/file/_attachments?{IN_NOTES}&filename=Holiday.png",
        content=PNG,
        headers={**api.headers, "Content-Type": "image/png"},
    )
    assert response.status_code == 201, response.text
    info = response.json()
    assert info["path"] == f"img/{info['name']}" and info["content_type"] == "image/png"
    assert (config.notes_dir / "bram" / "files" / "Notes" / "img" / info["name"]).read_bytes() == PNG
    back = api.client.get(f"/api/records/file/_attachments/{info['name']}?{IN_NOTES}", headers=api.headers)
    assert back.status_code == 200 and back.content == PNG
    assert back.headers["content-type"] == "image/png"
    # The pictures' folder is beside the pages, never among them.
    assert "Notes/img" not in [f["fields"]["path"] for f in api("GET", f"/api/records/file?{IN_NOTES}")]
    missing = api.client.get(f"/api/records/file/_attachments/nope.png?{IN_NOTES}", headers=api.headers)
    assert missing.status_code == 404


def test_what_is_not_a_picture_is_refused(api):
    response = api.client.post(f"/api/records/file/_attachments?{IN_NOTES}", content=b"hello", headers=api.headers)
    assert response.status_code == 400


def test_pictures_are_their_owners_alone(api):
    info = api.client.post(f"/api/records/file/_attachments?{IN_NOTES}", content=PNG, headers=api.headers).json()
    guest = {"Authorization": f"Bearer {token_for(api.client, *GUEST)}"}
    got = api.client.get(f"/api/records/file/_attachments/{info['name']}?{IN_NOTES}", headers=guest)
    assert got.status_code == 404


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
        conn.execute(
            "INSERT INTO features (key, enabled, changed_by, updated_at)"
            " VALUES ('notes', 0, 'bram', '2026-01-01T00:00:00+00:00')"
        )
    conn.close()
    registry = _registry(config)
    write_meta(db, SEEDED, "tasks")
    assert adopt_builtins(db, registry) == []
    assert "notes" not in registry.quills
    # And were it installed by hand later, the old switch still means off.
    registry.install_from_catalog("notes")
    features = FeatureStore(db, lambda: [Feature("notes", "Notes", "")])
    assert features.enabled("notes") is False


def test_the_notes_that_were_there_are_the_notes_the_quill_shows(config, users):
    from fastapi.testclient import TestClient

    from cloudmorrow.server.app import create_app
    from tests.conftest import ADMIN

    # Written long before there was a Quill: a file in the Notes folder.
    root = config.notes_dir / "bram" / "files" / "Notes" / "old"
    root.mkdir(parents=True)
    (root / "plan.md").write_text("# plan\n")
    client = TestClient(create_app(config))
    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    state = client.app.state.cloudmorrow
    write_meta(config.db_path, SEEDED, "-")
    adopt_builtins(config.db_path, state.quills)
    listed = client.get(PAGES, headers=auth).json()
    assert [n["fields"]["path"] for n in listed] == ["Notes/old/plan.md"]


def test_choosing_at_install_is_final(config, users):
    """A new server that leaves Notes out is not given it by the boot work."""
    offered, _, _ = choices(config)
    assert {c.id: c.kind for c in offered}["notes"] == "quill"
    choose(config, {"tasks"})
    registry = _registry(config)
    assert adopt_builtins(config.db_path, registry) == []
    assert "notes" not in registry.quills
