"""The desktop app's bridge: what the web app may ask of this computer.

Nothing is mounted and no server is reached: the server is a fake client,
and the mount itself is caught where `client.mounts` would shell out — so
the record-keeping these check is the real one, the same `mounts.json` the
command line and the terminal app read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudmorrow.agent import service
from cloudmorrow.agent.config import AgentConfig
from cloudmorrow.client import mounts, rclone
from cloudmorrow.client.api import ApiError
from cloudmorrow.client.config import ClientConfig, StoredCredentials
from cloudmorrow.desktop import system
from cloudmorrow.desktop.bridge import Bridge

API = "https://cloud.example"
SHARES = [
    {"name": "my-files", "kind": "drive", "url": f"{API}/dav/my-files/"},
    {"name": "media", "kind": "server", "url": f"{API}/dav/media/"},
    {"name": "music", "kind": "machine", "machine": "desk", "online": False, "url": ""},
]


class FakeApi:
    """The few calls the bridge makes, answered from SHARES."""

    def __init__(self, *, fail: str = "") -> None:
        self.fail = fail
        self.closed = False

    async def shares(self) -> list[dict]:
        if self.fail:
            raise ApiError(self.fail)
        return [dict(share) for share in SHARES]

    async def get_share(self, name: str) -> dict:
        for share in SHARES:
            if share["name"] == name:
                return dict(share)
        raise ApiError(f"no share called {name}", status_code=404)

    async def aclose(self) -> None:
        self.closed = True


class Machine:
    """What is mounted on this pretend computer, and what the mount was told."""

    def __init__(self) -> None:
        self.active: set[str] = set()
        self.mounted: list[tuple[str, str, str, str]] = []

    def mount(self, name, url, username, secret, path):
        self.mounted.append((name, url, username, secret))
        self.active.add(str(path))
        return mounts.Mount(name=name, path=Path(path), url=url, tool="rclone")

    def unmount(self, path):
        self.active.discard(str(path))


@pytest.fixture()
def machine(monkeypatch, tmp_path) -> Machine:
    here = Machine()
    monkeypatch.setattr(mounts, "platform", lambda: "linux")
    monkeypatch.setattr(mounts, "LINUX_MOUNT_ROOT", tmp_path / "Fileshares")
    monkeypatch.setattr(mounts, "_mount_rclone", here.mount)
    monkeypatch.setattr(mounts, "_unmount_path", here.unmount)
    monkeypatch.setattr(mounts.os.path, "ismount", lambda path: str(path) in here.active)
    monkeypatch.setattr(rclone, "installed", lambda: True)
    return here


@pytest.fixture()
def signed_in() -> StoredCredentials:
    credentials = StoredCredentials(api_url=API, username="bram", access_token="tok-1")
    credentials.save()
    return credentials


@pytest.fixture()
def bridge() -> Bridge:
    return Bridge(ClientConfig(api_url=API), api_factory=lambda config: FakeApi())


def test_shares_say_which_are_mounted_here_and_where(bridge, machine, signed_in, tmp_path):
    assert bridge.mount("media") == {
        "name": "media",
        "mounted": True,
        "path": str(tmp_path / "Fileshares" / "media"),
    }
    listed = {share["name"]: share for share in bridge.shares()["shares"]}
    assert listed["media"]["mounted"] is True
    assert listed["media"]["path"] == str(tmp_path / "Fileshares" / "media")
    assert listed["my-files"]["mounted"] is False
    assert listed["my-files"]["path"] == ""
    # The server's own facts come through untouched.
    assert listed["music"]["machine"] == "desk"


def test_a_mount_signs_in_as_the_machine_does(bridge, machine, signed_in):
    bridge.mount("media")
    assert machine.mounted == [("media", f"{API}/dav/media/", "bram", "tok-1")]
    # The same record the command line keeps, so `cm share unmount` undoes it.
    assert mounts.lookup("media").tool == "rclone"


def test_unmount_forgets_it(bridge, machine, signed_in):
    bridge.mount("media")
    assert bridge.unmount("media")["mounted"] is False
    assert mounts.lookup("media") is None
    assert bridge.mounted_here() == {"mounts": {}}


def test_mounted_here_is_what_this_machine_has(bridge, machine, signed_in, tmp_path):
    bridge.mount("my-files")
    assert bridge.mounted_here() == {
        "mounts": {"my-files": {"mounted": True, "path": str(tmp_path / "Fileshares" / "my-files")}}
    }
    # A mount that went away by itself — a reboot — is not mounted, but the
    # record says where it was.
    machine.active.clear()
    assert bridge.mounted_here()["mounts"]["my-files"]["mounted"] is False


def test_refusals_come_back_as_words_not_exceptions(bridge, machine, signed_in):
    assert "not mounted on this machine" in bridge.unmount("media")["error"]
    # A machine share whose machine is not serving: the command line's words.
    assert "not serving right now" in bridge.mount("music")["error"]
    assert "no share called nope" in bridge.mount("nope")["error"]
    bridge.mount("media")
    assert "already mounted" in bridge.mount("media")["error"]


def test_a_server_that_cannot_be_reached_is_an_error_too(machine, signed_in):
    bridge = Bridge(
        ClientConfig(api_url=API), api_factory=lambda config: FakeApi(fail="cannot reach it")
    )
    assert bridge.shares() == {"error": "cannot reach it"}


def test_mounting_needs_a_sign_in(bridge, machine):
    assert bridge.mount("media") == {"error": "this computer is not signed in"}


def test_without_rclone_the_answer_is_the_command_that_installs_it(
    bridge, machine, signed_in, monkeypatch
):
    monkeypatch.setattr(rclone, "installed", lambda: False)
    monkeypatch.setattr(rclone, "install_command", lambda: ["sudo", "pacman", "-S", "rclone"])
    answer = bridge.mount("media")
    assert "`sudo pacman -S rclone` installs it" in answer["error"]
    assert bridge.platform()["mount"] == {
        "available": False,
        "tool": "rclone",
        "detail": answer["error"],
    }
    assert machine.mounted == []


def test_platform_names_this_machine_as_its_agent_does(bridge, machine):
    answer = bridge.platform()
    assert answer["os"] == "linux"
    assert answer["machine"]
    assert answer["mount"] == {"available": True, "tool": "rclone", "detail": ""}


def test_windows_is_told_plainly_that_mounting_is_not_done_yet(monkeypatch):
    monkeypatch.setattr(mounts, "platform", lambda: "win32")
    assert system.mount_support()["available"] is False
    assert "not done on this system yet" in system.mount_support()["detail"]


def test_agent_status(bridge, tmp_path, monkeypatch):
    path = tmp_path / "agent.toml"
    monkeypatch.setenv("CLOUDMORROW_AGENT_CONFIG", str(path))
    monkeypatch.setattr(service, "detect_kind", lambda: "systemd")
    monkeypatch.setattr(service, "is_installed", lambda: True)
    monkeypatch.setattr(service, "is_active", lambda: True)
    assert bridge.agent_status()["enrolled"] is False
    assert bridge.agent_status()["running"] is False

    AgentConfig(server_url=API, agent_token="agent-tok", name="desk").save(path)
    status = bridge.agent_status()
    assert status == {
        "enrolled": True,
        "name": "desk",
        "service": "systemd",
        "installed": True,
        "running": True,
    }


def test_open_folder_opens_only_a_folder(bridge, tmp_path, monkeypatch):
    opened: list[list[str]] = []
    monkeypatch.setattr(mounts, "platform", lambda: "linux")
    monkeypatch.setattr(system.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(system, "_spawn", opened.append)
    assert bridge.open_folder(str(tmp_path)) == {"opened": str(tmp_path)}
    assert opened == [["/usr/bin/xdg-open", str(tmp_path)]]
    assert "is not a folder" in bridge.open_folder(str(tmp_path / "nope"))["error"]


def test_open_folder_on_a_mac_is_finder(tmp_path, monkeypatch):
    opened: list[list[str]] = []
    monkeypatch.setattr(mounts, "platform", lambda: "darwin")
    monkeypatch.setattr(system, "_spawn", opened.append)
    system.open_folder(tmp_path)
    assert opened == [["open", str(tmp_path)]]


def test_notify_is_best_effort(bridge, monkeypatch):
    sent: list[list[str]] = []
    monkeypatch.setattr(mounts, "platform", lambda: "linux")
    monkeypatch.setattr(system.shutil, "which", lambda name: f"/usr/bin/{name}")

    def run(command):
        sent.append(command)
        import subprocess

        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(system, "_run", run)
    assert bridge.notify("Mounted", "media is at ~/Fileshares/media") == {"sent": True}
    assert sent[0][0] == "/usr/bin/notify-send"
    assert sent[0][-2:] == ["Mounted", "media is at ~/Fileshares/media"]
    monkeypatch.setattr(system.shutil, "which", lambda name: None)
    assert bridge.notify("Mounted") == {"sent": False}


def test_version(bridge):
    assert set(bridge.version()) == {"version", "server"}


class Window:
    def __init__(self, url: str) -> None:
        self.url = url

    def get_current_url(self) -> str:
        return self.url


def test_only_this_clouds_own_page_may_ask(bridge, machine, signed_in):
    bridge._attach(Window(f"{API}/app#/shares"))
    assert "shares" in bridge.shares()
    bridge._attach(Window("https://elsewhere.example/app"))
    for answer in (bridge.shares(), bridge.mount("media"), bridge.session()):
        assert "not your cloud's" in answer["error"]
    assert machine.mounted == []


def test_nothing_private_is_handed_to_the_page():
    """pywebview gives the page every public attribute; these are all of them."""
    public = {name for name in dir(Bridge) if not name.startswith("_")}
    assert public == {
        "platform", "version", "agent_status", "notify", "open_folder", "mounted_here",
        "shares", "mount", "unmount", "session", "signed_in", "signed_out",
    }
