"""Me → Add a device, in the browser and in the terminal.

The web screen is driven in a browser (screenshots), not from here. What a
test can hold on to is the wiring: the files are listed and served, the QR
encoder is vendored with its licence and nothing is fetched from elsewhere.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from rich.text import Text
from textual.widgets import Static

from cloudmorrow.server.app import create_app
from cloudmorrow.server.routes.web import WEB, asset_version
from cloudmorrow.tui.screens.adddevice import add_device_text
from tests.conftest import ADMIN, token_for
from tests.tui_harness import start

ADD_JS = (WEB / "adddevice.js").read_text(encoding="utf-8")
QR_JS = (WEB / "qr.js").read_text(encoding="utf-8")


def test_the_files_are_listed_and_served(client):
    assert 'import "./adddevice.js";' in (WEB / "app.js").read_text(encoding="utf-8")
    assert '@import "./adddevice.css";' in (WEB / "app.css").read_text(encoding="utf-8")
    version = asset_version()
    for name in ("adddevice.js", "qr.js", "qrcode.js", "adddevice.css"):
        assert client.get(f"/app/{version}/{name}").status_code == 200, name


def test_the_qr_encoder_is_vendored_with_its_licence():
    assert 'import qrcode from "./qrcode.js";' in QR_JS
    assert 'from "./qr.js"' in ADD_JS
    source = (WEB / "qrcode.js").read_text(encoding="utf-8")
    assert "Kazuhiko Arase" in source and "export default qrcode" in source
    licence = (WEB / "MIT-qrcode-generator.txt").read_text(encoding="utf-8")
    assert "MIT License" in licence and "Kazuhiko Arase" in licence
    for text in (ADD_JS, QR_JS):
        assert "https://cdn" not in text and "unpkg" not in text


def test_it_asks_the_server_nothing_and_shows_no_code():
    """Every device signs in at the address the page was opened at."""
    assert "window.location.origin" in ADD_JS and "api(" not in ADD_JS
    # Things to read and copy, not a next step.
    assert ADD_JS.count('class="row primary') == 0
    for gone in ("mesh", "tailscale", "invite", "linked"):
        assert gone not in ADD_JS.lower(), gone


def test_the_server_sets_no_cookie(config, users):
    """A sign-in is a bearer token the page keeps in its own origin's storage."""
    client = TestClient(create_app(config))
    token_for(client, *ADMIN)
    answers = [
        client.post("/api/auth/login", json={"username": ADMIN[0], "password": ADMIN[1]}),
        client.get("/app"),
        client.get("/"),
        client.get("/install"),
    ]
    for answer in answers:
        assert "set-cookie" not in answer.headers, answer.request.url
    core = (WEB / "core.js").read_text(encoding="utf-8")
    assert "document.cookie" not in core and "localStorage" in core


# -- the terminal ------------------------------------------------------------------------
def plain(markup: str) -> str:
    return Text.from_markup(markup).plain


async def dialog(pilot) -> None:
    # Not settle(): the worker waits on the dialog until it is answered.
    await pilot.pause()
    await pilot.pause()


def test_the_add_device_text() -> None:
    text = plain(add_device_text("http://cloudmorrow.local:8787/"))
    assert "curl -fsSL http://cloudmorrow.local:8787/install.sh | sh" in text
    assert "http://cloudmorrow.local:8787/app" in text and "▀" in text
    assert "http://cloudmorrow.local:8787/mcp" in text
    assert "code" not in text.lower().replace("cloudmorrow", "")


async def test_add_a_device_from_settings(app):
    async with app.run_test(size=(120, 60)) as pilot:
        await start(app, pilot)
        await pilot.press("ctrl+g")
        await dialog(pilot)
        await pilot.click("#open-add-device")
        await dialog(pilot)
        text = app.screen.query_one("#add-device-text", Static)
        assert f"{app.client_config.api_url}/install.sh" in plain(str(text.content))
        await pilot.click("#close")
        await dialog(pilot)
