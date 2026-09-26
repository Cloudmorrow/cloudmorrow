"""The desktop app in the applications menu: an icon to click instead of `cm app`.

On Linux that is a `.desktop` file in `~/.local/share/applications` and the
hedgehog in `~/.local/share/icons`, which every desktop — GNOME, KDE,
Hyprland's launchers — reads without being told. It runs the `cloudmorrow`
this copy was installed as, by its full path, so it works whatever the
desktop's PATH is.

install.sh writes it (`cloudmorrow app --install-launcher`) on a computer with
a desktop; `cloudmorrow uninstall` takes it away again.

TODO(macos): an `.app` bundle in `~/Applications`: `Contents/MacOS/Cloudmorrow`
a two-line shell script that execs `<venv>/bin/cloudmorrow app`,
`Contents/Info.plist` naming it, and the hedgehog as `Contents/Resources/
Cloudmorrow.icns` (made with `iconutil` from icon-512.png). Without it a Mac
runs `cm app` from a terminal.

TODO(windows): a Start-menu shortcut, `%APPDATA%\\Microsoft\\Windows\\Start
Menu\\Programs\\Cloudmorrow.lnk`, pointing at `<venv>\\Scripts\\pythonw.exe -m
cloudmorrow.cli.main app` (pythonw, so no console window comes with it), with
the hedgehog as an .ico. A .lnk is binary, so it wants `pywin32` or a line of
PowerShell (`WScript.Shell`.CreateShortcut) to write; install.sh does not run
on Windows at all yet, so there is no installer to call it from either.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from cloudmorrow.desktop import system

APP_ID = "cloudmorrow"


class LauncherError(RuntimeError):
    """No launcher was written; the message says why."""


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def desktop_file() -> Path:
    return data_home() / "applications" / f"{APP_ID}.desktop"


def icon_file() -> Path:
    # The hicolor theme is the one every icon lookup falls back to, so the
    # launcher can name the icon rather than give a path to it.
    return data_home() / "icons" / "hicolor" / "512x512" / "apps" / f"{APP_ID}.png"


def command() -> str:
    """The `cloudmorrow` beside the Python running this — the copy being installed."""
    candidate = Path(sys.executable).parent / "cloudmorrow"
    if candidate.exists():
        return str(candidate)
    return shutil.which("cloudmorrow") or "cloudmorrow"


def _quote(argument: str) -> str:
    """An argument as the Exec line of a .desktop file wants it."""
    if not any(char in argument for char in ' \t"\'\\$`<>~|&;*?#()'):
        return argument
    escaped = argument.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`")
    return '"' + escaped.replace("$", "\\$") + '"'


def entry(name: str = "Cloudmorrow") -> str:
    """The .desktop file. *name* is what the menu shows: the cloud's own name."""
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={name}\n"
        "GenericName=Your own cloud\n"
        "Comment=Notes, files, chat and calendar on your own server\n"
        f"Exec={_quote(command())} app\n"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        "Categories=Network;Office;FileTransfer;\n"
    )


def install(name: str = "Cloudmorrow") -> list[Path]:
    """Write the launcher and its icon. Safe to run again: it just writes them anew."""
    if system.os_name() != system.LINUX:
        raise LauncherError(
            "a launcher is only made on Linux so far — run `cm app` to open the desktop app"
        )
    icon = icon_file()
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(system.ICON, icon)
    launcher = desktop_file()
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(entry(name), encoding="utf-8")
    launcher.chmod(0o755)
    # Most menus notice a new file on their own; this is for the ones that
    # read a cache. Not being there is not a failure.
    if shutil.which("update-desktop-database"):
        try:
            subprocess.run(
                ["update-desktop-database", str(launcher.parent)],
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    return [launcher, icon]


def installed() -> list[Path]:
    """The launcher files that are there now — what an uninstall would remove."""
    return [path for path in (desktop_file(), icon_file()) if path.exists()]


def remove() -> list[Path]:
    removed = []
    for path in installed():
        path.unlink()
        removed.append(path)
    return removed
