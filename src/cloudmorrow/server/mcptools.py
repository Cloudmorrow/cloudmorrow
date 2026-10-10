"""What an assistant can do in Cloudmorrow: the MCP tools.

Each tool is one thing a person could do themselves in the app — read a
page, add a task, move it along — described plainly enough that a model
picks the right one, and done with the same record store the API uses, as
the signed-in user and nobody else, through the same gate. Notes are
files: an assistant reads and writes them as `file` records, the way every
Quill does.

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

from cloudmorrow.quill_reference import quill_reference
from cloudmorrow.server.circles import Access
from cloudmorrow.server.db import User
from cloudmorrow.server.paths import UnsafePathError
from cloudmorrow.server.quills import QuillError, load_catalog
from cloudmorrow.server.records import (
    NEVER_FOR_ASSISTANTS,
    Principal,
    RecordConflictError,
    Refused,
)
from cloudmorrow.server.seeding import seed
from cloudmorrow.server.state import AppState

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


def _principal(user: User) -> Principal:
    return Principal.assistant(user.username, admin=user.is_admin)


def _model(state: AppState, args: dict[str, Any]) -> str:
    """The datamodel asked for, if it is installed and some Quill using it is on."""
    model = _str(args, "model", required=True).strip()
    if model not in state.quills.datamodels:
        known = ", ".join(sorted(set(state.quills.datamodels) - NEVER_FOR_ASSISTANTS)) or "none"
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


def _access(state: AppState, user: User) -> Access | None:
    shelf = getattr(state, "shelf", None) or getattr(state, "circles", None)
    return shelf.access_for(user.username) if shelf is not None else None


def list_datamodels(state: AppState, user: User, args: dict[str, Any]) -> Any:
    """What the person may reach, with what they may do with each: their circles decide."""
    access = _access(state, user)
    rows = []
    for row in state.quills.catalogue_of_models():
        if row["id"] in NEVER_FOR_ASSISTANTS:
            continue
        if access is not None:
            if not access.may("read", row["id"]):
                continue
            row["access"] = access.level(row["id"])
        rows.append(row)
    return {"datamodels": rows}


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
    listed = state.records.list(principal, model, where, last=_int(args, "last"))
    return {"records": [r.to_dict() for r in listed]}


def get_record(state: AppState, user: User, args: dict[str, Any]) -> Any:
    return state.records.get(_principal(user), _model(state, args), _str(args, "id", required=True)).to_dict()


def get_record_history(state: AppState, user: User, args: dict[str, Any]) -> Any:
    lines = state.records.history(_principal(user), _model(state, args), _str(args, "id", required=True))
    return {"history": lines}


def create_record(state: AppState, user: User, args: dict[str, Any]) -> Any:
    members = args.get("members") or []
    if not isinstance(members, list) or not all(isinstance(m, str) for m in members):
        raise ToolError("members is a list of usernames")
    for username in members:
        if state.users.get(username) is None:
            raise ToolError(f"no such account: {username}")
    return state.records.create(
        _principal(user),
        _model(state, args),
        _fields(args),
        index=_int(args, "index"),
        scope=_str(args, "scope") or None,
        members=members,
    ).to_dict()


def update_record(state: AppState, user: User, args: dict[str, Any]) -> Any:
    return state.records.update(
        _principal(user),
        _model(state, args),
        _str(args, "id", required=True),
        _fields(args),
        rev=_rev(args),
    ).to_dict()


def move_record(state: AppState, user: User, args: dict[str, Any]) -> Any:
    return state.records.move(
        _principal(user),
        _model(state, args),
        _str(args, "id", required=True),
        _fields(args),
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


# -- building Quills: an administrator's for the server, anybody's for themselves --------
def _builds_for(state: AppState, user: User) -> str:
    """Whose the Quill an assistant builds will be: "" for the server's (an administrator's
    assistant), the person's own name for one of their own (docs/SHARING.md), or refused."""
    if user.is_admin:
        return ""
    policy = getattr(state, "policy", None)
    if policy is None or not policy.may_install():
        if policy is not None and policy.may_have():
            raise ToolError(
                "on this server a Quill of your own comes through a request: quill_request asks an administrator"
            )
        raise ToolError("only an administrator's assistant may build Quills on this server")
    return user.username


