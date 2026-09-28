"""Loading a Quill's code and calling one handler: the same in the sandbox and in a test.

`load` imports the Quill's module (`code` in the manifest: `quill.py`, or a
`quill/` package) from its folder, which fills the registry. `call` runs one
handler with a context whose every reach goes through *host*, and returns
what it returned in the shape the core expects:

    view      the tree, checked
    action    a list of effects
    hook, job nothing
    webhook, api   a response: {status, body, headers}
    machine   whatever JSON the handler returned

A handler that raises is reported as a failure: the error's kind, its words,
and the part of the traceback that is the Quill's own.
"""

from __future__ import annotations

import importlib
import json
import sys
import traceback
from pathlib import Path

from cloudmorrow.quill import effects, registry, ui
from cloudmorrow.quill.context import Context, HostError, Record, Request


class Change:
    """What a hook is told: what happened to which record, and what it was before."""

    def __init__(self, data: dict) -> None:
        self.action: str = data["action"]  # created, changed, deleted
        self.record = Record(data["record"])
        self.before: dict = dict(data.get("before") or {})
        self.changed: list[str] = list(data.get("changed") or [])

    def __repr__(self) -> str:
        return f"Change({self.action} {self.record.model} {self.record.id})"


class Failure(Exception):
    """A handler failed; `kind` is refused, notfound, invalid, conflict or error."""

    def __init__(self, kind: str, message: str, trace: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.trace = trace

    def to_dict(self) -> dict:
        return {"kind": self.kind, "message": self.message, "trace": self.trace}


def module_name(code: str) -> str:
    """`quill.py` -> quill; `quill` (a package) -> quill."""
    return code[:-3] if code.endswith(".py") else code.rstrip("/")


# The folder of the Quill loaded last, so the next one's is not found behind it.
_on_path: list[str] = []


def load(folder: str | Path, code: str) -> dict[str, list[str]]:
    """Import the Quill in *folder*; returns the handlers it registered, by kind.

    In the sandbox this happens once. In a test, one interpreter loads one
    Quill after another, each with a `quill.py` of its own: the last one's
    folder comes off the path, and its modules out of `sys.modules`, first.
    """
    folder = str(folder)
    name = module_name(code)
    registry.clear()
    for loaded in [m for m in sys.modules if m == name or m.startswith(name + ".")]:
        del sys.modules[loaded]
    for earlier in _on_path:
        while earlier in sys.path:
            sys.path.remove(earlier)
    _on_path[:] = [folder]
    sys.path.insert(0, folder)
    importlib.invalidate_caches()
    importlib.import_module(name)
    return {kind: sorted(table) for kind, table in registry.HANDLERS.items()}


def _handler(kind: str, name: str):
    found = registry.HANDLERS.get(kind, {}).get(name)
    if found is None:
        raise Failure("error", f"there is no {kind} handler called {name!r}")
    return found


def _response(result) -> dict:
    if result is None:
        return {"status": 204, "body": "", "headers": {}}
    if isinstance(result, dict) and result.get("effect") == "respond":
        return {k: v for k, v in result.items() if k != "effect"}
    if isinstance(result, str):
        result = effects.respond(text=result)
    else:
        result = effects.respond(json=result)
    return {k: v for k, v in result.items() if k != "effect"}


def call(kind: str, name: str, data: dict, args: dict, host) -> object:
    """Run one handler. Raises Failure when it goes wrong, for whatever reason."""
    function = _handler(kind, name)
    ctx = Context(host, data)
    try:
        if kind == "view":
            return ui.check(function(ctx))
        if kind == "action":
            record = Record(args["record"]) if args.get("record") else None
            fields = dict(args.get("fields") or {})
            result = function(ctx, record, **fields) if record is not None else function(ctx, **fields)
            return effects.normalise(result)
        if kind == "hook":
            function(ctx, Change(args["change"]))
            return None
        if kind == "job":
            function(ctx)
            return None
        if kind in ("webhook", "api"):
            return _response(function(ctx, Request(args.get("request", {}))))
        if kind == "machine":
            result = function(ctx)
            json.dumps(result)
            return result
    except HostError as exc:
        kind_name = next(
            (k for k, cls in _error_kinds().items() if isinstance(exc, cls)), "refused"
        )
        raise Failure(kind_name, str(exc), _trace(exc)) from exc
    except ui.TreeError as exc:
        raise Failure("error", f"{name}: {exc}", _trace(exc)) from exc
    except Failure:
        raise
    except Exception as exc:
        raise Failure("error", f"{type(exc).__name__}: {exc}", _trace(exc)) from exc
    raise Failure("error", f"no such kind of handler: {kind}")


def _error_kinds():
    from cloudmorrow.quill.context import ERRORS

    return ERRORS


def _trace(exc: BaseException) -> str:
    """The traceback, from the first frame that is not the SDK's."""
    frames = traceback.extract_tb(exc.__traceback__)
    sdk = str(Path(__file__).parent)
    own = [f for f in frames if not f.filename.startswith(sdk)]
    lines = traceback.format_list(own or frames)
    lines += traceback.format_exception_only(type(exc), exc)
    return "".join(lines)[-4000:]
