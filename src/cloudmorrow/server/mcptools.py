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
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cloudmorrow.paths import UnsafePathError
from cloudmorrow.quill_reference import quill_reference
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState
from cloudmorrow.server.notes import (
    NoteConflictError,
    NoteExistsError,
    NoteNode,
    NoteNotFoundError,
    NoteStore,
)
from cloudmorrow.server.quills import QuillError, load_catalog
from cloudmorrow.server.records import (
    NEVER_FOR_ASSISTANTS,
    Principal,
    RecordConflictError,
    Refused,
)
from cloudmorrow.server.routes.records import seed

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


# -- records, of any installed datamodel ---------------------------------------
def _principal(user: User) -> Principal:
    return Principal.assistant(user.username, admin=user.is_admin)


def _model(state: AppState, args: dict[str, Any]) -> str:
    """The datamodel asked for, if it is installed and some Quill using it is on."""
    model = _str(args, "model", required=True).strip()
    if model not in state.quills.datamodels:
        known = ", ".join(sorted(state.quills.datamodels)) or "none"
        raise ToolError(f"no datamodel {model!r}; there are: {known}")
    users = state.quills.users_of(model)
    if users and not any(_enabled(state, quill) for quill in users):
        raise ToolError(f"{model} belongs to Quills that are switched off on this server")
    return model


def _fields(args: dict[str, Any]) -> dict[str, Any]:
    fields = args.get("fields", {})
    if not isinstance(fields, dict):
        raise ToolError("fields must be an object of field name to value")
    return fields


def list_datamodels(state: AppState, user: User, args: dict[str, Any]) -> Any:
    return {
        "datamodels": [
            row for row in state.quills.catalogue_of_models() if row["id"] not in NEVER_FOR_ASSISTANTS
        ]
    }


def list_records(state: AppState, user: User, args: dict[str, Any]) -> Any:
    model = _model(state, args)
    where = args.get("where", {})
    if not isinstance(where, dict):
        raise ToolError("where must be an object of indexed field to value")
    where = dict(where)
    if args.get("q"):
        where["q"] = _str(args, "q")
    principal = _principal(user)
    seed(state, principal, model)
    return {"records": [r.to_dict() for r in state.records.list(principal, model, where)]}


def get_record(state: AppState, user: User, args: dict[str, Any]) -> Any:
    return state.records.get(_principal(user), _model(state, args), _str(args, "id", required=True)).to_dict()


def create_record(state: AppState, user: User, args: dict[str, Any]) -> Any:
    return state.records.create(
        _principal(user), _model(state, args), _fields(args), index=_int(args, "index")
    ).to_dict()


def update_record(state: AppState, user: User, args: dict[str, Any]) -> Any:
    return state.records.update(
        _principal(user), _model(state, args), _str(args, "id", required=True), _fields(args),
        rev=_rev(args),
    ).to_dict()


def move_record(state: AppState, user: User, args: dict[str, Any]) -> Any:
    return state.records.move(
        _principal(user), _model(state, args), _str(args, "id", required=True), _fields(args),
        _int(args, "index"),
    ).to_dict()


def delete_record(state: AppState, user: User, args: dict[str, Any]) -> Any:
    model = _model(state, args)
    record_id = _str(args, "id", required=True)
    gone = state.records.delete(_principal(user), model, record_id)
    return {"id": record_id, "deleted": gone}


def _rev(args: dict[str, Any]) -> int | str | None:
    """A record's rev: a whole number, or a note's string."""
    value = args.get("rev")
    if value is None or isinstance(value, int | str) and not isinstance(value, bool):
        return value
    raise ToolError("rev is the rev get_record gave")


# -- building Quills, for an administrator's assistant -------------------------
def _admin(user: User) -> None:
    if not user.is_admin:
        raise ToolError("only an administrator's assistant may build Quills")


def quill_schema(state: AppState, user: User, args: dict[str, Any]) -> Any:
    return {
        "reference": quill_reference(),
        "datamodels": state.quills.catalogue_of_models(),
        "installed": sorted(state.quills.quills),
    }


def _write_draft(state: AppState, args: dict[str, Any], folder: Path) -> Path:
    manifest = _str(args, "manifest", required=True)
    extra = args.get("datamodels", {})
    if not isinstance(extra, dict) or not all(isinstance(v, str) for v in extra.values()):
        raise ToolError("datamodels is an object of file name to TOML text")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "quill.toml").write_text(manifest, encoding="utf-8")
    if extra:
        (folder / "datamodels").mkdir(exist_ok=True)
        for name, text in extra.items():
            stem = Path(name).stem
            if not stem.replace("_", "").replace(".", "").isalnum():
                raise ToolError(f"{name!r} is not a datamodel file name")
            (folder / "datamodels" / f"{stem}.toml").write_text(text, encoding="utf-8")
    return folder


def _datamodels_for(state: AppState, tmp: Path) -> Path | None:
    try:
        return state.quills.datamodels_source(load_catalog(state.config.quill_catalog), tmp / "m")
    except QuillError:
        return None


def quill_check(state: AppState, user: User, args: dict[str, Any]) -> Any:
    _admin(user)
    with tempfile.TemporaryDirectory(prefix="quill-") as tmp:
        folder = _write_draft(state, args, Path(tmp) / "q")
        try:
            return {"ok": True, "adds": state.quills.plan(folder, _datamodels_for(state, Path(tmp)))}
        except QuillError as exc:
            raise ToolError(f"not yet: {exc}") from exc


