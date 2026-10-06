"""A brake on guessing passwords: failed sign-ins, counted and limited.

A cloud's sign-in page may well be on the internet, so somebody can try
passwords against it for as long as they like. Failures are counted per
visitor address and per account, in a sliding window each; past either
limit, sign-in answers 429 with `Retry-After` for that address or that
account until the oldest failure in the window has aged out. A right
password does not get through a limit either, or the limit would tell a
guesser when they had it.

The address is the one the server sees: the visitor's own through the
reverse proxy, which puts it in X-Forwarded-For, and uvicorn believes that
header only from the box's loopback. Kept in memory: a restart forgets it,
which costs a guesser nothing they could not get from waiting.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable

# (failures, window in seconds)
PER_ADDRESS = (10, 15 * 60)
PER_ACCOUNT = (20, 60 * 60)


class SigninLimits:
    def __init__(
        self,
        per_address: tuple[int, float] = PER_ADDRESS,
        per_account: tuple[int, float] = PER_ACCOUNT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.per_address = per_address
        self.per_account = per_account
        self.clock = clock
        self._failed: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _wait(self, key: str, limit: tuple[int, float], now: float) -> float:
        count, window = limit
        seen = self._failed.get(key)
        if not seen:
            return 0.0
        while seen and now - seen[0] >= window:
            seen.popleft()
        if not seen:
            del self._failed[key]
            return 0.0
        if len(seen) < count:
            return 0.0
        return seen[0] + window - now

    def retry_after(self, address: str | None, username: str) -> int:
        """Seconds until this address may try this account again; 0 when it may now.

        None for an address the caller cannot know (WebDAV, behind WSGI):
        then only the account's limit applies.
        """
        now = self.clock()
        with self._lock:
            wait = self._wait(f"account:{username.lower()}", self.per_account, now)
            if address is not None:
                wait = max(wait, self._wait(f"address:{address}", self.per_address, now))
        return math.ceil(wait) if wait > 0 else 0

    def failed(self, address: str | None, username: str) -> None:
        now = self.clock()
        keys = [f"account:{username.lower()}"]
        if address is not None:
            keys.append(f"address:{address}")
        with self._lock:
            for key in keys:
                self._failed.setdefault(key, deque()).append(now)
