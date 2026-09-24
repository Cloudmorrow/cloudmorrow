"""The rules a config bundle's file names obey.

Both ends need these and neither should import the other: the server checks a
path before it stores it, and the agent checks the same path again before it
writes the file, because the agent is the one with a home directory to lose.
So they live here, next to the palette, needing nothing but the standard
library.
"""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath

MAX_PATH_CHARS = 512


class InvalidPathError(ValueError):
    """A file name that has no business being in a bundle."""


def digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def validate_path(raw: str) -> str:
    """A bundle path is relative, forward-slashed and stays under the root.

    Whatever is in the bundle gets written into `~/.config`, so this is the
    check that has to be certain it cannot be talked into writing anywhere
    else — and it runs on both sides of the wire, not just the far one.
    """
    path = str(raw).strip().replace("\\", "/")
    if not path:
        raise InvalidPathError("empty path")
    if path.startswith("~"):
        raise InvalidPathError(f"{raw}: must be relative to the bundle root")
    pure = PurePosixPath(path)
    if pure.is_absolute():
        raise InvalidPathError(f"{raw}: must be relative to the bundle root")
    if any(part in {"..", "."} for part in pure.parts):
        raise InvalidPathError(f"{raw}: must not climb out of the bundle root")
    if len(path) > MAX_PATH_CHARS:
        raise InvalidPathError(f"{raw}: path is too long")
    return str(pure)
