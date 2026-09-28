"""The Quill SDK: what a Quill's Python imports, and all it imports of Cloudmorrow.

A Quill's code is handlers the manifest names: views, actions, hooks, jobs,
webhooks, APIs and machine handlers. Each is a plain function, registered
under its name by a decorator; what it *is* — its label, its form, what it
is on — is in `quill.toml`, so nothing has to run to know what a Quill does.

    from cloudmorrow.quill import action, view, ui, toast

    @view("garage")
    def garage(ctx):
        return ui.table(ctx.records.list("vehicle"), columns=["name"])

    @action("log_service")
    def log_service(ctx, vehicle, date, km):
        ctx.records.patch("vehicle", vehicle.id, {"fleet.odometer": km})
        return toast(f"Logged at {km} km")

On a server this runs in the sandbox: CPython compiled to WebAssembly, with
no files, no sockets and no processes, and every `ctx.records` call a request
to the core, which answers it through the gate. In tests it runs in plain
Python against the same record store (`cloudmorrow.quill.testing`). The code
cannot tell which, and must not need to.

Only the standard library and this package are importable in the sandbox,
so nothing here imports anything else — not even the rest of `cloudmorrow`.

See docs/QUILLCODE.md.
"""

from __future__ import annotations

from cloudmorrow.quill import ui
from cloudmorrow.quill.context import (
    Conflict,
    Context,
    Invalid,
    NotFound,
    Record,
    Refused,
    Request,
    Response,
)
from cloudmorrow.quill.effects import confirm, error, go, open, redraw, respond, toast
from cloudmorrow.quill.registry import action, api, hook, job, machine, view, webhook

SDK_VERSION = "1"

__all__ = [
    "SDK_VERSION",
    "Conflict",
    "Context",
    "Invalid",
    "NotFound",
    "Record",
    "Refused",
    "Request",
    "Response",
    "action",
    "api",
    "confirm",
    "error",
    "go",
    "hook",
    "job",
    "machine",
    "open",
    "redraw",
    "respond",
    "toast",
    "ui",
    "view",
    "webhook",
]
