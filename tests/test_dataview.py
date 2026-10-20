"""The Data tab: every datamodel a person may see, and the records in it, to look at.

Composed by the server for whoever asks (server/dataview.py), drawn by the
kit's `data` element on every surface. What a test holds on to: it is on
every shelf, last; it is fitted to the person's circles and marked read
whatever they give; the web kit and the terminal draw it; and `cm data`
lists and shows without writing.
"""

from __future__ import annotations

import asyncio
import io
import re

import httpx
import pytest
from rich.console import Console

from cloudmorrow.cli import quillrun
from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.client.config import ClientConfig
from cloudmorrow.server.quills import KIT_READY, QuillRegistry, load_manifest
from cloudmorrow.server.routes.web import WEB, asset_version
from cloudmorrow.tui.panes.kit import pane_for
from cloudmorrow.tui.panes.kit_data import DataPane, columns_of
from tests.conftest import ADMIN, GUEST, QUILL_CATALOG, js_code, token_for


def headers(client, who) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(client, *who)}"}


def data_of(client, who=ADMIN) -> dict:
    listed = client.get("/api/quills", headers=headers(client, who)).json()
    assert listed[-1]["id"] == "data", [q["id"] for q in listed]
    return listed[-1]


# -- the server -------------------------------------------------------------------------
def test_data_is_on_every_shelf_last_with_every_datamodel_marked_read(tasks_quill):
    data = data_of(tasks_quill)
    assert data["name"] == "Data" and data["composed"] is True and data["available"] and data["enabled"]
    assert data["screens"] == [{"id": "data", "kit": "data", "label": "Data"}]
    assert set(data["models"]) == {"board", "task", "snapshot", "attestation"}
    assert {m["access"] for m in data["models"].values()} == {"read"}
    assert data["uses"] == sorted(data["models"])
    # The same shape as any Quill: what every client reads of one is there.
    for key in ("key", "icon", "summary", "actions", "jobs", "grants", "extends", "introduces", "models", "data"):
        assert key in data, key


def test_data_is_a_feature_an_administrator_or_a_person_switches(tasks_quill):
    """The web app draws no tab whose feature the server does not list: Data is one, last."""
    auth = headers(tasks_quill, ADMIN)
    listed = tasks_quill.get("/api/me/features", headers=auth).json()
    assert listed[-1]["key"] == "data" and listed[-1]["enabled"] is True
    off = tasks_quill.patch("/api/me/features/data", json={"enabled": False}, headers=auth)
    assert off.status_code == 200, off.text
    assert data_of(tasks_quill)["enabled"] is False and data_of(tasks_quill)["available"] is True


def test_datamodels_a_backend_keeps_are_left_out(secrets_quill):
    data = data_of(secrets_quill)
    assert "secret" not in data["models"]
    assert "snapshot" in data["models"]


def test_data_is_fitted_to_the_persons_circles(tasks_quill):
    circles = tasks_quill.app.state.cloudmorrow.circles
    kids = circles.create("Kids", rules={"task": "read"}, members=[GUEST[0]])
    circles.leave("members", GUEST[0])
    data = data_of(tasks_quill, GUEST)
    assert set(data["models"]) == {"task"}
    # The task's link to its board goes with the board.
    assert "board" not in [f["name"] for f in data["models"]["task"]["fields"]]
    circles.delete(kids.id)
    circles.leave("members", GUEST[0]) if GUEST[0] in circles.get("members").members else None
    nothing = data_of(tasks_quill, GUEST)
    assert nothing["models"] == {} and not nothing["available"] and not nothing["enabled"]


def test_the_records_api_still_refuses_writing_where_the_circles_only_read(tasks_quill):
    """Data marks everything read for its screens; the gate, not the tab, is what refuses a write."""
    auth = headers(tasks_quill, ADMIN)
    data = data_of(tasks_quill)
    assert data["models"]["task"]["access"] == "read"
    board = tasks_quill.get("/api/records/board", headers=auth).json()[0]
    made = tasks_quill.post("/api/records/task", json={"fields": {"board": board["id"], "title": "x"}}, headers=auth)
    assert made.status_code == 201


def test_a_quill_may_declare_a_data_screen_over_its_own_datamodels(tmp_path):
    folder = tmp_path / "quill-looking"
    (folder / "datamodels").mkdir(parents=True)
    (folder / "quill.toml").write_text(
        """
[quill]
id = "looking"
name = "Looking"
version = "1.0.0"
summary = "A look at the plants."
category = "home"

[uses]
datamodels = []

[[screens]]
id = "all"
kit = "data"
label = "All of it"
"""
    )
    (folder / "datamodels" / "plant.toml").write_text(
        """
[datamodel]
id = "looking.plant"
label = "Plant"
[fields]
name = { kind = "string", required = true }
"""
    )
    manifest = load_manifest(folder)
    assert manifest.screens[0]["kit"] == "data" and "model" not in manifest.screens[0]
    registry = QuillRegistry(tmp_path / "quills", tmp_path / "datamodels", str(QUILL_CATALOG))
    registry.install(folder, QUILL_CATALOG / "datamodels")
    assert "looking" in registry.quills


# -- the web ------------------------------------------------------------------------------
KIT_JS = (WEB / "kit.js").read_text(encoding="utf-8")
DATA_JS = (WEB / "kit_data.js").read_text(encoding="utf-8")
DATA_CSS = (WEB / "kit_data.css").read_text(encoding="utf-8")
APP_CSS = (WEB / "app.css").read_text(encoding="utf-8")


