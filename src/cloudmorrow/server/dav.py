"""The server's fileshares over WebDAV, at `/dav/<share>/`.

WebDAV rather than a filesystem of our own, because every machine already has
a client for it: macOS mounts a WebDAV URL from Finder with nothing
installed, and on Linux `rclone mount` does the same on top of FUSE. The
alternative — a FUSE driver of our own talking to a private API — would be
more code on the end that is hardest to debug, for a mount that behaves
worse than the one the OS ships.

The protocol and the provider live in `cloudmorrow.webdav`, shared with the
agent, which serves the shares on its own machine the same way. What is the
server's alone is here: the credential check, against its accounts, and
which shares it serves — the ones on the server, since a machine share is
served by the machine.

The whole thing is a WSGI app; `create_app` mounts it at `/dav`.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable

from wsgidav.wsgidav_app import WsgiDAVApp

from cloudmorrow.server.db import UserStore
from cloudmorrow.server.security import TokenError, decode_access_token, verify_password
from cloudmorrow.server.shares import DRIVE_NAME, SERVER, Share, ShareStore
from cloudmorrow.webdav import MOUNT_PATH, build_app

__all__ = ["MOUNT_PATH", "CredentialCheck", "ServerShares", "build_dav_app"]

# A password check is argon2, which is deliberately slow, and a mount sends
# the same credentials with every request — dozens a second while Finder is
# looking around. A password that just verified is trusted again for this long
# without hashing it again. Tokens are cheap to check and are not cached.
PASSWORD_CACHE_SECONDS = 600
PASSWORD_CACHE_MAX = 256


class CredentialCheck:
    """Is this the account's password, or a token it was issued?"""

    def __init__(self, users: UserStore, secret_key: str) -> None:
        self._users = users
        self._secret_key = secret_key
        self._cache: dict[tuple[str, str], tuple[str, float]] = {}
        self._lock = threading.Lock()

    def __call__(self, username: str, password: str) -> bool:
        user = self._users.get(username)
        if user is None or not user.is_active or not password:
            return False
        try:
            if decode_access_token(password, self._secret_key) == user.username:
                return True
        except TokenError:
            pass
        key = (user.username, hashlib.sha256(password.encode("utf-8")).hexdigest())
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            # Still the same hash on file: a changed password empties its cache.
            if cached and cached[0] == user.password_hash and cached[1] > now:
                return True
        if not verify_password(password, user.password_hash):
            return False
        with self._lock:
            if len(self._cache) >= PASSWORD_CACHE_MAX:
                self._cache.clear()
            self._cache[key] = (user.password_hash, now + PASSWORD_CACHE_SECONDS)
        return True


class ServerShares:
    """The shares this server serves: the caller's own drive, then their
    shares — only those on the server.

    *drive_for* gives an account its drive (`cloudmorrow.server.drive`); it
    is listed first and answers to its own name, whatever the shares table
    holds.
    """

    def __init__(self, shares: ShareStore, drive_for: Callable[[str], Share]) -> None:
        self._shares = shares
        self._drive_for = drive_for

    def shares_for(self, owner: str) -> list[Share]:
        return [self._drive_for(owner), *self._shares.shares(owner, kind=SERVER)]

    def share_for(self, owner: str, name: str) -> Share | None:
        if (name or "").strip().lower() == DRIVE_NAME:
            return self._drive_for(owner)
        share = self._shares.get(owner, name)
        return share if share is not None and share.kind == SERVER else None


def build_dav_app(
    shares: ShareStore, check: CredentialCheck, drive_for: Callable[[str], Share]
) -> WsgiDAVApp:
    """The WSGI app `create_app` mounts at `/dav`."""
    return build_app(ServerShares(shares, drive_for), check)
