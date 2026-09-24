"""The agent on the server itself: enrolling it, and the unit that runs it.

Nobody signs in on the server, so `cloudmorrow-server agent-install` is the only
path onto it — it goes straight at the database rather than over HTTP.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cloudmorrow.agent import service
from cloudmorrow.server.agents import AgentStore
from cloudmorrow.server.cli import app
from cloudmorrow.server.db import UserStore
from cloudmorrow.server.security import hash_password

runner = CliRunner()


@pytest.fixture()
def server(tmp_path, monkeypatch) -> Path:
    """A configured, empty server, addressed by its config file."""
    config = tmp_path / "server.toml"
    config.write_text(
        f'[server]\nnotes_dir = "{tmp_path / "notes"}"\ndata_dir = "{tmp_path / "data"}"\n'
        'host = "127.0.0.1"\nport = 8787\n',
        encoding="utf-8",
    )
    return config


def with_admin(config: Path) -> UserStore:
    data = tomllib.loads(config.read_text())["server"]["data_dir"]
    store = UserStore(Path(data) / "cloudmorrow.db")
    store.create("bram", hash_password("supersecret1"), is_admin=True)
    return store


def install(config: Path, agent_config: Path, *extra: str):
    return runner.invoke(
        app,
        [
            "agent-install",
            "--config",
            str(config),
            "--agent-config",
            str(agent_config),
            "--name",
            "bramserver",
            *extra,
        ],
    )


def test_the_server_enrols_itself_against_its_own_database(server, tmp_path):
    store = with_admin(server)
    agent_config = tmp_path / "agent.toml"

    result = install(server, agent_config, "--no-service")

    assert result.exit_code == 0, result.output
    written = tomllib.loads(agent_config.read_text())["agent"]
    assert written["name"] == "bramserver"
    assert written["agent_token"].startswith("bca_")
    assert written["server_url"] == "http://127.0.0.1:8787"
    # It backs up the server's own data, not whoever's home ran the command.
    assert any("notes" in root for root in written["backup_roots"])

    agents = AgentStore(Path(tomllib.loads(server.read_text())["server"]["data_dir"])
                        / "cloudmorrow.db").list("bram")
    assert [agent.name for agent in agents] == ["bramserver"]
    assert store.require("bram").is_admin


def test_running_it_again_rotates_the_token_rather_than_failing(server, tmp_path):
    with_admin(server)
    agent_config = tmp_path / "agent.toml"
    install(server, agent_config, "--no-service")
    first = tomllib.loads(agent_config.read_text())["agent"]["agent_token"]

    result = install(server, agent_config, "--no-service")

    assert result.exit_code == 0, result.output
    second = tomllib.loads(agent_config.read_text())["agent"]["agent_token"]
    assert second != first
    db = Path(tomllib.loads(server.read_text())["server"]["data_dir"]) / "cloudmorrow.db"
    assert len(AgentStore(db).list("bram")) == 1


def test_a_server_with_no_account_says_what_to_do(server, tmp_path):
    result = install(server, tmp_path / "agent.toml", "--no-service")

    assert result.exit_code == 1
    assert "user create" in result.output
    assert not (tmp_path / "agent.toml").exists()


def test_the_public_url_is_what_the_agent_is_pointed_at(server, tmp_path):
    with_admin(server)
    agent_config = tmp_path / "agent.toml"

    install(server, agent_config, "--no-service", "--url", "https://cloudmorrow.example/")

    written = tomllib.loads(agent_config.read_text())["agent"]
    assert written["server_url"] == "https://cloudmorrow.example"


# -- the unit ----------------------------------------------------------------
def test_the_system_unit_runs_as_the_service_account(tmp_path):
    calls: list[list[str]] = []

    def fake_run(args):
        calls.append(args)

        class Done:
            returncode = 0
            stderr = ""

        return Done()

    result = service.install_system(
        run_as="cloudmorrow",
        executable="/opt/cloudmorrow/venv/bin/cloudmorrow-agent",
        config_path=Path("/etc/cloudmorrow/agent.toml"),
        unit_dir=tmp_path,
        runner=fake_run,
    )

    unit = (tmp_path / service.UNIT_NAME).read_text()
    assert "User=cloudmorrow" in unit
    assert "ExecStart=/opt/cloudmorrow/venv/bin/cloudmorrow-agent run" in unit
    assert "Environment=CLOUDMORROW_AGENT_CONFIG=/etc/cloudmorrow/agent.toml" in unit
    assert "WantedBy=multi-user.target" in unit
    if result.installed:
        # Only where this test is running on systemd; elsewhere the unit is
        # written and the failure says why, which is the other assertion.
        assert ["systemctl", "enable", service.UNIT_NAME] in calls
    else:
        assert "systemd" in result.detail


def test_uninstalling_takes_the_unit_away(tmp_path):
    unit = tmp_path / service.UNIT_NAME
    unit.write_text("[Unit]\n", encoding="utf-8")

    service.uninstall_system(unit_dir=tmp_path, runner=lambda args: None)

    assert not unit.exists()
