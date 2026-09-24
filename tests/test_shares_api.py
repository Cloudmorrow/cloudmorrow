"""The shares API, and the WebDAV side that serves what it made."""

from __future__ import annotations

import base64
import re

import pytest

from tests.conftest import ADMIN, GUEST, token_for


def basic(username: str, secret: str) -> dict[str, str]:
    raw = base64.b64encode(f"{username}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


def hrefs(body: str) -> list[str]:
    return [h for h in re.findall(r"<[^>]*:href>([^<]*)</[^>]*:href>", body) if h.startswith("/")]


@pytest.fixture()
def guest_auth(client) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(client, *GUEST)}"}


@pytest.fixture()
def share(client, auth) -> dict:
    created = client.post("/api/shares", json={"name": "media"}, headers=auth)
    assert created.status_code == 201, created.text
    return created.json()


# -- the API -----------------------------------------------------------------


def test_a_share_is_created_and_listed_with_its_url(client, auth, config):
    created = client.post(
        "/api/shares", json={"name": "media", "description": "films"}, headers=auth
    ).json()
    assert created["managed"] is True
    assert created["path"] == str(config.notes_dir / "Shares" / "media")
    assert created["url"].endswith("/dav/media/")
    listed = client.get("/api/shares", headers=auth).json()
    # The caller's own drive first, then the shares.
    assert [(s["name"], s["description"]) for s in listed] == [
        ("my-files", "Your own files on the server"),
        ("media", "films"),
    ]


def test_the_url_is_built_on_public_url_when_there_is_one(client, auth, config):
    config.public_url = "https://cloudmorrow.example"
    created = client.post("/api/shares", json={"name": "media"}, headers=auth).json()
    assert created["url"] == "https://cloudmorrow.example/dav/media/"


def test_only_an_admin_makes_a_share_on_the_server(client, auth, guest_auth):
    refused = client.post("/api/shares", json={"name": "photos"}, headers=guest_auth)
    assert refused.status_code == 403
    allowed = client.post("/api/shares", json={"name": "photos"}, headers=auth)
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["managed"] is True


def test_a_folder_already_in_shares_becomes_the_share(client, auth, config):
    """rsync a library into Shares, then name it — whatever case the folder has."""
    folder = config.notes_dir / "Shares" / "Pictures"
    folder.mkdir(parents=True)
    (folder / "holiday.jpg").write_bytes(b"x")
    created = client.post("/api/shares", json={"name": "pictures"}, headers=auth)
    assert created.status_code == 201, created.text
    assert created.json()["path"] == str(folder)
    assert (folder / "holiday.jpg").exists()


def test_the_shares_directory_is_listed_for_the_dialog(client, auth, guest_auth, config):
    directory = config.notes_dir / "Shares"
    (directory / "Pictures").mkdir(parents=True)
    (directory / "Music").mkdir()
    listed = client.get("/api/shares/folders", headers=auth)
    assert listed.status_code == 200, listed.text
    assert listed.json() == {"directory": str(directory), "folders": ["Music", "Pictures"]}
    client.post("/api/shares", json={"name": "music"}, headers=auth)
    assert client.get("/api/shares/folders", headers=auth).json()["folders"] == ["Pictures"]
    # Not for a guest: they make no shares on the server.
    assert client.get("/api/shares/folders", headers=guest_auth).status_code == 403


def test_a_bad_name_or_a_path_is_a_400(client, auth, tmp_path):
    assert client.post("/api/shares", json={"name": "My Media"}, headers=auth).status_code == 400
    # A project id's reserved words are not a share's: "projects" is fine.
    assert client.post("/api/shares", json={"name": "projects"}, headers=auth).status_code == 201
    # A server share is named, not placed — even at a directory that is there.
    placed = client.post("/api/shares", json={"name": "media", "path": str(tmp_path)}, headers=auth)
    assert placed.status_code == 400
    assert "Shares directory" in placed.json()["detail"]


def test_a_name_is_taken_once(client, auth, share):
    assert client.post("/api/shares", json={"name": "media"}, headers=auth).status_code == 409


def test_shares_are_the_callers_own(client, auth, guest_auth, share):
    assert [s["name"] for s in client.get("/api/shares", headers=guest_auth).json()] == ["my-files"]
    assert client.get("/api/shares/media", headers=guest_auth).status_code == 404


def test_deleting_a_share_keeps_the_files_unless_asked(client, auth, share, config):
    root = config.notes_dir / "Shares" / "media"
    (root / "film.mkv").write_bytes(b"x")
    assert client.delete("/api/shares/media", headers=auth).status_code == 204
    assert (root / "film.mkv").exists()
    assert [s["name"] for s in client.get("/api/shares", headers=auth).json()] == ["my-files"]


def test_deleting_a_share_with_its_files(client, auth, share, config):
    root = config.notes_dir / "Shares" / "media"
    client.delete("/api/shares/media", params={"remove_files": True}, headers=auth)
    assert not root.exists()


