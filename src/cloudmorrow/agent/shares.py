"""Machine shares: directories on this machine, served over WebDAV by the agent.

The server keeps the record — which directory, which machine — and hands it
to the agent on every heartbeat. This is the other half: a small WebDAV
server on this machine, at `http://<this machine>:<share_port>/dav/<name>/`,
that starts when there is something to serve, follows the list as it
changes, and stops when the list is empty. The address it serves at goes
back on the next heartbeat, which is how the owner's other machines find it
— and how the server knows to say "offline" once the heartbeats stop.

Who may mount it is the server's call: the agent has no password hashes and
no signing key, so it asks the server whether a username and password are
good, and remembers a yes for a while so a mount's dozens of requests a
second do not become dozens of questions.

WsgiDAV speaks the protocol, and it is the one thing the agent needs that
most agents never use — so it is not installed with the agent. The first
time this machine has a share to serve, the agent puts it into its own venv
with pip, and from then on it is there.
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import urlsplit
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from cloudmorrow.agent.client import AgentApiError, AgentClient
from cloudmorrow.agent.config import AgentConfig

log = logging.getLogger("cloudmorrow.agent.shares")

# The same path the server serves its shares under; `cloudmorrow.webdav` is
# the authority, but importing it needs WsgiDAV, which may not be here yet.
MOUNT_PATH = "/dav"

# What serving needs, and where it comes from when it is not here.
WEBDAV_REQUIREMENT = "wsgidav>=4.3"
# A failed install is not retried on every heartbeat — the network is down,
# or pip is not there — but it is retried.
INSTALL_RETRY_SECONDS = 600

# A yes from the server is good for this long. A no is not remembered: a
# wrong password is rare, and a right one after a change must work at once.
CREDENTIAL_CACHE_SECONDS = 600


def webdav_installed() -> bool:
    return importlib.util.find_spec("wsgidav") is not None


def install_webdav() -> bool:
    """Put WsgiDAV into this interpreter's environment. True when it is there."""
    if webdav_installed():
        return True
    log.info("fetching %s, to serve this machine's shares", WEBDAV_REQUIREMENT)
    try:
        done = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", WEBDAV_REQUIREMENT],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("could not install %s: %s", WEBDAV_REQUIREMENT, exc)
        return False
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip().splitlines()
        log.warning("could not install %s: %s", WEBDAV_REQUIREMENT, detail[-1] if detail else "")
        return False
    importlib.invalidate_caches()
    return webdav_installed()


@dataclass(slots=True, frozen=True)
class MachineShare:
    """One share as the server described it, with the directory resolved here."""

    name: str
    path: Path


class Credentials:
    """Asks the server, once per username and password for a while."""

    def __init__(self, client: AgentClient) -> None:
        self._client = client
        self._good: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def __call__(self, username: str, password: str) -> bool:
        if not username or not password:
            return False
        key = (username, hashlib.sha256(password.encode("utf-8")).hexdigest())
        now = time.monotonic()
        with self._lock:
            until = self._good.get(key)
            if until is not None and until > now:
                return True
        try:
            valid = self._client.check_credentials(username, password)
        except AgentApiError as exc:
            log.warning("could not check a mount's credentials: %s", exc)
            return False
        if valid:
            with self._lock:
                self._good[key] = now + CREDENTIAL_CACHE_SECONDS
        return valid


class Served:
    """The share list the provider reads: whatever the last heartbeat said."""

    def __init__(self) -> None:
        self._shares: dict[str, MachineShare] = {}
        self._lock = threading.Lock()

    def replace(self, shares: list[MachineShare]) -> bool:
        """Take a new list. Returns whether it differs from the old one."""
        fresh = {share.name: share for share in shares}
        with self._lock:
            changed = fresh != self._shares
            self._shares = fresh
        return changed

    def __len__(self) -> int:
        return len(self._shares)

    # What `cloudmorrow.webdav` asks. The caller was checked against the
    # owner by the server, so whoever got in sees every share here.
    def shares_for(self, owner: str) -> list[MachineShare]:
        with self._lock:
            return sorted(self._shares.values(), key=lambda share: share.name)

    def share_for(self, owner: str, name: str) -> MachineShare | None:
        with self._lock:
            return self._shares.get(name)


