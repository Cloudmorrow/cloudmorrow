"""The home network: the box says where it is, so nobody has to type an address.

Multicast DNS, which every phone and computer already speaks: the box
answers to `<name>.local` (the cloud's name made into a hostname, or
`cloudmorrow.local` before it has one) and announces a service,
`_cloudmorrow._tcp`, whose TXT record carries what a client needs to pick
it from a list:

    name     what the cloud is called ("The Larsens")
    version  the server's version
    url      what to open on this network — https://<its real name> when it
             has a public or private name, else http://<name>.local:<port>
    public   its public name, when public access is on
    private  its private name, when private access is on

With a real name the service's port is 443, where Caddy answers with the
certificate for that name, so a client on the same network connects to
the box's local address and still checks the certificate against the real
name (`client/discover.py`). Without one it is the server's own port, and
plain http, which is only for setting the box up and finding it.

A box whose server listens only on loopback and has no real name has
nothing to offer the network, so it says nothing. `access_lan = false`
turns it off entirely.

python-zeroconf is pure Python and needs no daemon; it shares port 5353
with Avahi where Avahi is running. It runs on its own thread (registering
blocks for the announcements) and is imported only when used, so a server
without it installed simply does not announce.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

log = logging.getLogger("cloudmorrow.access.lan")

SERVICE_TYPE = "_cloudmorrow._tcp.local."
DEFAULT_LABEL = "cloudmorrow"
# The mesh's addresses (CGNAT space, which Tailscale uses) and link-local
# ones are no use to a device on the same network.
_SKIP = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
)


def hostname_label(name: str) -> str:
    """"The Larsens" → `the-larsens`: a DNS label, at most 63 characters."""
    label = re.sub(r"[^a-z0-9-]+", "-", name.strip().lower()).strip("-")
    label = re.sub(r"-{2,}", "-", label)[:63].strip("-")
    return label or DEFAULT_LABEL


@dataclass(slots=True)
class Announcement:
    """What the box says about itself on the network."""

    label: str
    name: str
    version: str
    port: int
    url: str
    public: str = ""
    private: str = ""
    addresses: list[str] = field(default_factory=list)

    def properties(self) -> dict[str, str]:
        props = {"name": self.name, "version": self.version, "url": self.url}
        if self.public:
            props["public"] = self.public
        if self.private:
            props["private"] = self.private
        return props


def local_addresses() -> list[str]:
    """This box's IPv4 addresses a neighbour could reach it on."""
    found: list[str] = []
    try:
        import ifaddr

        for adapter in ifaddr.get_adapters():
            for ip in adapter.ips:
                if isinstance(ip.ip, str):
                    found.append(ip.ip)
    except ImportError:  # pragma: no cover - zeroconf brings ifaddr
        try:
            found = [info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
        except OSError:
            found = []
    usable = []
    for value in found:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if any(address in net for net in _SKIP) or value in usable:
            continue
        usable.append(value)
    return usable


class LanAnnouncer:
    """Announces the box with python-zeroconf, and changes what it says when asked.

    *describe* is called for the announcement each time: it reads the
    cloud's name and access state, which change while the server runs.
    None from it means "say nothing now".
    """

    def __init__(
        self,
        describe: Callable[[], Announcement | None],
        zeroconf_factory: Callable[[], object] | None = None,
    ) -> None:
        self.describe = describe
        self.zeroconf_factory = zeroconf_factory
        self._zc = None
        self._info = None
        self._lock = threading.Lock()
        self.error = ""
        self.announced: Announcement | None = None

    def start(self) -> None:
        threading.Thread(target=self.refresh, name="access-lan", daemon=True).start()

    def status(self) -> dict:
        current = self.announced
        return {
            "on": current is not None,
            "hostname": f"{current.label}.local" if current else "",
            "url": current.url if current else "",
            "addresses": list(current.addresses) if current else [],
            "error": self.error,
        }

    def refresh(self) -> None:
        """Announce what `describe` says now: register, update, or withdraw."""
        with self._lock:
            try:
                self._refresh()
            except Exception as exc:  # the network is not ours to crash on
                log.warning("could not announce on the local network: %s", exc)
                self.error = str(exc)

    def _refresh(self) -> None:
        wanted = self.describe()
        if wanted is None or not wanted.addresses:
            self._withdraw()
            return
        from zeroconf import ServiceInfo

        info = ServiceInfo(
            SERVICE_TYPE,
            f"{wanted.label}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(a) for a in wanted.addresses],
            port=wanted.port,
            properties=wanted.properties(),
            server=f"{wanted.label}.local.",
        )
        if self._zc is None:
            if self.zeroconf_factory is not None:
                self._zc = self.zeroconf_factory()
            else:
                from zeroconf import Zeroconf

                self._zc = Zeroconf()
        if self._info is not None and self._info.name == info.name:
            self._zc.update_service(info)
        else:
            if self._info is not None:
                self._zc.unregister_service(self._info)
            # A second box on the network with the same name gets a number.
            self._zc.register_service(info, allow_name_change=True)
        self._info = info
        self.announced = wanted
        self.error = ""
        log.info("announced %s on the local network at %s", wanted.label, ", ".join(wanted.addresses))

    def _withdraw(self) -> None:
        if self._zc is not None and self._info is not None:
            self._zc.unregister_service(self._info)
        self._info = None
        self.announced = None

    def stop(self) -> None:
        with self._lock:
            try:
                self._withdraw()
                if self._zc is not None:
                    self._zc.close()
            except Exception:  # shutting down; nothing to be done
                pass
            self._zc = None
