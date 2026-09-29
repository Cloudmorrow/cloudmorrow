"""A Quill's code in the terminal: its view drawn, its actions pressed, their effects.

Unlike the rest of the TUI tests these run against the real server, not the
fake in tui_harness.py: the Fleet fixture (fixtures/quill-fleet) is installed
with its code run in the server's own interpreter (`quill_code = "trusted"`,
as tests/test_quill_code.py does), and the app's client talks to it over
ASGI. What is drawn is what the Quill's `garage` view really returned.

A dialog open holds its worker open, so while one is up these wait with two
pauses rather than `settle()`.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from textual.widgets import Button, DataTable, Input, Static

from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.client.config import ClientConfig
from cloudmorrow.quill import ui
from cloudmorrow.server.app import create_app
from cloudmorrow.tui.panes.kit import pane_for
from cloudmorrow.tui.panes.kit_view import RENDERERS, Drawer, TableNode, ViewPane
from cloudmorrow.tui.quill_actions import ActionModal
from cloudmorrow.tui.screens.record_sheet import RecordSheet
from tests.conftest import ADMIN, token_for
from tests.tui_harness import PRESS_ANIMATION, settle, start

FLEET = Path(__file__).parent / "fixtures" / "quill-fleet"


async def breathe(pilot) -> None:
    await pilot.pause()
    await pilot.pause()


async def until(pilot, check, *, tries: int = 100) -> None:
    """Pause until *check()* holds: a dialog's own call to the server is no worker to wait on."""
    for _ in range(tries):
        if check():
            return
        await pilot.pause(0.02)
    assert check()


@pytest.fixture()
def fleet(config, users, tmp_path, monkeypatch):
    """The app, signed in as the administrator, on a server with Fleet and one van."""
    from cloudmorrow.tui.app import CloudmorrowApp

    config.quill_code = "trusted"
    server = TestClient(create_app(config))
    token = token_for(server, *ADMIN)
    auth = {"Authorization": f"Bearer {token}"}
    answer = server.post("/api/quills", json={"source": str(FLEET)}, headers=auth)
    assert answer.status_code == 201, answer.text
    made = server.post(
        "/api/quills/fleet/actions/add-van",
        json={"fields": {"name": "Transit", "registration": "AB 12 345"}},
        headers=auth,
    )
    assert made.status_code == 200, made.text

    monkeypatch.setenv("CLOUDMORROW_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(CloudmorrowApp, "_resume_session", lambda self: None)
    client_config = ClientConfig(api_url="http://testserver")
    app = CloudmorrowApp(client_config)
    api = CloudmorrowClient(client_config, token=token)
    api._client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app), base_url="http://testserver"
    )
    app.client = api
    app.username = ADMIN[0]
    app.server = server
    app.auth = auth
    return app


async def open_garage(app, pilot) -> ViewPane:
    screen = await start(app, pilot)
    await pilot.click("#nav-fleet-garage")
    await settle(app, pilot)
    return screen.query_one(ViewPane)


def toasts(app) -> str:
    """What the app has said in the log along the bottom: nothing here is a toast."""
    from cloudmorrow.tui.screens.workspace import WorkspaceScreen
    from tests.tui_harness import said

    workspace = next(s for s in app.screen_stack if isinstance(s, WorkspaceScreen))
    return said(workspace)


def vans(app) -> list[dict]:
    return app.server.get("/api/records/vehicle", headers=app.auth).json()


# -- drawing ----------------------------------------------------------------------------------
def test_every_primitive_has_a_renderer():
    assert set(ui.PRIMITIVES) <= set(RENDERERS)
    for kind, method in RENDERERS.items():
        assert callable(getattr(Drawer, method, None)), kind


def test_a_view_screen_gets_the_view_pane_with_or_without_a_datamodel():
    quill = {"id": "q", "name": "Q", "models": {}, "screens": [], "actions": []}
    assert isinstance(pane_for(quill, {"id": "home", "kit": "view", "view": "home"}), ViewPane)


async def test_the_garage_draws_its_stat_table_and_button(fleet):
    app = fleet
    async with app.run_test(size=(120, 40)) as pilot:
        pane = await open_garage(app, pilot)

        assert pane.failed == ""
        texts = [w.visual.plain for w in pane.query(".view-text")]
        assert "Garage" in texts
        stat = pane.query_one(".view-stat", Static).visual.plain
        assert stat.splitlines() == ["Vans", "1"]
        table = pane.query_one(TableNode)
        rows = table.query_one(DataTable)
        assert rows.row_count == 1
        assert [str(c.label) for c in rows.columns.values()] == ["NAME", "ODOMETER"]
        assert str(rows.get_cell_at((0, 0))) == "Transit"
        # The row's action, under the table, and the view's own button.
        labels = [str(b.label) for b in pane.query(Button)]
        assert "Log a service" in labels
        assert "Add a van" in labels


