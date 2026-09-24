"""Pictures in notes: kept in img/, hidden from the list, served back as they are."""

from __future__ import annotations

import os

import pytest

from cloudmorrow.server.notes import InvalidImageError, NoteStore, sniff_image
from cloudmorrow.server.sealed import FILE_MAGIC, Sealer

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
GIF = b"GIF89a" + b"\x00" * 40
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 40


def test_the_type_comes_from_the_bytes():
    assert sniff_image(PNG) == "image/png"
    assert sniff_image(JPEG) == "image/jpeg"
    assert sniff_image(GIF) == "image/gif"
    assert sniff_image(WEBP) == "image/webp"
    assert sniff_image(b"<svg/>") is None


# -- the store --------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path) -> NoteStore:
    return NoteStore(tmp_path / "notes", Sealer(os.urandom(32)))


def test_a_picture_is_kept_under_a_name_that_says_when_it_came(store):
    info = store.save_image(PNG, filename="Holiday Photo.PNG")
    assert info.path == f"img/{info.name}"
    assert info.name.endswith("-holiday-photo.png")
    assert info.content_type == "image/png"
    # On disk it is ciphertext; through the store it is the picture.
    stored = (store.root / "img" / info.name).read_bytes()
    assert stored != PNG and stored.startswith(FILE_MAGIC)
    assert store.image(info.name) == (PNG, "image/png")


def test_a_pasted_picture_has_no_name_and_that_is_fine(store):
    info = store.save_image(JPEG)
    stamp, token = info.name.split("-")[:2]
    assert len(stamp) == 8 and len(token) == 6
    assert info.name.endswith(".jpg")


def test_the_extension_follows_the_bytes_not_the_claim(store):
    assert store.save_image(PNG, filename="lies.jpg").name.endswith(".png")


def test_what_is_not_a_picture_is_refused(store):
    with pytest.raises(InvalidImageError):
        store.save_image(b"")
    with pytest.raises(InvalidImageError):
        store.save_image(b"<svg xmlns='http://www.w3.org/2000/svg'/>", filename="x.svg")


def test_the_img_folder_never_shows_in_the_tree(store):
    store.save_image(PNG)
    store.create_note("plan", "# plan\n")
    assert [child.name for child in store.tree().children] == ["plan.md"]
    # A folder someone made and called img elsewhere is an ordinary folder.
    store.create_dir("work/img")
    names = {child.name: child for child in store.tree().children}
    assert [c.name for c in names["work"].children] == ["img"]


def test_a_picture_is_read_back_by_name_only(store):
    info = store.save_image(GIF)
    data, content_type = store.image(info.name)
    assert data == GIF and content_type == "image/gif"
    from cloudmorrow.paths import UnsafePathError
    from cloudmorrow.server.notes import NoteNotFoundError

    with pytest.raises(NoteNotFoundError):
        store.image("20260101-000000-abcdef.png")
    for bad in ("../plan.md", "sub/x.png", ".hidden.png", ""):
        with pytest.raises(UnsafePathError):
            store.image(bad)


# -- the API ---------------------------------------------------------------------


def test_upload_and_fetch(client, auth):
    posted = client.post(
        "/api/notes/img", content=PNG, params={"filename": "rack.png"}, headers=auth
    )
    assert posted.status_code == 201, posted.text
    info = posted.json()
    assert info["path"] == f"img/{info['name']}" and info["content_type"] == "image/png"
    got = client.get(f"/api/notes/img/{info['name']}", headers=auth)
    assert got.status_code == 200
    assert got.content == PNG
    assert got.headers["content-type"] == "image/png"
    assert "immutable" in got.headers["cache-control"]
    # And the tree does not list it.
    assert client.get("/api/notes/tree", headers=auth).json()["children"] == []


def test_uploads_are_per_account(client, auth):
    from tests.conftest import GUEST, token_for

    name = client.post("/api/notes/img", content=PNG, headers=auth).json()["name"]
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    assert client.get(f"/api/notes/img/{name}", headers=guest).status_code == 404


def test_a_non_image_upload_is_a_400(client, auth):
    refused = client.post("/api/notes/img", content=b"hello", headers=auth)
    assert refused.status_code == 400
    # A name with a slash in it is another URL entirely, never a file.
    assert client.get("/api/notes/img/..%2Fplan.md", headers=auth).status_code in (400, 404, 405)


def test_an_upload_needs_a_sign_in(client):
    assert client.post("/api/notes/img", content=PNG).status_code == 401
