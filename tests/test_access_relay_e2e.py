"""End to end against the real relay repository, when it is installed beside us.

`cloudmorrow-relay dev` runs the whole relay on this machine — the control
server, the tunnel and the router for `*.cm.localhost` — with a throwaway
CA. This test enrols a cloud there through `Access`, runs the real tunnel
client, serves the box's certificate from a local TLS upstream standing in
for Caddy, and fetches `https://<name>.cm.localhost` through the relay the
way a visitor would. Skipped where the relay is not installed; point
CLOUDMORROW_RELAY_BIN at its `cloudmorrow-relay` to run it.
"""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from cloudmorrow.server.access_ways import Access

RELAY_BIN = os.environ.get("CLOUDMORROW_RELAY_BIN") or shutil.which("cloudmorrow-relay")

pytestmark = pytest.mark.skipif(not RELAY_BIN, reason="the relay repository is not installed")


def free_base() -> int:
    """A port base whose +443, +80, +53 and +81 are all free."""
    for _ in range(50):
        base = 20000 + secrets.randbelow(30000)
        try:
            for offset in (443, 80, 53, 81):
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1", base + offset))
            return base
        except OSError:
            continue
    raise RuntimeError("no free ports")


def wait_for(port: int, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"nothing came up on {port}")


@pytest.fixture()
def relay(tmp_path):
    base = free_base()
    state = tmp_path / "relaydev"
    process = subprocess.Popen(
        [RELAY_BIN, "dev", "--dir", str(state), "--port-base", str(base)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        wait_for(base + 443)
        yield base, state / "tls"
    finally:
        process.terminate()
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            process.kill()


class Hello(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - the standard library's name
        body = f"hello from the box, for {self.headers.get('Host')}".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def box_upstream(tls: Path) -> tuple[ThreadingHTTPServer, int]:
    """Caddy's part: TLS with the box's own certificate, then an answer."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), Hello)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tls / "box.pem", tls / "box-key.pem")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def test_a_visitor_reaches_the_box_through_the_real_relay(relay, config, users, tmp_path):
    base, tls = relay
    ca = str(tls / "ca.pem")
    trust = ssl.create_default_context(cafile=ca)
    upstream, port = box_upstream(tls)

    config.access_control = f"https://relay.cm.localhost:{base + 443}"
    config.access_lan = False
    config.access_upstream_443 = f"127.0.0.1:{port}"
    config.access_caddy_dir = tmp_path / "no-caddy-here"
    access = Access(config, lambda: "The Larsens", http=httpx.Client(verify=trust))
    access.tunnel_options = {"tls": trust}
    name = "e2e-" + secrets.token_hex(3)
    try:
        cloud = access.claim(name, public=True)
        assert cloud.host == f"{name}.cm.localhost"
        assert config.public_url == f"https://{name}.cm.localhost"
        access.start()
        deadline = time.monotonic() + 15
        while access.tunnel.status()["state"] != "connected":
            assert time.monotonic() < deadline, access.tunnel.status()
            time.sleep(0.1)
        assert access.tunnel.status()["host"] == f"{name}.cm.localhost"

        # A visitor: TLS end to end with the box, through the relay.
        with httpx.Client(verify=trust) as visitor:
            answer = visitor.get(f"https://{name}.cm.localhost:{base + 443}/")
        assert answer.status_code == 200
        assert answer.text == f"hello from the box, for {name}.cm.localhost:{base + 443}"
        status = access.tunnel.status()
        assert status["bytes_in"] > 0 and status["bytes_out"] > 0

        # Public off at the control server: the relay stops routing the name.
        access.set_public(False)
        assert access.tunnel is None
        access.release()
        assert access.cloud() is None
    finally:
        access.stop()
        upstream.shutdown()
