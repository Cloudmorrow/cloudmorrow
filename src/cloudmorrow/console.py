"""Consoles that decide their own colours.

A terminal's sixteen named colours belong to whoever is running us. Ask for
"cyan" and you get their cyan, which on one machine is our accent and on the
next is a flat blue from a theme somebody downloaded in 2013 — and on a light
background, half of them are illegible. So nothing here ever names one.

Two things make that hold. `color_system="truecolor"` sends 24-bit RGB, so a
colour we pick arrives as the colour we picked. And the theme below maps every
name that rich would otherwise hand to the terminal onto a value from the
palette, which catches markup like `[green]Saved[/]` without every call site
having to spell out a hex code.

Redirect the output and rich drops colour of its own accord, and NO_COLOR is
still honoured — forcing the colour system decides *which* colours, not
whether there are any.
"""

from __future__ import annotations

from rich.console import Console
from rich.theme import Theme

from cloudmorrow.palette import ACCENT, BAD, GOOD, MUTED, SECOND, TEXT, WARN

# What the sixteen names mean here. `dim` is in the list because it is not a
# colour at all — it is a request for the terminal to fade whatever it likes,
# and the answer varies from "slightly grey" to "invisible".
NAMED = {
    "green": GOOD,
    "red": BAD,
    "yellow": WARN,
    "cyan": ACCENT,
    "blue": SECOND,
    "magenta": SECOND,
    "white": TEXT,
    "bright_black": MUTED,
    "dim": MUTED,
}

# The compound styles the tables and banners ask for by name. rich resolves a
# style like "bold cyan" in one piece, so it never reaches the entries above
# and has to be spelled out here as well.
COMPOUND = {
    "bold cyan": f"bold {ACCENT}",
    "bold green": f"bold {GOOD}",
    "bold red": f"bold {BAD}",
    "bold blue": f"bold {SECOND}",
    "dim italic": f"italic {MUTED}",
}

THEME = Theme({**NAMED, **COMPOUND})

# The one a table or a banner should be titled in.
TITLE = f"bold {ACCENT}"

# What text nobody styled comes out as. Without it, "unstyled" means the
# terminal's own foreground, which is the last place the host still gets a
# vote.
#
# The foreground only. Painting INK behind it as well would take the last
# of that vote away, but it lays a dark slab over whatever the terminal is,
# and a command's output is not a window — it is a few lines in the middle
# of somebody's scrollback, and it should sit in it rather than on it. The
# cost is honest: on a pale terminal this text is a pale grey on white and
# hard to read. CATHODE is a dark theme and so is the terminal it was drawn
# for; if that stops being true, this is the line to revisit.
BASE = TEXT


def console(**kwargs: object) -> Console:
    """A rich Console that sends our colours and nobody else's.

    Piping the output still drops colour, and NO_COLOR is still honoured;
    what this settles is which colours, not whether there are any. That
    distinction is why the colour system is only forced once rich has said
    it is writing to a terminal: naming one outright makes rich render
    styles whether or not anybody is there to see them, and
    `cloudmorrow secret get KEY > file` would come out full of escapes.
    """
    kwargs.setdefault("theme", THEME)
    kwargs.setdefault("style", BASE)
    # rich knows about isatty, FORCE_COLOR, jupyter and the rest, so ask it
    # rather than working it out again here. Building one to throw away is
    # cheaper than getting the answer wrong.
    if Console(**kwargs).is_terminal:  # type: ignore[arg-type]
        kwargs.setdefault("color_system", "truecolor")
    return Console(**kwargs)  # type: ignore[arg-type]