def quill_dev_install(state: AppState, user: User, args: dict[str, Any]) -> Any:
    _admin(user)
    with tempfile.TemporaryDirectory(prefix="quill-") as tmp:
        folder = _write_draft(state, args, Path(tmp) / "q")
        try:
            plan = state.quills.install(
                folder, _datamodels_for(state, Path(tmp)), origin={"catalog": False, "dev": True, "by": "assistant"}
            )
        except QuillError as exc:
            raise ToolError(f"not installed: {exc}") from exc
    return {"installed": plan["id"], "version": plan["version"], "adds": plan}


# -- the catalogue ------------------------------------------------------------
_PATH = {
    "type": "string",
    "description": "Path under the notes root, e.g. 'ideas/garden.md'. The .md suffix is optional.",
}
_MODEL = {"type": "string", "description": "A datamodel id from list_datamodels, e.g. 'task'."}
_RECORD_ID = {"type": "string", "description": "The record's id, e.g. 'r_1a2b3c4d5e'."}
_FIELDS = {"type": "object", "description": "Field name to value, as list_datamodels describes them."}
_MANIFEST = {"type": "string", "description": "The quill.toml, as TOML text."}
_DATAMODELS = {
    "type": "object",
    "description": "Datamodels the Quill introduces: file name to TOML text. Optional.",
}

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
        "list_datamodels",
        "List the kinds of data on this server (tasks, boards, and whatever Quills added), "
        "with their fields, which are indexed (filterable), and which Quills use each.",
        _schema({}),
        "",
        list_datamodels,
    ),
    Tool(
        "list_records",
        "List the user's records of one datamodel, in order. Filter with `where` on indexed "
        "fields, e.g. {\"board\": \"r_…\", \"lane\": \"todo\"}; search their text with `q` "
        "(a found record's `preview` is the line that matched).",
        _schema({"model": _MODEL, "where": {"type": "object", "description": "Indexed field to value."},
                 "q": {"type": "string", "description": "Text to search for. Optional."}},
                ("model",)),
        "",
        list_records,
    ),
    Tool(
        "get_record",
        "Read one record: its fields and its rev.",
        _schema({"model": _MODEL, "id": _RECORD_ID}, ("model", "id")),
        "",
        get_record,
    ),
    Tool(
        "create_record",
        "Make a record of a datamodel from its fields. Links are record ids.",
        _schema({"model": _MODEL, "fields": _FIELDS,
                 "index": {"type": "integer", "description": "Place in its group; the end when left out."}},
                ("model", "fields")),
        "",
        create_record,
    ),
    Tool(
        "update_record",
        "Change some fields of a record. Pass the rev you read so a change made elsewhere "
        "is not overwritten.",
        _schema({"model": _MODEL, "id": _RECORD_ID, "fields": _FIELDS,
                 "rev": {"type": ["integer", "string"], "description": "The rev from get_record. Optional."}},
                ("model", "id", "fields")),
        "",
        update_record,
    ),
    Tool(
        "move_record",
        "Move a record to another group (a task to another lane: {\"lane\": \"done\"}) and/or "
        "to a place in it. Done tasks are swept away after a week.",
        _schema({"model": _MODEL, "id": _RECORD_ID, "fields": _FIELDS,
                 "index": {"type": "integer", "description": "0 for the top; the end when left out."}},
                ("model", "id")),
        "",
        move_record,
    ),
    Tool(
        "delete_record",
        "Delete a record for good, and what cascades from it (a board takes its tasks).",
        _schema({"model": _MODEL, "id": _RECORD_ID}, ("model", "id")),
        "",
        delete_record,
    ),
    Tool(
        "quill_schema",
        "For building a Quill (a Cloudmorrow app): the manifest format, the screen kit, "
        "field kinds, and the datamodels already on this server. Read this first.",
        _schema({}),
        "",
        quill_schema,
    ),
    Tool(
        "quill_check",
        "Check a Quill manifest (and any datamodels it introduces) without installing it, "
        "and say everything it would add. Administrators only.",
        _schema({"manifest": _MANIFEST, "datamodels": _DATAMODELS}, ("manifest",)),
        "",
        quill_check,
    ),
    Tool(
        "quill_dev_install",
        "Install a Quill from a manifest on this server, as a development Quill: it is on the "
        "phone, the web app and the terminal at once. Installing again replaces it. "
        "Administrators only; check it first.",
        _schema({"manifest": _MANIFEST, "datamodels": _DATAMODELS}, ("manifest",)),
        "",
        quill_dev_install,
    ),
)

BY_NAME: dict[str, Tool] = {tool.name: tool for tool in TOOLS}

INSTRUCTIONS = (
    "Cloudmorrow is the user's own cloud: Markdown notes in folders, and records of "
    "datamodels the installed Quills use — task boards with todo/doing/done lanes, and "
    "whatever else is installed (list_datamodels says). Everything here is the signed-in "
    "user's own data. Read before you overwrite, and prefer append_to_note and "
    "move_record over rewriting or deleting. To build a new Quill, read quill_schema first."
)


FEATURE_LABELS = {"notes": "Notes"}


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
    except RecordConflictError as exc:
        return _error(
            f"the record changed since it was read; its rev is now {exc.current.rev}. Read it again."
        )
    except Refused as exc:
        return _error(f"not allowed: {exc}")
    except (LookupError, ValueError, FileExistsError, UnsafePathError) as exc:
        return _error(str(exc) or exc.__class__.__name__)
    text = result if isinstance(result, str) else json.dumps(result, indent=2, ensure_ascii=False)
    answer: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if isinstance(result, dict):
        answer["structuredContent"] = result
    return answer


def _error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}
