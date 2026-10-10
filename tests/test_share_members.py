"""Sharing a share: with people, circles and everybody, to write or to read.

And the rest of what goes with it: who decides, what a member sees of the
share, an administrator's share on a directory elsewhere on the server and
what is said about its permissions, and what happens to shares when an
account or a circle goes.
"""

from __future__ import annotations

import os
import re

import pytest

from tests.conftest import GUEST, basic, token_for

not_root = pytest.mark.skipif(os.geteuid() == 0, reason="root can read and write anywhere")


def hrefs(body: str) -> list[str]:
    return [h for h in re.findall(r"<[^>]*:href>([^<]*)</[^>]*:href>", body) if h.startswith("/")]


def names(client, headers) -> list[str]:
    return [s["name"] for s in client.get("/api/shares", headers=headers).json()]


def guest_dav(client) -> dict[str, str]:
    return basic("guest", token_for(client, *GUEST))


@pytest.fixture()
def elsewhere(tmp_path):
    """A directory on the server outside everything Cloudmorrow keeps."""
    place = tmp_path.parent / f"{tmp_path.name}-library"
    place.mkdir()
    (place / "song.mp3").write_bytes(b"x")
    return place


# -- with people ------------------------------------------------------------------


def test_a_share_is_seen_by_the_people_it_is_shared_with(client, auth, guest_auth):
    created = client.post(
        "/api/shares",
        json={"name": "family", "members": [{"kind": "user", "who": "guest"}]},
        headers=auth,
    )
    assert created.status_code == 201, created.text
    assert created.json()["members"] == [
        {"kind": "user", "who": "guest", "access": "write", "label": "guest", "added_by": "bram"}
    ]
    assert names(client, guest_auth) == ["my-files", "family"]
    theirs = client.get("/api/shares/family", headers=guest_auth).json()
    assert theirs["owner"] == "bram" and theirs["access"] == "write" and theirs["can_manage"] is False
    # Where it is on the server, and what is wrong with it, are its owner's.
    assert theirs["path"] == "" and theirs["warnings"] == []
    put = client.put("/dav/family/hello.txt", content=b"hi", headers=guest_dav(client))
    assert put.status_code == 201, put.text


def test_a_share_shared_to_read_cannot_be_changed_over_dav(client, auth, config):
    client.post(
        "/api/shares",
        json={"name": "library", "members": [{"kind": "user", "who": "guest", "access": "read"}]},
        headers=auth,
    )
    client.post("/api/shares", json={"name": "scratch", "members": [{"kind": "user", "who": "guest"}]}, headers=auth)
    root = config.notes_dir / "Shares" / "library"
    (root / "book.txt").write_text("words")
    guest = guest_dav(client)
    listing = client.request("PROPFIND", "/dav/", headers={**guest, "Depth": "1"})
    assert hrefs(listing.text) == ["/dav/", "/dav/my-files/", "/dav/library/", "/dav/scratch/"]
    assert client.get("/dav/library/book.txt", headers=guest).content == b"words"
    for method, path in (
        ("PUT", "/dav/library/new.txt"),
        ("DELETE", "/dav/library/book.txt"),
        ("MKCOL", "/dav/library/d"),
    ):
        refused = client.request(method, path, content=b"x" if method == "PUT" else None, headers=guest)
        assert refused.status_code == 403, (method, refused.text)
    assert (root / "book.txt").read_text() == "words"
    # Nor carried out of it into a share they may write, nor into it from one.
    moved = client.request(
        "MOVE", "/dav/library/book.txt", headers={**guest, "Destination": "http://testserver/dav/scratch/book.txt"}
    )
    assert moved.status_code == 403
    client.put("/dav/scratch/note.txt", content=b"n", headers=guest)
    copied = client.request(
        "COPY", "/dav/scratch/note.txt", headers={**guest, "Destination": "http://testserver/dav/library/note.txt"}
    )
    assert copied.status_code == 403
    assert not (root / "note.txt").exists()


def test_who_has_it_changes_and_a_person_may_leave(client, auth, guest_auth):
    client.post("/api/shares", json={"name": "family"}, headers=auth)
    assert names(client, guest_auth) == ["my-files"]
    added = client.put("/api/shares/family/members", json={"kind": "user", "who": "guest"}, headers=auth)
    assert added.status_code == 200, added.text
    assert names(client, guest_auth) == ["my-files", "family"]
    # The same person again changes what they may do; it does not add a line.
    read = client.put(
        "/api/shares/family/members", json={"kind": "user", "who": "guest", "access": "read"}, headers=auth
    )
    assert [(m["who"], m["access"]) for m in read.json()["members"]] == [("guest", "read")]
    # They leave it.
    assert client.delete("/api/shares/family/members/user/guest", headers=guest_auth).status_code == 204
    assert names(client, guest_auth) == ["my-files"]


