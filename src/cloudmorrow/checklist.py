"""A list of boxes to tick, on the terminal: the installer's questions.

    [x] Notes        Pages that link to each other
    [ ] Chat         Talk in spaces
    [x] Other: 10.0.0.4

Arrows (or j and k) move, space ticks, Enter is done. An "Other" row takes
typing, for the answer that is not in the list. Standard library only, so
the installer can run it from a checkout with nothing else installed:

    python -m cloudmorrow.checklist --title "Which addresses?" \\
        --item 0.0.0.0 "Every address" "now and later" --on 0.0.0.0 --alone 0.0.0.0 \\
        --item 127.0.0.1 "This machine" "lo" --other "Other"

prints what was ticked, one value a line, and draws on /dev/tty, so its
output can be captured while the question is on the screen.

Every line is cut to the terminal's width before it is written, never left
to wrap: a wrapped line is one the redraw cannot count, and the list would
walk up the screen. A list taller than the terminal scrolls inside itself.
"""

from __future__ import annotations

import argparse
import os
import re
import select
import sys
import textwrap
from dataclasses import dataclass

from cloudmorrow.palette import FAINT, GOOD, MUTED, SKY, WARN


@dataclass
class Item:
    value: str
    label: str
    detail: str = ""
    on: bool = False
    # Ticking it clears the others, and ticking another clears it: "every
    # address" next to single addresses.
    alone: bool = False


def _sgr(colour: str, bold: bool = False) -> str:
    n = int(colour.lstrip("#"), 16)
    return f"\033[{'1;' if bold else ''}38;2;{(n >> 16) & 255};{(n >> 8) & 255};{n & 255}m"


class _Style:
    def __init__(self, colour: bool) -> None:
        self.on = colour

    def __call__(
        self, text: str, colour: str | None = None, *, bold: bool = False, dim: bool = False
    ) -> tuple[str, str]:
        if not self.on:
            return text, ""
        if colour:
            return text, _sgr(colour, bold)
        return text, "\033[1m" if bold else "\033[2m" if dim else ""


def _fit(segments: list[tuple[str, str]], width: int) -> str:
    """Segments of (text, style) as one line no wider than *width*."""
    out, used = [], 0
    for text, style in segments:
        room = width - used
        if room <= 0:
            break
        if len(text) > room:
            text = text[: max(room - 1, 0)] + "…"
        out.append(f"{style}{text}\033[0m" if style else text)
        used += len(text)
    return "".join(out)


