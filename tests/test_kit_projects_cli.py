"""`cm <quill> init | update | clone | secrets` on a list of projects, against a real server and real git.

The Devlist fixture binds `vault`, `repo` and `env_files` on its list; the
secrets are the server's vaults, so Secrets is installed beside it.
"""

from __future__ import annotations

import asyncio
import io
import subprocess

import httpx
import pytest
import typer
from fastapi.testclient import TestClient
from rich.console import Console

from cloudmorrow.cli import quillrun
from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.client.config import ClientConfig
from cloudmorrow.server.app import create_app
from tests.conftest import ADMIN, QUILL_CATALOG, token_for


def git(folder, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=folder, check=True, capture_output=True
    )


@pytest.fixture()
def server(config, users) -> TestClient:
    client = TestClient(create_app(config))
    state = client.app.state.cloudmorrow
    state.quills.install_from_catalog("secrets")
    state.quills.install(QUILL_CATALOG / "quill-devlist", QUILL_CATALOG / "datamodels")
    return client


@pytest.fixture()
def checkout(tmp_path):
    """A repository with a remote, and the .env files only this machine has."""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", str(origin))
    folder = tmp_path / "myapp"
    git(tmp_path, "clone", "-q", str(origin), str(folder))
    (folder / ".gitignore").write_text(".env*\n!.env.example\n")
    (folder / ".env.example").write_text("DB_URL=\n")
    git(folder, "add", "-A")
    git(folder, "commit", "-qm", "first")
    git(folder, "push", "-q", "origin", "HEAD")
    (folder / ".env").write_text("DB_URL=postgres://here\n")
    (folder / ".env.prod").write_text('DB_URL=postgres://prod\nAPI_KEY="a b"\n')
    return folder


@pytest.fixture()
def cm(server, monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUDMORROW_CONFIG_DIR", str(tmp_path / "config"))

    def run(*argv: str, **local) -> str:
        screen_out = Console(file=io.StringIO(), width=200, color_system=None)
        monkeypatch.setattr(quillrun, "out", screen_out)
        monkeypatch.setattr(quillrun, "console", screen_out)
        monkeypatch.setattr(quillrun, "emit", screen_out.file.write)
        api = CloudmorrowClient(ClientConfig(api_url="http://testserver"), token=token_for(server, *ADMIN))
        api._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://testserver")

        async def go() -> None:
            try:
                await quillrun.dispatch(api, "devlist", argv[0], list(argv[1:]), local=local)
            finally:
                await api.aclose()

        asyncio.run(go())
        return screen_out.file.getvalue()

    return run


def secrets(server, vault: str, environment: str) -> dict:
    auth = {"Authorization": f"Bearer {token_for(server, *ADMIN)}"}
    answer = server.get(f"/api/secrets/export?vault={vault}&env={environment}&format=json", headers=auth)
    return answer.json()


def test_init_makes_the_folder_a_project_and_reads_its_env_files(cm, server, checkout, monkeypatch):
    monkeypatch.chdir(checkout)
    said = cm("init")
    assert "Made myapp" in said and "vault myapp" in said
    assert ".env → local" in said and ".env.prod → prod" in said
    assert ".env.example" not in said
    assert secrets(server, "myapp", "prod") == {"DB_URL": "postgres://prod", "API_KEY": "a b"}
    shown = cm("secrets")
    assert "local" in shown and ".env.prod" in shown
    # Again finds the same project, by its origin.
    assert "Found myapp" in cm("init")


def test_clone_on_another_machine_writes_the_files_back(cm, checkout, tmp_path):
    cm("init", path=str(checkout))
    elsewhere = tmp_path / "elsewhere"
    said = cm("clone", "myapp", str(elsewhere))
    assert "Cloned myapp" in said
    assert (elsewhere / ".env.example").exists()
    assert (elsewhere / ".env.prod").read_text().endswith("API_KEY='a b'\nDB_URL=postgres://prod\n")
    assert (elsewhere / ".env").stat().st_mode & 0o777 == 0o600


def test_update_pulls_and_keeps_a_file_with_keys_the_vault_lacks(cm, server, checkout, monkeypatch):
    monkeypatch.chdir(checkout)
    cm("init")
    (checkout / ".env.prod").write_text("DB_URL=postgres://prod\nAPI_KEY=a b\nNEW=1\n")
    said = cm("update")
    assert "Pulled myapp" in said and "kept" in said and "NEW" in said
    assert "NEW=1" in (checkout / ".env.prod").read_text()
    assert ".env.prod → prod" in cm("secrets", "import", file=".env.prod")
    assert secrets(server, "myapp", "prod")["NEW"] == "1"
    assert "unchanged .env.prod" in cm("update", "myapp")
    # The vault changed elsewhere: the file follows.
    auth = {"Authorization": f"Bearer {token_for(server, *ADMIN)}"}
    server.put("/api/secrets/item/NEW?vault=myapp", json={"value": "2", "environment": "prod"}, headers=auth)
    assert "wrote     .env.prod" in cm("update")
    assert "NEW=2" in (checkout / ".env.prod").read_text()


def test_secrets_export_writes_one_environment_where_asked(cm, checkout, tmp_path, monkeypatch):
    monkeypatch.chdir(checkout)
    cm("init")
    out = tmp_path / "prod.env"
    cm("secrets", "export", "myapp", env="prod", file=str(out))
    assert "DB_URL=postgres://prod" in out.read_text()
    with pytest.raises(typer.Exit):
        cm("secrets", "import", file="nothing.env")


def test_a_folder_that_is_no_project_is_said(cm, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(typer.Exit):
        cm("update")
