"""A short form on the terminal: the installer's "where should it go?".

    › Code      /opt/cloudmorrow▏      the checkout and the virtualenv
      Settings  /etc/cloudmorrow       server.toml and the sealing key
      Data      /var/lib/cloudmorrow   files/, the database, keys and quills

Every row is a field with a default in it. Arrows move, typing changes the
field on the row, Backspace erases, Ctrl-U puts the default back, Enter is
done. Nobody has to change anything: Enter on the first screen takes the
defaults, which is what most people want. It is drawn the way the list of
boxes to tick is (cloudmorrow.checklist), and like it needs nothing but the
standard library, so the installer can run it before anything is installed:

    python -m cloudmorrow.form --title "Where should it go?" \\
        --field code Code /opt/cloudmorrow "the checkout and the virtualenv" \\
        --field data Data /var/lib/cloudmorrow "the database, keys and quills" \\
        --pattern '/\\S*' --problem "an absolute path, please"

prints one "key=value" a line, in the order the fields were given, and
draws on /dev/tty, so its output can be captured while the form is up.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import textwrap
from dataclasses import dataclass

from cloudmorrow.checklist import _fit, _read_key, _Style
from cloudmorrow.palette import FAINT, MUTED, SKY, WARN


@dataclass
class Field:
    key: str
    label: str
    default: str
    detail: str = ""
    # What has been typed. Empty means the default: Ctrl-U gets back to it,
    # and so does erasing everything.
    text: str | None = None

    @property
    def value(self) -> str:
        return self.default if self.text is None else self.text


class Form:
    def __init__(
        self,
        title: str,
        fields: list[Field],
        *,
        pattern: str | None = None,
        problem: str = "that does not look right",
        colour: bool = True,
    ) -> None:
        self.title = title
        self.fields = fields
        self.pattern = re.compile(pattern) if pattern else None
        self.problem_text = problem
        self.cursor = 0
        self.top = 0
        self.problem = ""
        self.style = _Style(colour)

    # --- state ------------------------------------------------------------

    @property
    def rows(self) -> int:
        return len(self.fields)

    @property
    def field(self) -> Field:
        return self.fields[self.cursor]

    def type(self, char: str) -> None:
        self.field.text = (self.field.text or "") + char

    def erase(self) -> None:
        if self.field.text is None:
            # Backspace on the default starts from it, minus a character:
            # what somebody changing the end of a path expects.
            self.field.text = self.field.default[:-1]
        else:
            self.field.text = self.field.text[:-1]

    def reset(self) -> None:
        self.field.text = None

    def values(self) -> dict[str, str]:
        return {f.key: f.value.strip() for f in self.fields}

    def finish(self) -> bool:
        """Whether Enter may end it; if not, says why and goes to the row."""
        for index, field in enumerate(self.fields):
            value = field.value.strip()
            if not value or (self.pattern and not self.pattern.fullmatch(value)):
                self.problem = f"{field.label}: {self.problem_text}"
                self.cursor = index
                return False
        seen: dict[str, str] = {}
        for field in self.fields:
            value = field.value.strip().rstrip("/") or "/"
            if value in seen:
                self.problem = f"{field.label} and {seen[value]} are the same place"
                self.cursor = self.fields.index(field)
                return False
            seen[value] = field.label
        return True

    # --- drawing ------------------------------------------------------------

    def lines(self, width: int, height: int, *, done: bool = False) -> list[str]:
        s = self.style
        width = max(width - 1, 20)
        out = [_fit([s("  "), s(t, bold=True)], width) for t in textwrap.wrap(self.title, width - 2)]
        out.append("")
        label_width = min(max((len(f.label) for f in self.fields), default=0), width // 3)
        # Wide enough for the defaults too, so the details stay put while a
        # path is being shortened.
        value_width = min(max((max(len(f.value), len(f.default)) for f in self.fields), default=0) + 3, width // 2)
        room = max(height - len(out) - 4, 3) if not done else self.rows
        if self.cursor < self.top:
            self.top = self.cursor
        elif self.cursor >= self.top + room:
            self.top = self.cursor - room + 1
        first, last = self.top, min(self.top + room, self.rows)
        if done:
            first, last = 0, self.rows
        for index in range(first, last):
            field = self.fields[index]
            here = index == self.cursor and not done
            pointer = s("› ", SKY, bold=True) if here else s("  ")
            name = s(field.label.ljust(label_width) + "  ", SKY if here else None, bold=here)
            if field.text is None:
                # The default, until something is typed: quiet, so a changed
                # field stands out from the ones left alone.
                value = s(field.default, None if done else FAINT)
            else:
                value = s(field.text, SKY if here else None)
            caret = s("▏", SKY) if here else s("")
            pad = s(" " * max(value_width - len(field.value) - (1 if here else 0), 1))
            detail = s(field.detail, MUTED) if field.detail else s("")
            out.append(_fit([s("  "), pointer, name, value, caret, pad, detail], width))
        if done:
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
            keys = ["↑↓ move", "type to change", "ctrl-u the default", "enter done"]
            keys = " · ".join(k.replace(" ", " ") for k in keys)
            for text in textwrap.wrap(keys, width - 2, break_on_hyphens=False):
                out.append(_fit([s("  "), s(text, FAINT)], width))
        return out

    # --- keys ----------------------------------------------------------------

    def key(self, key: str) -> bool:
        """Handle one key; True when the form is done."""
        self.problem = ""
        if key in ("up", "shift-tab"):
            self.cursor = (self.cursor - 1) % self.rows
        elif key in ("down", "tab"):
            self.cursor = (self.cursor + 1) % self.rows
        elif key == "home":
            self.cursor = 0
        elif key == "end":
            self.cursor = self.rows - 1
        elif key == "enter":
            return self.finish()
        elif key == "backspace":
            self.erase()
        elif key == "\x15":  # Ctrl-U
            self.reset()
        elif len(key) == 1 and key.isprintable():
            self.type(key)
        return False


def fill(form: Form, terminal: str = "/dev/tty") -> dict[str, str]:
    """Ask on *terminal*; the fields' values when Enter was pressed."""
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
        lines = form.lines(*size(), done=done)
        up = f"\033[{drawn - 1}A" if drawn > 1 else ""
        os.write(fd, (f"\r{up}\033[J" + "\n".join(lines)).encode())
        drawn = len(lines)

    try:
        tty.setcbreak(fd, termios.TCSANOW)
        os.write(fd, b"\n\033[?25l")
        draw()
        while True:
            if form.key(_read_key(fd)):
                break
            draw()
        draw(done=True)
        return form.values()
    finally:
        os.write(fd, b"\033[?25h\n\n")
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        os.close(fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cloudmorrow.form", description=__doc__.split("\n")[0])
    parser.add_argument("--title", required=True)
    parser.add_argument(
        "--field", nargs=4, action="append", default=[], required=True, metavar=("KEY", "LABEL", "DEFAULT", "DETAIL")
    )
    parser.add_argument("--pattern", help="what every value has to match")
    parser.add_argument("--problem", default="that does not look right", help="what to say when it does not")
    parser.add_argument("--terminal", default="/dev/tty")
    args = parser.parse_args(argv)
    form = Form(
        args.title,
        [Field(key, label, default, detail) for key, label, default, detail in args.field],
        pattern=args.pattern,
        problem=args.problem,
        colour="NO_COLOR" not in os.environ,
    )
    try:
        values = fill(form, args.terminal)
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        print(f"no terminal to ask on: {exc}", file=sys.stderr)
        return 2
    for key, value in values.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
