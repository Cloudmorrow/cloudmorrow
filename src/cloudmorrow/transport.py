"""Whether an address is one to send a password over.

Everything Cloudmorrow sends — passwords, tokens, notes, chat — is meant to
cross the wire under TLS. A client refuses a plain `http://` server address
unless one of two things is true: the address is this machine, where the
wire is a loopback and there is nothing to intercept; or the person has
said, in their config, that this box is meant to be plain, which is a
decision they are allowed to make on purpose but not by accident.

Shared by the TUI/CLI client and the agent, so they refuse the same things
for the same reasons.
"""

from __future__ import annotations

from urllib.parse import urlsplit

__all__ = ["InsecureUrlError", "check_url", "is_local_url"]

# This machine — and the name Starlette's test client answers to, which is
# a server in the same process and no wire at all.
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]", "testserver"}


class InsecureUrlError(ValueError):
    """A plain http:// address to somewhere other than this machine."""

    def __init__(self, url: str) -> None:
        super().__init__(
            f"{url} is plain http: your password and everything else would cross the"
            " network unencrypted. Use https, or set allow_insecure_http = true in the"
            " config if this box is meant to be reached in the clear."
        )
        self.url = url


def is_local_url(url: str) -> bool:
    """True for an address on this machine, where plain http hurts nobody."""
    host = (urlsplit(url).hostname or "").lower()
    return host in LOCAL_HOSTS or host.endswith(".localhost")


def check_url(url: str, *, allow_insecure: bool = False) -> str:
    """Return *url* if it is one to talk to; raise InsecureUrlError otherwise."""
    scheme = urlsplit(url).scheme.lower()
    # No address at all is a client with its transport mounted by hand — a
    # test, or something in-process — which crosses no wire either.
    if not url or scheme == "https" or allow_insecure or is_local_url(url):
        return url
    raise InsecureUrlError(url)