def _personal_allowed(state: AppState, plan: dict) -> None:
    policy = getattr(state, "policy", None)
    if plan.get("code") and policy is not None and not policy.may_code():
        raise ToolError("Quills of your own may not run code on this server; leave the code out")


def quill_schema(state: AppState, user: User, args: dict[str, Any]) -> Any:
    shelf = getattr(state, "shelf", None)
    mine = sorted(shelf.for_user(user.username)) if shelf is not None else sorted(state.quills.quills)
    rows = state.quills.catalogue_of_models()
    access = _access(state, user)
    if access is not None:
        rows = [row for row in rows if access.may("read", row["id"])]
    return {
        "reference": quill_reference(),
        "datamodels": rows,
        "installed": mine,
        "builds": "the server's" if user.is_admin else f"{user.username}'s own",
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
    owner = _builds_for(state, user)
    with tempfile.TemporaryDirectory(prefix="quill-") as tmp:
        folder = _write_draft(state, args, Path(tmp) / "q")
        try:
            plan = state.quills.plan(folder, _datamodels_for(state, Path(tmp)), owner=owner)
        except QuillError as exc:
            raise ToolError(f"not yet: {exc}") from exc
        if owner:
            _personal_allowed(state, plan)
        return {"ok": True, "adds": plan, "whose": owner or "the server's"}


def quill_dev_install(state: AppState, user: User, args: dict[str, Any]) -> Any:
    owner = _builds_for(state, user)
    with tempfile.TemporaryDirectory(prefix="quill-") as tmp:
        folder = _write_draft(state, args, Path(tmp) / "q")
        try:
            source = _datamodels_for(state, Path(tmp))
            if owner:
                _personal_allowed(state, state.quills.plan(folder, source, owner=owner))
            plan = state.quills.install(
                folder,
                source,
                origin={"catalog": False, "dev": True, "by": "assistant", "installed_by": user.username},
                owner=owner,
            )
        except QuillError as exc:
            raise ToolError(f"not installed: {exc}") from exc
    return {"installed": plan["id"], "version": plan["version"], "whose": owner or "the server's", "adds": plan}


def quill_mine(state: AppState, user: User, args: dict[str, Any]) -> Any:
    """Your own Quills and who has them, what you were offered, what you asked for."""
    sharing = getattr(state, "sharing", None)
    if sharing is None:
        raise ToolError("this server keeps no shelves")
    own = state.quills.personal.get(user.username, {})
    return {
        "quills": [
            {
                "id": m.id,
                "name": m.name,
                "version": m.version,
                "summary": m.summary,
                "shared_with": sharing.shared_with(user.username, m.id),
            }
            for m in own.values()
        ],
        "offers": sharing.of_person(user.username),
        "requests": sharing.requests(username=user.username, open_only=False),
        "policy": state.policy.get() if getattr(state, "policy", None) else {},
    }


def quill_share(state: AppState, user: User, args: dict[str, Any]) -> Any:
    """Offer a Quill of the person's own to people; each says yes themselves."""
    sharing, policy = getattr(state, "sharing", None), getattr(state, "policy", None)
    if sharing is None or policy is None:
        raise ToolError("this server keeps no shelves")
    quill_id = _str(args, "quill", required=True).strip()
    if quill_id not in state.quills.personal.get(user.username, {}):
        raise ToolError(f"{user.username} has no Quill of their own called {quill_id}")
    if not policy.may_share():
        raise ToolError("sharing Quills of your own is switched off on this server")
    people = args.get("people")
    if not isinstance(people, list) or not all(isinstance(p, str) for p in people) or not people:
        raise ToolError("people is a list of usernames")
    known = {u.username for u in state.users.list() if u.is_active}
    unknown = sorted(set(people) - known)
    if unknown:
        raise ToolError(f"no such account: {', '.join(unknown)}")
    manifest = state.quills.personal[user.username][quill_id]
    for who in people:
        if who == user.username:
            continue
        from cloudmorrow.server.quills.sharing import OFFERED, SharingError

        try:
            share = sharing.offer(user.username, quill_id, who, by=user.username)
        except SharingError as exc:
            raise ToolError(str(exc)) from exc
        if share["state"] == OFFERED:
            state.notifications.add(
                who,
                kind="quill.offered",
                title=f"{user.display_name or user.username} shared {manifest.name} with you",
                body="Say yes under Me, Your Quills, and it is on your shelf, over your own data.",
            )
    return {"shared_with": sharing.shared_with(user.username, quill_id)}


def quill_request(state: AppState, user: User, args: dict[str, Any]) -> Any:
    """Ask an administrator for a Quill: from the catalog or a source, or one of the person's own promoted."""
    sharing = getattr(state, "sharing", None)
    if sharing is None:
        raise ToolError("this server keeps no shelves")
    from cloudmorrow.server.quills.sharing import SharingError

    kind = _str(args, "kind", default="install")
    quill_id = _str(args, "quill").strip()
    if kind == "promote" and quill_id not in state.quills.personal.get(user.username, {}):
        raise ToolError(f"{user.username} has no Quill of their own called {quill_id}")
    try:
        made = sharing.ask(
            user.username,
            kind,
            quill=quill_id,
            source=_str(args, "source"),
            ref=_str(args, "ref"),
            note=_str(args, "note"),
        )
    except SharingError as exc:
        raise ToolError(str(exc)) from exc
    for admin in (u for u in state.users.list() if u.is_admin and u.is_active and u.username != user.username):
        state.notifications.add(
            admin.username,
            kind="quill.requested",
            title=f"{user.display_name or user.username} asks for {quill_id or _str(args, 'source')}"
            + (" to be promoted" if kind == "promote" else ""),
            body=_str(args, "note") or "Under Administration, Quills.",
        )
    return made


# -- the catalogue ------------------------------------------------------------
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
        'fields, e.g. {"board": "r_…", "lane": "todo"}; `name__lt`, `__lte`, `__gt`, '
        '`__gte` are ranges, e.g. the events in October: {"starts_at__lte": '
        '"2026-10-31T23:59", "ends_at__gte": "2026-10-01"}. A datetime without a zone is '
        "the wall clock; a bare date is a whole day. Search their text with `q` "
        "(a found record's `preview` is the line that matched).",
        _schema(
            {
                "model": _MODEL,
                "where": {"type": "object", "description": "Indexed field to value."},
                "q": {"type": "string", "description": "Text to search for. Optional."},
                "last": {"type": "integer", "description": "Only the newest this many, e.g. of a conversation."},
            },
            ("model",),
        ),
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
        "get_record_history",
        "Who did what to one record, newest first: who, when, what was done, and which "
        "fields it touched — never a value. The record itself says what they are now.",
        _schema({"model": _MODEL, "id": _RECORD_ID}, ("model", "id")),
        "",
        get_record_history,
    ),
    Tool(
        "create_record",
        "Make a record of a datamodel from its fields. Links are record ids. A space (a channel, "
        "a calendar) takes a scope, and a shared one the people in it besides you.",
        _schema(
            {
                "model": _MODEL,
                "fields": _FIELDS,
                "index": {"type": "integer", "description": "Place in its group; the end when left out."},
                "scope": {"type": "string", "description": "For a space: personal, shared or public."},
                "members": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For a shared space: usernames to put in it.",
                },
            },
            ("model", "fields"),
        ),
        "",
        create_record,
    ),
    Tool(
        "update_record",
        "Change some fields of a record. Pass the rev you read so a change made elsewhere is not overwritten.",
        _schema(
            {
                "model": _MODEL,
                "id": _RECORD_ID,
                "fields": _FIELDS,
                "rev": {"type": ["integer", "string"], "description": "The rev from get_record. Optional."},
            },
            ("model", "id", "fields"),
        ),
        "",
        update_record,
    ),
    Tool(
        "move_record",
        'Move a record to another group (a task to another lane: {"lane": "done"}) and/or '
        "to a place in it. Done tasks are swept away after a week.",
        _schema(
            {
                "model": _MODEL,
                "id": _RECORD_ID,
                "fields": _FIELDS,
                "index": {"type": "integer", "description": "0 for the top; the end when left out."},
            },
            ("model", "id"),
        ),
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
        "and say everything it would add. For an administrator the Quill is the server's; for "
        "anybody else it is their own: on their shelf alone, over their own data, with no fields "
        "added to shared datamodels, no services, and personal-scope datamodels only.",
        _schema({"manifest": _MANIFEST, "datamodels": _DATAMODELS}, ("manifest",)),
        "",
        quill_check,
    ),
    Tool(
        "quill_dev_install",
        "Install a Quill from a manifest on this server, as a development Quill: it is on the "
        "phone, the web app and the terminal at once. Installing again replaces it. An "
        "administrator's is the server's; anybody else's is a Quill of their own. Check it first.",
        _schema({"manifest": _MANIFEST, "datamodels": _DATAMODELS}, ("manifest",)),
        "",
        quill_dev_install,
    ),
    Tool(
        "quill_mine",
        "The user's own Quills and who has them, the Quills offered to them, and what they asked an administrator for.",
        _schema({}),
        "",
        quill_mine,
    ),
    Tool(
        "quill_share",
        "Offer one of the user's own Quills to people on this server. Each person says yes "
        "themselves; then it is on their shelf, over their own data, run as them.",
        _schema(
            {
                "quill": {"type": "string", "description": "The id of a Quill of the user's own."},
                "people": {"type": "array", "items": {"type": "string"}, "description": "Usernames."},
            },
            ("quill", "people"),
        ),
        "",
        quill_share,
    ),
    Tool(
        "quill_request",
        "Ask an administrator for a Quill: kind 'install' with a catalog id (quill) or a source "
        "repository, or kind 'promote' with the id of one of the user's own Quills, to be made "
        "the server's for everyone. Say why in note.",
        _schema(
            {
                "kind": {"type": "string", "enum": ["install", "promote"]},
                "quill": {"type": "string", "description": "A catalog id, or the user's own Quill's id."},
                "source": {"type": "string", "description": "A repository, instead of the catalog."},
                "ref": {"type": "string", "description": "Its release, e.g. v1.0.0."},
                "note": {"type": "string", "description": "Why, in a line."},
            },
        ),
        "",
        quill_request,
    ),
)

