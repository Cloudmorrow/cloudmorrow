"""Installing rclone where it is missing: which command, and what happens after.

Nothing is installed — the shell-out is caught — so these run on any machine,
with or without a package manager.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import typer

from cloudmorrow.cli import share as share_cli
from cloudmorrow.client import mounts, rclone


def have(*tools: str):
    """A PATH with just these on it."""
    return lambda name: f"/usr/bin/{name}" if name in tools else None


@pytest.fixture()
def user(monkeypatch):
    monkeypatch.setattr(rclone, "_root", lambda: False)


# -- which command --------------------------------------------------------------


def test_the_distributions_package_manager_is_used_with_sudo(user, monkeypatch):
    monkeypatch.setattr(rclone.shutil, "which", have("apt-get", "sudo"))
    assert rclone.install_command() == ["sudo", "apt-get", "install", "-y", "rclone"]


def test_the_first_package_manager_found_wins(user, monkeypatch):
    monkeypatch.setattr(rclone.shutil, "which", have("pacman", "brew", "sudo"))
    assert rclone.install_command()[:2] == ["sudo", "pacman"]


def test_root_needs_no_sudo(monkeypatch):
    monkeypatch.setattr(rclone, "_root", lambda: True)
    monkeypatch.setattr(rclone.shutil, "which", have("dnf"))
    assert rclone.install_command() == ["dnf", "install", "-y", "rclone"]


def test_brew_is_never_run_with_sudo(user, monkeypatch):
    monkeypatch.setattr(rclone.shutil, "which", have("brew"))
    assert rclone.install_command() == ["brew", "install", "rclone"]


def test_no_sudo_means_no_command_unless_brew_is_there(user, monkeypatch):
    monkeypatch.setattr(rclone.shutil, "which", have("apt-get"))
    assert rclone.install_command() is None
    monkeypatch.setattr(rclone.shutil, "which", have("apt-get", "brew"))
    assert rclone.install_command() == ["brew", "install", "rclone"]


def test_no_package_manager_means_no_command(user, monkeypatch):
    monkeypatch.setattr(rclone.shutil, "which", have("sudo"))
    assert rclone.install_command() is None


def test_the_hint_says_the_command_or_where_to_read(user, monkeypatch):
    monkeypatch.setattr(rclone.shutil, "which", have("pacman", "sudo"))
    assert "`sudo pacman -S --needed --noconfirm rclone` installs it" in rclone.hint()
    monkeypatch.setattr(rclone.shutil, "which", lambda name: None)
    assert rclone.DOWNLOAD in rclone.hint()


def test_the_mount_error_without_rclone_carries_the_same_hint(user, monkeypatch):
    monkeypatch.setattr(mounts, "platform", lambda: "linux")
    monkeypatch.setattr(rclone.shutil, "which", have("apt-get", "sudo"))
    with pytest.raises(mounts.MountError, match="sudo apt-get install -y rclone"):
        mounts.mount("media", "https://x/dav/media/", "bram", "token")


# -- installing ---------------------------------------------------------------------


class Shell:
    def __init__(self, returncode: int = 0, *, appears: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode
        self.appears = appears

    def __call__(self, command: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(command)
        if self.appears:
            rclone.shutil.which = have("apt-get", "sudo", "rclone")
        return subprocess.CompletedProcess(command, self.returncode)


def test_install_runs_the_command_in_the_terminal_and_says_where_rclone_is(user, monkeypatch):
    monkeypatch.setattr(rclone.shutil, "which", have("apt-get", "sudo"))
    shell = Shell()
    monkeypatch.setattr(rclone, "_run", shell)
    assert rclone.install() == Path("/usr/bin/rclone")
    # No pipes: the package manager has the terminal, so sudo can ask there.
    assert shell.calls == [["sudo", "apt-get", "install", "-y", "rclone"]]


def test_a_failed_install_says_so(user, monkeypatch):
    monkeypatch.setattr(rclone.shutil, "which", have("apt-get", "sudo"))
    monkeypatch.setattr(rclone, "_run", Shell(returncode=100, appears=False))
    with pytest.raises(rclone.InstallError, match="exited 100"):
        rclone.install()


def test_an_install_that_leaves_no_rclone_behind_is_a_failure(user, monkeypatch):
    monkeypatch.setattr(rclone.shutil, "which", have("apt-get", "sudo"))
    monkeypatch.setattr(rclone, "_run", Shell(appears=False))
    with pytest.raises(rclone.InstallError, match="still not on the PATH"):
        rclone.install()


def test_nothing_to_install_with_is_a_failure_that_says_where_to_read(user, monkeypatch):
    monkeypatch.setattr(rclone.shutil, "which", lambda name: None)
    with pytest.raises(rclone.InstallError, match="rclone.org"):
        rclone.install()


# -- the CLI ---------------------------------------------------------------------------


def test_share_mount_asks_before_installing_and_then_does(user, monkeypatch, capsys):
    monkeypatch.setattr(rclone.shutil, "which", have("apt-get", "sudo"))
    shell = Shell()
    monkeypatch.setattr(rclone, "_run", shell)
    monkeypatch.setattr(share_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(share_cli.typer, "confirm", lambda *args, **kwargs: True)
    share_cli._install_rclone()
    assert shell.calls == [["sudo", "apt-get", "install", "-y", "rclone"]]
    assert "Installed" in capsys.readouterr().err


def test_share_mount_takes_no_for_an_answer(user, monkeypatch):
    monkeypatch.setattr(rclone.shutil, "which", have("apt-get", "sudo"))
    shell = Shell()
    monkeypatch.setattr(rclone, "_run", shell)
    monkeypatch.setattr(share_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(share_cli.typer, "confirm", lambda *args, **kwargs: False)
    with pytest.raises(typer.Exit):
        share_cli._install_rclone()
    assert shell.calls == []


def test_share_mount_in_a_script_only_says_the_command(user, monkeypatch, capsys):
    monkeypatch.setattr(rclone.shutil, "which", have("apt-get", "sudo"))
    shell = Shell()
    monkeypatch.setattr(rclone, "_run", shell)
    monkeypatch.setattr(share_cli.sys.stdin, "isatty", lambda: False)
    with pytest.raises(typer.Exit):
        share_cli._install_rclone()
    assert shell.calls == []
    # Rich wraps the line; the command is in it all the same.
    assert "sudo apt-get install -y rclone" in " ".join(capsys.readouterr().err.split())
