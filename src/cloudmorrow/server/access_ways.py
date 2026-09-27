"""Reaching your cloud: the three ways, kept in step with each other.

Home network (`access_lan`), public through the relay (`access_tunnel`),
private through the mesh (`access_mesh`): each module does one thing and
knows nothing of the others. This one decides. It holds the cloud's record
(`access_control.AccessStore`), talks to the control server, and after
every change puts everything else where the record says it should be:

* `public_url`, and with it `require_tls`, follow the claimed name while
  public or private access is on — `https://<name>.<zone>` — and go back to
  what the config file says when neither is;
* the tunnel runs while public access is on, and is started again when the
  name changes;
* Caddy has a site for the name while it is in use (`access_caddy`);
* the box is on the mesh while private access is on, and the control
  server knows its mesh address;
* what the box announces on the home network says all of it.

The routes (`routes/access.py`), the server's CLI (`cli_access.py`) and the
setup page all go through `Access`, so a name claimed from the installer
and one claimed from the browser are the same thing.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from cloudmorrow import __version__
from cloudmorrow.server.access_caddy import Caddy
from cloudmorrow.server.access_control import (
    AccessStore,
    Cloud,
    Control,
    ControlError,
    cloud_from_claim,
    normalise_name,
    suggest_name,
)
from cloudmorrow.server.access_lan import (
    Announcement,
    LanAnnouncer,
    hostname_label,
    local_addresses,
)
from cloudmorrow.server.access_mesh import Mesh, MeshError, label_for, owner_of
from cloudmorrow.server.access_tunnel import Tunnel, TunnelStatus
from cloudmorrow.server.config import ServerConfig

log = logging.getLogger("cloudmorrow.access")

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
# How long a key a person asks for is good for: long enough to paste it.
KEY_SECONDS = 600
BOX_LABEL = "the box"


def tunnel_address(control: str) -> str:
    """`host:port` of the control server: where the tunnel is dialled."""
    parts = urlsplit(control)
    port = parts.port or (80 if parts.scheme == "http" else 443)
    host = parts.hostname or ""
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


class AccessError(RuntimeError):
    """Something a person asked for that cannot be done, with the sentence why."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _from_control(exc: ControlError) -> AccessError:
    code = exc.status_code or 502
    # The control server's own 401 is the box's credential, not the person's.
    if code in (401, 403):
        return AccessError(f"the control server refused this cloud: {exc}", 502)
    return AccessError(str(exc), code if code < 500 else 502)


