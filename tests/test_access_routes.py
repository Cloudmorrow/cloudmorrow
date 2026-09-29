"""Administration → Access and Me → Invite a device, over HTTP, against a fake relay."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cloudmorrow.server.app import create_app
from tests.access_fakes import ZONE, wire
from tests.conftest import ADMIN, GUEST, token_for


@pytest.fixture()
def wired(config, users, tmp_path):
    app = create_app(config)
    fakes = wire(app.state.cloudmorrow.access, tmp_path)
    client = TestClient(app)
    admin = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    return client, fakes, admin, guest, app


def linked(client, fakes, admin, name="larsens"):
    started = client.post("/api/access/link", headers=admin)
    assert started.status_code == 200, started.text
    fakes.control.approve(started.json()["link"]["code"], name)
    assert client.app.state.cloudmorrow.access.poll_once() == "linked"


def test_a_fresh_cloud_is_reached_at_home_only(wired) -> None:
    client, _, admin, guest, _ = wired
    status = client.get("/api/access", headers=admin).json()
    assert status["linked"] is False and status["mesh"]["on"] is False
    assert status["link"] is None and status["link_state"] == ""
    assert status["lan"]["on"] is True
    # Everybody may see how it is reached; not the workings.
    mine = client.get("/api/access", headers=guest).json()
    assert "control" not in mine and "link" not in mine and "box" not in mine["mesh"]
    assert client.get("/api/access").status_code == 401


def test_only_an_admin_links_and_unlinks(wired) -> None:
    client, _, _, guest, _ = wired
    assert client.post("/api/access/link", headers=guest).status_code == 403
    assert client.delete("/api/access/link", headers=guest).status_code == 403
    assert client.post("/api/access/unlink", headers=guest).status_code == 403
    assert client.post("/api/access/setup", headers=guest).status_code == 403


def test_linking_shows_a_code_and_then_the_name(wired, config) -> None:
    client, fakes, admin, _, _ = wired
    status = client.post("/api/access/link", headers=admin).json()
    link = status["link"]
    assert status["link_state"] == "waiting"
    assert link["place"] == "cloudmorrow.test/link" and link["link"].endswith("?code=" + link["code"])
    assert "poll" not in link
    fakes.control.approve(link["code"], "larsens")
    client.app.state.cloudmorrow.access.poll_once()
    status = client.get("/api/access", headers=admin).json()
    assert status["linked"] and status["host"] == f"larsens.{ZONE}" and status["mesh"]["on"]
    assert status["link"] is None and status["link_state"] == "linked"
    assert config.public_url == f"https://larsens.{ZONE}"
    # Linked twice is a sentence, not a second cloud.
    again = client.post("/api/access/link", headers=admin)
    assert again.status_code == 409 and "already linked" in again.json()["detail"]


def test_a_code_can_be_let_go(wired) -> None:
    client, _, admin, _, _ = wired
    client.post("/api/access/link", headers=admin)
    status = client.delete("/api/access/link", headers=admin).json()
    assert status["link"] is None and status["link_state"] == ""


def test_unlinking_goes_back_home(wired, config) -> None:
    client, fakes, admin, _, _ = wired
    linked(client, fakes, admin)
    status = client.post("/api/access/unlink", headers=admin).json()
    assert status["linked"] is False and config.public_url == ""
    assert fakes.control.clouds == {}


def test_a_relay_that_cannot_be_reached_is_a_502_with_a_sentence(wired, monkeypatch) -> None:
    client, _, admin, _, app = wired
    import httpx

    def down(*args, **kwargs):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(app.state.cloudmorrow.access.http, "request", down)
    response = client.post("/api/access/link", headers=admin)
    assert response.status_code == 502 and "cannot reach" in response.json()["detail"]


def test_before_the_mesh_there_is_nothing_to_invite_to(wired) -> None:
    client, _, _, guest, _ = wired
    for path in ("/api/access/mesh/invite", "/api/access/mesh/key"):
        response = client.post(path, headers=guest)
        assert response.status_code == 409 and "not linked" in response.json()["detail"]


def test_anybody_signed_in_invites_a_device(wired) -> None:
    client, fakes, admin, guest, _ = wired
    linked(client, fakes, admin)
    invite = client.post("/api/access/mesh/invite", headers=guest)
    assert invite.status_code == 200, invite.text
    body = invite.json()
    assert len(body["code"]) == 6 and body["login_server"].startswith("https://mesh.")
    assert body["command"] == f"curl -fsSL https://larsens.{ZONE}/install.sh | sh"
    assert body["host"] == f"larsens.{ZONE}"
    # The relay was asked for a code and told nothing about who asked.
    method, path, sent = fakes.control.calls[-1]
    assert (method, path) == ("POST", "/v1/clouds/me/mesh/invites") and sent == {}
    assert client.post("/api/access/mesh/invite").status_code == 401


def test_a_computer_joins_labels_itself_and_is_its_owners(wired) -> None:
    client, fakes, admin, guest, _ = wired
    linked(client, fakes, admin)
    fakes.control.only().mesh_address = "100.64.0.7"
    key = client.post("/api/access/mesh/key", headers=guest).json()
    assert key["hostname"].startswith("cm-") and key["host"] == f"larsens.{ZONE}"
    fakes.control.join(key["key"], "100.64.0.20")
    mine = client.post("/api/access/mesh/mine", json={"address": "100.64.0.20", "device": "laptop"}, headers=guest)
    assert mine.status_code == 200, mine.text
    assert mine.json()["label"] == "guest: laptop"
    listed = client.get("/api/access/mesh/devices", headers=guest).json()["devices"]
    assert [d["label"] for d in listed] == ["guest: laptop"]
    # An administrator sees them all, the box among them once the relay lists it.
    assert client.get("/api/access/mesh/devices", headers=admin).json()["devices"] == []
    everyone = client.get("/api/access/mesh/devices?everyone=true", headers=admin).json()["devices"]
    assert [d["label"] for d in everyone] == ["this cloud", "guest: laptop"]
    assert everyone[0]["box"] is True
    # Somebody else cannot take it, or remove it.
    device_id = listed[0]["id"]
    taken = client.post("/api/access/mesh/mine", json={"address": "100.64.0.20"}, headers=admin)
    assert taken.status_code == 403
    missing = client.post("/api/access/mesh/mine", json={"address": "100.64.0.99"}, headers=guest)
    assert missing.status_code == 404
    assert client.delete(f"/api/access/mesh/devices/{device_id}", headers=admin).status_code == 204
    assert client.get("/api/access/mesh/devices", headers=guest).json()["devices"] == []
    assert "guest" not in fakes.control.bodies() and "laptop" not in fakes.control.bodies()


def test_an_admin_says_whose_a_phone_is(wired) -> None:
    client, fakes, admin, guest, _ = wired
    linked(client, fakes, admin)
    key = client.post("/api/access/mesh/key", headers=admin).json()
    phone = fakes.control.join(key["key"], "100.64.0.30")
    refused = client.put(f"/api/access/mesh/devices/{phone['id']}", json={"owner": "guest"}, headers=guest)
    assert refused.status_code == 403
    done = client.put(
        f"/api/access/mesh/devices/{phone['id']}", json={"owner": "guest", "device": "phone"}, headers=admin
    )
    assert done.status_code == 200 and done.json()["label"] == "guest: phone"
    assert [d["id"] for d in client.get("/api/access/mesh/devices", headers=guest).json()["devices"]] == [phone["id"]]
    assert "phone" not in fakes.control.bodies()
