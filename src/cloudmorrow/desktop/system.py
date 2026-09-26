"""The things the desktop app does that differ per operating system.

Each is one small function, so that a Mac or Windows is a matter of filling
in a branch rather than finding the places that assumed Linux. Linux is done
properly. A Mac and Windows get what is one command away on them — revealing
a folder, a notification — and a plain sentence where it is not done yet.

Mounting is not here: `client.mounts` already knows who mounts on which
system, and the desktop app asks it rather than knowing twice.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from cloudmorrow.client import mounts, rclone

LINUX = "linux"
MACOS = "macos"
WINDOWS = "windows"

# What `notify` passes for an icon, where the system takes one.
ICON = Path(__file__).resolve().parent.parent / "server" / "web" / "icon-512.png"


class Unsupported(RuntimeError):
    """Not done on this operating system yet; the message says what would be needed."""


def os_name() -> str:
    """linux, macos or windows — the three the app is written for — or sys.platform."""
    platform = mounts.platform()
    if platform.startswith("linux"):
        return LINUX
    if platform == "darwin":
        return MACOS
    if platform in ("win32", "cygwin"):
        return WINDOWS
    return platform


def has_display() -> bool:
    """Whether a window could be opened here at all.

    On Linux that is a graphical session to draw in — X or Wayland — or Qt
    told to draw off the screen, which is how the tests open one on a
    machine with no display. A Mac or Windows is taken to have a screen: a
    headless one is a server, and nobody runs the desktop app on that.
    """
    if os_name() != LINUX:
        return True
    env = os.environ
    offscreen = env.get("QT_QPA_PLATFORM") == "offscreen"
    return bool(env.get("WAYLAND_DISPLAY") or env.get("DISPLAY") or offscreen)


def mount_support() -> dict:
    """Whether a share can be mounted here, what does it, and what is missing.

    A Mac mounts with Finder, which is always there. Linux mounts with
    rclone, which may not be — and the desktop app has no terminal to run
    sudo in, so what it can offer is the command. Windows has no mount yet.
    """
    name = os_name()
    if name == MACOS:
        return {"available": True, "tool": "finder", "detail": ""}
    if name == LINUX:
        if rclone.installed():
            return {"available": True, "tool": "rclone", "detail": ""}
        return {"available": False, "tool": "rclone", "detail": rclone.hint()}
    # TODO(windows): a share is a WebDAV URL, and Windows maps one as a drive
    # letter itself: `net use Z: https://…/dav/<name>/ /user:<name> <token>`
    # (the WebClient service must be running), or rclone with WinFsp. Either
    # needs a branch in client/mounts.py, not here.
    return {
        "available": False,
        "tool": "",
        "detail": "Mounting a share is not done on this system yet.",
    }


def _run(command: list[str]) -> subprocess.CompletedProcess:
    """Every shell-out goes through here, so a test can stand in for it."""
    return subprocess.run(command, capture_output=True, text=True, timeout=15)


def _spawn(command: list[str]) -> None:
    """Start something that outlives us — a file manager — without waiting on it."""
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def open_folder(path: str | os.PathLike) -> Path:
    """Show a folder in the system's file manager: Finder, Explorer, or xdg-open."""
    folder = Path(path).expanduser()
    if not folder.is_dir():
        raise FileNotFoundError(f"{folder} is not a folder on this computer")
    name = os_name()
    if name == MACOS:
        _spawn(["open", str(folder)])
    elif name == WINDOWS:
        os.startfile(str(folder))  # type: ignore[attr-defined]  # Windows only
    else:
        opener = shutil.which("xdg-open") or shutil.which("gio")
        if opener is None:
            raise Unsupported("there is no xdg-open here to open a folder with")
        _spawn([opener, "open", str(folder)] if opener.endswith("gio") else [opener, str(folder)])
    return folder


def _applescript_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(title: str, body: str = "") -> bool:
    """A notification from the system, best effort. False when there was none to send.

    Linux asks notify-send, which every desktop has; a Mac asks AppleScript.
    Windows would need a toast through WinRT, which is more than one command,
    so it says no rather than half doing it.
    """
    name = os_name()
    try:
        if name == MACOS:
            script = (
                f"display notification {_applescript_string(body)} "
                f"with title {_applescript_string(title)}"
            )
            return _run(["osascript", "-e", script]).returncode == 0
        if name == LINUX:
            binary = shutil.which("notify-send")
            if binary is None:
                return False
            command = [binary, "--app-name=Cloudmorrow"]
            if ICON.exists():
                command.append(f"--icon={ICON}")
            return _run([*command, title, body]).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    # TODO(windows): a toast via WinRT (the `windows-toasts` package, say).
    return False
