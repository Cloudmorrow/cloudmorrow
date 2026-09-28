"""Running a Quill's Python where it can reach nothing but the host: the sandbox.

The sandbox is CPython compiled to WebAssembly (CPython's own WASI build,
pinned below), run by wasmtime. It sees three folders, all read-only: the
standard library at `/lib`, the Quill SDK at `/sdk` and the Quill at
`/quill` — and, for a machine handler, the folders the person picked, at
`/folders/<name>`. It has no sockets, no processes, no clock worth trusting
and no environment of the host's. Everything else it wants, it asks for over
standard in and out (see `cloudmorrow.quill.guest`), and the host answers.

Two halves, both here:

* `Guest`: the host's handle on one running sandbox — start it, call a
  handler, answer its requests, stop it. A call that runs past its time is
  ended by killing the process; the next call starts a fresh one.
* `main`: the small process that *is* the sandbox — `python -m
  cloudmorrow.sandbox …` — which sets wasmtime up and hands it its stdio.
  A process of its own so a runaway handler can be killed without taking
  the server with it.

`InProcessGuest` runs the same calls in this interpreter, with no sandbox:
for the test harness, where a traceback and a debugger are worth more than
a wall, and nothing else.

The runtime (about 14 MB) is downloaded once, checked against its hash, and
kept under `runtime_dir()`; the compiled module is kept beside it, so a
sandbox starts in a tenth of a second.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger("cloudmorrow.sandbox")

PYTHON_VERSION = "3.14.7"
PYTHON_URL = (
    "https://github.com/brettcannon/cpython-wasi-build/releases/download/"
    f"v{PYTHON_VERSION}/python-{PYTHON_VERSION}-wasi_sdk-24.zip"
)
PYTHON_SHA256 = "2e064d3fb8172471d39d741348efa722349c40b96301f69968dff714999c584b"
PYTHON_LIB = "python3.14"

MEMORY_LIMIT = 256 * 1024 * 1024
START_TIMEOUT = 30.0
CALL_TIMEOUT = 15.0

SDK_FILES = ("__init__.py", "context.py", "dispatch.py", "effects.py", "guest.py", "registry.py", "ui.py")


class SandboxError(RuntimeError):
    """The sandbox could not be had: no runtime, no wasmtime, or it would not start."""


# -- the runtime ---------------------------------------------------------------------
def runtime_dir() -> Path:
    """Where the runtime is kept: $CLOUDMORROW_SANDBOX_DIR, or the user's cache."""
    given = os.environ.get("CLOUDMORROW_SANDBOX_DIR")
    if given:
        return Path(given).expanduser()
    cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(cache) / "cloudmorrow" / "sandbox"


_runtime_lock = threading.Lock()


def ensure_runtime(base: Path | None = None) -> Path:
    """The runtime folder, downloading and unpacking it the first time."""
    base = base or runtime_dir()
    target = base / f"python-{PYTHON_VERSION}"
    if (target / "python.wasm").is_file():
        return target
    with _runtime_lock:
        if (target / "python.wasm").is_file():
            return target
        log.info("fetching the sandbox runtime, CPython %s for WASI", PYTHON_VERSION)
        try:
            request = urllib.request.Request(PYTHON_URL, headers={"User-Agent": "cloudmorrow"})
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - pinned
                data = response.read()
        except OSError as exc:
            raise SandboxError(f"could not fetch the sandbox runtime: {exc}") from exc
        if hashlib.sha256(data).hexdigest() != PYTHON_SHA256:
            raise SandboxError("the sandbox runtime did not match its hash; not using it")
        staging = base / f".python-{PYTHON_VERSION}.new"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            archive.extractall(staging)
        shutil.rmtree(target, ignore_errors=True)
        staging.rename(target)
    return target


