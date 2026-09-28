"""Files only their owner may read: tokens, keys, exported secrets.

Writing the file and then narrowing its mode leaves a moment in which anyone
on the machine can read it. These are created private instead.
"""

from __future__ import annotations

import os
from pathlib import Path


def write_private(path: Path, text: str) -> None:
    """Write a file only its owner can read, private from the moment it exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as file:
        file.write(text)
    # A file that already existed keeps its old mode through O_CREAT.
    os.chmod(path, 0o600)
