"""`cm chat`: the kit's thread on the command line — list, show, say.

Driven through the real client against the app under test, as `cm` would
be, with the Chat Quill installed from the local catalog.
"""

from __future__ import annotations

import asyncio
import io

import httpx
import pytest
import typer
from rich.console import Console

from cloudmorrow.cli import quillrun
from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.client.config import ClientConfig
from tests.conftest import ADMIN, GUEST, token_for


def api_for(test_client, token: str) -> CloudmorrowClient:
    api = CloudmorrowClient(ClientConfig(api_url="http://testserver"), token=token)
    api._client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_client.app), base_url="http://testserver"
    )
    return api


@pytest.fixture()
def run(chat_quill, monkeypatch):
    def cm(*argv: str, who=ADMIN) -> str:
        screen_out = Console(file=io.StringIO(), width=200, color_system=None)
        monkeypatch.setattr(quillrun, "out", screen_out)
        monkeypatch.setattr(quillrun, "console", screen_out)
        api = api_for(chat_quill, token_for(chat_quill, *who))

        async def go() -> None:
            try:
                screen = quillrun._screen(await api.quills(), "chat", "")
                await quillrun._act(api, screen, argv[0], list(argv[1:]), "", None, False)
            finally:
                await api.aclose()

        asyncio.run(go())
        return screen_out.file.getvalue()

    return cm


def test_say_then_show_then_list(run, chat_quill):
    said = run("say", "general", "morning", "all")
    assert "Said" in said and "general" in said
    shown = run("show", "general", who=GUEST)
    assert "bram" in shown and "morning all" in shown
    listed = run("list")
    assert "general" in listed and "bram: morning all" in listed


def test_a_direct_conversation_is_found_by_the_other_persons_name(run, chat_quill):
    bram = {"Authorization": f"Bearer {token_for(chat_quill, *ADMIN)}"}
    chat_quill.post("/api/records/channel", headers=bram, json={
        "fields": {"name": "bram & guest", "kind": "direct"}, "scope": "shared",
        "members": ["guest"], "unique": True})
    run("say", "guest", "are you up")
    assert "are you up" in run("show", "bram", who=GUEST)


def test_a_space_that_is_not_there_is_said_plainly(run):
    with pytest.raises(typer.Exit):
        run("show", "nowhere")
