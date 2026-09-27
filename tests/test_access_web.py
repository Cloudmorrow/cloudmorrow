"""Access in the browser: Administration → Access, Me → Pair a device, and the setup page.

The screens are driven in a browser (screenshots), not from here. What a
test can hold on to is the wiring — the files are listed and served, the
paths they call exist, the QR encoder is vendored with its licence and
nothing is fetched from elsewhere — and the setup page's new question,
which does something on the server.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from cloudmorrow.server.app import create_app
from cloudmorrow.server.routes.web import WEB, asset_version
from tests.access_fakes import ZONE, wire
from tests.conftest import ADMIN, GUEST, token_for

ACCESS_JS = (WEB / "accessadmin.js").read_text(encoding="utf-8")
PAIR_JS = (WEB / "pairdevice.js").read_text(encoding="utf-8")


def test_the_files_are_listed_and_served(client):
    app_js = (WEB / "app.js").read_text(encoding="utf-8")
    assert 'import "./accessadmin.js";' in app_js and 'import "./pairdevice.js";' in app_js
    assert '@import "./access.css";' in (WEB / "app.css").read_text(encoding="utf-8")
    version = asset_version()
    for name in ("accessadmin.js", "pairdevice.js", "qrcode.js", "access.css"):
        assert client.get(f"/app/{version}/{name}").status_code == 200, name


def test_access_is_a_side_of_administration_and_pairing_is_on_me():
    admin = (WEB / "admin.js").read_text(encoding="utf-8")
    assert 'data-side="access"' in admin and "drawAccess(panel)" in admin
    me = (WEB / "me.js").read_text(encoding="utf-8")
    assert "${pairRow()}" in me
    assert 'registerScreen("pair"' in PAIR_JS


def test_the_qr_encoder_is_vendored_with_its_licence():
    assert 'import qrcode from "./qrcode.js";' in PAIR_JS
    source = (WEB / "qrcode.js").read_text(encoding="utf-8")
    assert "Kazuhiko Arase" in source and "export default qrcode" in source
    licence = (WEB / "MIT-qrcode-generator.txt").read_text(encoding="utf-8")
    assert "MIT License" in licence and "Kazuhiko Arase" in licence
    for text in (ACCESS_JS, PAIR_JS):
        assert "https://cdn" not in text and "unpkg" not in text


def test_one_amber_action_per_view():
    """Each view draws at most one .row.primary: the next step, or the claim."""
    for view in ("function unnamed", "function nextStep"):
        body = ACCESS_JS.split(view, 1)[1].split("\nfunction ", 1)[0]
        buttons = re.findall(r'class="row primary"', body)
        assert buttons, view
    # The enrolled view has its primary only through nextStep.
    enrolled = ACCESS_JS.split("function enrolled", 1)[1].split("\nfunction ", 1)[0]
    assert "row primary" not in enrolled and "nextStep(status)" in enrolled
    assert PAIR_JS.count('class="row primary"') == 1


def test_the_paths_they_call_exist(config, users, tmp_path):
    app = create_app(config)
    wire(app.state.cloudmorrow.access, tmp_path)
    client = TestClient(app)
    admin = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    for path in ("/api/access/name", "/api/access/public", "/api/access/${way}",
                 "/api/access/mesh/devices", "/api/access/mesh/pair", "/api/access/mesh/key"):
        assert path in ACCESS_JS + PAIR_JS, path
    assert client.get("/api/access", headers=guest).status_code == 200
    client.post("/api/access/name", json={"name": "larsens", "private": True}, headers=admin)
    assert client.post("/api/access/mesh/pair", json={"device": "phone"}, headers=guest).status_code == 200
    assert client.get("/api/access/mesh/devices?everyone=true", headers=admin).status_code == 200


# -- the setup page ---------------------------------------------------------------
def fresh(config, tmp_path):
    config.ensure_dirs()
    app = create_app(config)
    fakes = wire(app.state.cloudmorrow.access, tmp_path)
    return TestClient(app), fakes


def test_the_setup_page_asks_how_people_reach_it(config, tmp_path):
    client, _ = fresh(config, tmp_path)
    page = client.get("/setup").text
    assert "How should people reach it?" in page
    for way in ("home", "public", "private", "both"):
        assert f'name="way" value="{way}"' in page
    assert "/api/setup/access" in page
    offered = client.get("/api/setup/access").json()
    assert offered["suggested_name"] == "cloudmorrow"
    assert offered["zone"] == "cloudmorrow.com"


def test_setup_with_a_public_name_claims_it(config, tmp_path):
    client, fakes = fresh(config, tmp_path)
    response = client.post("/api/setup", json={
        "name": "The Larsens", "username": "alice", "password": "longenough",
        "access": {"way": "public", "name": "larsens"},
    })
    assert response.status_code == 201, response.text
    assert response.json()["address"] == f"https://larsens.{ZONE}"
    assert fakes.control.by_name("larsens").public is True
    # Once set up, the question is gone with the page.
    assert client.get("/api/setup/access").status_code == 409


def test_setup_at_home_claims_nothing(config, tmp_path):
    client, fakes = fresh(config, tmp_path)
    response = client.post("/api/setup", json={
        "name": "The Larsens", "username": "alice", "password": "longenough",
        "access": {"way": "home", "name": ""},
    })
    assert response.status_code == 201
    assert response.json()["address"] == ""
    assert fakes.control.clouds == {}


def test_a_taken_name_still_sets_the_cloud_up(config, tmp_path):
    client, fakes = fresh(config, tmp_path)
    from tests.access_fakes import FakeCloud

    fakes.control.clouds["t"] = FakeCloud("c_x", "t", "larsens")
    response = client.post("/api/setup", json={
        "name": "The Larsens", "username": "alice", "password": "longenough",
        "access": {"way": "both", "name": "larsens"},
    })
    assert response.status_code == 201
    body = response.json()
    assert body["address"] == ""
    assert "larsens is taken" in body["note"] and "Administration, Access" in body["note"]
