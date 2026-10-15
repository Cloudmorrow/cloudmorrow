"""`cm channels`: reply, react, pin and show --thread on the command line.

Driven through the real client against the app under test, as `cm` would
be, with the Channels Quill installed from the local catalog.
"""

from __future__ import annotations

import asyncio
import io

import pytest
import typer
from rich.console import Console

from cloudmorrow.cli import quillrun
from tests.conftest import ADMIN, GUEST, token_for
from tests.test_quill_chat_cli import api_for


@pytest.fixture()
def channels_quill(client):
    client.app.state.cloudmorrow.quills.install_from_catalog("channels")
    return client


@pytest.fixture()
def run(channels_quill, monkeypatch):
    def cm(*argv: str, who=ADMIN) -> str:
        screen_out = Console(file=io.StringIO(), width=200, color_system=None)
        monkeypatch.setattr(quillrun, "out", screen_out)
        monkeypatch.setattr(quillrun, "console", screen_out)
        api = api_for(channels_quill, token_for(channels_quill, *who))

        async def go() -> None:
            try:
                screen = quillrun._screen(await api.quills(), "channels", "")
                await quillrun._act(api, screen, argv[0], list(argv[1:]), "", None, False)
            finally:
                await api.aclose()

        asyncio.run(go())
        return screen_out.file.getvalue()

    return cm


def line_id(shown: str, words: str) -> str:
    """The margin's four characters before the line that says *words*."""
    for row in shown.splitlines():
        if words in row:
            return row.split()[0]
    raise AssertionError(f"{words!r} is not in:\n{shown}")


def test_reply_shows_under_the_line_and_as_a_thread(run):
    run("say", "general", "lunch?")
    shown = run("show", "general", who=GUEST)
    parent = line_id(shown, "lunch?")
    replied = run("reply", "general", parent, "yes", "please", who=GUEST)
    assert "Replied to bram" in replied
    shown = run("show", "general")
    assert shown.index("lunch?") < shown.index("↳") < shown.index("yes please")
    thread = run("show", "general", "--thread", parent)
    assert "thread of" in thread and "lunch?" in thread and "yes please" in thread
    # A second reply, from the reply's own id, lands in the same thread.
    run("reply", "general", line_id(shown, "yes please"), "noon")
    assert "noon" in run("show", "general", "--thread", parent)


def test_react_toggles_and_is_counted(run):
    run("say", "general", "shipped")
    parent = line_id(run("show", "general"), "shipped")
    assert "Reacted" in run("react", "general", parent, "👍", who=GUEST)
    assert "👍 1" in run("show", "general")
    assert "👍 1*" in run("show", "general", who=GUEST), "yours is marked"
    assert "Took back" in run("react", "general", parent, "👍", who=GUEST)
    assert "👍" not in run("show", "general")


def test_pin_marks_the_line_and_unpins_again(run):
    run("say", "general", "read me", who=GUEST)
    parent = line_id(run("show", "general"), "read me")
    assert "Pinned" in run("pin", "general", parent)
    assert "📌" in run("show", "general")
    assert "Unpinned" in run("pin", "general", parent, who=GUEST)
    assert "📌" not in run("show", "general")


def test_a_line_that_is_not_there_is_said_plainly(run):
    with pytest.raises(typer.Exit):
        run("reply", "general", "zzzz", "hello")