def test_only_its_owner_decides_about_a_share(client, auth, guest_auth, tmp_path):
    client.post("/api/shares", json={"name": "family", "members": [{"kind": "user", "who": "guest"}]}, headers=auth)
    assert (
        client.put(
            "/api/shares/family/members", json={"kind": "user", "who": "guest", "access": "read"}, headers=guest_auth
        ).status_code
        == 403
    )
    assert client.patch("/api/shares/family", json={"description": "mine now"}, headers=guest_auth).status_code == 403
    assert client.delete("/api/shares/family", headers=guest_auth).status_code == 403
    # An administrator is no different: being one opens nobody's share.
    client.post("/api/shares", json={"name": "diary"}, headers=guest_auth)
    assert client.get("/api/shares/diary", headers=auth).status_code == 404
    assert client.delete("/api/shares/diary", headers=auth).status_code == 404
    assert (
        client.request(
            "PROPFIND", "/dav/diary/", headers={**basic("bram", auth["Authorization"].split()[1]), "Depth": "0"}
        ).status_code
        == 404
    )


def test_nobody_and_yourself_are_not_members(client, auth):
    client.post("/api/shares", json={"name": "family"}, headers=auth)
    nobody = client.put("/api/shares/family/members", json={"kind": "user", "who": "nobody"}, headers=auth)
    assert nobody.status_code == 400 and "nobody called nobody" in nobody.json()["detail"]
    myself = client.put("/api/shares/family/members", json={"kind": "user", "who": "bram"}, headers=auth)
    assert myself.status_code == 400
    bad = client.put(
        "/api/shares/family/members", json={"kind": "user", "who": "guest", "access": "admin"}, headers=auth
    )
    assert bad.status_code == 400
    # And a share is not made with a member that is not there: nothing is.
    refused = client.post(
        "/api/shares", json={"name": "other", "members": [{"kind": "circle", "who": "ghosts"}]}, headers=auth
    )
    assert refused.status_code == 400
    assert client.get("/api/shares/other", headers=auth).status_code == 404


# -- with circles and everybody -------------------------------------------------------


def test_a_share_shared_with_a_circle_follows_who_is_in_it(client, auth, guest_auth):
    circle = client.post("/api/circles", json={"name": "Kids", "rules": {"*": "write"}}, headers=auth)
    assert circle.status_code == 201, circle.text
    # Anybody may share with a circle — the guest's own share, with Kids.
    client.post(
        "/api/shares",
        json={"name": "games", "members": [{"kind": "circle", "who": "Kids", "access": "read"}]},
        headers=guest_auth,
    )
    made = client.get("/api/shares/games", headers=guest_auth).json()
    assert [(m["kind"], m["who"], m["label"]) for m in made["members"]] == [("circle", "kids", "Kids")]
    client.post("/api/shares", json={"name": "homework", "members": [{"kind": "circle", "who": "kids"}]}, headers=auth)
    assert names(client, guest_auth) == ["my-files", "games"]
    # The guest joins Kids, and has it.
    client.put("/api/circles/kids/members/guest", headers=auth)
    assert names(client, guest_auth) == ["my-files", "games", "homework"]
    # A circle cannot be left from a share; the circle is left instead.
    assert client.delete("/api/shares/homework/members/circle/kids", headers=guest_auth).status_code == 403
    client.delete("/api/circles/kids/members/guest", headers=auth)
    assert names(client, guest_auth) == ["my-files", "games"]


def test_a_circle_that_goes_takes_its_line_with_it(client, auth):
    client.post("/api/circles", json={"name": "Kids"}, headers=auth)
    client.post("/api/shares", json={"name": "homework", "members": [{"kind": "circle", "who": "kids"}]}, headers=auth)
    client.delete("/api/circles/kids", headers=auth)
    assert client.get("/api/shares/homework", headers=auth).json()["members"] == []
    # And a new circle of the same name does not inherit it.
    client.post("/api/circles", json={"name": "Kids", "members": ["guest"]}, headers=auth)
    assert client.get("/api/shares/homework", headers=auth).json()["members"] == []


def test_only_an_administrator_shares_with_everybody(client, auth, guest_auth):
    refused = client.post("/api/shares", json={"name": "mine", "members": [{"kind": "everyone"}]}, headers=guest_auth)
    assert refused.status_code == 403
    assert client.get("/api/shares/mine", headers=guest_auth).status_code == 404
    client.post("/api/shares", json={"name": "mine"}, headers=guest_auth)
    assert client.put("/api/shares/mine/members", json={"kind": "everyone"}, headers=guest_auth).status_code == 403
    made = client.post(
        "/api/shares", json={"name": "public", "members": [{"kind": "everyone", "access": "read"}]}, headers=auth
    )
    assert made.status_code == 201, made.text
    assert made.json()["members"][0]["label"] == "Everybody"
    theirs = client.get("/api/shares/public", headers=guest_auth).json()
    assert theirs["access"] == "read"
    # The most any line gives: everybody may read, the guest by name may write.
    client.put("/api/shares/public/members", json={"kind": "user", "who": "guest"}, headers=auth)
    assert client.get("/api/shares/public", headers=guest_auth).json()["access"] == "write"