# -- WebDAV ---------------------------------------------------------------------


def test_the_dav_root_lists_your_shares(client, auth, share):
    token = auth["Authorization"].split()[1]
    client.post("/api/shares", json={"name": "photos"}, headers=auth)
    response = client.request(
        "PROPFIND", "/dav/", headers={**basic("bram", token), "Depth": "1"}
    )
    assert response.status_code == 207, response.text
    assert hrefs(response.text) == ["/dav/", "/dav/my-files/", "/dav/media/", "/dav/photos/"]


def test_the_access_token_works_as_the_password(client, auth, share):
    token = auth["Authorization"].split()[1]
    put = client.put("/dav/media/hello.txt", content=b"hi there", headers=basic("bram", token))
    assert put.status_code == 201, put.text
    got = client.get("/dav/media/hello.txt", headers=basic("bram", token))
    assert got.content == b"hi there"


def test_the_account_password_works_too(client, auth, share):
    listing = client.request(
        "PROPFIND", "/dav/media/", headers={**basic(*ADMIN), "Depth": "1"}
    )
    assert listing.status_code == 207
    # And again: the second check is answered from the cache, not argon2.
    assert (
        client.request("PROPFIND", "/dav/media/", headers={**basic(*ADMIN), "Depth": "0"})
        .status_code
        == 207
    )


def test_wrong_credentials_are_a_401_with_a_basic_challenge(client, share):
    refused = client.request("PROPFIND", "/dav/media/", headers=basic("bram", "nope"))
    assert refused.status_code == 401
    anonymous = client.request("PROPFIND", "/dav/media/")
    assert anonymous.status_code == 401
    assert anonymous.headers["www-authenticate"].startswith("Basic")


def test_another_accounts_share_does_not_exist(client, share):
    response = client.request(
        "PROPFIND", "/dav/media/", headers={**basic(*GUEST), "Depth": "1"}
    )
    assert response.status_code == 404


def test_folders_are_made_moved_and_listed(client, auth, share, config):
    token = auth["Authorization"].split()[1]
    root = config.notes_dir / "Shares" / "media"
    made = client.request("MKCOL", "/dav/media/films", headers=basic("bram", token))
    assert made.status_code == 201
    assert (root / "films").is_dir()
    moved = client.request(
        "MOVE",
        "/dav/media/films/",
        headers={**basic("bram", token), "Destination": "http://testserver/dav/media/movies/"},
    )
    assert moved.status_code == 201, moved.text
    assert (root / "movies").is_dir() and not (root / "films").exists()
    listing = client.request(
        "PROPFIND", "/dav/media/", headers={**basic("bram", token), "Depth": "1"}
    )
    assert hrefs(listing.text) == ["/dav/media/", "/dav/media/movies/"]


def test_nothing_escapes_the_share(client, auth, share, config):
    token = auth["Authorization"].split()[1]
    (config.notes_dir / "bram" / "notes").mkdir(parents=True, exist_ok=True)
    (config.notes_dir / "bram" / "notes" / "secret.md").write_text("x")
    assert (
        client.get("/dav/media/../notes/secret.md", headers=basic("bram", token)).status_code
        == 404
    )
    encoded = client.get("/dav/media/%2e%2e/notes/secret.md", headers=basic("bram", token))
    assert encoded.status_code in (403, 404)


def test_the_share_itself_cannot_be_deleted_or_made_over_dav(client, auth, share, config):
    """Removing a share is an API call; DAV must not empty it on the way to a 403."""
    token = auth["Authorization"].split()[1]
    root = config.notes_dir / "Shares" / "media"
    (root / "film.mkv").write_bytes(b"x")
    assert client.request("DELETE", "/dav/media/", headers=basic("bram", token)).status_code == 403
    assert (root / "film.mkv").exists()
    assert client.request("MKCOL", "/dav/newshare", headers=basic("bram", token)).status_code == 403
    gone = client.request("DELETE", "/dav/media/film.mkv", headers=basic("bram", token))
    assert gone.status_code == 204
    assert not (root / "film.mkv").exists()


def test_locks_are_supported_so_finder_will_write(client, auth, share):
    token = auth["Authorization"].split()[1]
    client.put("/dav/media/doc.txt", content=b"x", headers=basic("bram", token))
    locked = client.request(
        "LOCK",
        "/dav/media/doc.txt",
        headers={**basic("bram", token), "Timeout": "Second-60"},
        content=(
            b'<?xml version="1.0"?><D:lockinfo xmlns:D="DAV:"><D:lockscope><D:exclusive/>'
            b"</D:lockscope><D:locktype><D:write/></D:locktype></D:lockinfo>"
        ),
    )
    assert locked.status_code == 200, locked.text
    assert "opaquelocktoken" in locked.headers.get("lock-token", "")


def test_dav_without_the_slash_redirects_to_it(client, auth):
    token = auth["Authorization"].split()[1]
    response = client.get("/dav", headers=basic("bram", token), follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/dav/"
