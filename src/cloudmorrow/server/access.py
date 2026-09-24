"""Restricting which hosts the API answers at all.

On a box that also serves SMB and ssh, a host firewall is a blunt instrument.
This is the narrow version: refuse HTTP from anywhere but the reverse proxy.

It matches the real TCP peer, never X-Forwarded-For — that header is set by
whoever is talking to us, so trusting it would defeat the point.
"""

from __future__ import annotations

from ipaddress import ip_address, ip_network
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters for typing
    from ipaddress import IPv4Network, IPv6Network


class InvalidClientRule(ValueError):
    pass


def parse_rules(values: list[str]) -> list[IPv4Network | IPv6Network]:
    """Turn config entries into networks. A bare address becomes a /32 or /128."""
    networks = []
    for raw in values:
        entry = str(raw).strip()
        if not entry:
            continue
        try:
            networks.append(ip_network(entry, strict=False))
        except ValueError as exc:
            raise InvalidClientRule(
                f"{entry!r} is not an IP address or CIDR range"
            ) from exc
    return networks


def is_allowed(client_host: str | None, networks: list[IPv4Network | IPv6Network]) -> bool:
    """True when *client_host* is covered by one of *networks*.

    An empty rule list allows everything, which is the default. An address we
    cannot parse is refused: better a visible 403 than a silent hole.
    """
    if not networks:
        return True
    if not client_host:
        return False
    try:
        address = ip_address(client_host)
    except ValueError:
        return False
    return any(address in network for network in networks)
