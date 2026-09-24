"""Shares: a name, a directory, and whose directory it is."""

from __future__ import annotations

import os

import pytest

from cloudmorrow.server.shares import (
    InvalidSlugError,
    ShareExistsError,
    SharePathError,
    ShareStore,
    UnknownShareError,
)

OWNER = "bram"


@pytest.fixture()
def root(tmp_path):
    return tmp_path / "notes"


@pytest.fixture()
def store(tmp_path, root) -> ShareStore:
    return ShareStore(tmp_path / "cloudmorrow.db", lambda owner: root / "Shares")


def test_a_share_gets_a_directory_the_server_makes(store, root):
    share = store.create(OWNER, "media")
    assert share.managed
    assert share.path == root / "Shares" / "media"
    assert share.path.is_dir()


def test_the_shares_folder_is_one_for_everyone(store, root):
    """Whoever made it, a share is a folder in the one Shares folder."""
    mine = store.create(OWNER, "media")
    theirs = store.create("guest", "music")
    assert mine.path.parent == theirs.path.parent == root / "Shares"


def test_projects_is_a_fine_name_for_a_share(store):
    """A project id's reserved words mean nothing here."""
    assert store.create(OWNER, "projects").name == "projects"


def test_shares_from_the_per_user_layout_move_into_the_shares_folder(tmp_path, root):
    """Made under `<owner>/shares` once; found there at startup and brought in."""
    old = ShareStore(tmp_path / "cloudmorrow.db", lambda owner: root / owner / "shares")
    share = old.create(OWNER, "pictures")
    (share.path / "holiday.jpg").write_bytes(b"x")
    taken = old.create(OWNER, "music")
    (root / "Shares" / "music").mkdir(parents=True)
    store = ShareStore(tmp_path / "cloudmorrow.db", lambda owner: root / "Shares")
    moved = store.relocate()
    assert [s.name for s in moved] == ["pictures"]
    assert store.get(OWNER, "pictures").path == root / "Shares" / "pictures"
    assert (root / "Shares" / "pictures" / "holiday.jpg").exists()
    assert not share.path.exists()
    # A name already taken in Shares: that share stays where it was.
    assert store.get(OWNER, "music").path == taken.path
    # And a second run has nothing to do.
    assert store.relocate() == []


def test_a_folder_already_in_shares_is_used_as_it_is(store, root):
    """What an admin copied into Shares becomes the share, whatever its case."""
    existing = root / "Shares" / "Pictures"
    existing.mkdir(parents=True)
    (existing / "holiday.jpg").write_bytes(b"x")
    share = store.create(OWNER, "pictures")
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
            store.create(OWNER, "locked")
        assert store.get(OWNER, "locked") is None
    finally:
        folder.chmod(0o700)


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_a_shares_folder_that_cannot_be_written_leaves_no_row_behind(store, root):
    shares = root / "Shares"
    shares.mkdir(parents=True)
    shares.chmod(0o500)
    try:
        with pytest.raises(SharePathError, match="cannot make the folder"):
            store.create(OWNER, "media")
        assert store.get(OWNER, "media") is None
    finally:
        shares.chmod(0o700)


def test_a_server_share_takes_no_path(store, tmp_path):
    """There is one place a server share can be; a path is a mistake, not a wish."""
    existing = tmp_path / "srv" / "photos"
    existing.mkdir(parents=True)
    with pytest.raises(SharePathError, match="Shares directory"):
        store.create(OWNER, "photos", path=existing)
    assert store.get(OWNER, "photos") is None


def test_the_shares_directory_says_what_is_in_it_unshared(store, root):
    directory, folders = store.folders(OWNER)
    # Asking makes the directory, so there is somewhere to put things.
    assert directory == root / "Shares" and directory.is_dir()
    assert folders == []
    (directory / "Music").mkdir()
    (directory / "Pictures").mkdir()
    (directory / ".hidden").mkdir()
    (directory / "notes.txt").write_text("x")
    assert store.folders(OWNER)[1] == ["Music", "Pictures"]
    store.create(OWNER, "pictures")
    assert store.folders(OWNER)[1] == ["Music"]


def test_the_name_is_a_slug(store):
    with pytest.raises(InvalidSlugError):
        store.create(OWNER, "My Media")
    with pytest.raises(InvalidSlugError):
        store.create(OWNER, "../etc")
    assert store.create(OWNER, "  MEDIA ").name == "media"


def test_two_shares_cannot_share_a_name(store):
    store.create(OWNER, "media")
    with pytest.raises(ShareExistsError):
        store.create(OWNER, "media")


def test_shares_are_listed_per_owner_but_the_folder_is_shared(store):
    """The record is the account's; the folder is the one in Shares, whoever named it."""
    store.create(OWNER, "media")
    store.create("guest", "media")
    assert [share.owner for share in store.shares(OWNER)] == [OWNER]
    assert store.get("guest", "media").path == store.get(OWNER, "media").path


def test_deleting_a_share_keeps_its_directory_unless_asked(store):
    share = store.create(OWNER, "media")
    (share.path / "film.mkv").write_bytes(b"x")
    store.delete(OWNER, "media")
    assert store.get(OWNER, "media") is None
    assert (share.path / "film.mkv").exists()


def test_deleting_a_managed_share_with_its_files_removes_the_directory(store):
    share = store.create(OWNER, "media")
    (share.path / "film.mkv").write_bytes(b"x")
    store.delete(OWNER, "media", remove_files=True)
    assert not share.path.exists()


def test_a_folder_that_was_already_in_shares_goes_with_the_files_too(store, root):
    """It is in Shares, so it is the server's to delete — when asked."""
    existing = root / "Shares" / "photos"
    existing.mkdir(parents=True)
    (existing / "holiday.jpg").write_bytes(b"x")
    store.create(OWNER, "photos")
    store.delete(OWNER, "photos")
    assert (existing / "holiday.jpg").exists()
    store.create(OWNER, "photos")
    store.delete(OWNER, "photos", remove_files=True)
    assert not existing.exists()


def test_deleting_what_is_not_there(store):
    with pytest.raises(UnknownShareError):
        store.delete(OWNER, "media")