BY_NAME: dict[str, Tool] = {tool.name: tool for tool in TOOLS}

INSTRUCTIONS = (
    "Cloudmorrow is the user's own cloud: records of the datamodels the installed Quills "
    "use — task boards with todo/doing/done lanes, contacts, calendars, files, and whatever "
    "else is installed (list_datamodels says). Everything here is the signed-in user's own "
    "data. Their notes are Markdown files in the Notes folder of their drive: list them "
    'with list_records on the \'file\' datamodel and where {"share": "my-files", '
    '"within": "Notes", "suffix": ".md"}; a file\'s words are its \'text\' when '
    "read one at a time with get_record, and written back with update_record and its rev. "
    "Read before you overwrite, and prefer move_record over rewriting or deleting. To build "
    "a new Quill, read quill_schema first: an administrator's assistant builds the server's, "
    "anybody else's builds one of their own, on their shelf alone (quill_share offers it to "
    "others; quill_request asks an administrator for more)."
)


FEATURE_LABELS: dict[str, str] = {}


def _enabled(state: AppState, feature: str) -> bool:
    """Is *feature* switched on? A server without the switchboard has everything on."""
    switches = getattr(state, "features", None)
    return switches is None or switches.enabled(feature)


# -- a Quill's actions, as tools -------------------------------------------------------
# Every action a Quill declares is a tool too, named `<quill>_<action>`, with
# its form as the schema and, for an action on a datamodel, the record's id.
# The code runs as an assistant's: it reaches no datamodel an assistant may
# not, is given no secret, and an action marked `assistant = false` is not
# offered at all.
JSON_KIND = {
    "bool": {"type": "boolean"},
    "int": {"type": "integer"},
    "decimal": {"type": "number"},
    "json": {},
}