def test_the_candidates_are_the_people_and_the_circles(client, auth, guest_auth):
    client.post("/api/circles", json={"name": "Kids"}, headers=auth)
    theirs = client.get("/api/shares/candidates", headers=guest_auth).json()
    assert [p["username"] for p in theirs["people"]] == ["bram"]
    assert "Kids" in [c["name"] for c in theirs["circles"]]
    assert theirs["everyone"] is False
    assert client.get("/api/shares/candidates", headers=auth).json()["everyone"] is True


# -- an administrator's share elsewhere on the server -----------------------------------


def test_an_administrator_shares_a_directory_elsewhere(client, auth, elsewhere):
    made = client.post("/api/shares", json={"name": "music", "path": str(elsewhere)}, headers=auth)
    assert made.status_code == 201, made.text
    share = made.json()
    assert share["path"] == str(elsewhere) and share["managed"] is False
    token = auth["Authorization"].split()[1]
    assert client.get("/dav/music/song.mp3", headers=basic("bram", token)).content == b"x"
    # Forgetting it never deletes a directory it did not make.
    client.delete("/api/shares/music", params={"remove_files": True}, headers=auth)
    assert (elsewhere / "song.mp3").exists()


def test_a_path_that_cannot_be_shared_is_refused(client, auth, config, tmp_path, elsewhere):
    def refused(path) -> str:
        response = client.post("/api/shares", json={"name": "nope", "path": str(path)}, headers=auth)
        assert response.status_code == 400, response.text
        return response.json()["detail"]

    assert "not there" in refused(elsewhere / "missing")
    assert "not a directory" in refused(elsewhere / "song.mp3")
    assert "absolute" in refused("relative/path")
    # Nothing that holds, or is inside, what the server keeps for itself.
    assert "database" in refused(config.data_dir)
    assert "never shared" in refused(tmp_path)
    assert "never shared" in refused("/")
    drive = config.notes_dir / "guest" / "files"
    drive.mkdir(parents=True)
    assert "everybody's own files" in refused(drive)
    # A symlink is followed to where it really is, and judged there.
    link = elsewhere / "sneaky"
    link.symlink_to(config.data_dir)
    assert "database" in refused(link)
    assert client.get("/api/shares/nope", headers=auth).status_code == 404


def test_a_path_in_the_shares_folder_is_fine(client, auth, config):
    inside = config.notes_dir / "Shares" / "Library" / "Books"
    inside.mkdir(parents=True)
    made = client.post("/api/shares", json={"name": "books", "path": str(inside)}, headers=auth)
    assert made.status_code == 201, made.text


def test_what_is_wrong_with_the_permissions_is_said(client, auth, elsewhere):
    elsewhere.chmod(0o777)
    try:
        made = client.post("/api/shares", json={"name": "music", "path": str(elsewhere)}, headers=auth).json()
        assert any("world-writable" in w for w in made["warnings"])
        # And again whenever its owner looks, until it is fixed.
        assert any("world-writable" in w for w in client.get("/api/shares/music", headers=auth).json()["warnings"])
    finally:
        elsewhere.chmod(0o755)
    assert client.get("/api/shares/music", headers=auth).json()["warnings"] == []


@not_root
def test_a_directory_the_server_cannot_write_is_shared_with_a_warning(client, auth, elsewhere):
    elsewhere.chmod(0o555)
    try:
        made = client.post("/api/shares", json={"name": "music", "path": str(elsewhere)}, headers=auth)
        assert made.status_code == 201
        assert any("read-only" in w for w in made.json()["warnings"])
    finally:
        elsewhere.chmod(0o755)


@not_root
def test_a_directory_the_server_cannot_read_is_shared_with_a_warning(client, auth, elsewhere):
    elsewhere.chmod(0o000)
    try:
        made = client.post("/api/shares", json={"name": "music", "path": str(elsewhere)}, headers=auth)
        assert made.status_code == 201
        assert any("cannot open" in w for w in made.json()["warnings"])
    finally:
        elsewhere.chmod(0o755)


