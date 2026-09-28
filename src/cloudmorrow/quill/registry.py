"""Registering handlers: a decorator per kind, and the table they fill.

    @action("log_service")      registered as log_service
    @action                     registered under the function's own name

A decorator returns the function unchanged, so a handler is still a function
a test may call. The manifest names handlers; `cm quill check` reads the
decorators from the source (never running it) and says which names are
missing on either side.
"""

from __future__ import annotations

from collections.abc import Callable

KINDS = ("view", "action", "hook", "job", "webhook", "api", "machine")

# kind -> name -> function. One table per interpreter: the sandbox loads one
# Quill; the test harness clears it before it loads the next.
HANDLERS: dict[str, dict[str, Callable]] = {kind: {} for kind in KINDS}


def clear() -> None:
    for table in HANDLERS.values():
        table.clear()


def _register(kind: str):
    def decorator(name_or_function=None):
        def register(function: Callable, name: str | None = None) -> Callable:
            key = name or function.__name__
            if key in HANDLERS[kind] and HANDLERS[kind][key] is not function:
                raise ValueError(f"two {kind} handlers called {key!r}")
            HANDLERS[kind][key] = function
            return function

        if callable(name_or_function):
            return register(name_or_function)
        return lambda function: register(function, name_or_function)

    decorator.__name__ = kind
    decorator.__doc__ = f"Register a {kind} handler, by name or by the function's own."
    return decorator


view = _register("view")
action = _register("action")
hook = _register("hook")
job = _register("job")
webhook = _register("webhook")
api = _register("api")
machine = _register("machine")
