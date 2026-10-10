"""Shares: a name, a directory, and whose directory it is."""

from __future__ import annotations

import os

import pytest

from cloudmorrow.server.shares import (
    InvalidSlugError,
    ShareExistsError,
    SharePathError,
    ShareRefused,
    ShareStore,
    UnknownShareError,
)

OWNER = "bram"


def make(store: ShareStore, owner: str, name: str, **kwargs):
    """A share, without what is said about its directory."""
    share, _warnings = store.create(owner, name, **kwargs)
    return share


@pytest.fixture()
def root(tmp_path):
    return tmp_path / "notes"


@pytest.fixture()
def store(tmp_path, root) -> ShareStore:
    return ShareStore(tmp_path / "cloudmorrow.db", lambda owner: root / "Shares")


def test_a_share_gets_a_directory_the_server_makes(store, root):
    share = make(store, OWNER, "media")
    assert share.managed
    assert share.path == root / "Shares" / "media"
    assert share.path.is_dir()


def test_the_shares_folder_is_one_for_everyone(store, root):
    """Whoever made it, a share is a folder in the one Shares folder."""
    mine = make(store, OWNER, "media")
    theirs = make(store, "guest", "music")
    assert mine.path.parent == theirs.path.parent == root / "Shares"


def test_projects_is_a_fine_name_for_a_share(store):
    """A project id's reserved words mean nothing here."""
    assert make(store, OWNER, "projects").name == "projects"


def test_shares_from_the_per_user_layout_move_into_the_shares_folder(tmp_path, root):
    """Made under `<owner>/shares` once; found there at startup and brought in."""
    old = ShareStore(tmp_path / "cloudmorrow.db", lambda owner: root / owner / "shares")
    share = make(old, OWNER, "pictures")
    (share.path / "holiday.jpg").write_bytes(b"x")
    taken = make(old, OWNER, "music")
    (root / "Shares" / "music").mkdir(parents=True)
    store = ShareStore(tmp_path / "cloudmorrow.db", lambda owner: root / "Shares")
    moved = store.relocate()
    assert [s.name for s in moved] == ["pictures"]
    assert store.get("pictures").path == root / "Shares" / "pictures"
    assert (root / "Shares" / "pictures" / "holiday.jpg").exists()
    assert not share.path.exists()
    # A name already taken in Shares: that share stays where it was.
    assert store.get("music").path == taken.path
    # And a second run has nothing to do.
    assert store.relocate() == []


def test_a_folder_already_in_shares_is_used_as_it_is(store, root):
    """What an admin copied into Shares becomes the share, whatever its case."""
    existing = root / "Shares" / "Pictures"
    existing.mkdir(parents=True)
    (existing / "holiday.jpg").write_bytes(b"x")
    share = make(store, OWNER, "pictures")
    assert share.path == existing
    assert share.managed
    assert (share.path / "holiday.jpg").exists()
    # And nothing was made beside it.
    assert sorted(child.name for child in (root / "Shares").iterdir()) == ["Pictures"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_a_folder_the_server_cannot_write_is_not_shared(store, root):
    """Copied in as another user, say: the share would be one nobody could use."""
    folder = root / "Shares" / "locked"
    folder.mkdir(parents=True)
    folder.chmod(0o500)
    try:
        with pytest.raises(SharePathError, match="cannot read and write"):
            make(store, OWNER, "locked")
        assert store.get("locked") is None
    finally:
        folder.chmod(0o700)


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_a_shares_folder_that_cannot_be_written_leaves_no_row_behind(store, root):
    shares = root / "Shares"
    shares.mkdir(parents=True)
    shares.chmod(0o500)
    try:
        with pytest.raises(SharePathError, match="cannot make the folder"):
            make(store, OWNER, "media")
        assert store.get("media") is None
    finally:
        shares.chmod(0o700)


def test_only_an_administrator_gives_a_path(store, tmp_path):
    """There is one place anybody's share can be; another is an admin's to choose."""
    existing = tmp_path / "srv" / "photos"
    existing.mkdir(parents=True)
    with pytest.raises(ShareRefused, match="administrator"):
        make(store, OWNER, "photos", path=existing)
    assert store.get("photos") is None
    share = make(store, OWNER, "photos", path=existing, admin=True)
    assert share.path == existing and not share.managed


def test_the_shares_directory_says_what_is_in_it_unshared(store, root):
    directory, folders = store.folders()
    # Asking makes the directory, so there is somewhere to put things.
    assert directory == root / "Shares" and directory.is_dir()
    assert folders == []
    (directory / "Music").mkdir()
    (directory / "Pictures").mkdir()
    (directory / ".hidden").mkdir()
    (directory / "notes.txt").write_text("x")
    assert store.folders()[1] == ["Music", "Pictures"]
    make(store, OWNER, "pictures")
    assert store.folders()[1] == ["Music"]


def test_the_name_is_a_slug(store):
    with pytest.raises(InvalidSlugError):
        make(store, OWNER, "My Media")
    with pytest.raises(InvalidSlugError):
        make(store, OWNER, "../etc")
    assert make(store, OWNER, "  MEDIA ").name == "media"


def test_two_shares_cannot_share_a_name(store):
    make(store, OWNER, "media")
    with pytest.raises(ShareExistsError):
        make(store, OWNER, "media")


def test_a_name_is_the_servers_not_the_accounts(store):
    """One folder and one address per name, so one share per name, whoever made it."""
    make(store, OWNER, "media")
    with pytest.raises(ShareExistsError):
        make(store, "guest", "media")
    assert [share.owner for share in store.owned_by(OWNER)] == [OWNER]
    assert store.owned_by("guest") == []


def test_deleting_a_share_keeps_its_directory_unless_asked(store):
    share = make(store, OWNER, "media")
    (share.path / "film.mkv").write_bytes(b"x")
    store.delete("media")
    assert store.get("media") is None
    assert (share.path / "film.mkv").exists()


def test_deleting_a_managed_share_with_its_files_removes_the_directory(store):
    share = make(store, OWNER, "media")
    (share.path / "film.mkv").write_bytes(b"x")
    store.delete("media", remove_files=True)
    assert not share.path.exists()


def test_a_folder_that_was_already_in_shares_goes_with_the_files_too(store, root):
    """It is in Shares, so it is the server's to delete — when asked."""
    existing = root / "Shares" / "photos"
    existing.mkdir(parents=True)
    (existing / "holiday.jpg").write_bytes(b"x")
    make(store, OWNER, "photos")
    store.delete("photos")
    assert (existing / "holiday.jpg").exists()
    make(store, OWNER, "photos")
    store.delete("photos", remove_files=True)
    assert not existing.exists()


def test_deleting_what_is_not_there(store):
    with pytest.raises(UnknownShareError):
        store.delete("media")


# -- who has it -----------------------------------------------------------------------


def _person(store: ShareStore, username: str) -> None:
    with store.db.connect() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at, updated_at) VALUES (?, 'x', 'now', 'now')",
            (username,),
        )


