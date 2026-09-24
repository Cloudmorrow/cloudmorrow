"""Whether a directory on this machine can be shared from here."""

from __future__ import annotations

import os

import pytest

from cloudmorrow.client import sharing

not_root = pytest.mark.skipif(os.geteuid() == 0, reason="root can read and write anywhere")


def test_a_readable_writable_directory_is_fine(tmp_path):
    assert sharing.problem(str(tmp_path)) is None


def test_the_path_is_resolved_with_the_home_and_dots_worked_out(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Music").mkdir()
    assert sharing.resolve("~/Music/../Music") == tmp_path / "Music"
    assert sharing.problem("~/Music") is None


def test_what_is_not_there_or_not_a_directory_is_said(tmp_path):
    assert "not there" in sharing.problem(str(tmp_path / "nope"))
    (tmp_path / "song.mp3").write_bytes(b"x")
    assert "not a directory" in sharing.problem(str(tmp_path / "song.mp3"))


@not_root
def test_what_you_cannot_read_or_write_is_said(tmp_path):
    sealed = tmp_path / "sealed"
    sealed.mkdir()
    sealed.chmod(0o000)
    try:
        assert "cannot read" in sharing.problem(str(sealed))
    finally:
        sealed.chmod(0o700)
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    frozen.chmod(0o500)
    try:
        assert "cannot write" in sharing.problem(str(frozen))
    finally:
        frozen.chmod(0o700)