def sdk_dir(base: Path | None = None) -> Path:
    """The SDK as the sandbox sees it: `cloudmorrow/quill/…`, copied, nothing else of ours."""
    here = Path(__file__).resolve().parent / "quill"
    digest = hashlib.sha256()
    for name in SDK_FILES:
        digest.update((here / name).read_bytes())
    target = (base or runtime_dir()) / f"sdk-{digest.hexdigest()[:12]}"
    if (target / "cloudmorrow" / "quill" / "guest.py").is_file():
        return target
    staging = target.with_name(target.name + ".new")
    shutil.rmtree(staging, ignore_errors=True)
    (staging / "cloudmorrow" / "quill").mkdir(parents=True)
    (staging / "cloudmorrow" / "__init__.py").write_text("", encoding="utf-8")
    for name in SDK_FILES:
        shutil.copyfile(here / name, staging / "cloudmorrow" / "quill" / name)
    shutil.rmtree(target, ignore_errors=True)
    staging.rename(target)
    return target


def available() -> bool:
    try:
        import wasmtime  # noqa: F401
    except ImportError:
        return False
    return True


# -- the sandbox process -----------------------------------------------------------------
def _module(engine, runtime: Path):
    from importlib.metadata import version

    import wasmtime

    cache = runtime / f"python-wasmtime-{version('wasmtime')}.cwasm"
    if cache.is_file():
        try:
            return wasmtime.Module.deserialize_file(engine, str(cache))
        except Exception:  # a cache from elsewhere: compile again
            cache.unlink(missing_ok=True)
    module = wasmtime.Module.from_file(engine, str(runtime / "python.wasm"))
    tmp = cache.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_bytes(module.serialize())
    tmp.replace(cache)
    return module


def run(runtime: Path, sdk: Path, quill: Path, code: str, folders: dict[str, tuple[Path, bool]]) -> int:
    """Run the guest with this process's stdio. Returns its exit code."""
    import wasmtime

    engine = wasmtime.Engine(wasmtime.Config())
    module = _module(engine, runtime)
    linker = wasmtime.Linker(engine)
    linker.define_wasi()
    store = wasmtime.Store(engine)
    store.set_limits(memory_size=MEMORY_LIMIT)
    wasi = wasmtime.WasiConfig()
    wasi.argv = [
        "python", "-S", "-c",
        "import sys; sys.path[:0] = ['/sdk', '/quill']; "
        f"from cloudmorrow.quill.guest import main; main('/quill', {code!r})",
    ]
    wasi.env = [("PYTHONHOME", "/"), ("PYTHONPATH", f"/lib/{PYTHON_LIB}"),
                ("PYTHONDONTWRITEBYTECODE", "1"), ("PYTHONUNBUFFERED", "1")]
    wasi.inherit_stdin()
    wasi.inherit_stdout()
    wasi.inherit_stderr()
    wasi.preopen_dir(str(runtime / "lib"), "/lib", False)
    wasi.preopen_dir(str(sdk), "/sdk", False)
    wasi.preopen_dir(str(quill), "/quill", False)
    for name, (path, writable) in folders.items():
        wasi.preopen_dir(str(path), f"/folders/{name}", writable)
    store.set_wasi(wasi)
    instance = linker.instantiate(store, module)
    try:
        instance.exports(store)["_start"](store)
    except wasmtime.ExitTrap as exit_:
        return exit_.code
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cloudmorrow.sandbox")
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--sdk", required=True)
    parser.add_argument("--quill", required=True)
    parser.add_argument("--code", default="quill.py")
    parser.add_argument("--folder", action="append", default=[], help="name=path[:rw]")
    args = parser.parse_args(argv)
    folders: dict[str, tuple[Path, bool]] = {}
    for item in args.folder:
        name, _, rest = item.partition("=")
        writable = rest.endswith(":rw")
        folders[name] = (Path(rest[:-3] if writable else rest), writable)
    return run(Path(args.runtime), Path(args.sdk), Path(args.quill), args.code, folders)


# -- the host's handle -------------------------------------------------------------------
HostFunction = Callable[[str, dict], object]


