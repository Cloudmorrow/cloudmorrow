"""Reading and writing `.env` files.

The one place that knows the file format. The API only ever sees key/value
pairs, so turning a `.env` into secrets — and back — is the client's job, and
both directions agree because they share this module.

The dialect is the usual one: `KEY=value`, an optional `export ` prefix, `#`
comments, and values that may be bare, `'literal'` or `"escaped"`. Quoted
values may span lines.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

# Where a secret lives when nobody says: the vault everyone has, and the
# environment a plain `.env` means. Both ends agree because both read these.
DEFAULT_VAULT = "default"
DEFAULT_ENVIRONMENT = "local"
KNOWN_ENVIRONMENTS = ("local", "development", "staging", "production")

# The POSIX name for an environment variable. Secrets use it too: a key that
# cannot be exported to a shell has no business in a .env file.
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Values that survive a shell untouched, so they need no quotes on the way out.
_BARE_RE = re.compile(r"^[A-Za-z0-9_@%+=:,./-]+$")
_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"', "'": "'"}
# An unquoted value ends at a `#` that follows whitespace.
_INLINE_COMMENT_RE = re.compile(r"\s#")

class DotenvError(ValueError):
    """A line we refuse to guess at, with the line number to look at."""

    def __init__(self, message: str, line: int) -> None:
        super().__init__(f"line {line}: {message}")
        self.line = line


def parse(text: str) -> dict[str, str]:
    """Parse a `.env` file. Later assignments win, as they do in a shell."""
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    entries: dict[str, str] = {}
    position = 0
    line_no = 1
    while position < len(text):
        end = text.find("\n", position)
        end = len(text) if end < 0 else end
        line = text[position:end]
        if not line.strip() or line.lstrip().startswith("#"):
            position, line_no = end + 1, line_no + 1
            continue
        separator = line.find("=")
        if separator < 0:
            raise DotenvError("expected KEY=value", line_no)
        name = line[:separator].strip()
        if name.startswith("export "):
            name = name[len("export ") :].strip()
        if not KEY_RE.match(name):
            raise DotenvError(f"{name!r} is not a valid variable name", line_no)
        value_start = position + separator + 1
        while value_start < len(text) and text[value_start] in " \t":
            value_start += 1
        value, position, line_no = _read_value(text, value_start, line_no)
        entries[name] = value
    return entries


def _read_value(text: str, start: int, line_no: int) -> tuple[str, int, int]:
    """Read one value, returning it with the next position and line number."""
    if start < len(text) and text[start] in "\"'":
        return _read_quoted(text, start, line_no)
    end = text.find("\n", start)
    end = len(text) if end < 0 else end
    raw = text[start:end]
    comment = _INLINE_COMMENT_RE.search(raw)
    if comment is not None:
        raw = raw[: comment.start()]
    return raw.strip(), end + 1, line_no + 1


def _read_quoted(text: str, start: int, line_no: int) -> tuple[str, int, int]:
    quote = text[start]
    chunks: list[str] = []
    index = start + 1
    while index < len(text):
        char = text[index]
        # Escapes are a double-quote thing; inside single quotes everything is
        # literal, which is why we prefer them when writing a file back out.
        if char == "\\" and quote == '"' and index + 1 < len(text):
            chunks.append(_ESCAPES.get(text[index + 1], "\\" + text[index + 1]))
            index += 2
            continue
        if char == quote:
            index += 1
            break
        if char == "\n":
            line_no += 1
        chunks.append(char)
        index += 1
    else:
        raise DotenvError("unterminated quoted value", line_no)
    end = text.find("\n", index)
    end = len(text) if end < 0 else end
    return "".join(chunks), end + 1, line_no + 1


def quote(value: str) -> str:
    """Quote a value so parsing it back — here or in a shell — returns it intact."""
    if _BARE_RE.match(value):
        return value
    if "'" not in value and "\n" not in value:
        # Single quotes are literal: no escapes, and no $VAR expansion.
        return f"'{value}'"
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def dump(entries: Mapping[str, str], *, header: str = "") -> str:
    """Render entries as a `.env` file, in the order given."""
    lines = [f"# {line}" for line in header.splitlines()] if header else []
    if lines:
        lines.append("")
    lines += [f"{name}={quote(value)}" for name, value in entries.items()]
    return "\n".join(lines) + "\n"
