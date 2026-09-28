"""Running a Quill's Python on the server: its views, actions, hooks, jobs, webhooks and APIs.

Every call goes the same way. The core picks who the code acts as — the
person looking or pressing for a view or an action; whoever made the change
for a hook; the administrator who installed the Quill for a job, a webhook
or an API — and runs the handler in the Quill's sandbox (`cloudmorrow.
sandbox`), answering each thing the code asks for (`HostCalls`) through the
gate, as that principal:

    records.*   the record store, as Principal("quill", <them>, quill=<id>, models=<declared>)
                — so the person's circles narrow it, and the Quill's manifest does too
    fetch       https, to a host in [[fetch]] only, and only there after a redirect
    secret      a key in [[secrets]], from the person's own vault; never for an assistant
    now         the time

When an assistant is the one pressing (an action as an MCP tool), the code
is an assistant's too: the datamodels no assistant may reach are taken out
of its reach, and it is given no secret.

One sandbox per Quill, started on its first call and kept warm; it is
stopped when the Quill is reinstalled, switched off or removed, and after
ten idle minutes. A call that runs past its time is stopped with it.

Hooks are queued as records change and run one at a time on a thread of
their own, so a write never waits for somebody's code. A Quill's hooks are
not told about what its own hooks wrote, and a chain of hooks stops three
deep.

Its log is `<data_dir>/logs/quills/<id>/code.log`: what the code printed or
logged, and a line for every call that failed.

See docs/QUILLCODE.md.
"""

from __future__ import annotations

import base64
import datetime as dt
import logging
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

from cloudmorrow.quill import context as sdk
from cloudmorrow.quill import ui
from cloudmorrow.sandbox import CALL_TIMEOUT, Failed, Guest, InProcessGuest, SandboxError
from cloudmorrow.server.codespec import action_fields
from cloudmorrow.server.db import connect
from cloudmorrow.server.datamodels import parse_duration
from cloudmorrow.server.quills import Manifest
from cloudmorrow.server.quillservices import ServiceLog
from cloudmorrow.server.quilltokens import runs_as
from cloudmorrow.server.records import (
    DATASET,
    NEVER_FOR_ASSISTANTS,
    Principal,
    Record,
    RecordConflictError,
    RecordError,
    Refused,
    UnknownModelError,
    UnknownRecordError,
    _coerce,
)
from cloudmorrow.server.secrets import DEFAULT_ENVIRONMENT, DEFAULT_VAULT

if TYPE_CHECKING:
    from cloudmorrow.server.deps import AppState

__all__ = ["CodeError", "QuillCode"]

log = logging.getLogger("cloudmorrow.quills")

IDLE = 600.0
JOB_TIMEOUT = 120.0
HOOK_DEPTH = 3
FETCH_TIMEOUT = 30.0
FETCH_MAX = 10 * 1024 * 1024
FETCH_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"})

TABLE = """
CREATE TABLE IF NOT EXISTS quill_call_runs (
    -- When each `call` job last ran, so a restart does not run a daily one again.
    quill        TEXT NOT NULL,
    job          TEXT NOT NULL,
    last_started TEXT NOT NULL,
    last_error   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (quill, job)
);
"""

# How a failure is answered over HTTP.
STATUS = {
    "refused": 403, "notfound": 404, "invalid": 400, "conflict": 409,
    "timeout": 504, "error": 500, "off": 403, "unavailable": 503,
}


class CodeError(Exception):
    """A handler could not be run, or failed: its kind, words, and the Quill's traceback."""

    def __init__(self, kind: str, message: str, trace: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.trace = trace

    @property
    def status(self) -> int:
        return STATUS.get(self.kind, 500)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "message": self.message}


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


