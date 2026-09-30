"""Access in the browser: Administration → Access, Me → Add a device, and the setup page.

The screens are driven in a browser (screenshots), not from here. What a
test can hold on to is the wiring — the files are listed and served, the
paths they call exist, the QR encoder is vendored with its licence and
nothing is fetched from elsewhere — and the setup page's question, which
does something on the server.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from cloudmorrow.server.app import create_app
from cloudmorrow.server.routes.web import WEB, asset_version
from tests.access_fakes import ZONE, wire
from tests.conftest import ADMIN, GUEST, token_for

ACCESS_JS = (WEB / "accessadmin.js").read_text(encoding="utf-8")
ADD_JS = (WEB / "adddevice.js").read_text(encoding="utf-8")
QR_JS = (WEB / "qr.js").read_text(encoding="utf-8")


def test_the_files_are_listed_and_served(client):
    app_js = (WEB / "app.js").read_text(encoding="utf-8")
    assert 'import "./accessadmin.js";' in app_js and 'import "./adddevice.js";' in app_js
    assert '@import "./access.css";' in (WEB / "app.css").read_text(encoding="utf-8")
    version = asset_version()
    for name in ("accessadmin.js", "adddevice.js", "qr.js", "qrcode.js", "access.css"):
        assert client.get(f"/app/{version}/{name}").status_code == 200, name
    # The setup page, which is not the app, imports the QR drawing unversioned.
    assert client.get("/app/qr.js").status_code == 200


def test_access_is_a_side_of_administration_and_inviting_is_on_me():
    admin = (WEB / "admin.js").read_text(encoding="utf-8")
    assert 'data-side="access"' in admin and "drawAccess(panel)" in admin
    me = (WEB / "me.js").read_text(encoding="utf-8")
    assert "${addDeviceRow()}" in me
    assert 'registerScreen("add-device"' in ADD_JS
    assert not (WEB / "pairdevice.js").exists()


def test_the_qr_encoder_is_vendored_with_its_licence():
    assert 'import qrcode from "./qrcode.js";' in QR_JS
    assert 'from "./qr.js"' in ACCESS_JS and 'from "./qr.js"' in ADD_JS
    source = (WEB / "qrcode.js").read_text(encoding="utf-8")
    assert "Kazuhiko Arase" in source and "export default qrcode" in source
    licence = (WEB / "MIT-qrcode-generator.txt").read_text(encoding="utf-8")
    assert "MIT License" in licence and "Kazuhiko Arase" in licence
    for text in (ACCESS_JS, ADD_JS, QR_JS):
        assert "https://cdn" not in text and "unpkg" not in text


def test_one_amber_action_per_view():
    """Each state draws at most one .row.primary: the next step."""
    for view in ("function unlinked", "function linked"):
        body = ACCESS_JS.split(view, 1)[1].split("\nfunction ", 1)[0]
        assert len(re.findall(r'class="row primary"', body)) == 1, view
    # Add a device is things to read and copy, not a next step.
    assert ADD_JS.count('class="row primary') == 0


def test_no_tunnel_and_no_codes_are_left():
    for text in (ACCESS_JS, ADD_JS, (WEB / "access.css").read_text(encoding="utf-8")):
        for gone in ("tunnel", "/api/access/name", "mesh/pair", "Pair a device", "mesh/invite", "invite code"):
            assert gone not in text, gone


def test_the_paths_they_call_exist(config, users, tmp_path):
    app = create_app(config)
    fakes = wire(app.state.cloudmorrow.access, tmp_path)
    client = TestClient(app)
    admin = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    for path in ("/api/access/link", "/api/access/unlink", "/api/access/setup", "/api/access/mesh/devices"):
        assert path in ACCESS_JS, path
    assert "/api/access/public" in ACCESS_JS
    assert client.get("/api/access", headers=guest).status_code == 200
    link = client.post("/api/access/link", headers=admin).json()["link"]
    fakes.control.approve(link["code"], "larsens")
    app.state.cloudmorrow.access.poll_once()
    assert client.put("/api/access/public", json={"public": False}, headers=admin).json()["public"]["on"] is False
    assert client.put("/api/access/public", json={"public": True}, headers=guest).status_code == 403
    assert client.get("/api/access/mesh/devices?everyone=true", headers=admin).status_code == 200


# -- the setup page ---------------------------------------------------------------
def fresh(config, tmp_path):
    config.ensure_dirs()
    app = create_app(config)
    fakes = wire(app.state.cloudmorrow.access, tmp_path)
    return TestClient(app), fakes, app


def test_the_setup_page_asks_whether_to_link(config, tmp_path):
    client, _, _ = fresh(config, tmp_path)
    page = client.get("/setup").text
    assert "Link this cloud to a cloudmorrow.com account" in page
    assert 'id="link"' in page and "You can do it later" in page
    assert 'import { qrSvg } from "/app/qr.js";' in page
    assert "/api/setup/link" in page
    for gone in ('name="way"', "/api/setup/access", "A public name"):
        assert gone not in page


def test_setup_with_linking_shows_a_code_and_follows_it(config, tmp_path):
    client, fakes, app = fresh(config, tmp_path)
    response = client.post(
        "/api/setup",
        json={"name": "The Larsens", "username": "alice", "password": "longenough", "link": True},
    )
    assert response.status_code == 201, response.text
    link = response.json()["link"]
    assert link["place"] == "cloudmorrow.test/link" and link["link"].endswith(link["code"])
    assert client.get("/api/setup/link").json()["state"] == "waiting"
    fakes.control.approve(link["code"], "larsens")
    app.state.cloudmorrow.access.poll_once()
    now = client.get("/api/setup/link").json()
    assert now == {"state": "linked", "host": f"larsens.{ZONE}", "on_mesh": True, "error": ""}


def test_setup_without_linking_links_nothing(config, tmp_path):
    client, fakes, _ = fresh(config, tmp_path)
    response = client.post("/api/setup", json={"name": "The Larsens", "username": "alice", "password": "longenough"})
    assert response.status_code == 201
    assert response.json()["link"] is None
    assert fakes.control.calls == []


def test_a_relay_that_cannot_be_reached_still_sets_the_cloud_up(config, tmp_path, monkeypatch):
    client, _, app = fresh(config, tmp_path)
    import httpx

    def down(*args, **kwargs):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(app.state.cloudmorrow.access.http, "request", down)
    response = client.post(
        "/api/setup",
        json={"name": "The Larsens", "username": "alice", "password": "longenough", "link": True},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["link"] is None
    assert "could not be linked yet" in body["note"] and "Administration, Access" in body["note"]


def test_no_cookie_a_sibling_cloud_could_plant_or_read(config, users):
    """Every linked cloud is a name under one zone, which is not a public suffix,
    so a cookie set with a Domain could reach a sibling. The server sets none:
    a sign-in is a bearer token the page keeps in its own origin's storage.
    """
    client = TestClient(create_app(config))
    token = token_for(client, *ADMIN)
    answers = [
        client.post("/api/auth/login", json={"username": ADMIN[0], "password": ADMIN[1]}),
        client.get("/app"),
        client.get("/"),
        client.get("/install"),
        client.get("/api/access", headers={"Authorization": f"Bearer {token}"}),
    ]
    for answer in answers:
        assert "set-cookie" not in answer.headers, answer.request.url
    core = (WEB / "core.js").read_text(encoding="utf-8")
    assert "document.cookie" not in core and "localStorage" in core
