#!/usr/bin/env python3
"""Draw the wordmark for deploy/install-server.sh, as shell.

The installer runs before anything of Cloudmorrow is installed, so it cannot
ask `cloudmorrow.logo` for the mark; it carries a copy, drawn by this. One
colour a letter, stepped along the brand gradient, so the drawing stays a
few lines of printf. A test fails when the copy and this disagree:

    python scripts/installer_banner.py     # paste over the block in the installer
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cloudmorrow import pixelfont  # noqa: E402
from cloudmorrow.logo import TAGLINE, ramp  # noqa: E402
from cloudmorrow.palette import MARK_GRADIENT, MUTED  # noqa: E402

WORD = "CLOUDMORROW"
# Deep, the dark end, is a fill colour and all but vanishes on a dark
# terminal: the letters start a little way in, as the TUI's header does.
SKIP = 3


def _sgr(colour: str, bold: bool = True) -> str:
    n = int(colour.lstrip("#"), 16)
    return f"\\033[{'1;' if bold else ''}38;2;{(n >> 16) & 255};{(n >> 8) & 255};{n & 255}m"


def colours() -> list[str]:
    return [_sgr(c) for c in ramp(MARK_GRADIENT, len(WORD) + SKIP)[SKIP:]]


def block() -> str:
    tints = colours()
    step = pixelfont.WIDTH + pixelfont.GAP
    big = []
    for row in pixelfont.rows(WORD):
        line = "".join(f"{tint}{row[i * step : (i + 1) * step]}" for i, tint in enumerate(tints))
        big.append(f"\tprintf '  {line.rstrip()}\\033[0m\\n'")
    small = "".join(f"{tint}{letter} " for letter, tint in zip(WORD, tints, strict=True)).rstrip()
    width = len(pixelfont.rows(WORD)[0]) + 2
    return "\n".join(
        [
            "# --- the wordmark (scripts/installer_banner.py draws this) ---------------",
            "wordmark() {",
            f'\tif [ "$1" -ge {width} ]; then',
            *("\t" + line for line in big),
            "\telse",
            f"\t\tprintf '  {small}\\033[0m\\n'",
            "\tfi",
            f"\tprintf '  {_sgr(MUTED, bold=False)}{TAGLINE}\\033[0m\\n\\n'",
            "}",
            "# --- end of the wordmark -------------------------------------------------",
        ]
    )


if __name__ == "__main__":
    print(block())
