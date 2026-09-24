"""What an update looks like while it is happening.

An update is mostly waiting — on pip, on git, on a service coming back — and
there are only two things worth showing during the wait: which server you are
talking to, and what is going on right now. So that is all this draws: a
header with the URL, and one live line that changes as the work moves.

The line is transient. When the work finishes it disappears and the result
takes its place, so what is left on screen afterwards is the outcome rather
than a transcript of getting there.

Nothing here assumes a terminal. Piped into a file or a CI log there is no
spinner to animate, so each step prints once instead — the same words, without
the cursor tricks that would otherwise fill the log with escape codes.
"""

from __future__ import annotations

import time

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from cloudmorrow.palette import ACCENT, BAD, GOOD, MUTED, SECOND, WARN

__all__ = ["Activity", "Waiter", "bad", "good", "header", "warn"]


def header(console: Console, what: str, url: str) -> None:
    """The brand, the command, and the server it is about to talk to."""
    console.print(
        f"\n [b {ACCENT}]◈ cloudmorrow[/] [{MUTED}]{what}[/]  [u {SECOND}]{url}[/]\n",
        highlight=False,
    )


def good(console: Console, message: str) -> None:
    console.print(f" [{GOOD}]✔[/] {message}", highlight=False)


def warn(console: Console, message: str) -> None:
    console.print(f" [{WARN}]![/] {message}", highlight=False)


def bad(console: Console, message: str) -> None:
    console.print(f" [{BAD}]✘[/] {message}", highlight=False)


class Activity:
    """A spinner and one line of text, saying what is happening right now."""

    def __init__(self, console: Console) -> None:
        self._console = console
        # No spinner into a pipe: there is nothing there to animate it.
        self._animate = console.is_terminal
        self._progress: Progress | None = None
        self._task: int | None = None

    def __enter__(self) -> Activity:
        if self._animate:
            self._progress = Progress(
                SpinnerColumn(spinner_name="dots", style=ACCENT),
                TextColumn("{task.description}"),
                console=self._console,
                transient=True,
            )
            self._progress.start()
            self._task = self._progress.add_task("", total=None)
        return self

    def step(self, text: str) -> None:
        """Say what is happening now, replacing whatever was happening before."""
        if self._progress is None or self._task is None:
            self._console.print(f" [{MUTED}]{text}[/]", highlight=False)
            return
        self._progress.update(self._task, description=f"[{MUTED}]{text}[/]")

    def __exit__(self, *_exc: object) -> None:
        if self._progress is not None:
            self._progress.stop()
            self._progress = None


class Waiter:
    """A bar for the one wait with a known end: a service coming back.

    It fills towards the moment we give up, so what it shows is how much
    patience is left rather than how much work is done — which is the only
    honest thing to measure when the other end is not talking to us yet.
    """

    def __init__(self, console: Console, text: str, seconds: int) -> None:
        self._console = console
        self._animate = console.is_terminal
        self._text = text
        self._seconds = max(1, seconds)
        self._started = 0.0
        self._progress: Progress | None = None
        self._task: int | None = None

    def __enter__(self) -> Waiter:
        self._started = time.monotonic()
        if self._animate:
            self._progress = Progress(
                SpinnerColumn(spinner_name="dots", style=ACCENT),
                TextColumn(f"[{MUTED}]{self._text}[/]"),
                BarColumn(complete_style=ACCENT, finished_style=WARN, pulse_style=ACCENT),
                TextColumn(f"[{MUTED}]{{task.fields[left]}}s[/]"),
                console=self._console,
                transient=True,
            )
            self._progress.start()
            self._task = self._progress.add_task(
                "", total=self._seconds, left=self._seconds
            )
        else:
            self._console.print(f" [{MUTED}]{self._text}[/]", highlight=False)
        return self

    def tick(self) -> None:
        """Move the bar to wherever the clock has got to."""
        if self._progress is None or self._task is None:
            return
        elapsed = time.monotonic() - self._started
        self._progress.update(
            self._task,
            completed=min(elapsed, self._seconds),
            left=max(0, round(self._seconds - elapsed)),
        )

    def __exit__(self, *_exc: object) -> None:
        if self._progress is not None:
            self._progress.stop()
            self._progress = None
