"""Channels, direct messages, and who has read what.

Chat is the first thing in Cloudmorrow that is not one person's. Notes, tasks
and secrets all hang off an `owner` column and never leave it; a message is
the opposite — it exists so somebody else reads it. So the tables here are
keyed by channel and membership rather than by owner, and every read takes
the username asking so it can be checked rather than assumed.

There are three kinds of channel, and the kind is the whole of the access
rule:

* **public** — everybody is in it. It is in everyone's list, anyone may post,
  and nobody can leave, because leaving a room everyone is in is a mute and
  a mute is not this.
* **private** — the people in it. Made by anyone, joined by being added;
  there is no invitation to accept, because an invitation you have to accept
  is a second thing to build and a second thing to forget. You are added, you
  are told, and you can leave.
* **direct** — two people, forever those two. It is not made from a form: ask
  for the channel with somebody and it is there, whether or not it existed a
  moment ago. It cannot be renamed, added to or left.

Unread is a high-water mark, not a flag per message: each membership row
remembers the id of the last message that member has read, and unread is
everything after it. That is one small integer per person per channel instead
of a row per person per message, and it survives a client reading the same
channel from a phone and a terminal at once — the mark only ever moves up.

Being added to a channel leaves a notification; a message does not. Messages
have their own count, which is what the badge on the phone's icon shows, and
running both through the notification list would show every line of chat
twice and count it twice. The one exception is the push itself, which is sent
from the routes rather than from here: this module stores, and nothing here
reaches out.
"""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from cloudmorrow.server.db import Connection, connect

__all__ = [
    "ChannelExistsError",
    "ChatStore",
    "DIRECT",
    "InvalidChannelError",
    "KINDS",
    "MAX_BODY_CHARS",
    "NotAMemberError",
    "PRIVATE",
    "PUBLIC",
    "UnknownChannelError",
    "direct_slug",
]

PUBLIC = "public"
PRIVATE = "private"
DIRECT = "direct"
# The kinds a person may ask for. A direct channel is never created by name.
KINDS: tuple[str, ...] = (PUBLIC, PRIVATE)

# Long enough for a paragraph and a link, short enough that a message is a
# message. Anything longer wants to be a note.
MAX_BODY_CHARS = 4000
MAX_NAME_CHARS = 64
MAX_TOPIC_CHARS = 200

# A page of history. The client asks for more with ?before=.
PAGE = 50

