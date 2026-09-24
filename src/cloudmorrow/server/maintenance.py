"""Finding what an older layout left behind, and leaving everything else alone.

Before notes had a tree of their own they were kept per project, in
`<base>/projects/<slug>/notes`. The layout migration moves those notes into
the owner's tree the first time the server sees them; what it cannot move —
a stray file somebody put beside them — it leaves, and an empty `projects/`
is all that remains to remove. Nothing here guesses, and nothing here ever
deletes a note.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cloudmorrow.server.config import ServerConfig
from cloudmorrow.server.db import UserStore
from cloudmorrow.server.notes import ensure_notes_layout


@dataclass(slots=True)
class Orphans:
    directories: list[Path] = field(default_factory=list)
    deleted: bool = False

    @property
    def empty(self) -> bool:
        return not self.directories


def find_orphans(config: ServerConfig) -> Orphans:
    """Every leftover per-project directory in the deployment."""
    orphans = Orphans()
    for user in UserStore(config.db_path).list():
        base = config.user_base(user.username)
        stale = base / "projects"
        if stale.is_dir():
            orphans.directories.append(stale)
    return orphans


def delete_orphans(config: ServerConfig, orphans: Orphans) -> Orphans:
    """Delete what `find_orphans` found. The notes in it are kept, as folders."""
    for directory in orphans.directories:
        # The layout migration moves any notes out first, so nothing readable
        # is thrown away — an empty `projects/` is all that is left to remove.
        ensure_notes_layout(directory.parent)
    orphans.deleted = True
    return orphans
