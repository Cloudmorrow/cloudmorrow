"""Administration → Access and Invite a device, in the terminal app."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Input, Static

from cloudmorrow.tui.panes.admin_access import access_text
from cloudmorrow.tui.screens.invite import invite_text
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


def plain(markup: str) -> str:
    return Text.from_markup(markup).plain


def test_the_text_says_the_home_network_and_the_mesh() -> None:
    fresh = plain(access_text(access_status()))
    assert "Home network  on" in fresh and "the-larsens.local" in fresh
    assert "The mesh  not linked" in fresh and "cloudmorrow.com account" in fresh

    waiting = plain(access_text(access_status(waiting=True)))
    assert "Open cloudmorrow.test/link and enter" in waiting and "KXRT-4829" in waiting
    assert "https://cloudmorrow.test/link?code=KXRT-4829" in waiting
    # The QR code: half-blocks, a few dozen of them across.
    assert "▀" in waiting and "▄" in waiting

    devices = [
        {"id": "d1", "label": "anna: phone", "address": "100.64.0.9", "online": True},
        {"id": "d2", "label": "", "address": "100.64.0.10", "online": False},
    ]
    linked = plain(access_text(access_status("larsens"), devices))
    assert "The mesh  on  larsens.cloudmorrow.test" in linked and "100.64.0.7" in linked
    assert "anna: phone" in linked and "nobody's yet" in linked
    assert "My Clouds" in linked
    halfway = plain(access_text(access_status("larsens", on_mesh=False)))
    assert "not on its mesh yet" in halfway and "access denied" in halfway


def test_the_invite_text() -> None:
    assert "home network only" in plain(invite_text(access_status()))
    status = access_status("larsens")
    before = plain(invite_text(status))
    assert "Make an invite" in before
    assert "curl -fsSL https://larsens.cloudmorrow.test/install.sh | sh" in before
    assert "https://mesh.cloudmorrow.test" in before and "▀" in before
    after = plain(invite_text(status, {"code": "7QX2MP", "expires_at": "2026-09-29T12:10:00+00:00"}))
    assert "7QX2MP" in after and "until 12:10 UTC" in after


async def test_an_admin_links_the_cloud_and_the_pane_follows(app):
    async with app.run_test(size=(120, 60)) as pilot:
        screen = await open_access(app, pilot)
        assert "not linked" in shown(screen)
        # One amber action: Link.
        primaries = [b for b in screen.query("#admin-view-access Button") if b.variant == "primary"]
        assert [b.id for b in primaries] == ["do-link"]

        await pilot.click("#do-link")
        await settle(app, pilot)
        assert app.client.access_calls[-1] == ("link",)
        assert "KXRT-4829" in shown(screen)
        assert "waiting for the code" in said(screen)

        # The code is entered on the website; the pane looks again by itself.
        app.client.code_entered("larsens")
        pane = screen.query_one("#admin-view-access")
        pane.reload()
        await settle(app, pilot)
        assert "The mesh  on  larsens.cloudmorrow.test" in shown(screen)
        assert "anna: phone" in shown(screen)
        assert pane._timer is None


async def test_unlinking_asks_first(app):
    app.client.access_state = access_status("larsens")
    async with app.run_test(size=(120, 60)) as pilot:
        screen = await open_access(app, pilot)
        await pilot.click("#do-unlink")
        await dialog(pilot)
        await pilot.click("#cancel")
        await settle(app, pilot)
        assert ("unlink",) not in app.client.access_calls
        await pilot.click("#do-unlink")
        await dialog(pilot)
        await pilot.click("#confirm")
        await settle(app, pilot)
        assert app.client.access_calls[-1] == ("unlink",)
        assert "not linked" in shown(screen)
        # Linking twice is refused with the server's sentence.
        app.client.access_state = access_status("larsens")
        await pilot.click("#do-link")
        await settle(app, pilot)
        assert "already linked" in said(screen).lower()


async def test_an_admin_says_whose_a_phone_is(app):
    app.client.access_state = access_status("larsens")
    async with app.run_test(size=(120, 60)) as pilot:
        await open_access(app, pilot)
        await pilot.click("#do-label")
        await dialog(pilot)
        app.screen.query_one("#prompt-input", Input).value = "d2"
        await pilot.click("#ok")
        await dialog(pilot)
        app.screen.query_one("#prompt-input", Input).value = "bram"
        await pilot.click("#ok")
        await dialog(pilot)
        app.screen.query_one("#prompt-input", Input).value = "tablet"
        await pilot.click("#ok")
        await settle(app, pilot)
        assert app.client.access_calls[-1] == ("label", "d2", "bram", "tablet")


async def test_invite_a_device_from_settings(app):
    app.client.access_state = access_status("larsens")
    async with app.run_test(size=(120, 60)) as pilot:
        await start(app, pilot)
        await pilot.press("ctrl+g")
        await dialog(pilot)
        await pilot.click("#open-invite")
        await dialog(pilot)
        text = app.screen.query_one("#invite-text", Static)
        await pilot.click("#make-invite")
        await dialog(pilot)
        assert app.client.access_calls[-1] == ("invite",)
        assert "7QX2MP" in plain(str(text.content))
        await pilot.click("#close")
        await dialog(pilot)
