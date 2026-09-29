"""A Quill's code on this machine: its `[[machine]]` handlers, in the sandbox, as its owner.

Nothing runs because the server says so. A handler runs here when this
machine's owner switched it on here (`cm quill machine enable`, which
writes it into this machine's agent.toml with the folders they picked),
while the Quill is installed and on for them, and while this machine has
not said no to all of it (`allow_quill_code = false`).

It runs in the same sandbox as on the server (`cloudmorrow.sandbox`), seeing
only the folders it was given, at `/folders/<name>`, read-only unless the
manifest asked for write and the person gave it. What it asks for besides —
records, the time, a fetch, a secret — goes to the server with this agent's
token and is answered there as the machine's owner, through the gate. The
one thing answered here is `ctx.run`: a program, started only when it is in
the handler's manifest *and* in this machine's `quill_programs`.

A handler with `every` runs on that clock; any handler also runs when asked
(an agent job of type `quill`, or `cm quill machine run`).
"""

from __future__ import annotations

import io
import logging
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

from cloudmorrow import locations
from cloudmorrow.agent.client import AgentApiError, AgentClient
from cloudmorrow.agent.config import AgentConfig
from cloudmorrow.quill import context as sdk

log = logging.getLogger("cloudmorrow.agent")

MACHINE_TIMEOUT = 300.0
OUTPUT_LIMIT = 64 * 1024


def quills_dir() -> Path:
    return locations.data_dir() / "quills"


def parse_every(text: str) -> float:
    from cloudmorrow.server.datamodels import parse_duration  # a pure function; no server needed

    return parse_duration(text).total_seconds()


class MachineQuills:
    """The handlers switched on here, fetched, kept, run on time or when asked."""

    def __init__(self, config: AgentConfig, client: AgentClient, *, base: Path | None = None, guest=None) -> None:
        self.config = config
        self.client = client
        self.base = base or quills_dir()
        # The sandbox; the test harness runs the same calls in-process instead.
        self.guest = guest
        self._last: dict[tuple[str, str], float] = {}
        self._offered: dict[str, dict] = {}

    # -- what is on here -------------------------------------------------------------------
    def switched_on(self) -> dict:
        """{quill: {handler: {"folders": {...}}}}, read fresh: `enable` may have just written it."""
        if self.config.path is not None and self.config.path.exists():
            return AgentConfig.load(self.config.path).quills or {}
        return self.config.quills or {}

    def offered(self) -> dict[str, dict]:
        self._offered = {q["id"]: q for q in self.client.machine_quills()}
        return self._offered

    # -- the clock ---------------------------------------------------------------------------
    def tick(self) -> list[str]:
        """Run every switched-on handler whose `every` has come round."""
        if not self.config.allow_quill_code:
            return []
        wanted = self.switched_on()
        if not wanted:
            return []
        offered = self.offered()
        ran = []
        now = time.monotonic()
        for quill_id, handlers in wanted.items():
            quill = offered.get(quill_id)
            if quill is None:
                continue
            for spec in quill["machine"]:
                if spec["id"] not in handlers or not spec.get("every"):
                    continue
                last = self._last.get((quill_id, spec["id"]))
                if last is not None and now - last < parse_every(spec["every"]):
                    continue
                self._last[(quill_id, spec["id"])] = now
                try:
                    self.run(quill_id, spec["id"])
                    ran.append(f"{quill_id}/{spec['id']}")
                except (sdk.HostError, RuntimeError, AgentApiError) as exc:
                    log.warning("%s/%s: %s", quill_id, spec["id"], exc)
        return ran

    # -- one run -----------------------------------------------------------------------------
    def _code(self, quill: dict) -> Path:
        """The Quill's code, fetched once per install of it."""
        stamp = "".join(c for c in quill["stamp"] if c.isalnum())[:40] or "current"
        folder = self.base / quill["id"] / stamp
        if (folder / quill["code"]).exists():
            return folder
        data = self.client.quill_code(quill["id"])
        if folder.parent.exists():
            shutil.rmtree(folder.parent)
        staging = folder.with_name(folder.name + ".new")
        staging.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            archive.extractall(staging, filter="data")
        staging.rename(folder)
        return folder

    def run(self, quill_id: str, handler_id: str) -> object:
        """Run one handler now, and return what it returned."""
        from cloudmorrow.sandbox import Failed, Guest

        guest_class = self.guest or Guest

        if not self.config.allow_quill_code:
            raise sdk.Refused("this machine runs no Quill code (allow_quill_code = false)")
        wanted = self.switched_on().get(quill_id, {})
        if handler_id not in wanted:
            raise sdk.Refused(f"{quill_id} {handler_id} is not switched on on this machine")
        quill = (self._offered or self.offered()).get(quill_id) or self.offered().get(quill_id)
        if quill is None:
            raise sdk.NotFound(f"{quill_id} is not installed, or not on for you")
        spec = next((m for m in quill["machine"] if m["id"] == handler_id), None)
        if spec is None:
            raise sdk.NotFound(f"{quill_id} has no machine handler {handler_id}")
        given = dict(wanted[handler_id].get("folders", {}))
        folders: dict[str, tuple[Path, bool]] = {}
        for need in spec["folders"]:
            if need["name"] not in given:
                raise sdk.Invalid(f"no folder was given for {need['name']}: enable it again")
            path = Path(given[need["name"]]).expanduser()
            if not path.is_dir():
                raise sdk.NotFound(f"{path} is not a folder here")
            folders[need["name"]] = (path, need["access"] == "write")

        def host(op: str, args: dict) -> object:
            if op == "run":
                return self._program(spec, args)
            answer = self.client.quill_host(quill_id, op, args, machine=handler_id)
            if answer.get("ok"):
                return answer.get("value")
            raise sdk.ERRORS.get(answer.get("kind", ""), sdk.Invalid)(answer.get("message", "refused"))

        guest = guest_class(
            self._code(quill),
            quill["code"],
            runtime_base=self.base / "sandbox",
            folders=folders,
            on_log=lambda line: log.info("%s/%s: %s", quill_id, handler_id, line),
        )
        ctx = {"quill": quill_id, "user": {"username": quill["owner"]}, "where": "machine"}
        try:
            return guest.call("machine", spec["handler"], ctx, {}, host, timeout=MACHINE_TIMEOUT)
        except Failed as failure:
            raise RuntimeError(f"{quill_id}/{handler_id}: {failure.message}") from failure
        finally:
            guest.stop()

    def _program(self, spec: dict, args: dict) -> dict:
        command = [str(part) for part in args.get("command") or []]
        if not command:
            raise sdk.Invalid("ctx.run needs a command")
        program = command[0]
        if program not in spec.get("run", []):
            raise sdk.Refused(f"{program} is not in this handler's needs.run")
        if program not in self.config.quill_programs:
            raise sdk.Refused(f"this machine has not allowed {program}: add it to quill_programs")
        try:
            done = subprocess.run(  # noqa: S603 - a program the manifest and the machine both named
                command,
                input=str(args.get("input") or ""),
                capture_output=True,
                text=True,
                timeout=min(float(args.get("timeout") or 60), MACHINE_TIMEOUT),
                check=False,
            )
        except FileNotFoundError as exc:
            raise sdk.NotFound(f"{program} is not installed here") from exc
        except subprocess.TimeoutExpired as exc:
            raise sdk.Invalid(f"{program} took too long") from exc
        return {"code": done.returncode, "out": done.stdout[-OUTPUT_LIMIT:], "err": done.stderr[-OUTPUT_LIMIT:]}
