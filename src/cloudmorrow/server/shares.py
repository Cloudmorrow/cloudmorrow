"""Fileshares: a name and a directory, on the server or on one of your machines.

A share is served over WebDAV at `/dav/<name>/`, and the name is what you
mount. There are two kinds, told apart by where the directory is:

- A **server share** is a folder in the Shares folder on the server —
  `<notes_dir>/Shares/<name>`, or under `shares_dir` — served by the server.
  One folder for every admin's shares, since a share is for everyone's
  machines rather than the account that made it. The folder is named after
  the share: made when the share is, or, when an admin has already put one
  there (rsync'd a library in, say), used as it is. Nothing outside that
  folder is ever served, so the server's own permissions are the only ones
  that matter. Making one is an admin's call: it puts files on the server.
- A **machine share** is a directory on one of the owner's machines, served
  by the agent running there. Anyone may make one — it is their own disk —
  and it is there for their other machines exactly as long as that agent is
  running. The server only keeps the record: which machine, which path.

Shares are yours, like notes: one set per account, and the WebDAV side only
ever shows an account its own.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from cloudmorrow.server.db import connect
from cloudmorrow.slugs import SLUG_RE, InvalidSlugError

__all__ = [
    "DRIVE",
    "DRIVE_NAME",
    "KINDS",
    "MACHINE",
    "SERVER",
    "InvalidSlugError",
    "Share",
    "ShareExistsError",
    "ShareKindError",
    "SharePathError",
    "ShareStore",
    "UnknownShareError",
    "validate_share_name",
]

log = logging.getLogger(__name__)

SERVER = "server"
MACHINE = "machine"
# The kinds a share can be made as. A user's own drive on the server is
# served beside them (`cloudmorrow.server.drive`) but is not made or forgotten
# — it is there because the account is — so it is a kind, not one of these.
KINDS = (SERVER, MACHINE)
DRIVE = "drive"
# The drive's name in a URL and a mount: `/dav/my-files/`. No share may take
# it, or the drive would be unreachable.
DRIVE_NAME = "my-files"


class ShareExistsError(ValueError):
    pass


class UnknownShareError(LookupError):
    pass


class SharePathError(ValueError):
    """The path given for a share cannot be used — or should not have been given."""


class ShareKindError(ValueError):
    """Not one of the kinds a share can be."""


def validate_share_name(name: str) -> str:
    """A share's name is a slug: it has to survive as a URL segment and a volume name.

    The shape of a project id, but not its reserved words — `projects` is a
    fine thing to call a share, and there is no command it could be taken for.
    """
    name = name.strip().lower()
    if not SLUG_RE.match(name):
        raise InvalidSlugError(
            "share name must be 1-64 chars of lowercase letters, digits or '-', "
            "starting with a letter or digit"
        )
    if name == DRIVE_NAME:
        raise InvalidSlugError(f"{DRIVE_NAME} is your own drive on the server, not a share name")
    return name


def validate_kind(kind: str) -> str:
    kind = (kind or SERVER).strip().lower()
    if kind not in KINDS:
        raise ShareKindError(f"kind must be one of {', '.join(KINDS)}")
    return kind


@dataclass(slots=True)
class Share:
    id: int
    owner: str
    name: str
    path: Path
    managed: bool
    description: str
    created_at: str
    updated_at: str
    kind: str = SERVER
    # The agent that serves a machine share. None for a server share.
    agent_id: int | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "path": str(self.path),
            "managed": self.managed,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _share(row: sqlite3.Row) -> Share:
    return Share(
        id=row["id"],
        owner=row["owner"],
        name=row["name"],
        path=Path(row["path"]),
        managed=bool(row["managed"]),
        description=row["description"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        kind=row["kind"] or SERVER,
        agent_id=row["agent_id"],
    )


def _stamp() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


class ShareStore:
    """The shares table, and the Shares folder behind the server shares.

    *managed_root* says where the Shares folder is, given an owner; it is
    the config's `shares_root`, handed in so this knows nothing about config
    files. There is one folder for everyone now, but the owner is still
    passed so an older layout can be found and moved (`relocate`).
    """

    def __init__(self, db_path: Path, managed_root) -> None:
        self.db_path = db_path
        self._managed_root = managed_root
        connect(self.db_path).close()

    # -- reading -----------------------------------------------------------
    def shares(self, owner: str, *, kind: str | None = None) -> list[Share]:
        query = "SELECT * FROM shares WHERE owner = ?"
        params: list[object] = [owner]
        if kind is not None:
            query += " AND kind = ?"
            params.append(kind)
        with connect(self.db_path) as conn:
            rows = conn.execute(query + " ORDER BY name", params).fetchall()
        return [_share(row) for row in rows]

    def on_agent(self, agent_id: int) -> list[Share]:
        """The machine shares one agent serves — what its heartbeat carries back."""
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM shares WHERE agent_id = ? AND kind = ? ORDER BY name",
                (agent_id, MACHINE),
            ).fetchall()
        return [_share(row) for row in rows]

    def get(self, owner: str, name: str) -> Share | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM shares WHERE owner = ? AND name = ?",
                (owner, (name or "").strip().lower()),
            ).fetchone()
        return _share(row) if row else None

    def require(self, owner: str, name: str) -> Share:
        share = self.get(owner, name)
        if share is None:
            raise UnknownShareError(name)
        return share

    def shares_dir(self, owner: str = "") -> Path:
        """The Shares folder on the server, made if it is not there."""
        root = Path(self._managed_root(owner))
        root.mkdir(parents=True, exist_ok=True)
        return root

    def relocate(self) -> list[Share]:
        """Bring server shares made under an older layout into the Shares folder.

        A share's folder used to be `<owner's tree>/shares/<name>`. One found
        there — or anywhere but the Shares folder — is moved in, as long as
        the name is free there; if it is not, the share is left where it is
        and served from there, and the log says so. Run at startup; returns
        the shares that moved.
        """
        moved: list[Share] = []
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM shares WHERE kind = ? AND managed = 1", (SERVER,)
            ).fetchall()
        for share in (_share(row) for row in rows):
            root = self.shares_dir(share.owner)
            if share.path.parent == root or not share.path.is_dir():
                continue
            target = root / share.path.name
            if target.exists():
                log.warning(
                    "share %s stays at %s: %s is already taken", share.name, share.path, target
                )
                continue
            shutil.move(str(share.path), str(target))
            with connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE shares SET path = ?, updated_at = ? WHERE id = ?",
                    (str(target), _stamp(), share.id),
                )
            log.info("share %s moved to %s", share.name, target)
            moved.append(self.require(share.owner, share.name))
        return moved

    def folders(self, owner: str) -> tuple[Path, list[str]]:
        """The Shares directory, and the folders in it that are not shares yet.

        What an admin copied in and has not made a share of; the dialog
        offers them by name, so the share is made from the folder rather
        than beside it.
        """
        root = self.shares_dir(owner)
        taken = {share.path.resolve() for share in self.shares(owner, kind=SERVER)}
        try:
            children = sorted(root.iterdir(), key=lambda child: child.name.lower())
        except OSError:
            children = []
        return root, [
            child.name
            for child in children
            if child.is_dir() and not child.name.startswith(".") and child.resolve() not in taken
        ]

    def _folder_for(self, owner: str, name: str) -> Path:
        """`<Shares>/<name>` — or the folder already there that is *name* in
        some other case, since "Pictures" is what one calls the folder and
        `pictures` is what a share can be called."""
        root = self.shares_dir(owner)
        exact = root / name
        if exact.is_dir():
            return exact
        try:
            children = sorted(root.iterdir())
        except OSError:
            children = []
        for child in children:
            if child.is_dir() and child.name.lower() == name:
                return child
        return exact

    # -- writing -----------------------------------------------------------
    def create(
        self,
        owner: str,
        name: str,
        *,
        kind: str = SERVER,
        path: Path | str | None = None,
        agent_id: int | None = None,
        description: str = "",
    ) -> Share:
        """A new share.

        A server share is the folder of that name in the owner's Shares
        directory: made if it is not there, used as it is if it is. It takes
        no *path*. A machine share needs the *agent_id* that will serve it
        and the *path* on that machine — which is not checked here, since it
        is not here.
        """
        name = validate_share_name(name)
        kind = validate_kind(kind)
        if kind == MACHINE:
            if agent_id is None:
                raise SharePathError("a machine share needs the machine that serves it")
            root = Path(str(path or "").strip())
            if not root.is_absolute():
                raise SharePathError("the path must be absolute — as it is on that machine")
            managed = False
        else:
            if path is not None and str(path).strip():
                raise SharePathError(
                    "a server share is the folder of that name in your Shares directory "
                    "on the server — there is no path to give"
                )
            # The folder first, and the row only once it is there and usable:
            # a share of a folder the server cannot write is a share nobody
            # can put anything in, and a row with no folder is worse.
            root = self._usable_folder(owner, name)
            managed = True
            agent_id = None
        now = _stamp()
        try:
            with connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO shares (owner, name, kind, path, managed, agent_id,"
                    " description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        owner,
                        name,
                        kind,
                        str(root),
                        int(managed),
                        agent_id,
                        description.strip(),
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ShareExistsError(name) from exc
        return self.require(owner, name)

    def _usable_folder(self, owner: str, name: str) -> Path:
        """The share's folder in Shares, made if missing, and checked: the
        server has to be able to read it, list it and write to it."""
        try:
            root = self._folder_for(owner, name)
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SharePathError(
                f"the server cannot make the folder for {name} in its Shares folder: "
                f"{exc.strerror or exc}"
            ) from exc
        if not os.access(root, os.R_OK | os.W_OK | os.X_OK):
            raise SharePathError(
                f"the server cannot read and write {root} — give its service user "
                f"access to that folder, then share it"
            )
        return root

    def delete(self, owner: str, name: str, *, remove_files: bool = False) -> Share:
        """Forget a share. Its folder goes too only if asked.

        Returns the share that went, so the caller can say what happened to
        the directory. A machine share's files are on the machine; nothing
        here can or does touch them.
        """
        share = self.require(owner, name)
        with connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM shares WHERE owner = ? AND name = ?", (owner, share.name)
            )
        if remove_files and share.managed and share.path.is_dir():
            shutil.rmtree(share.path)
        return share

    def forget_agent(self, agent_id: int) -> int:
        """The machine is gone; so are the shares it served. Returns how many."""
        with connect(self.db_path) as conn:
            return int(
                conn.execute(
                    "DELETE FROM shares WHERE agent_id = ? AND kind = ?", (agent_id, MACHINE)
                ).rowcount
            )
