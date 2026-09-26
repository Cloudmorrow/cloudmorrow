"""Running a Quill's code: its services, kept up, and its `run` jobs, on time.

A Quill is declarative first, and code is the exception — a mail sync, a
bridge to somebody else's API — so the core runs that code *outside* itself:
each `[[services]]` entry is a process of its own, started here, and it
reaches the data through the record API over loopback HTTP like any client,
through the gate, with a token of its own (see `quilltokens`). The server
never imports a Quill's code, and a Quill's code never holds anything of the
server's but that token.

**What runs.** Only what an administrator installed: the Quills in the
registry, from the folders the install copied under `<data_dir>/quills/`,
and only while the Quill is switched on for the server. Switching it off,
removing it, and stopping the server stop its processes — SIGTERM to the
process group, then SIGKILL after a grace period. A reinstall (a new
`installed_at` in its origin) restarts them on the new code.

**How it runs.** `cwd` is the Quill's folder. The environment is built from
nothing rather than copied from the server's, so no setting, path or key of
the server's leaks into it:

    PATH, LANG             the server's own, so programs are found
    HOME                   <data_dir>/quill-homes/<id>, the Quill's to keep things in
    PYTHONUNBUFFERED=1     so its log is written as it goes
    CLOUDMORROW_URL        this server, on loopback
    CLOUDMORROW_TOKEN      the Quill's token
    CLOUDMORROW_QUILL      its id; CLOUDMORROW_SERVICE, which service this is
    PORT                   a free loopback port, for a service that serves an
                           [[apis]] entry or a forwarded webhook

`python` as the first word of a command is the server's own interpreter
(`sys.executable`), so a Quill needs nothing installed to run a script; its
standard library is what a Quill can count on.

**Staying up.** A service with `always = true` is started again when it
exits, after a wait that doubles with each quick failure (one second, then
two, four, … up to a minute) and starts over once it has stayed up a while.
One without `always` runs once per start of the Quill. A service a `run`
job names is not started on its own: the job starts it, every `every`,
never twice at once.

**Logs.** Whatever a process writes, out and err, goes to
`<data_dir>/logs/quills/<id>/<service>.log`, with a line from the core at
each start and exit. At a megabyte the file becomes `<service>.log.1` and a
new one starts: two files, never more.

**One process.** The server runs as a single uvicorn process, and this
supervisor lives in it. Two workers would each start every service; if the
server ever grows workers, this has to move to one of them.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from cloudmorrow.server.config import ServerConfig
from cloudmorrow.server.datamodels import parse_duration
from cloudmorrow.server.db import UserStore, connect
from cloudmorrow.server.features import FeatureStore
from cloudmorrow.server.quills import Manifest, QuillRegistry
from cloudmorrow.server.quilltokens import QuillTokenStore, runs_as

__all__ = ["Supervisor"]

log = logging.getLogger("cloudmorrow.quills")

TABLE = """
CREATE TABLE IF NOT EXISTS quill_job_runs (
    -- When each `run` job last started, so a restart of the server does
    -- not run a daily job again at once.
    quill        TEXT NOT NULL,
    job          TEXT NOT NULL,
    last_started TEXT NOT NULL,
    last_exit    INTEGER,
    PRIMARY KEY (quill, job)
);
"""

LOG_MAX = 1024 * 1024
TAIL_BYTES = 64 * 1024


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


def free_port() -> int:
    """A loopback port nothing is listening on right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def loopback_url(config: ServerConfig) -> str:
    """This server as a process on the same machine reaches it."""
    host = config.host
    if host in ("", "0.0.0.0", "::", "localhost"):
        host = "127.0.0.1"
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{config.port}"


class ServiceLog:
    """One service's log file, capped: `<service>.log`, and `.log.1` before it."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def write(self, text: str) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size >= LOG_MAX:
                os.replace(self.path, self.path.with_name(self.path.name + ".1"))
            with self.path.open("a", encoding="utf-8", errors="replace") as handle:
                handle.write(text)

    def note(self, text: str) -> None:
        """A line from the core, told apart from the service's own."""
        self.write(f"-- {_now()} {text}\n")

    def pump(self, stream) -> None:
        """Copy a process's output in, a line at a time, until it closes."""
        try:
            for raw in iter(stream.readline, b""):
                self.write(raw.decode("utf-8", errors="replace"))
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def tail(self, lines: int = 50) -> list[str]:
        if not self.path.exists():
            return []
        with self.path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - TAIL_BYTES))
            text = handle.read().decode("utf-8", errors="replace")
        return text.splitlines()[-lines:]


