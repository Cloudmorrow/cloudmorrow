"""What a screen's bindings mean, for everything in Python that draws one.

The server checks a Quill's screens when it is installed (server/quills/
checks.py), so a screen that gets this far names its fields. What is left is
reading them the same way everywhere: which lane a board calls done, what a
space is called, which fields a calendar or a grid draws from. The terminal
app and the command line both ask here, so the two can never disagree about
it. The web app does the same in JavaScript (kit.js, kit_calendar.js); the
rules below are the ones it follows.

Nothing here draws or fetches: it takes records the caller already has.
"""

from __future__ import annotations

from typing import Any

# -- boards --------------------------------------------------------------------


def lane_filter(lane_model: dict, group_model_id: str, group_id: str | None) -> dict[str, str]:
    """Which lane records belong on a board with groups: those linked to the group shown.

    A board without groups, or lanes that do not link to the group's
    datamodel, shows every lane record.
    """
    if not group_model_id or not group_id:
        return {}
    by = next(
        (f["name"] for f in lane_model.get("fields", []) if f.get("kind") == "link" and f.get("to") == group_model_id),
        None,
    )
    return {by: group_id} if by else {}


def in_order(rows: list[dict]) -> list[dict]:
    """Lane records in the order they were put in."""
    return sorted(rows, key=lambda row: row.get("position") or 0)


def done_lane(screen: dict, lanes: list[tuple[str, str]], rows: list[dict] | None = None) -> str | None:
    """The lane a tick moves a card to.

    `done` names it: an enum value, or, when the lanes are records, the
    fields the finished one has. Said nowhere, or matching no lane, it is the
    last lane, as the web app has it.
    """
    done = screen.get("done")
    values = [value for value, _ in lanes]
    if isinstance(done, str) and done in values:
        return done
    if isinstance(done, dict) and rows:
        found = next(
            (row["id"] for row in rows if all((row.get("fields") or {}).get(k) == v for k, v in done.items())),
            None,
        )
        if found is not None:
            return found
    return values[-1] if values else None


# -- spaces --------------------------------------------------------------------


def made_as(screen: dict | None) -> dict[str, dict]:
    """How the screen says spaces are made: scope (or `direct`) → the fields it sets."""
    return dict((screen or {}).get("made_as") or {})


def is_between(screen: dict | None, space: dict | None) -> bool:
    """Is this a space made between people, named for whoever else is in it?"""
    marks = made_as(screen).get("direct") or {}
    fields = (space or {}).get("fields") or {}
    return bool(marks) and space is not None and all(fields.get(k) == v for k, v in marks.items())


def people_in(space: dict) -> list[str]:
    """Everybody in a space: its owner, then the people added to it."""
    return [space.get("owner", ""), *(space.get("members") or [])]


def space_name(space: dict, title: str, screen: dict | None, me: str) -> str:
    """What a space is called, to whoever is looking.

    One made between people is called by the others in it; any other by its
    *title* field, or Untitled.
    """
    if is_between(screen, space):
        others = [who for who in people_in(space) if who != me]
        return ", ".join(others) or me
    fields = space.get("fields") or {}
    return str(fields.get(title or "name") or "").strip() or "Untitled"


# -- calendars and grids -------------------------------------------------------


def _field(model: dict, name: Any) -> dict:
    return next((f for f in model.get("fields", []) if f.get("name") == name), {})


def calendar_fields(screen: dict, model: dict) -> dict[str, str]:
    """The fields a calendar draws from: its two moments, the space, and the rest."""
    return {
        "starts": screen.get("starts") or "starts",
        "ends": screen.get("ends") or "ends",
        "all_day": screen.get("all_day") or "",
        "space": _field(model, screen.get("space")).get("name") or "",
        "colour": screen.get("colour") or "",
        "title": screen.get("title") or model.get("title") or "title",
        "subtitle": screen.get("subtitle") or "",
    }


def grid_fields(screen: dict, model: dict) -> dict[str, str]:
    """The fields a grid of files draws from."""
    return {
        "title": screen.get("title") or model.get("title") or "name",
        "folder": screen.get("folder") or "folder",
        "kind": screen.get("kind") or "kind",
        "size": screen.get("size") or "",
        "modified": screen.get("modified") or "",
        "mime": screen.get("mime") or "",
        "subtitle": screen.get("group_subtitle") or "",
    }


