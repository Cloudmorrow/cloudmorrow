"""Two kinds of share: on the server, an admin's to make; on a machine, anyone's.

A machine share is a record here and a directory there. The server tells
the agent about it on the heartbeat, learns from the heartbeat where the
agent serves, and passes that on as the share's URL — with `online` saying
whether the machine is there right now. The server's own `/dav` never shows
a machine share: the machine serves it.
"""

from __future__ import annotations

import base64

import pytest

from cloudmorrow.server.agents import AgentStore
from cloudmorrow.server.shares import MACHINE, SERVER, SharePathError, ShareStore
from tests.conftest import GUEST, token_for


def basic(username: str, secret: str) -> dict[str, str]:
    raw = base64.b64encode(f"{username}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


@pytest.fixture()
def guest_auth(client) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(client, *GUEST)}"}


def enroll(client, auth, name="laptop") -> dict[str, str]:
    """An agent of the caller's, and the headers it heartbeats with."""
    enrolled = client.post(
        "/api/agents/enroll-self", json={"name": name}, headers=auth
    ).json()
    return {"Authorization": f"Bearer {enrolled['agent_token']}"}


def beat(client, agent_headers, **fields) -> dict:
    response = client.post("/api/agent/heartbeat", json=fields, headers=agent_headers)
    assert response.status_code == 200, response.text
    return response.json()


# -- the store ---------------------------------------------------------------


def test_the_store_keeps_a_machine_share_as_a_record_only(tmp_path):
    store = ShareStore(tmp_path / "db", lambda owner: tmp_path / owner)
    agent, _token = AgentStore(tmp_path / "db").enroll_for_user("bram", name="laptop")
    share = store.create(
        "bram", "music", kind=MACHINE, path="/home/bram/Music", agent_id=agent.id
    )
    assert (share.kind, share.agent_id, share.managed) == (MACHINE, agent.id, False)
    assert str(share.path) == "/home/bram/Music"
    # Nothing was made here: the directory is on the machine.
    assert not (tmp_path / "bram").exists()
    assert store.on_agent(agent.id) == [share]
    assert store.shares("bram", kind=SERVER) == []


def test_a_machine_share_needs_a_machine_and_an_absolute_path(tmp_path):
    store = ShareStore(tmp_path / "db", lambda owner: tmp_path / owner)
    with pytest.raises(SharePathError):
        store.create("bram", "music", kind=MACHINE, path="/home/bram/Music")
    agent, _token = AgentStore(tmp_path / "db").enroll_for_user("bram", name="laptop")
    with pytest.raises(SharePathError):
        store.create("bram", "music", kind=MACHINE, path="Music", agent_id=agent.id)


def test_a_share_from_before_the_split_is_a_server_share(tmp_path):
    store = ShareStore(tmp_path / "db", lambda owner: tmp_path / owner)
    share = store.create("bram", "media")
    assert share.kind == SERVER and share.agent_id is None


# -- the API -------------------------------------------------------------------


def test_only_an_admin_makes_a_share_on_the_server(client, auth, guest_auth):
    refused = client.post("/api/shares", json={"name": "media"}, headers=guest_auth)
    assert refused.status_code == 403
    assert "machine share" in refused.json()["detail"]
    allowed = client.post("/api/shares", json={"name": "media"}, headers=auth)
    assert allowed.status_code == 201
    assert allowed.json()["kind"] == "server"
    assert allowed.json()["online"] is True


def test_anyone_makes_a_share_on_their_own_machine(client, guest_auth):
    enroll(client, guest_auth)
    created = client.post(
        "/api/shares",
        json={"name": "music", "kind": "machine", "machine": "laptop", "path": "/home/guest/Music"},
        headers=guest_auth,
    )
    assert created.status_code == 201, created.text
    share = created.json()
    assert share["kind"] == "machine"
    assert share["machine"] == "laptop"
    assert share["path"] == "/home/guest/Music"
    # The machine has not said where it serves, so there is no URL and it is offline.
    assert share["url"] == ""
    assert share["online"] is False


