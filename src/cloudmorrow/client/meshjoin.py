"""Putting this computer on the cloud's private mesh.

Private access is a mesh of the box and the devices its people enrolled
(server/access_mesh.py), and a computer joins it with Tailscale's own
open-source client pointed at the cloud's login server. Enrolling is three
steps, and this module is each of them, shared by `cm access join`, the
client installer's `--private` and the desktop app:

1. ask the cloud for a one-time key, as the signed-in person, labelled with
   this computer's name (`POST /api/access/mesh/key`);
2. have `tailscale` — installing it first only with the person's consent,
   from tailscale.com's own installer on Linux; a Mac gets the Tailscale app
   from the App Store, which this cannot do for anybody;
3. `tailscale up --login-server <login server> --authkey <key> --hostname
   <this computer>`, which needs root on Linux: through sudo on a terminal,
   pkexec (a password dialog) from the desktop app.

Whether this computer is on the mesh is `tailscale status --json`: running,
and — where tailscale says so — on this cloud's login server.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass

INSTALL_SCRIPT = "https://tailscale.com/install.sh"
MAC_APP = "https://apps.apple.com/app/tailscale/id1475387142"
# Where the Mac app keeps its CLI when it is not on the PATH.
MAC_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


class JoinError(RuntimeError):
    """What stops this computer joining, in a sentence that says what to do."""


def _run(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, timeout=120)


def device_name() -> str:
    """This computer's name, as a mesh hostname: `Annas-MacBook.local` → `annas-macbook`."""
    raw = socket.gethostname().split(".")[0].lower()
    name = re.sub(r"[^a-z0-9-]+", "-", raw).strip("-")
    return name[:63] or "computer"


def tailscale_binary() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    if platform.system() == "Darwin" and os.path.exists(MAC_CLI):
        return MAC_CLI
    return None


@dataclass(slots=True)
class MeshState:
    installed: bool
    running: bool = False
    address: str = ""
    login_server: str = ""
    state: str = ""

    def on(self, login_server: str = "") -> bool:
        """On the mesh, and on *login_server*'s when both are known."""
        if not self.running:
            return False
        if login_server and self.login_server:
            return self.login_server.rstrip("/") == login_server.rstrip("/")
        return True

    def as_dict(self) -> dict:
        return {
            "installed": self.installed,
            "running": self.running,
            "address": self.address,
            "login_server": self.login_server,
            "state": self.state,
        }


def state(run: Runner = _run) -> MeshState:
    """What tailscale says about this computer."""
    binary = tailscale_binary()
    if binary is None:
        return MeshState(installed=False)
    try:
        result = run([binary, "status", "--json"])
        data = json.loads(result.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return MeshState(installed=True)
    backend = str(data.get("BackendState") or "")
    me = data.get("Self") or {}
    addresses = sorted((a for a in me.get("TailscaleIPs") or [] if a), key=lambda a: ":" in a)
    login = ""
    # The login server is in the preferences, not the status; asked for, and
    # left unknown if this tailscale will not say.
    try:
        prefs = json.loads(run([binary, "debug", "prefs"]).stdout or "{}")
        login = str(prefs.get("ControlURL") or "")
    except (OSError, ValueError, subprocess.SubprocessError):
        login = ""
    return MeshState(
        installed=True,
        running=backend == "Running",
        address=addresses[0] if addresses and backend == "Running" else "",
        login_server=login,
        state=backend,
    )


def elevated(cmd: Sequence[str], *, graphical: bool = False) -> list[str]:
    """*cmd* as root: itself when already root or on a Mac, else pkexec or sudo."""
    if platform.system() == "Darwin" or (hasattr(os, "geteuid") and os.geteuid() == 0):
        return list(cmd)
    if graphical and shutil.which("pkexec"):
        return ["pkexec", *cmd]
    return ["sudo", *cmd]


def install_command() -> list[str]:
    """How tailscale is installed here, or JoinError saying how to do it by hand."""
    if platform.system() == "Darwin":
        raise JoinError(
            f"Install the Tailscale app from the App Store ({MAC_APP}), then run this again."
        )
    if platform.system() != "Linux":
        raise JoinError("Install Tailscale from https://tailscale.com/download, then run this again.")
    if not shutil.which("curl"):
        raise JoinError(f"curl is needed to install Tailscale: curl -fsSL {INSTALL_SCRIPT} | sh")
    # Tailscale's installer asks for sudo itself where it needs it.
    return ["sh", "-c", f"curl -fsSL {INSTALL_SCRIPT} | sh"]


def up_command(login_server: str, key: str, hostname: str, *, graphical: bool = False) -> list[str]:
    binary = tailscale_binary() or "tailscale"
    return elevated(
        [binary, "up", "--login-server", login_server, "--authkey", key, "--hostname", hostname],
        graphical=graphical,
    )


def join(
    key: dict,
    *,
    hostname: str = "",
    install: Callable[[], bool] | None = None,
    graphical: bool = False,
    run: Runner = _run,
) -> MeshState:
    """Join with *key* (what the cloud answered: key, login_server).

    *install* is asked whether tailscale may be installed when it is not
    here, and returns True to go ahead; None means do not install.
    """
    if tailscale_binary() is None:
        command = install_command()
        if install is None or not install():
            raise JoinError(
                "Tailscale is not installed. Install it (" + " ".join(command[2:]) + ") and run this again."
            )
        result = run(command)
        if result.returncode != 0 or tailscale_binary() is None:
            raise JoinError(f"installing Tailscale did not work: {_last(result)}")
    command = up_command(key["login_server"], key["key"], hostname or device_name(), graphical=graphical)
    result = run(command)
    if result.returncode != 0:
        raise JoinError(f"tailscale up failed: {_last(result)}")
    return state(run)


def _last(result: subprocess.CompletedProcess) -> str:
    lines = [ln.strip() for ln in f"{result.stderr or ''}\n{result.stdout or ''}".splitlines() if ln.strip()]
    return lines[-1] if lines else f"exit {result.returncode}"
