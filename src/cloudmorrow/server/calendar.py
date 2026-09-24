"""Calendars, the people who share them, and what is written in them.

A calendar is the second thing in Cloudmorrow that is not one person's, and it
borrows chat's shape on purpose: the kind of a calendar is the whole of the
access rule, and every call takes the username asking rather than assuming
it.

There are three kinds:

* **personal** — yours. Everybody has exactly one, made the first time they
  ask for their calendars and named after them. It cannot be shared, left or
  deleted, because it is the place your own things go and a place that can
  disappear is not that.
* **public** — everybody's. It is in everyone's list, anyone may put
  something in it, and nobody can leave, for the same reason a public
  channel cannot be left.
* **shared** — the people in it. Made by anyone, joined by being added;
  there is no invitation to accept. You are added, you are told, and you can
  leave.

Being added to a shared calendar leaves a notification, the way being added
to a channel does. An event does not: a shared calendar that pinged
everybody for every dentist appointment would be a calendar nobody leaves
notifications on. What the routes do about the telling is their business;
this module stores, and nothing here reaches out.

**Time is the wall clock.** A moment is stored as the local time somebody
typed — `2026-09-19T14:00` — and an all-day event as a bare date. No zone,
no conversion: this is one house on one clock, and "the dentist at ten" is
at ten on every screen in it, in October and in June alike. That also makes
a range query a string comparison, because ISO sorts the way time does.
"""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from cloudmorrow.server.db import Connection, connect

__all__ = [
    "COLOURS",
    "CalendarExistsError",
    "CalendarStore",
    "InvalidCalendarError",
    "InvalidEventError",
    "KINDS",
    "NotAMemberError",
    "PERSONAL",
    "PUBLIC",
    "SHARED",
    "UnknownCalendarError",
    "UnknownEventError",
    "day_window",
    "personal_slug",
]

PERSONAL = "personal"
PUBLIC = "public"
SHARED = "shared"
# The kinds a person may ask for. A personal calendar is never made by name.
KINDS: tuple[str, ...] = (PUBLIC, SHARED)

# The colours a calendar can be, named rather than spelled in hex: the TUI,
# the web app and the CLI each know what "violet" looks like to them, and
# `cloudmorrow.palette` is where all three get it from.
COLOURS: tuple[str, ...] = ("cyan", "violet", "green", "amber", "rose")

MAX_NAME_CHARS = 64
MAX_TITLE_CHARS = 120
MAX_LOCATION_CHARS = 120
# Long enough for the address, the door code and who else is coming.
MAX_NOTES_CHARS = 4000

# How much of a range one call will answer with. A year of a busy house is
# well inside it; a client asking for a decade gets told to ask for less.
MAX_EVENTS = 2000

# Same shape as a channel's, and for the same reason: a personal calendar's
# slug is built out of a username, so '_' has to be legal.
CALENDAR_SLUG_RE = re.compile(r"^[a-z0-9_][a-z0-9_-]{0,71}$")
RESERVED_SLUGS = {"new", "all", "none", "events", "mine", "today", "people"}
# What a personal calendar's slug starts with, so nobody can make one by hand.
PERSONAL_PREFIX = "my-"

SCHEMA = """
CREATE TABLE IF NOT EXISTS calendars (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    -- The calendar's id everywhere: in the API, and in the address bar.
    slug       TEXT    NOT NULL UNIQUE,
    name       TEXT    NOT NULL DEFAULT '',
    -- 'personal', 'public' or 'shared'. The kind is the access rule.
    kind       TEXT    NOT NULL DEFAULT 'shared',
    colour     TEXT    NOT NULL DEFAULT 'cyan',
    -- Whose it is: the one person for a personal calendar, and whoever made
    -- it otherwise. An owner may rename it and throw it away.
    owner      TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS calendar_members (
    calendar_id INTEGER NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
    username    TEXT    NOT NULL,
    added_by    TEXT    NOT NULL DEFAULT '',
    joined_at   TEXT    NOT NULL,
    PRIMARY KEY (calendar_id, username)
);
CREATE INDEX IF NOT EXISTS calendar_members_user ON calendar_members (username);
CREATE TABLE IF NOT EXISTS calendar_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    calendar_id INTEGER NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
    title       TEXT    NOT NULL,
    notes       TEXT    NOT NULL DEFAULT '',
    location    TEXT    NOT NULL DEFAULT '',
    -- Wall-clock ISO: '2026-09-19T14:00', or '2026-09-19' when all_day.
    -- The end of an all-day event is the last day it is on, inclusive.
    starts_at   TEXT    NOT NULL,
    ends_at     TEXT    NOT NULL,
    all_day     INTEGER NOT NULL DEFAULT 0,
    created_by  TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS calendar_events_when
    ON calendar_events (calendar_id, starts_at);
"""


