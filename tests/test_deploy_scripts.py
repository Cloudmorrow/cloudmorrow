"""The server installer: one command, a few questions, and a dry run that
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
    script = (DEPLOY / "docker" / "entrypoint.sh").read_text().replace("/opt/cloudmorrow/dist", str(image))
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
        "--name",
        "The Larsens",
        "--public-url",
        "https://cloud.example.com/",
        "--user",
        "alice",
        "--quills",
        "all",
        "--host",
        "0.0.0.0",
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
        "--name",
        "Test",
        "--public-url",
        "http://192.168.1.10:8787",
        "--user",
        "alice",
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


def test_the_addresses_to_answer_on_are_asked_unless_given():
    asked = dry_run("--name", "T", "--public-url", "https://cloud.test", "--user", "alice")
    assert "would ask: which addresses to answer on" in asked.stdout
    given = dry_run(
        "--name",
        "T",
        "--public-url",
        "https://cloud.test",
        "--user",
        "alice",
        "--host",
        "127.0.0.1, 10.0.0.2",
    )
    assert "would ask: which addresses" not in given.stdout
    # Every one is listed at the end, and the proxy is pointed at loopback.
    assert "127.0.0.1, port 8787" in given.stdout
    assert "10.0.0.2, port 8787" in given.stdout
    assert "reverse_proxy 127.0.0.1:8787" in given.stdout


def test_the_address_given_is_the_one_a_proxy_and_the_network_use():
    result = dry_run("--name", "T", "--user", "alice", "--host", "10.0.0.2", "--public-url", "https://c.test")
    assert "reverse_proxy 10.0.0.2:8787" in result.stdout


def test_the_closing_page_fits_a_narrow_terminal():
    """Short lines under headings: only the lines that carry a URL or a path run long."""
    result = dry_run(
        "--name",
        "The Larsens",
        "--public-url",
        "https://cloud.example.com",
        "--user",
        "alice",
        "--quills",
        "all",
        env={"CLOUDMORROW_ADMIN_PASSWORD": "longenough"},
    )
    page = result.stdout[result.stdout.index("would be installed") :]
    for text in page.splitlines():
        if "/" not in text:
            assert len(text) <= 48, text


def test_the_installer_draws_the_wordmark_its_script_draws():
    import sys

    sys.path.insert(0, str(DEPLOY.parent / "scripts"))
    from installer_banner import block

    assert block() in INSTALLER.read_text()


# -- linking --------------------------------------------------------------------
ANSWERS = {"CLOUDMORROW_ADMIN_PASSWORD": "longenough"}


def test_without_an_answer_it_asks_whether_to_link_and_stays_home():
    result = dry_run("--name", "The Larsens", "--user", "alice", "--quills", "all", env=ANSWERS)
    assert result.returncode == 0, result.stderr + result.stdout
    out = result.stdout
    assert "would ask: whether to link this cloud to a cloudmorrow.com account" in out
    # Nobody said yes: nothing is installed for it, and the relay is never asked.
    assert "access link" not in out and "tailscale" not in out.lower() and "caddy" not in out.lower()
    assert "http://the-larsens.local:8787, at home" in out
    assert "From anywhere, too" in out and "--link" in out
    # No address of its own, so no proxy to put in front.
    assert "reverse_proxy" not in out


def test_linking_installs_what_it_needs_and_waits_for_the_code_as_the_service_user():
    result = dry_run(
        "--name",
        "The Larsens",
        "--link",
        "--yes",
        "--host",
        "0.0.0.0",
        "--user",
        "alice",
        "--quills",
        "all",
        env=ANSWERS,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    out = result.stdout
    assert "would ask" not in out
    assert "would run: tailscale set --operator=cloudmorrow" in out
    if "caddy is here" not in out:
        assert "p=github.com/caddy-dns/acmedns" in out
    assert "chown cloudmorrow:caddy /var/lib/cloudmorrow-caddy" in out
    link = next(line for line in out.splitlines() if "access link" in line and "would run" in line)
    assert link.strip().startswith("would run: sudo -u cloudmorrow") and link.endswith("access link")
    assert "Open cloudmorrow.com/link and enter a code" in out
    assert "linking through https://relay.cloudmorrow.tech" in out
    # Linked before the service starts, so it starts at its name.
    assert out.index("access link") < out.index("systemctl restart cloudmorrow")
    assert "Linked, and on its mesh" in out


def test_a_box_without_a_tun_device_runs_tailscale_in_userspace(tmp_path):
    """An LXC container has no /dev/net/tun; tailscaled only starts in userspace mode there."""
    args = (
        "--name",
        "X",
        "--link",
        "--yes",
        "--host",
        "0.0.0.0",
        "--user",
        "alice",
        "--quills",
        "all",
        "--public-url",
        "https://c.test",
    )
    without = dry_run(*args, env={**ANSWERS, "CLOUDMORROW_TUN_DEVICE": str(tmp_path / "no-tun")}).stdout
    assert "tailscaled runs in userspace mode" in without
    assert 'FLAGS="--tun=userspace-networking"' in without
    # The daemon is started before the operator is set: that call needs it.
    assert without.index("systemctl restart tailscaled") < without.index("tailscale set --operator")
    with_tun = dry_run(*args, env={**ANSWERS, "CLOUDMORROW_TUN_DEVICE": str(tmp_path)}).stdout
    assert "userspace" not in with_tun
    # Linked, there is no proxy to put in front.
    assert "First, a proxy in front" not in without


def test_linking_asks_before_installing_anything():
    result = dry_run("--name", "X", "--link", "--user", "alice", "--quills", "all", env=ANSWERS)
    assert result.returncode == 0, result.stderr + result.stdout
    if "tailscale is here" not in result.stdout:
        assert "would ask: Install Tailscale's client" in result.stdout
    if "caddy is here" not in result.stdout:
        assert "would ask: Install Caddy" in result.stdout


def test_a_relay_of_ones_own_and_no_link():
    own = dry_run(
        "--name",
        "X",
        "--link",
        "--yes",
        "--access-control",
        "https://relay.example.org",
        "--user",
        "alice",
        "--quills",
        "all",
        env=ANSWERS,
    )
    assert "linking through https://relay.example.org" in own.stdout
    home = dry_run("--name", "X", "--no-link", "--user", "alice", "--quills", "all", env=ANSWERS)
    assert "would ask: whether to link" not in home.stdout and "access link" not in home.stdout


def test_the_unit_may_write_the_caddy_site():
    text = INSTALLER.read_text()
    assert "ReadWritePaths=$NOTES_DIR $DATA_DIR $PREFIX -$CADDY_DIR" in text
    # Caddy imports the site the service writes, and nothing else is replaced.
    assert "import $CADDY_DIR/*.caddy" in text
    assert "grep -q '/usr/share/caddy'" in text
    # No public mode is left in it.
    for gone in ("cmtunnel", "--public-name", "access claim", "--private"):
        assert gone not in text
