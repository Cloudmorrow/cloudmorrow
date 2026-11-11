"""A view as plain text: for the command line, `cm quill preview`, and tests.

The phone, the web app and the terminal app draw a view's primitives; this
writes the same tree as lines, so a view can be read where nothing draws —
piped, previewed, or asserted on (`Harness.view(...).text()`).

    render(tree, actions={"log-service": "Log a service"})
"""

from __future__ import annotations

import datetime as dt

RULE = "─"


def value_text(record: dict, name: str) -> str:
    """A field of *record* as plain words: nothing for nothing, yes or no for a tick."""
    value = record.get("fields", {}).get(name)
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def section_of(stamp: str, today: dt.date | None = None) -> str:
    """Which stretch of time *stamp* (ISO) falls in, for the headings over a
    long list, newest first: Today, Yesterday, Last 7 Days, Last 30 Days, a
    month of this year by name, an earlier year by number; "" for no date."""
    try:
        when = dt.datetime.fromisoformat(str(stamp or "")).date()
    except ValueError:
        return ""
    today = today or dt.date.today()
    days = (today - when).days
    if days <= 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if days < 7:
        return "Last 7 Days"
    if days < 30:
        return "Last 30 Days"
    if when.year == today.year:
        return when.strftime("%B")
    return str(when.year)


def _label(name: str) -> str:
    return name.rsplit(".", 1)[-1].replace("_", " ").capitalize()


def _table(node: dict, actions: dict) -> list[str]:
    records = node["records"]
    if not records:
        return [f"({node.get('empty') or 'nothing yet'})"]
    heads = [c.get("label") or _label(c["field"]) for c in node["columns"]]
    rows = [[value_text(r, c["field"]) for c in node["columns"]] for r in records]
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
    if kind == "split":
        return _lines(node["side"], actions) + [RULE * 20] + _lines(node["main"], actions)
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
        return [f"{node.get('label') or _label(node['name'])}: {value_text(node['record'], node['name'])}"]
    if kind == "form":
        return [f"[{node.get('submit') or actions.get(node['action'], node['action'])}…]"]
    if kind == "button":
        return [f"[▸{node['label']}]" if node.get("current") else f"[{node['label']}]"]
    if kind == "toggle":
        out = [f"[{'x' if node.get('on') else ' '}] {node['label']}"]
        if node.get("hint"):
            out.append("    " + node["hint"])
        return out
    if kind == "conversation":
        out = []
        if node.get("close"):
            out.append(f"[✕ {actions.get(node['close'], node['close'])}]")
        for record in node["records"]:
            fields = record.get("fields", {})
            who = "You" if fields.get(node["mine"]) else (node.get("name") or "Them")
            head = f"{who}:"
            if node.get("at") and value_text(record, node["at"]):
                head += f"  {value_text(record, node['at'])}"
            out.append(head)
            out += ["  " + line for line in value_text(record, node["body"]).splitlines() or [""]]
            if node.get("failed") and fields.get(node["failed"]):
                out.append("  (did not go through)")
            if node.get("note") and value_text(record, node["note"]):
                out.append("  " + value_text(record, node["note"]))
        if not out and node.get("empty"):
            out.append(f"({node['empty']})")
        if node.get("ask"):
            out.append(f"[{node.get('placeholder') or actions.get(node['ask'], node['ask'])}…]")
        if node.get("hint"):
            out.append(node["hint"])
        return out
    if kind == "menu":
        return [f"{node['label']}: " + " ".join(line for item in node["items"] for line in _lines(item, actions))]
    if kind == "table":
        return _table(node, actions)
    if kind == "rows":
        if not node["records"]:
            return [f"({node.get('empty') or 'nothing yet'})"]
        out = [f"[{node['search']}…]"] if node.get("search") else []
        heading = None
        for record in node["records"]:
            if node.get("group"):
                label = section_of(value_text(record, node["group"]))
                if label and label != heading:
                    out.append(f"{label}:")
                    heading = label
            head = value_text(record, node["title"])
            if node.get("subtitle") and value_text(record, node["subtitle"]):
                head += f" — {value_text(record, node['subtitle'])}"
            if node.get("badge") and value_text(record, node["badge"]):
                head += f" [{value_text(record, node['badge'])}]"
            out.append(f"{'▶' if node.get('current') == record['id'] else '•'} {head}")
        return out
    if kind == "cards":
        if not node["records"]:
            return [f"({node.get('empty') or 'nothing yet'})"]
        out = []
        for record in node["records"]:
            head = value_text(record, node["title"])
            if node.get("subtitle") and value_text(record, node["subtitle"]):
                head += f" — {value_text(record, node['subtitle'])}"
            if node.get("badge") and value_text(record, node["badge"]):
                head += f" [{value_text(record, node['badge'])}]"
            out.append(f"{'▶' if node.get('current') == record['id'] else '•'} {head}")
            if node.get("body") and value_text(record, node["body"]):
                out += ["  " + line for line in value_text(record, node["body"]).splitlines()[:3]]
        return out
    if kind == "gallery":
        if not node["records"]:
            return [f"({node.get('empty') or 'nothing yet'})"]
        out = []
        for record in node["records"]:
            head = stars_text(record.get("fields", {}).get(node["stars"])) + "  " if node.get("stars") else ""
            head += value_text(record, node["title"])
            if node.get("badge") and value_text(record, node["badge"]):
                head += f" [{value_text(record, node['badge'])}]"
            if node.get("subtitle") and value_text(record, node["subtitle"]):
                head += f" — {value_text(record, node['subtitle'])}"
            out.append(f"▣ {head}")
        return out
    if kind == "lanes":
        order = [lane["value"] for lane in node.get("lanes") or []]
        names = {lane["value"]: lane["label"] for lane in node.get("lanes") or []}
        for record in node["records"]:
            value = value_text(record, node["field"])
            if value not in order:
                order.append(value)
        out = []
        for value in order:
            inside = [r for r in node["records"] if value_text(r, node["field"]) == value]
            out.append(f"{names.get(value, value or '—')} ({len(inside)})")
            out += [f"  • {value_text(r, node['title'])}" for r in inside]
        return out
    if kind == "month":
        records = sorted(node["records"], key=lambda r: value_text(r, node["date"]))
        return [f"{value_text(r, node['date'])[:16]}  {value_text(r, node['title'])}" for r in records] or [
            "(nothing this month)"
        ]
    return [f"[{kind}]"]


def stars_text(value) -> str:
    """A rating of 0 to 5 as five stars, the lit ones first: ★★★☆☆."""
    try:
        lit = max(0, min(5, int(value or 0)))
    except (TypeError, ValueError):
        lit = 0
    return "★" * lit + "☆" * (5 - lit)


def render(tree: dict, *, actions: dict[str, str] | None = None) -> str:
    """*tree* as text; *actions* maps action ids to their labels, for the buttons."""
    return "\n".join(_lines(tree, actions or {})).rstrip() + "\n"
