"""Administration → Access and Me → Pair a device, against a fake control server."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cloudmorrow.server.app import create_app
from cloudmorrow.server.sealed import sealer_for
from tests.access_fakes import LOGIN_SERVER, ZONE, tailscale_calls, wire
from tests.conftest import ADMIN, GUEST, token_for


@pytest.fixture()
def wired(config, users, tmp_path):
    app = create_app(config)
    fakes = wire(app.state.cloudmorrow.access, tmp_path)
    client = TestClient(app)
    admin = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    return client, fakes, admin, guest, app


def test_a_fresh_cloud_is_reached_at_home_only(wired) -> None:
    client, _, admin, guest, _ = wired
    status = client.get("/api/access", headers=admin).json()
    assert status["enrolled"] is False
    assert status["public"]["on"] is False and status["private"]["on"] is False
    assert status["public"]["tunnel"]["state"] == "off"
    assert status["suggested_name"] == "cloudmorrow"
    # Everybody may see how it is reached; not the workings.
    mine = client.get("/api/access", headers=guest).json()
    assert "tunnel" not in mine["public"] and "control" not in mine


def test_only_an_admin_claims_and_switches(wired) -> None:
    client, _, _, guest, _ = wired
    assert client.post("/api/access/name", json={"name": "larsens"}, headers=guest).status_code == 403
    assert client.put("/api/access/public", json={"on": True}, headers=guest).status_code == 403
    assert client.put("/api/access/private", json={"on": True}, headers=guest).status_code == 403
    assert client.delete("/api/access/name", headers=guest).status_code == 403
    assert client.get("/api/access").status_code == 401


def test_claiming_a_public_name(wired, config) -> None:
    client, fakes, admin, _, app = wired
    response = client.post("/api/access/name", json={"name": "Larsens"}, headers=admin)
    assert response.status_code == 200, response.text
    status = response.json()
    assert status["host"] == f"larsens.{ZONE}"
    assert status["public"]["on"] is True
    # public_url, and with it require_tls, follow the name.
    assert config.public_url == f"https://larsens.{ZONE}"
    assert config.tls_required
    # Caddy has a site for it, and was asked to load it.
    site = (config.access_caddy_dir / "cloudmorrow.caddy").read_text()
    assert f"larsens.{ZONE} {{" in site and "reverse_proxy 127.0.0.1:8787" in site
    assert "acmedns" not in site
    assert fakes.caddy_loads
    # The token is kept sealed, never plain.
    import sqlite3

    raw = sqlite3.connect(config.db_path).execute("SELECT token FROM access_cloud").fetchone()[0]
    cloud = fakes.control.by_name("larsens")
    assert cloud.token not in raw and raw.startswith("s1:")
    assert app.state.cloudmorrow.access.cloud().token == cloud.token
    assert sealer_for(config.db_path) is not None


def test_a_taken_name_is_a_409_with_a_sentence(wired) -> None:
    client, fakes, admin, _, _ = wired
    from tests.access_fakes import FakeCloud

    fakes.control.clouds["t"] = FakeCloud("c_x", "t", "larsens")
    response = client.post("/api/access/name", json={"name": "larsens"}, headers=admin)
    assert response.status_code == 409
    assert response.json()["detail"] == "larsens is taken; try another name"
    bad = client.post("/api/access/name", json={"name": "a"}, headers=admin)
    assert bad.status_code == 400


def test_rename_and_release(wired, config) -> None:
    client, fakes, admin, _, _ = wired
    client.post("/api/access/name", json={"name": "larsens"}, headers=admin)
    response = client.patch("/api/access/name", json={"name": "the-larsens"}, headers=admin)
    assert response.status_code == 200
    assert response.json()["host"] == f"the-larsens.{ZONE}"
    assert config.public_url == f"https://the-larsens.{ZONE}"
    assert "the-larsens." in (config.access_caddy_dir / "cloudmorrow.caddy").read_text()
    response = client.delete("/api/access/name", headers=admin)
    assert response.status_code == 200
    assert response.json()["enrolled"] is False
    assert fakes.control.clouds == {}
    assert config.public_url == ""
    assert not (config.access_caddy_dir / "cloudmorrow.caddy").exists()


def test_public_off_goes_back_to_the_configured_address(wired, config) -> None:
    client, fakes, admin, _, _ = wired
    client.post("/api/access/name", json={"name": "larsens"}, headers=admin)
    response = client.put("/api/access/public", json={"on": False}, headers=admin)
    assert response.json()["public"]["on"] is False
    assert fakes.control.by_name("larsens").public is False
    assert config.public_url == ""


def test_private_joins_the_mesh_and_reports_the_address(wired, config) -> None:
    client, fakes, admin, _, _ = wired
    client.post("/api/access/name", json={"name": "larsens", "public": False}, headers=admin)
    response = client.put("/api/access/private", json={"on": True}, headers=admin)
    assert response.status_code == 200, response.text
    status = response.json()
    assert status["private"]["on"] is True
    assert status["private"]["address"] == "100.64.0.7"
    assert status["private"]["mesh"]["state"] == "Running"
    cloud = fakes.control.by_name("larsens")
    assert cloud.mesh_address == "100.64.0.7"
    assert cloud.keys[0]["for"] == "the box"
    up = [c for c in tailscale_calls(fakes.tailscale_dir) if c.startswith("up ")][0]
    assert f"--login-server {LOGIN_SERVER}" in up
    assert "--hostname cloud" in up and f"--authkey {cloud.keys[0]['key']}" in up
    # Private only: the certificate by DNS, through the control server's acme-dns.
    site = (config.access_caddy_dir / "cloudmorrow.caddy").read_text()
    assert "dns acmedns" in site and cloud.acme["password"] in site
    assert "/v1/acme-dns" in site
    assert config.public_url == f"https://larsens.{ZONE}"
    # Off: the box leaves, and the name no longer points at it inside the mesh.
    response = client.put("/api/access/private", json={"on": False}, headers=admin)
    assert response.json()["private"]["on"] is False
    assert "down" in tailscale_calls(fakes.tailscale_dir)
    assert cloud.mesh_address == ""


def test_private_without_tailscale_says_what_to_do(wired, tmp_path) -> None:
    client, _, admin, _, app = wired
    from cloudmorrow.server.access_mesh import Mesh

    app.state.cloudmorrow.access.mesh = Mesh(str(tmp_path / "nowhere" / "tailscale"))
    client.post("/api/access/name", json={"name": "larsens"}, headers=admin)
    response = client.put("/api/access/private", json={"on": True}, headers=admin)
    assert response.status_code == 503
    assert "--private" in response.json()["detail"]


def test_a_person_gets_a_key_and_a_code_and_sees_only_their_devices(wired) -> None:
    client, fakes, admin, guest, _ = wired
    # Nothing to enroll in until private access is on.
    assert client.post("/api/access/mesh/pair", json={}, headers=guest).status_code == 409
    client.post("/api/access/name", json={"name": "larsens", "private": True}, headers=admin)

    key = client.post("/api/access/mesh/key", json={"device": "laptop"}, headers=guest)
    assert key.status_code == 200, key.text
    body = key.json()
    assert body["login_server"] == LOGIN_SERVER and body["key"].startswith("hskey-")
    assert body["hostname"] == f"larsens.{ZONE}"
    cloud = fakes.control.by_name("larsens")
    assert cloud.keys[-1]["for"] == "guest: laptop" and cloud.keys[-1]["owner"] == "guest"

    code = client.post("/api/access/mesh/pair", json={"device": "phone"}, headers=guest).json()
    assert len(code["code"]) == 6 and code["login_server"] == LOGIN_SERVER
    assert cloud.codes[-1]["for"] == "guest: phone"

    fakes.control.join(body["key"], "guests-laptop", "100.64.0.9")
    admin_key = client.post("/api/access/mesh/key", json={"device": "desk"}, headers=admin).json()
    theirs = fakes.control.join(admin_key["key"], "bram-desk", "100.64.0.10")
    # A relay that keeps only the label still says whose a device is.
    theirs.pop("owner")

    mine = client.get("/api/access/mesh/devices", headers=guest).json()["devices"]
    assert [d["name"] for d in mine] == ["guests-laptop"]
    everyone = client.get("/api/access/mesh/devices?everyone=true", headers=admin).json()["devices"]
    assert {d["owner"] for d in everyone} == {"guest", ADMIN[0]}
    # ?everyone is an admin's word only.
    assert len(client.get("/api/access/mesh/devices?everyone=true", headers=guest).json()["devices"]) == 1

    # A person removes their own device, never somebody else's; an admin any.
    assert client.delete(f"/api/access/mesh/devices/{theirs['id']}", headers=guest).status_code == 404
    assert client.delete(f"/api/access/mesh/devices/{mine[0]['id']}", headers=guest).status_code == 204
    assert client.delete(f"/api/access/mesh/devices/{theirs['id']}", headers=admin).status_code == 204
    assert cloud.devices == []


def test_the_record_survives_a_restart_and_follows_the_name(config, users, tmp_path) -> None:
    app = create_app(config)
    fakes = wire(app.state.cloudmorrow.access, tmp_path)
    client = TestClient(app)
    admin = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    client.post("/api/access/name", json={"name": "larsens"}, headers=admin)
    config.public_url = ""
    again = create_app(config)
    assert config.public_url == f"https://larsens.{ZONE}"
    assert again.state.cloudmorrow.access.cloud().name == "larsens"
    assert fakes.control.calls


def test_a_revoked_token_is_the_clouds_problem_not_the_persons(wired) -> None:
    client, fakes, admin, _, _ = wired
    client.post("/api/access/name", json={"name": "larsens", "private": True}, headers=admin)
    fakes.control.clouds.clear()
    response = client.post("/api/access/mesh/key", json={}, headers=admin)
    # Not a 401: that would sign the person out of their own cloud.
    assert response.status_code == 502
    assert "refused this cloud" in response.json()["detail"]
