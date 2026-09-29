"""A QR code in a terminal: two rows of modules to a line of half-blocks.

For the link code (Administration → Access, `cm access link`) and the login
server a phone's Tailscale app is pointed at (Invite a device), where the web
app draws the same codes as SVG (web/qr.js). segno does the encoding; it is
pure Python and in the `tui` extra, and without it there is no picture, only
the text beside it, which says the same.

Dark modules are drawn dark on a light ground whatever the theme, with the
quiet zone the standard asks for, because a camera reads contrast.
"""

from __future__ import annotations

QUIET = 2


def qr_lines(text: str) -> list[str]:
    """The code as lines of `█▀▄ `, dark on light; empty when segno is not here."""
    try:
        import segno
    except ImportError:
        return []
    code = segno.make(text, error="m", micro=False)
    rows = [[bool(cell) for cell in row] for row in code.matrix]
    width = len(rows[0]) + QUIET * 2
    blank = [False] * width
    grid = [blank] * QUIET + [[False] * QUIET + row + [False] * QUIET for row in rows] + [blank] * (QUIET + 1)
    lines = []
    for top, bottom in zip(grid[0::2], grid[1::2], strict=False):
        # Light ground: a character's foreground is the light part, so a dark
        # module is a gap in it. Drawn with the colours swapped by the caller.
        lines.append("".join(" ▄▀█"[(not a) * 2 + (not b)] for a, b in zip(top, bottom, strict=True)))
    return lines


def qr_markup(text: str) -> str:
    """The code as Rich markup, white blocks on black: the gaps are the dark modules."""
    lines = qr_lines(text)
    return "\n".join(f"[#ffffff on #000000]{line}[/]" for line in lines)
