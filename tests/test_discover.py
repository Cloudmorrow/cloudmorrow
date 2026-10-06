"""Finding a cloud on the home network, `cm login` with nothing configured, and the client installer."""

from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from cloudmorrow.cli import main as cli_main
from cloudmorrow.client import discover
from cloudmorrow.client.config import ClientConfig

HOST = "cloud.example.com"


# -- finding clouds ------------------------------------------------------------------
class Info:
    """Shaped like zeroconf's ServiceInfo, as much as discover reads of it."""

    def __init__(self, name: str, props: dict, addresses: list[str], port: int) -> None:
        self.name = name
        self.properties = {k.encode(): v.encode() for k, v in props.items()}
        self._addresses = addresses
        self.port = port

    def parsed_addresses(self) -> list[str]:
        return list(self._addresses)


INFOS = [
    Info(
        "larsens._cloudmorrow._tcp.local.",
        {"name": "The Larsens", "version": "0.4.0", "url": f"https://{HOST}"},
        ["fe80::1", "192.168.1.20"],
        443,
    ),
    Info(
        "attic._cloudmorrow._tcp.local.",
        {"name": "Attic", "version": "0.4.0", "url": "http://attic.local:8787"},
        ["192.168.1.30"],
        8787,
    ),
    Info("stray._cloudmorrow._tcp.local.", {"name": "Nothing to open"}, ["192.168.1.40"], 1),
]


def test_browse_reads_what_each_box_announces() -> None:
    found = discover.browse(0, infos=lambda seconds: INFOS)
    assert [f.name for f in found] == ["Attic", "The Larsens"]
    attic, larsens = found
    assert larsens.api_url == f"https://{HOST}" and not larsens.plain
    assert attic.api_url == "http://attic.local:8787" and attic.plain
    assert "192.168.1.30" in attic.describe()


def test_browse_without_multicast_finds_nothing() -> None:
    def broken(seconds):
        raise OSError("no multicast here")

    assert discover.browse(0, infos=broken) == []


# -- cm login with nothing configured ------------------------------------------------
def test_choose_cloud_takes_the_one_picked(monkeypatch) -> None:
    found = discover.browse(0, infos=lambda seconds: INFOS)
    monkeypatch.setattr("builtins.input", lambda prompt="": "2")
    config = ClientConfig()
    cli_main.choose_cloud(config, found)
    again = ClientConfig.load()
    assert again.api_url == f"https://{HOST}"
    assert again.allow_insecure_http is False

    monkeypatch.setattr("builtins.input", lambda prompt="": "1")
    cli_main.choose_cloud(config, found)
    again = ClientConfig.load()
    assert again.api_url == "http://attic.local:8787" and again.allow_insecure_http is True


def test_choose_cloud_asks_for_an_address_when_none_answer(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt="": "cloud.example.com")
    cli_main.choose_cloud(ClientConfig(), [])
    assert ClientConfig.load().api_url == "https://cloud.example.com"


class FakeLoginClient:
    def __init__(self, config) -> None:
        self.config = config

    async def login(self, username, password):
        from cloudmorrow.client.api import Session

        return Session(username=username, access_token="t", expires_at="")

    async def aclose(self) -> None: ...

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None: ...


def test_login_browses_only_when_nothing_is_configured(monkeypatch) -> None:
    browsed: list[float] = []

    real_browse = discover.browse

    def fake_browse(seconds=2.0, infos=None):
        browsed.append(seconds)
        return real_browse(0, infos=lambda s: INFOS)

    monkeypatch.setattr(discover, "browse", fake_browse)
    monkeypatch.setattr(cli_main, "CloudmorrowClient", FakeLoginClient)
    monkeypatch.setattr(cli_main.getpass, "getpass", lambda prompt="": "pw")
    monkeypatch.delenv("CLOUDMORROW_API_URL", raising=False)
    runner = CliRunner()
    result = runner.invoke(cli_main.app, ["login", "--no-agent", "-u", "bram"], input="2\n")
    assert result.exit_code == 0, result.output
    assert ClientConfig.load().api_url == f"https://{HOST}"
    assert len(browsed) == 1

    # Configured now: no list, the old behaviour.
    browsed.clear()
    result = runner.invoke(cli_main.app, ["login", "--no-agent", "-u", "bram"])
    assert result.exit_code == 0, result.output
    assert browsed == []


def test_bare_cm_access_is_your_own_access() -> None:
    command = next(c for c in cli_main.app.registered_commands if c.name == "access")
    assert command.callback is cli_main.circle.access


# -- the client installer ------------------------------------------------------------
def dry_run(script_text: str, tmp_path, *args: str):
    script = tmp_path / "install.sh"
    script.write_text(script_text)
    import re

    done = subprocess.run(
        ["sh", str(script), "--dry-run", "--no-desktop", *args],
        capture_output=True,
        text=True,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # no /dev/tty to ask on, as under a CI runner
        timeout=60,
    )
    done.stdout = re.sub(r"\x1b\[[0-9;]*m", "", done.stdout)
    return done


def test_the_installer_signs_in_and_asks_for_no_code(client, tmp_path) -> None:
    result = dry_run(client.get("/install.sh").text, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "cloudmorrow login --server http://testserver" in result.stdout
    assert "invite" not in result.stdout.lower() and "tailscale" not in result.stdout.lower()
    skipped = dry_run(client.get("/install.sh").text, tmp_path, "--no-login")
    assert "cloudmorrow login --server" not in skipped.stdout


def test_the_released_installer_is_for_whichever_cloud_it_is_given(tmp_path) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from release_installer import render

    text = render("v9.9.9", "cloudmorrow-9.9.9-py3-none-any.whl")
    assert "__" not in text
    assert (
        'PACKAGE="cloudmorrow[tui,agent] @ '
        'https://github.com/Cloudmorrow/cloudmorrow/releases/download/v9.9.9/cloudmorrow-9.9.9-py3-none-any.whl"'
    ) in text
    # With no --server and no terminal to ask on, it says what it needs.
    lost = dry_run(text, tmp_path)
    assert lost.returncode != 0 and "--server" in lost.stderr
    ran = dry_run(text, tmp_path, "--server", f"https://{HOST}/")
    assert ran.returncode == 0, ran.stderr
    assert f"cloudmorrow login --server https://{HOST}" in ran.stdout
    assert "releases/download/v9.9.9" in ran.stdout


def test_the_release_workflow_publishes_the_installer() -> None:
    workflow = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "release.yml").read_text()
    assert 'tags: ["v*"]' in workflow
    assert "scripts/release_installer.py" in workflow
    assert "gh release create" in workflow and "dist/install.sh" in workflow and "dist/*.whl" in workflow
