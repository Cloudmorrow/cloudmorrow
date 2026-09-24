"""The server installer: one command, three questions, and a dry run that
says what it would do without asking any of them."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"
INSTALLER = DEPLOY / "install-server.sh"


ANSI = re.compile(r"\x1b\[[0-9;]*m")


def dry_run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["sh", str(INSTALLER), "--dry-run", "--repo", "https://example.invalid/cloud.git", *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env={**os.environ, **(env or {})},
        timeout=60,
    )
    # The script colours its output; the tests read the words.
    result.stdout = ANSI.sub("", result.stdout)
    result.stderr = ANSI.sub("", result.stderr)
    return result


def test_installer_is_valid_posix_shell():
    subprocess.run(["sh", "-n", str(INSTALLER)], check=True)


def test_container_entrypoint_is_valid_posix_shell():
    subprocess.run(["sh", "-n", str(DEPLOY / "docker" / "entrypoint.sh")], check=True)


def test_container_entrypoint_publishes_the_wheel_it_was_built_with(tmp_path):
    """The image's wheel lands in <data>/dist, replacing an older one."""
    data = tmp_path / "data"
    (data / "dist").mkdir(parents=True)
    (data / "dist" / "cloudmorrow-0.8.0-py3-none-any.whl").write_bytes(b"old")
    image = tmp_path / "image-dist"
    image.mkdir()
    (image / "cloudmorrow-0.9.0-py3-none-any.whl").write_bytes(b"new")
    script = (DEPLOY / "docker" / "entrypoint.sh").read_text().replace(
        "/opt/cloudmorrow/dist", str(image)
    )
    result = subprocess.run(
        ["sh", "-c", script, "entrypoint", "printf", "ran"],
        capture_output=True,
        text=True,
        env={**os.environ, "CLOUDMORROW_DATA_DIR": str(data)},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ran"
    assert [p.name for p in (data / "dist").iterdir()] == ["cloudmorrow-0.9.0-py3-none-any.whl"]


def test_dry_run_with_every_answer_asks_nothing():
    result = dry_run(
        "--name", "The Larsens",
        "--public-url", "https://cloud.example.com/",
        "--user", "alice",
        env={"CLOUDMORROW_ADMIN_PASSWORD": "longenough"},
    )
    assert result.returncode == 0, result.stderr + result.stdout
    out = result.stdout
    assert "The Larsens" in out
    assert "cloud.example.com" in out
    assert "would create: the account alice" in out
    assert "would ask" not in out
    # The proxy hint is for the name people typed, without the scheme.
    assert "cloud.example.com {" in out
    assert "reverse_proxy 127.0.0.1:8787" in out


def test_dry_run_says_which_question_it_would_have_asked():
    result = dry_run("--name", "Test", "--public-url", "https://cloud.test")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "would ask for the first account's username" in result.stdout


def test_a_plain_http_address_is_allowed_with_a_warning():
    result = dry_run(
        "--name", "Test", "--public-url", "http://192.168.1.10:8787", "--user", "alice",
        env={"CLOUDMORROW_ADMIN_PASSWORD": "longenough"},
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "plain http" in result.stdout
    # No TLS, so no proxy block to suggest.
    assert "reverse_proxy" not in result.stdout


@pytest.mark.parametrize("bad", ["al ice", "-alice", "a" * 33])
def test_a_username_the_server_would_refuse_is_refused_first(bad):
    result = dry_run("--name", "Test", "--public-url", "https://cloud.test", "--user", bad)
    assert result.returncode == 1
    assert "a username is" in result.stderr
