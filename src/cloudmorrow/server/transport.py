"""In transit: the server insists on TLS.

TLS is terminated by the reverse proxy in front of the server — Caddy or
nginx — and the server itself listens on plain HTTP behind it. That is the
usual arrangement, and the hole in it is that anything reaching the plain
port directly, or a proxy relaying a plain request, is answered as if it
had come over TLS. This middleware closes it.

With `require_tls` on (the default when the public URL is https), a request
whose scheme is not https is refused with 426 Upgrade Required — unless it
came straight to the port, with no proxy header, from this machine or from
the local network: a browser on the LAN opening `http://<ip>:8787`, or a
local check. What that closes is the proxy relaying a plain request from
outside, and anything off the local network reaching the port. The scheme
is what uvicorn's proxy-header handling says it is: `X-Forwarded-Proto`
from a trusted proxy, else the socket's own. Every https answer also
carries HSTS, so a browser that has seen the app over https never tries
plain http on that name again.
"""

from __future__ import annotations

from ipaddress import ip_address, ip_network

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from cloudmorrow.server.config import ServerConfig

__all__ = ["HSTS", "install"]

HSTS = "max-age=31536000; includeSubDomains"
# What a call from this machine looks like: the loopback addresses, and the
# name Starlette's test client gives itself.
LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient", None}
# Carrier-grade NAT space (100.64.0.0/10) is not "private" to Python, but a
# VPN such as Tailscale hands it out, and then it is as local as the LAN.
SHARED = ip_network("100.64.0.0/10")


def _on_local_network(host: str | None) -> bool:
    if host in LOCAL_CLIENTS:
        return True
    try:
        address = ip_address(host or "")
    except ValueError:
        return False
    if address.version == 6 and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_private or address.is_link_local or address in SHARED


def _is_local(request: Request) -> bool:
    """Straight to the port from this machine or the LAN, not through a proxy."""
    host = request.client.host if request.client else None
    return _on_local_network(host) and "x-forwarded-proto" not in request.headers


def install(app: FastAPI, config: ServerConfig) -> None:
    @app.middleware("http")
    async def require_tls(request: Request, call_next):
        if not config.tls_required:
            return await call_next(request)
        if request.url.scheme != "https" and not _is_local(request):
            return JSONResponse(
                {"detail": "this server is reached over https only"},
                status_code=426,
                headers={"Upgrade": "TLS/1.2, HTTP/1.1", "Connection": "Upgrade"},
            )
        response = await call_next(request)
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = HSTS
        return response
