"""My Files: the drive every account has on the server, served as `my-files`."""

from __future__ import annotations

import pytest

from cloudmorrow.server.shares import InvalidSlugError, validate_share_name
from tests.conftest import basic


def test_every_account_has_a_drive_and_it_is_not_an_admins_call(client, guest_auth, config):
    listed = client.get("/api/shares", headers=guest_auth).json()
    assert [s["name"] for s in listed] == ["my-files"]
    drive = listed[0]
    assert drive["kind"] == "drive"
    assert drive["online"] is True and drive["managed"] is True
    assert drive["path"] == str(config.notes_dir / "guest" / "files")
    assert drive["url"].endswith("/dav/my-files/")
    # Made the moment it is asked about, so a fresh account has one to open.
    assert (config.notes_dir / "guest" / "files").is_dir()
    assert client.get("/api/shares/my-files", headers=guest_auth).json()["name"] == "my-files"


def test_the_drive_is_browsed_and_written_like_a_share(client, guest_auth, config):
    root = config.notes_dir / "guest" / "files"
    root.mkdir(parents=True, exist_ok=True)
    (root / "Tax").mkdir()
    (root / "cv.txt").write_text("me")
    body = client.get("/api/shares/my-files/ls", headers=guest_auth).json()
    assert body["share"] == "my-files"
    found = sorted((e["name"], e["is_dir"]) for e in body["entries"])
    # Notes is a folder in the drive like any other: the person's notes are there.
    assert found == [("Notes", True), ("Tax", True), ("cv.txt", False)]
    put = client.post(
        "/api/shares/my-files/upload?path=Tax&filename=2025.pdf",
        content=b"%PDF",
        headers=guest_auth,
    )
    assert put.status_code == 201, put.text
    assert (root / "Tax" / "2025.pdf").read_bytes() == b"%PDF"
    got = client.get("/api/shares/my-files/file?path=cv.txt", headers=guest_auth)
    assert got.status_code == 200 and got.content == b"me"


def test_each_account_sees_only_its_own_drive(client, auth, guest_auth, config):
    (config.notes_dir / "bram" / "files").mkdir(parents=True, exist_ok=True)
    (config.notes_dir / "bram" / "files" / "secret.txt").write_text("x")
    guest = client.get("/api/shares/my-files/ls", headers=guest_auth).json()
    assert [e["name"] for e in guest["entries"] if e["name"] != "Notes"] == []
    admin = client.get("/api/shares/my-files/ls", headers=auth).json()
    assert [e["name"] for e in admin["entries"] if e["name"] != "Notes"] == ["secret.txt"]


def test_the_drive_is_mounted_over_dav_under_its_name(client, guest_auth, config):
    token = guest_auth["Authorization"].split()[1]
    put = client.put("/dav/my-files/hello.txt", content=b"hi", headers=basic("guest", token))
    assert put.status_code in (201, 204), put.text
    assert (config.notes_dir / "guest" / "files" / "hello.txt").read_bytes() == b"hi"
    listing = client.request("PROPFIND", "/dav/", headers={**basic("guest", token), "Depth": "1"})
    assert listing.status_code == 207
    assert "/dav/my-files/" in listing.text


def test_the_drive_cannot_be_removed_or_taken_as_a_share_name(client, auth, guest_auth):
    gone = client.delete("/api/shares/my-files", headers=guest_auth)
    assert gone.status_code == 403
    assert "drive" in gone.json()["detail"]
    taken = client.post("/api/shares", json={"name": "my-files"}, headers=auth)
    assert taken.status_code == 400
    with pytest.raises(InvalidSlugError):
        validate_share_name("My-Files")
