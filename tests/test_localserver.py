"""`cm` on the server itself: it finds the server beside it, at whichever
address that answers on, counts that address as this machine, and enrols no
second agent on a box that has the server's own."""

from __future__ import annotations

import asyncio
import os
import stat

import pytest

from cloudmorrow import localserver
from cloudmorrow.agent.setup import ensure_agent
from cloudmorrow.client.config import DEFAULT_API_URL, ClientConfig
from cloudmorrow.links import link_server_commands
from cloudmorrow.transport import InsecureUrlError, check_url, is_local_url


@pytest.fixture()
def server_here(tmp_path, monkeypatch):
    """Point the client at a server config on 'this machine'; returns a writer for it."""
    path = tmp_path / "server.toml"
    monkeypatch.setattr(localserver, "CONFIG_PATH", path)

    def listening(host: str, port: int = 8787) -> None:
        path.write_text(f'[server]\nname = "Trial"\nhost = "{host}"\nport = {port}\n')

    return listening


# -- where the server here is ------------------------------------------------
def test_no_server_config_means_no_server_here():
    assert not localserver.is_here()
    assert localserver.url() == ""
    assert not localserver.answers_on("http://127.0.0.1:8787")


@pytest.mark.parametrize(
    ("host", "url"),
    [
        ("0.0.0.0", "http://127.0.0.1:8787"),
        ("::", "http://127.0.0.1:8787"),
        ("127.0.0.1", "http://127.0.0.1:8787"),
        ("localhost", "http://127.0.0.1:8787"),
        ("::1", "http://[::1]:8787"),
        # Only its own address: reached there, which is still this machine.
        ("192.168.1.5", "http://192.168.1.5:8787"),
        ("10.0.0.2, 127.0.0.1", "http://127.0.0.1:8787"),
        ("10.0.0.2, 192.168.1.5", "http://10.0.0.2:8787"),
        ("fd00::5", "http://[fd00::5]:8787"),
    ],
)
def test_the_server_here_is_reached_as_its_own_processes_reach_it(server_here, host, url):
    server_here(host)
    assert localserver.is_here()
    assert localserver.url() == url


def test_the_port_is_the_servers(server_here):
    server_here("0.0.0.0", 9000)
    assert localserver.url() == "http://127.0.0.1:9000"


def test_the_servers_config_can_be_elsewhere(tmp_path, monkeypatch):
    elsewhere = tmp_path / "etc" / "server.toml"
    elsewhere.parent.mkdir()
    elsewhere.write_text('[server]\nhost = "10.0.0.2"\n')
    monkeypatch.setenv("CLOUDMORROW_SERVER_CONFIG", str(elsewhere))
    assert localserver.url() == "http://10.0.0.2:8787"


def test_a_config_that_is_not_one_is_no_server(server_here):
    localserver.CONFIG_PATH.write_text("not toml at all = [")
    assert not localserver.is_here()
    localserver.CONFIG_PATH.write_text('[server]\nport = "many"\n')
    assert not localserver.is_here()


# -- an address the server here listens on is this machine -------------------
def test_an_address_the_server_here_listens_on_is_local(server_here):
    server_here("192.168.1.5, fd00::5")
    assert localserver.answers_on("http://192.168.1.5:8787")
    assert localserver.answers_on("http://[fd00::5]:8787")
    assert is_local_url("http://192.168.1.5:8787")
    assert check_url("http://192.168.1.5:8787") == "http://192.168.1.5:8787"
    # Another port on the same host is something else; so is another host.
    assert not localserver.answers_on("http://192.168.1.5:9000")
    assert not localserver.answers_on("http://192.168.1.5")
    assert not is_local_url("http://192.168.1.6:8787")
    with pytest.raises(InsecureUrlError):
        check_url("http://192.168.1.6:8787")


def test_a_wildcard_says_nothing_about_which_addresses_are_this_machine(server_here):
    server_here("0.0.0.0")
    assert not localserver.answers_on("http://192.168.1.5:8787")
    assert not is_local_url("http://192.168.1.5:8787")
    # Loopback is this machine as it always was.
    assert is_local_url("http://127.0.0.1:8787")


# -- a client with no config of its own signs in to the server here ----------
def test_a_client_with_no_config_takes_the_server_here(server_here):
    server_here("0.0.0.0")
    assert ClientConfig.load().api_url == "http://127.0.0.1:8787"


def test_a_client_with_no_config_and_no_server_here_keeps_the_default():
    assert ClientConfig.load().api_url == DEFAULT_API_URL


def test_a_config_of_their_own_wins_over_the_server_here(server_here):
    server_here("0.0.0.0")
    config = ClientConfig.load()
    config.api_url = "https://cloud.example.com"
    config.save()
    assert ClientConfig.load().api_url == "https://cloud.example.com"


