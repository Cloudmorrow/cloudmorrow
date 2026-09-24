"""Signing in should leave a working agent behind, without being asked."""

from __future__ import annotations

import subprocess

import httpx

from cloudmorrow.agent import service
from cloudmorrow.agent.config import AgentConfig
from cloudmorrow.agent.setup import ensure_agent, machine_name, stop_agent
from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.client.config import ClientConfig
from tests.conftest import ADMIN, GUEST, token_for


class FakeRunner:
    """Stands in for launchctl/systemctl so tests touch no real services."""

    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(args)
        return subprocess.CompletedProcess(args, self.returncode, "", "boom")


def api_for(test_client, token: str) -> CloudmorrowClient:
    """A real async client speaking ASGI straight to the app under test."""
    api = CloudmorrowClient(ClientConfig(api_url="http://testserver"), token=token)
    api._client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_client.app), base_url="http://testserver"
    )
    return api


# -- naming ------------------------------------------------------------------
def test_machine_name_is_a_valid_agent_name():
    from cloudmorrow.server.agents import AGENT_NAME_RE

    assert AGENT_NAME_RE.match(machine_name())


# -- service files -----------------------------------------------------------
def test_launchd_plist_is_written_and_loaded(tmp_path):
    runner = FakeRunner()
    result = service.install(
        home=tmp_path, executable="/opt/bc/bin/cloudmorrow-agent", runner=runner, kind="launchd"
    )
    assert result.installed
    plist = tmp_path / "Library" / "LaunchAgents" / "io.bramlabs.cloudmorrow-agent.plist"
    assert plist.is_file()
    body = plist.read_text()
    assert "/opt/bc/bin/cloudmorrow-agent" in body
    assert "<string>run</string>" in body
    assert any("bootstrap" in " ".join(call) for call in runner.calls)
    assert service.is_installed(home=tmp_path, kind="launchd")


def test_systemd_user_unit_is_written_and_enabled(tmp_path):
    runner = FakeRunner()
    result = service.install(
        home=tmp_path, executable="/opt/bc/bin/cloudmorrow-agent", runner=runner, kind="systemd"
    )
    assert result.installed
    unit = tmp_path / ".config" / "systemd" / "user" / "cloudmorrow-agent.service"
    assert "ExecStart=/opt/bc/bin/cloudmorrow-agent run" in unit.read_text()
    assert ["systemctl", "--user", "enable", "cloudmorrow-agent.service"] in runner.calls


def test_installing_restarts_a_unit_that_is_already_running(tmp_path):
    """`enable --now` leaves a running unit alone, which would keep old code."""
    runner = FakeRunner()
    service.install(home=tmp_path, executable="x", runner=runner, kind="systemd")
    assert ["systemctl", "--user", "restart", "cloudmorrow-agent.service"] in runner.calls


def test_restart_systemd(tmp_path):
    runner = FakeRunner()
    service.install(home=tmp_path, executable="x", runner=runner, kind="systemd")
    runner.calls.clear()
    result = service.restart(home=tmp_path, runner=runner, kind="systemd")
    assert result.installed
    assert runner.calls == [["systemctl", "--user", "restart", "cloudmorrow-agent.service"]]


def test_restart_launchd_kickstarts(tmp_path):
    runner = FakeRunner()
    service.install(home=tmp_path, executable="x", runner=runner, kind="launchd")
    runner.calls.clear()
    result = service.restart(home=tmp_path, runner=runner, kind="launchd")
    assert result.installed
    assert any("kickstart" in " ".join(call) for call in runner.calls)


def test_restart_falls_back_when_kickstart_is_missing(tmp_path):
    """Older macOS has no kickstart: bootout and bootstrap instead."""
    service.install(home=tmp_path, executable="x", runner=FakeRunner(), kind="launchd")
    runner = FakeRunner(returncode=1)
    service.restart(home=tmp_path, runner=runner, kind="launchd")
    assert any("bootout" in " ".join(call) for call in runner.calls)
    assert any("bootstrap" in " ".join(call) for call in runner.calls)


def test_restarting_what_is_not_installed_says_so(tmp_path):
    runner = FakeRunner()
    result = service.restart(home=tmp_path, runner=runner, kind="systemd")
    assert not result.installed
    assert "no agent service" in result.detail
    assert runner.calls == []


def test_service_failure_is_reported_not_raised(tmp_path):
    result = service.install(
        home=tmp_path, executable="x", runner=FakeRunner(returncode=1), kind="systemd"
    )
    assert not result.installed
    assert "boom" in result.detail


def test_unknown_platform_says_what_to_do(tmp_path):
    result = service.install(home=tmp_path, executable="cloudmorrow-agent", kind="none")
    assert not result.installed
    assert "run" in result.detail


def test_uninstall_removes_the_unit(tmp_path):
    runner = FakeRunner()
    service.install(home=tmp_path, executable="x", runner=runner, kind="systemd")
    service.uninstall(home=tmp_path, runner=runner, kind="systemd")
    assert not service.is_installed(home=tmp_path, kind="systemd")


