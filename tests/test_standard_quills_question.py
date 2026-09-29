"""The installer's question about the standard quills, asked on a real terminal."""

from __future__ import annotations

from types import SimpleNamespace

from cloudmorrow.server.quills.cli import _ask
from tests.test_checklist import on_a_terminal

OPTIONS = [
    SimpleNamespace(id="notes", name="Notes", summary="Notes."),
    SimpleNamespace(id="tasks", name="Tasks", summary="Boards."),
    SimpleNamespace(id="chat", name="Chat", summary="Talk."),
]


def ask(typed: bytes) -> set[str]:
    return on_a_terminal(typed, lambda terminal: _ask(OPTIONS, terminal=terminal))[0]


def test_enter_keeps_every_one():
    assert ask(b"\n") == {"notes", "tasks", "chat"}


def test_space_unticks_the_one_under_the_cursor():
    assert ask(b"\x1b[B \x1b[B \n") == {"notes"}


def test_a_ticks_none_then_all():
    assert ask(b"a\n") == set()
    assert ask(b"aa\n") == {"notes", "tasks", "chat"}