# Usernames are already `[a-z_][a-z0-9_-]{0,31}`, and a direct channel's slug
# is built out of two of them, so '_' has to be legal here as well.
CHANNEL_SLUG_RE = re.compile(r"^[a-z0-9_][a-z0-9_-]{0,71}$")
# Words the API would read as something other than a channel.
RESERVED_SLUGS = {"new", "unread", "read", "direct", "with", "all", "none"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_channels (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    -- The channel's id everywhere: in the API, and in the address bar.
    slug       TEXT    NOT NULL UNIQUE,
    -- What it is called. Empty for a direct channel, which is called after
    -- whichever of its two people is not the one looking at it.
    name       TEXT    NOT NULL DEFAULT '',
    topic      TEXT    NOT NULL DEFAULT '',
    -- 'public', 'private' or 'direct'. See the module docstring: the kind is
    -- the access rule, there is nothing else to check.
    kind       TEXT    NOT NULL DEFAULT 'private',
    created_by TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_members (
    channel_id INTEGER NOT NULL REFERENCES chat_channels(id) ON DELETE CASCADE,
    username   TEXT    NOT NULL,
    added_by   TEXT    NOT NULL DEFAULT '',
    joined_at  TEXT    NOT NULL,
    -- The id of the last message this member has read. Everything after it
    -- is their unread. 0 means they have read nothing in here yet.
    last_read  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (channel_id, username)
);
CREATE INDEX IF NOT EXISTS chat_members_user ON chat_members (username);
CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL REFERENCES chat_channels(id) ON DELETE CASCADE,
    author     TEXT    NOT NULL,
    body       TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    edited_at  TEXT
);
CREATE INDEX IF NOT EXISTS chat_messages_channel ON chat_messages (channel_id, id);
"""


class InvalidChannelError(ValueError):
    pass


class ChannelExistsError(ValueError):
    pass


class UnknownChannelError(LookupError):
    pass


class NotAMemberError(PermissionError):
    """The channel exists; it is not this person's to read or write."""


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


def slugify_channel(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")[:72]
    return slug.rstrip("-")


def direct_slug(one: str, other: str) -> str:
    """The slug of the channel between two people, from either side.

    Sorted, so `bram` asking for `ada` and `ada` asking for `bram` name the
    same row and there is never a second thread with the same two people in
    it.
    """
    first, second = sorted((one.strip().lower(), other.strip().lower()))
    return f"dm-{first}-{second}"


@dataclass(slots=True)
class Channel:
    id: int
    slug: str
    name: str
    topic: str
    kind: str
    created_by: str
    created_at: str
    updated_at: str

    @property
    def direct(self) -> bool:
        return self.kind == DIRECT


def _channel(conn: Connection, row: sqlite3.Row) -> Channel:
    return Channel(
        id=row["id"],
        slug=row["slug"],
        name=row["name"],
        topic=conn.unseal("chat_channels", "topic", (row["slug"],), row["topic"]),
        kind=row["kind"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _message(conn: Connection, row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "author": row["author"],
        "body": conn.unseal("chat_messages", "body", (row["channel_id"],), row["body"]),
        "created_at": row["created_at"],
        "edited_at": row["edited_at"],
    }


class ChatStore:
    """The channels, the messages in them, and the marks people leave."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return connect(self.db_path)

    # -- the people ---------------------------------------------------------
    # Chat is the one feature that has to know who else there is, so it reads
    # the users table directly rather than being handed a store. Same
    # database, same connection; a second object would only be a longer way
    # of writing this query.

    @staticmethod
    def _everyone(conn: sqlite3.Connection) -> list[str]:
        """Who a public channel is for: the active people, agents aside.

        An agent is a program acting for somebody who is already in the list,
        and a screen on a wall does not read its messages.
        """
        rows = conn.execute(
            "SELECT username FROM users WHERE is_active = 1 AND user_type = 'human'"
            " ORDER BY username"
        ).fetchall()
        return [row["username"] for row in rows]

    def people(self, *, excluding: str = "") -> list[dict]:
        """Everyone you could start a direct channel with."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT username, display_name FROM users WHERE is_active = 1"
                " AND user_type = 'human' ORDER BY username"
            ).fetchall()
        return [
            {"username": row["username"], "display_name": row["display_name"]}
            for row in rows
            if row["username"] != excluding
        ]

    @staticmethod
    def _known(conn: sqlite3.Connection, username: str) -> bool:
        return (
            conn.execute(
                "SELECT 1 FROM users WHERE username = ? AND is_active = 1", (username,)
            ).fetchone()
            is not None
        )

    # -- finding a channel ---------------------------------------------------
    @staticmethod
    def _row(conn: sqlite3.Connection, slug: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM chat_channels WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            raise UnknownChannelError(slug)
        return row

    @staticmethod
    def _is_member(conn: sqlite3.Connection, channel_id: int, username: str) -> bool:
        return (
            conn.execute(
                "SELECT 1 FROM chat_members WHERE channel_id = ? AND username = ?",
                (channel_id, username),
            ).fetchone()
            is not None
        )

    @classmethod
    def _readable(cls, conn: sqlite3.Connection, row: sqlite3.Row, username: str) -> None:
        """Raise unless *username* may see this channel at all.

        Public is everybody's. Anything else is its members'. There is no
        third rule, and no rule that depends on who made it.
        """
        if row["kind"] == PUBLIC:
            return
        if not cls._is_member(conn, row["id"], username):
            raise NotAMemberError(row["slug"])

    @staticmethod
    def _members(conn: sqlite3.Connection, channel_id: int) -> list[str]:
        rows = conn.execute(
            "SELECT username FROM chat_members WHERE channel_id = ? ORDER BY username",
            (channel_id,),
        ).fetchall()
        return [row["username"] for row in rows]

    @staticmethod
    def _join(
        conn: sqlite3.Connection,
        channel_id: int,
        username: str,
        *,
        added_by: str = "",
        last_read: int = 0,
    ) -> bool:
        """Put somebody in a channel. False when they were already in it."""
        cursor = conn.execute(
            "INSERT OR IGNORE INTO chat_members (channel_id, username, added_by,"
            " joined_at, last_read) VALUES (?, ?, ?, ?, ?)",
            (channel_id, username, added_by, _now(), last_read),
        )
        return cursor.rowcount > 0

    @staticmethod
    def _tip(conn: sqlite3.Connection, channel_id: int) -> int:
        row = conn.execute(
            "SELECT MAX(id) AS tip FROM chat_messages WHERE channel_id = ?", (channel_id,)
        ).fetchone()
        return int(row["tip"] or 0)

    def _catch_up_public(self, conn: sqlite3.Connection, username: str) -> None:
        """Put *username* in every public channel they are not in yet.

        A public channel made before somebody had an account still has to be
        theirs, and the membership row is where their read mark lives. They
        join at the tip rather than at the beginning: an account created today
        should not open to a badge counting every message of the last year.
        """
        rows = conn.execute(
            "SELECT id FROM chat_channels WHERE kind = ? AND id NOT IN"
            " (SELECT channel_id FROM chat_members WHERE username = ?)",
            (PUBLIC, username),
        ).fetchall()
        for row in rows:
            self._join(conn, row["id"], username, last_read=self._tip(conn, row["id"]))

    # -- listing --------------------------------------------------------------
    def _summary(self, conn: sqlite3.Connection, row: sqlite3.Row, username: str) -> dict:
        members = self._members(conn, row["id"])
        last = conn.execute(
            "SELECT * FROM chat_messages WHERE channel_id = ? ORDER BY id DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        mark = conn.execute(
            "SELECT last_read FROM chat_members WHERE channel_id = ? AND username = ?",
            (row["id"], username),
        ).fetchone()
        last_read = int(mark["last_read"]) if mark else self._tip(conn, row["id"])
        unread = int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM chat_messages WHERE channel_id = ?"
                " AND id > ? AND author <> ?",
                (row["id"], last_read, username),
            ).fetchone()["n"]
        )
        channel = _channel(conn, row)
        return {
            "slug": channel.slug,
            "name": self.display_name(channel, members, username),
            "topic": channel.topic,
            "kind": channel.kind,
            "created_by": channel.created_by,
            "created_at": channel.created_at,
            "updated_at": channel.updated_at,
            "members": members,
            # Who the other person is, for a direct channel; empty otherwise.
            "other": self._other(channel, members, username),
            "member": mark is not None,
            "unread": unread,
            "last_read": last_read,
            "last_message": _message(conn, last) if last else None,
        }

    @staticmethod
    def _other(channel: Channel, members: list[str], username: str) -> str:
        if not channel.direct:
            return ""
        others = [name for name in members if name != username]
        # A direct channel with yourself is a legal thing to ask for, and its
        # other person is you.
        return others[0] if others else username

    def display_name(self, channel: Channel, members: list[str], username: str) -> str:
        """What this channel is called, to this person.

        Only a direct channel's name depends on who is asking, and it has to:
        the row has no name of its own, because the name is the other person.
        """
        if channel.direct:
            return self._other(channel, members, username)
        return channel.name or channel.slug

    def channels(self, username: str) -> list[dict]:
        """Every channel *username* can see, the ones with news first."""
        with self._connect() as conn:
            self._catch_up_public(conn, username)
            rows = conn.execute(
                "SELECT * FROM chat_channels WHERE kind = ? OR id IN"
                " (SELECT channel_id FROM chat_members WHERE username = ?)",
                (PUBLIC, username),
            ).fetchall()
            listed = [self._summary(conn, row, username) for row in rows]
        # Newest activity first, and a channel nobody has written in yet
        # sorts by when it was made — which is the same question.
        listed.sort(
            key=lambda c: (
                c["last_message"]["created_at"] if c["last_message"] else c["created_at"]
            ),
            reverse=True,
        )
        return listed

    def get(self, username: str, slug: str) -> dict:
        with self._connect() as conn:
            row = self._row(conn, slug.strip().lower())
            self._readable(conn, row, username)
            return self._summary(conn, row, username)

    # -- making one ------------------------------------------------------------
    def create(
        self,
        creator: str,
        *,
        name: str,
        kind: str = PRIVATE,
        topic: str = "",
        members: list[str] | None = None,
    ) -> dict:
        """Make a channel. Returns it as its creator sees it.

        A public channel is made for everybody, so everybody is put in it
        here; *members* only adds to a private one.
        """
        kind = kind.strip().lower()
        if kind not in KINDS:
            raise InvalidChannelError(f"a channel is {' or '.join(KINDS)}")
        name = " ".join(name.split())[:MAX_NAME_CHARS]
        if not name:
            raise InvalidChannelError("a channel needs a name")
        slug = slugify_channel(name)
        if not CHANNEL_SLUG_RE.match(slug):
            raise InvalidChannelError(
                "a channel's name must have some letters or digits in it"
            )
        if slug in RESERVED_SLUGS or slug.startswith("dm-"):
            raise InvalidChannelError(f"'{slug}' is reserved")
        now = _now()
        with self._connect() as conn:
            try:
                cursor = conn.execute(
                    "INSERT INTO chat_channels (slug, name, topic, kind, created_by,"
                    " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        slug,
                        name,
                        conn.seal(
                            "chat_channels", "topic", (slug,), topic.strip()[:MAX_TOPIC_CHARS]
                        ),
                        kind,
                        creator,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ChannelExistsError(slug) from exc
            channel_id = int(cursor.lastrowid)
            wanted = [creator] if kind == PRIVATE else self._everyone(conn)
            for who in wanted:
                self._join(conn, channel_id, who, added_by=creator)
            if kind == PRIVATE:
                for who in self._clean(conn, members or [], creator):
                    self._join(conn, channel_id, who, added_by=creator)
            row = self._row(conn, slug)
            return self._summary(conn, row, creator)

    @classmethod
    def _clean(
        cls, conn: sqlite3.Connection, usernames: list[str], creator: str
    ) -> list[str]:
        """The real, active accounts among *usernames*, each once, minus the creator."""
        seen: list[str] = []
        for raw in usernames:
            who = str(raw).strip().lower()
            if not who or who == creator or who in seen:
                continue
            if not cls._known(conn, who):
                raise InvalidChannelError(f"no such person: {who}")
            seen.append(who)
        return seen

    def direct(self, username: str, other: str) -> dict:
        """The channel between two people, made on the spot if it is new."""
        other = other.strip().lower()
        slug = direct_slug(username, other)
        now = _now()
        with self._connect() as conn:
            if not self._known(conn, other):
                raise InvalidChannelError(f"no such person: {other}")
            row = conn.execute(
                "SELECT * FROM chat_channels WHERE slug = ?", (slug,)
            ).fetchone()
            if row is None:
                cursor = conn.execute(
                    "INSERT INTO chat_channels (slug, name, topic, kind, created_by,"
                    " created_at, updated_at) VALUES (?, '', ?, ?, ?, ?, ?)",
                    (
                        slug,
                        conn.seal("chat_channels", "topic", (slug,), ""),
                        DIRECT,
                        username,
                        now,
                        now,
                    ),
                )
                channel_id = int(cursor.lastrowid)
                for who in dict.fromkeys((username, other)):
                    self._join(conn, channel_id, who, added_by=username)
                row = self._row(conn, slug)
            else:
                self._readable(conn, row, username)
            return self._summary(conn, row, username)

    # -- changing one -------------------------------------------------------------
    def update(self, username: str, slug: str, *, name: str | None = None,
               topic: str | None = None) -> dict:
        """Rename a channel or set its topic. Any member may; a direct one, nobody."""
        with self._connect() as conn:
            row = self._row(conn, slug.strip().lower())
            self._readable(conn, row, username)
            if row["kind"] == DIRECT:
                raise InvalidChannelError("a direct channel is named after the person in it")
            updates: dict[str, object] = {}
            if name is not None:
                cleaned = " ".join(name.split())[:MAX_NAME_CHARS]
                if not cleaned:
                    raise InvalidChannelError("a channel needs a name")
                updates["name"] = cleaned
            if topic is not None:
                updates["topic"] = conn.seal(
                    "chat_channels", "topic", (row["slug"],), topic.strip()[:MAX_TOPIC_CHARS]
                )
            if updates:
                assignments = ", ".join(f"{key} = ?" for key in updates)
                conn.execute(
                    f"UPDATE chat_channels SET {assignments}, updated_at = ? WHERE id = ?",
                    (*updates.values(), _now(), row["id"]),
                )
            return self._summary(conn, self._row(conn, row["slug"]), username)

    def add_members(self, actor: str, slug: str, usernames: list[str]) -> list[str]:
        """Add people to a private channel. Returns the ones who were not in it.

        Nobody accepts anything: they are in, and the caller tells them so.
        """
        with self._connect() as conn:
            row = self._row(conn, slug.strip().lower())
            self._readable(conn, row, actor)
            if row["kind"] == DIRECT:
                raise InvalidChannelError("a direct channel is two people and stays two")
            if row["kind"] == PUBLIC:
                raise InvalidChannelError("everybody is already in a public channel")
            tip = self._tip(conn, row["id"])
            added = []
            for who in self._clean(conn, usernames, actor):
                # Joining at the tip: what was said before you arrived is
                # there to scroll back to, but it is not news you missed.
                if self._join(conn, row["id"], who, added_by=actor, last_read=tip):
                    added.append(who)
            return added

    def leave(self, username: str, slug: str) -> None:
        with self._connect() as conn:
            row = self._row(conn, slug.strip().lower())
            if row["kind"] == PUBLIC:
                raise InvalidChannelError("a public channel is everybody's; you cannot leave it")
            if row["kind"] == DIRECT:
                raise InvalidChannelError("a direct channel is the two of you; it stays")
            if not self._is_member(conn, row["id"], username):
                raise NotAMemberError(row["slug"])
            conn.execute(
                "DELETE FROM chat_members WHERE channel_id = ? AND username = ?",
                (row["id"], username),
            )

    def delete(self, username: str, slug: str, *, force: bool = False) -> None:
        """Throw a channel away, messages and all. Its maker's to do, or an admin's."""
        with self._connect() as conn:
            row = self._row(conn, slug.strip().lower())
            if not force and row["created_by"] != username:
                raise NotAMemberError(f"{row['slug']} is not yours to delete")
            if row["kind"] == DIRECT:
                raise InvalidChannelError("a direct channel is not deleted, only left alone")
            conn.execute("DELETE FROM chat_channels WHERE id = ?", (row["id"],))

    # -- the messages --------------------------------------------------------------
    def messages(
        self,
        username: str,
        slug: str,
        *,
        limit: int = PAGE,
        before: int | None = None,
        after: int | None = None,
    ) -> list[dict]:
        """A page of a channel, oldest first.

        `before` walks back through history; `after` is how an open screen
        asks what it has not got yet.
        """
        limit = max(1, min(int(limit), 200))
        with self._connect() as conn:
            row = self._row(conn, slug.strip().lower())
            self._readable(conn, row, username)
            if after is not None:
                rows = conn.execute(
                    "SELECT * FROM chat_messages WHERE channel_id = ? AND id > ?"
                    " ORDER BY id LIMIT ?",
                    (row["id"], int(after), limit),
                ).fetchall()
            else:
                # The newest *limit*, then turned back the right way round.
                clause = " AND id < ?" if before is not None else ""
                args: tuple = (row["id"], int(before), limit) if before is not None else (
                    row["id"],
                    limit,
                )
                rows = conn.execute(
                    f"SELECT * FROM chat_messages WHERE channel_id = ?{clause}"
                    " ORDER BY id DESC LIMIT ?",
                    args,
                ).fetchall()
                rows = list(reversed(rows))
        return [_message(conn, r) for r in rows]

    def post(self, username: str, slug: str, body: str) -> dict:
        """Say something. Returns the message, and who should hear about it.

        Writing in a public channel you have never opened puts you in it, so
        the reply lands in your list like any other channel.
        """
        body = body.strip()[:MAX_BODY_CHARS]
        if not body:
            raise InvalidChannelError("a message needs some words")
        now = _now()
        with self._connect() as conn:
            row = self._row(conn, slug.strip().lower())
            self._readable(conn, row, username)
            self._join(conn, row["id"], username)
            cursor = conn.execute(
                "INSERT INTO chat_messages (channel_id, author, body, created_at)"
                " VALUES (?, ?, ?, ?)",
                (row["id"], username, conn.seal("chat_messages", "body", (row["id"],), body), now),
            )
            message_id = int(cursor.lastrowid)
            # Your own message is read the moment you send it, or your phone
            # would badge you for typing.
            conn.execute(
                "UPDATE chat_members SET last_read = ? WHERE channel_id = ? AND username = ?",
                (message_id, row["id"], username),
            )
            conn.execute(
                "UPDATE chat_channels SET updated_at = ? WHERE id = ?", (now, row["id"])
            )
            message = _message(
                conn,
                conn.execute("SELECT * FROM chat_messages WHERE id = ?", (message_id,)).fetchone(),
            )
            members = [who for who in self._members(conn, row["id"]) if who != username]
            channel = _channel(conn, self._row(conn, row["slug"]))
        return {
            "message": message,
            "channel": channel,
            # Everyone to tell. The caller does the telling; this module only
            # knows who, not how.
            "audience": members,
        }

    def edit(self, username: str, slug: str, message_id: int, body: str) -> dict:
        """Change what you said. Only the author, and only the words."""
        body = body.strip()[:MAX_BODY_CHARS]
        if not body:
            raise InvalidChannelError("a message needs some words")
        with self._connect() as conn:
            row = self._row(conn, slug.strip().lower())
            self._readable(conn, row, username)
            existing = conn.execute(
                "SELECT * FROM chat_messages WHERE id = ? AND channel_id = ?",
                (message_id, row["id"]),
            ).fetchone()
            if existing is None:
                raise UnknownChannelError(f"no message {message_id} in {row['slug']}")
            if existing["author"] != username:
                raise NotAMemberError("only the person who wrote it may change it")
            conn.execute(
                "UPDATE chat_messages SET body = ?, edited_at = ? WHERE id = ?",
                (conn.seal("chat_messages", "body", (row["id"],), body), _now(), message_id),
            )
            return _message(
                conn,
                conn.execute("SELECT * FROM chat_messages WHERE id = ?", (message_id,)).fetchone(),
            )

    def delete_message(self, username: str, slug: str, message_id: int, *,
                       force: bool = False) -> None:
        with self._connect() as conn:
            row = self._row(conn, slug.strip().lower())
            self._readable(conn, row, username)
            existing = conn.execute(
                "SELECT * FROM chat_messages WHERE id = ? AND channel_id = ?",
                (message_id, row["id"]),
            ).fetchone()
            if existing is None:
                raise UnknownChannelError(f"no message {message_id} in {row['slug']}")
            if not force and existing["author"] != username:
                raise NotAMemberError("only the person who wrote it may delete it")
            conn.execute("DELETE FROM chat_messages WHERE id = ?", (message_id,))

    # -- what has been read -----------------------------------------------------------
    def mark_read(self, username: str, slug: str, upto: int | None = None) -> int:
        """Move the read mark up. Returns where it now stands.

        Never down: two clients on the same channel, one of them scrolled
        back, must not un-read what the other has seen.
        """
        with self._connect() as conn:
            row = self._row(conn, slug.strip().lower())
            self._readable(conn, row, username)
            self._join(conn, row["id"], username)
            mark = self._tip(conn, row["id"]) if upto is None else int(upto)
            conn.execute(
                "UPDATE chat_members SET last_read = ? WHERE channel_id = ?"
                " AND username = ? AND last_read < ?",
                (mark, row["id"], username, mark),
            )
            current = conn.execute(
                "SELECT last_read FROM chat_members WHERE channel_id = ? AND username = ?",
                (row["id"], username),
            ).fetchone()
            return int(current["last_read"]) if current else mark

    def unread(self, username: str) -> dict:
        """How much is waiting, per channel and altogether.

        This is the number on the phone's icon, so it counts messages rather
        than channels: "3" should mean three things to read.
        """
        with self._connect() as conn:
            self._catch_up_public(conn, username)
            rows = conn.execute(
                "SELECT c.slug AS slug, COUNT(m.id) AS n FROM chat_channels c"
                " JOIN chat_members mem ON mem.channel_id = c.id AND mem.username = ?"
                " LEFT JOIN chat_messages m ON m.channel_id = c.id"
                "  AND m.id > mem.last_read AND m.author <> ?"
                " GROUP BY c.id",
                (username, username),
            ).fetchall()
        channels = {row["slug"]: int(row["n"]) for row in rows if row["n"]}
        return {"channels": channels, "total": sum(channels.values())}
