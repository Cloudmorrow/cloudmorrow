"""Testing a Quill on your own machine: the real record store and gate, and its code, in pytest.

    from cloudmorrow.quill.testing import Harness

    def test_logging_a_service_moves_the_odometer():
        q = Harness(".")
        van = q.seed("vehicle", name="Van", **{"fleet.odometer": 1000})
        done = q.act("log-service", van, date="2026-09-28", km=1200)
        assert done.toast == "Logged Van at 1200 km"
        assert q.get("vehicle", van.id)["fleet.odometer"] == 1200

A `Harness` is a Cloudmorrow server with nobody else on it, in a temporary
folder: the Quill in *folder* installed the way a server installs it (so a
manifest that would not install fails here first), the foundational
datamodels it uses, the record store with its sealing and positions, the
gate and circles, and the Quill's code. Nothing is mocked but the network:
`q.fetch` answers what the code fetches, from what the test put there.

The code runs in this interpreter, so a failure is a Python traceback and a
debugger stops in it. `cm quill test --sandbox` runs the same tests with the
code inside the sandbox instead, as a server runs it — set by the
environment (`CLOUDMORROW_QUILL_SANDBOX=1`), so the tests do not change.

It needs the `server` extra: `pip install "cloudmorrow[server]"`, which the
template's pyproject.toml asks for.
"""

from __future__ import annotations

import atexit
import base64
import json
import os
import shutil
import tempfile
from pathlib import Path

from cloudmorrow.quill import text as _text
from cloudmorrow.quill.context import Record, Refused

__all__ = ["Fetches", "Harness", "HandlerFailed", "Result", "View", "datamodels_folder"]

DEFAULT_USER = "alice"
PASSWORD = "harness-password"


class HandlerFailed(AssertionError):
    """The Quill's code raised, or returned something the core would not take."""


# -- the foundational datamodels, fetched once --------------------------------------------------
def datamodels_folder() -> Path | None:
    """A checkout of the foundational datamodels: $CLOUDMORROW_DATAMODELS, or the
    catalog's pinned release, downloaded once and kept in the user's cache."""
    given = os.environ.get("CLOUDMORROW_DATAMODELS")
    if given:
        return Path(given).expanduser()
    from cloudmorrow.server.config import DEFAULT_QUILL_CATALOG
    from cloudmorrow.server.quills import fetch, load_catalog

    catalog_location = os.environ.get("CLOUDMORROW_QUILL_CATALOG", DEFAULT_QUILL_CATALOG)
    catalog = load_catalog(catalog_location)
    spec = catalog.datamodels
    if not spec.get("repo"):
        return None
    if not str(spec["repo"]).startswith(("https://", "http://")):
        return fetch(str(spec["repo"]), base=catalog.base, into=Path(tempfile.mkdtemp()))
    ref = str(spec.get("ref", "")) or "main"
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "cloudmorrow" / "datamodels"
    target = cache / "".join(c if c.isalnum() or c in ".-_" else "_" for c in ref)
    if not target.is_dir():
        staging = Path(tempfile.mkdtemp(dir=cache.parent if cache.parent.exists() else None))
        found = fetch(str(spec["repo"]), ref, into=staging)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(found), str(target))
    return target


# -- what a test gets back ---------------------------------------------------------------------
class Result:
    """What pressing an action did: its effects, or why it was refused."""

    def __init__(self, effects: list[dict] | None = None, *, kind: str = "", message: str = "") -> None:
        self.effects = list(effects or [])
        self.kind = kind
        self.message = message

    @property
    def ok(self) -> bool:
        return not self.kind and not any(e["effect"] == "error" for e in self.effects)

    @property
    def refused(self) -> bool:
        """The gate said no, or the record is not theirs to see."""
        return self.kind in ("refused", "notfound")

    @property
    def error(self) -> str:
        """Why the form stays open: a field it will not take, or the code's `error(...)`."""
        if self.kind == "invalid":
            return self.message
        return next((e["text"] for e in self.effects if e["effect"] == "error"), "")

    @property
    def toast(self) -> str:
        return next((e["text"] for e in self.effects if e["effect"] == "toast"), "")

    @property
    def opened(self) -> list[tuple[str, str]]:
        return [(e["model"], e["id"]) for e in self.effects if e["effect"] == "open"]

    def __repr__(self) -> str:
        return f"Result({self.kind or 'ok'} {self.message or self.effects!r})"