async def test_pressing_an_action_button_runs_it_toasts_and_draws_again(fleet):
    app = fleet
    async with app.run_test(size=(120, 40)) as pilot:
        pane = await open_garage(app, pilot)
        add = next(b for b in pane.query(Button) if str(b.label) == "Add a van")
        await pilot.click(add)
        await breathe(pilot)
        form = app.screen
        assert isinstance(form, ActionModal)

        # Its form is the manifest's: a name (needed) and a registration.
        form.query_one("#action-form-fields").query_one("#action-name", Input).value = ""
        await pilot.click("#action-submit")
        await breathe(pilot)
        assert app.screen is form
        assert "Name is needed" in form.query_one("#action-complaint", Static).visual.plain

        form.query_one("#action-name", Input).value = "Sprinter"
        await pilot.pause(PRESS_ANIMATION)
        await pilot.click("#action-submit")
        await until(pilot, lambda: isinstance(app.screen, RecordSheet))
        # add_van answers with a toast, and opens the van it made.
        assert "Added Sprinter" in toasts(app)
        sheet = app.screen
        assert isinstance(sheet, RecordSheet)
        assert sheet.query_one("#field-name", Input).value == "Sprinter"
        sheet.action_cancel()
        await settle(app, pilot)

        assert sorted(v["fields"]["name"] for v in vans(app)) == ["Sprinter", "Transit"]
        # The view was asked again: two vans now.
        assert pane.query_one(".view-stat", Static).visual.plain.splitlines()[1] == "2"


async def test_a_row_action_runs_on_the_row_you_are_on(fleet):
    app = fleet
    async with app.run_test(size=(120, 40)) as pilot:
        pane = await open_garage(app, pilot)
        log = next(b for b in pane.query(Button) if str(b.label) == "Log a service")
        await pilot.click(log)
        await breathe(pilot)
        form = app.screen
        assert isinstance(form, ActionModal)
        form.query_one("#action-date", Input).value = "2026-09-28"
        form.query_one("#action-km", Input).value = "1200"
        await pilot.click("#action-submit")
        await until(pilot, lambda: app.screen is not form)
        await settle(app, pilot)

        assert "Logged Transit at 1200 km" in toasts(app)
        # Its hook moves the odometer, on the server's own time; drawn again
        # once it has, the view says so.
        app.server.app.state.cloudmorrow.code.drain()
        assert vans(app)[0]["fields"]["fleet.odometer"] == 1200
        pane.reload()
        await settle(app, pilot)
        rows = pane.query_one(TableNode).query_one(DataTable)
        assert str(rows.get_cell_at((0, 1))) == "1200"


async def test_the_record_sheet_lists_the_actions_on_its_datamodel(fleet):
    app = fleet
    async with app.run_test(size=(120, 40)) as pilot:
        pane = await open_garage(app, pilot)
        table = pane.query_one(TableNode).query_one(DataTable)
        table.focus()
        await pilot.press("enter")
        await breathe(pilot)
        sheet = app.screen
        assert isinstance(sheet, RecordSheet)
        buttons = [str(b.label) for b in sheet.query_one("#sheet-actions").query(Button)]
        # `on = "vehicle"` only: Add a van is on no record, so it is not here.
        assert buttons == ["Log a service"]

        await pilot.click("#sheet-act-0")
        await breathe(pilot)
        form = app.screen
        assert isinstance(form, ActionModal)
        form.query_one("#action-date", Input).value = "2026-09-28"
        form.query_one("#action-km", Input).value = "900"
        await pilot.click("#action-submit")
        await until(pilot, lambda: app.screen is sheet and sheet.acted)

        assert "Logged Transit at 900 km" in toasts(app)
        app.server.app.state.cloudmorrow.code.drain()
        assert vans(app)[0]["fields"]["fleet.odometer"] == 900
        # Closed after an action, the sheet answers with the record, so the
        # view is asked again.
        sheet.action_cancel()
        await settle(app, pilot)
        rows = pane.query_one(TableNode).query_one(DataTable)
        assert str(rows.get_cell_at((0, 1))) == "900"


async def test_a_refusal_is_said_in_the_quills_words(fleet):
    app = fleet
    async with app.run_test(size=(120, 40)) as pilot:
        await start(app, pilot)
        from cloudmorrow.tui.kitdata import find_action
        from cloudmorrow.tui.quill_actions import run_action

        quill = next(q for q in app.quills if q["id"] == "fleet")
        ran = []

        async def go():
            ran.append(await run_action(app, quill, find_action(quill, "reach-out")))

        app.run_worker(go())
        await settle(app, pilot)
        assert ran == [False]
        assert "did not ask for contact" in toasts(app)


