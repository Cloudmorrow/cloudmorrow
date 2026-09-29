"""The primitives a view is made of. Every surface draws every one of them.

A view returns a tree of these — plain dicts, `{"ui": "stack", ...}` — and
the phone, the web app and the terminal each draw it their own way. There is
nothing else a view can return, and nothing per surface to write: when the
primitives cannot say something, they grow, for every surface at once.

    ui.stack(
        ui.text("Garage", style="title"),
        ui.row(ui.stat("Vans", 3), ui.stat("Due", 1, tone="warn")),
        ui.table(vans, columns=["name", ("Odometer", "fleet.odometer")]),
        ui.button("Log a service", action="log-service", tone="primary"),
    )

What can be pressed runs an action the manifest declares, opens a record, or
goes to another screen of the Quill. A `lanes` card dragged to another lane
is moved through the record API, as a board's card is.

`check(tree)` is what the core runs on every tree a view returns, before a
surface sees it.
"""

from __future__ import annotations

__all__ = [
    "CONTAINERS",
    "GAPS",
    "PRIMITIVES",
    "TONES",
    "badge",
    "button",
    "cards",
    "check",
    "children",
    "columns",
    "divider",
    "empty",
    "field",
    "form",
    "image",
    "lanes",
    "markdown",
    "menu",
    "month",
    "row",
    "stack",
    "stat",
    "table",
    "tabs",
    "text",
]

TONES = ("neutral", "info", "good", "warn", "bad", "primary", "danger")
TEXT_STYLES = ("body", "title", "subtitle", "muted", "small", "mono")
GAPS = ("none", "small", "normal", "large")
MAX_TEXT = 20_000
MAX_NODES = 5_000
MAX_DEPTH = 24


class TreeError(ValueError):
    """A view returned something the surfaces cannot draw."""


# -- building --------------------------------------------------------------------
def _record(value) -> dict:
    """A record for a tree: its id, datamodel, fields and revision."""
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if not isinstance(value, dict) or "id" not in value or "model" not in value:
        raise TreeError(f"{value!r} is not a record")
    return {
        "id": value["id"],
        "model": value["model"],
        "rev": value.get("rev"),
        "fields": dict(value.get("fields", {})),
    }


def _records(values) -> list[dict]:
    return [_record(v) for v in values]


def _node(kind: str, **props) -> dict:
    return {"ui": kind, **{k: v for k, v in props.items() if v is not None}}


def _children(items) -> list[dict]:
    out = []
    for item in items:
        if item is None or item is False:
            continue  # so `cond and ui.text(...)` reads naturally
        if isinstance(item, list | tuple):
            out.extend(_children(item))
        elif isinstance(item, str):
            out.append(text(item))
        else:
            out.append(item)
    return out


def stack(*children, gap: str = "normal") -> dict:
    """Things one under another; *gap* between them is none, small, normal or large."""
    return _node("stack", children=_children(children), gap=gap)


def row(*children, wrap: bool = True) -> dict:
    """Things side by side; they wrap on a narrow screen."""
    return _node("row", children=_children(children), wrap=wrap)


def columns(*children) -> dict:
    """Two or three columns on a wide screen, one under another on a phone."""
    return _node("columns", children=_children(children))


def tabs(*pairs, **named) -> dict:
    """`tabs(("Open", tree), ("Done", tree))`, or `tabs(Open=tree, Done=tree)`."""
    items = list(pairs) + list(named.items())
    return _node("tabs", tabs=[{"label": str(label), "child": child} for label, child in items])


def text(value, *, style: str = "body") -> dict:
    return _node("text", text=str(value), style=style)


def markdown(value: str) -> dict:
    return _node("markdown", text=str(value))


def image(src: str = "", *, record=None, alt: str = "") -> dict:
    """A picture: a record with content (a file), or an https address."""
    if record is not None:
        rec = _record(record)
        return _node("image", model=rec["model"], id=rec["id"], alt=alt)
    return _node("image", src=src, alt=alt)


def badge(value, *, tone: str = "neutral") -> dict:
    return _node("badge", text=str(value), tone=tone)


def stat(label: str, value, *, hint: str | None = None, tone: str = "neutral") -> dict:
    """A number with a label: "Vans 3"."""
    return _node("stat", label=str(label), value=str(value), hint=hint, tone=tone)


def empty(value: str, *, action: str | None = None, label: str | None = None) -> dict:
    """What a list says when there is nothing in it, and what to do about it."""
    return _node("empty", text=str(value), action=action, label=label)


def divider() -> dict:
    return _node("divider")


