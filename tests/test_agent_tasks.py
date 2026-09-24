from __future__ import annotations

import tarfile

import pytest

from cloudmorrow.agent.config import AgentConfig
from cloudmorrow.agent.tasks import TaskError, TaskRefused, run_task


@pytest.fixture()
def agent_config(tmp_path) -> AgentConfig:
    (tmp_path / "data").mkdir()
    return AgentConfig(
        server_url="http://localhost",
        agent_token="bca_test",
        name="testbox",
        backup_roots=[str(tmp_path / "data")],
        backup_dir=str(tmp_path / "backups"),
        backup_retention=2,
    )


def test_ping(agent_config):
    result = run_task("ping", {"echo": "hi"}, agent_config)
    assert result["pong"] is True
    assert result["echo"] == "hi"
    assert result["agent"] == "testbox"


def test_sysinfo_reports_disks(agent_config, tmp_path):
    result = run_task("sysinfo", {"paths": [str(tmp_path)]}, agent_config)
    assert result["hostname"]
    assert result["disks"][str(tmp_path)]["total_bytes"] > 0


def test_unknown_task_is_refused(agent_config):
    with pytest.raises(TaskRefused):
        run_task("mine-bitcoin", {}, agent_config)


def test_backup_creates_an_archive(agent_config, tmp_path):
    source = tmp_path / "data"
    (source / "notes").mkdir()
    (source / "notes" / "a.md").write_text("hello")
    (source / "skip.log").write_text("noise")

    result = run_task(
        "backup", {"paths": [str(source)], "name": "data", "exclude": [".log"]}, agent_config
    )
    archive = tmp_path / "backups" / result["archive"].rsplit("/", 1)[-1]
    assert archive.is_file()
    assert result["bytes"] > 0
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert "data/notes/a.md" in names
    assert not any(name.endswith("skip.log") for name in names)


def test_backup_refuses_paths_outside_the_allowed_roots(agent_config, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with pytest.raises(TaskRefused):
        run_task("backup", {"paths": [str(outside)]}, agent_config)


def test_backup_refuses_traversal_out_of_a_root(agent_config, tmp_path):
    with pytest.raises(TaskRefused):
        run_task("backup", {"paths": [str(tmp_path / "data" / ".." / "..")]}, agent_config)


def test_backup_needs_an_existing_path(agent_config, tmp_path):
    with pytest.raises(TaskError):
        run_task("backup", {"paths": [str(tmp_path / "data" / "ghost")]}, agent_config)


def test_backup_can_be_disabled(agent_config):
    agent_config.allow_backup = False
    with pytest.raises(TaskRefused):
        run_task("backup", {"paths": ["/"]}, agent_config)


def test_backup_prunes_to_the_retention_limit(agent_config, tmp_path):
    source = tmp_path / "data"
    (source / "f.txt").write_text("x")
    backups = tmp_path / "backups"
    backups.mkdir(exist_ok=True)
    # Three older archives; retention is 2, so the newest run keeps 2 total.
    for index in range(3):
        stale = backups / f"data-2020010{index}T000000Z.tar.gz"
        stale.write_bytes(b"old")
    result = run_task("backup", {"paths": [str(source)], "name": "data"}, agent_config)
    assert len(result["pruned"]) == 2
    assert len(list(backups.glob("data-*.tar.gz"))) == 2


def test_shell_is_off_by_default(agent_config):
    with pytest.raises(TaskRefused):
        run_task("shell", {"command": "echo hi"}, agent_config)


def test_shell_runs_when_enabled(agent_config):
    agent_config.allow_shell = True
    result = run_task("shell", {"command": "echo cloudmorrow"}, agent_config)
    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "cloudmorrow"


def test_shell_failure_becomes_a_task_error(agent_config):
    agent_config.allow_shell = True
    with pytest.raises(TaskError):
        run_task("shell", {"command": "exit 3"}, agent_config)


def test_shell_timeout(agent_config):
    agent_config.allow_shell = True
    with pytest.raises(TaskError, match="timed out"):
        run_task("shell", {"command": "sleep 5", "timeout": 1}, agent_config)


def test_config_roundtrip(tmp_path):
    path = tmp_path / "agent.toml"
    config = AgentConfig(server_url="https://x/", agent_token="bca_1", allow_shell=True)
    config.save(path)
    assert path.stat().st_mode & 0o777 == 0o600
    loaded = AgentConfig.load(path)
    assert loaded.agent_token == "bca_1"
    assert loaded.allow_shell is True
    assert "shell" in loaded.capabilities
