"""Which records an action is for: an action's `only`.

An action `on` a datamodel is drawn on every record of it, unless the
manifest says which ones it is for:

    [[actions]]
    id = "edit-photo"
    label = "Edit this photo"
    on = "file"
    only = { kind = "file", name = ["*.jpg", "*.jpeg", "*.png"] }

Each key is a field of that datamodel; its value is a pattern, or a list of
them, and the record fits when every field's value matches one of its
patterns. A pattern is the value as text, `*` standing for anything and `?`
for one letter, case not minding. The web app, the terminal and the command
line leave the button off a record that does not fit, and the server refuses
the press; the same sums are actions.js's `fits`.
"""

from __future__ import annotations

import fnmatch


def patterns_of(value: object) -> list[str]:
    """The patterns one `only` entry holds, as text."""
    items = value if isinstance(value, list) else [value]
    return [str(item) for item in items]


def value_fits(value: object, patterns: list[str]) -> bool:
    """Whether a field's value, as text, matches one of the patterns."""
    said = "" if value is None else str(value).lower()
    return any(fnmatch.fnmatchcase(said, pattern.lower()) for pattern in patterns)


def fits(action: dict, fields: dict | None) -> bool:
    """Whether a record with *fields* is one the action is for."""
    only = action.get("only")
    if not isinstance(only, dict) or not only:
        return True
    fields = fields or {}
    return all(value_fits(fields.get(name), patterns_of(patterns)) for name, patterns in only.items())
