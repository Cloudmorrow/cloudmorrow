"""The public way in: one outbound connection to the relay, carrying everything.

A box behind a home router cannot be reached from outside, but it can
reach out. So it opens one TLS connection to the relay on port 443 and
keeps it open, and the relay sends every visitor to `<name>.<zone>` down
it. The relay never holds the cloud's certificate: what comes down the
tunnel is the visitor's own TLS, spliced here, unchanged, into Caddy on
the box, which answers it with the certificate it got for the name.

The protocol is `cmtunnel/1`, written down in docs/HOSTING.md:

* one line each way to begin — `CMTUNNEL/1 <cloud_id> <token>` from the
  box, `OK <name>.<zone>` or `NO <reason>` from the relay;
* then frames, a 9-byte header (type, stream, length; big-endian) and a
  payload: OPEN (relay → box, JSON with the port and the visitor's
  address), DATA (at most 64 KiB), CLOSE (this side is done), WINDOW
  (more bytes the other side may send), PING and PONG.

Each stream has a window of 256 KiB each way. The box grants more as it
writes what it was sent into Caddy, and sends no more than it has been
granted, so a slow visitor slows its own stream and nobody else's; the
tunnel itself is only ever written with `drain()`, so a slow relay slows
the box. A connection with nothing on it for 25 seconds gets a PING, and
one with nothing on it for 60 is dropped and made again, with a backoff
that grows to a minute and starts over once a connection has held.

It runs on a thread of its own with its own event loop, like the Quill
clock: whatever it does, it cannot hold up the API, and the API's own
loop is never asked to carry a visitor's bytes twice.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import logging
import os
import random
import ssl
import struct
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

log = logging.getLogger("cloudmorrow.access.tunnel")

PROTOCOL = "CMTUNNEL/1"
OPEN, DATA, CLOSE, WINDOW, PING, PONG = 1, 2, 3, 4, 5, 6
FRAME_NAMES = {OPEN: "OPEN", DATA: "DATA", CLOSE: "CLOSE", WINDOW: "WINDOW", PING: "PING", PONG: "PONG"}
HEADER = struct.Struct(">BII")
MAX_DATA = 64 * 1024
INITIAL_WINDOW = 256 * 1024
PING_AFTER = 25.0
DROP_AFTER = 60.0
# How long the relay has to answer the first line, and Caddy to answer a connect.
HELLO_TIMEOUT = 20.0
CONNECT_TIMEOUT = 10.0
BACKOFF_FIRST = 1.0
BACKOFF_MAX = 60.0
# What the relay says with `NO`, and what the box does about it. A wrong
# token, or public access off at the control server, will not change by
# trying again: the tunnel stops, the Access screen says why, and it starts
# again when somebody changes something there (or the server restarts).
# Too many failures from one address is a minute's wait at least. Any other
# refusal is tried again slowly.
FINAL_REFUSALS = ("unknown cloud or wrong token", "public access is off for this cloud")
TOO_MANY = "too many failed attempts"
TOO_MANY_BACKOFF = 60.0
REFUSED_BACKOFF = 300.0
# A connection that held this long was a good one: the backoff starts over.
HELD = 30.0


class ProtocolError(RuntimeError):
    """The relay sent something `cmtunnel/1` does not allow. The connection is dropped."""


class Refused(RuntimeError):
    """The relay answered `NO <reason>`."""


def frame(kind: int, stream: int, payload: bytes = b"") -> bytes:
    return HEADER.pack(kind, stream, len(payload)) + payload


def parse_address(value: str, default_port: int) -> tuple[str, int]:
    """`host:port`, `host`, or `[v6]:port`, as a pair."""
    value = value.strip()
    if value.startswith("["):
        host, _, rest = value[1:].partition("]")
        return host, int(rest.lstrip(":") or default_port)
    if value.count(":") == 1:
        host, _, port = value.partition(":")
        return host, int(port)
    return value, default_port


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


@dataclass(slots=True)
class TunnelStatus:
    """What the admin screen shows about the tunnel."""

    # off, connecting, connected, waiting (to try again), refused (and
    # trying again later), stopped (refused for good: see error)
    state: str = "off"
    host: str = ""
    connected_since: str = ""
    reconnects: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    streams: int = 0
    error: str = ""
    retry_in: float = 0.0

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "host": self.host,
            "connected_since": self.connected_since,
            "reconnects": self.reconnects,
            "bytes_in": self.bytes_in,
            "bytes_out": self.bytes_out,
            "streams": self.streams,
            "error": self.error,
            "retry_in": self.retry_in,
        }


@dataclass(slots=True)
class _Stream:
    id: int
    port: int
    remote: str
    # What the box may still send the relay on this stream.
    send_window: int = INITIAL_WINDOW
    window_open: asyncio.Event = field(default_factory=asyncio.Event)
    # What the relay sent, waiting to go into the upstream. None is its CLOSE.
    inbox: asyncio.Queue = field(default_factory=asyncio.Queue)
    writer: asyncio.StreamWriter | None = None
    closed_sent: bool = False
    task: asyncio.Task | None = None


class Tunnel:
    """The tunnel client. `start()` it on its own thread; `status()` from anywhere."""

    def __init__(
        self,
        relay: str,
        cloud_id: str,
        token: str,
        upstreams: dict[int, str],
        *,
        tls: bool | ssl.SSLContext = True,
        ping_after: float = PING_AFTER,
        drop_after: float = DROP_AFTER,
        backoff_first: float = BACKOFF_FIRST,
        backoff_max: float = BACKOFF_MAX,
        refused_backoff: float = REFUSED_BACKOFF,
        on_host: Callable[[str], object] | None = None,
    ) -> None:
        self.relay_host, self.relay_port = parse_address(relay, 443)
        self.cloud_id = cloud_id
        self.token = token
        self.upstreams = {port: parse_address(addr, port) for port, addr in upstreams.items()}
        self.tls = tls
        self.ping_after = ping_after
        self.drop_after = drop_after
        self.backoff_first = backoff_first
        self.backoff_max = backoff_max
        self.refused_backoff = refused_backoff
        # Told the name the relay says this cloud is, each time it says it.
        self.on_host = on_host
        self._status = TunnelStatus()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopping: asyncio.Event | None = None
        self._main: asyncio.Task | None = None
        self._ready = threading.Event()

    # -- from any thread --------------------------------------------------------
    def status(self) -> dict:
        with self._lock:
            return self._status.as_dict()

    def _set(self, **fields: object) -> None:
        with self._lock:
            for key, value in fields.items():
                setattr(self._status, key, value)

    def _add(self, **fields: int) -> None:
        with self._lock:
            for key, value in fields.items():
                setattr(self._status, key, getattr(self._status, key) + value)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._thread_main, name="access-tunnel", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def stop(self, timeout: float = 5.0) -> None:
        loop, stopping = self._loop, self._stopping
        if loop is not None and stopping is not None and not loop.is_closed():
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(stopping.set)
        if self._thread is not None:
            self._thread.join(timeout)
        self._thread = None
        self._set(state="off", connected_since="", streams=0, retry_in=0.0)

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        try:
            loop.run_until_complete(self._run_forever())
        finally:
            loop.close()

    # -- the loop -----------------------------------------------------------------
    async def _run_forever(self) -> None:
        self._stopping = asyncio.Event()
        self._ready.set()
        delay = self.backoff_first
        while not self._stopping.is_set():
            self._set(state="connecting", retry_in=0.0)
            began = time.monotonic()
            refused = ""
            try:
                session = asyncio.ensure_future(self.run_once())
                stopper = asyncio.ensure_future(self._stopping.wait())
                done, _ = await asyncio.wait(
                    {session, stopper}, return_when=asyncio.FIRST_COMPLETED
                )
                if stopper in done:
                    session.cancel()
                    with contextlib.suppress(BaseException):
                        await session
                    return
                stopper.cancel()
                session.result()
            except Refused as exc:
                log.warning("the relay refused the tunnel: %s", exc)
                self._set(state="refused", error=str(exc), connected_since="")
                refused = str(exc)
            except (TimeoutError, OSError, ProtocolError, ssl.SSLError) as exc:
                message = str(exc) or type(exc).__name__
                log.info("tunnel to %s dropped: %s", self.relay_host, message)
                self._set(error=message)
            if self._stopping.is_set():
                return
            if refused.startswith(FINAL_REFUSALS):
                # Not tried again: nothing here can change the answer.
                self._set(state="stopped", retry_in=0.0)
                return
            if refused.startswith(TOO_MANY):
                wait = max(TOO_MANY_BACKOFF, delay)
            elif refused:
                wait = self.refused_backoff
            elif time.monotonic() - began >= HELD:
                # It was up: try again at once-ish, and start the backoff over.
                delay = wait = self.backoff_first
            else:
                wait = delay
                delay = min(delay * 2, self.backoff_max)
            if not refused:
                self._set(state="waiting", connected_since="", streams=0)
            # Full jitter, so a relay coming back is not met by every box at once.
            pause = random.uniform(wait / 2, wait)
            self._set(retry_in=round(pause, 1))
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), pause)

    async def run_once(self) -> None:
        """One connection, from the first line to the drop. Returns when the relay closes it."""
        context: ssl.SSLContext | None
        if self.tls is True:
            context = ssl.create_default_context()
        elif isinstance(self.tls, ssl.SSLContext):
            context = self.tls
        else:
            context = None
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                self.relay_host,
                self.relay_port,
                ssl=context,
                server_hostname=self.relay_host if context else None,
            ),
            HELLO_TIMEOUT,
        )
        session = _Session(self, reader, writer)
        try:
            await session.run()
        finally:
            await session.close()


class _Session:
    """One connection to the relay, and the streams on it."""

    def __init__(
        self, tunnel: Tunnel, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.tunnel = tunnel
        self.reader = reader
        self.writer = writer
        self.streams: dict[int, _Stream] = {}
        self.send_lock = asyncio.Lock()
        self.last_heard = time.monotonic()
        self.last_ping = 0.0

    async def run(self) -> None:
        tunnel = self.tunnel
        self.writer.write(f"{PROTOCOL} {tunnel.cloud_id} {tunnel.token}\n".encode())
        await self.writer.drain()
        line = await asyncio.wait_for(self.reader.readline(), HELLO_TIMEOUT)
        if not line:
            raise ProtocolError("the relay closed the connection before answering")
        answer = line.decode("utf-8", "replace").strip()
        word, _, rest = answer.partition(" ")
        if word == "NO":
            raise Refused(rest or "no reason given")
        if word != "OK" or not rest:
            raise ProtocolError(f"the relay answered {answer[:80]!r}")
        tunnel._set(
            state="connected", host=rest, connected_since=_now(), error="", retry_in=0.0
        )
        if tunnel.on_host is not None:
            try:
                tunnel.on_host(rest)
            except Exception:  # the tunnel does not care what the listener thinks
                log.exception("on_host failed")
        log.info("tunnel to %s is up as %s", tunnel.relay_host, rest)
        self.last_heard = time.monotonic()
        keepalive = asyncio.ensure_future(self.keepalive())
        try:
            await self.read_frames()
        finally:
            keepalive.cancel()
            with contextlib.suppress(BaseException):
                await keepalive
            tunnel._add(reconnects=1)

    async def close(self) -> None:
        for stream in list(self.streams.values()):
            self._forget(stream)
            if stream.task is not None:
                stream.task.cancel()
        self.tunnel._set(streams=0)
        with contextlib.suppress(Exception):
            self.writer.close()
            await asyncio.wait_for(self.writer.wait_closed(), 2)

    # -- writing ------------------------------------------------------------------
    async def send(self, kind: int, stream: int, payload: bytes = b"") -> None:
        async with self.send_lock:
            self.writer.write(frame(kind, stream, payload))
            await self.writer.drain()

    # -- keepalive ----------------------------------------------------------------
    async def keepalive(self) -> None:
        tick = max(0.05, min(1.0, self.tunnel.ping_after / 5))
        while True:
            await asyncio.sleep(tick)
            now = time.monotonic()
            silent = now - self.last_heard
            if silent >= self.tunnel.drop_after:
                # Closing the transport ends read_frames, which ends the session.
                log.info("nothing from the relay for %.0f seconds; dropping", silent)
                self.writer.transport.abort()
                return
            if silent >= self.tunnel.ping_after and now - self.last_ping >= self.tunnel.ping_after:
                self.last_ping = now
                with contextlib.suppress(Exception):
                    await self.send(PING, 0, os.urandom(8))

    # -- reading ------------------------------------------------------------------
    async def read_frames(self) -> None:
        while True:
            try:
                header = await self.reader.readexactly(HEADER.size)
            except asyncio.IncompleteReadError:
                return
            kind, stream_id, length = HEADER.unpack(header)
            if length > MAX_DATA:
                raise ProtocolError(f"a frame of {length} bytes is over the limit")
            try:
                payload = await self.reader.readexactly(length) if length else b""
            except asyncio.IncompleteReadError:
                return
            self.last_heard = time.monotonic()
            await self.dispatch(kind, stream_id, payload)

    async def dispatch(self, kind: int, stream_id: int, payload: bytes) -> None:
        if kind == OPEN:
            self.open(stream_id, payload)
        elif kind == DATA:
            stream = self.streams.get(stream_id)
            self.tunnel._add(bytes_in=len(payload))
            if stream is not None and payload:
                stream.inbox.put_nowait(payload)
        elif kind == CLOSE:
            stream = self.streams.get(stream_id)
            if stream is not None:
                stream.inbox.put_nowait(None)
        elif kind == WINDOW:
            if len(payload) != 4:
                raise ProtocolError("a WINDOW frame carries four bytes")
            stream = self.streams.get(stream_id)
            if stream is not None:
                stream.send_window += struct.unpack(">I", payload)[0]
                stream.window_open.set()
        elif kind == PING:
            await self.send(PONG, stream_id, payload)
        elif kind == PONG:
            pass
        # Any other type is from a later protocol, and is ignored: an old box
        # keeps working against a newer relay that sends it something new.

    # -- streams ------------------------------------------------------------------
    def open(self, stream_id: int, payload: bytes) -> None:
        try:
            request = json.loads(payload or b"{}")
            port = int(request.get("port", 443))
            remote = str(request.get("remote", ""))
        except (ValueError, TypeError, AttributeError):
            port, remote = 443, ""
        if stream_id in self.streams:
            raise ProtocolError(f"stream {stream_id} was opened twice")
        stream = _Stream(id=stream_id, port=port, remote=remote)
        stream.window_open.set()
        self.streams[stream_id] = stream
        self.tunnel._set(streams=len(self.streams))
        stream.task = asyncio.ensure_future(self.serve(stream))

    def _forget(self, stream: _Stream) -> None:
        self.streams.pop(stream.id, None)
        self.tunnel._set(streams=len(self.streams))
        if stream.writer is not None:
            with contextlib.suppress(Exception):
                stream.writer.close()

    async def _close(self, stream: _Stream) -> None:
        if not stream.closed_sent:
            stream.closed_sent = True
            with contextlib.suppress(Exception):
                await self.send(CLOSE, stream.id)

    async def serve(self, stream: _Stream) -> None:
        upstream = self.tunnel.upstreams.get(stream.port)
        try:
            if upstream is None:
                raise OSError(f"nothing on this box answers port {stream.port}")
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(*upstream), CONNECT_TIMEOUT
            )
        except (TimeoutError, OSError) as exc:
            log.info("stream %d from %s: cannot reach %s: %s", stream.id, stream.remote, upstream, exc)
            await self._close(stream)
            self._forget(stream)
            return
        stream.writer = writer
        up = asyncio.ensure_future(self.pump_up(stream, writer))
        down = asyncio.ensure_future(self.pump_down(stream, reader))
        # CLOSE is a half-close. The relay's ends what goes into Caddy (a
        # write EOF) and the box keeps sending what Caddy still says; the
        # stream is over when Caddy's side ends and the box has sent its own
        # CLOSE, which the relay answers by closing the visitor — it need not
        # send anything more, so the box does not wait for it.
        try:
            pending = {up, down}
            while down in pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                if up in done and up.exception() is not None:
                    raise up.exception()
            down.result()
        except Exception as exc:  # one side broke: the stream is over
            log.debug("stream %d ended: %s", stream.id, exc)
            await self._close(stream)
        finally:
            up.cancel()
            down.cancel()
            self._forget(stream)

    async def pump_up(self, stream: _Stream, writer: asyncio.StreamWriter) -> None:
        """What the relay sends, into Caddy; a WINDOW back for each piece written."""
        while True:
            chunk = await stream.inbox.get()
            if chunk is None:
                if writer.can_write_eof():
                    with contextlib.suppress(OSError):
                        writer.write_eof()
                return
            writer.write(chunk)
            await writer.drain()
            await self.send(WINDOW, stream.id, struct.pack(">I", len(chunk)))

    async def pump_down(self, stream: _Stream, reader: asyncio.StreamReader) -> None:
        """What Caddy answers, to the relay; never more than the window allows."""
        while True:
            while stream.send_window <= 0:
                stream.window_open.clear()
                await stream.window_open.wait()
            data = await reader.read(min(MAX_DATA, stream.send_window))
            if not data:
                await self._close(stream)
                return
            stream.send_window -= len(data)
            self.tunnel._add(bytes_out=len(data))
            await self.send(DATA, stream.id, data)
