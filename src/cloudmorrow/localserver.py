"""The server on this machine, when the installer put one here.

The terminal app is on the server too: an administrator at the box runs
`cm`, signs in with their own name and password, and has Administration,
as on any other machine. For that it has to know where the server is,
and the answer is beside it, in the server's own config: the addresses
it was told to answer on. So a client on the same box with no config of
its own reads the address off `/etc/cloudmorrow/server.toml`, and reaches
the server at whichever of them a process here can — loopback when it
listens there or everywhere, else the first address it names — whatever
the box is called from outside and whether or not a proxy sits in front.

A plain http address that is one the server here listens on is this
machine, where the wire is a loopback and there is nothing to intercept,
so transport.py counts it as local. And a machine that runs the server
has an agent already, the server's own, so signing in here enrols no
second one.

Nothing here imports the server: the client is installed on machines
that have no server package, and the two keys this reads, `host` and
`port`, are the two in server.toml that have never changed.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

# Where install-server.sh writes the server's config. CLOUDMORROW_SERVER_CONFIG
# names another, as it does for the server itself and its unit.
CONFIG_PATH = Path("/etc/cloudmorrow/server.toml")

LOOPBACK = ("127.0.0.1", "::1", "localhost")
WILDCARD = ("0.0.0.0", "::")


def config_path() -> Path:
    """Where the server here keeps its config, whether or not there is one."""
    override = os.environ.get("CLOUDMORROW_SERVER_CONFIG")
    return Path(override).expanduser() if override else CONFIG_PATH


def listening() -> tuple[list[str], int] | None:
    """The addresses the server here answers on, and its port; None without a server here."""
    try:
        data = tomllib.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    section = data.get("server", data)
    if not isinstance(section, dict):
        return None
    try:
        port = int(section.get("port", 8787))
    except (TypeError, ValueError):
        return None
    hosts = [h.strip() for h in str(section.get("host", "0.0.0.0")).split(",") if h.strip()]
    return (hosts or ["0.0.0.0"]), port


def is_here() -> bool:
    """Whether this machine runs a server: the installer left its config here."""
    return listening() is not None


def url() -> str:
    """How a process on this machine reaches the server here, or "" without one.

    The same choice the server makes for its own processes
    (server/quills/services.py, loopback_url): loopback when it listens
    there or everywhere, else the first address it names.
    """
    found = listening()
    if found is None:
        return ""
    hosts, port = found
    host = next((h for h in hosts if h in LOOPBACK), hosts[0])
    if host in WILDCARD or host == "localhost":
        host = "127.0.0.1"
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{port}"


def public_url() -> str:
    """The address other machines reach the server here on, when its config names one.

    For what the terminal app shows a person adding a device: signed in
    at the box over loopback, the address to hand a phone is not that one.
    """
    try:
        data = tomllib.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return ""
    section = data.get("server", data)
    if not isinstance(section, dict):
        return ""
    return str(section.get("public_url") or "").rstrip("/")


def answers_on(address: str) -> bool:
    """Whether *address* is where the server here listens: this machine, then, whatever it is called.

    Not a wildcard, which says nothing about which addresses are this
    machine's; and the port has to be the server's, so an address that
    merely shares a host with it is not taken for it.
    """
    found = listening()
    if found is None:
        return False
    hosts, port = found
    parts = urlsplit(address)
    host = (parts.hostname or "").lower()
    try:
        asked = parts.port or 80
    except ValueError:
        return False
    return asked == port and any(h.lower() == host for h in hosts if h not in WILDCARD)