def _field_schema(spec: dict) -> dict[str, Any]:
    schema = dict(JSON_KIND.get(spec["kind"], {"type": "string"}))
    words = spec.get("label") or spec["name"]
    if spec["kind"] == "enum":
        schema["enum"] = list(spec["values"])
    elif spec["kind"] == "date":
        words += " (YYYY-MM-DD)"
    elif spec["kind"] == "datetime":
        words += " (ISO 8601; without a zone it is the wall clock)"
    elif spec["kind"] == "link":
        words += f" (the id of a {spec['to']} record)"
    schema["description"] = words
    return schema


def action_tool_name(quill_id: str, action_id: str) -> str:
    return f"{quill_id}_{action_id.replace('-', '_')}"


def _action_tool(state: AppState, manifest, action: dict) -> Tool:
    properties = {f["name"]: _field_schema(f) for f in action["fields"]}
    required = [f["name"] for f in action["fields"] if f.get("required")]
    if action.get("on"):
        properties = {
            "record": {"type": "string", "description": f"The id of the {action['on']} to do it to."}
        } | properties
        required = ["record", *required]
    description = f"{manifest.name}: {action['label']}."
    if action.get("description"):
        description += " " + action["description"]
    if action.get("on"):
        description += f" Done to one {action['on']} record."

    def handler(state: AppState, user: User, args: dict[str, Any], quill=manifest.id, act=action["id"]) -> Any:
        from cloudmorrow.server.quills.code import CodeError

        if state.code is None:
            raise ToolError("this server runs no Quill code")
        record = str(args.pop("record", "") or "")
        try:
            effects = state.code.action(user.username, quill, act, record=record, fields=args, via="assistant")
        except CodeError as exc:
            raise ToolError(exc.message) from exc
        said = [e["text"] for e in effects if e.get("effect") in ("toast", "error")]
        opened = [{"model": e["model"], "id": e["id"]} for e in effects if e.get("effect") == "open"]
        return {"done": True, "said": said, "opened": opened} if (said or opened) else {"done": True}

    return Tool(
        action_tool_name(manifest.id, action["id"]),
        description,
        _schema(properties, tuple(required)),
        manifest.key,
        handler,
    )


