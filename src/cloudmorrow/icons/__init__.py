"""The pixel icon library: hundreds of marks drawn in dots, themed, free to use.

The icons are the app's own kind: a square grid of dots, `X` where a dot is
and `.` where it is not, drawn on every surface the way the tab icons are
(``pixelArt`` in ``server/web/core.js``). The library is TOML beside this
file: ``themes.toml`` lists the themes in order, and each theme is a file of
``[[icons]]`` with an ``id``, a ``name``, a few ``tags`` and the ``rows``.

A Quill names one in its manifest (``icon = "hedgehog"``) and the tab shows
it; the web app reads them all once from ``GET /icons.json``. Every icon is
CC0: public domain, free to use anywhere, in anything, no attribution owed.
"""

from __future__ import annotations

import functools
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).parent
SIZES = (12, 8)
ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# The nine marks the app draws itself (core.js PIXELS), and the CRM's funnel:
# a Quill may name these too, and they are not in the library's files.
APP_ICONS = ("notes", "tasks", "files", "secrets", "settings", "chat", "calendar", "me", "today", "funnel")


@dataclass(frozen=True, slots=True)
class Icon:
    id: str
    name: str
    theme: str
    tags: tuple[str, ...]
    rows: tuple[str, ...]

    @property
    def size(self) -> int:
        return len(self.rows)

    def to_dict(self) -> dict:
        return {"name": self.name, "theme": self.theme, "tags": list(self.tags), "rows": list(self.rows)}


def _read(name: str) -> dict:
    return tomllib.loads((HERE / name).read_text(encoding="utf-8"))


@functools.cache
def themes() -> list[dict]:
    """The themes, in display order: id, name, description, file."""
    return [dict(t) for t in _read("themes.toml").get("themes", [])]


@functools.cache
def icons() -> dict[str, Icon]:
    """Every icon of every theme, by id, in the order of the files."""
    found: dict[str, Icon] = {}
    for theme in themes():
        for row in _read(theme["file"]).get("icons", []):
            icon = Icon(
                id=str(row.get("id", "")),
                name=str(row.get("name") or row.get("id", "")),
                theme=str(theme["id"]),
                tags=tuple(str(t) for t in row.get("tags", [])),
                rows=tuple(str(r) for r in row.get("rows", [])),
            )
            found.setdefault(icon.id, icon)
    return found


def get(icon_id: str) -> Icon | None:
    return icons().get(icon_id)


def svg(rows: tuple[str, ...] | list[str], cls: str = "pixel-icon") -> str:
    """The rows as SVG dots, exactly as the web app draws them."""
    dots = []
    for y, row in enumerate(rows):
        for x, cell in enumerate(row):
            if cell == "X":
                dots.append(f'<rect x="{x + 0.08:g}" y="{y + 0.08:g}" width="0.84" height="0.84" rx="0.16"/>')
    n = len(rows)
    return f'<svg class="{cls}" viewBox="0 0 {n} {n}" fill="currentColor" aria-hidden="true">{"".join(dots)}</svg>'


def check() -> list[str]:
    """Every problem with the library's files; an empty list when it is sound."""
    problems: list[str] = []
    index = _read("themes.toml").get("themes", [])
    listed = {str(t.get("file", "")) for t in index}
    for path in sorted(HERE.glob("*.toml")):
        if path.name != "themes.toml" and path.name not in listed:
            problems.append(f"{path.name} is not in themes.toml")
    seen: dict[str, str] = {}
    for theme in index:
        for key in ("id", "name", "description", "file"):
            if not theme.get(key):
                problems.append(f"theme {theme.get('id', '?')!r} has no {key}")
        file = str(theme.get("file", ""))
        if not (HERE / file).is_file():
            problems.append(f"theme {theme.get('id', '?')!r}: {file} is missing")
            continue
        for row in _read(file).get("icons", []):
            icon_id = str(row.get("id", ""))
            where = f"{file}: {icon_id or '?'}"
            if not ID.match(icon_id):
                problems.append(f"{where}: an id is lowercase letters, digits and dashes")
            if icon_id in seen:
                problems.append(f"{where}: already in {seen[icon_id]}")
            seen[icon_id] = file
            if not row.get("name"):
                problems.append(f"{where}: no name")
            if not row.get("tags"):
                problems.append(f"{where}: no tags")
            rows = [str(r) for r in row.get("rows", [])]
            if len(rows) not in SIZES or any(len(r) != len(rows) for r in rows):
                problems.append(f"{where}: {len(rows)} rows; an icon is {' or '.join(f'{s}×{s}' for s in SIZES)}")
            if any(set(r) - {"X", "."} for r in rows):
                problems.append(f"{where}: rows are X and . only")
            if not any("X" in r for r in rows):
                problems.append(f"{where}: nothing is drawn")
    return problems


def as_json() -> dict:
    """What /icons.json answers: the themes, and every icon by id."""
    return {"themes": themes(), "icons": {icon_id: icon.to_dict() for icon_id, icon in icons().items()}}
