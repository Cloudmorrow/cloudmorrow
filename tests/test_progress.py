"""What an update draws while it waits, and what it draws when nothing can.

The spinner is for a terminal. Everything here also runs into a pipe — a CI
log, a `> out.txt` — and the point of these is that the words still arrive
there without the cursor tricks.
"""

from __future__ import annotations

import io
import re

from rich.console import Console

from cloudmorrow.cli import progress


def plain(buffer: io.StringIO) -> str:
    """What was written, without the escape codes that move the cursor."""
    return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", buffer.getvalue())


def piped() -> tuple[Console, io.StringIO]:
    buffer = io.StringIO()
    return Console(file=buffer, width=90, force_terminal=False), buffer


def terminal() -> tuple[Console, io.StringIO]:
    buffer = io.StringIO()
    return Console(file=buffer, width=90, force_terminal=True), buffer


def test_the_header_says_which_server():
    console, buffer = piped()
    progress.header(console, "update server", "https://bram.example")
    written = plain(buffer)
    assert "cloudmorrow" in written
    assert "update server" in written
    assert "https://bram.example" in written


def test_every_step_reaches_a_pipe():
    """No spinner to replace the last line, so each one has to be printed."""
    console, buffer = piped()
    with progress.Activity(console) as activity:
        activity.step("asking what the server publishes")
        activity.step("installing")
    written = plain(buffer)
    assert "asking what the server publishes" in written
    assert "installing" in written


def test_the_spinner_leaves_nothing_behind_on_a_terminal():
    """It is transient: the result takes its place, not a transcript."""
    console, buffer = terminal()
    with progress.Activity(console) as activity:
        activity.step("installing")
    progress.good(console, "installed")
    # The last line standing is the outcome.
    assert plain(buffer).strip().endswith("installed")


def test_a_package_with_extras_is_not_eaten_as_markup():
    """`cloudmorrow[tui,agent]` is a spec, not a rich tag."""
    from rich.markup import escape

    console, buffer = piped()
    with progress.Activity(console) as activity:
        activity.step(f"installing {escape('cloudmorrow[tui,agent]')}")
    assert "cloudmorrow[tui,agent]" in plain(buffer)


def test_the_waiter_counts_down_rather_than_up():
    console, buffer = terminal()
    with progress.Waiter(console, "waiting", 30) as bar:
        bar.tick()
        assert bar._progress is not None
        task = bar._progress.tasks[0]
        assert task.total == 30
        # Just started, so effectively all of the patience is left.
        assert task.fields["left"] == 30
        assert task.completed < 1


def test_the_waiter_says_its_piece_into_a_pipe_too():
    console, buffer = piped()
    with progress.Waiter(console, "waiting for the server", 30) as bar:
        bar.tick()  # no bar to move, and no crash for trying
    assert "waiting for the server" in plain(buffer)


def test_a_waiter_always_has_a_length():
    """A zero-second wait would be a bar that cannot be drawn."""
    console, _ = terminal()
    with progress.Waiter(console, "waiting", 0) as bar:
        assert bar._progress.tasks[0].total == 1


def test_the_marks_are_what_you_would_expect():
    console, buffer = piped()
    progress.good(console, "done")
    progress.warn(console, "careful")
    progress.bad(console, "no")
    written = plain(buffer)
    assert "✔ done" in written
    assert "! careful" in written
    assert "✘ no" in written
