"""Getting rclone onto a Linux machine that does not have it.

rclone is what mounts a share on Linux (see `mounts`), and it is one package
in every distribution's repository — so when it is missing, the fix is one
package-manager command, and the only thing in the way is the password sudo
asks for. This knows which command it is on this machine, and runs it in the
terminal, where sudo can ask.

The TUI hands the terminal over for the duration (`App.suspend`) and the CLI
is already in one; neither captures the output, so what the package manager
prints is seen where it always is.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

# In the order they are tried. One machine rarely has two, and when it does
# the first is the distribution's own; brew comes last because it is the one
# that may be there beside it.
PACKAGE_MANAGERS: tuple[tuple[str, list[str]], ...] = (
    ("pacman", ["pacman", "-S", "--needed", "--noconfirm", "rclone"]),
    ("apt-get", ["apt-get", "install", "-y", "rclone"]),
    ("dnf", ["dnf", "install", "-y", "rclone"]),
    ("zypper", ["zypper", "--non-interactive", "install", "rclone"]),
    ("apk", ["apk", "add", "rclone"]),
    ("brew", ["brew", "install", "rclone"]),
)

# brew refuses to run as root, and does not need to.
NO_SUDO = {"brew"}

DOWNLOAD = "https://rclone.org/install/"
MISSING = "rclone is what mounts a share on Linux, and it is not installed."


class InstallError(RuntimeError):
    """rclone was not installed; the message says what happened."""


def installed() -> bool:
    return shutil.which("rclone") is not None


def _root() -> bool:
    geteuid = getattr(os, "geteuid", None)
    return geteuid is not None and geteuid() == 0


def install_command() -> list[str] | None:
    """The command that installs rclone here, `sudo` included when it takes one.

    None when no package manager we know is on this machine, or the one that
    is needs root and there is no sudo to get it with.
    """
    for tool, command in PACKAGE_MANAGERS:
        if shutil.which(tool) is None:
            continue
        if tool in NO_SUDO or _root():
            return list(command)
        if shutil.which("sudo") is None:
            continue
        return ["sudo", *command]
    return None


def hint() -> str:
    """What to say when rclone is missing: the command, or where to look."""
    command = install_command()
    if command is None:
        return f"{MISSING} {DOWNLOAD} says how to get it."
    return f"{MISSING} `{shlex.join(command)}` installs it."


def _run(command: list[str]) -> subprocess.CompletedProcess:
    """The package manager, with the terminal: no pipes, so sudo can ask."""
    return subprocess.run(command)


def install() -> Path:
    """Install rclone with this machine's package manager, and say where it is.

    Runs in the terminal, so the caller must have one to give: the TUI
    suspends itself around this. Raises `InstallError` when there is no
    package manager to use, the command fails, or rclone is still not on the
    PATH afterwards.
    """
    command = install_command()
    if command is None:
        raise InstallError(hint())
    try:
        result = _run(command)
    except OSError as exc:
        raise InstallError(f"could not run {command[0]}: {exc}") from exc
    if result.returncode != 0:
        raise InstallError(f"`{shlex.join(command)}` exited {result.returncode}")
    found = shutil.which("rclone")
    if found is None:
        raise InstallError(
            f"`{shlex.join(command)}` finished, but rclone is still not on the PATH."
        )
    return Path(found)