def _circle(store: ShareStore, circle_id: str, *members: str) -> None:
    with store.db.connect() as conn:
        conn.execute("INSERT INTO circles (id, name, created_at) VALUES (?, ?, 'now')", (circle_id, circle_id.title()))
        for username in members:
            conn.execute("INSERT INTO circle_members (circle_id, username) VALUES (?, ?)", (circle_id, username))


def test_access_is_the_most_any_line_gives(store):
    for name in ("ann", "kid"):
        _person(store, name)
    _circle(store, "kids", "kid")
    share = make(store, OWNER, "family", members=[("circle", "kids", "read"), ("user", "kid", "write")])
    assert store.access_of(share, OWNER) == "write"
    assert store.access_of(share, "kid") == "write"
    assert store.access_of(share, "ann") is None
    share = store.add_member(share, "everyone", "", "read", by=OWNER, admin=True)
    assert store.access_of(share, "ann") == "read"
    assert [s.name for s in store.visible("ann")] == ["family"]
    assert store.for_user("nobody-at-all", "family") is not None  # everybody is everybody
    share = store.remove_member(share, "everyone", "*")
    assert store.for_user("ann", "family") is None


def test_an_account_that_goes_hands_its_shares_on(store):
    for name in ("ann", "kid", OWNER):
        _person(store, name)
    make(store, "ann", "recipes", members=[("user", "kid", "write"), ("user", OWNER, "read")])
    make(store, OWNER, "family", members=[("user", "ann", "write")])
    handed = store.forget_user("ann", heir=OWNER)
    assert [s.name for s in handed] == ["recipes"]
    recipes = store.get("recipes")
    assert recipes.owner == OWNER
    # The heir's own line is no longer needed; the others stay.
    assert [(m.kind, m.who) for m in recipes.members] == [("user", "kid")]
    assert store.get("family").members == ()


def test_the_migration_drops_machine_shares_and_renames_a_name_taken_twice(store):
    from cloudmorrow.server import schema

    with store.db.connect() as conn:
        conn.executescript("DROP INDEX IF EXISTS shares_by_name")
        for owner, name, kind in (("ann", "media", "server"), ("bob", "media", "server"), ("bob", "music", "machine")):
            conn.execute(
                "INSERT INTO shares (owner, name, kind, path, managed, description, created_at, updated_at)"
                " VALUES (?, ?, ?, '/x', 1, '', 'now', 'now')",
                (owner, name, kind),
            )
        schema._shares_shared(conn)
        rows = conn.execute("SELECT id, owner, name, kind FROM shares ORDER BY id").fetchall()
    assert [(r["owner"], r["name"]) for r in rows] == [("ann", "media"), ("bob", f"media-{rows[1]['id']}")]
    with pytest.raises(ShareExistsError):
        make(store, OWNER, "media")


def test_what_the_server_cannot_do_in_a_folder_is_said(tmp_path, monkeypatch):
    """Root can do anything, so the server's view is stood in for."""
    from cloudmorrow.server import shares

    folder = tmp_path / "library"
    folder.mkdir()
    (folder / "locked.mp3").write_bytes(b"x")
    (folder / "song.mp3").write_bytes(b"x")
    real = os.access

    def server_can(path, mode):
        name = os.path.basename(str(path))
        if name == "locked.mp3":
            return False
        if name == "library" and mode & os.W_OK:
            return False
        return real(path, mode)

    monkeypatch.setattr(shares.os, "access", server_can)
    found = shares.permission_warnings(folder)
    assert any("read-only" in w for w in found)
    assert any("1 item at the top of the folder cannot be read" in w for w in found)

    monkeypatch.setattr(shares.os, "access", lambda path, mode: False)
    assert len(shares.permission_warnings(folder)) == 1
    assert "cannot open the folder" in shares.permission_warnings(folder)[0]
