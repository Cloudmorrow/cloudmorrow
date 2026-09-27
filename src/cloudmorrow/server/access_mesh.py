"""The private way in: the box on the cloud's own mesh, through the `tailscale` CLI.

Private access is WireGuard between the box and the devices its people
enroll, coordinated by the Headscale behind the control server. The box
does its part with Tailscale's own open-source client, which is a daemon
(`tailscaled`, root, installed by the installer with the owner's consent)
and a CLI that talks to it. This module is only the CLI, run as the
service user, which the installer made the daemon's `--operator` so it may
bring the box up and down without root.

What it does: say what state the box is in (`tailscale status --json`),
join (`tailscale up --login-server … --authkey … --hostname cloud`), leave
(`tailscale down`), and read the box's mesh address, which the control
server is told so `<name>.<zone>` points at the box inside the mesh.

Keys and pairing codes for people's devices are not the box's business
with tailscale: they are minted at the control server, labelled with who
asked for which device, and handed to the person (`access_ways`).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass

# The name the box has in the mesh. One per cloud: each cloud is its own
# Headscale user, so "cloud" never collides with another cloud's box.
BOX_HOSTNAME = "cloud"
TIMEOUT = 60


class MeshError(RuntimeError):
    """tailscale is missing, or said no. The message is what to do about it."""


@dataclass(slots=True)
class MeshStatus:
    installed: bool = False
    # tailscale's BackendState: NoState, NeedsLogin, NeedsMachineAuth,
    # Stopped, Starting, Running — or "" when it could not be asked.
    state: str = ""
    address: str = ""
    hostname: str = ""
    error: str = ""

    @property
    def running(self) -> bool:
        return self.state == "Running"

    def as_dict(self) -> dict:
        return {
            "installed": self.installed,
            "state": self.state,
            "address": self.address,
            "hostname": self.hostname,
            "error": self.error,
        }


class Mesh:
    """The box's tailscale, through its CLI."""

    def __init__(self, binary: str = "tailscale") -> None:
        self.binary = binary

    def path(self) -> str | None:
        return shutil.which(self.binary)

    def _run(self, *args: str, timeout: float = TIMEOUT) -> subprocess.CompletedProcess:
        path = self.path()
        if path is None:
            raise MeshError(
                "tailscale is not installed on this box; the server installer adds it "
                "with --private (sudo sh install-server.sh --private)"
            )
        try:
            return subprocess.run(
                [path, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "TS_NO_LOGS": "1"},
            )
        except subprocess.TimeoutExpired as exc:
            raise MeshError(f"tailscale {args[0]} did not finish in {int(timeout)} seconds") from exc
        except OSError as exc:
            raise MeshError(f"cannot run tailscale: {exc}") from exc

    def status(self) -> MeshStatus:
        if self.path() is None:
            return MeshStatus(installed=False)
        try:
            result = self._run("status", "--json", timeout=15)
        except MeshError as exc:
            return MeshStatus(installed=True, error=str(exc))
        try:
            data = json.loads(result.stdout or "{}")
        except ValueError:
            return MeshStatus(installed=True, error=_last_line(result.stderr) or "no answer")
        me = data.get("Self") or {}
        addresses = [a for a in (me.get("TailscaleIPs") or data.get("TailscaleIPs") or []) if a]
        # IPv4 first: it is what DNS extra records and people read most easily.
        addresses.sort(key=lambda a: ":" in a)
        return MeshStatus(
            installed=True,
            state=str(data.get("BackendState") or ""),
            address=addresses[0] if addresses and data.get("BackendState") == "Running" else "",
            hostname=str(me.get("HostName") or ""),
            error="" if result.returncode == 0 else _last_line(result.stderr),
        )

    def up(self, login_server: str, authkey: str = "", hostname: str = BOX_HOSTNAME) -> MeshStatus:
        """Join the mesh. Without *authkey*, only a box that is already registered comes back up."""
        # --reset, so a box that was on some other tailnet with other flags
        # is not refused for not repeating them; and --operator, because
        # --reset would otherwise take the service's right to do this again.
        args = ["up", "--login-server", login_server, "--hostname", hostname, "--reset"]
        operator = operator_name()
        if operator:
            args += ["--operator", operator]
        if authkey:
            args += ["--authkey", authkey]
        result = self._run(*args)
        if result.returncode != 0:
            detail = _last_line(result.stderr) or _last_line(result.stdout)
            if "access denied" in detail.lower() or "permission" in detail.lower():
                detail += (
                    " — the service is not tailscale's operator yet: "
                    "sudo tailscale set --operator=cloudmorrow"
                )
            raise MeshError(f"tailscale up failed: {detail}")
        return self.status()

    def down(self) -> None:
        result = self._run("down", timeout=30)
        if result.returncode != 0:
            raise MeshError(f"tailscale down failed: {_last_line(result.stderr)}")


def operator_name() -> str:
    """Who runs this, when it is not root: the user tailscale should let do it again."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return ""
    try:
        import pwd

        return pwd.getpwuid(os.geteuid()).pw_name
    except (ImportError, KeyError):
        return ""


def _last_line(text: str | None) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""


def owner_of(device: dict) -> str:
    """Whose device this is: the `owner` the key was minted with, else the label's prefix.

    Keys and codes are labelled `"<username>: <device>"` and carry `owner`
    as well; a control server that keeps only `for` still says whose it is.
    """
    owner = str(device.get("owner") or "")
    if owner:
        return owner
    label = str(device.get("for") or "")
    head, sep, _ = label.partition(": ")
    return head if sep else ""


def label_for(username: str, device: str) -> str:
    device = " ".join((device or "").split())[:60] or "a device"
    return f"{username}: {device}"
