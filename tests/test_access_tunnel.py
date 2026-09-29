"""The tunnel client, end to end against a fake relay speaking cmtunnel/1."""

from __future__ import annotations

import asyncio
import json
import struct
import time

import pytest

from cloudmorrow.server.access_tunnel import (
    CLOSE,
    DATA,
    INITIAL_WINDOW,
    MAX_DATA,
    PING,
    PONG,
    WINDOW,
    Tunnel,
    frame,
    parse_address,
)
from tests.access_fakes import FakeRelay, echo_server

CLOUD, TOKEN = "c_1", "tok_secret"


def make_tunnel(relay: FakeRelay, upstream_port: int, **options) -> Tunnel:
    options.setdefault("backoff_first", 0.05)
    options.setdefault("backoff_max", 0.2)
    return Tunnel(
        f"127.0.0.1:{relay.port}",
        CLOUD,
        options.pop("token", TOKEN),
        {443: f"127.0.0.1:{upstream_port}", 80: "127.0.0.1:1"},
        tls=False,
        **options,
    )


async def until(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition never came true")
        await asyncio.sleep(0.02)


def test_addresses_parse() -> None:
    assert parse_address("relay.example.com", 443) == ("relay.example.com", 443)
    assert parse_address("127.0.0.1:9443", 443) == ("127.0.0.1", 9443)
    assert parse_address("[::1]:80", 443) == ("::1", 80)
    assert frame(DATA, 7, b"hi") == b"\x02\x00\x00\x00\x07\x00\x00\x00\x02hi"


async def test_hello_and_a_visitor_spliced_through_to_the_upstream() -> None:
    relay = await FakeRelay({CLOUD: TOKEN}).start()
    upstream, port = await echo_server()
    tunnel = make_tunnel(relay, port)
    tunnel.start()
    try:
        conn = await relay.next_conn()
        assert relay.hellos == [f"CMTUNNEL/1 {CLOUD} {TOKEN}"]
        await until(lambda: tunnel.status()["state"] == "connected")
        assert tunnel.status()["host"] == "larsens.cloudmorrow.test"
        assert tunnel.status()["connected_since"]

        visitors = await relay.serve_visitors(conn)
        reader, writer = await asyncio.open_connection("127.0.0.1", visitors)
        writer.write(b"GET / HTTP/1.1\r\n\r\n")
        await writer.drain()
        assert await asyncio.wait_for(reader.readexactly(18), 5) == b"GET / HTTP/1.1\r\n\r\n"
        writer.write_eof()
        assert await asyncio.wait_for(reader.read(), 5) == b""
        writer.close()
        await until(lambda: tunnel.status()["streams"] == 0)
        status = tunnel.status()
        assert status["bytes_in"] == 18 and status["bytes_out"] == 18
    finally:
        tunnel.stop()
        upstream.close()
        await relay.stop()


async def test_open_sends_the_first_data_before_the_upstream_answers_and_close_ends_it() -> None:
    relay = await FakeRelay({CLOUD: TOKEN}).start()
    upstream, port = await echo_server()
    tunnel = make_tunnel(relay, port)
    tunnel.start()
    try:
        conn = await relay.next_conn()
        await conn.open(1, 443, "198.51.100.4:4000")
        # The bytes the relay already read (a TLS ClientHello) come straight after OPEN.
        await conn.send(DATA, 1, b"hello")
        await conn.send(CLOSE, 1)
        data = await conn.read_until_close(1)
        assert data == b"hello"
        # A WINDOW came back for the five bytes written into the upstream
        # (this fake counts grants on top of the first window).
        await until(lambda: conn.windows[1] == INITIAL_WINDOW + 5)
    finally:
        tunnel.stop()
        upstream.close()
        await relay.stop()


async def test_an_open_for_a_port_nothing_answers_is_closed_at_once() -> None:
    relay = await FakeRelay({CLOUD: TOKEN}).start()
    tunnel = make_tunnel(relay, 1)  # nothing listens on port 1
    tunnel.start()
    try:
        conn = await relay.next_conn()
        await conn.open(3, 80)
        kind, _ = await conn.next(3)
        assert kind == CLOSE
        await until(lambda: tunnel.status()["streams"] == 0)
    finally:
        tunnel.stop()
        await relay.stop()


async def test_the_box_never_sends_past_its_window_and_resumes_on_window() -> None:
    relay = await FakeRelay({CLOUD: TOKEN}).start()

    # An upstream that pours out a megabyte as soon as it is connected to.
    payload = bytes(range(256)) * 4096  # 1 MiB

    async def pour(reader, writer):
        writer.write(payload)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(pour, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    tunnel = make_tunnel(relay, port)
    tunnel.start()
    try:
        conn = await relay.next_conn()
        await conn.open(5)
        received = b""
        # Without a WINDOW, exactly the first 256 KiB, then nothing.
        while len(received) < INITIAL_WINDOW:
            kind, data = await conn.next(5)
            assert kind == DATA and len(data) <= MAX_DATA
            received += data
        assert len(received) == INITIAL_WINDOW
        with pytest.raises(asyncio.TimeoutError):
            await conn.next(5, timeout=0.4)
        # Granting more lets exactly that much through.
        await conn.send(WINDOW, 5, struct.pack(">I", 100_000))
        more = b""
        while len(more) < 100_000:
            kind, data = await conn.next(5)
            more += data
        assert len(more) == 100_000
        with pytest.raises(asyncio.TimeoutError):
            await conn.next(5, timeout=0.3)
        # And everything, once granted, arrives in order and ends with CLOSE.
        await conn.send(WINDOW, 5, struct.pack(">I", len(payload)))
        rest = await conn.read_until_close(5)
        assert received + more + rest == payload
    finally:
        tunnel.stop()
        server.close()
        await relay.stop()


async def test_the_box_grants_window_as_it_writes_into_the_upstream() -> None:
    relay = await FakeRelay({CLOUD: TOKEN}).start()
    upstream, port = await echo_server()
    tunnel = make_tunnel(relay, port)
    tunnel.start()
    try:
        conn = await relay.next_conn()
        await conn.open(9)
        await conn.send(DATA, 9, b"x" * 1000)
        await until(lambda: conn.windows.get(9, INITIAL_WINDOW) == INITIAL_WINDOW + 1000)
    finally:
        tunnel.stop()
        upstream.close()
        await relay.stop()


async def test_ping_is_answered_with_the_same_bytes() -> None:
    relay = await FakeRelay({CLOUD: TOKEN}).start()
    tunnel = make_tunnel(relay, 1)
    tunnel.start()
    try:
        conn = await relay.next_conn()
        await conn.send(PING, 0, b"12345678")
        kind, _, payload = await asyncio.wait_for(conn.control.get(), 5)
        assert (kind, payload) == (PONG, b"12345678")
    finally:
        tunnel.stop()
        await relay.stop()


async def test_silence_brings_a_ping_and_then_a_drop_and_a_reconnect() -> None:
    relay = await FakeRelay({CLOUD: TOKEN}).start()
    tunnel = make_tunnel(relay, 1, ping_after=0.2, drop_after=0.6)
    tunnel.start()
    try:
        first = await relay.next_conn()
        kind, _, payload = await asyncio.wait_for(first.control.get(), 3)
        assert kind == PING and len(payload) == 8
        # Not answered: the box gives up on the connection and makes another.
        second = await relay.next_conn(timeout=5)
        assert second is not first
        await asyncio.wait_for(first.closed.wait(), 3)
        await until(lambda: tunnel.status()["reconnects"] >= 1)
        await until(lambda: tunnel.status()["state"] == "connected")
    finally:
        tunnel.stop()
        await relay.stop()


async def test_a_dropped_connection_is_made_again() -> None:
    relay = await FakeRelay({CLOUD: TOKEN}).start()
    tunnel = make_tunnel(relay, 1)
    tunnel.start()
    try:
        first = await relay.next_conn()
        first.abort()
        second = await relay.next_conn()
        assert second is not first
        assert relay.hellos.count(f"CMTUNNEL/1 {CLOUD} {TOKEN}") == 2
    finally:
        tunnel.stop()
        await relay.stop()


async def test_a_wrong_token_stops_the_tunnel_and_says_why() -> None:
    relay = await FakeRelay({CLOUD: TOKEN}).start()
    tunnel = make_tunnel(relay, 1, token="wrong")
    tunnel.start()
    try:
        await until(lambda: tunnel.status()["state"] == "stopped")
        assert tunnel.status()["error"] == "unknown cloud or wrong token"
        await until(lambda: not tunnel.running)
        assert len(relay.hellos) == 1
    finally:
        tunnel.stop()
        await relay.stop()
    assert tunnel.status()["state"] == "off"


async def refuse_with(reason: bytes) -> tuple[list[str], int]:
    hellos: list[str] = []

    async def handle(reader, writer):
        hellos.append((await reader.readline()).decode().strip())
        writer.write(b"NO " + reason + b"\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return hellos, server


@pytest.mark.parametrize(
    ("reason", "state", "least"),
    [
        (b"too many failed attempts, wait a minute", "refused", 60),
        (b"not a cmtunnel/1 handshake", "refused", 30),
        (b"public access is off for this cloud", "stopped", 0),
    ],
)
async def test_each_refusal_is_waited_out_as_the_contract_says(reason, state, least) -> None:
    hellos, server = await refuse_with(reason)
    port = server.sockets[0].getsockname()[1]
    tunnel = Tunnel(f"127.0.0.1:{port}", CLOUD, TOKEN, {443: "127.0.0.1:1"}, tls=False,
                    backoff_first=0.05, refused_backoff=60)
    tunnel.start()
    try:
        await until(lambda: tunnel.status()["state"] == state)
        assert tunnel.status()["error"] == reason.decode()
        if least:
            await until(lambda: tunnel.status()["retry_in"] > 0)
            assert tunnel.status()["retry_in"] >= least / 2  # full jitter: [wait/2, wait]
        await asyncio.sleep(0.3)
        assert len(hellos) == 1
    finally:
        tunnel.stop()
        server.close()


async def test_half_close_keeps_the_answer_coming_until_the_upstream_ends() -> None:
    """The relay's CLOSE ends what goes in; what Caddy still says comes out, then the box's CLOSE."""
    relay = await FakeRelay({CLOUD: TOKEN}).start()

    async def answer_after_eof(reader, writer):
        asked = await reader.read()  # until the write EOF the relay's CLOSE caused
        await asyncio.sleep(0.1)
        writer.write(b"answer to " + asked)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(answer_after_eof, "127.0.0.1", 0)
    tunnel = make_tunnel(relay, server.sockets[0].getsockname()[1])
    tunnel.start()
    try:
        conn = await relay.next_conn()
        await conn.open(21)
        await conn.send(DATA, 21, b"question")
        await conn.send(CLOSE, 21)
        assert await conn.read_until_close(21) == b"answer to question"
        # The relay sends nothing more; the box forgets the stream anyway.
        await until(lambda: tunnel.status()["streams"] == 0)
    finally:
        tunnel.stop()
        server.close()
        await relay.stop()


async def test_the_box_forgets_a_stream_it_closed_without_waiting_for_the_relay() -> None:
    relay = await FakeRelay({CLOUD: TOKEN}).start()

    async def say_and_go(reader, writer):
        writer.write(b"bye")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(say_and_go, "127.0.0.1", 0)
    tunnel = make_tunnel(relay, server.sockets[0].getsockname()[1])
    tunnel.start()
    try:
        conn = await relay.next_conn()
        await conn.open(22)
        assert await conn.read_until_close(22) == b"bye"
        await until(lambda: tunnel.status()["streams"] == 0)
    finally:
        tunnel.stop()
        server.close()
        await relay.stop()


async def test_nothing_listening_is_retried_with_backoff() -> None:
    relay = await FakeRelay({CLOUD: TOKEN}).start()
    port = relay.port
    await relay.stop()
    relay.server.close()
    await relay.server.wait_closed()
    tunnel = Tunnel(f"127.0.0.1:{port}", CLOUD, TOKEN, {443: "127.0.0.1:1"}, tls=False,
                    backoff_first=0.05, backoff_max=0.1)
    tunnel.start()
    try:
        await until(lambda: tunnel.status()["state"] == "waiting")
        assert tunnel.status()["error"]
    finally:
        tunnel.stop()


async def test_the_app_starts_the_tunnel_when_public_access_is_on(config, users, tmp_path) -> None:
    """Claimed from Administration, started with the server, shown on the admin screen."""
    from fastapi.testclient import TestClient

    from cloudmorrow.server.app import create_app
    from tests.access_fakes import wire
    from tests.conftest import ADMIN, token_for

    app = create_app(config)
    access = app.state.cloudmorrow.access
    fakes = wire(access, tmp_path)
    access.tunnel_options = {"tls": False, "backoff_first": 0.05, "backoff_max": 0.2}
    cloud = access.claim("larsens", public=True)
    remote = fakes.control.by_name("larsens")
    relay = await FakeRelay({cloud.cloud_id: remote.token}).start()
    # Dialled at the control server's host and port.
    config.access_control = f"http://127.0.0.1:{relay.port}"
    upstream, port = await echo_server()
    config.access_upstream_443 = f"127.0.0.1:{port}"

    with TestClient(app) as client:
        try:
            conn = await relay.next_conn()
            assert relay.hellos == [f"CMTUNNEL/1 {cloud.cloud_id} {remote.token}"]
            await until(lambda: access.tunnel.status()["state"] == "connected")
            admin = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
            tunnel = client.get("/api/access", headers=admin).json()["public"]["tunnel"]
            assert tunnel["state"] == "connected" and tunnel["host"] == "larsens.cloudmorrow.test"
            await conn.open(1)
            await conn.send(DATA, 1, b"through")
            await conn.send(CLOSE, 1)
            assert await conn.read_until_close(1) == b"through"
            # Public off stops it.
            client.put("/api/access/public", json={"on": False}, headers=admin)
            assert access.tunnel is None
            await asyncio.wait_for(conn.closed.wait(), 5)
        finally:
            upstream.close()
            await relay.stop()


async def test_open_carries_json_the_box_reads() -> None:
    # A malformed OPEN still opens a stream on 443, rather than killing the tunnel.
    relay = await FakeRelay({CLOUD: TOKEN}).start()
    upstream, port = await echo_server()
    tunnel = make_tunnel(relay, port)
    tunnel.start()
    try:
        conn = await relay.next_conn()
        await conn.send(1, 11, b"not json")
        await conn.send(DATA, 11, b"ok")
        await conn.send(CLOSE, 11)
        assert await conn.read_until_close(11) == b"ok"
        await conn.send(1, 12, json.dumps({"port": 443}).encode())
        await conn.send(CLOSE, 12)
        assert await conn.read_until_close(12) == b""
    finally:
        tunnel.stop()
        upstream.close()
        await relay.stop()