def test_the_web_kit_draws_it_and_it_is_served(client):
    assert "data" in KIT_READY
    assert '@import "./kit_data.css";' in APP_CSS
    assert 'import { dataSheet, renderData } from "./kit_data.js";' in KIT_JS
    assert "data: renderData" in KIT_JS and "data: dataSheet" in KIT_JS
    version = asset_version()
    for name in ("kit_data.js", "kit_data.css"):
        assert client.get(f"/app/{version}/{name}").status_code == 200, name
    # The sheet gives the kit a slot under the fields, and the data kit fills it.
    assert '<div class="own-slot"></div>' in KIT_JS and "own.section(" in KIT_JS
    assert "function dataSheet" in DATA_JS and "section:" in DATA_JS


def test_nothing_in_the_web_kit_is_named_for_one_quill_or_one_domain():
    code = js_code(DATA_JS)
    for word in ("ledger", "book", "deal", "contact", "task", "secret", "vault", "accounting", "crm"):
        assert not re.search(rf"[\"'.`#]{word}[\"'`\s.-]", code, re.IGNORECASE), f"kit_data.js names {word!r}"
    # The snapshot and the attestation are the one pair it knows by name,
    # because they have a route of their own (docs/ATTESTATIONS.md).
    assert 'const SNAPSHOT = "snapshot"' in DATA_JS and "/api/snapshots/" in DATA_JS
    assert "task" not in js_code(DATA_CSS)


# -- the terminal --------------------------------------------------------------------------
PLANT = {
    "id": "plant",
    "label": "Plant",
    "domain": "home",
    "title": "name",
    "in_space": "",
    "access": "read",
    "fields": [
        {"name": "name", "kind": "string", "label": "Name"},
        {"name": "room", "kind": "link", "label": "Room", "to": "room", "indexed": True},
        {"name": "watered", "kind": "date", "label": "Watered", "indexed": True},
        {"name": "notes", "kind": "markdown", "label": "Notes"},
        {"name": "code", "kind": "string", "label": "Code", "secret": True, "indexed": True},
    ],
}


def test_the_terminal_draws_a_data_screen_as_the_data_pane():
    quill = {"id": "data", "name": "Data", "models": {"plant": PLANT}, "screens": [{"id": "data", "kit": "data"}]}
    pane = pane_for(quill, quill["screens"][0])
    assert isinstance(pane, DataPane)
    assert pane.model_id == "plant" and not pane.writes and "new_record" in pane.refused
    assert [f["name"] for f in columns_of(PLANT)] == ["room", "watered"]


async def test_the_data_tab_lists_the_datamodels_and_the_records_of_the_one_picked(app):
    from textual.widgets import DataTable

    from cloudmorrow.tui.widgets.group_list import GroupList
    from tests.tui_harness import settle, start

    tasks = next(q for q in app.client.quill_list if q["id"] == "tasks")
    app.client.quill_list.append(
        {
            "id": "data",
            "key": "data",
            "name": "Data",
            "summary": "Every kind of data here you may see.",
            "icon": "database",
            "screens": [{"id": "data", "kit": "data", "label": "Data"}],
            "models": {k: dict(m, access="read") for k, m in tasks["models"].items()},
            "actions": [],
            "enabled": True,
            "available": True,
        }
    )
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await start(app, pilot)
        await pilot.click("#nav-data")
        await settle(app, pilot)
        pane = screen.query_one(DataPane)
        rows = [row.value for row in pane.query_one(GroupList).query("GroupRow")]
        assert rows == ["board", "task"]
        table = pane.query_one("#kit-table", DataTable)
        assert table.row_count == 2 and pane.model_id == "board"
        pane.stand("task")
        await settle(app, pilot)
        assert pane.model_id == "task" and pane.query_one("#kit-table", DataTable).row_count == 3
        # Where a task is, and what it is sorted by, beside its title.
        assert [f["name"] for f in pane.columns] == ["board", "lane", "due"]
        assert pane.ACTIONS[0].id == "open_record" and "new_record" in pane.refused


# -- the command line -----------------------------------------------------------------------
def api_for(test_client, token: str) -> CloudmorrowClient:
    api = CloudmorrowClient(ClientConfig(api_url="http://testserver"), token=token)
    api._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=test_client.app), base_url="http://testserver")
    return api


@pytest.fixture()
def run(tasks_quill, monkeypatch):
    def cm(*argv: str) -> str:
        screen_out = Console(file=io.StringIO(), width=200, color_system=None)
        monkeypatch.setattr(quillrun, "out", screen_out)
        monkeypatch.setattr(quillrun, "console", screen_out)
        api = api_for(tasks_quill, token_for(tasks_quill, *ADMIN))

        async def go() -> None:
            try:
                await quillrun.dispatch(api, "data", argv[0], list(argv[1:]))
            finally:
                await api.aclose()

        asyncio.run(go())
        return screen_out.file.getvalue()

    return cm


def test_cm_data_lists_datamodels_then_records_then_one(run, tasks_quill):
    auth = headers(tasks_quill, ADMIN)
    board = tasks_quill.get("/api/records/board", headers=auth).json()[0]
    task = tasks_quill.post(
        "/api/records/task", json={"fields": {"board": board["id"], "title": "Repot the fig"}}, headers=auth
    ).json()
    listed = run("list")
    assert "board" in listed and "task" in listed and "snapshot" in listed
    tasks = run("list", "task")
    assert "Repot the fig" in tasks and task["id"][2:6] in tasks
    shown = run("show", "task", task["id"][2:6])
    assert "Repot the fig" in shown and "Lane" in shown and "To Do" in shown


def test_cm_data_refuses_writing_and_an_unknown_datamodel(run):
    import typer

    with pytest.raises(typer.Exit):
        run("add", "task", "x")
    with pytest.raises(typer.Exit):
        run("list", "spaceship")
