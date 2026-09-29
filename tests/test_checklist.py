"""The tick-box list the installer asks its questions with."""

from __future__ import annotations

import os
import re
import threading

from cloudmorrow.checklist import Checklist, Item, main, pick

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def on_a_terminal(typed: bytes, ask, *, columns: int = 80, rows: int = 24):
    """Run *ask(terminal)* on a pseudo-terminal that has *typed* waiting.

    What it draws is read off the other side as it comes, or a long redraw
    would fill the terminal's buffer and hang the writer.
    """
    import fcntl
    import struct
    import termios

    main_fd, side = os.openpty()
    fcntl.ioctl(side, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
    # Typed ahead, before the list turns echo and line editing off: set here
    # instead, or the line discipline would echo the keys and eat backspaces.
    attrs = termios.tcgetattr(side)
    attrs[3] &= ~(termios.ECHO | termios.ICANON)
    termios.tcsetattr(side, termios.TCSANOW, attrs)
    drawn = bytearray()

    def drain():
        while True:
            try:
                chunk = os.read(main_fd, 4096)
            except OSError:
                return
            if not chunk:
                return
            drawn.extend(chunk)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        os.write(main_fd, typed)
        result = ask(os.ttyname(side))
    finally:
        os.close(side)
        reader.join(timeout=2)
        os.close(main_fd)
    return result, drawn.decode("utf-8", "replace")


def addresses() -> Checklist:
    return Checklist(
        "Which addresses?",
        [
            Item("0.0.0.0", "Every address", "now and later", on=True, alone=True),
            Item("127.0.0.1", "This machine", "lo"),
            Item("192.168.1.5", "192.168.1.5", "eth0"),
        ],
        other="Other",
        other_pattern=r"[0-9a-fA-F.:]+",
        need_one=True,
        colour=False,
    )


def test_enter_takes_what_is_ticked():
    assert on_a_terminal(b"\r", lambda t: pick(addresses(), t))[0] == ["0.0.0.0"]


def test_ticking_one_address_clears_every_address():
    chosen, _ = on_a_terminal(b"\x1b[B \x1b[B \r", lambda t: pick(addresses(), t))
    assert chosen == ["127.0.0.1", "192.168.1.5"]


def test_ticking_every_address_clears_the_rest():
    chosen, _ = on_a_terminal(b"\x1b[B \x1b[A \r", lambda t: pick(addresses(), t))
    assert chosen == ["0.0.0.0"]


def test_typing_on_other_ticks_it():
    chosen, _ = on_a_terminal(b"\x1b[A10.0.0.9\r", lambda t: pick(addresses(), t))
    assert chosen == ["10.0.0.9"]


def test_other_is_checked_before_enter_is_taken():
    typed = b"\x1b[Anope\r" + b"\x7f" * 4 + b"10.0.0.9\r"
    chosen, drawn = on_a_terminal(typed, lambda t: pick(addresses(), t))
    assert chosen == ["10.0.0.9"]
    assert "does not look right" in drawn


def test_nothing_ticked_is_refused_when_one_is_needed():
    chosen, drawn = on_a_terminal(b" \r\x1b[B \r", lambda t: pick(addresses(), t))
    assert chosen == ["127.0.0.1"]
    assert "Tick at least one" in drawn


def test_no_line_is_wider_than_a_narrow_terminal():
    items = [Item(str(n), f"Quill {n}", "a summary that goes on and on " * 3, on=True) for n in range(30)]
    checklist = Checklist("Which software should your cloud start with?", items, colour=False)
    _, drawn = on_a_terminal(b"\x1b[B" * 25 + b"\r", lambda t: pick(checklist, t), columns=32, rows=12)
    for line in ANSI.sub("", drawn).replace("\r", "\n").split("\n"):
        assert len(line) < 32, line
    assert "↑ more" in drawn


def test_the_command_prints_one_value_a_line(capsys):
    def run(terminal):
        return main(
            [
                "--title",
                "Which?",
                "--terminal",
                terminal,
                "--item",
                "a",
                "A",
                "",
                "--item",
                "b",
                "B",
                "the second",
                "--on",
                "a",
            ]
        )

    code, _ = on_a_terminal(b"\x1b[B \r", run)
    assert code == 0
    assert capsys.readouterr().out == "a\nb\n"
