"""What an assistant can do in Cloudmorrow: the MCP tools.

Each tool is one thing a person could do themselves in the app — read a
note, add a task, move it along — described plainly enough that a model
picks the right one, and done with the same stores the API uses, as the
signed-in user and nobody else. A feature an administrator switched off
takes its tools off the list, and refuses them if called anyway.

Secrets are not here on purpose. An assistant that can read your notes is
useful; one that can read your production keys is a liability, and the
person can always paste a value in themselves.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cloudmorrow.paths import UnsafePathError
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState
from cloudmorrow.server.notes import (
    NoteConflictError,
    NoteExistsError,
    NoteNode,
    NoteNotFoundError,
    NoteStore,
)
from cloudmorrow.server.tasks import LANES

Handler = Callable[[AppState, User, dict[str, Any]], Any]


class ToolError(Exception):
    """The tool could not do what was asked, and this is what to tell the model."""


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    # JSON Schema for the arguments, as MCP wants it.
    schema: dict[str, Any]
    # The server feature this belongs to: off means gone.
    feature: str
    handler: Handler

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.schema,
        }


def _schema(properties: dict[str, dict], required: tuple[str, ...] = ()) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return schema


def _str(args: dict[str, Any], key: str, *, required: bool = False, default: str = "") -> str:
    value = args.get(key)
    if value is None:
        if required:
            raise ToolError(f"{key} is required")
        return default
    if not isinstance(value, str):
        raise ToolError(f"{key} must be a string")
    if required and not value.strip():
        raise ToolError(f"{key} is required")
    return value


def _int(args: dict[str, Any], key: str, *, required: bool = False) -> int | None:
    value = args.get(key)
    if value is None:
        if required:
            raise ToolError(f"{key} is required")
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"{key} must be a whole number")
    return value


def _bool(args: dict[str, Any], key: str, default: bool = False) -> bool:
    value = args.get(key, default)
    if not isinstance(value, bool):
        raise ToolError(f"{key} must be true or false")
    return value


# -- notes -------------------------------------------------------------------
def _notes(state: AppState, user: User) -> NoteStore:
    return state.note_store(user)


def _flatten(node: NoteNode, into: list[dict]) -> None:
    for child in node.children:
        entry = {"path": child.path, "is_dir": child.is_dir}
        if child.is_dir:
            into.append(entry)
            _flatten(child, into)
        else:
            entry["size"] = child.size
            if child.preview is not None:
                entry["preview"] = child.preview
            into.append(entry)


def list_notes(state: AppState, user: User, args: dict[str, Any]) -> Any:
    folder = _str(args, "folder").strip("/")
    tree = _notes(state, user).tree(previews=_bool(args, "previews"))
    node = tree
    for part in [p for p in folder.split("/") if p]:
        node = next((c for c in node.children if c.is_dir and c.name == part), None)
        if node is None:
            raise ToolError(f"no such folder: {folder}")
    entries: list[dict] = []
    _flatten(node, entries)
    return {"folder": folder, "entries": entries}


def read_note(state: AppState, user: User, args: dict[str, Any]) -> Any:
    note = _notes(state, user).read(_str(args, "path", required=True))
    return {"path": note.path, "content": note.content, "rev": note.rev}


def search_notes(state: AppState, user: User, args: dict[str, Any]) -> Any:
    query = _str(args, "query", required=True)
    return {"query": query, "results": _notes(state, user).search(query)}


def create_note(state: AppState, user: User, args: dict[str, Any]) -> Any:
    note = _notes(state, user).create_note(
        _str(args, "path", required=True), _str(args, "content")
    )
    return {"path": note.path, "rev": note.rev, "created": True}


def write_note(state: AppState, user: User, args: dict[str, Any]) -> Any:
    rev = _str(args, "rev") or None
    note = _notes(state, user).write(
        _str(args, "path", required=True), _str(args, "content", required=True), rev=rev
    )
    return {"path": note.path, "rev": note.rev}


def append_to_note(state: AppState, user: User, args: dict[str, Any]) -> Any:
    store = _notes(state, user)
    path = _str(args, "path", required=True)
    text = _str(args, "text", required=True)
    current = store.read(path)
    body = current.content
    if body and not body.endswith("\n"):
        body += "\n"
    note = store.write(current.path, body + text.rstrip("\n") + "\n", rev=current.rev)
    return {"path": note.path, "rev": note.rev}


def move_note(state: AppState, user: User, args: dict[str, Any]) -> Any:
    moved = _notes(state, user).move(
        _str(args, "from", required=True), _str(args, "to", required=True)
    )
    return {"path": moved}


def delete_note(state: AppState, user: User, args: dict[str, Any]) -> Any:
    path = _str(args, "path", required=True)
    _notes(state, user).delete(path, recursive=False)
    return {"path": path, "deleted": True}


def create_folder(state: AppState, user: User, args: dict[str, Any]) -> Any:
    path = _notes(state, user).create_dir(_str(args, "path", required=True))
    return {"path": path, "is_dir": True}


# -- tasks -------------------------------------------------------------------
def list_boards(state: AppState, user: User, args: dict[str, Any]) -> Any:
    return {"boards": [board.to_dict() for board in state.tasks.boards(user.username)]}


def create_board(state: AppState, user: User, args: dict[str, Any]) -> Any:
    board = state.tasks.create_board(
        user.username, _str(args, "title", required=True), slug=_str(args, "slug")
    )
    return board.to_dict()


def _board_slug(state: AppState, user: User, args: dict[str, Any]) -> str:
    """The board asked for, or the only one there is."""
    slug = _str(args, "board").strip().lower()
    if slug:
        return slug
    boards = state.tasks.boards(user.username)
    if len(boards) == 1:
        return boards[0].slug
    names = ", ".join(f"{b.slug} ({b.title})" for b in boards)
    raise ToolError(f"say which board: {names}")


def list_tasks(state: AppState, user: User, args: dict[str, Any]) -> Any:
    slug = _str(args, "board").strip().lower()
    boards = state.tasks.boards(user.username)
    if slug:
        boards = [b for b in boards if b.slug == slug]
        if not boards:
            raise ToolError(f"no such board: {slug}")
    return {
        "boards": [
            {
                **board.to_dict(),
                "tasks": [task.to_dict() for task in state.tasks.tasks(user.username, board.slug)],
            }
            for board in boards
        ]
    }


def create_task(state: AppState, user: User, args: dict[str, Any]) -> Any:
    task = state.tasks.create_task(
        user.username,
        _board_slug(state, user, args),
        _str(args, "title", required=True),
        body=_str(args, "body"),
        lane=_str(args, "lane", default="todo") or "todo",
    )
    return task.to_dict()


def update_task(state: AppState, user: User, args: dict[str, Any]) -> Any:
    task_id = _int(args, "id", required=True)
    title = args.get("title")
    body = args.get("body")
    if title is not None and not isinstance(title, str):
        raise ToolError("title must be a string")
    if body is not None and not isinstance(body, str):
        raise ToolError("body must be a string")
    return state.tasks.edit_task(user.username, task_id, title=title, body=body).to_dict()


def move_task(state: AppState, user: User, args: dict[str, Any]) -> Any:
    task_id = _int(args, "id", required=True)
    return state.tasks.move_task(
        user.username, task_id, _str(args, "lane", required=True), _int(args, "index")
    ).to_dict()


def delete_task(state: AppState, user: User, args: dict[str, Any]) -> Any:
    task_id = _int(args, "id", required=True)
    task = state.tasks.require_task(user.username, task_id)
    state.tasks.delete_task(user.username, task_id)
    return {"id": task.id, "title": task.title, "deleted": True}



# -- the catalogue ------------------------------------------------------------
_PATH = {
    "type": "string",
    "description": "Path under the notes root, e.g. 'ideas/garden.md'. The .md suffix is optional.",
}
_BOARD = {
    "type": "string",
    "description": "The board's id (slug). May be left out when there is only one board.",
}
_TASK_ID = {"type": "integer", "description": "The task's id, from list_tasks."}
_LANE = {"type": "string", "enum": list(LANES), "description": "todo, doing or done."}

TOOLS: tuple[Tool, ...] = (
    Tool(
        "list_notes",
        "List the user's notes and folders, optionally under one folder. Paths come back "
        "relative to the notes root; use them with read_note.",
        _schema(
            {
                "folder": {
                    "type": "string",
                    "description": "Only this folder and what is under it. Empty for everything.",
                },
                "previews": {
                    "type": "boolean",
                    "description": "Include the first line or two of each note.",
                },
            }
        ),
        "notes",
        list_notes,
    ),
    Tool(
        "read_note",
        "Read one note: its Markdown content and its rev (a version stamp for write_note).",
        _schema({"path": _PATH}, ("path",)),
        "notes",
        read_note,
    ),
    Tool(
        "search_notes",
        "Find notes whose name or text contains the words given (case-insensitive substring).",
        _schema({"query": {"type": "string", "description": "What to look for."}}, ("query",)),
        "notes",
        search_notes,
    ),
    Tool(
        "create_note",
        "Make a new Markdown note. Fails if a note already exists at that path.",
        _schema(
            {"path": _PATH, "content": {"type": "string", "description": "The Markdown body."}},
            ("path",),
        ),
        "notes",
        create_note,
    ),
    Tool(
        "write_note",
        "Replace the whole content of a note (creating it if needed). Read it first and pass "
        "its rev so a note changed elsewhere in the meantime is not overwritten.",
        _schema(
            {
                "path": _PATH,
                "content": {"type": "string", "description": "The full new Markdown body."},
                "rev": {
                    "type": "string",
                    "description": "The rev from read_note. Optional, but recommended.",
                },
            },
            ("path", "content"),
        ),
        "notes",
        write_note,
    ),
    Tool(
        "append_to_note",
        "Add text to the end of an existing note, on a new line. Good for lists and logs.",
        _schema(
            {"path": _PATH, "text": {"type": "string", "description": "What to add."}},
            ("path", "text"),
        ),
        "notes",
        append_to_note,
    ),
    Tool(
        "move_note",
        "Move or rename a note or folder.",
        _schema(
            {"from": _PATH, "to": {"type": "string", "description": "The new path."}},
            ("from", "to"),
        ),
        "notes",
        move_note,
    ),
    Tool(
        "delete_note",
        "Delete one note, or an empty folder. This cannot be undone.",
        _schema({"path": _PATH}, ("path",)),
        "notes",
        delete_note,
    ),
    Tool(
        "create_folder",
        "Make a folder for notes.",
        _schema(
            {"path": {"type": "string", "description": "Folder path under the notes root."}},
            ("path",),
        ),
        "notes",
        create_folder,
    ),
    Tool(
        "list_boards",
        "List the user's task boards. Every board has three lanes: todo, doing and done.",
        _schema({}),
        "tasks",
        list_boards,
    ),
    Tool(
        "create_board",
        "Make a new task board.",
        _schema(
            {
                "title": {"type": "string", "description": "What the board is called."},
                "slug": {
                    "type": "string",
                    "description": "An id for it. Made from the title when left out.",
                },
            },
            ("title",),
        ),
        "tasks",
        create_board,
    ),
    Tool(
        "list_tasks",
        "List tasks, with their lane and id, on one board or on every board.",
        _schema({"board": _BOARD}),
        "tasks",
        list_tasks,
    ),
    Tool(
        "create_task",
        "Add a task to a board. New tasks start in the todo lane unless told otherwise.",
        _schema(
            {
                "title": {"type": "string", "description": "One line: what is to be done."},
                "board": _BOARD,
                "body": {"type": "string", "description": "Details, in Markdown. Optional."},
                "lane": _LANE,
            },
            ("title",),
        ),
        "tasks",
        create_task,
    ),
    Tool(
        "update_task",
        "Change a task's title or body. To change its lane, use move_task.",
        _schema(
            {
                "id": _TASK_ID,
                "title": {"type": "string", "description": "The new title."},
                "body": {"type": "string", "description": "The new body."},
            },
            ("id",),
        ),
        "tasks",
        update_task,
    ),
    Tool(
        "move_task",
        "Move a task to a lane: todo, doing or done. Done tasks are swept away after a week.",
        _schema(
            {
                "id": _TASK_ID,
                "lane": _LANE,
                "index": {
                    "type": "integer",
                    "description": "Position within the lane, 0 for the top. Bottom when left out.",
                },
            },
            ("id", "lane"),
        ),
        "tasks",
        move_task,
    ),
    Tool(
        "delete_task",
        "Delete a task for good. Moving it to done is usually what is wanted instead.",
        _schema({"id": _TASK_ID}, ("id",)),
        "tasks",
        delete_task,
    ),
)

BY_NAME: dict[str, Tool] = {tool.name: tool for tool in TOOLS}

INSTRUCTIONS = (
    "Cloudmorrow is the user's own cloud: Markdown notes in folders and task "
    "boards with todo/doing/done lanes. Everything here "
    "is the signed-in user's own data. Read before you overwrite, and prefer "
    "append_to_note and move_task over rewriting or deleting."
)


FEATURE_LABELS = {"notes": "Notes", "tasks": "Tasks"}


def _enabled(state: AppState, feature: str) -> bool:
    """Is *feature* switched on? A server without the switchboard has everything on."""
    switches = getattr(state, "features", None)
    return switches is None or switches.enabled(feature)


def available(state: AppState) -> list[Tool]:
    """The tools on offer right now: those whose feature is switched on."""
    return [tool for tool in TOOLS if _enabled(state, tool.feature)]


def call(state: AppState, user: User, name: str, arguments: Any) -> dict[str, Any]:
    """Run a tool and shape the answer the way MCP wants it.

    A tool that could not do its job answers with `isError` and a plain
    sentence, so the model can say so or try again — that is not a protocol
    error. An unknown tool is, and raises KeyError for the caller to turn
    into one.
    """
    tool = BY_NAME[name]
    if not _enabled(state, tool.feature):
        label = FEATURE_LABELS.get(tool.feature, tool.feature)
        return _error(f"{label} is switched off on this server")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return _error("arguments must be an object")
    try:
        result = tool.handler(state, user, arguments)
    except ToolError as exc:
        return _error(str(exc))
    except NoteConflictError as exc:
        return _error(
            "the note changed since it was read; read it again before writing."
            f" Its rev is now {exc.current_rev}"
        )
    except NoteNotFoundError as exc:
        return _error(f"no such note or folder: {exc}")
    except NoteExistsError as exc:
        return _error(f"already there: {exc}")
    except (LookupError, ValueError, FileExistsError, UnsafePathError) as exc:
        return _error(str(exc) or exc.__class__.__name__)
    text = result if isinstance(result, str) else json.dumps(result, indent=2, ensure_ascii=False)
    answer: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if isinstance(result, dict):
        answer["structuredContent"] = result
    return answer


def _error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}
