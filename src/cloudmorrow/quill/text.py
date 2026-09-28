"""A view as plain text: for the command line, `cm quill preview`, and tests.

The phone, the web app and the terminal app draw a view's primitives; this
writes the same tree as lines, so a view can be read where nothing draws —
piped, previewed, or asserted on (`Harness.view(...).text()`).

    render(tree, actions={"log-service": "Log a service"})
"""

from __future__ import annotations

RULE = "─"


def _value(record: dict, name: str) -> str:
    value = record.get("fields", {}).get(name)
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _label(name: str) -> str:
    return name.rsplit(".", 1)[-1].replace("_", " ").capitalize()


def _table(node: dict, actions: dict) -> list[str]:
    records = node["records"]
    if not records:
        return [f"({node.get('empty') or 'nothing yet'})"]
    heads = [c.get("label") or _label(c["field"]) for c in node["columns"]]
    rows = [[_value(r, c["field"]) for c in node["columns"]] for r in records]
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(heads)]
    lines = ["  ".join(h.ljust(w) for h, w in zip(heads, widths, strict=True)).rstrip()]
    lines.append("  ".join(RULE * w for w in widths))
    lines += ["  ".join(v.ljust(w) for v, w in zip(row, widths, strict=True)).rstrip() for row in rows]
    if node.get("actions"):
        lines.append("each: " + ", ".join(f"[{actions.get(a, a)}]" for a in node["actions"]))
    return lines


def _lines(node: dict, actions: dict) -> list[str]:
    kind = node["ui"]
    if kind in ("stack", "columns"):
        out: list[str] = []
        for child in node["children"]:
            out += _lines(child, actions)
        return out
    if kind == "row":
        parts = [_lines(child, actions) for child in node["children"]]
        if all(len(p) <= 1 for p in parts):
            return ["   ".join(p[0] for p in parts if p)]
        return [line for part in parts for line in part]
    if kind == "tabs":
        out = []
        for tab in node["tabs"]:
            out.append(f"[{tab['label']}]")
            out += ["  " + line for line in _lines(tab["child"], actions)]
        return out
    if kind == "text":
        if node.get("style") == "title":
            return [node["text"], RULE * len(node["text"])]
        return node["text"].splitlines() or [""]
    if kind == "markdown":
        return node["text"].splitlines()
    if kind == "image":
        return [f"[picture{': ' + node['alt'] if node.get('alt') else ''}]"]
    if kind == "badge":
        return [f"[{node['text']}]"]
    if kind == "stat":
        hint = f" ({node['hint']})" if node.get("hint") else ""
        return [f"{node['label']}: {node['value']}{hint}"]
    if kind == "empty":
        more = f" [{node.get('label') or actions.get(node['action'], node['action'])}]" if node.get("action") else ""
        return [f"({node['text']}){more}"]
    if kind == "divider":
        return [RULE * 20]
    if kind == "field":
        return [f"{node.get('label') or _label(node['name'])}: {_value(node['record'], node['name'])}"]
    if kind == "form":
        return [f"[{node.get('submit') or actions.get(node['action'], node['action'])}…]"]
    if kind == "button":
        target = node.get("action") and actions.get(node["action"], node["action"])
        return [f"[{node['label']}]" if not target or target == node["label"] else f"[{node['label']}]"]
    if kind == "menu":
        return [f"{node['label']}: " + " ".join(line for item in node["items"] for line in _lines(item, actions))]
    if kind == "table":
        return _table(node, actions)
    if kind == "cards":
        if not node["records"]:
            return [f"({node.get('empty') or 'nothing yet'})"]
        out = []
        for record in node["records"]:
            head = _value(record, node["title"])
            if node.get("subtitle") and _value(record, node["subtitle"]):
                head += f" — {_value(record, node['subtitle'])}"
            if node.get("badge") and _value(record, node["badge"]):
                head += f" [{_value(record, node['badge'])}]"
            out.append(f"• {head}")
            if node.get("body") and _value(record, node["body"]):
                out += ["  " + line for line in _value(record, node["body"]).splitlines()[:3]]
        return out
    if kind == "lanes":
        order = [lane["value"] for lane in node.get("lanes") or []]
        names = {lane["value"]: lane["label"] for lane in node.get("lanes") or []}
        for record in node["records"]:
            value = _value(record, node["field"])
            if value not in order:
                order.append(value)
        out = []
        for value in order:
            inside = [r for r in node["records"] if _value(r, node["field"]) == value]
            out.append(f"{names.get(value, value or '—')} ({len(inside)})")
            out += [f"  • {_value(r, node['title'])}" for r in inside]
        return out
    if kind == "month":
        records = sorted(node["records"], key=lambda r: _value(r, node["date"]))
        return [f"{_value(r, node['date'])[:16]}  {_value(r, node['title'])}" for r in records] or ["(nothing this month)"]
    return [f"[{kind}]"]


def render(tree: dict, *, actions: dict[str, str] | None = None) -> str:
    """*tree* as text; *actions* maps action ids to their labels, for the buttons."""
    return "\n".join(_lines(tree, actions or {})).rstrip() + "\n"
