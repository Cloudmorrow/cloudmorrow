"""Administration → Access in the terminal app."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Button, Input, Static

from cloudmorrow.tui.panes.admin_access import access_text
from tests.tui_access import access_status
from tests.tui_harness import said, settle, start


async def open_access(app, pilot):
    screen = await start(app, pilot)
    await pilot.click("#nav-admin-access")
    await settle(app, pilot)
    return screen


def shown(screen) -> str:
    return Text.from_markup(str(screen.query_one("#admin-access-text", Static).content)).plain


async def dialog(pilot) -> None:
    # Not settle(): the worker waits on the dialog until it is answered.
    await pilot.pause()
    await pilot.pause()


def test_the_text_says_all_three_ways() -> None:
    plain = Text.from_markup(access_text(access_status("larsens", public=True, private=True), [
        {"name": "annas-phone", "address": "100.64.0.9", "for": "anna: phone", "online": True},
    ])).plain
    assert "Home network  on" in plain and "larsens.local" in plain
    assert "Public  on  larsens.cloudmorrow.test" in plain
    assert "tunnel connected since 2026-09-27 12:00 UTC" in plain and "2 reconnects" in plain
    assert "43.6 MB out" in plain
    assert "Private  on" in plain and "100.64.0.7" in plain and "annas-phone" in plain
    fresh = Text.from_markup(access_text(access_status())).plain
    assert "no name yet" in fresh and "(cloudmorrow, say)" in fresh


async def test_an_admin_claims_a_name_and_switches_the_ways(app):
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_access(app, pilot)
        assert "no name yet" in shown(screen)
        # One amber action: the name.
        primaries = [b for b in screen.query("#admin-view-access Button") if b.variant == "primary"]
        assert [b.id for b in primaries] == ["do-name"]

        await pilot.click("#do-name")
        await dialog(pilot)
        field = app.screen.query_one("#prompt-input", Input)
        assert field.value == "cloudmorrow"
        field.value = "larsens"
        await pilot.click("#ok")
        await settle(app, pilot)
        assert app.client.access_calls[-1] == ("claim", "larsens", True, False)
        assert "Public  on  larsens.cloudmorrow.test" in shown(screen)
        assert "Claimed larsens" in said(screen)

        await pilot.click("#do-private")
        await settle(app, pilot)
        assert app.client.access_calls[-1] == ("private", True)
        assert "annas-phone" in shown(screen)

        # Off asks first.
        await pilot.click("#do-public")
        await dialog(pilot)
        await pilot.click("#confirm")
        await settle(app, pilot)
        assert app.client.access_calls[-1] == ("public", False)
        assert "Public  off" in shown(screen)


async def test_giving_the_name_back_asks_and_a_refusal_is_said(app):
    app.client.access_state = access_status("larsens", public=True)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_access(app, pilot)
        await pilot.click("#do-release")
        await dialog(pilot)
        await pilot.click("#cancel")
        await settle(app, pilot)
        assert ("release",) not in app.client.access_calls
        await pilot.click("#do-release")
        await dialog(pilot)
        await pilot.click("#confirm")
        await settle(app, pilot)
        assert app.client.access_calls[-1] == ("release",)
        assert "no name yet" in shown(screen)

        # A name that is taken: the server's sentence, in the log.
        await pilot.click("#do-name")
        await dialog(pilot)
        app.screen.query_one("#prompt-input", Input).value = "taken"
        await pilot.click("#ok")
        await settle(app, pilot)
        assert "taken is taken" in said(screen)
        assert isinstance(screen.query_one("#do-name"), Button)
