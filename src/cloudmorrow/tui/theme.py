"""The look: the Textual theme, built from the one palette.

Textual resolves `$primary` and friends in CSS from the registered theme; the
same hex values are re-exported here as plain strings for the places that
build rich markup by hand.

`$primary` is Sky — where you are: focus, selection, the card you are on.
The one primary action on a screen is not `$primary` but `$action`, amber,
because the brand keeps blue for the platform and amber for the person (see
cloudmorrow.palette).
"""

from __future__ import annotations

from textual.theme import Theme

# The values live in cloudmorrow.palette, which needs no Textual, so the command
# line can be the same colour as the app without dragging the app in with it.
from cloudmorrow.palette import (
    ACCENT,
    ACTION,
    ACTION_INK,
    BAD,
    CLOUD,
    DEEP,
    FAINT,
    GOOD,
    INK,
    LENS,
    LINE,
    LINE_BRIGHT,
    MUTED,
    NIGHT,
    PANEL,
    PUFF,
    SECOND,
    SKY,
    SURFACE,
    TEXT,
    WARN,
)

__all__ = [
    "ACCENT",
    "ACTION",
    "ACTION_INK",
    "BAD",
    "CLOUD",
    "CLOUDMORROW_THEME",
    "DEEP",
    "FAINT",
    "GOOD",
    "INK",
    "LENS",
    "LINE",
    "LINE_BRIGHT",
    "MUTED",
    "NIGHT",
    "PANEL",
    "PUFF",
    "SECOND",
    "SKY",
    "SURFACE",
    "TEXT",
    "WARN",
]

CLOUDMORROW_THEME = Theme(
    name="cloudmorrow",
    primary=SKY,
    secondary=LENS,
    accent=SKY,
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
        "faint": FAINT,
        "night": NIGHT,
        "sky": SKY,
        "cloud": CLOUD,
        "puff": PUFF,
        "deep": DEEP,
        "lens": LENS,
        "action": ACTION,
        "action-ink": ACTION_INK,
        "block-cursor-text-style": "none",
        "footer-key-foreground": SKY,
        "footer-description-foreground": MUTED,
        "border": SKY,
        "border-blurred": SURFACE,
        "scrollbar": LINE,
        "scrollbar-hover": LINE_BRIGHT,
        "scrollbar-active": SKY,
        "input-selection-background": f"{CLOUD} 60%",
        "input-cursor-background": SKY,
    },
)
