"""Fileshares: a folder on the server with a name, and the people it is shared with.

A share is served over WebDAV at `/dav/<name>/`, and the name is what you
mount. Its name is the server's, not the account's: there is one share
called `media`, whoever made it, because its folder and its address are
one each too.

**Where it is.** A share is the folder of its name in the Shares folder —
`<notes_dir>/Shares/<name>`, or under `shares_dir` — made when the share
is, or, when one is already there (an admin rsync'd a library in, say),
used as it is. That is the only place anybody's share can be, so the
server's own permissions are the only ones that matter. An administrator
may point a share at another directory on the server instead, by giving
its path. That path is checked when it is given: it has to be a directory,
it may not hold the server's own data, and what is wrong with the
permissions on it is said, so the admin hears about it then rather than
from somebody's empty mount later (`check_path`).

**Who has it.** Anybody may make a share, and whoever made it is its
owner: they see it, write in it, decide who else does, and remove it. They
share it with people by name, and with circles, so the next person in the
circle has it the day they join. An administrator may also share with
everybody on the server. Each of those is a *member* of the share, with
`write` or `read`. Your access to a share is the most any member that
names you gives — yourself, a circle you are in, or everybody — the way
your access to a datamodel is the most your circles give
(`cloudmorrow.server.circles`). There is no deny.

Being an administrator opens nobody's share: an admin has the shares they
made and the ones shared with them, like everybody else.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import shutil
import stat
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from cloudmorrow.server.database import Connection, Database, IntegrityError, Row
from cloudmorrow.server.database import open as open_database
from cloudmorrow.server.slugs import SLUG_RE, InvalidSlugError

__all__ = [
    "CIRCLE",
    "DRIVE",
    "DRIVE_NAME",
    "EVERYONE",
    "MEMBER_KINDS",
    "PERSON",
    "READ",
    "SERVER",
    "WRITE",
    "InvalidSlugError",
    "Member",
    "PathCheck",
    "Protected",
    "Share",
    "ShareError",
    "ShareExistsError",
    "SharePathError",
    "ShareRefused",
    "ShareStore",
    "UnknownShareError",
    "check_path",
    "validate_share_name",
]

log = logging.getLogger(__name__)

# A share on the server: the only kind there is to make. A user's own drive
# on the server is served beside them (`cloudmorrow.server.drive`) but is not
# made or forgotten — it is there because the account is — so it is a kind,
# not something made here.
SERVER = "server"
DRIVE = "drive"
# The drive's name in a URL and a mount: `/dav/my-files/`. No share may take
# it, or the drive would be unreachable.
DRIVE_NAME = "my-files"
# Names `/api/shares/<name>` would read as something else.
RESERVED = frozenset({"folders", "candidates", "check"})

# Who a share is shared with.
PERSON = "user"
CIRCLE = "circle"
EVERYONE = "everyone"
MEMBER_KINDS = (PERSON, CIRCLE, EVERYONE)
# What they may do in it.
WRITE = "write"
READ = "read"
ACCESS = (WRITE, READ)
_RANK = {None: 0, READ: 1, WRITE: 2}

# How many entries at the top of a directory an admin points a share at are
# looked at for files the server cannot read. Enough to notice a tree copied
# in as another user; not a walk of a whole library.
SAMPLE = 200

TABLE = """
CREATE TABLE IF NOT EXISTS share_members (
    share_id  INTEGER NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
    -- 'user' (who is a username), 'circle' (a circle's id) or 'everyone' ('*').
    kind      TEXT    NOT NULL,
    who       TEXT    NOT NULL,
    -- 'write' or 'read'.
    access    TEXT    NOT NULL DEFAULT 'write',
    added_by  TEXT    NOT NULL DEFAULT '',
    added_at  TEXT    NOT NULL,
    PRIMARY KEY (share_id, kind, who)
);
CREATE INDEX IF NOT EXISTS share_members_who ON share_members (kind, who);
"""


class ShareError(ValueError):
    """Something about a share that cannot be done as asked."""


class ShareExistsError(ShareError):
    pass


class UnknownShareError(LookupError):
    pass


class SharePathError(ShareError):
    """The path given for a share cannot be used — or should not have been given."""


class ShareRefused(PermissionError):
    """Allowed to somebody, but not to whoever asked."""


def validate_share_name(name: str) -> str:
    """A share's name is a slug: it has to survive as a URL segment and a volume name.

    The shape of a project id, but not its reserved words — `projects` is a
    fine thing to call a share, and there is no command it could be taken for.
    """
    name = (name or "").strip().lower()
    if not SLUG_RE.match(name):
        raise InvalidSlugError(
            "share name must be 1-64 chars of lowercase letters, digits or '-', starting with a letter or digit"
        )
    if name == DRIVE_NAME:
        raise InvalidSlugError(f"{DRIVE_NAME} is your own drive on the server, not a share name")
    if name in RESERVED:
        raise InvalidSlugError(f"{name} is a word the server keeps for itself; call the share something else")
    return name


def validate_access(access: str | None) -> str:
    access = (access or WRITE).strip().lower()
    if access not in ACCESS:
        raise ShareError(f"access must be {' or '.join(ACCESS)}")
    return access


@dataclass(frozen=True, slots=True)
class Member:
    """One line of who a share is shared with."""

    kind: str
    who: str
    access: str = WRITE
    # What to call them: a person's display name, a circle's name, "Everybody".
    label: str = ""
    added_by: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "who": self.who,
            "access": self.access,
            "label": self.label or self.who,
            "added_by": self.added_by,
        }


@dataclass(slots=True)
class Share:
    id: int
    owner: str
    name: str
    path: Path
    # True when the folder is the share's own in the Shares folder, and so
    # may go with the share. False for a directory an admin pointed it at,
    # which is never deleted from here.
    managed: bool
    description: str
    created_at: str
    updated_at: str
    kind: str = SERVER
    members: tuple[Member, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "owner": self.owner,
            "path": str(self.path),
            "managed": self.managed,
            "description": self.description,
            "members": [m.to_dict() for m in self.members],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class Protected:
    """A place on the server no share may reach: what is in it, and why not."""

    path: Path
    why: str


@dataclass(slots=True)
class PathCheck:
    """What `check_path` found: reasons it cannot be shared, and things to fix."""

    path: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _stamp() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


def _service_user() -> str:
    try:
        import pwd

        return pwd.getpwuid(os.geteuid()).pw_name
    except (ImportError, KeyError, OSError):
        return "the server's service user"


def _within(child: Path, parent: Path) -> bool:
    return child == parent or parent in child.parents


def _read_only_mount(path: Path) -> bool:
    try:
        return bool(os.statvfs(path).f_flag & os.ST_RDONLY)
    except (AttributeError, OSError):
        return False


def permission_warnings(path: Path) -> list[str]:
    """What is wrong with the permissions on a share's directory, as the
    server runs: each a sentence with the fix in it. Empty when it is fine."""
    user = _service_user()
    if not os.access(path, os.R_OK | os.X_OK):
        return [
            f"The server cannot open the folder: nothing in it can be seen until {user} may read it "
            f"(give {user}, or a group it is in, read and execute on it)."
        ]
    found: list[str] = []
    if _read_only_mount(path):
        # The service's sandbox: ProtectSystem=strict makes everything but
        # its ReadWritePaths read-only, whatever the permissions say.
        found.append(
            "The server sees the folder's filesystem as read-only, so the share works as read-only. "
            "If the server runs under systemd, add the folder to ReadWritePaths for the service "
            "(`sudo systemctl edit cloudmorrow`), then restart it."
        )
    elif not os.access(path, os.W_OK):
        found.append(
            "The server can read the folder but not write to it, so nothing can be put there or changed: "
            f"it works as read-only until {user} may write to it."
        )
    try:
        mode = path.stat().st_mode
    except OSError:
        mode = 0
    if mode & stat.S_IWOTH and not mode & stat.S_ISVTX:
        found.append("The folder is world-writable: anybody with an account on this machine can change what is in it.")
    unreadable = unwritable = 0
    try:
        with os.scandir(path) as entries:
            for i, entry in enumerate(entries):
                if i >= SAMPLE:
                    break
                if entry.name.startswith("."):
                    continue
                target = os.path.join(path, entry.name)
                is_dir = entry.is_dir(follow_symlinks=False)
                wanted = os.R_OK | (os.X_OK if is_dir else 0)
                if not os.access(target, wanted):
                    unreadable += 1
                elif not os.access(target, os.W_OK):
                    unwritable += 1
    except OSError:
        pass
    if unreadable:
        found.append(
            f"{unreadable} {'item' if unreadable == 1 else 'items'} at the top of the folder cannot be read by "
            f"{user}, so nobody will see {'it' if unreadable == 1 else 'them'} on a mount."
        )
    if unwritable and os.access(path, os.W_OK):
        found.append(
            f"{unwritable} {'item' if unwritable == 1 else 'items'} at the top of the folder cannot be changed by "
            f"{user}: they can be opened on a mount, not saved over."
        )
    return found


def check_path(
    raw: str | Path,
    *,
    protected: Iterable[Protected] = (),
    shares_root: Path | None = None,
    others: Iterable[Share] = (),
) -> PathCheck:
    """Whether a directory on the server can be a share, and what to fix.

    An *error* is a reason not to make it at all: not absolute, not there,
    not a directory, or holding — or inside — something of the server's own.
    A *warning* is a share that would work worse than its maker expects:
    permissions the server cannot use, a world-writable folder, files the
    server cannot read, or a folder another share already covers.
    """
    text = str(raw or "").strip()
    given = Path(text).expanduser() if text else Path()
    check = PathCheck(path=given)
    if not text or not given.is_absolute():
        check.errors.append("the path must be absolute: a directory on the server, as the server sees it")
        return check
    path = Path(os.path.realpath(given))
    check.path = path
    if not path.exists():
        hidden = path.parts[1:2] in (("home",), ("root",))
        why = " — or the service may not look there: under systemd, ProtectHome hides /home and /root"
        check.errors.append(f"{path} is not there on the server" + (why if hidden else ""))
        return check
    if not path.is_dir():
        check.errors.append(f"{path} is a file, not a directory")
        return check
    in_shares = shares_root is not None and _within(path, Path(os.path.realpath(shares_root)))
    # The first reason is enough: the data directory holds the key too.
    for place in protected:
        guarded = Path(os.path.realpath(place.path))
        if _within(guarded, path):
            check.errors.append(f"{path} holds {place.why} ({guarded}), and that is never shared")
            return check
        if _within(path, guarded) and not in_shares:
            check.errors.append(f"{path} is inside {place.why} ({guarded}), and that is never shared")
            return check
    check.warnings.extend(permission_warnings(path))
    for other in others:
        theirs = Path(os.path.realpath(other.path))
        if theirs == path:
            check.warnings.append(f"The share {other.name} is this same folder: whoever has it sees the same files.")
        elif _within(path, theirs):
            check.warnings.append(f"The folder is inside the share {other.name}: whoever has that sees it too.")
        elif _within(theirs, path):
            check.warnings.append(f"The share {other.name} is inside the folder, so its files are in this one too.")
    return check


def _share(row: Row, members: tuple[Member, ...] = ()) -> Share:
    return Share(
        id=row["id"],
        owner=row["owner"],
        name=row["name"],
        path=Path(row["path"]),
        managed=bool(row["managed"]),
        description=row["description"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        kind=SERVER,
        members=members,
    )


class ShareStore:
    """The shares table, who each share is shared with, and the Shares folder.

    *managed_root* says where the Shares folder is, given an owner; it is
    the config's `shares_root`, handed in so this knows nothing about config
    files. There is one folder for everyone, but the owner is still passed
    so an older layout can be found and moved (`relocate`). *protected* is
    what no share may hold or be inside: the server's data, its key, the
    people's own files.
    """

    def __init__(
        self,
        db: Database | Path,
        managed_root,
        *,
        protected: Callable[[], Iterable[Protected]] = lambda: (),
    ) -> None:
        self.db = open_database(db)
        self._managed_root = managed_root
        self._protected = protected
        self.db.connect().close()

    # -- reading -----------------------------------------------------------
    def _members(self, conn: Connection, ids: list[int]) -> dict[int, list[Member]]:
        if not ids:
            return {}
        marks = ", ".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT m.*, u.display_name AS person, c.name AS circle FROM share_members m"
            f" LEFT JOIN users u ON m.kind = '{PERSON}' AND u.username = m.who"
            f" LEFT JOIN circles c ON m.kind = '{CIRCLE}' AND c.id = m.who"
            f" WHERE m.share_id IN ({marks}) ORDER BY m.added_at, m.kind, m.who",
            ids,
        ).fetchall()
        found: dict[int, list[Member]] = {}
        for row in rows:
            if row["kind"] == EVERYONE:
                label = "Everybody"
            elif row["kind"] == CIRCLE:
                label = row["circle"] or row["who"]
            else:
                label = row["person"] or row["who"]
            found.setdefault(row["share_id"], []).append(
                Member(row["kind"], row["who"], row["access"], label, row["added_by"])
            )
        return found

    def _load(self, conn: Connection, rows: list[Row]) -> list[Share]:
        members = self._members(conn, [row["id"] for row in rows])
        return [_share(row, tuple(members.get(row["id"], ()))) for row in rows]

    def all(self) -> list[Share]:
        """Every share on the server, whoever has it."""
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM shares ORDER BY name").fetchall()
            return self._load(conn, rows)

    def owned_by(self, owner: str) -> list[Share]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM shares WHERE owner = ? ORDER BY name", (owner,)).fetchall()
            return self._load(conn, rows)

    def visible(self, username: str) -> list[Share]:
        """The shares *username* has: theirs, and every one shared with them —
        by name, through a circle they are in, or with everybody."""
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM shares s WHERE s.owner = ? OR EXISTS ("
                " SELECT 1 FROM share_members m WHERE m.share_id = s.id AND ("
                f"  m.kind = '{EVERYONE}'"
                f"  OR (m.kind = '{PERSON}' AND m.who = ?)"
                f"  OR (m.kind = '{CIRCLE}' AND m.who IN"
                "      (SELECT circle_id FROM circle_members WHERE username = ?))))"
                " ORDER BY s.name",
                (username, username, username),
            ).fetchall()
            return self._load(conn, rows)

    def get(self, name: str) -> Share | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM shares WHERE name = ?", ((name or "").strip().lower(),)).fetchone()
            return self._load(conn, [row])[0] if row else None

    def require(self, name: str) -> Share:
        share = self.get(name)
        if share is None:
            raise UnknownShareError(name)
        return share

    def circles_of(self, username: str) -> set[str]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT circle_id FROM circle_members WHERE username = ?", (username,)).fetchall()
        return {row["circle_id"] for row in rows}

    def access_of(self, share: Share, username: str, *, circles: set[str] | None = None) -> str | None:
        """`write`, `read`, or None: what *username* may do in *share*."""
        if not username:
            return None
        if share.owner == username:
            return WRITE
        circles = self.circles_of(username) if circles is None else circles
        best: str | None = None
        for member in share.members:
            if (
                member.kind == EVERYONE
                or (member.kind == PERSON and member.who == username)
                or (member.kind == CIRCLE and member.who in circles)
            ) and _RANK[member.access] > _RANK[best]:
                best = member.access
        return best

    def for_user(self, username: str, name: str) -> Share | None:
        """The share called *name*, if *username* has it; None if not, or
        if there is none — the same answer, so a name is not a way to find
        out about somebody else's share."""
        share = self.get(name)
        if share is None or self.access_of(share, username) is None:
            return None
        return share

    @staticmethod
    def may_manage(share: Share, username: str) -> bool:
        """Who decides about a share — who has it, where it is, whether it
        stays — is whoever made it."""
        return share.owner == username

    def shares_dir(self, owner: str = "") -> Path:
        """The Shares folder on the server, made if it is not there."""
        root = Path(self._managed_root(owner))
        root.mkdir(parents=True, exist_ok=True)
        return root

    def default_path(self, name: str) -> Path:
        """Where a share of this name is when nobody says otherwise."""
        return self._folder_for("", validate_share_name(name))

    def problems(self, share: Share) -> list[str]:
        """What is wrong with the share's directory now: gone, or permissions
        the server cannot use. Asked again every time, so a fix shows at once."""
        if not share.path.is_dir():
            return [f"The folder is not there on the server any more ({share.path})."]
        return permission_warnings(share.path)

    def check_path(self, raw: str | Path, *, exclude: str = "") -> PathCheck:
        """`check_path` with this server's protected places and its other shares."""
        return check_path(
            raw,
            protected=list(self._protected()),
            shares_root=Path(self._managed_root("")),
            others=[s for s in self.all() if s.name != exclude],
        )

    def relocate(self) -> list[Share]:
        """Bring shares made under an older layout into the Shares folder.

        A share's folder used to be `<owner's tree>/shares/<name>`. One found
        there — or anywhere but the Shares folder — is moved in, as long as
        the name is free there; if it is not, the share is left where it is
        and served from there, and the log says so. Run at startup; returns
        the shares that moved.
        """
        moved: list[Share] = []
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM shares WHERE managed = 1").fetchall()
        for share in (_share(row) for row in rows):
            root = self.shares_dir(share.owner)
            if share.path.parent == root or not share.path.is_dir():
                continue
            target = root / share.path.name
            if target.exists():
                log.warning("share %s stays at %s: %s is already taken", share.name, share.path, target)
                continue
            shutil.move(str(share.path), str(target))
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE shares SET path = ?, updated_at = ? WHERE id = ?",
                    (str(target), _stamp(), share.id),
                )
            log.info("share %s moved to %s", share.name, target)
            moved.append(self.require(share.name))
        return moved

    def folders(self) -> tuple[Path, list[str]]:
        """The Shares directory, and the folders in it that are not shares yet.

        What an admin copied in and has not made a share of; the dialog
        offers them by name, so the share is made from the folder rather
        than beside it.
        """
        root = self.shares_dir()
        taken = {share.path.resolve() for share in self.all()}
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
    def _where(self, name: str, path: Path | str | None, *, admin: bool, exclude: str = "") -> tuple[Path, bool, list]:
        """The directory a share is, whether it is its own, and what to fix there."""
        text = str(path or "").strip()
        if text and Path(os.path.realpath(Path(text).expanduser())) == Path(
            os.path.realpath(self._folder_for("", name))
        ):
            # The default, spelled out: the share's own folder.
            text = ""
        if not text:
            return self._usable_folder(name), True, []
        if not admin:
            raise ShareRefused(
                "a share is the folder of its name in the Shares folder on the server; "
                "only an administrator may point one at another directory"
            )
        check = self.check_path(text, exclude=exclude)
        if not check.ok:
            raise SharePathError("; ".join(check.errors))
        return check.path, False, check.warnings

    def create(
        self,
        owner: str,
        name: str,
        *,
        admin: bool = False,
        path: Path | str | None = None,
        description: str = "",
        members: Iterable[tuple[str, str, str]] = (),
    ) -> tuple[Share, list[str]]:
        """A new share, and what is worth fixing about its directory.

        It is the folder of that name in the Shares folder — made if it is
        not there, used as it is if it is — unless an admin gives a *path*.
        *members* are (kind, who, access), as `add_member` takes them, and
        each is checked before anything is made.
        """
        name = validate_share_name(name)
        if self.get(name) is not None:
            raise ShareExistsError(name)
        wanted = [self._member(owner, kind, who, access, admin=admin) for kind, who, access in members]
        root, managed, warnings = self._where(name, path, admin=admin)
        now = _stamp()
        try:
            with self.db.connect() as conn:
                conn.execute(
                    "INSERT INTO shares (owner, name, kind, path, managed, agent_id,"
                    " description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (owner, name, SERVER, str(root), int(managed), None, description.strip(), now, now),
                )
                share_id = conn.execute("SELECT id FROM shares WHERE name = ?", (name,)).fetchone()["id"]
                for kind, who, access in wanted:
                    self._put_member(conn, share_id, kind, who, access, owner)
        except IntegrityError as exc:
            raise ShareExistsError(name) from exc
        return self.require(name), warnings

    def _usable_folder(self, name: str) -> Path:
        """The share's folder in Shares, made if missing, and checked: the
        server has to be able to read it, list it and write to it."""
        try:
            root = self._folder_for("", name)
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SharePathError(
                f"the server cannot make the folder for {name} in its Shares folder: {exc.strerror or exc}"
            ) from exc
        if not os.access(root, os.R_OK | os.W_OK | os.X_OK):
            raise SharePathError(
                f"the server cannot read and write {root} — give its service user access to that folder, then share it"
            )
        return root

    def update(
        self,
        share: Share,
        *,
        admin: bool = False,
        path: Path | str | None = None,
        description: str | None = None,
    ) -> tuple[Share, list[str]]:
        """Change where a share is, or what it says about itself.

        A *path* is an admin's to give, checked as at creation; an empty one
        puts the share back in its own folder in Shares. The directory it
        was in is left as it is.
        """
        updates: dict[str, object] = {}
        warnings: list[str] = []
        if path is not None:
            root, managed, warnings = self._where(share.name, path, admin=admin, exclude=share.name)
            updates["path"] = str(root)
            updates["managed"] = int(managed)
        if description is not None:
            updates["description"] = description.strip()
        if updates:
            updates["updated_at"] = _stamp()
            assignments = ", ".join(f"{column} = ?" for column in updates)
            with self.db.connect() as conn:
                conn.execute(f"UPDATE shares SET {assignments} WHERE id = ?", (*updates.values(), share.id))
        return self.require(share.name), warnings

    def _member(self, owner: str, kind: str, who: str, access: str | None, *, admin: bool) -> tuple[str, str, str]:
        """A member checked: a person or a circle that is there, or everybody
        — which is an admin's to give, since it is everybody on the server."""
        kind = (kind or "").strip().lower()
        who = (who or "").strip()
        access = validate_access(access)
        if kind == EVERYONE:
            if not admin:
                raise ShareRefused("only an administrator may share with everybody on the server")
            return EVERYONE, "*", access
        with self.db.connect() as conn:
            if kind == PERSON:
                row = conn.execute(
                    "SELECT username FROM users WHERE lower(username) = lower(?) AND is_active = 1", (who,)
                ).fetchone()
                if row is None:
                    raise ShareError(f"there is nobody called {who} on this server")
                if row["username"] == owner:
                    raise ShareError("a share is always its owner's; there is no need to add yourself")
                return PERSON, row["username"], access
            if kind == CIRCLE:
                row = conn.execute(
                    "SELECT id FROM circles WHERE id = ? OR lower(name) = lower(?)", (who.lower(), who)
                ).fetchone()
                if row is None:
                    raise ShareError(f"there is no circle called {who}")
                return CIRCLE, row["id"], access
        raise ShareError(f"a share is shared with {', '.join(MEMBER_KINDS)}")

    @staticmethod
    def _put_member(conn: Connection, share_id: int, kind: str, who: str, access: str, by: str) -> None:
        conn.execute(
            "INSERT INTO share_members (share_id, kind, who, access, added_by, added_at) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (share_id, kind, who) DO UPDATE SET access = excluded.access",
            (share_id, kind, who, access, by, _stamp()),
        )

    def add_member(
        self, share: Share, kind: str, who: str, access: str | None = WRITE, *, by: str, admin: bool = False
    ) -> Share:
        """Share it with a person, a circle or everybody — or change what one may do."""
        kind, who, access = self._member(share.owner, kind, who, access, admin=admin)
        with self.db.connect() as conn:
            self._put_member(conn, share.id, kind, who, access, by)
            conn.execute("UPDATE shares SET updated_at = ? WHERE id = ?", (_stamp(), share.id))
        return self.require(share.name)

    def remove_member(self, share: Share, kind: str, who: str) -> Share:
        kind = (kind or "").strip().lower()
        who = "*" if kind == EVERYONE else (who or "").strip()
        if kind == CIRCLE:
            who = who.lower()
        match = next((m for m in share.members if m.kind == kind and m.who.lower() == who.lower()), None)
        if match is None:
            raise UnknownShareError(f"{share.name} is not shared with that {kind}")
        with self.db.connect() as conn:
            conn.execute(
                "DELETE FROM share_members WHERE share_id = ? AND kind = ? AND who = ?",
                (share.id, match.kind, match.who),
            )
            conn.execute("UPDATE shares SET updated_at = ? WHERE id = ?", (_stamp(), share.id))
        return self.require(share.name)

    def delete(self, name: str, *, remove_files: bool = False) -> Share:
        """Forget a share. Its folder goes too only if asked, and only when
        it is the share's own in Shares: a directory an admin pointed a share
        at is never deleted from here. Returns the share that went."""
        share = self.require(name)
        with self.db.connect() as conn:
            conn.execute("DELETE FROM share_members WHERE share_id = ?", (share.id,))
            conn.execute("DELETE FROM shares WHERE id = ?", (share.id,))
        if remove_files and share.managed and share.path.is_dir():
            shutil.rmtree(share.path)
        return share

    def forget_user(self, username: str, heir: str) -> list[Share]:
        """An account is gone. What it was given goes with it; what it made
        passes to *heir* — the administrator who removed it — with its files
        and its members as they were, so nothing on the server is left with
        nobody to decide about it. Returns the shares that changed hands."""
        handed = self.owned_by(username)
        with self.db.connect() as conn:
            conn.execute("DELETE FROM share_members WHERE kind = ? AND who = ?", (PERSON, username))
            conn.execute("UPDATE shares SET owner = ?, updated_at = ? WHERE owner = ?", (heir, _stamp(), username))
            # The heir has them now; a line naming the heir says nothing more.
            conn.execute(
                "DELETE FROM share_members WHERE kind = ? AND who = ? AND share_id IN"
                " (SELECT id FROM shares WHERE owner = ?)",
                (PERSON, heir, heir),
            )
        return [self.require(share.name) for share in handed]

    def forget_circle(self, circle_id: str) -> int:
        """A circle is gone; so is every share's line for it. Returns how many."""
        with self.db.connect() as conn:
            return int(
                conn.execute("DELETE FROM share_members WHERE kind = ? AND who = ?", (CIRCLE, circle_id)).rowcount
            )
