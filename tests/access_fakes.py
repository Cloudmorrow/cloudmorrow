"""Fakes for reaching a cloud: the relay's /v1 API, and a tailscale.

The real relay lives in the Cloudmorrow/relay repository and on the
internet; this is the contract in docs/HOSTING.md ("The relay's API"),
small enough to read, so the core is tested against what it was promised
rather than against whatever the relay happens to do this week.

Every call is recorded with its body in `FakeControl.calls`, so a test can
say what the box told the relay — and that no username or label was in it.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import secrets
import stat
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response

ZONE = "cloudmorrow.test"
LOGIN_SERVER = "https://mesh.cloudmorrow.test"
LINK_PAGE = "https://cloudmorrow.test/link"
RESERVED = {"www", "relay", "mesh", "admin", "mail"}


def _in(minutes: float) -> str:
    return (dt.datetime.now(tz=dt.UTC) + dt.timedelta(minutes=minutes)).isoformat(timespec="seconds")


# -- the relay ----------------------------------------------------------------------
@dataclass
class FakeCloud:
    cloud_id: str
    token: str
    name: str
    mesh_address: str = ""
    devices: list[dict] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    invites: list[str] = field(default_factory=list)


@dataclass
class FakeLink:
    code: str
    poll: str
    expires_at: str
    # waiting, approved (the answer not yet collected), collected, refused
    state: str = "waiting"
    name: str = ""


class FakeControl:
    """The /v1 API, in memory. `app` is the FastAPI app; the rest is for tests to look at and steer."""

    def __init__(self) -> None:
        self.clouds: dict[str, FakeCloud] = {}
        self.links: dict[str, FakeLink] = {}
        self.calls: list[tuple[str, str, dict]] = []
        # What the next poll that finds an approved link hands over.
        self.acme = {
            "username": "u-acme",
            "password": "p-acme-secret",
            "subdomain": "sub-1",
            "server_url": f"https://relay.{ZONE}/v1/acme-dns",
        }
        self.app = self._build()

    # -- what the website and the devices do ------------------------------------------
    def by_name(self, name: str) -> FakeCloud | None:
        return next((c for c in self.clouds.values() if c.name == name), None)

    def only(self) -> FakeCloud:
        (cloud,) = self.clouds.values()
        return cloud

    def approve(self, code: str | None = None, name: str = "larsens") -> None:
        """A person entered the code on the website and picked *name*."""
        link = self.links[code] if code else next(iter(self.links.values()))
        link.state = "approved"
        link.name = name

    def refuse(self, code: str | None = None) -> None:
        link = self.links[code] if code else next(iter(self.links.values()))
        link.state = "refused"

    def rename(self, name: str) -> None:
        self.only().name = name

    def unlink_from_website(self) -> None:
        self.clouds.clear()

    def join(self, key: str, address: str) -> dict:
        """What a device does with a key: it appears in the cloud's devices, with nothing about whose."""
        for cloud in self.clouds.values():
            if key in cloud.keys:
                cloud.keys.remove(key)
                device = {
                    "id": secrets.token_hex(4),
                    "address": address,
                    "online": True,
                    "last_seen": "2026-09-29T12:00:00+00:00",
                }
                cloud.devices.append(device)
                return device
        raise KeyError(key)

    def bodies(self) -> str:
        """Everything the box ever sent the relay, as one string to search."""
        return json.dumps(self.calls)

    def _build(self) -> FastAPI:
        app = FastAPI()
        control = self

        async def record(request: Request) -> None:
            body = {}
            if request.method in ("POST", "PATCH", "PUT"):
                with contextlib.suppress(ValueError):
                    body = await request.json()
            control.calls.append((request.method, request.url.path, body))

        def me(authorization: str = Header(default="")) -> FakeCloud:
            token = authorization.removeprefix("Bearer ").strip()
            cloud = control.clouds.get(token)
            if cloud is None:
                raise HTTPException(401, "unknown token")
            return cloud

        app.router.dependencies.append(Depends(record))

        @app.post("/v1/links", status_code=201)
        def start_link() -> dict:
            code = "".join(secrets.choice("ABCDEFGHJKMNPQRSTVWXYZ") for _ in range(4))
            code += "-" + "".join(secrets.choice("0123456789") for _ in range(4))
            link = FakeLink(code=code, poll="poll_" + secrets.token_hex(8), expires_at=_in(15))
            control.links[code] = link
            return {"code": code, "poll": link.poll, "url": LINK_PAGE, "expires_at": link.expires_at, "interval": 1}

        @app.post("/v1/links/poll")
        async def poll(request: Request) -> Response:
            body = await request.json()
            link = next((k for k in control.links.values() if k.poll == body.get("poll")), None)
            if link is None or link.state in ("refused", "collected"):
                return JSONResponse({"detail": "that code is gone"}, status_code=410)
            if dt.datetime.fromisoformat(link.expires_at) <= dt.datetime.now(tz=dt.UTC):
                return JSONResponse({"detail": "that code ran out"}, status_code=410)
            if link.state == "waiting":
                return Response(status_code=202)
            link.state = "collected"
            cloud = FakeCloud(cloud_id="c_" + secrets.token_hex(4), token="tok_" + secrets.token_hex(8), name=link.name)
            control.clouds[cloud.token] = cloud
            return JSONResponse(
                {
                    "cloud_id": cloud.cloud_id,
                    "token": cloud.token,
                    "name": cloud.name,
                    "zone": ZONE,
                    "login_server": LOGIN_SERVER,
                    "acme_dns": dict(control.acme),
                }
            )

        @app.get("/v1/clouds/me")
        def get_me(cloud: FakeCloud = Depends(me)) -> dict:
            return {
                "cloud_id": cloud.cloud_id,
                "name": cloud.name,
                "zone": ZONE,
                "mesh_address": cloud.mesh_address,
                "login_server": LOGIN_SERVER,
            }

        @app.delete("/v1/clouds/me", status_code=204)
        def delete_me(cloud: FakeCloud = Depends(me)) -> None:
            control.clouds.pop(cloud.token, None)

        @app.post("/v1/clouds/me/mesh/keys", status_code=201)
        def keys(cloud: FakeCloud = Depends(me)) -> dict:
            key = "hskey-" + secrets.token_hex(12)
            cloud.keys.append(key)
            # "cloud" while the cloud has no box on the mesh: this key is the box's.
            hint = None if cloud.mesh_address else "cloud"
            return {"key": key, "login_server": LOGIN_SERVER, "expires_at": _in(10), "node_hint": hint}

        @app.post("/v1/clouds/me/mesh/invites", status_code=201)
        def invites(cloud: FakeCloud = Depends(me)) -> dict:
            code = "".join(secrets.choice("ABCDEFGHJKMNPQRSTVWXYZ23456789") for _ in range(6))
            cloud.invites.append(code)
            return {"code": code, "expires_at": _in(10), "login_server": LOGIN_SERVER}

        @app.post("/v1/invites/redeem", status_code=201)
        async def redeem(request: Request) -> dict:
            body = await request.json()
            cloud = control.by_name(str(body.get("name", "")))
            code = str(body.get("code", "")).upper()
            if cloud is None or code not in cloud.invites:
                raise HTTPException(404, "that invite is wrong or used")
            cloud.invites.remove(code)
            key = "hskey-" + secrets.token_hex(12)
            cloud.keys.append(key)
            return {"key": key, "login_server": LOGIN_SERVER, "expires_at": _in(60)}

        @app.get("/v1/clouds/me/mesh/devices")
        def devices(cloud: FakeCloud = Depends(me)) -> list[dict]:
            # The box's own node is on the list too, once it is on the mesh.
            box = [{"id": "box", "address": cloud.mesh_address, "online": True, "last_seen": ""}]
            return (box if cloud.mesh_address else []) + cloud.devices

        @app.delete("/v1/clouds/me/mesh/devices/{device_id}", status_code=204)
        def remove(device_id: str, cloud: FakeCloud = Depends(me)) -> None:
            before = len(cloud.devices)
            cloud.devices = [d for d in cloud.devices if d["id"] != device_id]
            if len(cloud.devices) == before:
                raise HTTPException(404, "no such device")

        return app