class InvalidCalendarError(ValueError):
    pass


class CalendarExistsError(ValueError):
    pass


class UnknownCalendarError(LookupError):
    pass


class UnknownEventError(LookupError):
    pass


class InvalidEventError(ValueError):
    pass


class NotAMemberError(PermissionError):
    """The calendar exists; it is not this person's to read or write."""


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


def today() -> str:
    """The date here, now. All-day things are wall-clock, so this is local."""
    return dt.date.today().isoformat()


def slugify_calendar(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")[:72]
    return slug.rstrip("-")


def personal_slug(username: str) -> str:
    return PERSONAL_PREFIX + username.strip().lower()


# -- the wall clock ------------------------------------------------------------
def normalise_when(value: str, *, all_day: bool, what: str = "time") -> str:
    """One moment, spelled the one way this module stores them.

    An all-day event keeps a bare date; anything else keeps minutes. A client
    that sends a zone is answered in ours rather than refused — there is one
    clock here, and it is the wall's.
    """
    text = str(value or "").strip()
    if not text:
        raise InvalidEventError(f"an event needs a {what}")
    if all_day:
        try:
            return dt.date.fromisoformat(text[:10]).isoformat()
        except ValueError as exc:
            raise InvalidEventError(f"{what} should be a date, as 2026-09-19") from exc
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise InvalidEventError(
            f"{what} should be a date and a time, as 2026-09-19T14:00"
        ) from exc
    if moment.tzinfo is not None:
        moment = moment.astimezone().replace(tzinfo=None)
    return moment.strftime("%Y-%m-%dT%H:%M")


def day_window(start: str, end: str) -> tuple[str, str]:
    """The two strings a window of whole days compares against.

    Everything stored is ISO, so "is this event in these days" is a pair of
    string comparisons: it starts before the end of the last day, and it ends
    after the beginning of the first. A bare date sorts before any time on
    that date, which is exactly what an all-day event wants.
    """
    try:
        first = dt.date.fromisoformat(str(start)[:10])
        last = dt.date.fromisoformat(str(end)[:10])
    except ValueError as exc:
        raise InvalidEventError("a range is two dates, as 2026-09-01") from exc
    if last < first:
        first, last = last, first
    return first.isoformat(), f"{last.isoformat()}T23:59"


def days_of(event: dict) -> list[str]:
    """Every date an event is on, for a view that draws one day at a time."""
    first = dt.date.fromisoformat(event["starts_at"][:10])
    last = dt.date.fromisoformat(event["ends_at"][:10])
    if last < first:
        last = first
    return [
        (first + dt.timedelta(days=step)).isoformat()
        for step in range((last - first).days + 1)
    ]


def _moved_end(existing: sqlite3.Row, starts_at: str | None, ends_at: str | None,
               all_day: bool) -> str | None:
    """Where an event ends once its start has been dragged somewhere else.

    Moving something keeps how long it is: an hour at ten, moved to half
    eleven, is an hour at half eleven, and nobody who dragged it there meant
    to shorten it. An end given by hand is an end given by hand.
    """
    if ends_at is not None or starts_at is None:
        return ends_at if ends_at is not None else existing["ends_at"]
    if bool(existing["all_day"]) != all_day:
        # The shape of the times is changing too; let the new start stand
        # on its own rather than guessing a length across the change.
        return None
    try:
        if all_day:
            was = dt.date.fromisoformat(existing["starts_at"][:10])
            until = dt.date.fromisoformat(existing["ends_at"][:10])
            now = dt.date.fromisoformat(normalise_when(starts_at, all_day=True)[:10])
        else:
            was = dt.datetime.fromisoformat(existing["starts_at"])
            until = dt.datetime.fromisoformat(existing["ends_at"])
            now = dt.datetime.fromisoformat(normalise_when(starts_at, all_day=False))
    except (ValueError, InvalidEventError):
        return None
    return (now + (until - was)).isoformat() if until >= was else None


@dataclass(slots=True)
class Calendar:
    id: int
    slug: str
    name: str
    kind: str
    colour: str
    owner: str
    created_at: str
    updated_at: str

    @property
    def personal(self) -> bool:
        return self.kind == PERSONAL


def _calendar(row: sqlite3.Row) -> Calendar:
    return Calendar(
        id=row["id"],
        slug=row["slug"],
        name=row["name"],
        kind=row["kind"],
        colour=row["colour"],
        owner=row["owner"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _event(conn: Connection, row: sqlite3.Row) -> dict:
    scope = (row["calendar_id"],)
    return {
        "id": row["id"],
        "calendar": row["slug"],
        "calendar_name": row["name"],
        "colour": row["colour"],
        "title": conn.unseal("calendar_events", "title", scope, row["title"]),
        "notes": conn.unseal("calendar_events", "notes", scope, row["notes"]),
        "location": conn.unseal("calendar_events", "location", scope, row["location"]),
        "starts_at": row["starts_at"],
        "ends_at": row["ends_at"],
        "all_day": bool(row["all_day"]),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# What an event row is selected with everywhere: the calendar it is on comes
# with it, because nothing that draws an event wants it without its colour.
_EVENT_SELECT = (
    "SELECT e.*, c.slug AS slug, c.name AS name, c.colour AS colour"
    " FROM calendar_events e JOIN calendars c ON c.id = e.calendar_id"
)


class CalendarStore:
    """The calendars, who shares them, and the events on them."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return connect(self.db_path)

    # -- the people ---------------------------------------------------------
    # As in chat: the users table is in the same database, and a second store
    # object would only be a longer way of writing these two queries.

    @staticmethod
    def _everyone(conn: sqlite3.Connection) -> list[str]:
        rows = conn.execute(
            "SELECT username FROM users WHERE is_active = 1 AND user_type = 'human'"
            " ORDER BY username"
        ).fetchall()
        return [row["username"] for row in rows]

    def people(self, *, excluding: str = "") -> list[dict]:
        """Everyone you could share a calendar with."""
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

    @staticmethod
    def _display_name(conn: sqlite3.Connection, username: str) -> str:
        row = conn.execute(
            "SELECT display_name FROM users WHERE username = ?", (username,)
        ).fetchone()
        return (row["display_name"] if row else "") or username

    # -- finding one ---------------------------------------------------------
    @staticmethod
    def _row(conn: sqlite3.Connection, slug: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM calendars WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            raise UnknownCalendarError(slug)
        return row

    @staticmethod
    def _is_member(conn: sqlite3.Connection, calendar_id: int, username: str) -> bool:
        return (
            conn.execute(
                "SELECT 1 FROM calendar_members WHERE calendar_id = ? AND username = ?",
                (calendar_id, username),
            ).fetchone()
            is not None
        )

    @classmethod
    def _readable(cls, conn: sqlite3.Connection, row: sqlite3.Row, username: str) -> None:
        """Raise unless *username* may see this calendar at all.

        Public is everybody's. Anything else is its members', and a personal
        calendar has exactly one. There is no third rule.
        """
        if row["kind"] == PUBLIC:
            return
        if not cls._is_member(conn, row["id"], username):
            raise NotAMemberError(row["slug"])

    @staticmethod
    def _members(conn: sqlite3.Connection, calendar_id: int) -> list[str]:
        rows = conn.execute(
            "SELECT username FROM calendar_members WHERE calendar_id = ? ORDER BY username",
            (calendar_id,),
        ).fetchall()
        return [row["username"] for row in rows]

    @staticmethod
    def _join(
        conn: sqlite3.Connection, calendar_id: int, username: str, *, added_by: str = ""
    ) -> bool:
        """Put somebody in a calendar. False when they were already in it."""
        cursor = conn.execute(
            "INSERT OR IGNORE INTO calendar_members (calendar_id, username, added_by,"
            " joined_at) VALUES (?, ?, ?, ?)",
            (calendar_id, username, added_by, _now()),
        )
        return cursor.rowcount > 0

    # -- the ones that make themselves -----------------------------------------
    def _next_colour(self, conn: sqlite3.Connection) -> str:
        """A colour that is not already on screen, while there is one left."""
        taken = {
            row["colour"]
            for row in conn.execute("SELECT DISTINCT colour FROM calendars").fetchall()
        }
        free = [colour for colour in COLOURS if colour not in taken]
        if free:
            return free[0]
        count = conn.execute("SELECT COUNT(*) AS n FROM calendars").fetchone()["n"]
        return COLOURS[int(count) % len(COLOURS)]

    def _ensure_personal(self, conn: sqlite3.Connection, username: str) -> None:
        """Everybody has their own calendar, made the first time they look.

        Made here rather than when the account is: an account created before
        this feature existed has to get one too, and "when they look" is the
        one moment that covers both.
        """
        slug = personal_slug(username)
        if conn.execute("SELECT 1 FROM calendars WHERE slug = ?", (slug,)).fetchone():
            return
        now = _now()
        cursor = conn.execute(
            "INSERT INTO calendars (slug, name, kind, colour, owner, created_at,"
            " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (slug, self._display_name(conn, username), PERSONAL, COLOURS[0], username, now, now),
        )
        self._join(conn, int(cursor.lastrowid), username, added_by=username)

    def _catch_up_public(self, conn: sqlite3.Connection, username: str) -> None:
        """Put *username* in every public calendar they are not in yet."""
        rows = conn.execute(
            "SELECT id FROM calendars WHERE kind = ? AND id NOT IN"
            " (SELECT calendar_id FROM calendar_members WHERE username = ?)",
            (PUBLIC, username),
        ).fetchall()
        for row in rows:
            self._join(conn, row["id"], username)

    def _settle(self, conn: sqlite3.Connection, username: str) -> None:
        """What has to be true before this person's calendars are looked at."""
        self._ensure_personal(conn, username)
        self._catch_up_public(conn, username)

    def _find(self, conn: sqlite3.Connection, username: str, slug: str) -> sqlite3.Row:
        """The calendar of that name, if this person may see it at all.

        Every call that names one comes through here, so the two calendars
        nobody made by hand — your own, and a public one from before your
        account — are there the first time you ask for them rather than only
        after a listing.
        """
        self._settle(conn, username)
        row = self._row(conn, slug.strip().lower())
        self._readable(conn, row, username)
        return row

    # -- listing ---------------------------------------------------------------
    def _summary(self, conn: sqlite3.Connection, row: sqlite3.Row, username: str) -> dict:
        calendar = _calendar(row)
        members = self._members(conn, calendar.id)
        events = conn.execute(
            "SELECT COUNT(*) AS n FROM calendar_events WHERE calendar_id = ?",
            (calendar.id,),
        ).fetchone()["n"]
        return {
            "slug": calendar.slug,
            "name": calendar.name or calendar.slug,
            "kind": calendar.kind,
            "colour": calendar.colour,
            "owner": calendar.owner,
            "created_at": calendar.created_at,
            "updated_at": calendar.updated_at,
            "members": members,
            "member": username in members,
            # Yours to rename, to share and to throw away.
            "mine": calendar.owner == username,
            "events": int(events),
        }

    @staticmethod
    def _order(calendar: dict) -> tuple:
        """Yours first, then the shared ones, then the public ones."""
        rank = {PERSONAL: 0, SHARED: 1, PUBLIC: 2}[calendar["kind"]]
        return (rank, calendar["name"].lower(), calendar["slug"])

    def calendars(self, username: str) -> list[dict]:
        """Every calendar *username* can see, their own at the top."""
        with self._connect() as conn:
            self._settle(conn, username)
            rows = conn.execute(
                "SELECT * FROM calendars WHERE kind = ? OR id IN"
                " (SELECT calendar_id FROM calendar_members WHERE username = ?)",
                (PUBLIC, username),
            ).fetchall()
            listed = [self._summary(conn, row, username) for row in rows]
        listed.sort(key=self._order)
        return listed

    def get(self, username: str, slug: str) -> dict:
        with self._connect() as conn:
            return self._summary(conn, self._find(conn, username, slug), username)

    # -- making one --------------------------------------------------------------
    def create(
        self,
        creator: str,
        *,
        name: str,
        kind: str = SHARED,
        colour: str = "",
        members: list[str] | None = None,
    ) -> dict:
        """Make a calendar. Returns it as its creator sees it.

        A public calendar is everybody's, so everybody is put in it here;
        *members* only adds to a shared one.
        """
        kind = kind.strip().lower()
        if kind not in KINDS:
            raise InvalidCalendarError(f"a calendar is {' or '.join(KINDS)}")
        name = " ".join(name.split())[:MAX_NAME_CHARS]
        if not name:
            raise InvalidCalendarError("a calendar needs a name")
        slug = slugify_calendar(name)
        if not CALENDAR_SLUG_RE.match(slug):
            raise InvalidCalendarError(
                "a calendar's name must have some letters or digits in it"
            )
        if slug in RESERVED_SLUGS or slug.startswith(PERSONAL_PREFIX):
            raise InvalidCalendarError(f"'{slug}' is reserved")
        colour = colour.strip().lower()
        if colour and colour not in COLOURS:
            raise InvalidCalendarError(f"a colour is one of {', '.join(COLOURS)}")
        now = _now()
        with self._connect() as conn:
            # Your own calendar first, so the colour picked here is one that
            # is not already on the screen this will appear on.
            self._settle(conn, creator)
            chosen = colour or self._next_colour(conn)
            try:
                cursor = conn.execute(
                    "INSERT INTO calendars (slug, name, kind, colour, owner,"
                    " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (slug, name, kind, chosen, creator, now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise CalendarExistsError(slug) from exc
            calendar_id = int(cursor.lastrowid)
            wanted = self._everyone(conn) if kind == PUBLIC else [creator]
            for who in wanted:
                self._join(conn, calendar_id, who, added_by=creator)
            if kind == SHARED:
                for who in self._clean(conn, members or [], creator):
                    self._join(conn, calendar_id, who, added_by=creator)
            return self._summary(conn, self._row(conn, slug), creator)

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
                raise InvalidCalendarError(f"no such person: {who}")
            seen.append(who)
        return seen

    # -- changing one ---------------------------------------------------------------
    def update(
        self,
        username: str,
        slug: str,
        *,
        name: str | None = None,
        colour: str | None = None,
    ) -> dict:
        """Rename a calendar or recolour it. Its owner's to do."""
        with self._connect() as conn:
            row = self._find(conn, username, slug)
            if row["owner"] != username:
                raise NotAMemberError(f"{row['slug']} is not yours to change")
            updates: dict[str, object] = {}
            if name is not None:
                cleaned = " ".join(name.split())[:MAX_NAME_CHARS]
                if not cleaned:
                    raise InvalidCalendarError("a calendar needs a name")
                updates["name"] = cleaned
            if colour is not None:
                wanted = colour.strip().lower()
                if wanted not in COLOURS:
                    raise InvalidCalendarError(f"a colour is one of {', '.join(COLOURS)}")
                updates["colour"] = wanted
            if updates:
                assignments = ", ".join(f"{key} = ?" for key in updates)
                conn.execute(
                    f"UPDATE calendars SET {assignments}, updated_at = ? WHERE id = ?",
                    (*updates.values(), _now(), row["id"]),
                )
            return self._summary(conn, self._row(conn, row["slug"]), username)

    def add_members(self, actor: str, slug: str, usernames: list[str]) -> list[str]:
        """Share a calendar with people. Returns the ones who were not in it."""
        with self._connect() as conn:
            row = self._find(conn, actor, slug)
            if row["kind"] == PERSONAL:
                raise InvalidCalendarError(
                    "a personal calendar is one person's; make a shared one to share"
                )
            if row["kind"] == PUBLIC:
                raise InvalidCalendarError("everybody is already in a public calendar")
            added = []
            for who in self._clean(conn, usernames, actor):
                if self._join(conn, row["id"], who, added_by=actor):
                    added.append(who)
            return added

    def leave(self, username: str, slug: str) -> None:
        with self._connect() as conn:
            self._settle(conn, username)
            row = self._row(conn, slug.strip().lower())
            if row["kind"] == PUBLIC:
                raise InvalidCalendarError(
                    "a public calendar is everybody's; you cannot leave it"
                )
            if row["kind"] == PERSONAL:
                raise InvalidCalendarError("your own calendar stays yours")
            if not self._is_member(conn, row["id"], username):
                raise NotAMemberError(row["slug"])
            if row["owner"] == username:
                raise InvalidCalendarError(
                    "you made this one: delete it, or it is still yours"
                )
            conn.execute(
                "DELETE FROM calendar_members WHERE calendar_id = ? AND username = ?",
                (row["id"], username),
            )

    def delete(self, username: str, slug: str, *, force: bool = False) -> None:
        """Throw a calendar away, events and all. Its owner's to do, or an admin's."""
        with self._connect() as conn:
            self._settle(conn, username)
            row = self._row(conn, slug.strip().lower())
            if row["kind"] == PERSONAL:
                raise InvalidCalendarError("a personal calendar is not deleted")
            if not force and row["owner"] != username:
                raise NotAMemberError(f"{row['slug']} is not yours to delete")
            conn.execute("DELETE FROM calendars WHERE id = ?", (row["id"],))

    # -- what is on them ---------------------------------------------------------------
    def _visible_ids(self, conn: sqlite3.Connection, username: str) -> dict[int, str]:
        rows = conn.execute(
            "SELECT id, slug FROM calendars WHERE kind = ? OR id IN"
            " (SELECT calendar_id FROM calendar_members WHERE username = ?)",
            (PUBLIC, username),
        ).fetchall()
        return {row["id"]: row["slug"] for row in rows}

    def events(
        self,
        username: str,
        *,
        start: str,
        end: str,
        calendar: str | None = None,
    ) -> list[dict]:
        """Everything in a window of days, across every calendar you can see.

        One call, not one per calendar: a month view wants them together and
        sorted, and sorting them here is one query rather than the client
        merging six lists. An event that runs over several days comes back
        once, with both ends on it; drawing it on each of its days is the
        view's business.
        """
        first, last = day_window(start, end)
        with self._connect() as conn:
            self._settle(conn, username)
            visible = self._visible_ids(conn, username)
            if calendar:
                row = self._find(conn, username, calendar)
                visible = {row["id"]: row["slug"]}
            if not visible:
                return []
            marks = ", ".join("?" for _ in visible)
            rows = conn.execute(
                f"{_EVENT_SELECT} WHERE e.calendar_id IN ({marks})"
                " AND e.starts_at <= ? AND e.ends_at >= ?"
                " ORDER BY e.starts_at, e.ends_at, e.id LIMIT ?",
                (*visible, last, first, MAX_EVENTS),
            ).fetchall()
        return [_event(conn, row) for row in rows]

    def event(self, username: str, event_id: int) -> dict:
        with self._connect() as conn:
            row = self._event_row(conn, event_id)
            self._readable(conn, self._row(conn, row["slug"]), username)
            return _event(conn, row)

    @staticmethod
    def _event_row(conn: sqlite3.Connection, event_id: int) -> sqlite3.Row:
        row = conn.execute(f"{_EVENT_SELECT} WHERE e.id = ?", (int(event_id),)).fetchone()
        if row is None:
            raise UnknownEventError(str(event_id))
        return row

    @staticmethod
    def _fields(
        *,
        title: str,
        starts_at: str,
        ends_at: str | None,
        all_day: bool,
        notes: str,
        location: str,
    ) -> dict:
        """What goes in a row, checked. The one place an event is validated."""
        clean_title = " ".join(str(title).split())[:MAX_TITLE_CHARS]
        if not clean_title:
            raise InvalidEventError("an event needs a title")
        start = normalise_when(starts_at, all_day=all_day, what="start")
        # An event with no end is an hour long, or the day it is on.
        if ends_at is None or not str(ends_at).strip():
            end = start
            if not all_day:
                end = (
                    dt.datetime.fromisoformat(start) + dt.timedelta(hours=1)
                ).strftime("%Y-%m-%dT%H:%M")
        else:
            end = normalise_when(ends_at, all_day=all_day, what="end")
        if end < start:
            raise InvalidEventError("an event cannot end before it starts")
        return {
            "title": clean_title,
            "starts_at": start,
            "ends_at": end,
            "all_day": int(bool(all_day)),
            "notes": str(notes or "").strip()[:MAX_NOTES_CHARS],
            "location": " ".join(str(location or "").split())[:MAX_LOCATION_CHARS],
        }

    def add_event(
        self,
        username: str,
        slug: str,
        *,
        title: str,
        starts_at: str,
        ends_at: str | None = None,
        all_day: bool = False,
        notes: str = "",
        location: str = "",
    ) -> dict:
        """Put something in a calendar. Anyone who can see it may.

        A shared calendar you cannot write in would be a calendar you are
        being shown rather than one you share, and that is not what the two
        words mean.
        """
        fields = self._fields(
            title=title,
            starts_at=starts_at,
            ends_at=ends_at,
            all_day=all_day,
            notes=notes,
            location=location,
        )
        now = _now()
        with self._connect() as conn:
            row = self._find(conn, username, slug)
            cursor = conn.execute(
                "INSERT INTO calendar_events (calendar_id, title, notes, location,"
                " starts_at, ends_at, all_day, created_by, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["id"],
                    conn.seal("calendar_events", "title", (row["id"],), fields["title"]),
                    conn.seal("calendar_events", "notes", (row["id"],), fields["notes"]),
                    conn.seal("calendar_events", "location", (row["id"],), fields["location"]),
                    fields["starts_at"],
                    fields["ends_at"],
                    fields["all_day"],
                    username,
                    now,
                    now,
                ),
            )
            conn.execute(
                "UPDATE calendars SET updated_at = ? WHERE id = ?", (now, row["id"])
            )
            return _event(conn, self._event_row(conn, int(cursor.lastrowid)))

    def edit_event(
        self,
        username: str,
        event_id: int,
        *,
        title: str | None = None,
        starts_at: str | None = None,
        ends_at: str | None = None,
        all_day: bool | None = None,
        notes: str | None = None,
        location: str | None = None,
        calendar: str | None = None,
        force: bool = False,
    ) -> dict:
        """Change an event, and move it to another calendar if asked.

        Whoever wrote it may, and so may whoever owns the calendar it is on:
        a shared calendar with somebody's stale event stuck on it, and only
        that somebody able to fix it, is a worse rule than this one.
        """
        with self._connect() as conn:
            existing = self._event_row(conn, event_id)
            row = self._row(conn, existing["slug"])
            self._readable(conn, row, username)
            if not force and username not in (existing["created_by"], row["owner"]):
                raise NotAMemberError("that is somebody else's event")
            whole_day = bool(existing["all_day"] if all_day is None else all_day)
            # What it says now, opened: the row itself holds ciphertext.
            was = _event(conn, existing)
            fields = self._fields(
                title=was["title"] if title is None else title,
                # Switching an event to all-day keeps the day it was on and
                # drops the time, which is the only sane reading of it.
                starts_at=existing["starts_at"] if starts_at is None else starts_at,
                ends_at=_moved_end(existing, starts_at, ends_at, whole_day),
                all_day=whole_day,
                notes=was["notes"] if notes is None else notes,
                location=was["location"] if location is None else location,
            )
            target = row["id"]
            if calendar is not None and calendar.strip().lower() != existing["slug"]:
                target = self._find(conn, username, calendar)["id"]
            conn.execute(
                "UPDATE calendar_events SET calendar_id = ?, title = ?, notes = ?,"
                " location = ?, starts_at = ?, ends_at = ?, all_day = ?, updated_at = ?"
                " WHERE id = ?",
                (
                    target,
                    conn.seal("calendar_events", "title", (target,), fields["title"]),
                    conn.seal("calendar_events", "notes", (target,), fields["notes"]),
                    conn.seal("calendar_events", "location", (target,), fields["location"]),
                    fields["starts_at"],
                    fields["ends_at"],
                    fields["all_day"],
                    _now(),
                    int(event_id),
                ),
            )
            return _event(conn, self._event_row(conn, int(event_id)))

    def delete_event(self, username: str, event_id: int, *, force: bool = False) -> None:
        with self._connect() as conn:
            existing = self._event_row(conn, event_id)
            row = self._row(conn, existing["slug"])
            self._readable(conn, row, username)
            if not force and username not in (existing["created_by"], row["owner"]):
                raise NotAMemberError("that is somebody else's event")
            conn.execute("DELETE FROM calendar_events WHERE id = ?", (int(event_id),))

    # -- what is next ----------------------------------------------------------------
    def upcoming(self, username: str, *, days: int = 7, limit: int = 20) -> list[dict]:
        """The next few things, for a screen that has room for a line of them."""
        start = dt.date.today()
        end = start + dt.timedelta(days=max(1, int(days)))
        soon = self.events(username, start=start.isoformat(), end=end.isoformat())
        now = dt.datetime.now().strftime("%Y-%m-%dT%H:%M")
        # Something that finished this morning is not upcoming; something
        # that is going on right now is. An all-day event is measured in
        # days, so today's is still to come at four in the afternoon.
        return [
            event
            for event in soon
            if event["ends_at"] >= (start.isoformat() if event["all_day"] else now)
        ][: max(1, int(limit))]
