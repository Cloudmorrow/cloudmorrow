"""`cm notes …`: the Notes Quill on the command line, through the kit's editor actions.

`cm note` (the old command, singular) stays as it was; `cm notes` is the
Quill's, drawn by quillrun from the `editor` screen like any Quill's command.
"""

from __future__ import annotations

import httpx
import pytest
import typer
from typer.testing import CliRunner

from cloudmorrow.cli import quillrun
from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.client.config import ClientConfig
from tests.conftest import ADMIN, token_for

runner = CliRunner()


@pytest.fixture()
def cm(notes_quill, monkeypatch):
    client = notes_quill
    token = token_for(client, *ADMIN)

    def api_for():
        api = CloudmorrowClient(ClientConfig(api_url="http://testserver"), token=token)
        api._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://testserver"
        )
        return None, api

    monkeypatch.setattr(quillrun, "client", api_for)
    app = typer.Typer()
    app.command(context_settings={"allow_interspersed_args": True})(quillrun.main)

    def invoke(*argv: str, stdin: str | None = None):
        return runner.invoke(app, list(argv), input=stdin)

    invoke.client = client
    invoke.headers = {"Authorization": f"Bearer {token}"}
    return invoke


def test_add_show_and_list_by_path(cm):
    added = cm("notes", "add", "ideas/garden", stdin="# garden\n\nRaised beds.\n")
    assert added.exit_code == 0, added.output
    assert "Added ideas/garden" in added.output
    shown = cm("notes", "show", "ideas/garden")
    assert shown.exit_code == 0 and shown.output == "# garden\n\nRaised beds.\n"
    listed = cm("notes", "list")
    assert "ideas/garden" in listed.output and "welcome" in listed.output
    # The same file the old command and the notes API read.
    note = cm.client.get("/api/notes/file/ideas/garden.md", headers=cm.headers).json()
    assert note["content"] == "# garden\n\nRaised beds.\n"


def test_edit_replaces_the_text_and_a_second_add_is_refused(cm):
    cm("notes", "add", "log", "first")
    edited = cm("notes", "edit", "log", stdin="second\n")
    assert edited.exit_code == 0, edited.output
    assert cm("notes", "show", "log").output == "second\n"
    again = cm("notes", "add", "log", "third")
    assert again.exit_code == 1 and "already" in again.output


def test_search_says_where_it_matched(cm):
    cm("notes", "add", "plants", "Tomatoes in June.")
    found = cm("notes", "search", "tomatoes")
    assert found.exit_code == 0
    assert "plants" in found.output and "Tomatoes in June." in found.output


def test_a_page_that_is_not_there_is_said_plainly(cm):
    missing = cm("notes", "show", "nowhere")
    assert missing.exit_code == 1 and "no page matches" in missing.output


def test_delete(cm):
    cm("notes", "add", "scratch", "x")
    assert cm("notes", "delete", "scratch").exit_code == 0
    assert "scratch" not in cm("notes", "list").output