# -- tailscale ---------------------------------------------------------------------
FAKE_TAILSCALE = r"""#!/usr/bin/env python3
# A tailscale CLI for tests: keeps its state in a JSON file beside itself,
# and writes every call to a log, one line of arguments each.
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
state_path = os.path.join(here, "tailscale-state.json")
state = {"BackendState": "NeedsLogin", "ip": "100.64.0.7"}
if os.path.exists(state_path):
    state = json.load(open(state_path))
with open(os.path.join(here, "tailscale-calls.log"), "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\n")
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if cmd == "status":
    running = state["BackendState"] == "Running"
    ips = [state["ip"], "fd7a::7"] if running else []
    out = {"BackendState": state["BackendState"], "Self": {"HostName": "cloud", "TailscaleIPs": ips}}
    print(json.dumps(out)); sys.exit(0)
if cmd == "up":
    if os.environ.get("FAKE_TS_DENY"):
        print("Access denied: prefs write access denied", file=sys.stderr); sys.exit(1)
    args = sys.argv[2:]
    if "--authkey" not in args and state["BackendState"] != "Stopped":
        print("NeedsLogin: an auth key is needed", file=sys.stderr); sys.exit(1)
    state["BackendState"] = "Running"
elif cmd == "down":
    state["BackendState"] = "Stopped"
json.dump(state, open(state_path, "w"))
"""


