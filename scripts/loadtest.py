#!/usr/bin/env python3
"""How far one cloud goes: a server, many people, and the numbers.

    python3 scripts/loadtest.py                        50 people, 200 tasks each, at 10, 50 and 100 at once
    python3 scripts/loadtest.py --users 100 --records 500 --concurrency 10,50,100,200
    python3 scripts/loadtest.py --requests 500         more requests per measurement, steadier numbers

It starts a real server — `cloudmorrow-server serve`, its own process, on a
directory it makes and takes away again — makes the accounts, installs Tasks
and Chat from the test catalog (no network), fills every account's board,
and then times the four requests an open screen makes, as so many people at
once, each as a different account:

    list      GET  /api/records/task?board=…      a board opening
    create    POST /api/records/task              a task being made
    search    GET  /api/records/task?q=…          a search: every row is unsealed until enough match
    thread    GET  /api/records/message?channel=…&_since=…   an open conversation asking for what it has not got

What it prints is a Markdown table, for docs/HOSTING.md, and the server's
memory at the end. Run it on the machine the cloud will run on: the numbers
are that machine's. Nothing here touches a cloud that exists.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "tests" / "fixtures" / "quills"
ADMIN = ("admin", "an-administrator-password")
PASSWORD = "a-long-enough-password"
NEEDLE = "lighthouse"
SEED_THREADS = 16


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--users", type=int, default=50, help="how many accounts (default 50)")
    parser.add_argument("--records", type=int, default=200, help="tasks on each account's board (default 200)")
    parser.add_argument("--messages", type=int, default=20, help="lines each account says in the channel (default 20)")
    parser.add_argument("--concurrency", default="10,50,100", help="how many at once, each level in turn")
    parser.add_argument("--requests", type=int, default=300, help="requests per measurement (default 300)")
    parser.add_argument("--port", type=int, default=0, help="where the server listens (default: a free one)")
    parser.add_argument("--keep", action="store_true", help="leave the directory and say where it is")
    parser.add_argument("--memory-limit", type=int, default=4096, help="stop if the server passes this many MB")
    args = parser.parse_args()
    levels = [int(n) for n in args.concurrency.split(",") if n.strip()]

    where = Path(tempfile.mkdtemp(prefix="cloudmorrow-load-"))
    port = args.port or free_port()
    server = start_server(where, port)
    try:
        base = f"http://127.0.0.1:{port}"
        wait_until_up(base)
        say(f"server up at {base}, pid {server.pid}")
        watch_memory(server, args.memory_limit)
        with httpx.Client(base_url=base, timeout=60) as admin:
            admin_token = setup(admin)
            admin.headers["Authorization"] = f"Bearer {admin_token}"
            for quill in ("tasks", "chat"):
                admin.post("/api/quills", json={"id": quill}).raise_for_status()
            names = [f"person{n:04d}" for n in range(args.users)]
            tokens = make_people(admin, base, names)
            channel = admin.post(
                "/api/records/channel", json={"fields": {"name": "everyone"}, "scope": "public"}
            ).json()["id"]
        say(f"{len(tokens)} accounts signed in")

        t0 = time.monotonic()
        boards = seed(base, tokens, channel, args.records, args.messages)
        seeded = time.monotonic() - t0
        records = args.users * (args.records + args.messages) + args.users + 1
        say(f"seeded {records} records in {seeded:.0f}s ({records / max(seeded, 0.001):.0f}/s)")

        people = [(name, tokens[name], boards[name]) for name in names]
        rows = []
        for level in levels:
            for op in ("list", "create", "search", "thread"):
                rows.append(measure(base, people, channel, op, level, args.requests))
                say(f"  {rows[-1]}")

        db = where / "data" / "cloudmorrow.db"
        size = sum(p.stat().st_size for p in db.parent.glob("cloudmorrow.db*")) / 1e6
        print()
        memory = rss_mb(server.pid)
        print(f"{args.users} accounts, {records} records, database {size:.0f} MB, server RSS {memory:.0f} MB")
        print(f"seeding: {records / max(seeded, 0.001):.0f} writes/s through the API, {SEED_THREADS} at once")
        print()
        print(table(rows))
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
        if args.keep:
            say(f"kept {where}")
        else:
            shutil.rmtree(where, ignore_errors=True)


# -- the server -----------------------------------------------------------------------
def start_server(where: Path, port: int) -> subprocess.Popen:
    config = where / "server.toml"
    config.write_text(
        "[server]\n"
        f'data_dir = "{where / "data"}"\n'
        f'notes_dir = "{where / "data" / "files"}"\n'
        f'key_file = "{where / "cloudmorrow.key"}"\n'
        'host = "127.0.0.1"\n'
        f"port = {port}\n"
        f'quill_catalog = "{CATALOG}"\n'
        "require_tls = false\n"
        "access_lan = false\n"
        'weather_place = ""\n',
        encoding="utf-8",
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONUNBUFFERED": "1"}
    log = (where / "server.log").open("w")
    return subprocess.Popen(
        [sys.executable, "-m", "cloudmorrow.server.cli", "serve", "--config", str(config)],
        stdout=log,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=str(where),
    )


def free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_until_up(base: str, seconds: float = 30) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base}/api/health", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise SystemExit("the server did not come up; see server.log in the directory (--keep)")


def watch_memory(server: subprocess.Popen, limit_mb: int) -> None:
    """A thread that stops the server, and this script, if it grows past the limit.

    A server that leaks under load would otherwise take the machine with it
    before the measurement said anything; this says so instead.
    """

    def watch() -> None:
        while server.poll() is None:
            used = rss_mb(server.pid)
            if used > limit_mb:
                say(f"the server is at {used:.0f} MB, past the {limit_mb} MB limit: stopping")
                server.kill()
                os._exit(2)
            time.sleep(2)

    threading.Thread(target=watch, name="memory-watch", daemon=True).start()


def rss_mb(pid: int) -> float:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return float("nan")


# -- the people and their records ---------------------------------------------------------
def setup(admin: httpx.Client) -> str:
    admin.post(
        "/api/setup", json={"name": "Load", "username": ADMIN[0], "password": ADMIN[1], "quills": []}
    ).raise_for_status()
    return login(admin, *ADMIN)


def login(client: httpx.Client, username: str, password: str) -> str:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    response.raise_for_status()
    return response.json()["access_token"]


def make_people(admin: httpx.Client, base: str, names: list[str]) -> dict[str, str]:
    for name in names:
        admin.post("/api/users", json={"username": name, "password": PASSWORD}).raise_for_status()

    def sign_in(name: str) -> tuple[str, str]:
        with httpx.Client(base_url=base, timeout=60) as client:
            return name, login(client, name, PASSWORD)

    with concurrent.futures.ThreadPoolExecutor(SEED_THREADS) as pool:
        return dict(pool.map(sign_in, names))


def seed(base: str, tokens: dict[str, str], channel: str, records: int, messages: int) -> dict[str, str]:
    """Every account's board filled, and its lines in the channel. Returns the boards."""
    boards: dict[str, str] = {}
    lock = threading.Lock()

    def fill(item: tuple[str, str]) -> None:
        name, token = item
        with httpx.Client(base_url=base, timeout=60, headers={"Authorization": f"Bearer {token}"}) as client:
            board = client.get("/api/records/board").json()[0]["id"]
            with lock:
                boards[name] = board
            for n in range(records):
                title = f"Task {n} for {name}" + (f" by the {NEEDLE}" if n % 50 == 0 else "")
                fields = {"board": board, "title": title, "body": f"Line {n}: " + "words " * 20, "lane": "todo"}
                client.post("/api/records/task", json={"fields": fields}).raise_for_status()
            for n in range(messages):
                fields = {"channel": channel, "body": f"{name} says line {n}"}
                client.post("/api/records/message", json={"fields": fields}).raise_for_status()

    with concurrent.futures.ThreadPoolExecutor(SEED_THREADS) as pool:
        list(pool.map(fill, tokens.items()))
    return boards


