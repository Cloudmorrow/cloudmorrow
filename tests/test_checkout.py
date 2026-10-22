"""checkout.py: which .env file is which environment, and writing one back without losing a key."""

from __future__ import annotations

import subprocess

import pytest

from cloudmorrow import checkout
from cloudmorrow.checkout import env_files, environment_of, file_for, same_repo, vault_name, write_file


def git(folder, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=folder, check=True, capture_output=True
    )


def test_a_file_name_says_its_environment():
    assert environment_of(".env.prod") == "prod"
    assert environment_of(".env.Production") == "production"
    assert environment_of(".env") == "local"
    # Beside a .env.local, a bare .env is the one under it.
    assert environment_of(".env", {".env", ".env.local"}) == "default"
    for name in (".env.example", ".env.sample", ".env.local.template", ".envrc", "env", ".env.", ".env.a b"):
        assert environment_of(name) is None, name


def test_an_environment_is_written_back_to_the_file_it_came_from():
    assert file_for("prod", {"prod": ".env.production"}) == ".env.production"
    assert file_for("prod", {}) == ".env.prod"
    assert file_for("local", {}) == ".env"


def test_only_the_files_git_does_not_commit_are_secrets(tmp_path):
    git(tmp_path, "init", "-q")
    for name, text in {".env": "A=1\n", ".env.prod": "B=2\n", ".env.example": "A=\n", ".env.ci": "C=3\n"}.items():
        (tmp_path / name).write_text(text)
    git(tmp_path, "add", ".env.ci")
    git(tmp_path, "commit", "-qm", "ci")
    assert env_files(tmp_path) == {"local": ".env", "prod": ".env.prod"}


def test_a_repository_is_the_same_however_it_is_written():
    assert same_repo("git@github.com:me/app.git", "https://github.com/me/app")
    assert same_repo("ssh://git@github.com/me/app.git", "https://github.com/Me/App/")
    assert not same_repo("git@github.com:me/app.git", "git@github.com:me/other.git")
    assert not same_repo("", "")


def test_a_vault_is_named_after_the_project():
    assert vault_name("My App") == "my-app"
    assert vault_name("  ") == "project"
    assert len(vault_name("x" * 50)) == 32


def test_a_file_that_knows_a_key_the_vault_lacks_is_kept(tmp_path):
    path = tmp_path / ".env.prod"
    path.write_text("A=1\nONLY_HERE=2\n")
    kept = write_file(path, "prod", {"A": "9"}, header="h")
    assert (kept.state, kept.only_here) == ("kept", ["ONLY_HERE"])
    assert "ONLY_HERE" in path.read_text()
    forced = write_file(path, "prod", {"A": "9"}, header="h", force=True)
    assert (forced.state, forced.changed) == ("written", ["A"])
    assert path.stat().st_mode & 0o777 == 0o600
    assert write_file(path, "prod", {"A": "9"}, header="h").state == "unchanged"


def test_where_a_project_is_is_remembered_per_server(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDMORROW_CONFIG_DIR", str(tmp_path / "config"))
    folder = tmp_path / "app"
    folder.mkdir()
    checkout.remember("https://a", "app", folder)
    assert checkout.remembered("https://a", "app") == folder.resolve()
    assert checkout.remembered("https://b", "app") is None


def test_a_broken_file_is_said_plainly(tmp_path):
    path = tmp_path / ".env"
    path.write_text("NOT A LINE\n")
    with pytest.raises(checkout.CheckoutError, match=r"^\.env: "):
        checkout.read_file(path)
