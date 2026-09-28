"""What the client and the agent both do when they talk to a server.

The client is async and the agent is not, so they stay two classes. What
they share is everything around a call: the address they refuse before
they make one, the words for a server that cannot be reached, and how an
answer that went wrong is read — the server's `detail`, or its body when
it has none. Each raises its own subclass of ServerError, so a caller
catches the one it knows about.
"""

from __future__ import annotations

from typing import Any, Self

import httpx

from cloudmorrow.transport import InsecureUrlError, check_url


class ServerError(RuntimeError):
    """The server said no, or could not be asked."""

    def __init__(
        self, message: str, *, status_code: int | None = None, payload: Any = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        # The server's own body, for the callers that act on what is in it —
        # a stale push is told the revision it should have been working from.
        self.payload = payload

    @classmethod
    def unreachable(cls, url: str, exc: Exception) -> Self:
        return cls(f"cannot reach {url}: {exc}")

    @classmethod
    def refuse_insecure(cls, url: str, *, allow_insecure: bool) -> None:
        """check_url, raising this kind of error instead of InsecureUrlError."""
        try:
            check_url(url, allow_insecure=allow_insecure)
        except InsecureUrlError as exc:
            raise cls(str(exc)) from exc


def detail(response: httpx.Response) -> Any:
    """What a failed answer says: its `detail`, its JSON, or its text."""
    try:
        payload = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"
    if isinstance(payload, dict) and "detail" in payload:
        return payload["detail"]
    return payload