class View:
    """A view as a test sees it: its tree, and the tree as text."""

    def __init__(self, tree: dict, labels: dict[str, str]) -> None:
        self.tree = tree
        self._labels = labels

    def text(self) -> str:
        return _text.render(self.tree, actions=self._labels)

    def find(self, kind: str) -> list[dict]:
        """Every primitive of *kind* in the tree, in order."""
        found: list[dict] = []

        def walk(node: dict) -> None:
            if node.get("ui") == kind:
                found.append(node)
            for key in ("children", "items"):
                for child in node.get(key) or []:
                    walk(child)
            for tab in node.get("tabs") or []:
                walk(tab["child"])

        walk(self.tree)
        return found

    @property
    def buttons(self) -> list[str]:
        return [b["label"] for b in self.find("button")]

    def __str__(self) -> str:
        return self.text()


class Fetches:
    """What `ctx.fetch` gets, in a test: answers put here by URL; anything else is a 404."""

    def __init__(self) -> None:
        self._answers: dict[tuple[str, str], dict] = {}
        self.sent: list[dict] = []

    def add(self, url: str, *, method: str = "GET", json_body=None, text: str = "", status: int = 200,
            headers: dict | None = None, **kwargs) -> None:
        if "json" in kwargs:
            json_body = kwargs.pop("json")
        body = json.dumps(json_body).encode() if json_body is not None else text.encode()
        head = dict(headers or {})
        if json_body is not None:
            head.setdefault("Content-Type", "application/json")
        self._answers[(method.upper(), url)] = {
            "status": status, "headers": head, "body": base64.b64encode(body).decode("ascii"),
        }

    def __call__(self, method: str, url: str, headers: dict, body: bytes) -> dict:
        self.sent.append({"method": method, "url": url, "headers": headers, "body": body})
        found = self._answers.get((method, url))
        if found is None:
            return {"status": 404, "headers": {}, "body": base64.b64encode(b"no answer in the test").decode()}
        return found