def test_a_config_that_leaves_the_address_out_still_takes_the_server_here(server_here):
    server_here("0.0.0.0")
    from cloudmorrow.client.config import config_path

    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text('[client]\nvault = "home"\n')
    config = ClientConfig.load()
    assert config.api_url == "http://127.0.0.1:8787"
    assert config.vault == "home"


def test_the_environment_wins_over_the_server_here(server_here, monkeypatch):
    server_here("0.0.0.0")
    monkeypatch.setenv("CLOUDMORROW_API_URL", "https://elsewhere.example")
    assert ClientConfig.load().api_url == "https://elsewhere.example"


def test_signing_in_does_not_look_on_the_network_when_the_server_is_here(server_here, monkeypatch):
    """`cm login` with no config: the server beside it, not a search of the LAN."""
    from cloudmorrow.cli import main as cli

    server_here("127.0.0.1")
    looked: list[str] = []
    monkeypatch.setattr(cli, "choose_cloud", lambda config, found=None: looked.append("browsed"))
    monkeypatch.setattr("builtins.input", lambda prompt="": "alice")
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": "longenough")
    signed_in: dict = {}

    class FakeApi:
        def __init__(self, config):
            signed_in["api_url"] = config.api_url

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def login(self, username, password):
            raise RuntimeError("far enough")

    monkeypatch.setattr(cli, "CloudmorrowClient", FakeApi)
    with pytest.raises(RuntimeError, match="far enough"):
        cli.login(username=None, server=None, agent_setup=False)
    assert looked == []
    assert signed_in["api_url"] == "http://127.0.0.1:8787"


# -- the server's own agent is the machine's ---------------------------------
def test_signing_in_on_the_server_enrols_no_second_agent(server_here):
    server_here("0.0.0.0")
    result = asyncio.run(ensure_agent(api=None))
    assert not result.enrolled
    assert not result.started
    assert "agent of its own" in result.detail


# -- cm beside cloudmorrow-server on the PATH ----------------------------------
def _server_installed(tmp_path, *tools: str):
    """A server's venv with these commands in its bin, and cloudmorrow-server linked onto a bin dir."""
    prefix = tmp_path / "venv"
    (prefix / "bin").mkdir(parents=True)
    for tool in ("cloudmorrow-server", *tools):
        (prefix / "bin" / tool).write_text("#!/bin/sh\n")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "cloudmorrow-server").symlink_to(prefix / "bin" / "cloudmorrow-server")
    return prefix, bindir


def test_the_terminal_app_is_linked_beside_the_server_command(tmp_path):
    prefix, bindir = _server_installed(tmp_path, "cm", "cloudmorrow", "cloudmorrow-agent")
    linked, unlinked = link_server_commands(prefix, which=lambda _: str(bindir / "cloudmorrow-server"))
    assert sorted(linked) == sorted([bindir / "cloudmorrow", bindir / "cm"])
    assert unlinked == []
    assert (bindir / "cm").resolve() == (prefix / "bin" / "cm").resolve()
    # Not the agent: the server's own runs from the venv, under its unit.
    assert not (bindir / "cloudmorrow-agent").exists()
    # Again: nothing to do, nothing reported.
    assert link_server_commands(prefix, which=lambda _: str(bindir / "cloudmorrow-server")) == ([], [])


def test_a_cm_that_is_somebody_elses_is_left_alone(tmp_path):
    prefix, bindir = _server_installed(tmp_path, "cm", "cloudmorrow")
    (bindir / "cm").write_text("#!/bin/sh\necho mine\n")
    linked, unlinked = link_server_commands(prefix, which=lambda _: str(bindir / "cloudmorrow-server"))
    assert linked == [bindir / "cloudmorrow"]
    assert unlinked == []
    assert (bindir / "cm").read_text() == "#!/bin/sh\necho mine\n"


def test_nothing_is_linked_when_cloudmorrow_server_is_not_our_link(tmp_path):
    prefix, bindir = _server_installed(tmp_path, "cm")
    (bindir / "cloudmorrow-server").unlink()
    (bindir / "cloudmorrow-server").write_text("#!/bin/sh\n")
    assert link_server_commands(prefix, which=lambda _: str(bindir / "cloudmorrow-server")) == ([], [])
    assert link_server_commands(prefix, which=lambda _: None) == ([], [])


@pytest.mark.skipif(os.geteuid() == 0, reason="root may write anywhere")
def test_what_the_service_user_could_not_link_is_said_by_name(tmp_path):
    """An update runs as the service user, which does not own /usr/local/bin."""
    prefix, bindir = _server_installed(tmp_path, "cm", "cloudmorrow")
    bindir.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        linked, unlinked = link_server_commands(prefix, which=lambda _: str(bindir / "cloudmorrow-server"))
    finally:
        bindir.chmod(stat.S_IRWXU)
    assert linked == []
    assert unlinked == ["cloudmorrow", "cm"]