def field(record, name: str, *, label: str | None = None, edit: bool = False) -> dict:
    """One field of a record, with its kind's widget; `edit=True` saves as it changes."""
    return _node("field", record=_record(record), name=name, label=label, edit=edit)


def form(action: str, *, values: dict | None = None, record=None, submit: str | None = None) -> dict:
    """The action's form, drawn in place, filled with *values*; submitting runs it."""
    return _node(
        "form",
        action=action,
        values=dict(values or {}),
        record=_record(record) if record is not None else None,
        submit=submit,
    )


def button(
    label: str,
    *,
    action: str | None = None,
    record=None,
    args: dict | None = None,
    open=None,  # noqa: A002 - reads as what it does
    go: str | None = None,
    params: dict | None = None,
    tone: str = "neutral",
) -> dict:
    """Runs an action (with its form, when it has fields), opens a record, or goes to a screen."""
    if sum(x is not None for x in (action, open, go)) != 1:
        raise TreeError(f"button {label!r} does one thing: action=, open= or go=")
    return _node(
        "button",
        label=str(label),
        action=action,
        record=_record(record) if record is not None else None,
        args=dict(args) if args else None,
        open=_record(open) if open is not None else None,
        go=go,
        params=dict(params) if params else None,
        tone=tone,
    )


def menu(label: str, *buttons) -> dict:
    return _node("menu", label=str(label), items=_children(buttons))


def _columns(cols) -> list[dict]:
    out = []
    for col in cols:
        if isinstance(col, str):
            out.append({"field": col})
        elif isinstance(col, tuple | list) and len(col) == 2:
            out.append({"label": str(col[0]), "field": str(col[1])})
        else:
            raise TreeError(f"a column is a field name or (label, field): {col!r}")
    return out


def table(records, *, columns, open: bool = True, actions=(), empty: str = "") -> dict:  # noqa: A002
    """Records, a row each. Opening a row shows its sheet; *actions* are ids, per row."""
    return _node(
        "table",
        records=_records(records),
        columns=_columns(columns),
        open=open,
        actions=list(actions),
        empty=empty,
    )


def cards(
    records,
    *,
    title: str,
    subtitle: str | None = None,
    body: str | None = None,
    badge: str | None = None,
    open: bool = True,  # noqa: A002
    empty: str = "",
) -> dict:
    """Records, a card each: *title*, *subtitle*, *body* and *badge* are field names."""
    return _node(
        "cards",
        records=_records(records),
        title=title,
        subtitle=subtitle,
        body=body,
        badge=badge,
        open=open,
        empty=empty,
    )


def lanes(
    records, *, field: str, title: str, body: str | None = None, lanes=None, model: str | None = None
) -> dict:  # noqa: A002
    """Records in columns by an enum *field*; dragging a card moves it to another lane.

    *lanes* is the order of the columns, `[(value, label), ...]`; left out,
    the surface takes the enum's own values and labels, from *model* — the
    records' datamodel, which it knows from them unless there are none.
    """
    rows = _records(records)
    return _node(
        "lanes",
        records=rows,
        field=field,
        title=title,
        body=body,
        lanes=[{"value": str(v), "label": str(label)} for v, label in lanes] if lanes else None,
        model=model or (rows[0]["model"] if rows else None),
    )


def month(records, *, date: str, title: str, ends: str | None = None, start: str | None = None) -> dict:
    """Records on a month by a date field; *start* (YYYY-MM) is the month shown first."""
    return _node("month", records=_records(records), date=date, title=title, ends=ends, start=start)


# -- checking --------------------------------------------------------------------
PRIMITIVES: dict[str, dict[str, tuple]] = {
    # kind: {prop: (types, required)}
    "stack": {"children": (list, True), "gap": (str, False)},
    "row": {"children": (list, True), "wrap": (bool, False)},
    "columns": {"children": (list, True)},
    "tabs": {"tabs": (list, True)},
    "text": {"text": (str, True), "style": (str, False)},
    "markdown": {"text": (str, True)},
    "image": {"src": (str, False), "model": (str, False), "id": (str, False), "alt": (str, False)},
    "badge": {"text": (str, True), "tone": (str, False)},
    "stat": {"label": (str, True), "value": (str, True), "hint": (str, False), "tone": (str, False)},
    "empty": {"text": (str, True), "action": (str, False), "label": (str, False)},
    "divider": {},
    "field": {"record": (dict, True), "name": (str, True), "label": (str, False), "edit": (bool, False)},
    "form": {"action": (str, True), "values": (dict, False), "record": (dict, False), "submit": (str, False)},
    "button": {
        "label": (str, True), "action": (str, False), "record": (dict, False), "args": (dict, False),
        "open": (dict, False), "go": (str, False), "params": (dict, False), "tone": (str, False),
    },
    "menu": {"label": (str, True), "items": (list, True)},
    "table": {
        "records": (list, True), "columns": (list, True), "open": (bool, False),
        "actions": (list, False), "empty": (str, False),
    },
    "cards": {
        "records": (list, True), "title": (str, True), "subtitle": (str, False), "body": (str, False),
        "badge": (str, False), "open": (bool, False), "empty": (str, False),
    },
    "lanes": {
        "records": (list, True), "field": (str, True), "title": (str, True), "body": (str, False),
        "lanes": (list, False), "model": (str, False),
    },
    "month": {
        "records": (list, True), "date": (str, True), "title": (str, True), "ends": (str, False),
        "start": (str, False),
    },
}

