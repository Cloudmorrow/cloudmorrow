"""Reaching your cloud: the home network always, and the mesh once the box is linked.

The home network (`access_lan`) needs nothing from anywhere. The mesh needs
the box linked to a cloudmorrow.com account (`access_control`), on the mesh
itself (`access_mesh`), and Caddy holding the certificate for its name
(`access_caddy`): each module does one thing and knows nothing of the
others. This one decides. It holds the cloud's record and puts everything
else where the record says it should be:

* linking is a code a person enters on the website; the box polls for the
  answer on a thread of its own, and a code still waiting when the server
  stops is polled again when it starts;
* once linked, the box joins the mesh and Caddy gets the site for
  `<name>.<zone>` — "set up". A box stopped halfway finishes at the next
  start, and every ten minutes after, until it has;
* `public_url`, and with it `require_tls`, follow the name once the box is
  set up — `https://<name>.<zone>` — and go back to what the config file
  says when it is unlinked;
* every ten minutes, and at start, the box reads its record at the relay:
  a name changed on the website moves Caddy and `public_url` to the new
  one, and a cloud unlinked on the website goes back to the home network;
* what the box announces on the home network says all of it.

Nothing about the cloud's people leaves the box: keys and invite codes are
asked for without saying whose device they are for, and whose each device
is stays in the box's own labels (`access_labels`).

The routes (`routes/access.py`), the server's CLI (`cli_access.py`), the
installer and the setup page all go through `Access`.
"""

from __future__ import annotations

import logging
import re
import secrets
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

from cloudmorrow import __version__
from cloudmorrow.server import public_way
from cloudmorrow.server.access_caddy import Caddy
from cloudmorrow.server.access_control import (
    AccessStore,
    Cloud,
    Control,
    ControlError,
    PendingLink,
    cloud_from_link,
    pending_from,
    valid_name,
    valid_zone,
)
from cloudmorrow.server.access_labels import LabelStore, clean_device
from cloudmorrow.server.access_lan import Announcement, LanAnnouncer, hostname_label, local_addresses
from cloudmorrow.server.access_mesh import Mesh, MeshError
from cloudmorrow.server.config import ServerConfig
from cloudmorrow.server.settings import SettingsStore

log = logging.getLogger("cloudmorrow.access")

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
# How long a key a person asks for is good for: long enough to paste it.
KEY_SECONDS = 600
# How often the box reads its own record at the relay: a rename on the
# website, or an unlink, reaches the box within this.
REFRESH_SECONDS = 600
# A computer's name on the mesh: opaque, so the relay learns nothing from it.
HOSTNAME_RE = re.compile(r"^cm-[0-9a-f]{6}$")


def computer_hostname(hint: str = "") -> str:
    """`cm-<6 hex>`: the relay's hint when it gives one of that shape, else a new one."""
    return hint if HOSTNAME_RE.match(hint or "") else f"cm-{secrets.token_hex(3)}"


