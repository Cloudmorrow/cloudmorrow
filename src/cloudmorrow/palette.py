"""The colours, named once, for everything that draws.

The TUI's stylesheet and the CLI's status lines are the same product and ought
to look like it. This module holds nothing but the values so that both can have
them: the TUI's theme is built on top of these, and the command line — which
may well be installed without Textual at all — imports them directly.

These are CATHODE: a colour monitor at two in the morning. Cool dark glass —
lifted off black, because a page of pure black has no surfaces on it, and
kept close to neutral, because a large flat area with much blue in it reads
as navy and navy is ugly at that size. Saturation is for the small things:
phosphor cyan for what you are on, violet for a name or a link. The web
app is painted from the same twelve, in `server/web/base.css`, and `/brand`
shows the other two that were not chosen.

Nothing here is a terminal colour name. "cyan" is whatever the person running
us has decided cyan looks like, and half the time that is a colour we would
never have picked; every one of these goes out as 24-bit RGB instead. See
`cloudmorrow.console`, which is what makes that stick.
"""

from __future__ import annotations

INK = "#14171f"          # the page
SURFACE = "#1f242e"      # panels sitting on it
PANEL = "#272d39"        # panels sitting on those
LINE = "#333a48"         # borders
LINE_BRIGHT = "#4a5364"  # borders that want noticing
TEXT = "#dfe5f0"
MUTED = "#99a1b3"
ACCENT = "#4fe3d7"       # phosphor cyan: the brand, and the current thing
SECOND = "#a78bfa"       # violet: names and links
GOOD = "#5ce89b"
WARN = "#ffc857"
BAD = "#ff6b81"

# The banner is tinted across these, dark end first: cyan through indigo into
# magenta, 154° of hue, which is a pleasure on the hairlines of a drawing.
GRADIENT = (
    "#4fe3d7",
    "#7c8cf8",
    "#f472b6",
)

# The wordmark is tinted across these instead. Same idea at 59° and half the
# chroma, because the wordmark is a dense field of dots rather than a few
# hairlines, and a wide hue arc across one of those on a dark ground has its
# two ends focusing at different apparent depths — which is a real and quite
# specific kind of unpleasant to look at.
MARK_GRADIENT = (
    "#3fbdb4",
    "#4886c9",
    "#6d74c6",
)
