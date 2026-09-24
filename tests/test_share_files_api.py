"""Browsing a server share from the web app: a folder's listing, and a file."""

from __future__ import annotations

import os
import stat

import pytest

from tests.conftest import GUEST, token_for


@pytest.fixture()
def share(client, auth, config):
    """A server share with a folder, a picture, a text file and a dotfile in it."""
    created = client.post("/api/shares", json={"name": "media"}, headers=auth)
    assert created.status_code == 201, created.text
    root = config.notes_dir / "Shares" / "media"
    (root / "Holiday").mkdir()
    (root / "Holiday" / "beach.jpg").write_bytes(b"\xff\xd8\xff" + b"x" * 100)
    (root / "readme.txt").write_text("hello")
    (root / ".hidden").write_text("no")
    return root


def listing(client, auth, path=""):
    response = client.get(f"/api/shares/media/ls?path={path}", headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def status_of(client, auth, what, path):
    """The status of asking for *path* as a folder ("ls") or a file ("file")."""
    return client.get(f"/api/shares/media/{what}?path={path}", headers=auth).status_code


def test_the_top_of_a_share_lists_folders_and_files_but_nothing_hidden(client, auth, share):
    body = listing(client, auth)
    assert body["share"] == "media" and body["path"] == ""
    entries = {entry["name"]: entry for entry in body["entries"]}
    assert set(entries) == {"Holiday", "readme.txt"}
    assert entries["Holiday"]["is_dir"] is True and entries["Holiday"]["size"] == 0
    assert entries["readme.txt"]["is_dir"] is False
    assert entries["readme.txt"]["size"] == 5
    assert entries["readme.txt"]["mime"] == "text/plain"
    assert entries["readme.txt"]["modified"] > 0


def test_a_folder_inside_the_share_is_listed_by_its_path(client, auth, share):
    body = listing(client, auth, "Holiday")
    assert body["path"] == "Holiday"
    assert [(e["name"], e["mime"]) for e in body["entries"]] == [("beach.jpg", "image/jpeg")]


def test_a_file_comes_back_as_itself(client, auth, share):
    response = client.get("/api/shares/media/file?path=Holiday/beach.jpg", headers=auth)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == (share / "Holiday" / "beach.jpg").read_bytes()
    # Someone's files: not for a shared cache.
    assert "private" in response.headers["cache-control"]


def test_what_is_not_there_is_a_404(client, auth, share):
    assert client.get("/api/shares/media/ls?path=Nowhere", headers=auth).status_code == 404
    assert client.get("/api/shares/media/file?path=nope.txt", headers=auth).status_code == 404
    # A folder is not a file, and a file is not a folder.
    assert client.get("/api/shares/media/file?path=Holiday", headers=auth).status_code == 404
    assert client.get("/api/shares/media/ls?path=readme.txt", headers=auth).status_code == 404
    assert client.get("/api/shares/nosuch/ls", headers=auth).status_code == 404


def test_nothing_escapes_the_share(client, auth, share, config):
    (config.notes_dir / "secret.txt").write_text("x")
    for path in ("../secret.txt", "..", "Holiday/../../secret.txt"):
        assert status_of(client, auth, "ls", path) == 400, path
        assert status_of(client, auth, "file", path) == 400, path
    # An absolute path is read as one inside the share, and there is no such thing.
    assert status_of(client, auth, "file", "/etc/passwd") == 404


def test_a_symlink_is_not_followed(client, auth, share, config):
    outside = config.notes_dir / "outside"
    outside.mkdir()
    (outside / "leak.txt").write_text("x")
    os.symlink(outside, share / "link")
    os.symlink(outside / "leak.txt", share / "leak.txt")
    names = [e["name"] for e in listing(client, auth)["entries"]]
    assert "link" not in names and "leak.txt" not in names
    assert status_of(client, auth, "file", "leak.txt") in (400, 404)
    assert status_of(client, auth, "ls", "link") in (400, 404)


def test_another_accounts_share_does_not_exist(client, auth, share):
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    assert client.get("/api/shares/media/ls", headers=guest).status_code == 404
    assert client.get("/api/shares/media/file?path=readme.txt", headers=guest).status_code == 404


def test_a_machine_share_cannot_be_browsed_from_the_server(client):
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    enrolled = client.post("/api/agents/enroll-self", json={"name": "laptop"}, headers=guest)
    assert enrolled.status_code == 200, enrolled.text
    created = client.post(
        "/api/shares",
        json={"name": "music", "kind": "machine", "machine": "laptop", "path": "/home/guest/Music"},
        headers=guest,
    )
    assert created.status_code == 201, created.text
    refused = client.get("/api/shares/music/ls", headers=guest)
    assert refused.status_code == 409
    assert "mount it" in refused.json()["detail"]


# -- putting a file in ----------------------------------------------------------------


def upload(client, auth, path, filename, body=b"data", content_type="application/octet-stream"):
    return client.post(
        f"/api/shares/media/upload?path={path}&filename={filename}",
        content=body,
        headers={**auth, "Content-Type": content_type},
    )


def test_a_file_is_put_in_the_folder_named(client, auth, share):
    response = upload(
        client, auth, "Holiday", "dune.jpg", b"\xff\xd8\xff" + b"y" * 50, "image/jpeg"
    )
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["name"] == "dune.jpg" and saved["size"] == 53 and saved["mime"] == "image/jpeg"
    assert (share / "Holiday" / "dune.jpg").read_bytes() == b"\xff\xd8\xff" + b"y" * 50
    # And it is in the listing now.
    names = [e["name"] for e in listing(client, auth, "Holiday")["entries"]]
    assert names == ["beach.jpg", "dune.jpg"]


def test_a_name_already_taken_gets_a_number_and_nothing_is_overwritten(client, auth, share):
    before = (share / "readme.txt").read_bytes()
    assert upload(client, auth, "", "readme.txt", b"new").json()["name"] == "readme 2.txt"
    assert upload(client, auth, "", "readme.txt", b"newer").json()["name"] == "readme 3.txt"
    assert (share / "readme.txt").read_bytes() == before
    assert (share / "readme 2.txt").read_bytes() == b"new"


def test_a_bad_name_or_a_missing_folder_is_refused(client, auth, share):
    for bad in ("", " ", ".", "..", ".hidden", "a/b", "a\\b", "x" * 300):
        assert upload(client, auth, "", bad).status_code == 400, repr(bad)
    assert upload(client, auth, "Nowhere", "x.txt").status_code == 404
    assert upload(client, auth, "../", "x.txt").status_code == 400
    # Nothing was left behind by any of them.
    assert not list(share.glob(".upload-*"))


def test_a_guest_cannot_put_a_file_in_someone_elses_share(client, auth, share):
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    assert upload(client, guest, "", "x.txt").status_code == 404
    assert not (share / "x.txt").exists()


def test_a_file_put_in_is_as_readable_as_one_made_through_the_mount(client, auth, share):
    from cloudmorrow.server.routes.sharefiles import FILE_MODE

    assert upload(client, auth, "", "plain.txt").status_code == 201
    assert stat.S_IMODE((share / "plain.txt").stat().st_mode) == FILE_MODE


# -- thumbnails: a picture made small for the browser's grid -------------------
@pytest.fixture()
def picture(share):
    """A real picture in the share, wide, so a small copy has a shape to keep."""
    from PIL import Image

    target = share / "Holiday" / "sunset.jpg"
    Image.new("RGB", (800, 600), (240, 120, 40)).save(target, "JPEG")
    return target


def thumb(client, auth, path, **params):
    query = "&".join(f"{key}={value}" for key, value in params.items())
    return client.get(f"/api/shares/media/thumb?path={path}&{query}", headers=auth)


def size_of(response):
    from io import BytesIO

    from PIL import Image

    with Image.open(BytesIO(response.content)) as image:
        return image.format, image.size


def test_a_thumbnail_is_the_picture_with_its_long_edge_at_the_size_asked(client, auth, picture):
    response = thumb(client, auth, "Holiday/sunset.jpg")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/jpeg"
    assert "private" in response.headers["cache-control"]
    assert size_of(response) == ("JPEG", (256, 192))


def test_the_size_snaps_up_to_one_of_a_few_and_never_beyond_the_picture(client, auth, picture):
    # 300 is not on offer; the next one up is.
    assert size_of(thumb(client, auth, "Holiday/sunset.jpg", size=300)) == ("JPEG", (512, 384))
    # A picture smaller than the size asked stays its own size: nothing is blown up.
    assert size_of(thumb(client, auth, "Holiday/sunset.jpg", size=1024)) == ("JPEG", (800, 600))
    # And an absurd size is the largest on offer, not a fresh cache entry per number.
    assert size_of(thumb(client, auth, "Holiday/sunset.jpg", size=99999)) == ("JPEG", (800, 600))


def test_a_thumbnail_is_made_once_and_kept_under_the_data_dir(client, auth, picture, config):
    thumb(client, auth, "Holiday/sunset.jpg")
    kept = list((config.data_dir / "thumbs").rglob("*.jpg"))
    assert len(kept) == 1
    kept[0].write_bytes(b"")  # if it is made again this comes back non-empty
    response = thumb(client, auth, "Holiday/sunset.jpg")
    assert response.status_code == 200 and response.content == b""


def test_a_picture_put_back_under_the_same_name_gets_a_fresh_thumbnail(client, auth, picture):
    from PIL import Image

    assert size_of(thumb(client, auth, "Holiday/sunset.jpg")) == ("JPEG", (256, 192))
    Image.new("RGB", (600, 800), (40, 120, 240)).save(picture, "JPEG")
    later = picture.stat().st_mtime + 5
    os.utime(picture, (later, later))
    assert size_of(thumb(client, auth, "Holiday/sunset.jpg")) == ("JPEG", (192, 256))


def test_a_photo_is_turned_the_way_the_camera_says(client, auth, share):
    from PIL import Image

    exif = Image.Exif()
    exif[0x0112] = 6  # rotated 90°: the camera was held upright
    Image.new("RGB", (800, 600)).save(share / "Holiday" / "held.jpg", "JPEG", exif=exif.tobytes())
    assert size_of(thumb(client, auth, "Holiday/held.jpg")) == ("JPEG", (192, 256))


def test_a_picture_with_holes_is_drawn_onto_a_ground(client, auth, share):
    from PIL import Image

    Image.new("RGBA", (400, 400), (255, 0, 0, 0)).save(share / "Holiday" / "clear.png", "PNG")
    response = thumb(client, auth, "Holiday/clear.png")
    assert response.status_code == 200
    assert size_of(response) == ("JPEG", (256, 256))


def test_what_is_not_a_picture_the_server_can_scale_is_a_415(client, auth, share):
    assert thumb(client, auth, "readme.txt").status_code == 415
    # Called a JPEG, but not one: the same answer, and the browser shows the icon.
    assert thumb(client, auth, "Holiday/beach.jpg").status_code == 415
    (share / "Holiday" / "shot.heic").write_bytes(b"x")
    assert thumb(client, auth, "Holiday/shot.heic").status_code == 415


def test_a_thumbnail_of_nothing_is_a_404_and_nothing_escapes(client, auth, share):
    assert thumb(client, auth, "Holiday/nope.jpg").status_code == 404
    assert thumb(client, auth, "Holiday").status_code == 404
    assert thumb(client, auth, "../secret.jpg").status_code == 400
    assert client.get("/api/shares/nosuch/thumb?path=x.jpg", headers=auth).status_code == 404
