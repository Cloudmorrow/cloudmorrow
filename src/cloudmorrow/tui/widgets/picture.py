"""A picture from a note, drawn in the terminal beside the editor.

The editor draws one line per line of source, so a picture cannot go inline;
it goes beside the text instead, the one the cursor is on, or the first in
the note. textual-image does the drawing: the real picture where the
terminal speaks Kitty's graphics protocol or Sixel, and coloured half-cells
everywhere else, which is enough to tell the right photo from the wrong one.
"""

from __future__ import annotations

import re
from io import BytesIO

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

try:
    # Probes the terminal on import, which has to happen before Textual takes
    # it over. Every entry point that shows the TUI imports this first.
    from textual_image.widget import Image as TerminalImage
except ImportError:  # an older install without the extra
    TerminalImage = None  # type: ignore[assignment]

# `![alt](img/name)`: how a note points at a picture of its own.
IMAGE_REF = re.compile(r"!\[(?P<alt>[^\]]*)\]\(img/(?P<name>[^)\s]+)\)")


def image_refs(text: str) -> list[tuple[str, str]]:
    """Every (name, alt) a note mentions, in order, once each."""
    seen: dict[str, str] = {}
    for match in IMAGE_REF.finditer(text):
        seen.setdefault(match.group("name"), match.group("alt"))
    return list(seen.items())


class Picture(Vertical):
    """The panel: a caption, and the picture under it. Hidden when there is none."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.shown: str | None = None
        self.display = False

    def compose(self) -> ComposeResult:
        yield Static("", id="picture-caption")

    async def show(self, name: str, alt: str, data: bytes) -> None:
        # `shown` is claimed last: a show cancelled halfway (the cursor moved
        # again) must not leave the panel claiming a picture it never drew.
        self.shown = None
        self.display = True
        self.query_one("#picture-caption", Static).update(f"[b]{alt or name}[/]\n[dim]{name}[/]")
        await self.query(".picture-image").remove()
        if TerminalImage is None:
            body = Static("[dim]Install textual-image to see pictures here.[/]")
        else:
            try:
                from PIL import Image as PILImage

                opened = PILImage.open(BytesIO(data))
                # Decode now, so a broken file is a caption and not a crash
                # in the middle of a repaint.
                opened.load()
                body = TerminalImage(opened, classes="picture-image")
            except Exception as exc:  # a file that is not a picture after all
                body = Static(f"[dim]cannot draw {name}: {exc}[/]")
        body.add_class("picture-image")
        await self.mount(body)
        self.shown = name

    def hide(self) -> None:
        self.shown = None
        self.display = False

    def say(self, message: str) -> None:
        """Something instead of a picture: fetching, or why there is none."""
        self.query_one("#picture-caption", Static).update(f"[dim]{message}[/]")
        self.display = True