class _BoundedInput:
    """`wsgi.input` that ends where the request body does.

    The standard library hands the raw socket stream in, and a read past the
    body's `Content-Length` waits for bytes the client will never send — it
    is waiting for the response. WsgiDAV does exactly one such read after a
    PUT, to be sure the body was taken. With the length known, that read
    gets an empty answer at once.
    """

    def __init__(self, stream, length: int) -> None:
        self._stream = stream
        self._left = max(length, 0)

    def read(self, size: int = -1) -> bytes:
        if self._left <= 0:
            return b""
        size = self._left if size is None or size < 0 else min(size, self._left)
        data = self._stream.read(size)
        self._left -= len(data)
        return data

    def readline(self, size: int = -1) -> bytes:
        if self._left <= 0:
            return b""
        size = self._left if size is None or size < 0 else min(size, self._left)
        data = self._stream.readline(size)
        self._left -= len(data)
        return data

    def readlines(self, hint: int = -1) -> list[bytes]:
        lines = []
        while line := self.readline():
            lines.append(line)
        return lines

    def __iter__(self):
        while line := self.readline():
            yield line


def _mounted_at_dav(app):
    """Serve *app* under `/dav`, the way the server's own is mounted.

    WsgiDAV expects the outer server to have taken the mount path off
    `PATH_INFO` already; here there is no outer server, so this does it.
    Anything not under `/dav` is not ours.
    """

    def application(environ: dict, start_response):
        path = environ.get("PATH_INFO", "")
        if path == MOUNT_PATH or path.startswith(MOUNT_PATH + "/"):
            environ["SCRIPT_NAME"] = environ.get("SCRIPT_NAME", "") + MOUNT_PATH
            environ["PATH_INFO"] = path[len(MOUNT_PATH):] or "/"
            try:
                length = int(environ.get("CONTENT_LENGTH") or 0)
            except ValueError:
                length = 0
            environ["wsgi.input"] = _BoundedInput(environ["wsgi.input"], length)
            return app(environ, start_response)
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not here: shares are under /dav/\n"]

    return application


class _Server(ThreadingMixIn, WSGIServer):
    """A mount opens several connections at once; each gets a thread."""

    daemon_threads = True
    allow_reuse_address = True


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        log.debug("dav: " + format, *args)


def _address_towards(server_url: str) -> str:
    """The address this machine has on the way to the server.

    Nothing is sent: connecting a UDP socket only picks the interface the
    packets would leave by, and that interface's address is the one the
    other machines on the same network reach this one at.
    """
    host = urlsplit(server_url).hostname or "127.0.0.1"
    port = urlsplit(server_url).port or 443
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((host, port))
        return probe.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())
    finally:
        probe.close()


class ShareHost:
    """Serves this machine's shares while there are any."""

    def __init__(self, config: AgentConfig, client: AgentClient) -> None:
        self.config = config
        self.client = client
        self.served = Served()
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self._base = ""
        self._install_failed_at: float | None = None
        # Stands in for `install_webdav` in a test; the real one shells out to pip.
        self.installer = install_webdav

    @property
    def base_url(self) -> str:
        """`http://<address>:<port>` while serving, else ""."""
        return self._base if self._server is not None else ""

    def update(self, shares: list[dict]) -> None:
        """Follow the list from the heartbeat: start, stop, or carry on."""
        wanted = [
            MachineShare(name=str(s["name"]), path=Path(str(s["path"])).expanduser())
            for s in shares
            if s.get("name") and s.get("path")
        ]
        if not self.config.allow_shares:
            wanted = []
        for share in wanted:
            if not share.path.is_dir():
                log.warning("share %s: %s is not a directory here", share.name, share.path)
        wanted = [share for share in wanted if share.path.is_dir()]
        if self.served.replace(wanted):
            log.info("serving %s", ", ".join(s.name for s in wanted) or "no shares")
        if wanted and self._server is None:
            self.start()
        elif not wanted and self._server is not None:
            self.stop()

    def _ready(self) -> bool:
        """WsgiDAV is here, or was just fetched. A recent failure is not retried yet."""
        if webdav_installed():
            return True
        if (
            self._install_failed_at is not None
            and time.monotonic() - self._install_failed_at < INSTALL_RETRY_SECONDS
        ):
            return False
        if self.installer():
            self._install_failed_at = None
            return True
        self._install_failed_at = time.monotonic()
        return False

    def start(self) -> None:
        if self._server is not None or not self._ready():
            return
        from cloudmorrow.webdav import build_app

        app = _mounted_at_dav(build_app(self.served, Credentials(self.client)))
        try:
            self._server = make_server(
                "0.0.0.0", self.config.share_port, app, server_class=_Server, handler_class=_Quiet
            )
        except OSError as exc:
            log.warning("cannot serve shares on port %s: %s", self.config.share_port, exc)
            self._server = None
            return
        host = self.config.share_host or _address_towards(self.config.server_url)
        self._base = f"http://{host}:{self._server.server_port}"
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="cloudmorrow-shares", daemon=True
        )
        self._thread.start()
        log.info("shares served at %s%s/", self._base, MOUNT_PATH)

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self._base = ""
        log.info("stopped serving shares")