class Failed(Exception):
    """A handler failed in the sandbox: its kind, its words and its traceback."""

    def __init__(self, kind: str, message: str, trace: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.trace = trace


class Guest:
    """One sandbox for one Quill, kept warm between calls, one call at a time."""

    def __init__(
        self,
        quill: Path,
        code: str,
        *,
        runtime_base: Path | None = None,
        folders: dict[str, tuple[Path, bool]] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.quill = quill
        self.code = code
        self.runtime_base = runtime_base
        self.folders = dict(folders or {})
        self.on_log = on_log or (lambda line: log.info("%s: %s", quill.name, line))
        self.handlers: dict[str, list[str]] = {}
        self._process: subprocess.Popen | None = None
        self._lines: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self.last_used = 0.0

    # -- life --------------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        if self.running:
            return
        if not available():
            raise SandboxError("wasmtime is not installed, so Quill code cannot run here")
        runtime = ensure_runtime(self.runtime_base)
        sdk = sdk_dir(self.runtime_base)
        command = [
            sys.executable, "-m", "cloudmorrow.sandbox",
            "--runtime", str(runtime), "--sdk", str(sdk),
            "--quill", str(self.quill), "--code", self.code,
        ]
        for name, (path, writable) in self.folders.items():
            command += ["--folder", f"{name}={path}{':rw' if writable else ''}"]
        env = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"}
        if "PYTHONPATH" in os.environ:  # a source checkout, in development
            env["PYTHONPATH"] = os.environ["PYTHONPATH"]
        self._lines = queue.Queue()
        self._process = subprocess.Popen(  # noqa: S603 - our own interpreter, our own module
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        threading.Thread(target=self._pump, args=(self._process.stdout, self._lines), daemon=True).start()
        threading.Thread(target=self._pump_err, args=(self._process.stderr,), daemon=True).start()
        first = self._next(time.monotonic() + START_TIMEOUT, "start")
        if first.get("t") == "broken":
            self.stop()
            raise Failed("error", f"the Quill's code does not load: {first.get('message')}", first.get("trace", ""))
        if first.get("t") != "ready":
            self.stop()
            raise SandboxError(f"the sandbox said {first!r} instead of ready")
        self.handlers = first.get("handlers", {})

    def stop(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover
            pass

    @staticmethod
    def _pump(stream, lines: queue.Queue) -> None:
        for raw in iter(stream.readline, b""):
            lines.put(raw)
        lines.put(None)

    def _pump_err(self, stream) -> None:
        for raw in iter(stream.readline, b""):
            text = raw.decode("utf-8", errors="replace").rstrip()
            if text:
                self.on_log(text)

    def _next(self, deadline: float, what: str) -> dict:
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                self.stop()
                raise Failed("timeout", f"{what} took longer than it may; it was stopped")
            try:
                raw = self._lines.get(timeout=left)
            except queue.Empty:
                continue
            if raw is None:
                self._process = None
                raise Failed("error", f"the sandbox stopped during {what}")
            try:
                message = json.loads(raw)
            except ValueError:
                self.on_log(raw.decode("utf-8", errors="replace").rstrip())
                continue
            if message.get("t") == "log":
                self.on_log(str(message.get("line", "")))
                continue
            return message

    def _send(self, message: dict) -> None:
        assert self._process is not None and self._process.stdin is not None
        try:
            self._process.stdin.write((json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8"))
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self._process = None
            raise Failed("error", "the sandbox went away") from exc

    # -- a call ------------------------------------------------------------------------
    def call(
        self,
        kind: str,
        name: str,
        ctx: dict,
        args: dict,
        host: HostFunction,
        *,
        timeout: float = CALL_TIMEOUT,
    ) -> object:
        """Run one handler, answering what it asks of *host*; its result, or Failed."""
        with self._lock:
            self.start()
            self.last_used = time.monotonic()
            deadline = time.monotonic() + timeout
            if self.folders:
                ctx = {**ctx, "folders": {name_: f"/folders/{name_}" for name_ in self.folders}}
            self._send({"t": "call", "kind": kind, "name": name, "ctx": ctx, "args": args})
            while True:
                message = self._next(deadline, f"{kind} {name}")
                kind_of = message.get("t")
                if kind_of == "done":
                    return message.get("value")
                if kind_of == "fail":
                    raise Failed(message.get("kind", "error"), message.get("message", ""), message.get("trace", ""))
                if kind_of == "host":
                    self._send(answer(host, str(message.get("op", "")), message.get("args") or {}))
                    continue
                self.on_log(f"the sandbox said something unexpected: {message!r:.200}")


def answer(host: HostFunction, op: str, args: dict) -> dict:
    """A host request answered: {ok, value} or {ok: false, kind, message}."""
    from cloudmorrow.quill.context import ERRORS, HostError

    try:
        return {"t": "reply", "ok": True, "value": host(op, args)}
    except HostError as exc:
        kind = next((k for k, cls in ERRORS.items() if isinstance(exc, cls)), "refused")
        return {"t": "reply", "ok": False, "kind": kind, "message": str(exc)}


class _Lines(io.TextIOBase):
    """What a handler prints, a line at a time, to its log."""

    def __init__(self, send: Callable[[str], None]) -> None:
        self._send = send
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._send(line)
        return len(text)

    def close(self) -> None:
        if self._buffer:
            self._send(self._buffer)
            self._buffer = ""


class InProcessGuest:
    """The same calls, in this interpreter, with no sandbox: for tests."""

    _lock = threading.RLock()
    _loaded: tuple[str, str, float] | None = None

    def __init__(self, quill: Path, code: str, *, folders=None, on_log=None, **_ignored) -> None:
        self.quill = quill
        self.code = code
        self.folders = {name: (path, rw) for name, (path, rw) in (folders or {}).items()}
        self.on_log = on_log or (lambda line: log.info("%s: %s", quill.name, line))
        self.handlers: dict[str, list[str]] = {}
        self.last_used = 0.0

    @property
    def running(self) -> bool:
        return True

    def _stamp(self) -> float:
        return max((p.stat().st_mtime for p in self.quill.rglob("*.py")), default=0.0)

    def start(self) -> None:
        from cloudmorrow.quill import dispatch

        key = (str(self.quill), self.code, self._stamp())
        if InProcessGuest._loaded != key or not self.handlers:
            try:
                self.handlers = dispatch.load(self.quill, self.code)
            except Exception as exc:
                InProcessGuest._loaded = None
                raise Failed("error", f"the Quill's code does not load: {exc}", dispatch._trace(exc)) from exc
            InProcessGuest._loaded = key

    def stop(self) -> None:
        return None

    def call(self, kind: str, name: str, ctx: dict, args: dict, host: HostFunction, *, timeout: float = CALL_TIMEOUT):
        from cloudmorrow.quill import dispatch

        with InProcessGuest._lock:
            self.start()
            self.last_used = time.monotonic()
            ctx = dict(ctx)
            if self.folders:
                ctx["folders"] = {name_: str(path) for name_, (path, _) in self.folders.items()}

            def logged(op: str, a: dict):
                if op == "log":
                    self.on_log(str(a.get("line", "")))
                    return None
                reply = answer(host, op, a)
                if reply["ok"]:
                    return reply["value"]
                from cloudmorrow.quill.context import ERRORS, Invalid

                raise ERRORS.get(reply["kind"], Invalid)(reply["message"])

            printed = _Lines(self.on_log)
            try:
                with contextlib.redirect_stdout(printed):
                    value = dispatch.call(kind, name, ctx, args, logged)
            except dispatch.Failure as failure:
                raise Failed(failure.kind, failure.message, failure.trace) from failure
            finally:
                printed.close()
            json.dumps(value)
            return value


if __name__ == "__main__":
    sys.exit(main())