class Checklist:
    def __init__(
        self,
        title: str,
        items: list[Item],
        *,
        other: str | None = None,
        other_hint: str = "type it here",
        other_pattern: str | None = None,
        need_one: bool = False,
        colour: bool = True,
    ) -> None:
        self.title = title
        self.items = items
        self.other = other
        self.other_hint = other_hint
        self.other_pattern = re.compile(other_pattern) if other_pattern else None
        self.other_text = ""
        self.other_on = False
        self.need_one = need_one
        self.cursor = 0
        self.top = 0
        self.problem = ""
        self.style = _Style(colour)
        self.all_key = not other and not any(i.alone for i in items)

    # --- state ------------------------------------------------------------

    @property
    def rows(self) -> int:
        return len(self.items) + (1 if self.other else 0)

    def on_other(self) -> bool:
        return self.other is not None and self.cursor == len(self.items)

    def toggle(self, index: int | None = None) -> None:
        index = self.cursor if index is None else index
        if index == len(self.items):
            self.other_on = not self.other_on
            if self.other_on:
                self._clear_alone()
            return
        item = self.items[index]
        item.on = not item.on
        if item.on and item.alone:
            for other in self.items:
                other.on = other is item
            self.other_on = False
        elif item.on:
            self._clear_alone()

    def _clear_alone(self) -> None:
        for item in self.items:
            if item.alone:
                item.on = False

    def type(self, char: str) -> None:
        self.other_text += char
        if not self.other_on:
            self.toggle(len(self.items))

    def erase(self) -> None:
        self.other_text = self.other_text[:-1]
        if not self.other_text:
            self.other_on = False

    def chosen(self) -> list[str]:
        values = [i.value for i in self.items if i.on]
        text = self.other_text.strip()
        if self.other_on and text:
            values.append(text)
        return values

    def finish(self) -> bool:
        """Whether Enter may end it; if not, says why."""
        text = self.other_text.strip()
        if self.other_on and text and self.other_pattern and not self.other_pattern.fullmatch(text):
            self.problem = f"“{text}” does not look right"
            self.cursor = len(self.items)
            return False
        if self.need_one and not self.chosen():
            self.problem = "Tick at least one"
            return False
        return True

    # --- drawing ------------------------------------------------------------

    def lines(self, width: int, height: int, *, done: bool = False) -> list[str]:
        s = self.style
        width = max(width - 1, 20)
        # The title and the keys wrap, since they are words; a row is cut.
        out = [_fit([s("  "), s(t, bold=True)], width) for t in textwrap.wrap(self.title, width - 2)]
        out.append("")
        label_width = min(max((len(i.label) for i in self.items), default=0), width // 2)
        # Title, blank, rows, blank, footer: the rows get what is left.
        room = max(height - len(out) - 4, 3) if not done else self.rows
        if self.cursor < self.top:
            self.top = self.cursor
        elif self.cursor >= self.top + room:
            self.top = self.cursor - room + 1
        first, last = self.top, min(self.top + room, self.rows)
        if done:
            first, last = 0, self.rows
        for index in range(first, last):
            here = index == self.cursor and not done
            pointer = s("› ", SKY, bold=True) if here else s("  ")
            if index < len(self.items):
                item = self.items[index]
                if done and not item.on:
                    continue
                box = self._box(item.on)
                name = s(item.label.ljust(label_width), SKY if here else None, bold=here)
                detail = s("  " + item.detail, MUTED) if item.detail else s("")
                out.append(_fit([s("  "), pointer, *box, name, detail], width))
            else:
                if done and not (self.other_on and self.other_text.strip()):
                    continue
                box = self._box(self.other_on)
                label = s(f"{self.other}: ", SKY if here else None, bold=here)
                if self.other_text or done:
                    typed = s(self.other_text + ("▏" if here else ""), SKY if here else None)
                else:
                    typed = s(self.other_hint, FAINT)
                out.append(_fit([s("  "), pointer, *box, label, typed], width))
        if done:
            if not any(i.on for i in self.items) and not self.chosen():
                out.append(_fit([s("    "), s("none", MUTED)], width))
            return out
        more = []
        if first > 0:
            more.append("↑ more")
        if last < self.rows:
            more.append("↓ more")
        out.append(_fit([s("    "), s("   ".join(more), FAINT)], width) if more else "")
        if self.problem:
            out.append(_fit([s("  "), s(self.problem, WARN, bold=True)], width))
        else:
            keys = ["↑↓ move", "space ticks"]
            if self.all_key:
                keys.append("a all")
            if self.other:
                keys.append("type for other")
            keys.append("enter done")
            # No-break spaces inside each, so a narrow terminal wraps between them.
            keys = " · ".join(k.replace(" ", "\u00a0") for k in keys)
            for text in textwrap.wrap(keys, width - 2, break_on_hyphens=False):
                out.append(_fit([s("  "), s(text, FAINT)], width))
        return out

    def _box(self, on: bool) -> list[tuple[str, str]]:
        s = self.style
        return [s("["), s("x", GOOD, bold=True) if on else s(" "), s("] ")]

    # --- keys ----------------------------------------------------------------

    def key(self, key: str) -> bool:
        """Handle one key; True when the list is done."""
        self.problem = ""
        typing = self.on_other()
        if key in ("up", "shift-tab") or (key == "k" and not typing):
            self.cursor = (self.cursor - 1) % self.rows
        elif key in ("down", "tab") or (key == "j" and not typing):
            self.cursor = (self.cursor + 1) % self.rows
        elif key == "home":
            self.cursor = 0
        elif key == "end":
            self.cursor = self.rows - 1
        elif key == "enter":
            return self.finish()
        elif key == " ":
            self.toggle()
        elif key == "backspace" and typing:
            self.erase()
        elif typing and len(key) == 1 and key.isprintable():
            self.type(key)
        elif key == "a" and self.all_key:
            every = not all(i.on for i in self.items)
            for item in self.items:
                item.on = every
        elif key == "x":
            self.toggle()
        return False


_SEQUENCES = {
    "[A": "up",
    "OA": "up",
    "[B": "down",
    "OB": "down",
    "[H": "home",
    "OH": "home",
    "[F": "end",
    "OF": "end",
    "[1~": "home",
    "[4~": "end",
    "[Z": "shift-tab",
}


def _read_key(fd: int) -> str:
    char = os.read(fd, 1)
    if char == b"\x1b":
        rest = b""
        while select.select([fd], [], [], 0.05)[0]:
            rest += os.read(fd, 1)
            if rest[-1:].isalpha() or rest[-1:] == b"~":
                break
        return _SEQUENCES.get(rest.decode("ascii", "replace"), "escape")
    if char in (b"\r", b"\n"):
        return "enter"
    if char in (b"\x7f", b"\x08"):
        return "backspace"
    if char == b"\t":
        return "tab"
    if char == b"\x03":
        raise KeyboardInterrupt
    if char == b"\x04":
        return "enter"
    # UTF-8: the rest of a character that did not fit in one byte.
    if char and char[0] >= 0xC0:
        more = 1 if char[0] < 0xE0 else 2 if char[0] < 0xF0 else 3
        char += os.read(fd, more)
    return char.decode("utf-8", "replace")


def pick(checklist: Checklist, terminal: str = "/dev/tty") -> list[str]:
    """Ask on *terminal*; the values ticked when Enter was pressed."""
    import termios
    import tty

    fd = os.open(terminal, os.O_RDWR | os.O_NOCTTY)
    saved = termios.tcgetattr(fd)
    drawn = 0

    def size() -> tuple[int, int]:
        try:
            columns, rows = os.get_terminal_size(fd)
        except OSError:
            columns, rows = 0, 0
        return columns or 80, rows or 24

    def draw(done: bool = False) -> None:
        nonlocal drawn
        lines = checklist.lines(*size(), done=done)
        up = f"\033[{drawn - 1}A" if drawn > 1 else ""
        os.write(fd, (f"\r{up}\033[J" + "\n".join(lines)).encode())
        drawn = len(lines)

    try:
        # TCSANOW, not the default flush: keys typed ahead are answers too.
        tty.setcbreak(fd, termios.TCSANOW)
        os.write(fd, b"\n\033[?25l")
        draw()
        while True:
            if checklist.key(_read_key(fd)):
                break
            draw()
        draw(done=True)
        return checklist.chosen()
    finally:
        os.write(fd, b"\033[?25h\n\n")
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        os.close(fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cloudmorrow.checklist", description=__doc__.split("\n")[0])
    parser.add_argument("--title", required=True)
    parser.add_argument("--item", nargs=3, action="append", default=[], metavar=("VALUE", "LABEL", "DETAIL"))
    parser.add_argument("--on", action="append", default=[], help="a value ticked to begin with")
    parser.add_argument("--alone", action="append", default=[], help="a value that is not ticked with others")
    parser.add_argument("--other", help="label for a row that takes typing")
    parser.add_argument("--other-hint", default="type it here")
    parser.add_argument("--other-pattern", help="what typed text has to match")
    parser.add_argument("--need-one", action="store_true", help="refuse Enter with nothing ticked")
    parser.add_argument("--terminal", default="/dev/tty")
    args = parser.parse_args(argv)
    items = [
        Item(value, label, detail, on=value in args.on, alone=value in args.alone) for value, label, detail in args.item
    ]
    checklist = Checklist(
        args.title,
        items,
        other=args.other,
        other_hint=args.other_hint,
        other_pattern=args.other_pattern,
        need_one=args.need_one,
        colour="NO_COLOR" not in os.environ,
    )
    try:
        chosen = pick(checklist, args.terminal)
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        print(f"no terminal to ask on: {exc}", file=sys.stderr)
        return 2
    for value in chosen:
        print(value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