def _host_error(exc: Exception) -> sdk.HostError:
    """A record store refusal, as the SDK's exception of the same kind."""
    if isinstance(exc, UnknownModelError):
        return sdk.NotFound(f"no such datamodel: {exc}")
    if isinstance(exc, UnknownRecordError):
        return sdk.NotFound("no such record")
    if isinstance(exc, Refused):
        return sdk.Refused(str(exc))
    if isinstance(exc, RecordConflictError):
        return sdk.Conflict("changed since it was read")
    return sdk.Invalid(str(exc))


STORE_ERRORS = (UnknownModelError, UnknownRecordError, Refused, RecordConflictError, RecordError)


def _host_allowed(host: str, allowed: tuple[dict, ...]) -> bool:
    host = host.lower().rstrip(".")
    for item in allowed:
        pattern = item["host"]
        if pattern.startswith("*."):
            if host.endswith(pattern[1:]) and host != pattern[2:]:
                return True
        elif host == pattern:
            return True
    return False


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to https, and only to a host the Quill may fetch from."""

    def __init__(self, allowed: tuple[dict, ...]) -> None:
        self.allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urllib.parse.urlsplit(newurl)
        if parts.scheme != "https" or not _host_allowed(parts.hostname or "", self.allowed):
            raise sdk.Refused(f"it was sent on to {parts.hostname}, which it may not fetch from")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# -- what the code may ask for ---------------------------------------------------------------
class HostCalls:
    """Answers one handler's requests, as one principal. Raises the SDK's exceptions."""

    def __init__(self, code: QuillCode, manifest: Manifest, principal: Principal, *, via: str) -> None:
        self.code = code
        self.state = code.state
        self.manifest = manifest
        self.principal = principal
        self.via = via

    def __call__(self, op: str, args: dict) -> object:
        handler = getattr(self, "op_" + op.replace(".", "_"), None)
        if handler is None:
            raise sdk.Invalid(f"there is no {op!r} to ask for")
        try:
            return handler(args)
        except STORE_ERRORS as exc:
            raise _host_error(exc) from exc

    # -- records -------------------------------------------------------------------------
    def _model(self, args: dict) -> str:
        model = str(args.get("model", ""))
        if not model:
            raise sdk.Invalid("which datamodel?")
        return model

    def op_records_list(self, args: dict) -> list[dict]:
        from cloudmorrow.server.routes.records import seed

        model = self._model(args)
        where = {str(k): v for k, v in (args.get("where") or {}).items()}
        if args.get("q"):
            where["q"] = str(args["q"])
        seed(self.state, self.principal, model)
        last = args.get("last")
        records = self.state.records.list(self.principal, model, where, last=int(last) if last else None)
        return [r.to_dict() for r in records]

    def op_records_get(self, args: dict) -> dict:
        return self.state.records.get(self.principal, self._model(args), str(args.get("id", ""))).to_dict()

    def op_records_create(self, args: dict) -> dict:
        record = self.state.records.create(
            self.principal, self._model(args), dict(args.get("fields") or {}), index=args.get("index")
        )
        return record.to_dict()

    def op_records_patch(self, args: dict) -> dict:
        record = self.state.records.update(
            self.principal, self._model(args), str(args.get("id", "")),
            dict(args.get("fields") or {}), rev=args.get("rev"),
        )
        return record.to_dict()

    def op_records_move(self, args: dict) -> dict:
        record = self.state.records.move(
            self.principal, self._model(args), str(args.get("id", "")),
            dict(args.get("fields") or {}), args.get("index"),
        )
        return record.to_dict()

    def op_records_delete(self, args: dict) -> int:
        return self.state.records.delete(self.principal, self._model(args), str(args.get("id", "")))

    # -- the rest ------------------------------------------------------------------------
    def op_now(self, args: dict) -> str:
        return dt.datetime.now(tz=dt.UTC).isoformat()

    def op_log(self, args: dict) -> None:
        self.code.log(self.manifest.id).write(str(args.get("line", "")) + "\n")

    def op_run(self, args: dict) -> None:
        raise sdk.Refused("ctx.run is for a machine handler, on a person's own machine")

    def op_secret(self, args: dict) -> str:
        key = str(args.get("key", ""))
        if self.via == "assistant":
            raise sdk.Refused("no secret is given to code an assistant started")
        if not any(s["key"] == key for s in self.manifest.secrets):
            raise sdk.Refused(f"{self.manifest.id} does not list {key} in [[secrets]]")
        secret = self.state.secrets.get(self.principal.username, DEFAULT_VAULT, DEFAULT_ENVIRONMENT, key)
        if secret is None or secret.value is None:
            raise sdk.NotFound(f"{key} is not in {self.principal.username}'s vault; add it with `cm secret set {key}`")
        return secret.value

    def op_fetch(self, args: dict) -> dict:
        url = str(args.get("url", ""))
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https":
            raise sdk.Refused("ctx.fetch reaches https:// addresses only")
        if not _host_allowed(parts.hostname or "", self.manifest.fetch):
            raise sdk.Refused(f"{self.manifest.id} does not list {parts.hostname} in [[fetch]]")
        method = str(args.get("method", "GET")).upper()
        if method not in FETCH_METHODS:
            raise sdk.Invalid(f"{method} is not a method ctx.fetch sends")
        headers = {
            str(k): str(v) for k, v in (args.get("headers") or {}).items()
            if str(k).lower() not in ("host", "content-length", "connection")
        }
        headers.setdefault("User-Agent", f"cloudmorrow-quill/{self.manifest.id}")
        body = base64.b64decode(args.get("body") or "") or None
        timeout = min(float(args.get("timeout") or FETCH_TIMEOUT), FETCH_TIMEOUT)
        opener = urllib.request.build_opener(_Redirects(self.manifest.fetch))
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with opener.open(request, timeout=timeout) as response:
                status, head, data = response.status, dict(response.headers), response.read(FETCH_MAX + 1)
        except urllib.error.HTTPError as exc:
            status, head, data = exc.code, dict(exc.headers or {}), exc.read(FETCH_MAX + 1)
        except sdk.HostError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise sdk.Invalid(f"could not reach {parts.hostname}: {getattr(exc, 'reason', exc)}") from exc
        if len(data) > FETCH_MAX:
            raise sdk.Invalid(f"{parts.hostname} sent more than {FETCH_MAX // (1024 * 1024)} MB")
        return {"status": status, "headers": head, "body": base64.b64encode(data).decode("ascii")}


# -- the runtime ---------------------------------------------------------------------------
class QuillCode:
    """The sandboxes, and every way into them."""

    def __init__(self, state: AppState) -> None:
        self.state = state
        self.config = state.config
        self.trusted = state.config.quill_code == "trusted"
        self._guests: dict[str, tuple[str, Guest | InProcessGuest]] = {}
        self._logs: dict[str, ServiceLog] = {}
        self._lock = threading.RLock()
        self._hooks: queue.Queue = queue.Queue()
        self._busy = threading.Event()
        self._local = threading.local()
        self._running_jobs: set[tuple[str, str]] = set()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        with connect(self.config.db_path) as conn:
            conn.executescript(TABLE)
        conn.close()
        state.records.on_change.append(self._on_change)
        state.quills.listeners.append(self.reconcile)

    # -- life ------------------------------------------------------------------------------
    def start(self) -> None:
        if self._worker is None:
            self._worker = threading.Thread(target=self._run_hooks, name="quill-hooks", daemon=True)
            self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        self._hooks.put(None)
        with self._lock:
            guests, self._guests = list(self._guests.values()), {}
        for _, guest in guests:
            guest.stop()

    def reconcile(self) -> None:
        """Stop the sandboxes of Quills that went, were switched off, or were installed again."""
        with self._lock:
            for quill_id, (stamp, guest) in list(self._guests.items()):
                manifest = self.state.quills.quills.get(quill_id)
                if manifest is None or self._stamp(manifest) != stamp or not self._on(quill_id):
                    guest.stop()
                    del self._guests[quill_id]

    def _on(self, quill_id: str) -> bool:
        try:
            return self.state.features.enabled(quill_id)
        except Exception:
            return True

    @staticmethod
    def _stamp(manifest: Manifest) -> str:
        return str(manifest.origin.get("installed_at", "")) + manifest.version

    def log(self, quill_id: str) -> ServiceLog:
        if quill_id not in self._logs:
            self._logs[quill_id] = ServiceLog(self.config.data_dir / "logs" / "quills" / quill_id / "code.log")
        return self._logs[quill_id]

    def tail(self, quill_id: str, lines: int = 50) -> list[str]:
        return self.log(quill_id).tail(lines)

    def _guest(self, manifest: Manifest) -> Guest | InProcessGuest:
        with self._lock:
            stamp = self._stamp(manifest)
            found = self._guests.get(manifest.id)
            if found is not None and found[0] == stamp:
                return found[1]
            if found is not None:
                found[1].stop()
            kind = InProcessGuest if self.trusted else Guest
            logfile = self.log(manifest.id)
            guest = kind(
                Path(manifest.folder or self.state.quills.quills_dir / manifest.id),
                manifest.code,
                runtime_base=self.config.data_dir / "sandbox",
                on_log=lambda line: logfile.write(line + "\n"),
            )
            self._guests[manifest.id] = (stamp, guest)
            return guest

    # -- one call --------------------------------------------------------------------------
    def installed(self, quill_id: str) -> Manifest:
        manifest = self.state.quills.quills.get(quill_id)
        if manifest is None:
            raise CodeError("notfound", f"{quill_id} is not installed")
        if not self._on(quill_id):
            raise CodeError("off", f"{manifest.name} is switched off on this server")
        if not manifest.code:
            raise CodeError("notfound", f"{manifest.name} has no code")
        return manifest

    def principal_for(self, manifest: Manifest, username: str, *, via: str) -> Principal:
        models = manifest.models
        if via == "assistant":
            models = frozenset(m for m in models if m not in NEVER_FOR_ASSISTANTS)
        return Principal("quill", username, quill=manifest.id, models=models)

    def _user(self, username: str) -> dict:
        user = self.state.users.get(username)
        circles = []
        if self.state.circles is not None:
            try:
                circles = [c.name for c in self.state.circles.circles_of(username)]
            except Exception:
                circles = []
        return {
            "username": username,
            "name": (user.display_name if user else "") or username,
            "admin": bool(user and user.is_admin),
            "circles": circles,
        }

    def run(
        self,
        manifest: Manifest,
        kind: str,
        name: str,
        principal: Principal,
        *,
        via: str = "person",
        ctx: dict | None = None,
        args: dict | None = None,
        timeout: float = CALL_TIMEOUT,
    ) -> object:
        """Run one handler as *principal*; its result, or CodeError."""
        data = {"quill": manifest.id, "user": self._user(principal.username), "where": "server", **(ctx or {})}
        host = HostCalls(self, manifest, principal, via=via)
        try:
            return self._guest(manifest).call(kind, name, data, args or {}, host, timeout=timeout)
        except Failed as failure:
            if failure.kind in ("error", "timeout"):
                self.log(manifest.id).note(f"{kind} {name} failed: {failure.message}")
                if failure.trace:
                    self.log(manifest.id).write(failure.trace.rstrip() + "\n")
            raise CodeError(failure.kind, failure.message, failure.trace) from failure
        except SandboxError as exc:
            self.log(manifest.id).note(str(exc))
            raise CodeError("unavailable", str(exc)) from exc

    # -- views and actions ---------------------------------------------------------------------
    def view(self, username: str, quill_id: str, screen_id: str, params: dict, *, record: str = "") -> dict:
        manifest = self.installed(quill_id)
        screen = next((s for s in manifest.screens if s["id"] == screen_id), None)
        if screen is None or screen["kit"] != "view":
            raise CodeError("notfound", f"{manifest.name} has no view called {screen_id}")
        principal = self.principal_for(manifest, username, via="person")
        ctx: dict = {"params": {str(k): str(v) for k, v in params.items()}}
        if record:
            model = screen.get("model") or str(params.get("model", ""))
            if not model:
                raise CodeError("invalid", "a record is opened with its datamodel")
            try:
                ctx["record"] = self.state.records.get(principal, model, record).to_dict()
            except STORE_ERRORS as exc:
                raise CodeError(_kind(exc), str(_host_error(exc))) from exc
        tree = self.run(manifest, "view", screen["view"], principal, ctx=ctx)
        try:
            return ui.check(
                tree,
                actions={a["id"] for a in manifest.actions},
                screens={s["id"] for s in manifest.screens},
            )
        except ui.TreeError as exc:
            self.log(manifest.id).note(f"view {screen_id}: {exc}")
            raise CodeError("error", str(exc)) from exc

    def actions_on(self, model: str) -> list[tuple[Manifest, dict]]:
        """Every action of every Quill that is on, on records of *model*."""
        found = []
        for manifest in self.state.quills.quills.values():
            if not manifest.code or not self._on(manifest.id):
                continue
            found.extend((manifest, a) for a in manifest.actions if a.get("on") == model)
        return found

    def action(
        self,
        username: str,
        quill_id: str,
        action_id: str,
        *,
        record: str = "",
        fields: dict | None = None,
        via: str = "person",
    ) -> list[dict]:
        """Press an action: its form checked, its record found as the person, its effects."""
        manifest = self.installed(quill_id)
        action = next((a for a in manifest.actions if a["id"] == action_id), None)
        if action is None:
            raise CodeError("notfound", f"{manifest.name} has no action {action_id}")
        if via == "assistant" and not action.get("assistant", True):
            raise CodeError("refused", f"{action['label']} is not for an assistant")
        principal = self.principal_for(manifest, username, via=via)
        args: dict = {"fields": self._form(manifest, action, principal, fields or {})}
        if action.get("on"):
            if not record:
                raise CodeError("invalid", f"{action['label']} is done to a {action['on']}: which one?")
            try:
                args["record"] = self.state.records.get(principal, action["on"], record).to_dict()
            except STORE_ERRORS as exc:
                raise CodeError(_kind(exc), str(_host_error(exc))) from exc
        elif record:
            raise CodeError("invalid", f"{action['label']} is not done to a record")
        effects = self.run(manifest, "action", action["handler"], principal, via=via, args=args)
        screens = {s["id"] for s in manifest.screens}
        actions = {a["id"] for a in manifest.actions}
        for effect in effects or []:
            if effect.get("effect") == "go" and effect.get("screen") not in screens:
                raise CodeError("error", f"{action_id} went to {effect.get('screen')!r}, which is not a screen")
            if effect.get("effect") == "confirm" and effect.get("then") not in actions:
                raise CodeError("error", f"{action_id} asks to confirm {effect.get('then')!r}, which is not an action")
        return list(effects or [])

    def _form(self, manifest: Manifest, action: dict, principal: Principal, given: dict) -> dict:
        """The action's fields, checked and made their kinds, the way a record's are."""
        fields = action_fields(action)
        known = {f.name for f in fields}
        unknown = sorted(set(given) - known)
        if unknown:
            raise CodeError("invalid", f"{action['label']} has no field {unknown[0]!r}")
        shape = SimpleNamespace(id=f"{manifest.id} {action['id']}")
        out: dict = {}
        for f in fields:
            value = given.get(f.name, f.default)
            if value in (None, "") and f.required:
                raise CodeError("invalid", f"{f.label or f.name.replace('_', ' ')} is needed")
            if value in (None, ""):
                if f.name in given or f.default is not None:
                    out[f.name] = value
                continue
            try:
                value = _coerce(shape, f, value)
            except RecordError as exc:
                raise CodeError("invalid", str(exc)) from exc
            if f.kind == "link":
                try:
                    self.state.records.get(principal, f.to, str(value))
                except STORE_ERRORS as exc:
                    raise CodeError("invalid", f"{f.name}: no such {f.to} of yours") from exc
            out[f.name] = value
        return out

    # -- hooks ---------------------------------------------------------------------------------
    def _on_change(self, principal: Principal, action: str, record: Record, before: dict | None) -> None:
        if principal.kind == DATASET:
            return
        depth = getattr(self._local, "depth", 0)
        hooking = getattr(self._local, "quill", "")
        after = record.fields
        changed = sorted(
            k for k in set(after) | set(before or {}) if (before or {}).get(k) != after.get(k)
        ) if before is not None else sorted(after)
        for manifest in list(self.state.quills.quills.values()):
            if not manifest.hooks or not manifest.code:
                continue
            if principal.kind == "quill" and principal.quill == manifest.id == hooking:
                continue
            for hook in manifest.hooks:
                if hook["on"] != record.model or action not in hook["when"]:
                    continue
                if action == "changed" and hook.get("fields") and not set(hook["fields"]) & set(changed):
                    continue
                if depth >= HOOK_DEPTH:
                    self.log(manifest.id).note(
                        f"hook on {record.model} not run: {HOOK_DEPTH} hooks deep already"
                    )
                    continue
                self._busy.set()
                self._hooks.put(
                    (manifest.id, hook, principal, action, record.to_dict(), before, changed, depth + 1)
                )

    def _run_hooks(self) -> None:
        while not self._stop.is_set():
            item = self._hooks.get()
            if item is None:
                return
            try:
                self._hook(*item)
            except Exception:
                log.exception("a hook failed")
            finally:
                if self._hooks.empty():
                    self._busy.clear()

    def _hook(self, quill_id, hook, changer, action, record, before, changed, depth) -> None:
        manifest = self.state.quills.quills.get(quill_id)
        if manifest is None or not self._on(quill_id):
            return
        via = "assistant" if changer.kind == "assistant" else "person"
        principal = self.principal_for(manifest, changer.username, via=via)
        change = {"action": action, "record": record, "before": before, "changed": changed}
        self._local.depth, self._local.quill = depth, quill_id
        try:
            self.run(manifest, "hook", hook["handler"], principal, via=via, args={"change": change})
        except CodeError:
            pass  # logged by run
        finally:
            self._local.depth, self._local.quill = 0, ""

    def drain(self, timeout: float = 30.0) -> None:
        """Wait until every queued hook has run: for tests, and for a clean stop."""
        if self._worker is None:
            while not self._hooks.empty():
                item = self._hooks.get()
                if item is not None:
                    self._hook(*item)
            return
        deadline = time.monotonic() + timeout
        while (self._busy.is_set() or not self._hooks.empty()) and time.monotonic() < deadline:
            time.sleep(0.02)

    # -- jobs ------------------------------------------------------------------------------------
    def run_due(self) -> list[str]:
        """Start every `call` job whose time has come; stop sandboxes left idle."""
        started = []
        now = dt.datetime.now(tz=dt.UTC)
        for manifest in list(self.state.quills.quills.values()):
            if not manifest.code or not self._on(manifest.id):
                continue
            for job in manifest.jobs:
                if job["action"] != "call" or (manifest.id, job["id"]) in self._running_jobs:
                    continue
                last = self._last_run(manifest.id, job["id"])
                if last is not None and now - last < parse_duration(job["every"]):
                    continue
                self._running_jobs.add((manifest.id, job["id"]))
                self._record_start(manifest.id, job["id"])
                threading.Thread(target=self._job, args=(manifest, job), daemon=True).start()
                started.append(f"{manifest.id}/{job['id']}")
        with self._lock:
            for quill_id, (_, guest) in list(self._guests.items()):
                if guest.last_used and time.monotonic() - guest.last_used > IDLE:
                    guest.stop()
                    del self._guests[quill_id]
        return started

    def run_job(self, quill_id: str, job_id: str) -> None:
        """Run one `call` job now, and wait for it: `cm quill run`, and tests."""
        manifest = self.installed(quill_id)
        job = next((j for j in manifest.jobs if j["id"] == job_id and j["action"] == "call"), None)
        if job is None:
            raise CodeError("notfound", f"{manifest.name} has no job {job_id} that calls code")
        self._record_start(quill_id, job_id)
        self._job(manifest, job, raise_=True)

    def _job(self, manifest: Manifest, job: dict, *, raise_: bool = False) -> None:
        error = ""
        try:
            owner = runs_as(self.state.users, manifest.origin)
            if not owner:
                raise CodeError("refused", f"{manifest.name} runs as nobody: install it again")
            principal = self.principal_for(manifest, owner, via="person")
            self.run(manifest, "job", job["handler"], principal, timeout=JOB_TIMEOUT)
        except CodeError as exc:
            error = exc.message
            if raise_:
                raise
        finally:
            self._running_jobs.discard((manifest.id, job["id"]))
            with connect(self.config.db_path) as conn:
                conn.execute(
                    "UPDATE quill_call_runs SET last_error = ? WHERE quill = ? AND job = ?",
                    (error, manifest.id, job["id"]),
                )
            conn.close()

    def _last_run(self, quill: str, job: str) -> dt.datetime | None:
        with connect(self.config.db_path) as conn:
            row = conn.execute(
                "SELECT last_started FROM quill_call_runs WHERE quill = ? AND job = ?", (quill, job)
            ).fetchone()
        conn.close()
        return dt.datetime.fromisoformat(row[0]) if row else None

    def _record_start(self, quill: str, job: str) -> None:
        with connect(self.config.db_path) as conn:
            conn.execute(
                "INSERT INTO quill_call_runs (quill, job, last_started) VALUES (?, ?, ?)"
                " ON CONFLICT(quill, job) DO UPDATE SET last_started = excluded.last_started",
                (quill, job, _now()),
            )
        conn.close()

    def jobs_status(self, quill_id: str) -> list[dict]:
        manifest = self.state.quills.quills.get(quill_id)
        if manifest is None:
            return []
        rows = []
        with connect(self.config.db_path) as conn:
            for job in manifest.jobs:
                if job["action"] != "call":
                    continue
                row = conn.execute(
                    "SELECT last_started, last_error FROM quill_call_runs WHERE quill = ? AND job = ?",
                    (quill_id, job["id"]),
                ).fetchone()
                rows.append({
                    "id": job["id"], "every": job["every"], "handler": job["handler"],
                    "last_run": row[0] if row else None, "last_error": row[1] if row else "",
                    "running": (quill_id, job["id"]) in self._running_jobs,
                })
        conn.close()
        return rows

    # -- webhooks and APIs -------------------------------------------------------------------
    def webhook(self, manifest: Manifest, hook: dict, request: dict) -> dict:
        owner = runs_as(self.state.users, manifest.origin)
        if not owner:
            raise CodeError("unavailable", f"{manifest.name} runs as nobody")
        principal = self.principal_for(manifest, owner, via="person")
        return self.run(manifest, "webhook", hook["handler"], principal, args={"request": request})

    def api(self, manifest: Manifest, api: dict, username: str, request: dict, *, as_quill: bool) -> dict:
        """An API answered by code: as the installer, told who asked (`request.user`)."""
        owner = runs_as(self.state.users, manifest.origin)
        if not owner:
            raise CodeError("unavailable", f"{manifest.name} runs as nobody")
        principal = self.principal_for(manifest, owner, via="person")
        request = {**request, "user": "" if as_quill else username}
        return self.run(manifest, "api", api["handler"], principal, args={"request": request})


def _kind(exc: Exception) -> str:
    if isinstance(exc, UnknownModelError | UnknownRecordError):
        return "notfound"
    if isinstance(exc, Refused):
        return "refused"
    if isinstance(exc, RecordConflictError):
        return "conflict"
    return "invalid"