@dataclass
class Service:
    """One service of one Quill, as the supervisor keeps it."""

    quill: str
    id: str
    command: list[str]
    always: bool
    # Started by a `run` job rather than kept up.
    scheduled: bool
    state: str = "stopped"  # running, restarting, stopped
    since: str = field(default_factory=_now)
    problem: str = ""
    process: subprocess.Popen | None = None
    port: int | None = None
    started_at: float = 0.0
    last_exit: int | None = None
    last_exit_at: str = ""
    restarts: int = 0
    # Quick failures in a row, for the backoff; and when to try again.
    failures: int = 0
    next_start: float = 0.0
    # A service without `always` that has had its run.
    done: bool = False

    def set_state(self, state: str, problem: str = "") -> None:
        if state != self.state:
            self.since = _now()
        self.state = state
        self.problem = problem

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "command": list(self.command),
            "always": self.always,
            "scheduled": self.scheduled,
            "state": self.state,
            "since": self.since,
            "problem": self.problem,
            "pid": self.process.pid if self.process is not None else None,
            "port": self.port if self.state == "running" else None,
            "last_exit": self.last_exit,
            "last_exit_at": self.last_exit_at,
            "restarts": self.restarts,
        }


class Supervisor:
    """Starts, watches and stops every installed Quill's processes."""

    # Seconds; tests make them small.
    TICK = 1.0
    BACKOFF_FIRST = 1.0
    BACKOFF_MAX = 60.0
    # Up this long, a service's failures are forgotten.
    STEADY = 60.0
    GRACE = 5.0

    def __init__(
        self,
        config: ServerConfig,
        registry: QuillRegistry,
        users: UserStore,
        features: FeatureStore,
        tokens: QuillTokenStore,
    ) -> None:
        self.config = config
        self.registry = registry
        self.users = users
        self.features = features
        self.tokens = tokens
        self._lock = threading.RLock()
        self._services: dict[tuple[str, str], Service] = {}
        self._logs: dict[tuple[str, str], ServiceLog] = {}
        # The installed_at each Quill's processes were started for.
        self._generation: dict[str, str] = {}
        # The working token of each Quill that runs code: here and in its
        # processes' environment, nowhere else.
        self._tokens: dict[str, str] = {}
        self._jobs: dict[tuple[str, str], subprocess.Popen] = {}
        self._wake = threading.Event()
        self._changed = True
        self._stopping = False
        self._thread: threading.Thread | None = None
        with connect(config.db_path) as conn:
            conn.executescript(TABLE)
        conn.close()
        registry.listeners.append(self.changed)

    # -- the thread ---------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._stopping = False
        self._thread = threading.Thread(target=self._run, name="quill-services", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the thread, then every process: the server is going away."""
        self._stopping = True
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=self.TICK + 5)
            self._thread = None
        with self._lock:
            doomed = [s for s in self._services.values() if s.process is not None]
            jobs = list(self._jobs.items())
            self._jobs.clear()
        self._terminate([(s, s.process) for s in doomed] + [(None, p) for _, p in jobs])
        for service in doomed:
            service.set_state("stopped", "the server stopped")

    def changed(self) -> None:
        """What is installed changed: look again now, not at the next tick."""
        self._changed = True
        self._wake.set()

    def _run(self) -> None:
        while not self._stopping:
            try:
                self.reconcile()
            except Exception:  # the supervisor outlives any one bad Quill
                log.exception("quill services: reconcile failed")
            self._wake.wait(self.TICK)
            self._wake.clear()

    # -- keeping what runs in line with what is installed -------------------------
    def reconcile(self) -> None:
        """Start what should run, stop what should not, restart what fell over."""
        registry_changed, self._changed = self._changed, False
        installed = dict(self.registry.quills)
        to_stop: list[tuple[Service | None, subprocess.Popen]] = []
        with self._lock:
            # Removed: every process stops and the token goes with it.
            for quill in {q for q, _ in self._services} - set(installed):
                to_stop += self._forget(quill)
            if registry_changed:
                for quill in set(self.tokens.holders()) - set(installed):
                    self.tokens.revoke(quill)
                    self._tokens.pop(quill, None)
            for manifest in installed.values():
                if not (manifest.services or manifest.webhooks):
                    continue
                generation = str(manifest.origin.get("installed_at", ""))
                if self._generation.get(manifest.id, generation) != generation:
                    # Reinstalled or updated: the old processes are old code.
                    to_stop += self._forget(manifest.id, revoke=False)
                self._generation[manifest.id] = generation
                if registry_changed:
                    hooks = {h["id"] for h in manifest.webhooks}
                    self.tokens.forget_webhooks(manifest.id, hooks)
                    for hook in hooks:
                        self.tokens.webhook_secret(manifest.id, hook)
                if manifest.services:
                    to_stop += self._keep_up(manifest)
        self._terminate(to_stop)

    def _forget(self, quill: str, *, revoke: bool = True) -> list:
        """Everything of *quill*'s this knows: its processes, to be stopped."""
        doomed = []
        for key in [k for k in self._services if k[0] == quill]:
            service = self._services.pop(key)
            if service.process is not None:
                doomed.append((service, service.process))
        for key in [k for k in self._jobs if k[0] == quill]:
            doomed.append((None, self._jobs.pop(key)))
        self._generation.pop(quill, None)
        if revoke:
            self._tokens.pop(quill, None)
            self.tokens.revoke(quill)
        return doomed

    def _keep_up(self, manifest: Manifest) -> list:
        scheduled = {j["service"] for j in manifest.jobs if j["action"] == "run"}
        on = self.features.enabled(manifest.id)
        owner = runs_as(self.users, manifest.origin)
        if manifest.id not in self._tokens:
            self._tokens[manifest.id] = self.tokens.issue(manifest.id)
        doomed = []
        now = time.monotonic()
        for spec in manifest.services:
            key = (manifest.id, spec["id"])
            service = self._services.get(key)
            if service is None:
                service = self._services[key] = Service(
                    manifest.id, spec["id"], list(spec["command"]),
                    bool(spec.get("always", False)), spec["id"] in scheduled,
                )
            if service.scheduled:
                continue
            if not on or not owner:
                if service.process is not None:
                    doomed.append((service, service.process))
                    service.process = None
                service.done = False
                service.set_state(
                    "stopped", "switched off" if not on else "runs as nobody: reinstall it"
                )
                continue
            process = service.process
            if process is not None:
                code = process.poll()
                if code is None:
                    continue
                self._exited(service, code, now)
            if service.done or now < service.next_start:
                continue
            self._start(manifest, service)
        return doomed

    def _exited(self, service: Service, code: int, now: float) -> None:
        service.process = None
        service.last_exit = code
        service.last_exit_at = _now()
        self._log(service.quill, service.id).note(f"exited with {code}")
        if not service.always:
            service.done = True
            service.set_state("stopped")
            return
        if now - service.started_at >= self.STEADY:
            service.failures = 0
        wait = min(self.BACKOFF_MAX, self.BACKOFF_FIRST * (2 ** service.failures))
        service.failures += 1
        service.next_start = now + wait
        service.set_state("restarting", f"exited with {code}; again in {wait:g}s")

    def _start(self, manifest: Manifest, service: Service) -> None:
        port = free_port()
        process = self._spawn(manifest, service.id, port)
        service.restarts += 1 if service.last_exit is not None else 0
        if process is None:
            self._exited(service, 127, time.monotonic())
            return
        service.process = process
        service.port = port
        service.started_at = time.monotonic()
        service.set_state("running")

    def _spawn(self, manifest: Manifest, service_id: str, port: int) -> subprocess.Popen | None:
        spec = next(s for s in manifest.services if s["id"] == service_id)
        argv = [sys.executable if i == 0 and a == "python" else a
                for i, a in enumerate(spec["command"])]
        logfile = self._log(manifest.id, service_id)
        env = self.environment(manifest.id, service_id, port)
        try:
            process = subprocess.Popen(  # noqa: S603 — an installed Quill's own command
                argv,
                cwd=manifest.folder,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            logfile.note(f"could not start {' '.join(argv)}: {exc}")
            return None
        logfile.note(f"started {' '.join(spec['command'])} (pid {process.pid}, port {port})")
        threading.Thread(
            target=logfile.pump, args=(process.stdout,), name=f"log-{manifest.id}-{service_id}",
            daemon=True,
        ).start()
        return process

    def environment(self, quill: str, service: str, port: int) -> dict[str, str]:
        """What a Quill's process is given: this and nothing else (see the module)."""
        home = self.config.data_dir / "quill-homes" / quill
        home.mkdir(parents=True, exist_ok=True)
        return {
            "PATH": os.environ.get("PATH", os.defpath),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "HOME": str(home),
            "PYTHONUNBUFFERED": "1",
            "CLOUDMORROW_URL": loopback_url(self.config),
            "CLOUDMORROW_TOKEN": self._tokens.get(quill, ""),
            "CLOUDMORROW_QUILL": quill,
            "CLOUDMORROW_SERVICE": service,
            "PORT": str(port),
        }

    def _log(self, quill: str, service: str) -> ServiceLog:
        key = (quill, service)
        if key not in self._logs:
            self._logs[key] = ServiceLog(
                self.config.data_dir / "logs" / "quills" / quill / f"{service}.log"
            )
        return self._logs[key]

    def _terminate(self, doomed: list) -> None:
        """SIGTERM to each process group, then SIGKILL to what is left after the grace."""
        live = [(s, p) for s, p in doomed if p is not None and p.poll() is None]
        for _, process in live:
            _signal(process, signal.SIGTERM)
        deadline = time.monotonic() + self.GRACE
        for service, process in live:
            try:
                process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                _signal(process, signal.SIGKILL)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            if service is not None:
                self._log(service.quill, service.id).note(f"stopped (exit {process.returncode})")
                service.last_exit = process.returncode
                service.last_exit_at = _now()

    # -- run jobs -------------------------------------------------------------------
    def run_due(self) -> list[str]:
        """Start every `run` job whose time has come and that is not running. The Clock asks."""
        started = []
        now = dt.datetime.now(tz=dt.UTC)
        for manifest in list(self.registry.quills.values()):
            jobs = [j for j in manifest.jobs if j["action"] == "run"]
            if not jobs or not self.features.enabled(manifest.id):
                continue
            if not runs_as(self.users, manifest.origin):
                continue
            with self._lock:
                if manifest.id not in self._tokens:
                    self._tokens[manifest.id] = self.tokens.issue(manifest.id)
            for job in jobs:
                key = (manifest.id, job["id"])
                with self._lock:
                    running = self._jobs.get(key)
                    if running is not None and running.poll() is None:
                        continue  # never twice at once
                last = self._last_run(manifest.id, job["id"])
                if last is not None and now - last < parse_duration(str(job["every"])):
                    continue
                process = self._spawn(manifest, job["service"], free_port())
                self._record_start(manifest.id, job["id"])
                if process is None:
                    self._record_exit(manifest.id, job["id"], 127)
                    continue
                with self._lock:
                    self._jobs[key] = process
                threading.Thread(
                    target=self._await_job, args=(manifest.id, job, process), daemon=True,
                    name=f"job-{manifest.id}-{job['id']}",
                ).start()
                started.append(f"{manifest.id}.{job['id']}")
        return started

    def _await_job(self, quill: str, job: dict, process: subprocess.Popen) -> None:
        code = process.wait()
        self._record_exit(quill, job["id"], code)
        self._log(quill, job["service"]).note(f"job {job['id']} exited with {code}")

    def _last_run(self, quill: str, job: str) -> dt.datetime | None:
        row = self._job_row(quill, job)
        return dt.datetime.fromisoformat(row["last_started"]) if row else None

    def _job_row(self, quill: str, job: str) -> sqlite3.Row | None:
        with connect(self.config.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM quill_job_runs WHERE quill = ? AND job = ?", (quill, job)
            ).fetchone()
        conn.close()
        return row

    def _record_start(self, quill: str, job: str) -> None:
        with connect(self.config.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO quill_job_runs (quill, job, last_started, last_exit)"
                " VALUES (?, ?, ?, NULL)",
                (quill, job, _now()),
            )
        conn.close()

    def _record_exit(self, quill: str, job: str, code: int) -> None:
        with connect(self.config.db_path) as conn:
            conn.execute(
                "UPDATE quill_job_runs SET last_exit = ? WHERE quill = ? AND job = ?",
                (code, quill, job),
            )
        conn.close()

    # -- what administrators and the proxy ask ------------------------------------
    def token(self, quill: str) -> str:
        """The working token of *quill*, for what the core itself starts. Never sent out."""
        with self._lock:
            return self._tokens.get(quill, "")

    def port_of(self, quill: str, service: str) -> int | None:
        with self._lock:
            found = self._services.get((quill, service))
            if found is None or found.state != "running" or found.process is None:
                return None
            return found.port

    def rotate(self, quill: str) -> None:
        """A new token for *quill*, and its services restarted to carry it."""
        with self._lock:
            self._tokens[quill] = self.tokens.issue(quill)
        self.restart(quill)

    def restart(self, quill: str) -> None:
        doomed = []
        with self._lock:
            for (q, _), service in self._services.items():
                if q != quill:
                    continue
                if service.process is not None:
                    doomed.append((service, service.process))
                    service.process = None
                service.failures = 0
                service.next_start = 0.0
                service.done = False
                service.set_state("restarting", "restarted by an administrator")
        self._terminate(doomed)
        self._wake.set()

    def tail(self, quill: str, service: str, lines: int = 50) -> list[str]:
        return self._log(quill, service).tail(lines)

    def status(self) -> list[dict]:
        """Every Quill that runs code: its services, jobs, webhooks and APIs, and as whom."""
        rows = []
        for manifest in sorted(self.registry.quills.values(), key=lambda m: m.id):
            if not (manifest.services or manifest.webhooks):
                continue
            with self._lock:
                services = []
                for spec in manifest.services:
                    found = self._services.get((manifest.id, spec["id"]))
                    services.append(
                        found.to_dict() if found else Service(
                            manifest.id, spec["id"], list(spec["command"]),
                            bool(spec.get("always", False)), False,
                        ).to_dict()
                    )
                jobs_running = {
                    k[1] for k, p in self._jobs.items() if k[0] == manifest.id and p.poll() is None
                }
            jobs = []
            for job in manifest.jobs:
                if job["action"] != "run":
                    continue
                row = self._job_row(manifest.id, job["id"])
                jobs.append({
                    "id": job["id"], "service": job["service"], "every": job["every"],
                    "running": job["id"] in jobs_running,
                    "last_started": row["last_started"] if row else "",
                    "last_exit": row["last_exit"] if row else None,
                })
            rows.append({
                "id": manifest.id,
                "name": manifest.name,
                "runs_as": runs_as(self.users, manifest.origin),
                "enabled": self.features.enabled(manifest.id),
                "reach": sorted(manifest.models),
                "token": self.tokens.info(manifest.id),
                "services": services,
                "jobs": jobs,
                "webhooks": [
                    {
                        "id": h["id"], "path": h["path"], "model": h.get("model", ""),
                        "forward": h.get("forward", ""), "signature": h.get("signature", ""),
                        "secret": self.tokens.webhook_secret(manifest.id, h["id"]),
                    }
                    for h in manifest.webhooks
                ],
                "apis": [
                    {"id": a["id"], "service": a["service"], "prefix": a.get("prefix", "")}
                    for a in manifest.apis
                ],
            })
        return rows


def _signal(process: subprocess.Popen, sig: int) -> None:
    try:
        os.killpg(process.pid, sig)
    except (ProcessLookupError, PermissionError, AttributeError):
        try:
            process.send_signal(sig)
        except (ProcessLookupError, OSError):
            pass
