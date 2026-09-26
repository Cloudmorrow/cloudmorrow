"""The sidebar down the left: every place in the app, as a small card.

This replaces the strip of tabs across the top. A strip says what is there;
a card can also say how it is — "3 to do", "2 unread", "4 vaults" — so the
sidebar is where you see the state of your cloud at a glance, and a click or
a key takes you in. The sections:

- **YOUR CLOUD** — what is built into the core: nothing now, so not drawn.
- **QUILLS** — a card for every screen of every installed Quill.
- **ADMINISTRATION** — for administrators: Users, Features, Quills. Smaller,
  one line each, because it is the server rather than your things.

A card is two rows: its name on a rounded top border, and one line under it
— a coloured dot and how it is, or a faint description until there is
something live to say — with its function key at the end. The card you are
on has a Sky border (blue is where you are); hovering one lights it. Below
about ninety columns the sidebar narrows and each card becomes one line.
"""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.message import Message
from textual.widgets import Static

from cloudmorrow.tui.theme import BAD, FAINT, GOOD, MUTED, SKY, TEXT, WARN

# Status tones, as the dot beside a card's line shows them.
TONES = {
    "ok": ("●", GOOD),
    "busy": ("◌", SKY),
    "warn": ("▲", WARN),
    "bad": ("✗", BAD),
    "none": ("·", FAINT),
    "off": ("○", FAINT),
    "news": ("●", SKY),
}


def status_text(tone: str, text: str, *, active: bool = False) -> Text:
    """● 2 to do — or, with nothing live to say yet, a faint description, no dot."""
    out = Text(no_wrap=True, overflow="ellipsis")
    if tone == "none":
        out.append(text, style=FAINT)
        return out
    dot, colour = TONES.get(tone, TONES["none"])
    out.append(f"{dot} ", style=colour)
    out.append(text, style=TEXT if active else MUTED)
    return out


class SectionLabel(Static):
    """YOUR CLOUD, in bold soft capitals, and a faint note after it."""

    def __init__(self, title: str, note: str = "", **kwargs) -> None:
        text = Text(title.upper(), style=f"bold {MUTED}")
        if note:
            text.append(f" {note}", style=FAINT)
        super().__init__(text, classes="nav-section", **kwargs)


class NavCard(Static, can_focus=False):
    """One place: its name, its key, and a line about how it is.

    Clicked, it says so with `Chosen`; the workspace does the switching, so a
    card never has to know what is behind it.
    """

    class Chosen(Message):
        def __init__(self, card: NavCard) -> None:
            self.card = card
            super().__init__()

    def __init__(self, key: str, title: str, *, tag: str = "", compact: bool = False,
                 **kwargs) -> None:
        super().__init__("", **kwargs)
        self.nav_key = key
        self.name_text = title
        self.tag = tag
        self.tone = "none"
        self.status_line = ""
        self.add_class("nav-card")
        if compact:
            self.add_class("-small")
        self.border_title = title

    def on_mount(self) -> None:
        self.redraw()

    def set_status(self, tone: str, text: str) -> None:
        if (tone, text) == (self.tone, self.status_line):
            return
        self.tone, self.status_line = tone, text
        self.redraw()

    def set_tag(self, tag: str) -> None:
        self.tag = tag
        self.redraw()

    @property
    def active(self) -> bool:
        return self.has_class("-active")

    def set_active(self, active: bool) -> None:
        self.set_class(active, "-active")
        self.redraw()

    def redraw(self) -> None:
        if self.has_class("-small") or self.has_class("-line"):
            # One line: the name, and the key after it, faint.
            line = Text(no_wrap=True, overflow="ellipsis")
            line.append("› " if self.active else "  ", style=SKY)
            line.append(self.name_text, style=f"bold {SKY}" if self.active else MUTED)
            if self.tag:
                line.append(f"  {self.tag}", style=FAINT)
            self.update(line)
            return
        # The status, and the key at the far end of the same line.
        width = self.size.width or 24
        room = width - (len(self.tag) + 1 if self.tag else 0)
        line = status_text(self.tone, self.status_line or " ", active=self.active)
        line.truncate(max(1, room), overflow="ellipsis", pad=True)
        if self.tag:
            line.append(" ")
            line.append(self.tag, style=SKY if self.active else FAINT)
        self.update(line)

    def on_resize(self, _: events.Resize) -> None:
        self.redraw()

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.post_message(self.Chosen(self))
