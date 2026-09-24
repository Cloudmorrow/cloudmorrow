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


def ensure_commands_linked() -> list[Path]:
    """Link this release's new commands, quietly. For the start of a run.

    Nothing that happens here may stop the command that was actually asked
    for, so a bin directory that cannot be written is simply left as it is.
    """
    prefix = Path(sys.executable).resolve().parent.parent
    try:
        return link_new_commands(prefix)
    except OSError:
        return []