async def test_a_view_that_fails_says_why_where_it_would_be(fleet):
    app = fleet
    async with app.run_test(size=(120, 40)) as pilot:
        pane = await open_garage(app, pilot)
        pane.screen_id = "nope"
        pane.reload()
        await settle(app, pilot)
        said = pane.query_one("#view-failed", Static).visual.plain
        assert "could not be drawn" in said
        assert "no view called nope" in said


async def test_the_palette_has_the_actions_on_no_record(fleet):
    from cloudmorrow.tui.kitdata import installed, loose_actions
    from cloudmorrow.tui.quill_actions import QuillCommands

    app = fleet
    async with app.run_test(size=(120, 40)) as pilot:
        await start(app, pilot)
        names = [a["label"] for _, a in loose_actions(installed(app))]
        assert "Add a van" in names
        assert "Log a service" not in names
        await pilot.press("ctrl+e")
        await breathe(pilot)
        from textual.command import CommandPalette

        assert isinstance(app.screen, CommandPalette)
        assert QuillCommands in app.screen._provider_classes
        await pilot.press(*"add a van")
        await until(pilot, lambda: "Add a van" in str(app.screen.query("CommandList").first()
                                                        .get_option_at_index(0).prompt)
                    if app.screen.query("CommandList").first().option_count else False)
        await pilot.press("enter")
        await until(pilot, lambda: isinstance(app.screen, ActionModal))
        assert app.screen.action["id"] == "add-van"
        await pilot.press("escape")
        await breathe(pilot)


def every_primitive(van: dict) -> dict:
    """One tree with each primitive in it, about one real van."""
    return ui.check(ui.stack(
        ui.text("Everything", style="title"),
        ui.row(ui.stat("Vans", 1, hint="in the yard", tone="good"), ui.badge("new", tone="info")),
        ui.columns(ui.markdown("**Bold** words"),
                   ui.image("https://example.com/van.png", alt="A van")),
        ui.tabs(("Lanes", ui.lanes([van], field="fuel", title="name")),
                ("Month", ui.month([van], date="registration", title="name", start="2026-09"))),
        ui.divider(),
        ui.field(van, "name", edit=True),
        ui.field(van, "fleet.odometer"),
        ui.form("log-service", record=van, values={"km": 10}, submit="Log it"),
        ui.menu("More", ui.button("Open it", open=van), ui.button("Vans", go="vans")),
        ui.cards([van], title="name", subtitle="registration", badge="fuel"),
        ui.table([], columns=["name"], empty="No vans here."),
        ui.empty("Nothing else.", action="add-van"),
    ))


async def test_every_primitive_is_drawn_and_what_can_be_changed_is_saved(fleet):
    app = fleet
    async with app.run_test(size=(120, 60)) as pilot:
        pane = await open_garage(app, pilot)
        van = vans(app)[0]
        van["fields"]["fuel"] = "diesel"
        van["fields"]["registration"] = "2026-09-14"
        pane.view_tree = every_primitive(van)
        await pane.draw()
        await settle(app, pilot)

        from cloudmorrow.tui.panes.kit_view import walk

        for node, path in walk(pane.view_tree):
            if path.startswith("v-8-"):
                continue  # a menu's items are in the dialog it opens
            assert pane.query(f"#{path}"), f"{node['ui']} at {path} is not drawn"
        assert "No vans here." in pane.query_one("#v-10").query_one(Static).visual.plain
        assert "https://example.com/van.png" in pane.query_one("#v-2-1").query_one(
            ".view-image-caption", Static).visual.plain
        # The form is the action's, filled in with its values, under its own submit.
        assert pane.query_one("#v-7-f-km", Input).value == "10"
        assert str(pane.query_one("#v-7-submit", Button).label) == "Log it"
        # An editable field saves when you leave it.
        name = pane.query_one("#v-5-input", Input)
        name.value = "Transit Custom"
        name.focus()
        await pilot.press("enter")
        await settle(app, pilot)
        assert vans(app)[0]["fields"]["name"] == "Transit Custom"


async def test_a_card_in_a_lane_moves_with_the_keys(fleet):
    app = fleet
    async with app.run_test(size=(120, 50)) as pilot:
        pane = await open_garage(app, pilot)
        van = vans(app)[0]
        app.server.patch(f"/api/records/vehicle/{van['id']}", json={"fields": {"fuel": "petrol"}},
                         headers=app.auth)
        van = vans(app)[0]
        pane.view_tree = ui.check(ui.lanes([van], field="fuel", title="name"))
        await pane.draw()
        await settle(app, pilot)
        card = pane.query_one(f"#card-{van['id']}")
        card.focus()
        await pilot.press("right_square_bracket")
        await settle(app, pilot)
        assert vans(app)[0]["fields"]["fuel"] == "diesel"
