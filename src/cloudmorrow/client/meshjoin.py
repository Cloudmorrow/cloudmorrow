"""Putting this computer on the cloud's mesh.

A linked cloud's mesh is the box and the devices its people invited
(server/access_mesh.py), and a computer joins it with Tailscale's own
open-source client pointed at the cloud's login server. Joining is three
steps, and this module is each of them, shared by `cm access join`, the
client installer's `--invite` and the desktop app:

1. a one-time key: from the cloud, signed in, on the home network (`POST
   /api/access/mesh/key`); or from the relay, for an invite code somebody
   on the cloud made (`POST <relay>/v1/invites/redeem` with the cloud's
   name and the code, no sign-in: this computer cannot reach the cloud
   yet, which is the point);
2. `tailscale` — installing it first only with the person's consent, from
   tailscale.com's own installer on Linux; a Mac gets the Tailscale app
   from the App Store, which this cannot do for anybody;
3. `tailscale up --login-server <login server> --authkey <key> --hostname
   cm-<6 hex>`, which needs root on Linux: through sudo on a terminal,
   pkexec (a password dialog) from the desktop app. The hostname says
   nothing about the computer or whose it is; the cloud keeps that.

Whether this computer is on the mesh is `tailscale status --json`: running,
and — where tailscale says so — on this cloud's login server.
"""

from __future__ import annotations

import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

INSTALL_SCRIPT = "https://tailscale.com/install.sh"
MAC_APP = "https://apps.apple.com/app/tailscale/id1475387142"
# Where the Mac app keeps its CLI when it is not on the PATH.
MAC_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


class JoinError(RuntimeError):
    """What stops this computer joining, in a sentence that says what to do."""


def _run(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, timeout=120)


def new_hostname() -> str:
    """`cm-<6 hex>`: this computer's name on the mesh, which tells the relay nothing."""
    return f"cm-{secrets.token_hex(3)}"


def device_name() -> str:
    """What to call this computer on the cloud, by default: `Annas-MacBook.local` → `annas-macbook`."""
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
        raise JoinError(f"Install the Tailscale app from the App Store ({MAC_APP}), then run this again.")
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
    """Join with *key* (what the cloud or the relay answered: key, login_server, maybe hostname).

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
    name = hostname or str(key.get("hostname") or "") or new_hostname()
    command = up_command(key["login_server"], key["key"], name, graphical=graphical)
    result = run(command)
    if result.returncode != 0:
        raise JoinError(f"tailscale up failed: {_last(result)}")
    return state(run)


def _last(result: subprocess.CompletedProcess) -> str:
    lines = [ln.strip() for ln in f"{result.stderr or ''}\n{result.stdout or ''}".splitlines() if ln.strip()]
    return lines[-1] if lines else f"exit {result.returncode}"


# -- an invite -----------------------------------------------------------------------
def cloud_name_of(server_url: str) -> tuple[str, str]:
    """`https://larsens.cloudmorrow.tech` → (`larsens`, `cloudmorrow.tech`)."""
    host = urlsplit(server_url if "://" in server_url else f"https://{server_url}").hostname or ""
    name, _, zone = host.partition(".")
    if not name or "." not in zone:
        raise JoinError(f"{server_url} is not a linked cloud's address (like https://larsens.cloudmorrow.tech)")
    return name, zone


def relay_for(server_url: str, access_control: str = "") -> str:
    """Where invites are redeemed: the one given, else `https://relay.<zone>` of the cloud's name."""
    if access_control:
        return access_control.rstrip("/")
    _, zone = cloud_name_of(server_url)
    return f"https://relay.{zone}"


def redeem(
    server_url: str,
    code: str,
    *,
    access_control: str = "",
    http: httpx.Client | None = None,
) -> dict:
    """Trade an invite code for a one-time key at the relay: {key, login_server, expires_at}.

    Only the cloud's name and the code are sent. Nothing about this computer.
    """
    name, _ = cloud_name_of(server_url)
    code = re.sub(r"[\s-]+", "", code or "").upper()
    if not code:
        raise JoinError("an invite code is six characters, from Me → Invite a device on the cloud")
    url = relay_for(server_url, access_control) + "/v1/invites/redeem"
    client = http or httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))
    try:
        response = client.post(url, json={"name": name, "code": code})
    except httpx.HTTPError as exc:
        raise JoinError(f"cannot reach {url}: {exc}") from exc
    finally:
        if http is None:
            client.close()
    if response.status_code == 404:
        raise JoinError("that invite code is wrong, used, or ran out; ask for a new one")
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        raise JoinError(str(detail or f"the relay answered {response.status_code}"))
    data = response.json()
    if not data.get("key") or not data.get("login_server"):
        raise JoinError("the relay's answer has no key")
    return data