# -- the harness ---------------------------------------------------------------------------------
class Harness:
    """A server with one Quill on it, for a test. See the module's docstring."""

    def __init__(
        self,
        folder: str | Path = ".",
        *,
        datamodels: str | Path | None = None,
        circles: dict[str, dict[str, str]] | None = None,
        sandbox: bool | None = None,
        user: str = DEFAULT_USER,
    ) -> None:
        from cloudmorrow.server.app import create_app
        from cloudmorrow.server.config import ServerConfig
        from cloudmorrow.server.db import UserStore
        from cloudmorrow.server.security import hash_password

        self.folder = Path(folder).resolve()
        if sandbox is None:
            sandbox = os.environ.get("CLOUDMORROW_QUILL_SANDBOX", "") not in ("", "0", "false")
        self._tmp = Path(tempfile.mkdtemp(prefix="quill-harness-"))
        atexit.register(shutil.rmtree, self._tmp, True)
        config = ServerConfig(
            notes_dir=self._tmp / "notes",
            data_dir=self._tmp / "data",
            secret_key="a-key-for-a-test-harness-long-enough-for-hs256",
            quill_catalog=str(self._tmp / "no-catalog"),
            quill_code="sandbox" if sandbox else "trusted",
        )
        config.ensure_dirs()
        self._users = UserStore(config.db_path)
        self._users.create(user, hash_password(PASSWORD), is_admin=True)
        self._app = create_app(config)
        self.state = self._app.state.cloudmorrow
        if sandbox:
            from cloudmorrow import sandbox as _sandbox

            runtime = _sandbox.ensure_runtime(_sandbox.runtime_dir())
            (config.data_dir / "sandbox").symlink_to(runtime.parent, target_is_directory=True)
        source = Path(datamodels) if datamodels else datamodels_folder()
        plan = self.state.quills.install(self.folder, source, origin={"installed_by": user})
        self.quill = plan["id"]
        self.manifest = self.state.quills.quills[self.quill]
        self.fetch = Fetches()
        self.state.code.fetcher = self.fetch
        self.user = user
        for name, rules in (circles or {}).items():
            self.state.circles.create(name, rules=rules)

    # -- who ---------------------------------------------------------------------------------
    def as_user(self, username: str, *, circles: list[str] = (), admin: bool = False) -> Harness:
        """The same server, as somebody else: made the first time, put in *circles*."""
        from cloudmorrow.server.security import hash_password

        if self._users.get(username) is None:
            self._users.create(username, hash_password(PASSWORD), is_admin=admin)
        if circles:
            # In these circles and no others: circles add up, and Members has everything.
            for circle in self.state.circles.circles_of(username):
                self.state.circles.leave(circle.id, username)
        for name in circles:
            circle = next((c for c in self.state.circles.list() if c.name == name), None)
            if circle is None:
                raise ValueError(f"there is no circle {name!r}: give it to Harness(circles=...)")
            self.state.circles.join(circle.id, username)
        other = object.__new__(Harness)
        other.__dict__.update(self.__dict__)
        other.user = username
        return other

    def _principal(self):
        from cloudmorrow.server.records import Principal

        found = self._users.get(self.user)
        return Principal.person(self.user, admin=bool(found and found.is_admin))

    # -- records, as the person would make them --------------------------------------------------
    def seed(self, model: str, fields: dict | None = None, **values) -> Record:
        """Make a record as the person, the way a screen would: hooks run."""
        record = self.state.records.create(self._principal(), model, {**(fields or {}), **values})
        self.state.code.drain()
        return Record(record.to_dict())

    def get(self, model: str, id: str) -> Record:  # noqa: A002
        return Record(self.state.records.get(self._principal(), model, getattr(id, "id", id)).to_dict())

    def list(self, model: str, **where) -> list[Record]:
        return [Record(r.to_dict()) for r in self.state.records.list(self._principal(), model, where)]

    def change(self, model: str, id: str, fields: dict | None = None, **values) -> Record:  # noqa: A002
        record = self.state.records.update(self._principal(), model, getattr(id, "id", id), {**(fields or {}), **values})
        self.state.code.drain()
        return Record(record.to_dict())

    def delete(self, model: str, id: str) -> None:  # noqa: A002
        self.state.records.delete(self._principal(), model, getattr(id, "id", id))
        self.state.code.drain()

    def secret(self, key: str, value: str) -> None:
        """Put a secret in the person's own vault, for `ctx.secret`."""
        from cloudmorrow.server.secrets import DEFAULT_ENVIRONMENT, DEFAULT_VAULT

        self.state.secrets.set(self.user, DEFAULT_VAULT, DEFAULT_ENVIRONMENT, key, value)

    # -- the code -------------------------------------------------------------------------------
    def _raise_for(self, exc) -> None:
        if exc.kind in ("error", "timeout", "unavailable"):
            raise HandlerFailed(f"{exc.message}\n\n{exc.trace}".rstrip()) from exc

    def act(self, action: str, record=None, *, via: str = "person", **fields) -> Result:
        """Press an action, as the person, with its form filled in with *fields*."""
        from cloudmorrow.server.quillhandlers import CodeError

        record_id = getattr(record, "id", record) or ""
        try:
            effects = self.state.code.action(
                self.user, self.quill, action, record=record_id, fields=fields, via=via
            )
        except CodeError as exc:
            self._raise_for(exc)
            return Result(kind=exc.kind, message=exc.message)
        finally:
            self.state.code.drain()
        return Result(effects)

    def view(self, screen: str, record=None, **params) -> View:
        from cloudmorrow.server.quillhandlers import CodeError

        try:
            tree = self.state.code.view(
                self.user, self.quill, screen, {k: str(v) for k, v in params.items()},
                record=getattr(record, "id", record) or "",
            )
        except CodeError as exc:
            self._raise_for(exc)
            raise AssertionError(f"{screen}: {exc.message}") from exc
        return View(tree, {a["id"]: a["label"] for a in self.manifest.actions})

    def run_job(self, job: str) -> None:
        from cloudmorrow.server.quillhandlers import CodeError

        try:
            self.state.code.run_job(self.quill, job)
        except CodeError as exc:
            self._raise_for(exc)
            raise AssertionError(f"{job}: {exc.message}") from exc
        finally:
            self.state.code.drain()

    def webhook(self, hook: str, *, json_body=None, body: bytes | str = b"", headers: dict | None = None,
                **kwargs) -> dict:
        """What a webhook answered (`{status, body, headers}`), for a request from outside."""
        if "json" in kwargs:
            json_body = kwargs.pop("json")
        found = next((h for h in self.manifest.webhooks if h["id"] == hook), None)
        if found is None or not found.get("handler"):
            raise AssertionError(f"{self.quill} has no webhook {hook} answered by code")
        raw = json.dumps(json_body).encode() if json_body is not None else (body.encode() if isinstance(body, str) else body)
        request = {"method": "POST", "path": found["path"], "query": {}, "headers": dict(headers or {}),
                   "body": base64.b64encode(raw).decode("ascii")}
        return self._answer(lambda: self.state.code.webhook(self.manifest, found, request))

    def api(self, path: str, *, method: str = "GET", json_body=None, **kwargs) -> dict:
        """What one of its APIs answered, asked by the person."""
        if "json" in kwargs:
            json_body = kwargs.pop("json")
        found = next(
            (a for a in self.manifest.apis
             if a.get("handler") and (not a.get("prefix") or path == a["prefix"] or path.startswith(a["prefix"] + "/"))),
            None,
        )
        if found is None:
            raise AssertionError(f"{self.quill} has no API answered by code at {path}")
        raw = json.dumps(json_body).encode() if json_body is not None else b""
        request = {"method": method, "path": path, "query": {}, "headers": {},
                   "body": base64.b64encode(raw).decode("ascii")}
        return self._answer(lambda: self.state.code.api(self.manifest, found, self.user, request, as_quill=False))

    def _answer(self, call) -> dict:
        from cloudmorrow.server.quillhandlers import CodeError

        try:
            answer = call()
        except CodeError as exc:
            self._raise_for(exc)
            return {"status": exc.status, "body": exc.message, "headers": {}}
        finally:
            self.state.code.drain()
        answer = dict(answer)
        try:
            answer["json"] = json.loads(answer.get("body") or "null")
        except ValueError:
            answer["json"] = None
        return answer

    def machine(self, handler: str, *, folders: dict[str, str | Path]) -> object:
        """Run a machine handler here, given *folders*, as the person: what it returned."""
        from cloudmorrow.quill import context as sdk
        from cloudmorrow.sandbox import Failed, Guest, InProcessGuest
        from cloudmorrow.server.quillhandlers import HostCalls

        spec = next((m for m in self.manifest.machine if m["id"] == handler), None)
        if spec is None:
            raise AssertionError(f"{self.quill} has no machine handler {handler}")
        missing = {f["name"] for f in spec["folders"]} - set(folders)
        if missing:
            raise AssertionError(f"it needs the folders {', '.join(sorted(missing))}")
        principal = self.state.code.principal_for(self.manifest, self.user, via="person")
        calls = HostCalls(self.state.code, self.manifest, principal, via="person")

        def host(op: str, args: dict):
            if op == "run":
                raise sdk.Refused("ctx.run is not run in a test; give the handler what it would print instead")
            return calls(op, args)

        kind = InProcessGuest if self.state.code.trusted else Guest
        guest = kind(
            self.folder, self.manifest.code,
            folders={n: (Path(p), next(f["access"] for f in spec["folders"] if f["name"] == n) == "write")
                     for n, p in folders.items()},
            runtime_base=self.state.config.data_dir / "sandbox",
            on_log=lambda line: self.state.code.log(self.quill).write(line + "\n"),
        )
        try:
            return guest.call("machine", spec["handler"], {"quill": self.quill, "user": {"username": self.user},
                                                          "where": "machine"}, {}, host)
        except Failed as failure:
            raise HandlerFailed(f"{failure.message}\n\n{failure.trace}".rstrip()) from failure
        finally:
            guest.stop()
            self.state.code.drain()

    @property
    def log(self) -> list[str]:
        """What the code printed and logged, and what failed."""
        return self.state.code.tail(self.quill, 500)

    def close(self) -> None:
        self.state.code.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def __enter__(self) -> Harness:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# So `from cloudmorrow.quill.testing import Refused` reads naturally in a test.
Refused = Refused
