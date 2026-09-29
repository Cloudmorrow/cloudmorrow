"""Finding clouds on the home network, so nobody has to type an address.

A box announces itself with multicast DNS as `_cloudmorrow._tcp`
(server/access_lan.py), and its TXT record says what it is called, its
version, the address to open, and its mesh name when it is linked to a
cloudmorrow.com account. `browse()` listens for a couple of seconds and returns what answered.

What a client does with one:

* a linked cloud is `https://<its mesh name>`,
  and its local address — the address it answered from, on 443 — is kept
  as `local_address`, so at home the client goes straight to the box while
  still checking the certificate against the real name (localroute.py);
* a cloud that is not linked is its plain `http://<name>.local:<port>`
  address, which is for a home that wants no more: the person picking it
  from the list is the person saying so.

python-zeroconf is imported only here and only when browsing, so a client
without it simply finds nothing and asks for an address, as it always did.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

SERVICE_TYPE = "_cloudmorrow._tcp.local."
BROWSE_SECONDS = 2.0


@dataclass(slots=True)
class Found:
    """One cloud that answered on the network."""

    name: str
    url: str
    version: str = ""
    mesh: str = ""
    addresses: list[str] = field(default_factory=list)
    port: int = 0
    service: str = ""

    @property
    def host(self) -> str:
        """Its real name, when it is linked: `larsens.cloudmorrow.tech`."""
        return self.mesh

    @property
    def api_url(self) -> str:
        return f"https://{self.host}" if self.host else self.url.rstrip("/")

    @property
    def local_address(self) -> str:
        """Where it is on this network, for a cloud with a real name; else nothing."""
        if not self.host or not self.addresses:
            return ""
        return f"{self.addresses[0]}:{self.port or 443}"

    @property
    def plain(self) -> bool:
        return self.api_url.startswith("http://")

    def describe(self) -> str:
        where = f"at {self.addresses[0]}" if self.addresses else ""
        extra = "linked, and on its mesh" if self.mesh else "home network only"
        return f"{self.name}  {self.api_url}  ({extra}{', ' + where if where else ''})"


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return "" if value is None else str(value)


def found_from_info(info: Any) -> Found | None:
    """A Found from a zeroconf ServiceInfo (or anything shaped like one)."""
    props = {_text(k): _text(v) for k, v in (getattr(info, "properties", None) or {}).items()}
    try:
        addresses = list(info.parsed_addresses())
    except Exception:
        addresses = []
    addresses = [a for a in addresses if ":" not in a] or addresses
    service = _text(getattr(info, "name", ""))
    name = props.get("name") or service.split(".", 1)[0]
    url = props.get("url", "")
    if not url and not props.get("mesh"):
        return None
    return Found(
        name=name,
        url=url,
        version=props.get("version", ""),
        mesh=props.get("mesh", ""),
        addresses=addresses,
        port=int(getattr(info, "port", 0) or 0),
        service=service,
    )


def _zeroconf_infos(seconds: float) -> Iterable[Any]:
    try:
        from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf
    except ImportError:
        return []
    names: set[str] = set()
    lock = threading.Lock()

    def changed(zeroconf, service_type, name, state_change) -> None:
        if state_change is ServiceStateChange.Added:
            with lock:
                names.add(name)

    zc = Zeroconf()
    try:
        browser = ServiceBrowser(zc, SERVICE_TYPE, handlers=[changed])
        time.sleep(seconds)
        browser.cancel()
        infos = []
        for name in sorted(names):
            info = zc.get_service_info(SERVICE_TYPE, name, timeout=1500)
            if info is not None:
                infos.append(info)
        return infos
    finally:
        zc.close()


def browse(
    seconds: float = BROWSE_SECONDS,
    infos: Callable[[float], Iterable[Any]] | None = None,
) -> list[Found]:
    """The clouds that answer on this network within *seconds*, by name."""
    try:
        answered = list((infos or _zeroconf_infos)(seconds))
    except OSError:
        # No multicast here (a container, a VPN that took the route): nothing found.
        return []
    found = [f for f in (found_from_info(info) for info in answered) if f is not None]
    return sorted(found, key=lambda f: f.name.lower())


def matching(found: list[Found], api_url: str) -> Found | None:
    """The one among *found* that is the cloud at *api_url*, by its real name."""
    from urllib.parse import urlsplit

    host = (urlsplit(api_url).hostname or "").lower()
    return next((f for f in found if f.host and f.host.lower() == host), None)
