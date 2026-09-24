"""Mounting a share here: which tool, what it is told, and what is written down.

Nothing is really mounted — the shell-outs are caught and inspected — so
these run anywhere, including on the machine that has neither rclone nor
Finder.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cloudmorrow.client import mounts

URL = "https://cloudmorrow.example/dav/media/"


class Shell:
    """Stands in for every command `mounts` runs, and remembers each one."""

    def __init__(self, *, fail: str | None = None, mount_listing: str = "") -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self.fail = fail
        self.mount_listing = mount_listing

    def __call__(self, command: list[str], **kwargs) -> subprocess.CompletedProcess:
        self.calls.append((command, kwargs))
        if self.fail and command[0] == self.fail:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="boom\nno such host")
        if Path(command[0]).name == "rclone" and command[1:2] == ["obscure"]:
            return subprocess.CompletedProcess(command, 0, stdout="OBSCURED\n", stderr="")
        if command == ["mount"]:
            return subprocess.CompletedProcess(command, 0, stdout=self.mount_listing, stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    def commands(self, name: str) -> list[list[str]]:
        return [command for command, _ in self.calls if command[0] == name]


@pytest.fixture()
def linux(monkeypatch):
    monkeypatch.setattr(mounts, "platform", lambda: "linux")
    monkeypatch.setattr(mounts.shutil, "which", lambda name: f"/usr/bin/{name}")


@pytest.fixture()
def macos(monkeypatch):
    monkeypatch.setattr(mounts, "platform", lambda: "darwin")
    monkeypatch.setattr(mounts.shutil, "which", lambda name: f"/usr/bin/{name}")


@pytest.fixture()
def not_mounted(monkeypatch):
    monkeypatch.setattr(mounts.os.path, "ismount", lambda path: False)


# -- Linux: rclone ----------------------------------------------------------------


def test_on_linux_rclone_mounts_it_where_you_say(linux, not_mounted, monkeypatch, tmp_path):
    shell = Shell()
    monkeypatch.setattr(mounts, "_run", shell)
    target = tmp_path / "Fileshares" / "media"
    mounted = mounts.mount("media", URL, "bram", "the-token", path=target)
    assert mounted.path == target and mounted.tool == "rclone"
    assert target.is_dir()
    (command, kwargs) = next(
        (command, kwargs) for command, kwargs in shell.calls if command[1:2] == ["mount"]
    )
    assert command[2:4] == [":webdav:", str(target)]
    assert "--daemon" in command and "writes" in command
    # The credentials go in the environment, obscured, not on the command line.
    env = kwargs["env"]
    assert env["RCLONE_WEBDAV_URL"] == URL
    assert env["RCLONE_WEBDAV_USER"] == "bram"
    assert env["RCLONE_WEBDAV_PASS"] == "OBSCURED"
    assert "the-token" not in " ".join(command)
    # And what happened is written down for the TUI and for unmount.
    assert mounts.lookup("media").path == target


def test_the_default_place_on_linux_is_under_fileshares(linux):
    assert mounts.default_mountpoint("media") == Path.home() / "Fileshares" / "media"


def test_without_rclone_the_message_says_what_to_install(monkeypatch, not_mounted):
    monkeypatch.setattr(mounts, "platform", lambda: "linux")
    monkeypatch.setattr(mounts.shutil, "which", lambda name: None)
    with pytest.raises(mounts.MountError, match="rclone"):
        mounts.mount("media", URL, "bram", "the-token")


def test_a_directory_with_things_in_it_is_not_mounted_over(
    linux, not_mounted, monkeypatch, tmp_path
):
    monkeypatch.setattr(mounts, "_run", Shell())
    target = tmp_path / "media"
    target.mkdir()
    (target / "keep.txt").write_text("x")
    with pytest.raises(mounts.MountError, match="not empty"):
        mounts.mount("media", URL, "bram", "the-token", path=target)


def test_a_failed_mount_says_why_and_remembers_nothing(linux, not_mounted, monkeypatch, tmp_path):
    monkeypatch.setattr(mounts, "_run", Shell(fail="/usr/bin/rclone"))
    with pytest.raises(mounts.MountError, match="no such host"):
        mounts.mount("media", URL, "bram", "the-token", path=tmp_path / "media")
    assert mounts.lookup("media") is None


def test_unmount_on_linux_uses_fusermount_and_forgets(linux, monkeypatch, tmp_path):
    shell = Shell()
    monkeypatch.setattr(mounts, "_run", shell)
    monkeypatch.setattr(mounts.os.path, "ismount", lambda path: False)
    mounts.mount("media", URL, "bram", "the-token", path=tmp_path / "media")
    monkeypatch.setattr(mounts.os.path, "ismount", lambda path: True)
    gone = mounts.unmount("media")
    assert gone.path == tmp_path / "media"
    assert shell.commands("fusermount3") == [["fusermount3", "-u", str(tmp_path / "media")]]
    assert mounts.lookup("media") is None


def test_unmounting_what_was_never_mounted(linux):
    with pytest.raises(mounts.MountError, match="not mounted"):
        mounts.unmount("media")


def test_a_mount_that_went_away_is_reported_as_gone(linux, monkeypatch, tmp_path):
    monkeypatch.setattr(mounts, "_run", Shell())
    monkeypatch.setattr(mounts.os.path, "ismount", lambda path: False)
    mounted = mounts.mount("media", URL, "bram", "the-token", path=tmp_path / "media")
    assert mounted.active is False
    # Mounting again is allowed: the record is stale, not the mount.
    mounts.mount("media", URL, "bram", "the-token", path=tmp_path / "media")


def test_mounting_twice_is_refused_while_the_first_is_up(linux, monkeypatch, tmp_path):
    monkeypatch.setattr(mounts, "_run", Shell())
    monkeypatch.setattr(mounts.os.path, "ismount", lambda path: False)
    mounts.mount("media", URL, "bram", "the-token", path=tmp_path / "media")
    monkeypatch.setattr(mounts.os.path, "ismount", lambda path: True)
    with pytest.raises(mounts.MountError, match="already mounted"):
        mounts.mount("media", URL, "bram", "the-token", path=tmp_path / "media")


# -- macOS: Finder ------------------------------------------------------------------


def test_on_a_mac_finder_mounts_it_and_says_where(macos, not_mounted, monkeypatch, tmp_path):
    shell = Shell(
        mount_listing=(
            "/dev/disk1s1 on / (apfs, local)\n"
            "https://cloudmorrow.example/dav/media on /Volumes/media-1 (webdav, nodev)\n"
        )
    )
    monkeypatch.setattr(mounts, "_run", shell)
    mounted = mounts.mount("media", URL, "bram", "the-token", path=tmp_path / "ignored")
    assert mounted.tool == "finder"
    # Finder chose the place — a path given is ignored, and the real one read back.
    assert mounted.path == Path("/Volumes/media-1")
    (command, kwargs) = shell.calls[0]
    assert command == ["osascript"]
    script = kwargs["input"]
    assert script.startswith(f'mount volume "{URL}"')
    assert 'as user name "bram"' in script and 'with password "the-token"' in script


def test_on_a_mac_the_volume_is_assumed_when_mount_does_not_list_it(
    macos, not_mounted, monkeypatch
):
    monkeypatch.setattr(mounts, "_run", Shell())
    assert mounts.mount("media", URL, "bram", "the-token").path == Path("/Volumes/media")


def test_unmount_on_a_mac_uses_diskutil(macos, monkeypatch):
    shell = Shell()
    monkeypatch.setattr(mounts, "_run", shell)
    monkeypatch.setattr(mounts.os.path, "ismount", lambda path: False)
    mounts.mount("media", URL, "bram", "the-token")
    monkeypatch.setattr(mounts.os.path, "ismount", lambda path: True)
    mounts.unmount("media")
    assert shell.commands("diskutil") == [["diskutil", "unmount", "/Volumes/media"]]


def test_a_quote_in_the_secret_does_not_break_the_script():
    assert mounts._applescript_string('a"b\\c') == '"a\\"b\\\\c"'
