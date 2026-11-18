"""The server's notices in the terminal: the updating modal, and the sidebar following
the Quills while you work. And the client reading them off the change feed."""

from __future__ import annotations

import copy

import httpx

from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.client.config import ClientConfig
from cloudmorrow.tui.screens import updating
from cloudmorrow.tui.screens.updating import UpdatingModal, frame
from cloudmorrow.tui.widgets.sidebar import NavCard
from tests.tui_harness import settle, start
from tests.tui_quills import READING_QUILL


async def test_a_quill_installed_elsewhere_comes_into_the_sidebar_and_lights_up(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        assert not screen.query("#nav-reading")
        app.client.quill_list.append(copy.deepcopy(READING_QUILL))
        app.client.feature_list.append({"key": "reading", "label": "Reading", "description": "", "enabled": True})
        app.quills_moved()
        await settle(app, pilot)
        await pilot.pause(0.05)
        card = screen.query_one("#nav-reading", NavCard)
        assert card.display and card.has_class("-arrived")
        # The cards that were there are not news.
        assert not screen.query_one("#nav-notes", NavCard).has_class("-arrived")


async def test_the_pane_you_are_in_is_not_drawn_again_under_you(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        current = screen.query_one("#panes").current
        pane = screen.query_one(f"#{current}")
        quill = next(q for q in app.client.quill_list if f"pane-{q['id']}" == current)
        quill["version"] = "9.9.9"
        app.quills_moved()
        await settle(app, pilot)
        assert screen.query_one(f"#{current}") is pane


async def test_the_updating_modal_stays_until_the_server_answers(app, monkeypatch):
    from cloudmorrow.client.api import ApiError

    monkeypatch.setattr(updating, "PROBE", 0.05)
    back: list[bool] = []

    async def health():
        if not back:
            raise ApiError("the server could not be reached")
        return {"status": "ok"}

    app.client.health = health
    async with app.run_test(size=(120, 34)) as pilot:
        await start(app, pilot)
        app.server_going()
        await pilot.pause()
        assert isinstance(app.screen, UpdatingModal)
        await pilot.press("escape")
        assert isinstance(app.screen, UpdatingModal)
        app.server_going()  # once is enough
        assert sum(isinstance(s, UpdatingModal) for s in app.screen_stack) == 1
        await pilot.pause(0.2)
        assert isinstance(app.screen, UpdatingModal)
        back.append(True)
        await pilot.pause(0.3)
        assert not isinstance(app.screen, UpdatingModal)


def test_the_blocks_take_turns():
    assert frame(0) != frame(1)
    assert all(len(frame(step).split("\n")) == 2 for step in range(8))


async def test_the_client_reads_the_notices_off_the_change_feed():
    body = (
        'retry: 3000\nevent: hello\ndata: {"seq":3}\n\n'
        'id: 4\nevent: change\ndata: {"seq":4,"model":"task"}\n\n'
        "event: quills\ndata: {}\n\n"
        ": ping\n\n"
        'event: bye\ndata: {"reason":"restart"}\n\n'
    )
    client = CloudmorrowClient(ClientConfig(api_url="https://test.invalid"), token="t")
    client._client = httpx.AsyncClient(
        base_url="https://test.invalid",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body)),
    )
    got = [notice async for notice in client.notices()]
    await client.aclose()
    assert got == [("quills", {}), ("bye", {"reason": "restart"})]
