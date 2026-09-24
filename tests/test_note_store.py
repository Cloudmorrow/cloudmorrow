from __future__ import annotations

import os

import pytest

from cloudmorrow.server.notes import (
    NoteConflictError,
    NoteExistsError,
    NoteNotFoundError,
    NoteStore,
    unique_path,
)
from cloudmorrow.server.sealed import Sealer


@pytest.fixture()
def store(tmp_path) -> NoteStore:
    return NoteStore(tmp_path / "notes", Sealer(os.urandom(32)))


def test_write_read_roundtrip(store):
    note = store.write("work/standup.md", "# Standup\n")
    assert note.path == "work/standup.md"
    assert store.read("work/standup").content == "# Standup\n"
    assert (store.root / "work" / "standup.md").is_file()


def test_suffix_is_added(store):
    assert store.write("idea", "x").path == "idea.md"


def test_tree_is_nested_and_sorted(store):
    store.write("b.md", "")
    store.write("alpha/one.md", "")
    store.write("alpha/two.md", "")
    tree = store.tree().to_dict()
    names = [child["name"] for child in tree["children"]]
    assert names == ["alpha", "b.md"]  # folders first
    assert [c["name"] for c in tree["children"][0]["children"]] == ["one.md", "two.md"]


def test_hidden_files_are_skipped(store):
    store.write("visible.md", "")
    (store.root / ".hidden.md").write_text("nope")
    assert [c["name"] for c in store.tree().to_dict()["children"]] == ["visible.md"]


def test_conflicting_write_is_rejected(store):
    note = store.write("n.md", "one")
    store.write("n.md", "two from elsewhere")
    with pytest.raises(NoteConflictError) as excinfo:
        store.write("n.md", "three", rev=note.rev)
    assert excinfo.value.current_content == "two from elsewhere"
    # Writing with the current rev succeeds.
    store.write("n.md", "three", rev=store.read("n.md").rev)
    assert store.read("n.md").content == "three"


def test_create_note_refuses_to_clobber(store):
    store.create_note("a.md", "hi")
    with pytest.raises(NoteExistsError):
        store.create_note("a.md")


def test_move_and_delete(store):
    store.write("a.md", "hi")
    assert store.move("a.md", "archive/a.md") == "archive/a.md"
    assert not (store.root / "a.md").exists()
    with pytest.raises(NoteExistsError):
        store.delete("archive")  # non-empty folder needs recursive
    store.delete("archive", recursive=True)
    with pytest.raises(NoteNotFoundError):
        store.read("archive/a.md")


def test_search_matches_body_and_name(store):
    store.write("meeting.md", "line one\nsomething about kubernetes\n")
    store.write("other.md", "nothing here")
    results = store.search("kubernetes")
    assert [r["path"] for r in results] == ["meeting.md"]
    assert results[0]["matches"][0]["line"] == 2
    assert [r["path"] for r in store.search("meet")] == ["meeting.md"]


def test_unique_path_avoids_collisions(store):
    store.write("note.md", "")
    assert unique_path(store, "", "note") == "note-2.md"
    assert unique_path(store, "sub", "note") == "sub/note.md"
