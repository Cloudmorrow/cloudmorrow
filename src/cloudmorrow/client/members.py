"""Who a share is shared with, as a line of text and back.

The command line and the terminal app both take members as words: a
username, `circle:NAME` for a circle, `everyone` for everybody on the
server, each followed by `(read)` when that is all they may do —

    ann, circle:kids (read), everyone (read)

— and show them the same way, so what is shown can be edited and handed
back. `changes` says what to ask the server for to get from one list to
another.
"""

from __future__ import annotations

__all__ = ["EVERYONE_WORDS", "changes", "format_members", "parse", "parse_one"]

EVERYONE_WORDS = frozenset({"everyone", "everybody", "*"})
READ_MARKS = ("(read)", "(read only)", "(read-only)")


def parse_one(spec: str, *, read: bool = False) -> dict:
    """`ann`, `circle:kids (read)` or `everyone`, as the API takes a member."""
    spec = spec.strip()
    lowered = spec.lower()
    for mark in READ_MARKS:
        if lowered.endswith(mark):
            spec, read = spec[: -len(mark)].strip(), True
            break
    access = "read" if read else "write"
    if spec.lower() in EVERYONE_WORDS:
        return {"kind": "everyone", "who": "*", "access": access}
    kind, colon, who = spec.partition(":")
    if colon and kind.strip().lower() in ("circle", "user"):
        return {"kind": kind.strip().lower(), "who": who.strip(), "access": access}
    return {"kind": "user", "who": spec, "access": access}


def parse(text: str) -> list[dict]:
    """Every member in a comma-separated line; the last word on one wins."""
    found: dict[tuple[str, str], dict] = {}
    for part in (text or "").replace("\n", ",").split(","):
        if part.strip():
            member = parse_one(part)
            found[(member["kind"], member["who"].lower())] = member
    return list(found.values())


def spec(member: dict) -> str:
    """One member as it is typed: `ann`, `circle:kids`, `everyone`."""
    if member["kind"] == "everyone":
        return "everyone"
    return f"circle:{member['who']}" if member["kind"] == "circle" else member["who"]


def format_members(members: list[dict]) -> str:
    """The line `parse` reads back: `ann, circle:kids (read)`."""
    return ", ".join(spec(m) + (" (read)" if m.get("access") == "read" else "") for m in members)


def changes(old: list[dict], new: list[dict]) -> tuple[list[dict], list[dict]]:
    """What to put and what to take away to get from *old* to *new*.

    A circle is matched by its id or its name, since the server says the id
    and a person may well type the name.
    """

    def key(member: dict) -> tuple[str, str]:
        return member["kind"], str(member["who"]).lower()

    def names(member: dict) -> set[tuple[str, str]]:
        keys = {key(member)}
        if member.get("label"):
            keys.add((member["kind"], str(member["label"]).lower()))
        return keys

    before = {k: m for m in old for k in names(m)}
    wanted = {key(m) for m in new}
    put = [m for m in new if key(m) not in before or before[key(m)].get("access") != m["access"]]
    gone = [m for m in old if not names(m) & wanted]
    return put, gone
