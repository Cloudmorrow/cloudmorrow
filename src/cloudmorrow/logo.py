"""The Cloudmorrow logo.

The mark is the wordmark from `pixelfont`, drawn in half blocks and tinted
across a gradient a column at a time — the same drawing, in the same colours,
as the mark at the top of the web app. A terminal cannot do a gradient on a
fill, but it can give every cell its own 24-bit colour, which comes to the
same thing at this size.

`LOGO_LARGE` stays for the install page, which is HTML and wants line art.
"""

from __future__ import annotations

from collections.abc import Sequence

from rich.align import Align
from rich.console import Group, RenderableType
from rich.text import Text

from cloudmorrow import __version__, pixelfont
from cloudmorrow.palette import ACCENT, MARK_GRADIENT, MUTED

# Line art, for the one place that is a web page rather than a terminal.
LOGO_LARGE = r"""
  ██████╗██╗      ██████╗ ██╗   ██╗██████╗ ███╗   ███╗ ██████╗ ██████╗ ██████╗  ██████╗ ██╗    ██╗
 ██╔════╝██║     ██╔═══██╗██║   ██║██╔══██╗████╗ ████║██╔═══██╗██╔══██╗██╔══██╗██╔═══██╗██║    ██║
 ██║     ██║     ██║   ██║██║   ██║██║  ██║██╔████╔██║██║   ██║██████╔╝██████╔╝██║   ██║██║ █╗ ██║
 ██║     ██║     ██║   ██║██║   ██║██║  ██║██║╚██╔╝██║██║   ██║██╔══██╗██╔══██╗██║   ██║██║███╗██║
 ╚██████╗███████╗╚██████╔╝╚██████╔╝██████╔╝██║ ╚═╝ ██║╚██████╔╝██║  ██║██║  ██║╚██████╔╝╚███╔███╔╝
  ╚═════╝╚══════╝ ╚═════╝  ╚═════╝ ╚═════╝ ╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚══╝╚══╝ 
"""

TAGLINE = "own your data, choose your apps"

# How wide the mark comes out, so a caller can ask whether it will fit.
WORDMARK_WIDTH = len(pixelfont.rows("CLOUDMORROW")[0])


def _rgb(colour: str) -> tuple[int, int, int]:
    n = int(colour.lstrip("#"), 16)
    return (n >> 16) & 255, (n >> 8) & 255, n & 255


def ramp(stops: Sequence[str], width: int) -> list[str]:
    """`width` colours stepped evenly across the stops.

    Straight sRGB interpolation. Something perceptual would be better over a
    long run, but these are three stops across fifty cells of a logo, and the
    difference does not survive the journey to a terminal.
    """
    if width <= 1:
        return [stops[0]]
    segments = len(stops) - 1
    out = []
    for i in range(width):
        position = i / (width - 1) * segments
        index = min(int(position), segments - 1)
        weight = position - index
        start, end = _rgb(stops[index]), _rgb(stops[index + 1])
        mixed = (round(a + (b - a) * weight) for a, b in zip(start, end, strict=True))
        out.append("#{:02x}{:02x}{:02x}".format(*mixed))
    return out


def wordmark(text: str = "CLOUDMORROW", *, stops: Sequence[str] = MARK_GRADIENT) -> Text:
    """The mark in half blocks, one colour per column.

    Per column rather than per cell, so the gradient runs along the word and
    a letter is never split down the middle by it.
    """
    lines = pixelfont.rows(text)
    colours = ramp(stops, len(lines[0]) if lines else 1)
    out = Text(no_wrap=True)
    for row, line in enumerate(lines):
        if row:
            out.append("\n")
        for column, char in enumerate(line):
            # A blank cell has nothing to colour, and styling it would only
            # cost a span.
            out.append(char, style=None if char == " " else colours[column])
    return out


def banner(*, subtitle: str | None = None) -> RenderableType:
    """Mark + tagline + version, centred — for `cloudmorrow` and the API server."""
    parts: list[RenderableType] = [wordmark()]
    parts.append(Text(f"{TAGLINE}   ·   v{__version__}", style=MUTED))
    if subtitle:
        parts.append(Text(subtitle, style=ACCENT))
    return Align.center(Group(*parts))


def mark_for_width(width: int) -> Text:
    """The mark, or the plain word when the terminal is too narrow for it."""
    if width >= WORDMARK_WIDTH:
        return wordmark()
    return Text("CLOUDMORROW", style=f"bold {ACCENT}")