# -- editors -------------------------------------------------------------------
# A screen binds a title, a body and, when the pages sit in folders, a path.
# `where` is the filters every listing, search and folder call is made with
# — a file's `share`, and `within`, the folder the pages are under — and
# `suffix` says which files are pages and what a new one is called. The
# tree shows paths under the root and without the suffix; the record store
# keeps them whole. The web app does the same in kit_editor.js.


def editor_fields(screen: dict, model: dict) -> dict:
    """What an editor draws from, and the filters and root it works within."""
    where = {str(k): str(v) for k, v in (screen.get("where") or {}).items()}
    return {
        "title": screen.get("title") or model.get("title") or "title",
        "body": screen.get("body") or "body",
        "path": screen.get("path") or "",
        "where": where,
        "root": where.get("within", "").strip("/"),
        "suffix": str(screen.get("suffix") or ""),
        "fields": {f.get("name") for f in model.get("fields", [])},
    }


def listing_filters(bound: dict) -> dict[str, str]:
    """What every listing, search and folder call sends: `where`, and the suffix."""
    filters = dict(bound["where"])
    if bound["suffix"]:
        filters["suffix"] = bound["suffix"]
    return filters


def under_root(bound: dict, raw: str) -> str:
    """*raw* as the tree shows it: under the root, or "" for the root itself."""
    path = str(raw or "").strip("/")
    root = bound["root"]
    if root and path.startswith(root + "/"):
        return path[len(root) + 1 :]
    if root and path == root:
        return ""
    return path


def _without_suffix(bound: dict, text: str) -> str:
    suffix = bound["suffix"]
    return text[: -len(suffix)] if suffix and text.lower().endswith(suffix.lower()) else text


def page_path(bound: dict, record: dict) -> str:
    """A page's path in the tree: under the root, without the suffix."""
    fields = record.get("fields") or {}
    return _without_suffix(bound, under_root(bound, str(fields.get(bound["path"] or bound["title"]) or "")))


def page_title(bound: dict, record: dict) -> str:
    fields = record.get("fields") or {}
    return _without_suffix(bound, str(fields.get(bound["title"]) or "")) or page_path(bound, record).rsplit("/", 1)[-1]


def whole_path(bound: dict, path: str) -> str:
    """A tree path as the record store keeps it: under the root, with the suffix."""
    path = str(path or "").strip("/")
    if bound["suffix"] and not path.lower().endswith(bound["suffix"].lower()):
        path += bound["suffix"]
    return f"{bound['root']}/{path}" if bound["root"] else path


def whole_folder(bound: dict, path: str) -> str:
    """A tree folder as the record store keeps it: under the root."""
    path = str(path or "").strip("/")
    if not bound["root"]:
        return path
    return f"{bound['root']}/{path}" if path else bound["root"]


def page_fields(bound: dict, path: str) -> dict:
    """What a page at tree *path* is written as: its path (or its title alone),
    and the filters that are fields of the datamodel — a file's share."""
    fields = {k: v for k, v in bound["where"].items() if k in bound["fields"]}
    if bound["path"]:
        fields[bound["path"]] = whole_path(bound, path)
    else:
        name = path.rsplit("/", 1)[-1]
        fields[bound["title"]] = whole_path(bound, name) if not bound["root"] else name + bound["suffix"]
    return fields


# -- a record's history --------------------------------------------------------


def history_said(line: dict, model: dict, me: str = "") -> str:
    """One line of a record's history in words: `you changed phone and notes`,
    `bram made it`, `the tasks Quill moved it`. Never a value."""
    who = str(line.get("by") or "somebody")
    kind = str(line.get("by_kind") or "person")
    if kind == "person":
        who = "you" if me and who == me else who
    elif kind in ("quill", "dataset"):
        who = f"the {who} Quill"
    elif kind == "assistant":
        who = f"an assistant, as {who}"
    labels = {f.get("name"): str(f.get("label") or f.get("name")) for f in model.get("fields", [])}
    names = [labels.get(n, str(n)) for n in line.get("fields") or []]
    action = str(line.get("action") or "changed")
    if action == "created":
        what = "made it"
    elif action == "deleted":
        what = "deleted it"
    elif action == "expired":
        what = "let it expire"
    elif action == "moved" and not names:
        what = "moved it"
    elif names:
        joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        what = f"changed {joined.lower()}"
    else:
        what = "changed it"
    return f"{who} {what}"
