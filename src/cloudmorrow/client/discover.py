"""Finding clouds on the home network, so nobody has to type an address.

A box announces itself with multicast DNS as `_cloudmorrow._tcp`
(server/access_lan.py), and its TXT record says what it is called, its
version and the address to open. `browse()` listens for a couple of seconds
and returns what answered; `cm login` with no server lists them.

An address that is plain http (`http://<name>.local:<port>`) is for a home
network that wants no more: the person picking it from the list is the
person saying so.

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
    addresses: list[str] = field(default_factory=list)
    port: int = 0
    service: str = ""

    @property
    def api_url(self) -> str:
        return self.url.rstrip("/")

    @property
    def plain(self) -> bool:
        return self.api_url.startswith("http://")

    def describe(self) -> str:
        where = f"  (at {self.addresses[0]})" if self.addresses else ""
        return f"{self.name}  {self.api_url}{where}"


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
    if not url:
        return None
    return Found(
        name=name,
        url=url,
        version=props.get("version", ""),
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