def test_a_folder_another_share_covers_is_said(client, auth, elsewhere):
    client.post("/api/shares", json={"name": "music", "path": str(elsewhere)}, headers=auth)
    (elsewhere / "Albums").mkdir()
    made = client.post("/api/shares", json={"name": "albums", "path": str(elsewhere / "Albums")}, headers=auth).json()
    assert any("inside the share music" in w for w in made["warnings"])


def test_a_path_is_checked_before_anything_is_made(client, auth, guest_auth, config, elsewhere):
    good = client.get("/api/shares/check", params={"path": str(elsewhere)}, headers=auth).json()
    assert good == {"path": str(elsewhere), "ok": True, "errors": [], "warnings": []}
    bad = client.get("/api/shares/check", params={"path": str(config.data_dir)}, headers=auth).json()
    assert bad["ok"] is False and bad["errors"]
    assert client.get("/api/shares/check", params={"path": str(elsewhere)}, headers=guest_auth).status_code == 403


def test_an_administrator_moves_a_share_by_changing_its_path(client, auth, config, elsewhere):
    client.post("/api/shares", json={"name": "music"}, headers=auth)
    moved = client.patch("/api/shares/music", json={"path": str(elsewhere)}, headers=auth)
    assert moved.status_code == 200, moved.text
    assert moved.json()["path"] == str(elsewhere) and moved.json()["managed"] is False
    back = client.patch("/api/shares/music", json={"path": ""}, headers=auth).json()
    assert back["path"] == str(config.notes_dir / "Shares" / "music") and back["managed"] is True
    # Giving its own folder by name is the same as giving none.
    again = client.patch("/api/shares/music", json={"path": back["path"]}, headers=auth).json()
    assert again["managed"] is True


def test_somebody_who_is_not_an_administrator_cannot_move_their_share(client, guest_auth, elsewhere):
    client.post("/api/shares", json={"name": "mine"}, headers=guest_auth)
    assert client.patch("/api/shares/mine", json={"path": str(elsewhere)}, headers=guest_auth).status_code == 403
    assert client.patch("/api/shares/mine", json={"description": "my things"}, headers=guest_auth).status_code == 200


# -- when an account goes -----------------------------------------------------------


def test_the_shares_of_an_account_that_goes_pass_to_the_administrator(client, auth, config):
    created = client.post("/api/users", json={"username": "carol", "password": "carolsecret1"}, headers=auth)
    assert created.status_code == 201, created.text
    carol = {"Authorization": f"Bearer {token_for(client, 'carol', 'carolsecret1')}"}
    client.post("/api/shares", json={"name": "recipes", "members": [{"kind": "user", "who": "guest"}]}, headers=carol)
    client.post("/api/shares", json={"name": "family", "members": [{"kind": "user", "who": "carol"}]}, headers=auth)
    assert client.delete("/api/users/carol", headers=auth).status_code == 204
    recipes = client.get("/api/shares/recipes", headers=auth).json()
    assert recipes["owner"] == "bram" and recipes["can_manage"] is True
    assert [m["who"] for m in recipes["members"]] == ["guest"]
    assert client.get("/api/shares/family", headers=auth).json()["members"] == []
    assert (config.notes_dir / "Shares" / "recipes").is_dir()


# -- the web app --------------------------------------------------------------------


def test_the_web_app_makes_shares_and_says_who_has_them():
    from pathlib import Path

    web = Path(__file__).parent.parent / "src" / "cloudmorrow" / "server" / "web"
    assert 'import "./shares.js";' in (web / "app.js").read_text(encoding="utf-8")
    assert '@import "./shares.css";' in (web / "app.css").read_text(encoding="utf-8")
    code = (web / "shares.js").read_text(encoding="utf-8")
    assert 'registerScreen("share"' in code
    # The routes it calls are the ones the server has.
    for route in ("/api/shares/candidates", "/api/shares/check", "/members", '"POST", "/api/shares"'):
        assert route in code, route


def test_a_share_called_dav_is_guarded_like_any_other(client, auth, config):
    """The path the guard reads is inside the mount: `/dav/dav/x` is the share `dav`."""
    client.post(
        "/api/shares",
        json={"name": "dav", "members": [{"kind": "user", "who": "guest", "access": "read"}]},
        headers=auth,
    )
    client.post("/api/shares", json={"name": "scratch", "members": [{"kind": "user", "who": "guest"}]}, headers=auth)
    guest = guest_dav(client)
    assert client.put("/dav/dav/x.txt", content=b"x", headers=guest).status_code == 403
    assert not (config.notes_dir / "Shares" / "dav" / "x.txt").exists()
    client.put("/dav/scratch/y.txt", content=b"y", headers=guest)
    moved = client.request(
        "MOVE", "/dav/scratch/y.txt", headers={**guest, "Destination": "http://testserver/dav/dav/y.txt"}
    )
    assert moved.status_code == 403
