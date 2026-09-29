"""Where the client and the agent keep things, and an old agent config still found."""

from __future__ import annotations

from pathlib import Path

from cloudmorrow import locations
from cloudmorrow.agent import config as agent_config


def _no_system_config(monkeypatch, tmp_path):
    monkeypatch.delenv("CLOUDMORROW_AGENT_CONFIG", raising=False)
    monkeypatch.setattr(agent_config, "SYSTEM_CONFIG", tmp_path / "etc" / "agent.toml")
    monkeypatch.setattr(agent_config.os, "geteuid", lambda: 1000)


def test_an_agent_config_left_where_it_used_to_be_is_still_read(monkeypatch, tmp_path):
    """A Mac's agent config moved to the platform's place; an old install's stays found."""
    _no_system_config(monkeypatch, tmp_path)
    legacy = tmp_path / "home" / ".config" / "cloudmorrow" / "agent.toml"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("[agent]\n")
    platform = tmp_path / "Library" / "Application Support" / "cloudmorrow" / "agent.toml"
    monkeypatch.setattr(locations, "LEGACY_AGENT_CONFIG", legacy)
    monkeypatch.setattr(locations, "agent_config_path", lambda: platform)
    assert agent_config.default_config_path() == legacy
    # Once there is one in the platform's place, that is the one.
    platform.parent.mkdir(parents=True)
    platform.write_text("[agent]\n")
    assert agent_config.default_config_path() == platform


def test_a_new_agent_config_goes_to_the_platforms_place(monkeypatch, tmp_path):
    _no_system_config(monkeypatch, tmp_path)
    platform = tmp_path / "platform" / "agent.toml"
    monkeypatch.setattr(locations, "LEGACY_AGENT_CONFIG", tmp_path / "nowhere" / "agent.toml")
    monkeypatch.setattr(locations, "agent_config_path", lambda: platform)
    assert agent_config.default_config_path() == platform


def test_on_linux_the_agent_config_is_where_it_always_was(monkeypatch):
    monkeypatch.setattr(locations.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/somewhere/else")
    assert locations.agent_config_path() == Path.home() / ".config" / "cloudmorrow" / "agent.toml"


def test_the_client_config_dir_can_be_moved(monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUDMORROW_CONFIG_DIR", str(tmp_path))
    assert locations.config_dir() == tmp_path
