"""Files as a Quill: shares and the files in them, served as records by the core.

The files stay where they always were — each person's drive and the Shares
folder — and the `shares` backend serves them through the record API, with
their bytes and a small copy of each picture beside the record. These hold
that the Quill does everything the built-in Files did: list a share and a
folder, open a file, a thumbnail of a picture, put a file in, and — new —
make a folder, rename, move and delete; that a machine share still says
where it is and that it is offline; that an account sees only its own; and
that a server which had Files built in gets the Quill at boot.
"""

from __future__ import annotations

import io
import os

import pytest

from cloudmorrow.server.quilljobs import (
    FILES_QUILL,
    SEEDED,
    boot,
    install_files,
    read_meta,
    write_meta,
)
from cloudmorrow.server.quills import QuillError, QuillRegistry
from cloudmorrow.server.records import RecordStore
from tests.conftest import ADMIN, GUEST, QUILL_CATALOG, token_for


@pytest.fixture()
def files(client):
    """The client with the Files Quill installed from the local catalog."""
    client.app.state.cloudmorrow.quills.install_from_catalog("files")
    return client


def headers(client, who=ADMIN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(client, *who)}"}


def call(client, method, path, body=None, *, expect=200, who=ADMIN, **kwargs):
    response = client.request(method, path, json=body, headers=headers(client, who), **kwargs)
    assert response.status_code == expect, response.text
    return (
        response.json()
        if response.content and "json" in response.headers.get("content-type", "")
        else response
    )


def drive(config, username="bram"):
    root = config.notes_dir / username / "files"
    root.mkdir(parents=True, exist_ok=True)
    return root


def png(size=(40, 20)) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, "PNG")
    return out.getvalue()


# -- the manifest ----------------------------------------------------------------
def test_the_quill_is_one_grid_over_shares_and_files(files):
    quills = call(files, "GET", "/api/quills")
    quill = next(q for q in quills if q["id"] == "files")
    [screen] = quill["screens"]
    assert (screen["kit"], screen["model"], screen["group"]) == ("grid", "file", "share")
    assert set(quill["models"]) == {"share", "file"}
    for model in quill["models"].values():
        assert model["backend"] == "shares"


def test_a_grid_must_bind_a_folder_field_and_a_kind_with_folders(registry_with_files, tmp_path):
    folder = tmp_path / "bad"
    folder.mkdir()
    (folder / "quill.toml").write_text(
        (QUILL_CATALOG / "quill-files" / "quill.toml")
        .read_text()
        .replace('folder = "folder"', 'folder = "size"')
    )
    with pytest.raises(QuillError, match="folder 'size' is a int; it wants string"):
        registry_with_files.plan(folder, QUILL_CATALOG / "datamodels")


@pytest.fixture()
def registry_with_files(tmp_path) -> QuillRegistry:
    return QuillRegistry(tmp_path / "quills", tmp_path / "datamodels", str(QUILL_CATALOG))


# -- shares ------------------------------------------------------------------------
def test_my_files_comes_first_then_the_shares(files, config):
    call(files, "POST", "/api/shares", {"name": "photos"}, expect=201)
    shares = call(files, "GET", "/api/records/share")
    assert [(s["id"], s["fields"]["label"], s["fields"]["kind"]) for s in shares] == [
        ("my-files", "My Files", "drive"),
        ("photos", "photos", "server"),
    ]
    assert shares[0]["fields"]["about"] == "Your own files on the server"
    assert all(s["fields"]["browsable"] and s["fields"]["online"] for s in shares)


def test_a_share_is_made_and_forgotten_as_a_record_by_the_same_rules(files, config):
    # A server share puts files on the server: an admin's call.
    call(files, "POST", "/api/records/share", {"fields": {"name": "media"}}, who=GUEST, expect=403)
    made = call(files, "POST", "/api/records/share", {"fields": {"label": "media"}}, expect=201)
    assert made["id"] == "media" and made["fields"]["kind"] == "server"
    assert [s["name"] for s in call(files, "GET", "/api/shares")] == ["my-files", "media"]
    # Forgotten; its folder stays.
    call(files, "DELETE", "/api/records/share/media", expect=204)
    assert [s["id"] for s in call(files, "GET", "/api/records/share")] == ["my-files"]
    assert (config.shares_root("bram") / "media").is_dir()
    # The drive is nobody's to remove.
    call(files, "DELETE", "/api/records/share/my-files", expect=403)