CONTAINERS = {"stack": "children", "row": "children", "columns": "children", "menu": "items"}


def children(node) -> list:
    """What a node holds, in order: a container's children, a menu's items, each tab's child.

    The one reading of a tree's shape, for anything that walks one — `check`
    here, and every surface that draws it.
    """
    if not isinstance(node, dict):
        return []
    kind = node.get("ui")
    if kind == "tabs":
        return [tab.get("child") or {} for tab in node.get("tabs") or [] if isinstance(tab, dict)]
    key = CONTAINERS.get(kind)
    return list(node.get(key) or []) if key else []


def check(tree, *, actions=None, screens=None) -> dict:
    """*tree*, if every surface can draw it; else TreeError saying what is wrong.

    *actions* and *screens*, when given, are the ids the Quill declares: a
    button that runs or goes anywhere else is refused here rather than
    failing when somebody presses it.
    """
    count = [0]

    def walk(node, depth: int, where: str) -> None:
        count[0] += 1
        if count[0] > MAX_NODES:
            raise TreeError(f"a view has at most {MAX_NODES} things in it")
        if depth > MAX_DEPTH:
            raise TreeError(f"{where}: nested more than {MAX_DEPTH} deep")
        if not isinstance(node, dict) or node.get("ui") not in PRIMITIVES:
            kinds = ", ".join(PRIMITIVES)
            raise TreeError(f"{where}: {node!r:.80} is not a primitive; a view is made of {kinds}")
        kind = node["ui"]
        spec = PRIMITIVES[kind]
        for key in node:
            if key != "ui" and key not in spec:
                raise TreeError(f"{where}: a {kind} has no {key!r}")
        for key, (types, required) in spec.items():
            if key not in node or node[key] is None:
                if required:
                    raise TreeError(f"{where}: a {kind} needs {key!r}")
                continue
            if not isinstance(node[key], types):
                raise TreeError(f"{where}: {kind} {key} is a {types.__name__}")
            if isinstance(node[key], str) and len(node[key]) > MAX_TEXT:
                raise TreeError(f"{where}: {kind} {key} is longer than {MAX_TEXT} characters")
        for key in ("tone",):
            if key in node and node[key] not in TONES:
                raise TreeError(f"{where}: tone is one of {', '.join(TONES)}")
        if kind == "stack" and node.get("gap", "normal") not in GAPS:
            raise TreeError(f"{where}: a stack's gap is one of {', '.join(GAPS)}")
        if kind == "text" and node.get("style", "body") not in TEXT_STYLES:
            raise TreeError(f"{where}: text style is one of {', '.join(TEXT_STYLES)}")
        if kind == "image" and node.get("src") and not node["src"].startswith("https://"):
            raise TreeError(f"{where}: an image's src is an https:// address")
        for key in ("action",):
            if node.get(key) and actions is not None and node[key] not in actions:
                raise TreeError(f"{where}: {kind} runs {node[key]!r}, which the manifest does not declare")
        for key in ("actions",):
            for name in node.get(key) or ():
                if actions is not None and name not in actions:
                    raise TreeError(f"{where}: {kind} runs {name!r}, which the manifest does not declare")
        if node.get("go") and screens is not None and node["go"] not in screens:
            raise TreeError(f"{where}: button goes to {node['go']!r}, which is not a screen")
        child_key = CONTAINERS.get(kind)
        if child_key:
            for i, child in enumerate(node[child_key]):
                walk(child, depth + 1, f"{where}.{kind}[{i}]")
        if kind == "tabs":
            for i, tab in enumerate(node["tabs"]):
                if not isinstance(tab, dict) or not isinstance(tab.get("label"), str) or "child" not in tab:
                    raise TreeError(f"{where}: a tab is a label and a child")
                walk(tab["child"], depth + 1, f"{where}.tabs[{i}]")

    walk(tree, 0, "view")
    return tree