# -- enrolment ---------------------------------------------------------------
async def test_login_enrols_this_machine(client, tmp_path):
    api = api_for(client, token_for(client, *ADMIN))
    config_path = tmp_path / "agent.toml"

    result = await ensure_agent(api, config_path=config_path, install_service=False)

    assert result.enrolled
    saved = AgentConfig.load(config_path)
    assert saved.agent_token.startswith("bca_")
    assert saved.server_url == "http://testserver"
    # And the server now lists it for that user.
    agents = client.get(
        "/api/agents", headers={"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    ).json()
    assert [a["name"] for a in agents] == [result.agent_name]


async def test_signing_in_again_rotates_rather_than_failing(client, tmp_path):
    api = api_for(client, token_for(client, *ADMIN))
    config_path = tmp_path / "agent.toml"

    first = await ensure_agent(api, config_path=config_path, install_service=False)
    token_one = AgentConfig.load(config_path).agent_token
    second = await ensure_agent(api, config_path=config_path, install_service=False)
    token_two = AgentConfig.load(config_path).agent_token

    assert first.enrolled and second.enrolled
    assert token_one != token_two
    # Still one agent, not two.
    agents = client.get(
        "/api/agents", headers={"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    ).json()
    assert len(agents) == 1
    # The old token stops working.
    assert client.post(
        "/api/agent/jobs/claim", headers={"Authorization": f"Bearer {token_one}"}
    ).status_code == 401


async def test_the_agent_belongs_to_the_user_who_signed_in(client, tmp_path):
    guest_api = api_for(client, token_for(client, *GUEST))
    await ensure_agent(guest_api, config_path=tmp_path / "agent.toml", install_service=False)

    admin_auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    guest_auth = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    assert client.get("/api/agents", headers=admin_auth).json() == []
    assert len(client.get("/api/agents", headers=guest_auth).json()) == 1


async def test_enrolment_needs_authentication(client, tmp_path):
    anonymous = api_for(client, "")
    anonymous._token = None
    result = await ensure_agent(
        anonymous, config_path=tmp_path / "agent.toml", install_service=False
    )
    assert not result.enrolled
    assert not (tmp_path / "agent.toml").exists()


async def test_a_failure_never_blocks_the_login(client, tmp_path, monkeypatch):
    """A machine we cannot install a service on still signs in fine."""
    api = api_for(client, token_for(client, *ADMIN))

    def explode(*_args, **_kwargs):
        raise RuntimeError("no service manager here")

    monkeypatch.setattr(service, "install", explode)
    result = await ensure_agent(api, config_path=tmp_path / "agent.toml")

    assert result.enrolled is True
    assert result.started is False
    assert "no service manager here" in result.detail


def test_logout_clears_the_token(tmp_path, monkeypatch):
    config_path = tmp_path / "agent.toml"
    AgentConfig(server_url="https://x", agent_token="bca_live", name="box").save(config_path)
    monkeypatch.setattr(service, "uninstall", lambda **_: service.ServiceResult(True, "systemd"))
    stop_agent(config_path=config_path)
    assert AgentConfig.load(config_path).agent_token == ""


def test_systemctl_is_pointed_at_the_user_bus_when_the_shell_is_not(tmp_path):
    """Over ssh there is no DBUS_SESSION_BUS_ADDRESS; the bus is at a known place."""
    (tmp_path / "bus").write_text("")
    env = service.user_bus_env({"PATH": "/usr/bin", "XDG_RUNTIME_DIR": str(tmp_path)}, uid=1000)
    assert env["DBUS_SESSION_BUS_ADDRESS"] == f"unix:path={tmp_path / 'bus'}"
    # What the shell did say is kept as it was.
    kept = service.user_bus_env(
        {"XDG_RUNTIME_DIR": str(tmp_path), "DBUS_SESSION_BUS_ADDRESS": "unix:path=/elsewhere"},
        uid=1000,
    )
    assert kept["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/elsewhere"
    # No bus at all: nothing is invented, and the runtime dir is still named.
    bare = service.user_bus_env({}, uid=1000)
    assert bare["XDG_RUNTIME_DIR"] == "/run/user/1000"
    assert "DBUS_SESSION_BUS_ADDRESS" not in bare or (tmp_path / "bus").exists()


def test_no_session_bus_is_explained_with_the_fix(tmp_path):
    class NoBus(FakeRunner):
        def __call__(self, args):
            result = super().__call__(args)
            if args[:3] == ["systemctl", "--user", "restart"]:
                result.returncode = 1
                result.stderr = "Failed to connect to bus: No medium found\n"
            return result

    runner = NoBus()
    service.install(home=tmp_path, executable="x", runner=runner, kind="systemd")
    result = service.restart(home=tmp_path, runner=runner, kind="systemd")
    assert result.installed is False
    assert "enable-linger" in result.detail


def test_installing_the_user_unit_makes_the_account_linger(tmp_path):
    runner = FakeRunner()
    service.install(home=tmp_path, executable="x", runner=runner, kind="systemd")
    assert ["loginctl", "enable-linger"] in runner.calls
