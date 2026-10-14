"""The commands this package installs, and keeping them on the PATH.

The installer symlinks `<venv>/bin/<tool>` into a bin directory; pip knows
nothing of that, so a command added in a later release would sit in the
venv unreachable. Two things put it right. `cloudmorrow update` links what
arrived, and — because the update that brings a new command is run by the
old code, which has never heard of it — the new code links itself the first
time it runs, from the CLI or from the agent.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Every command the package installs. The installer links these onto the
# PATH; an update, or the first run after one, links whichever arrived since.
COMMANDS = ("cloudmorrow", "cm", "cloudmorrow-agent")
# What a server has on its PATH beside cloudmorrow-server: the terminal
# app, under both its names, so an administrator at the box can sign in
# there. Not the agent: the server's own runs from the venv, under its unit.
SERVER_COMMANDS = ("cloudmorrow", "cm")


def link_new_commands(prefix: Path, *, which=None) -> list[Path]:
    """Link commands new to this release beside the `cloudmorrow` already on the PATH.

    Finds the bin directory by way of the existing link and puts the
    newcomers next to it. Whatever is already there — ours or not — is left
    alone, and so is a `cloudmorrow` that is not our link (pipx, a checkout).
    """
    found = (which or shutil.which)("cloudmorrow")
    if not found:
        return []
    existing = Path(found)
    if not existing.is_symlink() or existing.resolve().parent != (prefix / "bin").resolve():
        return []
    bindir = existing.parent
    linked: list[Path] = []
    for tool in COMMANDS:
        target = prefix / "bin" / tool
        link = bindir / tool
        if target.is_file() and not link.exists() and not link.is_symlink():
            link.symlink_to(target)
            linked.append(link)
    return linked


def link_server_commands(prefix: Path, *, which=None) -> tuple[list[Path], list[str]]:
    """Put the terminal app beside the `cloudmorrow-server` on the PATH.

    The server installer links `<venv>/bin/cloudmorrow-server` into
    /usr/local/bin, and `cm` belongs beside it. The installer links it; so
    does an update, which is how `cm` reaches a server installed before it
    was there — when it may. The update runs as the service user, which
    owns the venv and not /usr/local/bin, so what could not be linked comes
    back by name for the caller to say. A `cm` that is somebody else's is
    left alone, and not reported: it is not ours to replace.

    Returns (linked, unlinked).
    """
    found = (which or shutil.which)("cloudmorrow-server")
    if not found:
        return [], []
    existing = Path(found)
    if not existing.is_symlink() or existing.resolve().parent != (prefix / "bin").resolve():
        return [], []
    bindir = existing.parent
    linked: list[Path] = []
    unlinked: list[str] = []
    for tool in SERVER_COMMANDS:
        target = prefix / "bin" / tool
        link = bindir / tool
        if not target.is_file() or link.exists() or link.is_symlink():
            continue
        try:
            link.symlink_to(target)
        except OSError:
            unlinked.append(tool)
        else:
            linked.append(link)
    return linked, unlinked


def ensure_commands_linked() -> list[Path]:
    """Link this release's new commands, quietly. For the start of a run.

    Nothing that happens here may stop the command that was actually asked
    for, so a bin directory that cannot be written is simply left as it is.
    On a server, a run with the right to write /usr/local/bin — root's —
    is also when `cm` gets there, if an update could not put it there.
    """
    prefix = Path(sys.executable).resolve().parent.parent
    try:
        linked = link_new_commands(prefix)
        linked += link_server_commands(prefix)[0]
        return linked
    except OSError:
        return []