def test_a_machine_share_says_where_it_is_and_that_it_is_offline(files):
    auth = headers(files)
    files.post("/api/agents/enroll-self", json={"name": "laptop"}, headers=auth)
    call(
        files,
        "POST",
        "/api/shares",
        {"name": "music", "kind": "machine", "machine": "laptop", "path": "/home/bram/Music"},
        expect=201,
    )
    music = call(files, "GET", "/api/records/share/music")
    assert music["fields"]["kind"] == "machine"
    assert music["fields"]["online"] is False and music["fields"]["browsable"] is False
    assert music["fields"]["about"] == "On laptop, offline — mount it to browse it"
    # Its files are on the machine; the server has nothing to list.
    refused = call(files, "GET", "/api/records/file?share=music", expect=400)
    assert "on laptop, offline — mount it to browse it" in refused["detail"]


# -- files ---------------------------------------------------------------------------
def test_a_folder_is_listed_as_records_and_a_file_read_as_itself(files, config):
    root = drive(config)
    (root / "Photos").mkdir()
    (root / "cv.txt").write_text("me")
    (root / ".hidden").write_text("no")
    top = call(files, "GET", "/api/records/file?share=my-files")
    assert [(f["fields"]["name"], f["fields"]["kind"]) for f in top] == [
        ("cv.txt", "file"),
        ("Photos", "folder"),
    ]
    cv = next(f for f in top if f["fields"]["name"] == "cv.txt")
    assert cv["fields"]["size"] == 2 and cv["fields"]["mime"] == "text/plain"
    assert cv["fields"]["share"] == "my-files" and cv["fields"]["folder"] == ""
    got = call(files, "GET", f"/api/records/file/{cv['id']}/content")
    assert got.content == b"me" and got.headers["cache-control"] == "private, no-cache"
    assert call(files, "GET", "/api/records/file?share=my-files&folder=Photos") == []
    # The share is asked for; there is no listing of every file everywhere.
    assert "share=my-files" in call(files, "GET", "/api/records/file", expect=400)["detail"]


def test_a_picture_has_a_thumbnail_and_anything_else_says_so(files, config):
    root = drive(config)
    (root / "red.png").write_bytes(png((400, 200)))
    (root / "notes.txt").write_text("x")
    listed = {
        f["fields"]["name"]: f for f in call(files, "GET", "/api/records/file?share=my-files")
    }
    thumb = call(files, "GET", f"/api/records/file/{listed['red.png']['id']}/thumb?size=128")
    assert thumb.headers["content-type"] == "image/jpeg"
    from PIL import Image

    assert max(Image.open(io.BytesIO(thumb.content)).size) == 128
    call(files, "GET", f"/api/records/file/{listed['notes.txt']['id']}/thumb", expect=415)


def test_a_file_is_put_in_a_folder_and_a_taken_name_gets_a_number(files, config):
    root = drive(config)
    (root / "Photos").mkdir()
    auth = headers(files)
    made = files.post(
        "/api/records/file/upload?share=my-files&folder=Photos&name=cat.jpg",
        content=b"one",
        headers=auth,
    )
    assert made.status_code == 201, made.text
    assert made.json()["fields"]["path"] == "Photos/cat.jpg"
    again = files.post(
        "/api/records/file/upload?share=my-files&folder=Photos&name=cat.jpg",
        content=b"two",
        headers=auth,
    ).json()
    assert again["fields"]["name"] == "cat 2.jpg"
    assert (root / "Photos" / "cat.jpg").read_bytes() == b"one"
    assert (root / "Photos" / "cat 2.jpg").read_bytes() == b"two"
    # Readable as one put through the mount is, and nothing left half-way.
    from cloudmorrow.server.fileops import FILE_MODE

    assert (root / "Photos" / "cat.jpg").stat().st_mode & 0o777 == FILE_MODE
    assert not [p for p in root.rglob(".upload-*")]
    bad = files.post(
        "/api/records/file/upload?share=my-files&name=../escape", content=b"x", headers=auth
    )
    assert bad.status_code == 400


