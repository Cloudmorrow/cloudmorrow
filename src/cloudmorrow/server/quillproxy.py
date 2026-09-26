"""Handing a request to a Quill's service on its loopback port, and its answer back.

What `/api/q/<quill>/…` and a forwarding webhook do. The standard library's
`http.client` rather than httpx, which the server does not depend on: it
connects to one port on 127.0.0.1, sends the request as it came minus what
is the core's business, and gives back a status, headers and the body as a
stream read in the threadpool, so a large answer is never held whole.

What never reaches the service: the caller's `Authorization` and cookies —
a person's token is theirs, not the Quill's — and the hop-by-hop headers.
What the core adds instead, and a service may trust because only the core
can reach its port from outside: `X-Cloudmorrow-User` (who is asking) or
`X-Cloudmorrow-Quill` (the Quill itself, calling its own API).
"""

from __future__ import annotations

import http.client
import time
from collections.abc import Iterator
from urllib.parse import urlencode

from fastapi import HTTPException, Request, status
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

__all__ = ["forward", "read_body"]

TIMEOUT = 30.0
# How long a refused connection is retried: a service still starting.
STARTING = 5.0
CHUNK = 64 * 1024
# An API call's body; a webhook has its own, smaller cap.
MAX_BODY = 10 * 1024 * 1024

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
    "trailer", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}
# Never passed on to the service, whoever sent them.
PRIVATE = {"authorization", "cookie", "x-cloudmorrow-webhook-token"}
# Set by the core alone: one sent from outside is dropped.
OURS = ("x-cloudmorrow-",)


async def read_body(request: Request, limit: int) -> bytes:
    """The request's body, refused with a 413 past *limit* bytes."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "the body is too big")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "the body is too big")
        chunks.append(chunk)
    return b"".join(chunks)


def _outgoing(request: Request, extra: dict[str, str]) -> dict[str, str]:
    headers = {
        name: value
        for name, value in request.headers.items()
        if name.lower() not in HOP_BY_HOP
        and name.lower() not in PRIVATE
        and not name.lower().startswith(OURS)
    }
    headers.update(extra)
    if request.client is not None:
        headers["X-Forwarded-For"] = request.client.host
    return headers


async def forward(
    request: Request,
    port: int,
    path: str,
    body: bytes,
    extra: dict[str, str],
    *,
    drop: tuple[str, ...] = (),
) -> StreamingResponse:
    """Send the request to 127.0.0.1:*port* at *path*, and stream the answer back.

    *drop* names query parameters that are the core's and stay here: a
    webhook's `token`.
    """
    query = urlencode([(k, v) for k, v in request.query_params.multi_items() if k not in drop])
    target = "/" + path.lstrip("/") + (f"?{query}" if query else "")
    headers = _outgoing(request, extra)

    def send() -> tuple[http.client.HTTPConnection, http.client.HTTPResponse]:
        # A service that has just started may not be listening yet: a refused
        # connection is tried again for a few seconds before it is an error.
        deadline = time.monotonic() + STARTING
        while True:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=TIMEOUT)
            try:
                conn.request(request.method, target, body=body or None, headers=headers)
                return conn, conn.getresponse()
            except ConnectionRefusedError:
                conn.close()
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
            except BaseException:
                conn.close()
                raise

    try:
        conn, answer = await run_in_threadpool(send)
    except (OSError, http.client.HTTPException) as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"the Quill's service did not answer: {exc}"
        ) from exc

    def stream() -> Iterator[bytes]:
        try:
            while True:
                chunk = answer.read(CHUNK)
                if not chunk:
                    break
                yield chunk
        finally:
            conn.close()

    back = {
        name: value
        for name, value in answer.getheaders()
        if name.lower() not in HOP_BY_HOP and name.lower() != "set-cookie"
    }
    return StreamingResponse(stream(), status_code=answer.status, headers=back)
