from __future__ import annotations

import pytest

from cloudmorrow.paths import UnsafePathError, normalise_rel_path, resolve_within


@pytest.mark.parametrize(
    "raw",
    ["../escape.md", "a/../../b.md", "/etc/passwd/../x", "", "   ", "bad\x00name"],
)
def test_rejects_unsafe_paths(raw):
    with pytest.raises(UnsafePathError):
        normalise_rel_path(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a.md", "a.md"),
        ("/a/b.md", "a/b.md"),
        ("a\\b.md", "a/b.md"),
        ("deep/nest/n.md", "deep/nest/n.md"),
    ],
)
def test_accepts_normal_paths(raw, expected):
    assert normalise_rel_path(raw).as_posix() == expected


def test_redundant_segments_are_normalised():
    assert normalise_rel_path("a/./b.md").as_posix() == "a/b.md"


def test_resolve_within_stays_inside_root(tmp_path):
    root = tmp_path / "notes"
    root.mkdir()
    assert resolve_within(root, "work/todo.md") == root / "work" / "todo.md"
    with pytest.raises(UnsafePathError):
        resolve_within(root, "../outside.md")


def test_resolve_within_blocks_symlink_escape(tmp_path):
    root = tmp_path / "notes"
    root.mkdir()
    (tmp_path / "secret").mkdir()
    (root / "link").symlink_to(tmp_path / "secret")
    with pytest.raises(UnsafePathError):
        resolve_within(root, "link/leak.md")
