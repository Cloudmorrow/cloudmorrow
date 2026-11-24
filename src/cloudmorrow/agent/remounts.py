"""Bringing the shares back: what was mounted here is mounted again.

A mount — rclone's on Linux, Finder's on a Mac — ends with the machine. The
shares this machine mounted are written down in `mounts.json` (client/mounts.py)
until `share unmount` takes one off, so after a restart the agent, which comes
up with the machine, mounts each of them again, signed in as the person the
client is signed in as. It looks each tick, so a share that drops while the
machine is up (the network went, rclone was killed) comes back too.

One that will not come back is said in the log and tried again a few minutes
later, not every tick. Signed out, nothing is tried: the mount would sign in
with the stored token, and there is none.
"""

from __future__ import annotations

import datetime as dt
import logging
import time

from cloudmorrow.client import mounts
from cloudmorrow.client.config import StoredCredentials

log = logging.getLogger("cloudmorrow.agent")

# After a share would not mount, leave it this long before the next try.
RETRY_SECONDS = 300


def _expired(credentials: StoredCredentials) -> bool:
    if not credentials.expires_at:
        return False
    try:
        until = dt.datetime.fromisoformat(credentials.expires_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if until.tzinfo is None:
        until = until.replace(tzinfo=dt.UTC)
    return until <= dt.datetime.now(tz=dt.UTC)


class Remounts:
    def __init__(self, clock=time.monotonic) -> None:
        self.clock = clock
        # Share name → when it may be tried again.
        self._waiting: dict[str, float] = {}

    def tick(self) -> list[str]:
        """Mount again what is written down and not mounted. Returns the names mounted."""
        if not mounts.all_mounts():
            return []
        credentials = StoredCredentials.load()
        if credentials is None or not credentials.access_token or _expired(credentials):
            return []
        now = self.clock()
        skip = {name for name, until in self._waiting.items() if until > now}
        back = []
        for name, outcome in mounts.restore(credentials.username, credentials.access_token, skip=skip).items():
            if isinstance(outcome, mounts.MountError):
                log.warning("share %s did not mount again: %s", name, outcome)
                self._waiting[name] = now + RETRY_SECONDS
                continue
            self._waiting.pop(name, None)
            log.info("mounted share %s again at %s", name, outcome.path)
            back.append(name)
        return back
