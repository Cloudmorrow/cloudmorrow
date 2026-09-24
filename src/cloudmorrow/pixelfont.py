"""The Cloudmorrow wordmark, drawn in dots.

Five dots across and seven down per letter, which is the smallest grid that
still gives a G a crossbar. The same glyphs the web app draws its mark with —
`server/web/brand.js` holds the other copy, and a test fails if the two ever
disagree — because the mark on the phone and the mark above a prompt should
be the same drawing, not two drawings of the same idea.

In a terminal each cell is about twice as tall as it is wide, so a dot per
cell would give letters stretched to twice their height. Half blocks fix it:
one cell carries two dots, an upper and a lower, and the letters come out
square. Seven rows of dots is four rows of cells.
"""

from __future__ import annotations

# Upper half set, lower half set → the character that fills that much of a cell.
HALVES = {
    (False, False): " ",
    (True, False): "\u2580",
    (False, True): "\u2584",
    (True, True): "\u2588",
}

ROWS = 7      # dots down, per letter
WIDTH = 5     # dots across, per letter
GAP = 1       # dots between two letters
SPACE = 3     # dots a space is worth

GLYPHS: dict[str, tuple[str, ...]] = {
    "A": (
        ".XXX.",
        "X...X",
        "X...X",
        "XXXXX",
        "X...X",
        "X...X",
        "X...X",
    ),
    "B": (
        "XXXX.",
        "X...X",
        "X...X",
        "XXXX.",
        "X...X",
        "X...X",
        "XXXX.",
    ),
    "C": (
        ".XXX.",
        "X...X",
        "X....",
        "X....",
        "X....",
        "X...X",
        ".XXX.",
    ),
    "D": (
        "XXX..",
        "X..X.",
        "X...X",
        "X...X",
        "X...X",
        "X..X.",
        "XXX..",
    ),
    "E": (
        "XXXXX",
        "X....",
        "X....",
        "XXXX.",
        "X....",
        "X....",
        "XXXXX",
    ),
    "F": (
        "XXXXX",
        "X....",
        "X....",
        "XXXX.",
        "X....",
        "X....",
        "X....",
    ),
    "G": (
        ".XXX.",
        "X...X",
        "X....",
        "X.XXX",
        "X...X",
        "X...X",
        ".XXX.",
    ),
    "H": (
        "X...X",
        "X...X",
        "X...X",
        "XXXXX",
        "X...X",
        "X...X",
        "X...X",
    ),
    "I": (
        "XXXXX",
        "..X..",
        "..X..",
        "..X..",
        "..X..",
        "..X..",
        "XXXXX",
    ),
    "J": (
        "..XXX",
        "...X.",
        "...X.",
        "...X.",
        "...X.",
        "X..X.",
        ".XX..",
    ),
    "K": (
        "X...X",
        "X..X.",
        "X.X..",
        "XX...",
        "X.X..",
        "X..X.",
        "X...X",
    ),
    "L": (
        "X....",
        "X....",
        "X....",
        "X....",
        "X....",
        "X....",
        "XXXXX",
    ),
    "M": (
        "X...X",
        "XX.XX",
        "X.X.X",
        "X.X.X",
        "X...X",
        "X...X",
        "X...X",
    ),
    "N": (
        "X...X",
        "XX..X",
        "X.X.X",
        "X..XX",
        "X...X",
        "X...X",
        "X...X",
    ),
    "O": (
        ".XXX.",
        "X...X",
        "X...X",
        "X...X",
        "X...X",
        "X...X",
        ".XXX.",
    ),
    "P": (
        "XXXX.",
        "X...X",
        "X...X",
        "XXXX.",
        "X....",
        "X....",
        "X....",
    ),
    "Q": (
        ".XXX.",
        "X...X",
        "X...X",
        "X...X",
        "X.X.X",
        "X..X.",
        ".XX.X",
    ),
    "R": (
        "XXXX.",
        "X...X",
        "X...X",
        "XXXX.",
        "X.X..",
        "X..X.",
        "X...X",
    ),
    "S": (
        ".XXXX",
        "X....",
        "X....",
        ".XXX.",
        "....X",
        "....X",
        "XXXX.",
    ),
    "T": (
        "XXXXX",
        "..X..",
        "..X..",
        "..X..",
        "..X..",
        "..X..",
        "..X..",
    ),
    "U": (
        "X...X",
        "X...X",
        "X...X",
        "X...X",
        "X...X",
        "X...X",
        ".XXX.",
    ),
    "V": (
        "X...X",
        "X...X",
        "X...X",
        "X...X",
        "X...X",
        ".X.X.",
        "..X..",
    ),
    "W": (
        "X...X",
        "X...X",
        "X...X",
        "X.X.X",
        "X.X.X",
        "XX.XX",
        "X...X",
    ),
    "X": (
        "X...X",
        "X...X",
        ".X.X.",
        "..X..",
        ".X.X.",
        "X...X",
        "X...X",
    ),
    "Y": (
        "X...X",
        "X...X",
        ".X.X.",
        "..X..",
        "..X..",
        "..X..",
        "..X..",
    ),
    "Z": (
        "XXXXX",
        "....X",
        "...X.",
        "..X..",
        ".X...",
        "X....",
        "XXXXX",
    ),
    "0": (
        ".XXX.",
        "X..XX",
        "X.X.X",
        "X.X.X",
        "X.X.X",
        "XX..X",
        ".XXX.",
    ),
    "1": (
        "..X..",
        ".XX..",
        "..X..",
        "..X..",
        "..X..",
        "..X..",
        ".XXX.",
    ),
    "2": (
        ".XXX.",
        "X...X",
        "....X",
        "...X.",
        "..X..",
        ".X...",
        "XXXXX",
    ),
    "3": (
        "XXXXX",
        "...X.",
        "..XX.",
        "....X",
        "....X",
        "X...X",
        ".XXX.",
    ),
    "4": (
        "...X.",
        "..XX.",
        ".X.X.",
        "X..X.",
        "XXXXX",
        "...X.",
        "...X.",
    ),
    "5": (
        "XXXXX",
        "X....",
        "XXXX.",
        "....X",
        "....X",
        "X...X",
        ".XXX.",
    ),
    "6": (
        "..XX.",
        ".X...",
        "X....",
        "XXXX.",
        "X...X",
        "X...X",
        ".XXX.",
    ),
    "7": (
        "XXXXX",
        "....X",
        "...X.",
        "..X..",
        ".X...",
        ".X...",
        ".X...",
    ),
    "8": (
        ".XXX.",
        "X...X",
        "X...X",
        ".XXX.",
        "X...X",
        "X...X",
        ".XXX.",
    ),
    "9": (
        ".XXX.",
        "X...X",
        "X...X",
        ".XXXX",
        "....X",
        "...X.",
        ".XX..",
    ),
    ".": (
        ".....",
        ".....",
        ".....",
        ".....",
        ".....",
        "..XX.",
        "..XX.",
    ),
    "-": (
        ".....",
        ".....",
        ".....",
        ".XXX.",
        ".....",
        ".....",
        ".....",
    ),
    "/": (
        "....X",
        "....X",
        "...X.",
        "..X..",
        ".X...",
        "X....",
        "X....",
    ),
    "'": (
        "..X..",
        "..X..",
        ".....",
        ".....",
        ".....",
        ".....",
        ".....",
    ),
    "!": (
        "..X..",
        "..X..",
        "..X..",
        "..X..",
        "..X..",
        ".....",
        "..X..",
    ),
    "?": (
        ".XXX.",
        "X...X",
        "....X",
        "...X.",
        "..X..",
        ".....",
        "..X..",
    ),
}


def columns(text: str) -> list[list[bool]]:
    """The word as upright columns of dots, left to right.

    Columns rather than rows because that is the axis a gradient runs along:
    every dot in a column is the same colour, whichever row of cells it ends
    up in. Anything the font cannot spell is dropped rather than drawn as a
    hole, so a stray character cannot put a gap in the middle of the mark.
    """
    blank = [False] * ROWS
    out: list[list[bool]] = []
    for char in text.upper():
        if char == " ":
            out.extend([blank[:] for _ in range(SPACE)])
            continue
        glyph = GLYPHS.get(char)
        if glyph is None:
            continue
        for x in range(WIDTH):
            out.append([glyph[y][x] == "X" for y in range(ROWS)])
        out.extend([blank[:] for _ in range(GAP)])
    while out and not any(out[-1]):
        out.pop()
    return out


def rows(text: str) -> list[str]:
    """The word as lines of half blocks — four of them, for seven dots."""
    grid = columns(text)
    lines = []
    for top in range(0, ROWS, 2):
        bottom = top + 1
        lines.append("".join(
            HALVES[(column[top], bottom < ROWS and column[bottom])] for column in grid
        ))
    return lines
