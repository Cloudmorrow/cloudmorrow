"""A cloud has a name, and it is on everything a person sees first."""

from __future__ import annotations

import tomllib
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from cloudmorrow.server.app import create_app
from cloudmorrow.server.cli import app as server_cli
from cloudmorrow.server.config import load_config
from cloudmorrow.server.db import UserStore

runner = CliRunner()


def test_the_name_defaults_to_cloudmorrow(config):
    assert config.name == "Cloudmorrow"


def test_the_name_is_read_from_the_config_and_the_environment(tmp_path, monkeypatch):
    path = tmp_path / "server.toml"
    path.write_text('[server]\nname = "The Larsens"\n', encoding="utf-8")
    assert load_config(path).name == "The Larsens"
    monkeypatch.setenv("CLOUDMORROW_NAME", "Number 12")
    assert load_config(path).name == "Number 12"
    # Blank is not a name; the default comes back rather than nothing.
    monkeypatch.setenv("CLOUDMORROW_NAME", "   ")
    assert load_config(path).name == "Cloudmorrow"


def named(config, users, name: str) -> TestClient:
    config.name = name
    return TestClient(create_app(config))


def test_health_says_the_name(config, users):
    with named(config, users, "The Larsens") as client:
        assert client.get("/api/health").json()["name"] == "The Larsens"


def test_the_install_page_carries_it(config, users):
    with named(config, users, "The Larsens") as client:
        body = client.get("/").text
        assert "<title>The Larsens</title>" in body
        assert "The Larsens" in body


def test_the_app_page_and_manifest_carry_it(config, users):
    with named(config, users, "Larsen & Co") as client:
        body = client.get("/app").text
        # Escaped: a name is text, never markup.
        assert "<title>Larsen &amp; Co</title>" in body
        assert 'content="Larsen &amp; Co"' in body
        assert 'data-name="Larsen &amp; Co"' in body
        assert "__NAME__" not in body
        manifest = client.get("/app/manifest.webmanifest")
        assert manifest.status_code == 200
        assert manifest.headers["content-type"].startswith("application/manifest+json")
        assert manifest.json()["name"] == "Larsen & Co"
        assert manifest.json()["short_name"] == "Larsen & Co"
        assert manifest.json()["start_url"] == "/app"


def server_config(tmp_path: Path) -> Path:
    path = tmp_path / "server.toml"
    path.write_text(
        f'[server]\nnotes_dir = "{tmp_path / "notes"}"\ndata_dir = "{tmp_path / "data"}"\n',
        encoding="utf-8",
    )
    return path


def test_the_installer_can_count_users_and_feed_a_password_on_stdin(tmp_path):
    config = server_config(tmp_path)
    result = runner.invoke(server_cli, ["user", "list", "--config", str(config), "--count"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "0"

    result = runner.invoke(
        server_cli,
        ["user", "create", "alice", "--config", str(config), "--admin", "--password-stdin"],
        input="longenough\n",
    )
    assert result.exit_code == 0, result.output
    data = tomllib.loads(config.read_text())["server"]["data_dir"]
    store = UserStore(Path(data) / "cloudmorrow.db")
    assert store.require("alice").is_admin

    result = runner.invoke(server_cli, ["user", "list", "--config", str(config), "--count"])
    assert result.output.strip() == "1"


def test_an_empty_stdin_password_is_refused(tmp_path):
    config = server_config(tmp_path)
    result = runner.invoke(
        server_cli,
        ["user", "create", "alice", "--config", str(config), "--password-stdin"],
        input="\n",
    )
    assert result.exit_code == 1
    assert "nothing came in" in result.output