class AccessError(RuntimeError):
    """Something a person asked for that cannot be done, with the sentence why."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _from_control(exc: ControlError) -> AccessError:
    code = exc.status_code or 502
    # The relay's own 401 is the box's credential, not the person's.
    if code in (401, 403):
        return AccessError(f"the relay refused this cloud: {exc}", 502)
    return AccessError(str(exc), code if code < 500 else 502)


class Access:
    """How one cloud is reached."""

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
        self.labels = LabelStore(config.db_path)
        # A client for the relay, for tests; None makes real ones.
        self.http = http
        self.mesh = mesh or Mesh()
        self.caddy = caddy or Caddy(config)
        # Reachable from anywhere (public_way): the owner's switch, kept here.
        self.settings = SettingsStore(config.db_path)
        self.addresses = addresses
        self.lan = LanAnnouncer(self.announcement, zeroconf_factory)
        # What the config file said, to go back to when the box is unlinked.
        self.configured_url = config.public_url
        # Why the last attempt at linking or setting up did not work, for the screens.
        self.link_error = ""
        self.setup_error = ""
        # "expired" once a code ran out or was refused, until a new one is asked for.
        self.link_state = ""
        self.refresh_seconds = REFRESH_SECONDS
        self._lock = threading.RLock()
        self._stopping = threading.Event()
        self._polling = False
        self._started = False

    # -- the record -------------------------------------------------------------
    def cloud(self) -> Cloud | None:
        return self.store.get()

    def pending(self) -> PendingLink | None:
        return self.store.pending()

    def control(self, cloud: Cloud | None = None) -> Control:
        base = (cloud.control if cloud and cloud.control else "") or self.config.access_control
        return Control(base, cloud.token if cloud else "", http=self.http)

    def _require(self) -> Cloud:
        cloud = self.cloud()
        if cloud is None:
            raise AccessError("this cloud is not linked to a cloudmorrow.com account", 409)
        return cloud

    def _require_mesh(self) -> Cloud:
        cloud = self._require()
        if not cloud.set_up:
            why = self.setup_error or "it is still being set up"
            raise AccessError(f"this cloud is linked, but not on its mesh yet: {why}", 409)
        return cloud

    # -- start and stop -----------------------------------------------------------
    def start(self) -> None:
        """At boot: the address, the announcement, a link still waiting, the record."""
        self._started = True
        self._stopping.clear()
        self.follow(self.cloud())
        if self.config.access_lan:
            self.lan.start()
        if self.pending() is not None:
            self._start_polling()
        if self.cloud() is not None:
            threading.Thread(target=self._keep_up, name="access-refresh", daemon=True).start()

    def stop(self) -> None:
        self._started = False
        self._stopping.set()
        self.lan.stop()

    def follow(self, cloud: Cloud | None) -> None:
        """public_url (and so require_tls) follow the name once the box answers to it."""
        if cloud is not None and cloud.set_up:
            self.config.public_url = f"https://{cloud.host}"
        else:
            self.config.public_url = self.configured_url

    def apply(self, cloud: Cloud | None) -> None:
        """Put the address, Caddy and the announcement where *cloud* says."""
        self.follow(cloud)
        control = (cloud.control if cloud else "") or self.config.access_control
        self.caddy.apply(cloud if cloud is not None and cloud.set_up else None, control, public=self.reachable())
        if self._started and self.config.access_lan:
            threading.Thread(target=self.lan.refresh, daemon=True).start()

    def _keep_up(self) -> None:
        """Now, and every ten minutes: the record at the relay, and a set-up left unfinished."""
        while not self._stopping.is_set():
            try:
                if self.refresh() is None:
                    return
            except Exception as exc:  # never take the server down over it
                log.warning("reading this cloud's record at the relay: %s", exc)
            if self._stopping.wait(self.refresh_seconds):
                return

    # -- what it looks like -------------------------------------------------------
    def announcement(self) -> Announcement | None:
        cloud = self.cloud()
        addresses = self.addresses()
        name = self.cloud_name()
        if cloud is not None and cloud.set_up:
            return Announcement(
                label=cloud.name,
                name=name,
                version=__version__,
                port=443,
                url=f"https://{cloud.host}",
                mesh=cloud.host,
                addresses=addresses,
            )
        if all(host in LOOPBACK for host in self.config.hosts):
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
        """How the cloud is reached, as a screen shows it. Admins see the workings too."""
        cloud = self.cloud()
        linked = cloud is not None
        on_mesh = bool(cloud and cloud.set_up)
        lan = self.lan.status()
        out: dict[str, Any] = {
            "address": self.config.public_url,
            "linked": linked,
            "name": cloud.name if cloud else "",
            "host": cloud.host if cloud else "",
            # `on` is whether it announces itself; `announced`, whether it is right now.
            "lan": {**lan, "on": self.config.access_lan, "announced": lan["on"]},
            "mesh": {
                "on": on_mesh,
                "login_server": cloud.login_server if on_mesh else "",
            },
            # Reachable from anywhere: the owner's switch, and whether it is in force.
            "public": {"on": self.reachable(), "live": on_mesh and self.reachable()},
        }
        if not admin:
            return out
        pending = self.pending()
        waiting = pending is not None and not pending.expired and not linked
        out["control"] = self.config.access_control
        out["zone"] = cloud.zone if cloud else ""
        out["link"] = pending.shown() if waiting else None
        out["link_state"] = "linked" if linked else "waiting" if waiting else self.link_state
        out["link_error"] = self.link_error
        out["setup_error"] = self.setup_error
        out["mesh"]["box"] = self.mesh.status().as_dict()
        out["mesh"]["address"] = cloud.mesh_address if cloud else ""
        out["caddy"] = self.caddy.status()
        return out

    # -- linking --------------------------------------------------------------------
    def link(self) -> dict:
        """A link code for a person to enter at cloudmorrow.com/link: the one waiting, or a new one."""
        with self._lock:
            cloud = self.cloud()
            if cloud is not None:
                raise AccessError(f"this cloud is already linked, as {cloud.host}", 409)
            pending = self.pending()
            if pending is None or pending.expired or pending.control != self.config.access_control:
                try:
                    with self.control() as control:
                        pending = pending_from(control.start_link(), self.config.access_control)
                except ControlError as exc:
                    raise _from_control(exc) from exc
                self.store.save_pending(pending)
            self.link_state = ""
            self.link_error = ""
        if self._started:
            self._start_polling()
        return pending.shown()

    def cancel_link(self) -> None:
        """Forget a code nobody entered. The relay lets it run out by itself."""
        with self._lock:
            self.store.clear_pending()
            self.link_state = ""

    def _start_polling(self) -> None:
        with self._lock:
            if self._polling:
                return
            self._polling = True
        threading.Thread(target=self._poll_loop, name="access-link", daemon=True).start()

    def _poll_loop(self) -> None:
        try:
            while not self._stopping.is_set():
                pending = self.pending()
                if pending is None:
                    return
                if self.poll_once() != "waiting":
                    break
                if self._stopping.wait(pending.interval):
                    return
        finally:
            with self._lock:
                self._polling = False
        if self.cloud() is not None and not self._stopping.is_set():
            # Linked while running: keep its record from now on.
            threading.Thread(target=self._keep_up, name="access-refresh", daemon=True).start()

    def _expire(self) -> str:
        with self._lock:
            self.store.clear_pending()
            self.link_state = "expired"
        return "expired"

    def poll_once(self) -> str:
        """Ask the relay once whether the code was entered.

        "waiting", "linked", "expired" (the code ran out or the person said
        no), or "none" when there is no code to ask about. A relay that
        cannot be reached is still "waiting": the next poll may reach it.
        """
        pending = self.pending()
        if pending is None:
            return "linked" if self.cloud() is not None else "none"
        try:
            with self.control() as control:
                answer = control.poll_link(pending.poll)
        except ControlError as exc:
            if exc.status_code in (404, 410):
                return self._expire()
            self.link_error = str(exc)
            return self._expire() if pending.expired else "waiting"
        if answer is None:
            self.link_error = ""
            return self._expire() if pending.expired else "waiting"
        try:
            cloud = cloud_from_link(answer, pending.control or self.config.access_control)
        except ControlError as exc:
            self.link_error = str(exc)
            return self._expire()
        with self._lock:
            # The token first: from here the cloud is linked, whatever happens next.
            self.store.save(cloud)
            self.store.clear_pending()
            self.link_state = "linked"
            self.link_error = ""
        log.info("linked as %s", cloud.host)
        try:
            self.set_up()
        except AccessError as exc:
            log.warning("linked as %s, but not set up yet: %s", cloud.host, exc)
        return "linked"

    def wait_for_link(self, on_wait: Callable[[PendingLink], None] | None = None) -> str:
        """Poll until the code is entered or runs out: the installer's and the CLI's way."""
        while True:
            state = self.poll_once()
            if state != "waiting":
                return state
            pending = self.pending()
            if pending is None:
                return self.poll_once()
            if on_wait is not None:
                on_wait(pending)
            time.sleep(pending.interval)

    # -- set up: the mesh and the certificate ------------------------------------------
    def set_up(self) -> Cloud:
        """On the mesh as `cloud`, and Caddy holding the site for the name."""
        with self._lock:
            cloud = self._require()
            try:
                status = self.mesh.status()
                if not status.installed:
                    raise MeshError(
                        "tailscale is not installed on this box; the server installer adds it "
                        "(sudo sh install-server.sh --link)"
                    )
                if not (status.running and cloud.set_up):
                    if status.state == "Stopped" and cloud.set_up:
                        # Registered before, and only down: up again, no key needed.
                        status = self.mesh.up(cloud.login_server)
                    else:
                        with self.control(cloud) as control:
                            key = control.mesh_key(expires_in=KEY_SECONDS)
                        cloud.login_server = str(key.get("login_server") or cloud.login_server)
                        status = self.mesh.up(cloud.login_server, str(key["key"]))
                if not status.running:
                    raise MeshError(f"the box did not come up on the mesh ({status.state or 'no state'})")
            except MeshError as exc:
                self.setup_error = str(exc)
                raise AccessError(str(exc), 503) from exc
            except ControlError as exc:
                self.setup_error = str(exc)
                raise _from_control(exc) from exc
            cloud.mesh_address = status.address or cloud.mesh_address
            cloud.set_up = True
            self.store.save(cloud)
            self.setup_error = ""
            self.apply(cloud)
            log.info("on the mesh as %s at %s", cloud.host, cloud.mesh_address)
            return cloud

    # -- the record at the relay: renames, and an unlink from the website ---------------
    def refresh(self) -> Cloud | None:
        """Read the cloud's record at the relay, and follow it."""
        cloud = self.cloud()
        if cloud is None:
            return None
        try:
            with self.control(cloud) as control:
                record = control.me()
        except ControlError as exc:
            if exc.status_code == 401:
                # Unlinked on the website: the token is revoked, and so is the mesh.
                log.warning("the relay no longer knows this cloud; back to the home network only")
                self._forget()
                return None
            log.info("could not read this cloud's record at the relay: %s", exc)
            record = {}
        name = str(record.get("name") or cloud.name)
        zone = str(record.get("zone") or cloud.zone)
        with self._lock:
            if (name, zone) != (cloud.name, cloud.zone):
                if valid_name(name) and valid_zone(zone):
                    log.info("renamed on the website: %s -> %s.%s", cloud.host, name, zone)
                    cloud.name, cloud.zone = name, zone
                else:
                    log.warning("the relay named this cloud %s.%s, which is not a usable name", name, zone)
            cloud.login_server = str(record.get("login_server") or cloud.login_server)
            cloud.mesh_address = str(record.get("mesh_address") or cloud.mesh_address)
            self.store.save(cloud)
        if "public" in record and bool(record["public"]) != self.reachable():
            # The box's switch is the one that counts; the relay follows it.
            self._tell_relay(cloud)
        if not cloud.set_up:
            try:
                cloud = self.set_up()
            except AccessError as exc:
                log.info("not set up yet: %s", exc)
        self.apply(cloud)
        return cloud

    # -- reachable from anywhere ------------------------------------------------------
    def reachable(self) -> bool:
        return public_way.reachable(self.settings)

    def set_reachable(self, on: bool, *, changed_by: str = "") -> dict:
        """Turn *Reachable from anywhere* on or off: Caddy's 8443 site, and the relay."""
        public_way.set_reachable(self.settings, on, changed_by=changed_by)
        cloud = self.cloud()
        self.apply(cloud)
        if cloud is not None:
            self._tell_relay(cloud)
        return self.status(admin=True)

    def _tell_relay(self, cloud: Cloud) -> None:
        """Say whether the relay should pass visitors through. A relay that cannot hear it yet is logged."""
        try:
            with self.control(cloud) as control:
                control.set_public(self.reachable())
        except ControlError as exc:
            log.info("could not tell the relay whether this cloud is reachable from anywhere: %s", exc)

    # -- unlinking --------------------------------------------------------------------
    def unlink(self) -> None:
        """Give the name back. The token, the mesh and its devices go with it."""
        with self._lock:
            cloud = self._require()
            try:
                with self.control(cloud) as control:
                    control.unlink()
            except ControlError as exc:
                # Already gone there is gone: forget it here too.
                if exc.status_code not in (401, 404):
                    raise _from_control(exc) from exc
            self._forget()

    def _forget(self) -> None:
        with self._lock:
            try:
                if self.mesh.status().installed:
                    self.mesh.down()
            except MeshError as exc:
                log.info("leaving the mesh: %s", exc)
            self.store.clear()
            self.store.clear_pending()
            self.labels.clear()
            self.setup_error = ""
            self.link_state = ""
            self.apply(None)

    # -- people's devices -------------------------------------------------------------
    def mesh_key(self) -> dict:
        """A one-time key for a computer to join the mesh with, and the name to join as."""
        cloud = self._require_mesh()
        try:
            with self.control(cloud) as control:
                answer = control.mesh_key(expires_in=KEY_SECONDS)
        except ControlError as exc:
            raise _from_control(exc) from exc
        return {
            "key": str(answer.get("key", "")),
            "login_server": str(answer.get("login_server") or cloud.login_server),
            "expires_at": str(answer.get("expires_at", "")),
            "hostname": computer_hostname(str(answer.get("node_hint") or "")),
            "host": cloud.host,
        }

    def invite(self) -> dict:
        """An invite code for a device: a computer's installer or a phone's Tailscale app asks for it."""
        cloud = self._require_mesh()
        try:
            with self.control(cloud) as control:
                answer = control.invite()
        except ControlError as exc:
            raise _from_control(exc) from exc
        return {
            "code": str(answer.get("code", "")),
            "expires_at": str(answer.get("expires_at", "")),
            "login_server": str(answer.get("login_server") or cloud.login_server),
            "host": cloud.host,
            "command": f"curl -fsSL https://{cloud.host}/install.sh | sh",
        }

    def devices(self, username: str | None) -> list[dict]:
        """The devices on the mesh with the box's labels: everybody's for None, else one person's."""
        cloud = self._require_mesh()
        try:
            with self.control(cloud) as control:
                found = control.devices()
        except ControlError as exc:
            raise _from_control(exc) from exc
        labels = self.labels.all()
        out = []
        for device in found:
            device_id = str(device.get("id", ""))
            address = str(device.get("address") or "")
            label = labels.get(device_id)
            is_box = bool(address) and address == cloud.mesh_address
            owner = label.owner if label else ""
            if username is not None and owner != username:
                continue
            out.append(
                {
                    "id": device_id,
                    "label": "this cloud" if is_box else (label.text if label else ""),
                    "owner": owner,
                    "device": label.device if label else "",
                    "box": is_box,
                    "address": address,
                    "online": bool(device.get("online")),
                    "last_seen": str(device.get("last_seen") or ""),
                }
            )
        return out

    def claim_device(self, username: str, address: str, device: str) -> dict:
        """The signed-in person's computer, just joined: labelled theirs, found by its mesh address."""
        match = next((d for d in self.devices(None) if d["address"] == address and not d["box"]), None)
        if match is None:
            raise AccessError(f"no device at {address} on this cloud's mesh", 404)
        if match["owner"] and match["owner"] != username:
            raise AccessError("that device is somebody else's", 403)
        self.labels.set(match["id"], username, clean_device(device) or "a computer")
        return next(d for d in self.devices(None) if d["id"] == match["id"])

    def label_device(self, device_id: str, owner: str, device: str) -> dict:
        """An administrator saying whose a device is (a phone, say, which cannot say it itself)."""
        if not any(d["id"] == device_id for d in self.devices(None)):
            raise AccessError("no such device on this cloud's mesh", 404)
        self.labels.set(device_id, owner, device)
        return next(d for d in self.devices(None) if d["id"] == device_id)

    def remove_device(self, device_id: str, username: str | None) -> None:
        cloud = self._require_mesh()
        if username is not None and not any(d["id"] == device_id for d in self.devices(username)):
            raise AccessError("no such device of yours", 404)
        try:
            with self.control(cloud) as control:
                control.remove_device(device_id)
        except ControlError as exc:
            raise _from_control(exc) from exc
        self.labels.remove(device_id)
