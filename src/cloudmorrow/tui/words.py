"""How the terminal says small things: a count of them, a moment, what somebody typed.

Kept in one place because each was written three times, slightly
differently, and a count that says "1 notes" on one card and "1 note" on
the next is the kind of thing that makes an app feel assembled rather than
made. Nothing here knows about Textual.
"""

from __future__ import annotations


def plural(count: int, word: str) -> str:
    """*count* of *word*: "1 task", "3 tasks"."""
    return f"{count} {word}{'' if count == 1 else 's'}"


def megabytes(size: int) -> str:
    """A download's size as a person reads it: 119 MB, 1.5 GB."""
    if size >= 1_000_000_000:
        return f"{size / 1_000_000_000:.1f} GB"
    return f"{max(1, round(size / 1_000_000))} MB"


def short_stamp(value: str | None, width: int = 16) -> str:
    """An ISO moment cut to the minute, with a space for the T: 2026-09-19 14:03."""
    return (value or "—")[:width].replace("T", " ")


def escape(text: object) -> str:
    """Whatever somebody typed is text, not markup."""
    return str(text or "").replace("[", r"\[")