def test_folders_are_made_renamed_moved_and_deleted(files, config):
    root = drive(config)
    made = call(
        files,
        "POST",
        "/api/records/file",
        {"fields": {"share": "my-files", "name": "Tax", "kind": "folder"}},
        expect=201,
    )
    assert (root / "Tax").is_dir() and made["fields"]["kind"] == "folder"
    (root / "2025.pdf").write_bytes(b"%PDF")
    pdf = next(
        f
        for f in call(files, "GET", "/api/records/file?share=my-files")
        if f["fields"]["name"] == "2025.pdf"
    )
    # Moved into the folder by its folder, renamed by its name.
    moved = call(
        files,
        "PATCH",
        f"/api/records/file/{pdf['id']}",
        {"fields": {"folder": "Tax"}, "rev": pdf["rev"]},
    )
    assert moved["fields"]["path"] == "Tax/2025.pdf" and (root / "Tax" / "2025.pdf").is_file()
    renamed = call(
        files, "PATCH", f"/api/records/file/{moved['id']}", {"fields": {"name": "return.pdf"}}
    )
    assert (root / "Tax" / "return.pdf").read_bytes() == b"%PDF"
    # The old id is gone with the old name.
    call(files, "GET", f"/api/records/file/{pdf['id']}", expect=404)
    # A stale rev is a conflict, not a surprise.
    (root / "Tax" / "return.pdf").write_bytes(b"%PDF-2")
    os.utime(root / "Tax" / "return.pdf", ns=(1, 1))
    call(
        files,
        "PATCH",
        f"/api/records/file/{renamed['id']}",
        {"fields": {"name": "x.pdf"}, "rev": renamed["rev"]},
        expect=409,
    )
    # A folder cannot go inside itself, and a name cannot be taken twice.
    tax = call(files, "GET", f"/api/records/file/{made['id']}")
    call(
        files, "PATCH", f"/api/records/file/{tax['id']}", {"fields": {"folder": "Tax"}}, expect=400
    )
    (root / "Other").mkdir()
    call(
        files, "PATCH", f"/api/records/file/{tax['id']}", {"fields": {"name": "Other"}}, expect=400
    )
    # Deleting a folder takes what is in it.
    call(files, "DELETE", f"/api/records/file/{tax['id']}", expect=204)
    assert not (root / "Tax").exists()


def test_files_are_their_owners_alone(files, config):
    (drive(config) / "secret.txt").write_text("x")
    mine = call(files, "GET", "/api/records/file?share=my-files")
    assert [f["fields"]["name"] for f in mine] == ["secret.txt"]
    # The guest's my-files is their own drive, and the id of bram's file is nothing to them.
    assert call(files, "GET", "/api/records/file?share=my-files", who=GUEST) == []
    call(files, "GET", f"/api/records/file/{mine[0]['id']}", who=GUEST, expect=404)
    call(files, "GET", f"/api/records/file/{mine[0]['id']}/content", who=GUEST, expect=404)
    call(files, "POST", "/api/shares", {"name": "family"}, expect=201)
    call(files, "GET", "/api/records/file?share=family", who=GUEST, expect=400)


def test_an_assistant_reaches_files_with_the_generic_tools(files, config):
    from cloudmorrow.server.records import Principal

    (drive(config) / "todo.md").write_text("- [ ] one")
    store = files.app.state.cloudmorrow.records
    found = store.list(Principal.assistant("bram"), "file", {"share": "my-files"})
    assert [f.fields["name"] for f in found] == ["todo.md"]


def test_switched_off_the_files_close(files):
    call(files, "PATCH", "/api/server/features/files", {"enabled": False})
    call(files, "GET", "/api/records/file?share=my-files", expect=403)
    call(files, "GET", "/api/shares", expect=403)


# -- boot ---------------------------------------------------------------------------------
def test_a_server_that_had_files_built_in_gets_the_quill_once(config, users, registry_with_files):
    db = config.db_path
    # A server set up before Files was a Quill: its choice was made, Tasks is there.
    write_meta(db, SEEDED, "tasks")
    registry_with_files.install_from_catalog("tasks")
    store = RecordStore(db, registry_with_files.models, registry_with_files.expiries)
    boot(db, registry_with_files, store)
    assert "files" in registry_with_files.quills
    assert read_meta(db, FILES_QUILL) == "installed"
    # Once: taken away by an administrator, it stays away.
    registry_with_files.uninstall("files")
    assert install_files(db, registry_with_files) is False
    assert "files" not in registry_with_files.quills


def test_a_server_that_chose_without_files_is_left_without(config, users, registry_with_files):
    from cloudmorrow.server.standard import choose

    choose(config, {"tasks"}, registry=registry_with_files)
    assert install_files(config.db_path, registry_with_files) is False
    assert "files" not in registry_with_files.quills


def test_the_switch_a_server_had_on_files_still_holds(files):
    """The built-in feature's key was `files`, and so is the Quill's id."""
    state = files.app.state.cloudmorrow
    state.features.set("files", False, changed_by="bram")
    assert state.features.enabled("files") is False
    tabs = {row["key"]: row["enabled"] for row in call(files, "GET", "/api/server/features")}
    assert tabs["files"] is False
