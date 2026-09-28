"""The installer's question about the standard quills, asked on a real terminal."""

from __future__ import annotations

import os
from types import SimpleNamespace

from cloudmorrow.server.cli_quill import _ask

OPTIONS = [
    SimpleNamespace(id="notes", name="Notes", summary="Notes."),
    SimpleNamespace(id="tasks", name="Tasks", summary="Boards."),
    SimpleNamespace(id="chat", name="Chat", summary="Talk."),
]


def ask_on_a_terminal(typed: bytes) -> set[str]:
    # A pseudo-terminal, not a pipe: a terminal is what cannot seek, and
    # that is what the installer hands the question.
    main, side = os.openpty()
    try:
        os.write(main, typed)
        return _ask(OPTIONS, terminal=os.ttyname(side))
    finally:
        os.close(main)
        os.close(side)


def test_enter_keeps_every_one():
    assert ask_on_a_terminal(b"\n") == {"notes", "tasks", "chat"}


def test_numbers_leave_those_out():
    assert ask_on_a_terminal(b"2, 3\n") == {"notes"}


def test_a_wrong_answer_is_asked_again():
    assert ask_on_a_terminal(b"tasks\n9\n1\n") == {"tasks", "chat"}