def fake_tailscale(directory: Path, state: str = "NeedsLogin", ip: str = "100.64.0.7") -> Path:
    """A `tailscale` on a PATH of its own. Returns the directory to put first on PATH."""
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "tailscale"
    script.write_text(FAKE_TAILSCALE, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (directory / "tailscale-state.json").write_text(json.dumps({"BackendState": state, "ip": ip}), encoding="utf-8")
    return directory


def tailscale_calls(directory: Path) -> list[str]:
    log = directory / "tailscale-calls.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def env_with_path(directory: Path) -> str:
    return f"{directory}{os.pathsep}{os.environ.get('PATH', '')}"


@dataclass
class Wired:
    control: FakeControl
    tailscale_dir: Path
    caddy_loads: list[str]


def wire(access, tmp_path: Path, tailscale_state: str = "NeedsLogin") -> Wired:
    """Point an `Access` at a fake control server, a fake tailscale and a fake Caddy."""
    import httpx
    from fastapi.testclient import TestClient

    from cloudmorrow.server.access_caddy import Caddy
    from cloudmorrow.server.access_mesh import Mesh

    control = FakeControl()
    access.http = TestClient(control.app)
    ts_dir = fake_tailscale(tmp_path / "ts-bin", tailscale_state)
    access.mesh = Mesh(str(ts_dir / "tailscale"))
    config = access.config
    config.access_caddy_dir = tmp_path / "caddy"
    config.access_caddy_dir.mkdir(exist_ok=True)
    config.access_caddyfile = tmp_path / "Caddyfile"
    config.access_caddyfile.write_text(f"import {config.access_caddy_dir}/*.caddy\n", encoding="utf-8")
    loads: list[str] = []

    def caddy_admin(request: httpx.Request) -> httpx.Response:
        loads.append(request.content.decode())
        return httpx.Response(200)

    access.caddy = Caddy(config, http=httpx.Client(transport=httpx.MockTransport(caddy_admin)))
    return Wired(control, ts_dir, loads)
