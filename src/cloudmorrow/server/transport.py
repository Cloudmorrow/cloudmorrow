"""In transit: the server insists on TLS.

TLS is terminated by the reverse proxy in front of the server — Caddy or
nginx — and the server itself listens on plain HTTP behind it. That is the
usual arrangement, and the hole in it is that anything reaching the plain
port directly, or a proxy relaying a plain request, is answered as if it
had come over TLS. This middleware closes it.

With `require_tls` on (the default when the public URL is https), a request
whose scheme is not https is refused with 426 Upgrade Required — unless it
comes from this machine without a proxy header, which is a local check or a
test, and crosses no wire. The scheme is what uvicorn's proxy-header
handling says it is: `X-Forwarded-Proto` from a trusted proxy, else the
socket's own. Every https answer also carries HSTS, so a browser that has
seen the app once never tries plain http again.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from cloudmorrow.server.config import ServerConfig

__all__ = ["HSTS", "install"]

HSTS = "max-age=31536000; includeSubDomains"
# What a call from this machine looks like: the loopback addresses, and the
# name Starlette's test client gives itself.
LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient", None}


def _is_local(request: Request) -> bool:
    host = request.client.host if request.client else None
    return host in LOCAL_CLIENTS and "x-forwarded-proto" not in request.headers


def install(app: FastAPI, config: ServerConfig) -> None:
    if not config.tls_required:
        return

    @app.middleware("http")
    async def require_tls(request: Request, call_next):
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
