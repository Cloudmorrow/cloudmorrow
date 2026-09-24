"""`cloudmorrow uninstall`: everything the install put here, and nothing of the server's."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cloudmorrow.agent import service
from cloudmorrow.agent.config import AgentConfig
from cloudmorrow.cli import uninstall


@pytest.fixture()
def machine(tmp_path, monkeypatch):
    """A machine install.sh set up: a venv under the prefix, links in bin, config, backups."""
    prefix = tmp_path / "share" / "cloudmorrow"
    (prefix / "venv" / "bin").mkdir(parents=True)
    for name in ("cloudmorrow", "cm", "cloudmorrow-agent"):
        (prefix / "venv" / "bin" / name).write_text("#!/bin/sh\n")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("cloudmorrow", "cm", "cloudmorrow-agent"):
        (bindir / name).symlink_to(prefix / "venv" / "bin" / name)
    # Somebody else's `cm`, in another bin dir, is not ours.
    other = tmp_path / "otherbin"
    other.mkdir()
    (other / "cm").symlink_to(tmp_path / "elsewhere")

    config = tmp_path / "config"
    config.mkdir()
    (config / "config.toml").write_text('[client]\napi_url = "https://x"\n')
    (config / "credentials.json").write_text('{"token": "t"}')
    (config / "projects.json").write_text("{}")
    backups = prefix / "backups"
    backups.mkdir()
    (backups / "home-1.tar.gz").write_bytes(b"x")
    AgentConfig(server_url="https://x", agent_token="a", name="box", backup_dir=str(backups)).save(
        config / "agent.toml"
    )

    monkeypatch.setenv("CLOUDMORROW_CONFIG_DIR", str(config))
    monkeypatch.setattr(uninstall, "install_prefix", lambda: prefix)
    monkeypatch.setattr(uninstall, "bin_dirs", lambda: [bindir, other])
    monkeypatch.setattr(uninstall, "data_dir", lambda: prefix)
    monkeypatch.setattr(uninstall, "agent_config_path", lambda: config / "agent.toml")
    monkeypatch.setattr(service, "is_installed", lambda **_: True)
    monkeypatch.setattr(service, "SYSTEM_UNIT_DIR", tmp_path / "no-such-dir")
    removed: list[str] = []
    monkeypatch.setattr(
        service,
        "uninstall",
        lambda **_: removed.append("service") or service.ServiceResult(True, "systemd"),
    )
    return {
        "prefix": prefix,
        "bindir": bindir,
        "other": other,
        "config": config,
        "backups": backups,
        "removed": removed,
    }


def test_the_plan_names_everything_the_install_put_here(machine):
    found = uninstall.plan()
    assert found.agent_name == "box"
    assert found.service is True
    assert found.config == machine["config"]
    assert found.prefix == machine["prefix"]
    # The backups live inside the prefix, so they go with it rather than twice.
    assert found.backups is None
    assert sorted(link.name for link in found.links) == ["cloudmorrow", "cloudmorrow-agent", "cm"]
    assert all(link.parent == machine["bindir"] for link in found.links)
    assert found.checkout is None
    assert len(found.lines()) == 7


def test_removing_takes_it_all_and_strikes_the_agent_off(machine):
    forgotten: list[str] = []

    async def forget(name: str) -> str:
        forgotten.append(name)
        return ""

    notes = uninstall.remove(uninstall.plan(), forget=forget)
    assert notes == []
    assert forgotten == ["box"]
    assert machine["removed"] == ["service"]
    assert not machine["config"].exists()
    assert not machine["prefix"].exists()
    assert not any(
        (machine["bindir"] / n).exists() for n in ("cloudmorrow", "cm", "cloudmorrow-agent")
    )
    # Not ours, not touched.
    assert (machine["other"] / "cm").is_symlink()


def test_backups_elsewhere_are_their_own_line_and_can_be_kept(machine, tmp_path):
    elsewhere = tmp_path / "Backups"
    elsewhere.mkdir()
    (elsewhere / "a.tar.gz").write_bytes(b"x")
    AgentConfig(
        server_url="https://x", agent_token="a", name="box", backup_dir=str(elsewhere)
    ).save(machine["config"] / "agent.toml")
    assert uninstall.plan().backups == elsewhere
    assert uninstall.plan(keep_backups=True).backups is None

    async def forget(name: str) -> str:
        return ""

    uninstall.remove(uninstall.plan(keep_backups=True), forget=forget)
    assert elsewhere.exists()


def test_a_checkout_is_left_alone(machine, tmp_path, monkeypatch):
    checkout = tmp_path / "src"
    (checkout / ".git").mkdir(parents=True)
    monkeypatch.setattr(uninstall, "install_prefix", lambda: None)
    monkeypatch.setattr(uninstall.dev, "checkout", lambda: checkout)
    found = uninstall.plan()
    assert found.prefix is None
    assert found.checkout == checkout
    # Links into the prefix no longer count, since there is no prefix.
    assert found.links == []

    async def forget(name: str) -> str:
        return ""

    notes = uninstall.remove(found, forget=forget)
    assert any("left as it is" in note for note in notes)
    assert checkout.exists()
    assert machine["prefix"].exists()


def test_a_server_that_cannot_be_reached_is_a_note_not_a_stop(machine):
    async def forget(name: str) -> str:
        return "could not reach the server (boom); the agent record stays"

    notes = uninstall.remove(uninstall.plan(), forget=forget)
    assert notes == ["could not reach the server (boom); the agent record stays"]
    assert not machine["config"].exists()


def test_the_command_asks_first_and_yes_skips_the_question(machine, monkeypatch):
    from cloudmorrow.cli import main as main_cli

    async def forget(name: str) -> str:
        return ""

    monkeypatch.setattr(uninstall, "forget_on_server", forget)
    monkeypatch.setattr(uninstall.os, "_exit", lambda code: None)
    runner = CliRunner()
    declined = runner.invoke(main_cli.app, ["uninstall"], input="n\n")
    assert declined.exit_code == 1
    assert machine["config"].exists()

    done = runner.invoke(main_cli.app, ["uninstall", "--yes"])
    assert done.exit_code == 0, done.output
    assert not machine["config"].exists()
    assert not machine["prefix"].exists()


def test_nothing_to_do_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDMORROW_CONFIG_DIR", str(tmp_path / "nowhere"))
    monkeypatch.setattr(uninstall, "install_prefix", lambda: tmp_path / "nowhere")
    monkeypatch.setattr(uninstall, "bin_dirs", lambda: [])
    monkeypatch.setattr(uninstall, "data_dir", lambda: tmp_path / "nowhere")
    monkeypatch.setattr(uninstall, "agent_config_path", lambda: tmp_path / "nowhere" / "agent.toml")
    monkeypatch.setattr(service, "is_installed", lambda **_: False)
    monkeypatch.setattr(service, "SYSTEM_UNIT_DIR", tmp_path / "nowhere")
    monkeypatch.setattr(uninstall.dev, "checkout", lambda: None)
    assert uninstall.plan().lines() == []


# -- what may be deleted wholesale, and what may not ---------------------------------
def test_the_prefix_is_matched_not_guessed(tmp_path, monkeypatch):
    """`sys.executable` in a venv resolves to /usr/bin/python3; /usr is not the prefix."""
    monkeypatch.setattr(uninstall.dev, "checkout", lambda: None)
    venv = tmp_path / "cloudmorrow" / "venv"
    site = venv / "lib" / "python3.12" / "site-packages" / "cloudmorrow"
    site.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
    monkeypatch.setattr(uninstall.sys, "prefix", str(venv))
    monkeypatch.setattr(uninstall.sys, "base_prefix", "/usr")
    assert uninstall.install_prefix() == tmp_path / "cloudmorrow"

    # Not in a venv at all: the system interpreter.
    monkeypatch.setattr(uninstall.sys, "prefix", "/usr")
    assert uninstall.install_prefix() is None
    # A venv by another name, or in a directory by another name — pipx, say.
    other = tmp_path / "pipx" / "venvs" / "cloudmorrow"
    (other / "lib" / "python3.12" / "site-packages" / "cloudmorrow").mkdir(parents=True)
    (other / "pyvenv.cfg").write_text("")
    monkeypatch.setattr(uninstall.sys, "prefix", str(other))
    assert uninstall.install_prefix() is None
    # The right shape, but without this package in it.
    empty = tmp_path / "x" / "cloudmorrow" / "venv"
    empty.mkdir(parents=True)
    (empty / "pyvenv.cfg").write_text("")
    monkeypatch.setattr(uninstall.sys, "prefix", str(empty))
    assert uninstall.install_prefix() is None


def test_a_copy_installed_some_other_way_is_left_with_a_note(machine, monkeypatch):
    monkeypatch.setattr(uninstall, "install_prefix", lambda: None)
    monkeypatch.setattr(uninstall.dev, "checkout", lambda: None)
    monkeypatch.setattr(uninstall.sys, "prefix", "/somewhere/pipx/venvs/cloudmorrow")

    async def forget(name: str) -> str:
        return ""

    found = uninstall.plan()
    assert found.prefix is None and found.elsewhere == "/somewhere/pipx/venvs/cloudmorrow"
    notes = uninstall.remove(found, forget=forget)
    assert any("pipx uninstall" in note for note in notes)
    assert machine["prefix"].exists()
