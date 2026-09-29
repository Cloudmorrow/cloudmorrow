"""The short way across the living room.

A linked cloud is `https://larsens.cloudmorrow.tech` wherever you are, and
from home that name leads over the mesh, or — for a device not on it — to
the relay's landing page: either way not the shortest road from the laptop
on the sofa to the box under the television. When the box has been found on the home network
(`client/discover.py`, which `cm login` records as `local_address`), the
client goes to it directly instead.

Directly, but not trustingly. The request still names the real host — the
`Host` header is the real name, and so is the TLS server name (httpcore's
`sni_hostname` request extension) — so Caddy on the box answers with the
certificate for that name, and the certificate is checked against that
name, exactly as it would be over the mesh. Another box on some other
network that happens to have the same address fails the check and is
never spoken to. Only where the connection goes is changed.

Whether to try is decided once per client: a quick connect to the local
address (a quarter of a second at most). Away from home that fails fast
and the real name is used, as it always was.
"""

from __future__ import annotations

import socket
import ssl
from urllib.parse import urlsplit

import httpx

# Long enough for a box on the same network, short enough not to be noticed
# on every command from a café.
PROBE_SECONDS = 0.25


def split_address(address: str, default_port: int = 443) -> tuple[str, int]:
    address = address.strip()
    if address.startswith("["):
        host, _, rest = address[1:].partition("]")
        return host, int(rest.lstrip(":") or default_port)
    if address.count(":") == 1:
        host, _, port = address.partition(":")
        return host, int(port or default_port)
    return address, default_port


def reachable(address: str, timeout: float = PROBE_SECONDS) -> bool:
    """Whether something answers at *address* ("ip:port") right now."""
    try:
        host, port = split_address(address)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


class LocalRoute(httpx.AsyncBaseTransport):
    """Sends requests for *host* to *address*, keeping the name for Host and TLS."""

    def __init__(self, inner: httpx.AsyncBaseTransport, host: str, address: str) -> None:
        self.inner = inner
        self.host = host.lower()
        self.ip, self.port = split_address(address)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host.lower() == self.host:
            # Host was set from the real URL when the request was built, and
            # stays; the server name for TLS is said explicitly.
            request.extensions = {**request.extensions, "sni_hostname": self.host}
            request.url = request.url.copy_with(host=self.ip, port=self.port)
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self.inner.aclose()


def local_transport(
    api_url: str,
    local_address: str,
    verify: bool | ssl.SSLContext = True,
    *,
    probe: bool = True,
) -> LocalRoute | None:
    """The route to use for *api_url*, or None to go the ordinary way."""
    parts = urlsplit(api_url)
    if not local_address or parts.scheme != "https" or not parts.hostname:
        return None
    if probe and not reachable(local_address):
        return None
    return LocalRoute(httpx.AsyncHTTPTransport(verify=verify), parts.hostname, local_address)