# -- the measurements ----------------------------------------------------------------------
class Row:
    def __init__(self, op: str, level: int, took: list[float], wall: float, errors: int) -> None:
        self.op, self.level, self.took, self.wall, self.errors = op, level, took, wall, errors

    def quantile(self, q: float) -> float:
        ordered = sorted(self.took)
        return ordered[min(len(ordered) - 1, int(q * len(ordered)))] * 1000 if ordered else float("nan")

    @property
    def per_second(self) -> float:
        return len(self.took) / self.wall if self.wall else float("nan")

    def __str__(self) -> str:
        return (
            f"{self.op:7} x{self.level:<4} {self.per_second:6.0f} req/s"
            f"  p50 {self.quantile(0.5):6.0f} ms  p95 {self.quantile(0.95):6.0f} ms"
            f"  max {max(self.took) * 1000 if self.took else 0:6.0f} ms  errors {self.errors}"
        )


def measure(base: str, people: list[tuple[str, str, str]], channel: str, op: str, level: int, total: int) -> Row:
    took: list[float] = []
    errors = 0
    lock = threading.Lock()
    each = max(1, total // level)
    # What an open conversation has: everything up to now. Nothing is said in
    # the channel while this runs, so the answer is the usual one — nothing
    # new — and the cost measured is the asking, not the reading of a page.
    since = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time()))

    def worker(seed_n: int) -> None:
        nonlocal errors
        rng = random.Random(seed_n)
        name, token, board = people[seed_n % len(people)]
        mine: list[float] = []
        failed = 0
        with httpx.Client(base_url=base, timeout=60, headers={"Authorization": f"Bearer {token}"}) as client:
            for n in range(each):
                t0 = time.perf_counter()
                try:
                    if op == "list":
                        r = client.get("/api/records/task", params={"board": board})
                    elif op == "create":
                        fields = {"board": board, "title": f"Made under load {n} by {name}", "lane": "todo"}
                        r = client.post("/api/records/task", json={"fields": fields})
                    elif op == "search":
                        needle = NEEDLE if rng.random() < 0.5 else "nothing-here"
                        r = client.get("/api/records/task", params={"q": needle})
                    else:
                        r = client.get("/api/records/message", params={"channel": channel, "_since": since})
                    r.raise_for_status()
                except httpx.HTTPError:
                    failed += 1
                mine.append(time.perf_counter() - t0)
        with lock:
            took.extend(mine)
            errors += failed

    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(level) as pool:
        list(pool.map(worker, range(level)))
    return Row(op, level, took, time.perf_counter() - t0, errors)


def table(rows: list[Row]) -> str:
    lines = [
        "| request | at once | req/s | p50 | p95 | max | errors |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row.op} | {row.level} | {row.per_second:.0f} | {row.quantile(0.5):.0f} ms"
            f" | {row.quantile(0.95):.0f} ms | {max(row.took) * 1000 if row.took else 0:.0f} ms | {row.errors} |"
        )
    return "\n".join(lines)


def say(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


if __name__ == "__main__":
    sys.exit(main())
