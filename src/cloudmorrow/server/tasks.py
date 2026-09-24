"""Boards, and the tasks on them.

A board is a title and three lanes — ToDo, Doing, Done — because that is what
a board is for: what you have not started, what you are on, and what is behind
you. There is no fourth lane and no way to add one; a board you have to
configure before you can use it is a board you do not use.

A task is a title and a markdown body, which is where its detail and its
subtasks live. Subtasks are `- [ ]` lines, the same ones the note editor
already knows how to tick, so a task is a small note with a lane — rather than
a second kind of checklist with its own storage, its own API and its own bugs.

Done is a lane you pass through, not one that fills up. A task that has been
done for a week is deleted, which is what makes the lane worth looking at: it
is what you finished recently, not everything you have ever finished. The
sweep happens when a board is read, so it needs nothing scheduled to run.

Boards are yours, like notes, rather than a project's. The work you have to do
rarely divides the way your checkouts do.

There is never no board. The first time yours are listed you get one named
after you, which you can rename, delete or add to — a board you have to create
before you can write a task down is a board you write the task somewhere else
instead.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from cloudmorrow.server.db import Connection, connect
from cloudmorrow.slugs import InvalidSlugError, slugify, validate_slug

__all__ = [
    "BoardExistsError",
    "DEFAULT_BOARD_SLUG",
    "DONE",
    "DOING",
    "InvalidLaneError",
    "InvalidSlugError",
    "LANES",
    "TODO",
    "TaskStore",
    "UnknownBoardError",
    "UnknownTaskError",
    "default_board_slug",
    "default_board_title",
]

# The three lanes, in the order they are shown. Left to right is also the
# direction work travels.
TODO = "todo"
DOING = "doing"
DONE = "done"
LANES: tuple[str, ...] = (TODO, DOING, DONE)

LANE_TITLES = {TODO: "ToDo", DOING: "Doing", DONE: "Done"}

# How long a finished task stays on the board before it is deleted.
DONE_TTL_DAYS = 7

# The board everyone starts with, when a name yields nothing sluggable.
DEFAULT_BOARD_SLUG = "my-tasks"


def default_board_title(owner: str) -> str:
    """What the board you did not make is called: yours."""
    owner = (owner or "").strip()
    return f"{owner}'s tasks" if owner else "My tasks"


def default_board_slug(owner: str) -> str:
    """Its id — `jimmi-tasks` rather than the `jimmi-s-tasks` the title gives."""
    return slugify(f"{owner} tasks") or DEFAULT_BOARD_SLUG


class BoardExistsError(ValueError):
    pass


class UnknownBoardError(LookupError):
    pass


class UnknownTaskError(LookupError):
    pass


class InvalidLaneError(ValueError):
    pass


def validate_lane(lane: str) -> str:
    lane = (lane or "").strip().lower()
    if lane not in LANES:
        raise InvalidLaneError(f"lane must be one of {', '.join(LANES)}")
    return lane


@dataclass(slots=True)
class Board:
    id: int
    owner: str
    slug: str
    title: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class Task:
    id: int
    owner: str
    board: str
    title: str
    body: str
    lane: str
    position: int
    created_at: str
    updated_at: str
    # When it entered Done, and so when the week starts counting. None in any
    # other lane, including for a task that was moved back out of Done.
    done_at: str | None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "board": self.board,
            "title": self.title,
            "body": self.body,
            "lane": self.lane,
            "position": self.position,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "done_at": self.done_at,
        }


def _board(conn: Connection, row: sqlite3.Row) -> Board:
    return Board(
        id=row["id"],
        owner=row["owner"],
        slug=row["slug"],
        title=conn.unseal("boards", "title", (row["owner"],), row["title"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _task(conn: Connection, row: sqlite3.Row) -> Task:
    scope = (row["owner"],)
    return Task(
        id=row["id"],
        owner=row["owner"],
        board=row["board"],
        title=conn.unseal("tasks", "title", scope, row["title"]),
        body=conn.unseal("tasks", "body", scope, row["body"]),
        lane=row["lane"],
        position=row["position"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        done_at=row["done_at"],
    )


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def _stamp(moment: dt.datetime | None = None) -> str:
    return (moment or _now()).isoformat(timespec="seconds")


def expires_at(done_at: str) -> dt.datetime | None:
    """When a task finished at *done_at* stops being shown."""
    try:
        moment = dt.datetime.fromisoformat(done_at)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return moment + dt.timedelta(days=DONE_TTL_DAYS)


class TaskStore:
    """Boards and their tasks, one table each."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        connect(self.db_path).close()

    # -- boards ------------------------------------------------------------
    def boards(self, owner: str) -> list[Board]:
        """Your boards — and the one you start with, if you have none.

        Seeded on read, the way the Done lane is swept on read: nothing has to
        run when an account is made, and a board that was deleted down to zero
        comes back rather than leaving a tab strip with nothing in it.
        """
        boards = self._board_rows(owner)
        if not boards:
            self.ensure_default_board(owner)
            boards = self._board_rows(owner)
        return boards

    def _board_rows(self, owner: str) -> list[Board]:
        # Titles are sealed, so the alphabet is applied here, not in SQL.
        with connect(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM boards WHERE owner = ?", (owner,)).fetchall()
        return sorted((_board(conn, row) for row in rows), key=lambda b: b.title.casefold())

    def ensure_default_board(self, owner: str) -> Board | None:
        """Give *owner* their starting board, unless they already have one.

        Named after them and otherwise ordinary: rename it, fill it, delete it.
        Nothing anywhere depends on its slug.
        """
        if self._board_rows(owner):
            return None
        try:
            slug = validate_slug(default_board_slug(owner))
        except InvalidSlugError:
            # A username that will not make a slug, or one that lands on a
            # reserved word. There is always a name that works.
            slug = DEFAULT_BOARD_SLUG
        try:
            return self.create_board(owner, default_board_title(owner), slug=slug)
        except BoardExistsError:
            # Two calls raced; the other one won and there is a board now.
            return self.get_board(owner, slug)

    def get_board(self, owner: str, slug: str) -> Board | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM boards WHERE owner = ? AND slug = ?",
                (owner, (slug or "").strip().lower()),
            ).fetchone()
        return _board(conn, row) if row else None

    def require_board(self, owner: str, slug: str) -> Board:
        board = self.get_board(owner, slug)
        if board is None:
            raise UnknownBoardError(slug)
        return board

    def create_board(self, owner: str, title: str, *, slug: str = "") -> Board:
        title = (title or "").strip()
        if not title:
            raise ValueError("board title is required")
        slug = validate_slug(slug or slugify(title))
        now = _stamp()
        try:
            with connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO boards (owner, slug, title, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (owner, slug, conn.seal("boards", "title", (owner,), title), now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise BoardExistsError(slug) from exc
        return self.require_board(owner, slug)

    def rename_board(self, owner: str, slug: str, title: str) -> Board:
        """A new title, but the same slug — the id a board is known by is its own."""
        title = (title or "").strip()
        if not title:
            raise ValueError("board title is required")
        with connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE boards SET title = ?, updated_at = ? WHERE owner = ? AND slug = ?",
                (conn.seal("boards", "title", (owner,), title), _stamp(), owner, slug),
            )
            if cursor.rowcount == 0:
                raise UnknownBoardError(slug)
        return self.require_board(owner, slug)

    def delete_board(self, owner: str, slug: str) -> None:
        """Delete a board and everything on it. Nothing else refers to a task."""
        with connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM boards WHERE owner = ? AND slug = ?", (owner, slug)
            )
            if cursor.rowcount == 0:
                raise UnknownBoardError(slug)
            conn.execute(
                "DELETE FROM tasks WHERE owner = ? AND board = ?", (owner, slug)
            )

    # -- tasks -------------------------------------------------------------
    def tasks(self, owner: str, board: str) -> list[Task]:
        """Every task on a board, in lane order — after the Done lane is swept."""
        self.sweep(owner=owner, board=board)
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE owner = ? AND board = ?"
                " ORDER BY position, id",
                (owner, board),
            ).fetchall()
        return [_task(conn, row) for row in rows]

    def get_task(self, owner: str, task_id: int) -> Task | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE owner = ? AND id = ?", (owner, task_id)
            ).fetchone()
        return _task(conn, row) if row else None

    def require_task(self, owner: str, task_id: int) -> Task:
        task = self.get_task(owner, task_id)
        if task is None:
            raise UnknownTaskError(str(task_id))
        return task

    def create_task(
        self, owner: str, board: str, title: str, *, body: str = "", lane: str = TODO
    ) -> Task:
        """A new task, at the bottom of its lane. New work starts in ToDo."""
        title = (title or "").strip()
        if not title:
            raise ValueError("task title is required")
        self.require_board(owner, board)
        lane = validate_lane(lane)
        now = _stamp()
        with connect(self.db_path) as conn:
            position = self._next_position(conn, owner, board, lane)
            cursor = conn.execute(
                "INSERT INTO tasks (owner, board, title, body, lane, position,"
                " created_at, updated_at, done_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    owner,
                    board,
                    conn.seal("tasks", "title", (owner,), title),
                    conn.seal("tasks", "body", (owner,), body),
                    lane,
                    position,
                    now,
                    now,
                    now if lane == DONE else None,
                ),
            )
            task_id = int(cursor.lastrowid or 0)
        return self.require_task(owner, task_id)

    @staticmethod
    def _next_position(
        conn: sqlite3.Connection, owner: str, board: str, lane: str
    ) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(position), -1) AS last FROM tasks"
            " WHERE owner = ? AND board = ? AND lane = ?",
            (owner, board, lane),
        ).fetchone()
        return int(row["last"]) + 1

    def edit_task(
        self, owner: str, task_id: int, *, title: str | None = None, body: str | None = None
    ) -> Task:
        """Change what a task says. Moving it is `move_task`; this is the text."""
        task = self.require_task(owner, task_id)
        updates: dict[str, object] = {}
        if title is not None:
            cleaned = title.strip()
            if not cleaned:
                raise ValueError("task title is required")
            updates["title"] = cleaned
        if body is not None:
            updates["body"] = body
        if not updates:
            return task
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with connect(self.db_path) as conn:
            sealed = [
                conn.seal("tasks", key, (owner,), str(value)) for key, value in updates.items()
            ]
            conn.execute(
                f"UPDATE tasks SET {assignments}, updated_at = ? WHERE owner = ? AND id = ?",
                (*sealed, _stamp(), owner, task_id),
            )
        return self.require_task(owner, task_id)

    def move_task(self, owner: str, task_id: int, lane: str, index: int | None = None) -> Task:
        """Put a task in a lane, at *index* within it, and renumber both lanes.

        Renumbering rather than wedging a fraction in between: a lane holds a
        handful of rows, and positions that are always 0..n-1 cannot drift into
        the tangle that makes a board show two tasks in the same place.
        """
        task = self.require_task(owner, task_id)
        lane = validate_lane(lane)
        now = _stamp()
        with connect(self.db_path) as conn:
            # Entering Done starts the week; leaving it stops the clock, so a
            # task pulled back out is not deleted a few days later.
            done_at = task.done_at if task.lane == DONE else None
            if lane == DONE and done_at is None:
                done_at = now
            elif lane != DONE:
                done_at = None
            conn.execute(
                "UPDATE tasks SET lane = ?, done_at = ?, updated_at = ? WHERE owner = ? AND id = ?",
                (lane, done_at, now, owner, task_id),
            )
            if task.lane != lane:
                self._renumber(conn, owner, task.board, task.lane, moved=task_id)
            self._renumber(conn, owner, task.board, lane, moved=task_id, insert_at=index)
        return self.require_task(owner, task_id)

    @staticmethod
    def _renumber(
        conn: sqlite3.Connection,
        owner: str,
        board: str,
        lane: str,
        *,
        moved: int,
        insert_at: int | None = None,
    ) -> None:
        """Give a lane positions 0..n-1, putting *moved* at *insert_at* if asked."""
        ids = [
            int(row["id"])
            for row in conn.execute(
                "SELECT id FROM tasks WHERE owner = ? AND board = ? AND lane = ?"
                " ORDER BY position, id",
                (owner, board, lane),
            )
        ]
        if insert_at is not None and moved in ids:
            ids.remove(moved)
            ids.insert(max(0, min(insert_at, len(ids))), moved)
        for position, task_id in enumerate(ids):
            conn.execute(
                "UPDATE tasks SET position = ? WHERE owner = ? AND id = ?",
                (position, owner, task_id),
            )

    def delete_task(self, owner: str, task_id: int) -> None:
        with connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM tasks WHERE owner = ? AND id = ?", (owner, task_id)
            )
            if cursor.rowcount == 0:
                raise UnknownTaskError(str(task_id))

    # -- the Done lane empties itself --------------------------------------
    def sweep(self, *, owner: str | None = None, board: str | None = None) -> int:
        """Delete tasks that have been Done for longer than a week.

        Called whenever a board is read, so the rule holds without anything
        scheduled. Returns how many went.
        """
        cutoff = _stamp(_now() - dt.timedelta(days=DONE_TTL_DAYS))
        query = "DELETE FROM tasks WHERE lane = ? AND done_at IS NOT NULL AND done_at < ?"
        params: list[object] = [DONE, cutoff]
        if owner is not None:
            query += " AND owner = ?"
            params.append(owner)
        if board is not None:
            query += " AND board = ?"
            params.append(board)
        with connect(self.db_path) as conn:
            return int(conn.execute(query, params).rowcount)
