"""What the web app may ask of this computer, when it is running in the desktop app.

pywebview hands this object to the page as `window.pywebview.api`: each
public method is a function there that returns a promise. So everything a
method returns is plain JSON, and nothing is ever raised into the page — a
refusal comes back as `{"error": "…"}` in the same sentence the command line
would print, because an exception in JS says only that the call failed.

Every method is the command line's own code, called rather than copied:
mounting is `client.mounts`, what is missing for it is `client.rclone`, the
agent is `agent.setup` and `agent.service`. The one thing the desktop app
knows that nobody else does is the sign-in in the window, and it hands that
across (`session`, `signed_in`, `signed_out`) so the window, the terminal
app and the command line are one sign-in on this machine, not three.

pywebview runs each call on a thread of its own, so a slow one — a mount
waits for rclone — does not freeze the window, and a method that talks to
the server runs its coroutine to completion right there.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import platform as _platform
import socket
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from cloudmorrow import __version__
from cloudmorrow.agent import service
from cloudmorrow.agent.config import AgentConfig
from cloudmorrow.agent.config import default_config_path as agent_config_path
from cloudmorrow.agent.setup import ensure_agent, machine_name
from cloudmorrow.client import mounts
from cloudmorrow.client.api import CloudmorrowClient, client_from_credentials
from cloudmorrow.client.config import ClientConfig, StoredCredentials, clear_credentials
from cloudmorrow.desktop import system

log = logging.getLogger(__name__)


def _origin(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.scheme.lower(), parts.netloc.lower()


def bridged(method: Callable[..., dict]) -> Callable[..., dict]:
    """A method the page may call: from this cloud's own page only, and never raising.

    The window opens on the server's `/app`, but a page can link anywhere;
    a page from somewhere else gets `{"error"}` rather than a way to mount
    things. Whatever goes wrong inside is logged and handed back as words.
    """

    @functools.wraps(method)
    def call(self: Bridge, *args: Any) -> dict:
        if not self._trusted():
            return {"error": "this page is not your cloud's, so it may not ask this computer"}
        try:
            return method(self, *args)
        except Exception as exc:
            log.exception("desktop bridge: %s failed", method.__name__)
            return {"error": str(exc) or exc.__class__.__name__}

    return call


class Bridge:
    """`window.pywebview.api`. Attributes that start with `_` are not given to the page."""

    def __init__(
        self,
        config: ClientConfig | None = None,
        *,
        api_factory: Callable[[ClientConfig], CloudmorrowClient] | None = None,
        enrol: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config or ClientConfig.load()
        # How a call that talks to the server gets a client: the stored
        # sign-in, read afresh each time, since the page may just have changed it.
        self._api_factory = api_factory or (
            lambda config: client_from_credentials(config, StoredCredentials.load())
        )
        self._enrol = enrol or ensure_agent
        self._window = None

    def _attach(self, window) -> None:
        """The window this bridge answers, so a call can ask which page asked."""
        self._window = window

    def _trusted(self) -> bool:
        if self._window is None:  # no window: a test, or nothing to spoof
            return True
        try:
            current = self._window.get_current_url() or ""
        except Exception:
            return False
        return _origin(current) == _origin(self._config.api_url)

    def _server(self, coroutine_of: Callable[[CloudmorrowClient], Any]) -> Any:
        """Run one conversation with the server, signed in as this machine is."""

        async def talk() -> Any:
            api = self._api_factory(self._config)
            try:
                return await coroutine_of(api)
            finally:
                await api.aclose()

        return asyncio.run(talk())

    # -- about this computer -------------------------------------------------
    @bridged
    def platform(self) -> dict:
        """Which system this is, what it is called, and whether it can mount."""
        return {
            "os": system.os_name(),
            "system": _platform.platform(),
            "hostname": socket.gethostname(),
            # The name this machine's agent goes by, and its shares say "on".
            "machine": machine_name(),
            "mount": system.mount_support(),
        }

    @bridged
    def version(self) -> dict:
        return {"version": __version__, "server": self._config.api_url}

    @bridged
    def agent_status(self) -> dict:
        """Whether this machine is enrolled as an agent, and whether it is running."""
        path = agent_config_path()
        agent = AgentConfig.load(path) if path.exists() else None
        enrolled = bool(agent and agent.agent_token)
        return {
            "enrolled": enrolled,
            "name": agent.name if agent else machine_name(),
            "service": service.detect_kind(),
            "installed": service.is_installed(),
            "running": service.is_active() if enrolled else False,
        }

    @bridged
    def notify(self, title: str, body: str = "") -> dict:
        return {"sent": system.notify(str(title), str(body or ""))}

    @bridged
    def open_folder(self, path: str) -> dict:
        return {"opened": str(system.open_folder(str(path)))}

    # -- shares, mounted here ---------------------------------------------------
    @staticmethod
    def _where(name: str) -> dict:
        mounted = mounts.lookup(name)
        if mounted is None:
            return {"mounted": False, "path": ""}
        # A record whose mount is gone — a reboot, a `umount` by hand — is
        # not mounted, but the path is still worth saying.
        return {"mounted": mounted.active, "path": str(mounted.path)}

    @bridged
    def mounted_here(self) -> dict:
        """What this machine has mounted, by share name. Local, so it is quick."""
        return {"mounts": {name: self._where(name) for name in mounts.all_mounts()}}

    @bridged
    def shares(self) -> dict:
        """The server's shares, each with whether and where it is mounted here."""
        listed = self._server(lambda api: api.shares())
        return {"shares": [{**share, **self._where(share["name"])} for share in listed]}

    @bridged
    def mount(self, name: str) -> dict:
        """Mount a share where the command line would, signed in the same way."""
        credentials = StoredCredentials.load()
        if credentials is None:
            return {"error": "this computer is not signed in"}
        support = system.mount_support()
        if not support["available"]:
            return {"error": support["detail"]}
        share = self._server(lambda api: api.get_share(str(name)))
        try:
            mounted = mounts.mount_share(share, credentials.username, credentials.access_token)
        except mounts.MountError as exc:
            return {"error": str(exc)}
        return {"name": mounted.name, "mounted": True, "path": str(mounted.path)}

    @bridged
    def unmount(self, name: str) -> dict:
        try:
            mounted = mounts.unmount(str(name))
        except mounts.MountError as exc:
            return {"error": str(exc)}
        return {"name": mounted.name, "mounted": False, "path": str(mounted.path)}

    # -- one sign-in for the machine ----------------------------------------------
    @bridged
    def session(self) -> dict:
        """The sign-in stored on this machine, for the window to start with.

        Only when it is for the server the window is on: a token for another
        cloud is no use to this one.
        """
        credentials = StoredCredentials.load()
        if credentials is None or credentials.api_url.rstrip("/") != self._config.api_url:
            return {"token": "", "user": ""}
        return {"token": credentials.access_token, "user": credentials.username}

    @bridged
    def signed_in(self, token: str, username: str, expires_at: str = "") -> dict:
        """The window signed in: store it, so the terminal app is signed in too.

        And, as `cloudmorrow login` does, make this machine an agent if it is
        not one yet — once; a sign-in after that leaves the agent alone.
        """
        StoredCredentials(
            api_url=self._config.api_url,
            username=str(username),
            access_token=str(token),
            expires_at=str(expires_at or ""),
        ).save()
        path = agent_config_path()
        if path.exists() and AgentConfig.load(path).agent_token:
            return {"saved": True, "agent": ""}
        result = self._server(lambda api: self._enrol(api))
        return {"saved": True, "agent": result.agent_name if result.enrolled else ""}

    @bridged
    def signed_out(self, token: str) -> dict:
        """The window signed out, or its token stopped working: so did this machine.

        Only if the stored sign-in is the one the window had — the terminal
        app may have signed in afresh since, and that one is not the window's
        to throw away. The agent has a credential of its own and keeps it.
        """
        credentials = StoredCredentials.load()
        if credentials is not None and credentials.access_token == str(token):
            clear_credentials()
            return {"cleared": True}
        return {"cleared": False}
