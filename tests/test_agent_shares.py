"""The agent serving a machine share: a real WebDAV server on a spare port.

The server is stood in for by a fake client that answers the credential
question, so what is tested is everything on the machine's side: that the
list from a heartbeat starts and stops the server, what it serves and to
whom, and that nothing escapes the directory.
"""

from __future__ import annotations

import base64
from pathlib import Path

import httpx
import pytest

from cloudmorrow.agent.config import AgentConfig
from cloudmorrow.agent.runner import AgentRunner
from cloudmorrow.agent.shares import ShareHost


class FakeClient:
    """Answers the two things the share host asks a server."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str]] = []
        self.heartbeats: list[dict] = []
        self.shares: list[dict] = []

    def check_credentials(self, username: str, password: str) -> bool:
        self.asked.append((username, password))
        return (username, password) == ("bram", "token")

    def heartbeat(self, hostname: str, platform: str, *, dav_base: str = "") -> dict:
        self.heartbeats.append({"dav_base": dav_base})
        return {"sync_bundles": [], "shares": self.shares}

    def claim_job(self) -> None:
        return None


def basic(username: str, secret: str) -> dict[str, str]:
    raw = base64.b64encode(f"{username}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


@pytest.fixture()
def host(tmp_path) -> ShareHost:
    config = AgentConfig(server_url="http://127.0.0.1:1", share_port=0, share_host="127.0.0.1")
    host = ShareHost(config, FakeClient())
    yield host
    host.stop()


@pytest.fixture()
def music(tmp_path) -> Path:
    directory = tmp_path / "Music"
    directory.mkdir()
    (directory / "song.txt").write_text("la la")
    return directory


def test_serving_starts_with_the_first_share_and_stops_with_the_last(host, music):
    assert host.base_url == ""
    host.update([{"name": "music", "path": str(music)}])
    assert host.base_url.startswith("http://127.0.0.1:")
    host.update([])
    assert host.base_url == ""


def test_a_directory_that_is_not_here_is_not_served(host, tmp_path, music):
    host.update([{"name": "gone", "path": str(tmp_path / "nope")}])
    assert host.base_url == ""
    host.update(
        [{"name": "gone", "path": str(tmp_path / "nope")}, {"name": "music", "path": str(music)}]
    )
    assert host.base_url != ""
    assert [s.name for s in host.served.shares_for("bram")] == ["music"]


def test_the_machine_serves_its_share_to_its_owner(host, music):
    host.update([{"name": "music", "path": str(music)}])
    base = host.base_url
    listing = httpx.request(
        "PROPFIND", f"{base}/dav/", headers={**basic("bram", "token"), "Depth": "1"}
    )
    assert listing.status_code == 207
    assert "/dav/music/" in listing.text
    song = httpx.get(f"{base}/dav/music/song.txt", headers=basic("bram", "token"))
    assert song.status_code == 200 and song.text == "la la"
    # The question went to the server once; the second request was remembered.
    assert host.client.asked == [("bram", "token")]


def test_wrong_credentials_are_refused_with_a_basic_challenge(host, music):
    host.update([{"name": "music", "path": str(music)}])
    refused = httpx.get(f"{host.base_url}/dav/music/song.txt", headers=basic("bram", "nope"))
    assert refused.status_code == 401
    assert refused.headers["www-authenticate"].startswith("Basic")


def test_nothing_escapes_the_share(host, music, tmp_path):
    (tmp_path / "secret.txt").write_text("no")
    host.update([{"name": "music", "path": str(music)}])
    outside = httpx.get(
        f"{host.base_url}/dav/music/../secret.txt", headers=basic("bram", "token")
    )
    assert outside.status_code in (403, 404)


def test_writes_land_in_the_directory(host, music):
    host.update([{"name": "music", "path": str(music)}])
    put = httpx.put(
        f"{host.base_url}/dav/music/new.txt", content=b"hello", headers=basic("bram", "token")
    )
    assert put.status_code in (201, 204)
    assert (music / "new.txt").read_text() == "hello"


def test_the_runner_reports_where_it_serves_on_the_next_heartbeat(tmp_path, music):
    config = AgentConfig(
        server_url="http://127.0.0.1:1", agent_token="x", share_port=0, share_host="127.0.0.1"
    )
    client = FakeClient()
    runner = AgentRunner(config, client=client)
    runner.tick()
    assert client.heartbeats[-1]["dav_base"] == ""
    client.shares = [{"name": "music", "path": str(music)}]
    runner.tick()
    runner.tick()
    assert client.heartbeats[-1]["dav_base"].startswith("http://127.0.0.1:")
    client.shares = []
    runner.tick()
    runner.tick()
    assert client.heartbeats[-1]["dav_base"] == ""
    runner.shares.stop()


def test_webdav_is_fetched_the_first_time_there_is_something_to_serve(host, music, monkeypatch):
    from cloudmorrow.agent import shares

    present = {"wsgidav": False}
    fetched = []
    monkeypatch.setattr(shares, "webdav_installed", lambda: present["wsgidav"])

    def failing_install() -> bool:
        fetched.append("tried")
        return False

    host.installer = failing_install
    host.update([{"name": "music", "path": str(music)}])
    # Not there, and could not be fetched: nothing is served, and the
    # heartbeat says so with an empty address.
    assert host.base_url == "" and fetched == ["tried"]
    # The failure is not retried at once.
    host.update([{"name": "music", "path": str(music)}])
    assert fetched == ["tried"]

    def install() -> bool:
        fetched.append("installed")
        present["wsgidav"] = True
        return True

    host.installer = install
    host._install_failed_at = None
    host.update([{"name": "music", "path": str(music)}])
    assert fetched == ["tried", "installed"]
    assert host.base_url.startswith("http://127.0.0.1:")


def test_a_machine_that_opted_out_serves_nothing(tmp_path, music):
    config = AgentConfig(server_url="http://127.0.0.1:1", allow_shares=False, share_port=0)
    host = ShareHost(config, FakeClient())
    host.update([{"name": "music", "path": str(music)}])
    assert host.base_url == ""
