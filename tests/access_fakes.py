"""Fakes for reaching a cloud: a control server, a relay speaking cmtunnel/1, a tailscale.

The real ones live in the Cloudmorrow/relay repository and on the internet;
these are the contract in docs/HOSTING.md, small enough to read, so the
core is tested against what it was promised rather than against whatever
the relay happens to do this week.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import stat
import struct
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request

from cloudmorrow.server.access_tunnel import (
    CLOSE,
    DATA,
    HEADER,
    INITIAL_WINDOW,
    MAX_DATA,
    OPEN,
    PING,
    PONG,
    WINDOW,
    frame,
)

ZONE = "cloudmorrow.test"
RELAY_HOST = "relay.cloudmorrow.test"
LOGIN_SERVER = "https://mesh.cloudmorrow.test"
RESERVED = {"www", "relay", "mesh", "api", "mail"}


# -- the control server ------------------------------------------------------------
@dataclass
class FakeCloud:
    cloud_id: str
    token: str
    name: str
    public: bool = True
    mesh_address: str = ""
    devices: list[dict] = field(default_factory=list)
    keys: list[dict] = field(default_factory=list)
    codes: list[dict] = field(default_factory=list)
    acme: dict | None = None


class FakeControl:
    """The /v1 API, in memory. `app` is the FastAPI app; the rest is for tests to look at."""

    def __init__(self) -> None:
        self.clouds: dict[str, FakeCloud] = {}
        self.calls: list[tuple[str, str, dict]] = []
        self.app = self._build()

    def by_name(self, name: str) -> FakeCloud | None:
        return next((c for c in self.clouds.values() if c.name == name), None)

    def join(self, key: str, name: str, address: str) -> dict:
        """What a device does with a key: it appears in the cloud's devices, labelled."""
        for cloud in self.clouds.values():
            for minted in cloud.keys:
                if minted["key"] == key and not minted.get("used"):
                    minted["used"] = True
                    device = {
                        "id": secrets.token_hex(4),
                        "name": name,
                        "for": minted["for"],
                        "address": address,
                        "online": True,
                        "last_seen": "2026-09-27T12:00:00+00:00",
                    }
                    if minted.get("owner"):
                        device["owner"] = minted["owner"]
                    cloud.devices.append(device)
                    return device
        raise KeyError(key)

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

        def record_of(cloud: FakeCloud) -> dict:
            return {
                "cloud_id": cloud.cloud_id,
                "name": cloud.name,
                "zone": ZONE,
                "public_host": f"{cloud.name}.{ZONE}",
                "public": cloud.public,
                "connected_since": None,
                "bytes_in": 0,
                "bytes_out": 0,
                "mesh_address": cloud.mesh_address,
                "devices": len(cloud.devices),
            }

        def check_name(name: str) -> str:
            import re

            if not re.match(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$", name) or name in RESERVED:
                raise HTTPException(422, "that name cannot be used")
            if control.by_name(name) is not None:
                raise HTTPException(409, "that name is taken")
            return name

        app.router.dependencies.append(Depends(record))

        @app.post("/v1/clouds", status_code=201)
        async def claim(request: Request) -> dict:
            body = await request.json()
            name = check_name(str(body.get("name", "")))
            cloud = FakeCloud(
                cloud_id="c_" + secrets.token_hex(4),
                token="tok_" + secrets.token_hex(8),
                name=name,
                public=bool(body.get("public", True)),
            )
            control.clouds[cloud.token] = cloud
            return {
                "cloud_id": cloud.cloud_id,
                "token": cloud.token,
                "name": name,
                "zone": ZONE,
                "public_host": f"{name}.{ZONE}",
                "relay_host": RELAY_HOST,
                "login_server": LOGIN_SERVER,
            }

        @app.get("/v1/clouds/me")
        def get_me(cloud: FakeCloud = Depends(me)) -> dict:
            return record_of(cloud)

        @app.patch("/v1/clouds/me")
        async def patch_me(request: Request, cloud: FakeCloud = Depends(me)) -> dict:
            body = await request.json()
            if "name" in body and body["name"] != cloud.name:
                cloud.name = check_name(str(body["name"]))
            if "public" in body:
                cloud.public = bool(body["public"])
            return record_of(cloud)

        @app.delete("/v1/clouds/me", status_code=204)
        def delete_me(cloud: FakeCloud = Depends(me)) -> None:
            control.clouds.pop(cloud.token, None)

        @app.post("/v1/clouds/me/mesh/keys", status_code=201)
        async def keys(request: Request, cloud: FakeCloud = Depends(me)) -> dict:
            body = await request.json()
            minted = {
                "key": "hskey-" + secrets.token_hex(12),
                "for": body.get("for", ""),
                "owner": body.get("owner", ""),
            }
            cloud.keys.append(minted)
            return {
                "key": minted["key"],
                "login_server": LOGIN_SERVER,
                "expires_at": "2026-09-27T12:10:00+00:00",
            }

        @app.post("/v1/clouds/me/mesh/pair", status_code=201)
        async def pair(request: Request, cloud: FakeCloud = Depends(me)) -> dict:
            body = await request.json()
            code = secrets.token_hex(3).upper()
            cloud.codes.append({"code": code, "for": body.get("for", ""), "owner": body.get("owner", "")})
            return {"code": code, "expires_at": "2026-09-27T12:10:00+00:00", "login_server": LOGIN_SERVER}

        @app.get("/v1/clouds/me/mesh/devices")
        def devices(cloud: FakeCloud = Depends(me)) -> list[dict]:
            # Only `for` for devices minted without an owner: a relay that
            # keeps just the label must still say whose a device is.
            return cloud.devices

        @app.delete("/v1/clouds/me/mesh/devices/{device_id}", status_code=204)
        def remove(device_id: str, cloud: FakeCloud = Depends(me)) -> None:
            before = len(cloud.devices)
            cloud.devices = [d for d in cloud.devices if d["id"] != device_id]
            if len(cloud.devices) == before:
                raise HTTPException(404, "no such device")

        @app.put("/v1/clouds/me/mesh/address")
        async def address(request: Request, cloud: FakeCloud = Depends(me)) -> dict:
            cloud.mesh_address = str((await request.json()).get("address", ""))
            return {"address": cloud.mesh_address}

        @app.post("/v1/acme-dns/register", status_code=201)
        def acme(cloud: FakeCloud = Depends(me)) -> dict:
            cloud.acme = {
                "username": "u-" + secrets.token_hex(4),
                "password": "p-" + secrets.token_hex(8),
                "fulldomain": f"_acme-challenge.{cloud.name}.{ZONE}",
                "server_url": f"https://relay.{ZONE}/v1/acme-dns",
                "subdomain": "x",
                "allowfrom": [],
            }
            return cloud.acme

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
    out = {"BackendState": state["BackendState"], "Self": {"HostName": "cloud", "TailscaleIPs": [state["ip"], "fd7a::7"] if state["BackendState"] == "Running" else []}}
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


def fake_tailscale(directory: Path, state: str = "NeedsLogin") -> Path:
    """A `tailscale` on a PATH of its own. Returns the directory to put first on PATH."""
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "tailscale"
    script.write_text(FAKE_TAILSCALE, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (directory / "tailscale-state.json").write_text(
        json.dumps({"BackendState": state, "ip": "100.64.0.7"}), encoding="utf-8"
    )
    return directory


def tailscale_calls(directory: Path) -> list[str]:
    log = directory / "tailscale-calls.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


# -- the relay ---------------------------------------------------------------------
class RelayConn:
    """One box's tunnel, from the relay's side: frames in, by stream, and a way to send."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self.streams: dict[int, asyncio.Queue] = {}
        self.control: asyncio.Queue = asyncio.Queue()
        self.windows: dict[int, int] = {}
        self.window_events: dict[int, asyncio.Event] = {}
        self.closed = asyncio.Event()
        self.lock = asyncio.Lock()
        self.task = asyncio.ensure_future(self._read())

    def queue(self, stream: int) -> asyncio.Queue:
        return self.streams.setdefault(stream, asyncio.Queue())

    async def _read(self) -> None:
        try:
            while True:
                kind, stream, length = HEADER.unpack(await self.reader.readexactly(HEADER.size))
                payload = await self.reader.readexactly(length) if length else b""
                if kind == WINDOW:
                    self.windows[stream] = self.windows.get(stream, INITIAL_WINDOW) + struct.unpack(">I", payload)[0]
                    self.window_events.setdefault(stream, asyncio.Event()).set()
                if kind in (PING, PONG) or stream == 0:
                    await self.control.put((kind, stream, payload))
                else:
                    await self.queue(stream).put((kind, payload))
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self.closed.set()

    async def send(self, kind: int, stream: int, payload: bytes = b"") -> None:
        async with self.lock:
            self.writer.write(frame(kind, stream, payload))
            await self.writer.drain()

    async def open(self, stream: int, port: int = 443, remote: str = "203.0.113.9:51000") -> None:
        self.windows[stream] = INITIAL_WINDOW
        await self.send(OPEN, stream, json.dumps({"port": port, "remote": remote}).encode())

    async def next(self, stream: int, timeout: float = 5.0) -> tuple[int, bytes]:
        return await asyncio.wait_for(self.queue(stream).get(), timeout)

    async def read_until_close(self, stream: int, timeout: float = 5.0) -> bytes:
        data = b""
        while True:
            kind, payload = await self.next(stream, timeout)
            if kind == DATA:
                data += payload
            elif kind == CLOSE:
                return data

    def abort(self) -> None:
        self.writer.transport.abort()


class FakeRelay:
    """A relay: it takes tunnels, and with `serve_visitors` it takes visitors as well.

    `tokens` is cloud_id → token. A wrong one is answered `NO`.
    """

    def __init__(self, tokens: dict[str, str], host: str = f"larsens.{ZONE}") -> None:
        self.tokens = tokens
        self.host = host
        self.conns: asyncio.Queue[RelayConn] = asyncio.Queue()
        self.hellos: list[str] = []
        self.server: asyncio.base_events.Server | None = None
        self.port = 0
        self.silent = False

    async def start(self) -> FakeRelay:
        self.server = await asyncio.start_server(self._on_tunnel, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        if self.server is not None:
            self.server.close()

    async def _on_tunnel(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        line = (await reader.readline()).decode().strip()
        self.hellos.append(line)
        parts = line.split(" ")
        if len(parts) != 3 or parts[0] != "CMTUNNEL/1" or self.tokens.get(parts[1]) != parts[2]:
            writer.write(b"NO unknown cloud or wrong token\n")
            await writer.drain()
            writer.close()
            return
        writer.write(f"OK {self.host}\n".encode())
        await writer.drain()
        await self.conns.put(RelayConn(reader, writer))

    async def next_conn(self, timeout: float = 10.0) -> RelayConn:
        return await asyncio.wait_for(self.conns.get(), timeout)

    async def serve_visitors(self, conn: RelayConn, port: int = 443) -> int:
        """Listen for visitors; each becomes an OPEN on *conn*, spliced both ways."""
        counter = iter(range(1, 1 << 30))

        async def visitor(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            stream = next(counter)
            await conn.open(stream, port)

            async def up() -> None:
                while True:
                    while conn.windows.get(stream, 0) <= 0:
                        event = conn.window_events.setdefault(stream, asyncio.Event())
                        event.clear()
                        await event.wait()
                    data = await reader.read(min(MAX_DATA, conn.windows[stream]))
                    if not data:
                        await conn.send(CLOSE, stream)
                        return
                    conn.windows[stream] -= len(data)
                    await conn.send(DATA, stream, data)

            async def down() -> None:
                while True:
                    kind, payload = await conn.next(stream, timeout=30)
                    if kind == DATA:
                        writer.write(payload)
                        await writer.drain()
                        await conn.send(WINDOW, stream, struct.pack(">I", len(payload)))
                    elif kind == CLOSE:
                        with contextlib.suppress(OSError):
                            writer.write_eof()
                        return

            await asyncio.gather(up(), down(), return_exceptions=True)
            writer.close()

        server = await asyncio.start_server(visitor, "127.0.0.1", 0)
        return server.sockets[0].getsockname()[1]


async def echo_server(prefix: bytes = b"") -> tuple[asyncio.base_events.Server, int]:
    """An upstream that answers everything it is sent, prefixed, until EOF, then closes."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        with contextlib.suppress(ConnectionError):
            while data := await reader.read(65536):
                writer.write(prefix + data)
                await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


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
    config.access_caddyfile.write_text(
        f"import {config.access_caddy_dir}/*.caddy\n", encoding="utf-8"
    )
    loads: list[str] = []

    def caddy_admin(request: httpx.Request) -> httpx.Response:
        loads.append(request.content.decode())
        return httpx.Response(200)

    access.caddy = Caddy(config, http=httpx.Client(transport=httpx.MockTransport(caddy_admin)))
    access.tunnel_options = {"tls": False, "backoff_first": 30, "backoff_max": 60}
    return Wired(control, ts_dir, loads)
