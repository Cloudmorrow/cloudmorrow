"""`cm <quill> …` for a sheet: .cell files listed, added, shown worked out, a cell set, against a real server."""

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
from cloudmorrow.server.app import create_app
from tests.conftest import ADMIN, token_for


@pytest.fixture()
def cells_quill(config, users) -> TestClient:
    client = TestClient(create_app(config))
    client.app.state.cloudmorrow.quills.install_from_catalog("cells")
    return client


@pytest.fixture()
def cm(cells_quill, monkeypatch):
    def run(*argv: str, plain: bool = False, raw: bool = False) -> str:
        screen_out = Console(file=io.StringIO(), width=200, color_system=None)
        monkeypatch.setattr(quillrun, "out", screen_out)
        monkeypatch.setattr(quillrun, "console", screen_out)
        monkeypatch.setattr(quillrun, "emit", screen_out.file.write)
        api = CloudmorrowClient(ClientConfig(api_url="http://testserver"), token=token_for(cells_quill, *ADMIN))
        api._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=cells_quill.app), base_url="http://testserver"
        )

        async def go() -> None:
            try:
                await quillrun.dispatch(api, "cells", argv[0], list(argv[1:]), plain=plain, raw=raw)
            finally:
                await api.aclose()

        asyncio.run(go())
        return screen_out.file.getvalue()

    return run


def test_the_welcome_sheet_is_listed_and_shown_worked_out(cm):
    assert "Budget" in cm("list")
    shown = cm("show", "Budget")
    assert "Rent" in shown and "1200" in shown and "1770" in shown, shown
    assert "=SUM(B1:B3)" in cm("show", "Budget", raw=True)
    assert cm("get", "Budget", "b5") == "1770\n"
    assert cm("get", "Budget", "B5", raw=True) == "=SUM(B1:B3)\n"
    plain = json.loads(cm("get", "Budget", "B5", plain=True))
    assert plain == {"raw": "=SUM(B1:B3)", "value": 1770.0, "shown": "1770"}


def test_a_cell_is_set_cleared_and_the_sheet_renamed(cm):
    assert "B3 1000" in cm("set", "Budget", "B3", "1000")
    assert cm("get", "Budget", "B5") == "2650\n"
    assert "cleared" in cm("set", "Budget", "B3", "")
    assert cm("get", "Budget", "B5") == "1650\n"
    assert "#DIV/0!" in cm("set", "Budget", "C1", "=1/0")
    plain = json.loads(cm("show", "Budget", plain=True))
    assert plain["C1"] == {"raw": "=1/0", "value": {"error": "#DIV/0!"}, "shown": "#DIV/0!"}
    assert "Saved Costs" in cm("set", "Budget", "name=Costs"), "renamed: the file is Documents/Costs.cell now"
    listed = cm("list")
    assert "Costs" in listed and "Budget" not in listed
    assert cm("get", "Costs", "B5") == "1650\n"


def test_a_sheet_is_added_and_deleted(cm):
    assert "Added Trip" in cm("add", "Trip")
    assert "is empty" in cm("show", "Trip")
    with pytest.raises(typer.Exit):
        cm("add", "trip")
    assert "Deleted Trip" in cm("delete", "Trip")
    with pytest.raises(typer.Exit):
        cm("show", "Trip")


def test_what_is_no_cell_or_no_sheet_says_so(cm):
    for argv in (("get", "Budget", "nope"), ("get", "Budget"), ("set", "Budget"), ("edit", "Budget"), ("show", "Nope")):
        with pytest.raises(typer.Exit):
            cm(*argv)


def test_the_check_sketches_the_sheet(tmp_path):
    from cloudmorrow.cli.quill import preview
    from cloudmorrow.server.quills import QuillRegistry
    from tests.conftest import QUILL_CATALOG

    plan = QuillRegistry(tmp_path / "q", tmp_path / "d").plan(
        QUILL_CATALOG / "quill-cells", QUILL_CATALOG / "datamodels"
    )
    sketch = preview(plan)
    assert "=SUM(B1:B3)" in sketch and "docs/CELLS.md" in sketch, sketch
    assert max(len(line) for line in sketch.splitlines()) <= 80
