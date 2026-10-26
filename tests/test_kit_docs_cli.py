"""`cm <quill> …` for a document: listed, shown as Markdown, added, edited, exported, imported; a real server."""

from __future__ import annotations

import asyncio
import io
import json

import httpx
import pytest
import typer
from fastapi.testclient import TestClient
from rich.console import Console

from cloudmorrow.cli import quillrun
from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.client.config import ClientConfig
from cloudmorrow.quill import docs, docx
from cloudmorrow.server.app import create_app
from tests.conftest import ADMIN, token_for


@pytest.fixture()
def docs_quill(config, users) -> TestClient:
    client = TestClient(create_app(config))
    client.app.state.cloudmorrow.quills.install_from_catalog("docs")
    return client


@pytest.fixture()
def cm(docs_quill, monkeypatch):
    def run(*argv: str, plain: bool = False, raw: bool = False) -> str:
        screen_out = Console(file=io.StringIO(), width=200, color_system=None)
        monkeypatch.setattr(quillrun, "out", screen_out)
        monkeypatch.setattr(quillrun, "console", screen_out)
        monkeypatch.setattr(quillrun, "emit", screen_out.file.write)
        api = CloudmorrowClient(ClientConfig(api_url="http://testserver"), token=token_for(docs_quill, *ADMIN))
        api._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=docs_quill.app), base_url="http://testserver")

        async def go() -> None:
            try:
                await quillrun.dispatch(api, "docs", argv[0], list(argv[1:]), plain=plain, raw=raw)
            finally:
                await api.aclose()

        asyncio.run(go())
        return screen_out.file.getvalue()

    return run


def test_the_welcome_document_is_listed_and_shown_as_markdown(cm):
    assert "Welcome" in cm("list")
    shown = cm("show", "Welcome")
    assert shown.startswith("# Welcome to Docs\n\nA document is a page of **headings**, paragraphs")
    assert "- Every document is a .docs file" in shown
    assert json.loads(cm("show", "Welcome", raw=True))["blocks"][0]["kind"] == "heading"
    assert json.loads(cm("show", "Welcome", plain=True))["fields"]["path"] == "Documents/Welcome.docs"


def test_a_document_is_added_edited_renamed_and_deleted(cm):
    assert "Added Letter" in cm("add", "Letter", "# Dear you", "", "A *short* note.")
    assert cm("show", "Letter") == "# Dear you\n\nA *short* note.\n"
    assert "Saved Letter" in cm("edit", "Letter", "# Dear you\n\n- one\n- two\n")
    assert json.loads(cm("show", "Letter", raw=True))["blocks"][1] == {"kind": "bullet", "runs": [{"text": "one"}]}
    assert "Saved Offer" in cm("set", "Letter", "name=Offer")
    assert "Offer" in cm("list") and "Letter" not in cm("list")
    assert "Offer" in cm("search", "two")
    assert "Deleted Offer" in cm("delete", "Offer")
    with pytest.raises(typer.Exit):
        cm("show", "Offer")
    with pytest.raises(typer.Exit):
        cm("add", "welcome", "x")


def test_export_writes_word_and_import_reads_it(cm, tmp_path):
    target = tmp_path / "out" / "Welcome.docx"
    assert "Wrote" in cm("export", "Welcome", str(target))
    welcome = docx.read_docx(target.read_bytes())
    assert welcome.blocks[0] == {"kind": "heading", "level": 1, "runs": [{"text": "Welcome to Docs"}]}
    md = tmp_path / "Welcome.md"
    cm("export", "Welcome", str(md))
    assert md.read_text(encoding="utf-8").startswith("# Welcome to Docs\n")
    pdf = tmp_path / "Welcome.pdf"
    cm("export", "Welcome", str(pdf))
    assert pdf.read_bytes().startswith(b"%PDF-")
    # A document anywhere on the cloud, by share:path.
    assert cm("show", "my-files:Documents/Welcome.docs").startswith("# Welcome to Docs\n")
    with pytest.raises(typer.Exit):
        cm("show", "my-files:Documents/Nope.docs")
    # Imported, a Word file becomes a document; a Markdown file too.
    assert "Imported Again" in cm("import", str(target), "Again")
    assert json.loads(cm("show", "Again", raw=True))["blocks"] == welcome.blocks
    (tmp_path / "Plan.md").write_text("# Plan\n\n1. first\n", encoding="utf-8")
    assert "Imported Plan" in cm("import", str(tmp_path / "Plan.md"))
    assert cm("show", "Plan") == "# Plan\n\n1. first\n"
    with pytest.raises(typer.Exit):
        cm("import", str(tmp_path / "nope.docx"))
    listing = cm("list")
    assert "Again" in listing and "Plan" in listing
    assert docs.Doc.from_text(cm("show", "Plan", raw=True)).text == "Plan\nfirst"