def action_tools(state: AppState, user: User | None = None) -> list[Tool]:
    quills = getattr(state, "quills", None)
    if quills is None or getattr(state, "code", None) is None:
        return []
    access = _access(state, user) if user is not None else None
    tools = []
    shelf = getattr(state, "shelf", None)
    manifests = (
        shelf.for_user(user.username).values() if (user is not None and shelf is not None) else quills.quills.values()
    )
    for manifest in manifests:
        if not manifest.code or not _enabled(state, manifest.key):
            continue
        for action in manifest.actions:
            on = action.get("on", "")
            if not action.get("assistant", True) or on in NEVER_FOR_ASSISTANTS:
                continue
            if on and access is not None and not access.may("read", on):
                continue
            tools.append(_action_tool(state, manifest, action))
    return tools


def find(state: AppState, name: str, user: User | None = None) -> Tool | None:
    """A tool by name: one of the fixed ones, or a Quill's action."""
    return BY_NAME.get(name) or next((t for t in action_tools(state, user) if t.name == name), None)


def available(state: AppState, user: User | None = None) -> list[Tool]:
    """The tools on offer right now: those whose feature is switched on, then
    every Quill's actions the person may use. What the record tools reach is
    the gate's business, as it is for everybody."""
    return [tool for tool in TOOLS if _enabled(state, tool.feature)] + action_tools(state, user)


def call(state: AppState, user: User, name: str, arguments: Any) -> dict[str, Any]:
    """Run a tool and shape the answer the way MCP wants it.

    A tool that could not do its job answers with `isError` and a plain
    sentence, so the model can say so or try again — that is not a protocol
    error. An unknown tool is, and raises KeyError for the caller to turn
    into one.
    """
    tool = find(state, name, user)
    if tool is None:
        raise KeyError(name)
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
    except RecordConflictError as exc:
        return _error(f"the record changed since it was read; its rev is now {exc.current.rev}. Read it again.")
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