class Access:
    """The three ways in, for one cloud."""

    def __init__(
        self,
        config: ServerConfig,
        cloud_name: Callable[[], str],
        *,
        http: httpx.Client | None = None,
        mesh: Mesh | None = None,
        caddy: Caddy | None = None,
        zeroconf_factory: Callable[[], object] | None = None,
        addresses: Callable[[], list[str]] = local_addresses,
    ) -> None:
        self.config = config
        self.cloud_name = cloud_name
        self.store = AccessStore(config.db_path)
        # A client for the control server, for tests; None makes real ones.
        self.http = http
        self.mesh = mesh or Mesh()
        self.caddy = caddy or Caddy(config)
        self.addresses = addresses
        self.lan = LanAnnouncer(self.announcement, zeroconf_factory)
        # What the config file said, to go back to when no name is in use.
        self.configured_url = config.public_url
        self.tunnel: Tunnel | None = None
        # Extra keywords for the tunnel (tests: plain TCP, short timers).
        self.tunnel_options: dict[str, Any] = {}
        self.mesh_error = ""
        self._lock = threading.RLock()
        self._started = False

    # -- the record -------------------------------------------------------------
    def cloud(self) -> Cloud | None:
        return self.store.get()

    def control(self, cloud: Cloud | None = None) -> Control:
        return Control(self.config.access_control, cloud.token if cloud else "", http=self.http)

    def _require(self) -> Cloud:
        cloud = self.cloud()
        if cloud is None:
            raise AccessError("this cloud has no name yet: claim one first", 409)
        return cloud

    # -- start and stop -----------------------------------------------------------
    def start(self) -> None:
        """At boot: the address, the announcement, the tunnel, the mesh."""
        self._started = True
        cloud = self.cloud()
        self.follow(cloud)
        if self.config.access_lan:
            self.lan.start()
        if cloud is not None and cloud.public:
            self._start_tunnel(cloud)
        if cloud is not None and cloud.private:
            threading.Thread(
                target=self._keep_mesh, args=(cloud,), name="access-mesh", daemon=True
            ).start()

    def stop(self) -> None:
        self._started = False
        if self.tunnel is not None:
            self.tunnel.stop()
            self.tunnel = None
        self.lan.stop()

    def follow(self, cloud: Cloud | None) -> None:
        """public_url (and so require_tls) follow the name while it is in use."""
        if cloud is not None and cloud.reachable:
            self.config.public_url = f"https://{cloud.host}"
        else:
            self.config.public_url = self.configured_url

    def _start_tunnel(self, cloud: Cloud) -> None:
        if self.tunnel is not None:
            self.tunnel.stop()
        # The tunnel is dialled at the control server's own host and port:
        # the relay tells them apart by what is said first.
        self.tunnel = Tunnel(
            tunnel_address(self.config.access_control),
            cloud.cloud_id,
            cloud.token,
            {443: self.config.access_upstream_443, 80: self.config.access_upstream_80},
            **self.tunnel_options,
        )
        self.tunnel.start()

    def _tunnel_wanted(self, restart: bool) -> bool:
        # One that stopped (refused for good) is started again by any change.
        return self.tunnel is None or restart or not self.tunnel.running

    def apply(self, cloud: Cloud | None, *, restart_tunnel: bool = False) -> None:
        """Put the address, the tunnel, Caddy and the announcement where *cloud* says."""
        self.follow(cloud)
        if self._started:
            wants_tunnel = cloud is not None and cloud.public
            if not wants_tunnel and self.tunnel is not None:
                self.tunnel.stop()
                self.tunnel = None
            elif wants_tunnel and self._tunnel_wanted(restart_tunnel):
                self._start_tunnel(cloud)
            if self.config.access_lan:
                threading.Thread(target=self.lan.refresh, daemon=True).start()
        self.caddy.apply(cloud, self.config.access_control)

    def _keep_mesh(self, cloud: Cloud) -> None:
        """At boot, with private access on: back on the mesh, and the address known."""
        try:
            status = self.mesh.status()
            if not status.running and status.state == "Stopped":
                status = self.mesh.up(cloud.login_server)
            if status.running and status.address and status.address != cloud.mesh_address:
                with self.control(cloud) as control:
                    control.report_address(status.address)
                cloud.mesh_address = status.address
                self.store.save(cloud)
            self.mesh_error = "" if status.running else (status.error or status.state)
        except (MeshError, ControlError) as exc:
            self.mesh_error = str(exc)
            log.warning("private access: %s", exc)

    # -- what it looks like -------------------------------------------------------
    def announcement(self) -> Announcement | None:
        cloud = self.cloud()
        addresses = self.addresses()
        name = self.cloud_name()
        if cloud is not None and cloud.reachable:
            return Announcement(
                label=cloud.name,
                name=name,
                version=__version__,
                port=443,
                url=f"https://{cloud.host}",
                public=cloud.host if cloud.public else "",
                private=cloud.host if cloud.private else "",
                addresses=addresses,
            )
        if self.config.host in LOOPBACK:
            # Nothing listens where a neighbour could reach it.
            return None
        label = hostname_label(name)
        return Announcement(
            label=label,
            name=name,
            version=__version__,
            port=self.config.port,
            url=f"http://{label}.local:{self.config.port}",
            addresses=addresses,
        )

    def status(self, admin: bool) -> dict:
        """The three ways, as a screen shows them. Admins see the workings too."""
        cloud = self.cloud()
        public_on = bool(cloud and cloud.public)
        private_on = bool(cloud and cloud.private)
        out: dict[str, Any] = {
            "address": self.config.public_url,
            "name": cloud.name if cloud else "",
            "host": cloud.host if cloud else "",
            "lan": {"on": self.config.access_lan, **self.lan.status()},
            "public": {"on": public_on},
            "private": {
                "on": private_on,
                "login_server": cloud.login_server if cloud and private_on else "",
            },
        }
        if not admin:
            return out
        out["control"] = self.config.access_control
        out["enrolled"] = cloud is not None
        out["zone"] = cloud.zone if cloud else ""
        out["suggested_name"] = suggest_name(self.cloud_name())
        tunnel = self.tunnel.status() if self.tunnel else TunnelStatus().as_dict()
        out["public"]["tunnel"] = tunnel
        mesh = self.mesh.status()
        out["private"]["mesh"] = mesh.as_dict()
        out["private"]["address"] = cloud.mesh_address if cloud else ""
        out["private"]["error"] = self.mesh_error
        out["caddy"] = self.caddy.status()
        return out

    # -- the name -----------------------------------------------------------------
    def claim(self, name: str, *, public: bool = True, private: bool = False) -> Cloud:
        """Enrol with the control server under *name*, or move to it; then the ways asked for."""
        try:
            wanted = normalise_name(name)
        except ControlError as exc:
            raise AccessError(str(exc), 400) from exc
        with self._lock:
            cloud = self.cloud()
            if cloud is not None:
                if cloud.name != wanted:
                    cloud = self.rename(wanted)
                cloud = self.set_public(public)
                if private != cloud.private:
                    cloud = self.set_private(private)
                return cloud
            try:
                with self.control() as control:
                    answer = control.claim(wanted, public=public)
            except ControlError as exc:
                if exc.status_code == 409:
                    raise AccessError(f"{wanted} is taken; try another name", 409) from exc
                raise _from_control(exc) from exc
            cloud = cloud_from_claim(answer, self.config.access_control, public)
            self.store.save(cloud)
            if not public:
                # The control server may start a name public; say it is not.
                try:
                    with self.control(cloud) as control:
                        control.update(public=False)
                except ControlError as exc:
                    log.warning("could not turn public access off at the control server: %s", exc)
            if not public and not private:
                # Neither way yet: the name is held, and nothing uses it.
                self.apply(cloud)
                return cloud
            if public:
                self.apply(cloud, restart_tunnel=True)
            if private:
                cloud = self.set_private(True)
            return cloud

    def rename(self, name: str) -> Cloud:
        try:
            wanted = normalise_name(name)
        except ControlError as exc:
            raise AccessError(str(exc), 400) from exc
        with self._lock:
            cloud = self._require()
            if wanted == cloud.name:
                return cloud
            try:
                with self.control(cloud) as control:
                    answer = control.update(name=wanted)
            except ControlError as exc:
                if exc.status_code == 409:
                    raise AccessError(f"{wanted} is taken; try another name", 409) from exc
                raise _from_control(exc) from exc
            cloud.name = str(answer.get("name") or wanted)
            cloud.zone = str(answer.get("zone") or cloud.zone)
            cloud.public_host = str(answer.get("public_host") or f"{cloud.name}.{cloud.zone}")
            self.store.save(cloud)
            self.apply(cloud, restart_tunnel=True)
            return cloud

    def release(self) -> None:
        """Give the name back. The token, the mesh and its devices go with it."""
        with self._lock:
            cloud = self._require()
            try:
                with self.control(cloud) as control:
                    control.release()
            except ControlError as exc:
                # Already gone there is gone: forget it here too.
                if exc.status_code not in (401, 404):
                    raise _from_control(exc) from exc
            if cloud.private:
                try:
                    self.mesh.down()
                except MeshError as exc:
                    log.info("leaving the mesh: %s", exc)
            self.store.clear()
            self.apply(None)

    # -- the ways -----------------------------------------------------------------
    def set_public(self, on: bool) -> Cloud:
        with self._lock:
            cloud = self._require()
            if cloud.public == on:
                self.apply(cloud)
                return cloud
            try:
                with self.control(cloud) as control:
                    control.update(public=on)
                    if not on and cloud.private and not cloud.acme:
                        # Private only: the certificate by DNS from now on.
                        cloud.acme = control.acme_register()
            except ControlError as exc:
                raise _from_control(exc) from exc
            cloud.public = on
            self.store.save(cloud)
            self.apply(cloud)
            return cloud

    def set_private(self, on: bool) -> Cloud:
        with self._lock:
            cloud = self._require()
            if on:
                return self._join(cloud)
            try:
                self.mesh.down()
            except MeshError as exc:
                log.info("leaving the mesh: %s", exc)
            try:
                with self.control(cloud) as control:
                    control.report_address("")
            except ControlError as exc:
                log.info("could not clear the mesh address: %s", exc)
            cloud.private = False
            cloud.mesh_address = ""
            self.mesh_error = ""
            self.store.save(cloud)
            self.apply(cloud)
            return cloud

    def _join(self, cloud: Cloud) -> Cloud:
        status = self.mesh.status()
        if not status.installed:
            raise AccessError(
                "tailscale is not installed on this box; run the server installer "
                "with --private to add it (sudo sh install-server.sh --private)",
                503,
            )
        try:
            with self.control(cloud) as control:
                if not status.running:
                    if status.state == "Stopped":
                        status = self.mesh.up(cloud.login_server)
                    else:
                        key = control.mesh_key(BOX_LABEL, expires_in=KEY_SECONDS)
                        login = str(key.get("login_server") or cloud.login_server)
                        cloud.login_server = login
                        status = self.mesh.up(login, str(key["key"]))
                if not status.running or not status.address:
                    raise AccessError(
                        f"the box did not come up on the mesh ({status.state or 'no state'})", 502
                    )
                control.report_address(status.address)
                if not cloud.public and not cloud.acme:
                    cloud.acme = control.acme_register()
        except MeshError as exc:
            self.mesh_error = str(exc)
            raise AccessError(str(exc), 503) from exc
        except ControlError as exc:
            raise _from_control(exc) from exc
        cloud.private = True
        cloud.mesh_address = status.address
        self.mesh_error = ""
        self.store.save(cloud)
        self.apply(cloud)
        return cloud

    # -- people's devices ---------------------------------------------------------
    def _private(self) -> Cloud:
        cloud = self._require()
        if not cloud.private:
            raise AccessError("private access is off on this cloud", 409)
        return cloud

    def mesh_key(self, username: str, device: str) -> dict:
        """A one-time key for *username*'s *device* to join the mesh with."""
        cloud = self._private()
        try:
            with self.control(cloud) as control:
                answer = control.mesh_key(
                    label_for(username, device), owner=username, expires_in=KEY_SECONDS
                )
        except ControlError as exc:
            raise _from_control(exc) from exc
        return {
            "key": str(answer.get("key", "")),
            "login_server": str(answer.get("login_server") or cloud.login_server),
            "expires_at": str(answer.get("expires_at", "")),
            "hostname": cloud.host,
        }

    def pair(self, username: str, device: str) -> dict:
        """A pairing code for a phone, which the Tailscale app's sign-in page asks for."""
        cloud = self._private()
        try:
            with self.control(cloud) as control:
                answer = control.pair(label_for(username, device), owner=username)
        except ControlError as exc:
            raise _from_control(exc) from exc
        return {
            "code": str(answer.get("code", "")),
            "login_server": str(answer.get("login_server") or cloud.login_server),
            "expires_at": str(answer.get("expires_at", "")),
            "hostname": cloud.host,
        }

    def devices(self, username: str | None) -> list[dict]:
        """The enrolled devices: everybody's for an admin (None), else the person's own."""
        cloud = self._private()
        try:
            with self.control(cloud) as control:
                found = control.devices()
        except ControlError as exc:
            raise _from_control(exc) from exc
        out = []
        for device in found:
            owner = owner_of(device)
            if username is not None and owner != username:
                continue
            out.append(
                {
                    "id": str(device.get("id", "")),
                    "name": str(device.get("name") or device.get("hostname") or ""),
                    "for": str(device.get("for") or ""),
                    "owner": owner,
                    "address": str(device.get("address") or ""),
                    "online": bool(device.get("online")),
                    "last_seen": str(device.get("last_seen") or ""),
                }
            )
        return out

    def remove_device(self, device_id: str, username: str | None) -> None:
        cloud = self._private()
        if username is not None and not any(
            d["id"] == device_id for d in self.devices(username)
        ):
            raise AccessError("no such device of yours", 404)
        try:
            with self.control(cloud) as control:
                control.remove_device(device_id)
        except ControlError as exc:
            raise _from_control(exc) from exc
