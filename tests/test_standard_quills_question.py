"""The installer's question about the standard quills, asked on a real terminal."""

from __future__ import annotations

from types import SimpleNamespace

from cloudmorrow.server.quills.cli import _ask
from tests.test_checklist import on_a_terminal

OPTIONS = [
    SimpleNamespace(id="notes", name="Notes", summary="Notes.", on=True),
    SimpleNamespace(id="tasks", name="Tasks", summary="Boards.", on=True),
    SimpleNamespace(id="chat", name="Chat", summary="Talk.", on=False),
]


def ask(typed: bytes) -> set[str]:
    return on_a_terminal(typed, lambda terminal: _ask(OPTIONS, terminal=terminal))[0]


def test_enter_keeps_the_ones_ticked_to_begin_with():
    assert ask(b"\n") == {"notes", "tasks"}


def test_space_flips_the_one_under_the_cursor():
    assert ask(b"\x1b[B \x1b[B \n") == {"notes", "chat"}


def test_a_ticks_all_then_none():
    assert ask(b"a\n") == {"notes", "tasks", "chat"}
    assert ask(b"aa\n") == set()


def test_without_a_terminal_the_server_gets_the_foundation_quills(tmp_path):
    """`quill choose` with neither --only nor --ask: Files, Calendar, Notes and Tasks."""
    from typer.testing import CliRunner

    from cloudmorrow.server.quills.cli import app
    from tests.conftest import QUILL_CATALOG

    toml = tmp_path / "server.toml"
    toml.write_text(
        f'[server]\nnotes_dir = "{tmp_path / "notes"}"\ndata_dir = "{tmp_path / "data"}"\n'
        f'quill_catalog = "{QUILL_CATALOG}"\n',
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["choose", "--config", str(toml)])
    assert result.exit_code == 0, result.output
    assert "installed: Calendar, Files, Notes, Tasks" in result.output
    assert "Chat" not in result.output.split("Your cloud has")[1]
    assert sorted((tmp_path / "data" / "quills").iterdir()) == sorted(
        tmp_path / "data" / "quills" / q for q in ("calendar", "files", "notes", "tasks")
    )
