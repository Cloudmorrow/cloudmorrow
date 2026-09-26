"""The reference for writing a Quill, as it ships with the package.

One text, read by the MCP `quill_schema` tool, written into a new Quill's
CLAUDE.md by `cm quill new`, and printed by `cm quill reference`, so an
assistant building a Quill reads the same thing wherever it starts.
"""

from __future__ import annotations

from pathlib import Path

REFERENCE = Path(__file__).with_name("quill_reference.md")


def quill_reference() -> str:
    return REFERENCE.read_text(encoding="utf-8")