def test_a_machine_share_names_a_machine_of_your_own(client, auth, guest_auth):
    enroll(client, auth, name="desktop")
    missing = client.post(
        "/api/shares",
        json={"name": "music", "kind": "machine", "path": "/x"},
        headers=guest_auth,
    )
    assert missing.status_code == 400
    # An admin's machine is not the guest's.
    other = client.post(
        "/api/shares",
        json={"name": "music", "kind": "machine", "machine": "desktop", "path": "/x"},
        headers=guest_auth,
    )
    assert other.status_code == 404


def test_the_heartbeat_carries_the_shares_out_and_the_address_back(client, guest_auth):
    agent = enroll(client, guest_auth)
    client.post(
        "/api/shares",
        json={"name": "music", "kind": "machine", "machine": "laptop", "path": "/home/guest/Music"},
        headers=guest_auth,
    )
    first = beat(client, agent, dav_base="")
    assert first["shares"] == [{"name": "music", "path": "/home/guest/Music"}]

    beat(client, agent, dav_base="http://192.168.1.20:8788")
    share = client.get("/api/shares/music", headers=guest_auth).json()
    assert share["online"] is True
    assert share["url"] == "http://192.168.1.20:8788/dav/music/"

    # Serving stopped: the empty address is the report, not a missing one.
    beat(client, agent, dav_base="")
    share = client.get("/api/shares/music", headers=guest_auth).json()
    assert share["online"] is False and share["url"] == ""


def test_an_older_agent_that_says_nothing_keeps_its_address(client, guest_auth):
    agent = enroll(client, guest_auth)
    beat(client, agent, dav_base="http://192.168.1.20:8788")
    beat(client, agent)
    assert client.get("/api/agents", headers=guest_auth).json()[0]["dav_base"] == (
        "http://192.168.1.20:8788"
    )


def test_the_servers_dav_does_not_show_a_machine_share(client, auth):
    enroll(client, auth)
    client.post("/api/shares", json={"name": "media"}, headers=auth)
    client.post(
        "/api/shares",
        json={"name": "music", "kind": "machine", "machine": "laptop", "path": "/tmp"},
        headers=auth,
    )
    token = auth["Authorization"].split()[1]
    listing = client.request("PROPFIND", "/dav/", headers={**basic("bram", token), "Depth": "1"})
    assert "/dav/media/" in listing.text
    assert "/dav/music/" not in listing.text
    missing = client.request("PROPFIND", "/dav/music/", headers=basic("bram", token))
    assert missing.status_code == 404


def test_an_agent_asks_the_server_whether_a_mount_may_come_in(client, auth, guest_auth):
    agent = enroll(client, guest_auth)
    guest_token = guest_auth["Authorization"].split()[1]
    admin_token = auth["Authorization"].split()[1]

    def ask(username: str, password: str) -> bool:
        response = client.post(
            "/api/agent/credentials",
            json={"username": username, "password": password},
            headers=agent,
        )
        assert response.status_code == 200, response.text
        return response.json()["valid"]

    assert ask("guest", guest_token) is True
    assert ask("guest", GUEST[1]) is True
    assert ask("guest", "wrong") is False
    # The owner's machine, the owner's shares: nobody else, admin or not.
    assert ask("bram", admin_token) is False
    # And not without an agent token at all.
    assert client.post(
        "/api/agent/credentials", json={"username": "guest", "password": guest_token}
    ).status_code == 401


def test_removing_the_machine_removes_its_shares(client, guest_auth):
    enroll(client, guest_auth)
    client.post(
        "/api/shares",
        json={"name": "music", "kind": "machine", "machine": "laptop", "path": "/x"},
        headers=guest_auth,
    )
    agent_id = client.get("/api/agents", headers=guest_auth).json()[0]["id"]
    assert client.delete(f"/api/agents/{agent_id}", headers=guest_auth).status_code == 204
    assert [s["name"] for s in client.get("/api/shares", headers=guest_auth).json()] == ["my-files"]


def test_removing_a_machine_share_never_asks_the_machine_for_its_files(client, guest_auth):
    enroll(client, guest_auth)
    client.post(
        "/api/shares",
        json={"name": "music", "kind": "machine", "machine": "laptop", "path": "/x"},
        headers=guest_auth,
    )
    gone = client.delete("/api/shares/music", params={"remove_files": True}, headers=guest_auth)
    assert gone.status_code == 204
    assert [s["name"] for s in client.get("/api/shares", headers=guest_auth).json()] == ["my-files"]
