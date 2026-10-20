"""Runtimes on the server: `cloudmorrow.runtimes`, refusing as a QuillError.

The store itself is shared with the agent, which keeps a machine's runtimes
the same way (docs/QUILLS.md, *Runtimes*); here every refusal is a
QuillError so the install sheet and the routes say it the way they say
everything else.
"""

from __future__ import annotations

from pathlib import Path

from cloudmorrow import runtimes as shared
from cloudmorrow.runtimes import MAX_RUNTIME_DOWNLOAD, RUNTIMES_DIR, build_for, platform_of, said_size
from cloudmorrow.server.quills.manifest import QuillError

__all__ = [
    "MAX_RUNTIME_DOWNLOAD",
    "RUNTIMES_DIR",
    "RuntimeStore",
    "build_for",
    "check_runtime",
    "platform_of",
    "said_size",
]


def check_runtime(runtime_id: str, spec: object) -> None:
    """A runtime as the catalog describes it, or why it cannot be used."""
    shared.check_runtime(runtime_id, spec, QuillError)


class RuntimeStore(shared.RuntimeStore):
    """The runtimes on this server, under `<data_dir>/runtimes/<id>/`."""

    def __init__(self, root: Path, fetch=None) -> None:
        super().__init__(root, fetch, QuillError)
