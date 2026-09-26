"""The colours, named once, for everything that draws.

The TUI's stylesheet and the CLI's status lines are the same product and ought
to look like it. This module holds nothing but the values so that both can have
them: the TUI's theme is built on top of these, and the command line — which
may well be installed without Textual at all — imports them directly.

They are the brand's (cloudmorrow-web: `brand/tokens.css`, and the rules in
`brand/index.html`), which kept the app's neutrals — cool dark glass, lifted
off black and kept close to neutral — and took its two colours from the logo:

- **Blue is the platform.** The cloud the hedgehog sits on. Sky is blue as
  text or a line on the dark ground: links, navigation, the card or tab you
  are on, selection, focus. Cloud is the blue fill, with white on it; Puff is
  Cloud lit (hover), Deep is Cloud in shadow (pressed, and the dark end of
  the gradient).
- **Amber is the person.** Lens, the glasses catching light, fills the one
  primary action on a screen — with ink on it — and marks, as text, the
  names and the things that are yours. One amber button per view; if there
  are two, one of them is wrong.
- **Status** keeps its three: good green, warn orange (orange so it can never
  be mistaken for amber, which means "you" rather than "careful"), bad pink.

What changed from CATHODE, the app's first palette: cyan `#4fe3d7` became Sky,
violet `#a78bfa` became Lens, warn `#ffc857` became `#ff9f5a`, and the
cyan-indigo-pink gradients became Deep → Cloud → Sky. The old names stay, so
the command line keeps working: ACCENT is Sky, SECOND is Lens.

Nothing here is a terminal colour name. "cyan" is whatever the person running
us has decided cyan looks like, and half the time that is a colour we would
never have picked; every one of these goes out as 24-bit RGB instead. See
`cloudmorrow.console`, which is what makes that stick.
"""

from __future__ import annotations

# -- neutrals: the app's own, unchanged by the brand ---------------------------
NIGHT = "#0b0d12"        # behind the logo; the darkest there is
INK = "#14171f"          # the page
SURFACE = "#1f242e"      # panels sitting on it
PANEL = "#272d39"        # panels sitting on those
LINE = "#333a48"         # borders
LINE_BRIGHT = "#4a5364"  # borders that want noticing
TEXT = "#dfe5f0"
MUTED = "#99a1b3"        # soft: secondary text
FAINT = "#667085"        # labels, times, what you read last — between muted and line

# -- blue: the platform ----------------------------------------------------------
DEEP = "#0a3f75"         # cloud in shadow: pressed, the dark end of the gradient
CLOUD = "#1c70b1"        # the brand blue, as a fill with white text on it
PUFF = "#3685bd"         # cloud, lit: hover on a blue fill
SKY = "#5aa6e0"          # blue as text or a line on dark: where you are

# -- amber: the person -------------------------------------------------------------
LENS = "#e0a84c"         # the one primary action's fill, and names as text
ACTION = LENS
ACTION_INK = INK         # the text on an amber fill

# -- status --------------------------------------------------------------------------
GOOD = "#5ce89b"
WARN = "#ff9f5a"         # orange, never to be confused with amber
BAD = "#ff6b81"

# The names the rest of the code has always used.
ACCENT = SKY             # the current thing, focus, the brand in a line of text
SECOND = LENS            # names, and what is yours

# The banner is tinted across these, dark end first: the cloud from its
# shadow to the sky.
GRADIENT = (DEEP, CLOUD, SKY)

# The wordmark too: the same three, as the brand guide has them. Where the
# mark sits on the page's own dark, the painter starts it a little way in
# (see tui/widgets/header.py), since Deep on Ink is a colour you have to be
# told is there.
MARK_GRADIENT = (DEEP, CLOUD, SKY)
