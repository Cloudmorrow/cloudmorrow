"""Webhooks without code: a JSON body read into a record, and the checks at the door.

A Quill's `[[webhooks]]` table either forwards the request to one of its
services or, far more often, says which fields of which datamodel the body
fills:

    [[webhooks]]
    id = "stripe"
    path = "stripe"
    model = "payment"
    map = { amount = "$.data.object.amount", customer = "$.data.object.customer" }

The paths in `map` are a deliberately small subset of JSONPath — `$`, then
`.name` and `[n]` steps, and `["odd name"]` for a key a dot cannot spell —
read by the few lines below rather than by a library, because a webhook
body is somebody else's input and a path language with filters and
expressions is a program run on it. A path that finds nothing leaves the
field out; the datamodel's own rules decide whether that is fine.

The door itself: every webhook has a secret the core made, sent back as
`?token=` or `X-Cloudmorrow-Webhook-Token`, or — when the manifest names a
`signature` header, the way GitHub signs its deliveries — an HMAC-SHA256 of
the body under that secret. A body has a size cap, and each webhook a rate
it is answered at, so one noisy sender cannot fill the store.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import threading
import time
from collections import deque

__all__ = [
    "MAX_BODY",
    "PathError",
    "RateLimit",
    "apply_map",
    "parse_path",
    "resolve",
    "signature_ok",
]

# A webhook's body: an event, not an upload.
MAX_BODY = 1024 * 1024

_STEP_RE = re.compile(
    r"""\.(?P<name>[A-Za-z_][A-Za-z0-9_-]*)      # .name
      | \[(?P<index>-?\d+)\]                    # [0]
      | \[\s*"(?P<quoted>[^"\\]*)"\s*\]         # ["odd name"]
    """,
    re.VERBOSE,
)


class PathError(ValueError):
    """A map path that is not in the subset this reads."""


def parse_path(text: str) -> tuple[str | int, ...]:
    """`$.a.b[0].c` as its steps: ("a", "b", 0, "c")."""
    if not isinstance(text, str) or not text.startswith("$"):
        raise PathError(f"{text!r} is a path from the body's root: $.field, $.list[0]")
    steps: list[str | int] = []
    at = 1
    while at < len(text):
        match = _STEP_RE.match(text, at)
        if match is None:
            raise PathError(f"{text!r}: only .name, [n] and [\"name\"] steps, from $")
        if match.group("name") is not None:
            steps.append(match.group("name"))
        elif match.group("index") is not None:
            steps.append(int(match.group("index")))
        else:
            steps.append(match.group("quoted"))
        at = match.end()
    return tuple(steps)


_MISSING = object()


def resolve(body: object, steps: tuple[str | int, ...]) -> object:
    """What *steps* reach in *body*, or `_MISSING`."""
    here = body
    for step in steps:
        if isinstance(step, int):
            if not isinstance(here, list) or not -len(here) <= step < len(here):
                return _MISSING
            here = here[step]
        else:
            if not isinstance(here, dict) or step not in here:
                return _MISSING
            here = here[step]
    return here


def apply_map(body: object, mapping: dict[str, str]) -> dict:
    """The fields a record gets from *body*: each field whose path found something."""
    fields: dict = {}
    for name, path in mapping.items():
        value = resolve(body, parse_path(path))
        if value is not _MISSING:
            fields[name] = value
    return fields


def signature_ok(secret: str, body: bytes, sent: str | None) -> bool:
    """Is *sent* the HMAC-SHA256 of *body* under *secret*, as GitHub writes it?

    `sha256=<hex>`, or the bare hex some senders use. Compared in constant
    time, like every secret here.
    """
    if not sent:
        return False
    sent = sent.strip()
    if sent.lower().startswith("sha256="):
        sent = sent[len("sha256="):]
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sent.lower())


class RateLimit:
    """At most *limit* calls per *window* seconds, per key: a sliding window.

    Kept in memory, so a restart forgets it, which is fine for what it is:
    a brake on a sender that has gone wrong, not an accounting.
    """

    def __init__(self, limit: int = 120, window: float = 60.0) -> None:
        self.limit = limit
        self.window = window
        self._seen: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            seen = self._seen.setdefault(key, deque())
            while seen and now - seen[0] > self.window:
                seen.popleft()
            if len(seen) >= self.limit:
                return False
            seen.append(now)
            return True
