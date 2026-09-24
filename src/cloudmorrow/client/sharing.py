"""Whether a directory on this machine can be shared from here.

A machine share serves a directory through the agent on this machine, which
runs as you. So the check is yours to make, before the server is asked: is
it there, is it a directory, and can you read and write it — because what
you cannot read the agent cannot serve, and what you cannot write nobody
can write on a mount of it.
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve(raw: str) -> Path:
    """The directory *raw* names, with `~` and `..` worked out."""
    return Path(raw.strip()).expanduser().resolve()


def problem(raw: str) -> str | None:
    """Why *raw* cannot be shared from this machine, or None when it can."""
    path = resolve(raw)
    if not path.exists():
        return f"{path} is not there"
    if not path.is_dir():
        return f"{path} is a file, not a directory"
    if not os.access(path, os.R_OK | os.X_OK):
        return f"you cannot read {path}, so the agent could not serve it"
    if not os.access(path, os.W_OK):
        return f"you cannot write to {path}, so nothing could be put there through a mount"
    return None
