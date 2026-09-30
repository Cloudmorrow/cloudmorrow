"""From anywhere: a visit the relay passed through, and the switch for it.

A linked cloud is reached from anywhere at `https://<name>.<zone>`: the
relay reads the name and passes the still-encrypted connection over the
mesh to port 8443 on the box, where Caddy ends TLS (docs/HOSTING.md, "From
anywhere"). Caddy's site marks every request with `Cloudmorrow-Way`:
`public` for one that came in on 8443, `home` for one on 443, from the home
network or the mesh, replacing whatever the request said.

The server needs no reason to believe the header, because it only ever
takes away: a request marked public cannot see the setup page. Forging it
hurts nobody but the forger, and a visitor from anywhere cannot remove it,
because Caddy writes it.

*Reachable from anywhere* is on by default once linked, and an
administrator turns it off in Administration → Access; then Caddy drops the
8443 site and the relay is told, so it shows its offline page instead.
"""

from __future__ import annotations

from fastapi import Request

from cloudmorrow.server.settings import SettingsStore

HEADER = "Cloudmorrow-Way"
PORT = 8443
SETTING = "access_public"


def from_anywhere(request: Request) -> bool:
    """Did this request come through the relay, from the internet?"""
    return request.headers.get(HEADER, "").strip().lower() == "public"


def reachable(settings: SettingsStore) -> bool:
    return settings.get(SETTING, "1") != "0"


def set_reachable(settings: SettingsStore, on: bool, *, changed_by: str = "") -> None:
    settings.set(SETTING, "1" if on else "0", changed_by=changed_by)
