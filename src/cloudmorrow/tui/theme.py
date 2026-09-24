"""The look: the Textual theme, built from the one palette.

Textual resolves `$primary` and friends in CSS from the registered theme; the
same hex values are re-exported here as plain strings for the places that
build rich markup by hand.
"""

from __future__ import annotations

from textual.theme import Theme

# The values live in cloudmorrow.palette, which needs no Textual, so the command
# line can be the same colour as the app without dragging the app in with it.
from cloudmorrow.palette import (
    ACCENT,
    BAD,
    GOOD,
    INK,
    LINE,
    LINE_BRIGHT,
    MUTED,
    PANEL,
    SECOND,
    SURFACE,
    TEXT,
    WARN,
)

__all__ = [
    "ACCENT",
    "BAD",
    "CLOUDMORROW_THEME",
    "GOOD",
    "INK",
    "LINE",
    "LINE_BRIGHT",
    "MUTED",
    "PANEL",
    "SECOND",
    "SURFACE",
    "TEXT",
    "WARN",
]

CLOUDMORROW_THEME = Theme(
    name="cloudmorrow",
    primary=ACCENT,
    secondary=SECOND,
    accent=ACCENT,
    foreground=TEXT,
    background=INK,
    surface=SURFACE,
    panel=PANEL,
    success=GOOD,
    warning=WARN,
    error=BAD,
    dark=True,
    variables={
        "line": LINE,
        "line-bright": LINE_BRIGHT,
        "muted": MUTED,
        "block-cursor-text-style": "none",
        "footer-key-foreground": ACCENT,
        "footer-description-foreground": MUTED,
        "border": LINE,
        "scrollbar": LINE,
        "scrollbar-hover": LINE_BRIGHT,
        "scrollbar-active": ACCENT,
        "input-selection-background": f"{ACCENT} 35%",
    },
)
