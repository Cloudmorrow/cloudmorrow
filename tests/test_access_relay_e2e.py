"""End to end against the real relay repository, when it is installed beside us.

`cloudmorrow-relay dev` runs the whole relay on this machine — the /v1 API,
the admin API the website uses, and a fake Headscale behind it — with a
throwaway CA. This test links a box through `Access` the way a person
would (a code, approved as the website approves it), puts it on the mesh
with a fake tailscale, reads its record, makes an invite and redeems it as
a computer's installer would, and unlinks. Skipped where the relay is not
installed; point CLOUDMORROW_RELAY_BIN at its `cloudmorrow-relay` to run it.
"""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import ssl
import subprocess
import time

import httpx
import pytest

from cloudmorrow.client import meshjoin
from cloudmorrow.server.access_ways import Access
from tests.access_fakes import wire

RELAY_BIN = os.environ.get("CLOUDMORROW_RELAY_BIN") or shutil.which("cloudmorrow-relay")
ADMIN_SECRET = "e2e-admin-secret-long-enough-for-the-relay"

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


def wait_for(port: int, process: subprocess.Popen, log, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"the relay stopped: {log.read_text()[-2000:]}")
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"nothing came up on {port}: {log.read_text()[-2000:]}")


@pytest.fixture()
def relay(tmp_path):
    base = free_base()
    state = tmp_path / "relaydev"
    process = subprocess.Popen(
        [RELAY_BIN, "dev", "--dir", str(state), "--port-base", str(base)],
        # A file, not a pipe: nobody reads it as it runs, and a full pipe
        # would stop the relay; a failure shows it.
        stdout=(tmp_path / "relay.log").open("w"),
        stderr=subprocess.STDOUT,
        env={**os.environ, "RELAY_ADMIN_SECRET": ADMIN_SECRET},
    )
    try:
        wait_for(base + 443, process, tmp_path / "relay.log")
        yield f"https://relay.cm.localhost:{base + 443}", state / "tls" / "ca.pem"
    finally:
        process.terminate()
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            process.kill()


def test_a_box_links_joins_invites_and_unlinks_through_the_real_relay(relay, config, users, tmp_path):
    control, ca = relay
    trust = ssl.create_default_context(cafile=str(ca))
    config.access_control = control
    config.access_lan = False
    access = Access(config, lambda: "The Larsens")
    wire(access, tmp_path)  # the fake tailscale and Caddy; the relay stays real
    access.http = httpx.Client(verify=trust)
    name = "e2e-" + secrets.token_hex(3)

    shown = access.link()
    assert access.poll_once() == "waiting"
    with httpx.Client(verify=trust) as website:
        approved = website.post(
            f"{control}/admin/v1/links/{shown['code']}/approve",
            headers={"Authorization": f"Bearer {ADMIN_SECRET}"},
            json={"account": "acct_e2e", "name": name},
        )
    assert approved.status_code in (200, 201), approved.text
    assert access.poll_once() == "linked"
    cloud = access.cloud()
    assert cloud.host == f"{name}.cm.localhost" and cloud.set_up, access.setup_error
    assert cloud.acme and cloud.acme.get("username")
    assert config.public_url == f"https://{name}.cm.localhost"

    # Its own record, as every ten minutes.
    assert access.refresh().name == name

    # An invite, redeemed the way a computer's installer does it.
    invite = access.invite()
    assert len(invite["code"]) == 6
    with httpx.Client(verify=trust) as computer:
        key = meshjoin.redeem(f"https://{name}.cm.localhost", invite["code"], access_control=control, http=computer)
    assert key["key"] and key["login_server"]
    assert isinstance(access.devices(None), list)

    access.unlink()
    assert access.cloud() is None and config.public_url == ""
