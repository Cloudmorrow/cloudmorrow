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
        "--quills", "all",
        env={"CLOUDMORROW_ADMIN_PASSWORD": "longenough"},
    )
    assert result.returncode == 0, result.stderr + result.stdout
    out = result.stdout
    assert "would choose: the standard quills all" in out
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


def test_the_standard_quills_are_the_fourth_question():
    result = dry_run("--name", "Test", "--public-url", "https://cloud.test", "--user", "alice")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "would ask: which standard quills to have" in result.stdout
    # And the guide at the end points at the one-line client install.
    assert "curl -fsSL https://cloud.test/install.sh | sh" in result.stdout


def test_the_script_installs_from_the_cloudmorrow_organisation():
    text = INSTALLER.read_text()
    assert 'DEFAULT_REPO="https://github.com/Cloudmorrow/cloudmorrow.git"' in text
    assert "bramlabs-io" not in text


# -- how people reach it ---------------------------------------------------------
ANSWERS = {"CLOUDMORROW_ADMIN_PASSWORD": "longenough"}


def test_with_no_answer_the_cloud_is_reached_on_the_home_network():
    result = dry_run("--name", "The Larsens", "--user", "alice", "--quills", "all", env=ANSWERS)
    assert result.returncode == 0, result.stderr + result.stdout
    out = result.stdout
    assert "would ask: how people should reach it" in out
    # Reachable by its neighbours, at the name it announces.
    assert "http://the-larsens.local:8787" in out
    assert "listening on 0.0.0.0:8787" in out
    assert "cloudmorrow-server access claim" not in out
    assert "reverse_proxy" not in out
    # A home cloud is not warned about http the way an own address is.
    assert "allow_insecure_http" not in out


def test_a_public_name_brings_caddy_and_is_claimed_as_the_service_user():
    result = dry_run("--name", "The Larsens", "--public-name", "Larsens", "--yes",
                     "--user", "alice", "--quills", "all", env=ANSWERS)
    assert result.returncode == 0, result.stderr + result.stdout
    out = result.stdout
    assert "would ask: how people" not in out
    assert "caddy" in out.lower()
    assert "chown cloudmorrow:caddy /var/lib/cloudmorrow-caddy" in out
    assert "chmod 2750 /var/lib/cloudmorrow-caddy" in out
    claim = next(line for line in out.splitlines() if "access claim" in line)
    assert claim.strip().startswith("would run: sudo -u cloudmorrow")
    assert claim.endswith("access claim larsens --public")
    # No mesh for a public-only cloud.
    assert "tailscale up" not in out and "access private on" not in out
    assert "address    https://larsens.cloudmorrow.com" in out
    # The site is Cloudmorrow's to write; no hand-written proxy block to paste.
    assert "Put a reverse proxy in front" not in out


def test_private_only_asks_first_and_joins_the_mesh():
    result = dry_run("--name", "The Larsens", "--private", "--user", "alice", "--quills", "all",
                     env=ANSWERS)
    assert result.returncode == 0, result.stderr + result.stdout
    out = result.stdout
    # Claimed with public access off, and the certificate by DNS.
    assert "access claim the-larsens --no-public" in out
    assert "tailscale up --login-server <from the control server>" in out
    assert "--hostname cloud --operator=cloudmorrow" in out
    assert "access private on" in out
    if "caddy is here" not in out:
        assert "would ask: Install Caddy" in out
        assert "p=github.com/caddy-dns/acmedns" in out
    assert "sh -s -- --private" in out


def test_both_and_an_own_control_server():
    result = dry_run("--name", "X", "--public-name", "larsens", "--private", "--yes",
                     "--access-control", "https://relay.example.org",
                     "--user", "alice", "--quills", "all", env=ANSWERS)
    assert result.returncode == 0, result.stderr + result.stdout
    out = result.stdout
    assert "access claim larsens --public" in out
    assert "access private on" in out
    assert "claiming larsens at https://relay.example.org" in out
    assert "https://larsens.example.org" in out
    assert "(public and private)" in out


def test_a_bad_name_is_refused_before_anything_is_done():
    result = dry_run("--name", "X", "--public-name", "a", "--user", "alice")
    assert result.returncode == 1
    assert "a name is 3 to 40" in result.stderr


def test_the_unit_may_write_the_caddy_site():
    text = INSTALLER.read_text()
    assert "ReadWritePaths=$NOTES_DIR $DATA_DIR $PREFIX -$CADDY_DIR" in text
    # Caddy imports the site the service writes, and nothing else is replaced.
    assert "import $CADDY_DIR/*.caddy" in text
    assert "grep -q '/usr/share/caddy'" in text
