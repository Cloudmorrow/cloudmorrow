"""Shared filesystem-path helpers and validation."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath


class UnsafePathError(ValueError):
    """Raised when a client-supplied path escapes its root or is otherwise illegal."""


_ILLEGAL = re.compile(r"[\x00-\x1f]")
_RESERVED = {".", "..", ""}


def normalise_rel_path(raw: str) -> PurePosixPath:
    """Normalise a client-supplied relative path, rejecting anything that escapes root.

    Accepts POSIX-style paths only (the wire format), with or without a leading slash.
    """
    if raw is None:
        raise UnsafePathError("path is required")
    candidate = raw.strip().replace("\\", "/").lstrip("/")
    if not candidate:
        raise UnsafePathError("path is empty")
    if _ILLEGAL.search(candidate):
        raise UnsafePathError("path contains control characters")
    parts: list[str] = []
    for part in PurePosixPath(candidate).parts:
        if part in _RESERVED:
            raise UnsafePathError(f"illegal path segment: {part!r}")
        if part.startswith("/"):
            raise UnsafePathError("absolute paths are not allowed")
        parts.append(part)
    if not parts:
        raise UnsafePathError("path is empty")
    return PurePosixPath(*parts)


def resolve_within(root: Path, raw: str) -> Path:
    """Resolve *raw* under *root*, guaranteeing the result stays inside it."""
    rel = normalise_rel_path(raw)
    root = root.resolve()
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise UnsafePathError("path escapes the notes root")
    return target
