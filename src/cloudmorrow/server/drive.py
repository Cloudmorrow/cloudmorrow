"""My Files: the drive every account has on the server.

A share is something an admin makes and everyone's machines mount. This is
the other thing people expect of a server: a folder of their own, there
from the day the account is, with nothing to set up. It is served exactly
as a server share is — over WebDAV at `/dav/my-files/`, and to the browser
through the same file routes — so every client that can open a share can
open it. What it is not is a row in the shares table: it cannot be made,
renamed or removed, and the name `my-files` is kept for it.

Where it is: `<user's tree>/files`, beside their notes (`config.files_root`).
Only the owner ever sees it; the WebDAV and the API sides both ask for the
caller's drive, never anyone else's.
"""

from __future__ import annotations

import logging
from pathlib import Path

from cloudmorrow.server.config import ServerConfig
from cloudmorrow.server.shares import DRIVE, DRIVE_NAME, Share

__all__ = ["DRIVE", "DRIVE_NAME", "DESCRIPTION", "user_drive", "is_drive"]

log = logging.getLogger(__name__)

DESCRIPTION = "Your own files on the server"


def is_drive(name: str) -> bool:
    return (name or "").strip().lower() == DRIVE_NAME


def user_drive(config: ServerConfig, username: str) -> Share:
    """*username*'s drive, as the share it is served as. The folder is made
    the first time it is asked for, so a fresh account has one to open."""
    root: Path = config.files_root(username)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # Served all the same: the listing says it cannot be read, which is
        # truer than a missing drive would be.
        log.warning("cannot make %s's files folder at %s: %s", username, root, exc)
    return Share(
        id=0,
        owner=username,
        name=DRIVE_NAME,
        path=root,
        managed=True,
        description=DESCRIPTION,
        created_at="",
        updated_at="",
        kind=DRIVE,
        agent_id=None,
    )
