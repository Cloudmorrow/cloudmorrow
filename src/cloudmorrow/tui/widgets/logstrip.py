"""The log along the bottom: what happened, newest last, with the time.

Two things write to it: the machines, through the notifications the bell
counts ("omarchy config changed on desktop"), and the app itself, whenever it
says something in passing ("Password changed.", "added to To Do"). Each is one
line — `12:03:04 what happened` — coloured by how it went: red for what
failed, orange for what wants a look, the rest soft. The bell still opens the
full list; this is the part you would have glanced at anyway.

A click on the strip opens the notifications, the way the bell does.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from rich.text import Text
from textual import events
from textual.message import Message
from textual.widgets import Static

from cloudmorrow.tui.theme import BAD, FAINT, GOOD, MUTED, SKY, TEXT, WARN

TONE_COLOURS = {"bad": BAD, "warn": WARN, "good": GOOD, "news": SKY, "soft": MUTED, "text": TEXT}
# How many lines are kept; the strip shows the last few that fit.
KEEP = 50


@dataclass(slots=True)
class LogLine:
    at: dt.datetime
    text: str
    tone: str = "soft"
    key: str = ""


def tone_of(note: dict) -> str:
    """How a notification reads: failures red, warnings orange, the rest news."""
    kind = f"{note.get('kind', '')} {note.get('level', '')}".lower()
    if any(word in kind for word in ("fail", "error", "bad")):
        return "bad"
    if "warn" in kind:
        return "warn"
    return "news"


def moment(value: str | None) -> dt.datetime:
    try:
        at = dt.datetime.fromisoformat(value or "")
    except ValueError:
        return dt.datetime.now()
    if at.tzinfo is not None:
        at = at.astimezone().replace(tzinfo=None)
    return at


class LogStrip(Static):
    """The last few lines of what happened."""

    class Opened(Message):
        """The strip was clicked: show the notifications."""

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self.lines: list[LogLine] = []
        self._seen: set[str] = set()
        self.border_title = "LOG"

    def on_mount(self) -> None:
        self.redraw()

    def say(self, text: str, tone: str = "soft") -> None:
        """A line from the app, now."""
        if not text:
            return
        if self.lines and self.lines[-1].text == text and not self.lines[-1].key:
            # Said twice in a row is said once.
            return
        self._add(LogLine(dt.datetime.now(), text, tone))

    def notes(self, notes: list[dict]) -> None:
        """Notifications from the server; each one is logged once, at its own time."""
        fresh = [n for n in notes if f"n{n.get('id')}" not in self._seen]
        for note in sorted(fresh, key=lambda n: str(n.get("created_at") or "")):
            key = f"n{note.get('id')}"
            self._seen.add(key)
            self.lines.append(
                LogLine(moment(note.get("created_at")), str(note.get("title") or ""),
                        tone_of(note), key)
            )
        if fresh:
            self.lines.sort(key=lambda line: line.at)
            del self.lines[:-KEEP]
            self.redraw()

    def _add(self, line: LogLine) -> None:
        self.lines.append(line)
        del self.lines[:-KEEP]
        self.redraw()

    def rows(self) -> int:
        return max(1, self.size.height or 3)

    def redraw(self) -> None:
        shown = self.lines[-self.rows():]
        out = Text(no_wrap=True, overflow="ellipsis")
        if not shown:
            out.append("Nothing has happened yet. Quiet is good.", style=FAINT)
        for index, line in enumerate(shown):
            if index:
                out.append("\n")
            stamp = line.at.strftime("%H:%M:%S") if line.at.date() == dt.date.today() \
                else line.at.strftime("%d %b %H:%M")
            out.append(f"{stamp} ", style=FAINT)
            out.append(line.text, style=TONE_COLOURS.get(line.tone, MUTED))
        self.update(out)

    def on_resize(self, _: events.Resize) -> None:
        self.redraw()

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.post_message(self.Opened())
