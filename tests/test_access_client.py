"""The client's side of reaching a cloud: finding it, going straight to it, joining its mesh."""

from __future__ import annotations

import datetime as dt
import http.server
import json
import ssl
import subprocess
import threading
from pathlib import Path

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from cloudmorrow.cli import access as access_cli
from cloudmorrow.cli import main as cli_main
from cloudmorrow.client import discover, meshjoin
from cloudmorrow.client.api import ApiError, CloudmorrowClient
from cloudmorrow.client.config import ClientConfig
from cloudmorrow.client.localroute import LocalRoute, local_transport
from cloudmorrow.desktop.bridge import Bridge
from cloudmorrow.server.app import create_app
from tests.access_fakes import LOGIN_SERVER, ZONE, tailscale_calls, wire
from tests.conftest import ADMIN, GUEST, token_for

HOST = f"larsens.{ZONE}"


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
        {"name": "The Larsens", "version": "0.4.0", "url": f"https://{HOST}", "public": HOST},
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
    assert larsens.host == HOST and larsens.api_url == f"https://{HOST}"
    assert larsens.local_address == "192.168.1.20:443" and not larsens.plain
    assert attic.api_url == "http://attic.local:8787" and attic.plain
    assert attic.local_address == ""
    assert discover.matching(found, f"https://{HOST}/") is larsens
    assert discover.matching(found, "https://elsewhere.example") is None


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
    assert again.api_url == f"https://{HOST}" and again.local_address == "192.168.1.20:443"
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
    # Once to list, once after signing in to note where the box is.
    assert len(browsed) == 2

    # Configured now: no list, the old behaviour.
    browsed.clear()
    result = runner.invoke(cli_main.app, ["login", "--no-agent", "-u", "bram"])
    assert result.exit_code == 0, result.output
    assert len(browsed) == 1  # only the look for its local address
    assert ClientConfig.load().local_address == "192.168.1.20:443"


# -- straight to the box, checked against the real name ------------------------------
def _cert(ca_key, ca_cert, name: str):
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


@pytest.fixture()
def pki(tmp_path):
    ca_key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    trust = ssl.create_default_context(cadata=ca_cert.public_bytes(serialization.Encoding.PEM).decode())

    def server_for(name: str) -> tuple[int, list[dict], http.server.HTTPServer]:
        key, cert = _cert(ca_key, ca_cert, name)
        pem = tmp_path / f"{name}.pem"
        pem.write_bytes(
            cert.public_bytes(serialization.Encoding.PEM)
            + key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        seen: list[dict] = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                seen.append({"host": self.headers.get("Host"), "sni": getattr(self.connection, "server_hostname", None)})
                body = json.dumps({"address": f"https://{HOST}"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(pem)
        names: list[str] = []
        context.sni_callback = lambda sock, server_name, ctx: names.append(server_name)
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        seen.append({"sni_names": names})
        return httpd.server_address[1], seen, httpd

    return trust, server_for


async def test_the_local_route_verifies_against_the_real_name(pki) -> None:
    trust, server_for = pki
    port, seen, httpd = server_for(HOST)
    try:
        config = ClientConfig(api_url=f"https://{HOST}", local_address=f"127.0.0.1:{port}")
        config.verify_tls = trust
        api = CloudmorrowClient(config, token="x")
        assert isinstance(api.local, LocalRoute)
        assert (await api.access())["address"] == f"https://{HOST}"
        await api.aclose()
        names = seen[0]["sni_names"]
        assert names == [HOST]
        assert seen[1]["host"] == HOST
    finally:
        httpd.shutdown()


async def test_a_box_with_another_names_certificate_is_refused(pki) -> None:
    trust, server_for = pki
    port, seen, httpd = server_for("impostor.example")
    try:
        config = ClientConfig(api_url=f"https://{HOST}", local_address=f"127.0.0.1:{port}")
        config.verify_tls = trust
        api = CloudmorrowClient(config, token="x")
        with pytest.raises(ApiError):
            await api.access()
        await api.aclose()
        assert len(seen) == 1  # the handshake failed: nothing was asked
    finally:
        httpd.shutdown()


def test_away_from_home_the_real_name_is_used() -> None:
    # Nothing listens on port 1: the probe fails and there is no local route.
    assert local_transport(f"https://{HOST}", "127.0.0.1:1") is None
    assert local_transport("http://attic.local:8787", "127.0.0.1:1", probe=False) is None
    assert local_transport(f"https://{HOST}", "", probe=False) is None
    api = CloudmorrowClient(ClientConfig(api_url=f"https://{HOST}", local_address="127.0.0.1:1"))
    assert api.local is None


# -- cm access, against the real routes ----------------------------------------------
@pytest.fixture()
def cloud(config, users, tmp_path, monkeypatch):
    app = create_app(config)
    fakes = wire(app.state.cloudmorrow.access, tmp_path)
    client = TestClient(app)
    tokens = {name: token_for(client, name, pw) for name, pw in (ADMIN, GUEST)}
    who = {"as": ADMIN[0]}

    def api_for(token: str) -> CloudmorrowClient:
        api = CloudmorrowClient(ClientConfig(api_url="http://testserver"), token=token)
        api._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        )
        return api

    monkeypatch.setattr(
        access_cli, "client", lambda: (ClientConfig(), api_for(tokens[who["as"]]))
    )
    return app, fakes, who, api_for, tokens


def test_cm_access_status_public_private_pair_key_devices(cloud) -> None:
    app, fakes, who, _, _ = cloud
    runner = CliRunner()
    result = runner.invoke(access_cli.app, ["status"])
    assert result.exit_code == 0, result.output
    assert "no name yet" in result.output

    result = runner.invoke(access_cli.app, ["public", "larsens"])
    assert result.exit_code == 0, result.output
    assert f"https://{HOST}" in result.output
    result = runner.invoke(access_cli.app, ["private", "on"])
    assert result.exit_code == 0, result.output
    assert "100.64.0.7" in result.output

    who["as"] = GUEST[0]
    assert runner.invoke(access_cli.app, ["public", "off"]).exit_code == 1
    result = runner.invoke(access_cli.app, ["pair", "--device", "phone"])
    assert result.exit_code == 0 and LOGIN_SERVER in result.output
    code = fakes.control.by_name("larsens").codes[-1]["code"]
    assert result.stdout.splitlines()[0] == code
    result = runner.invoke(access_cli.app, ["key", "--device", "laptop"])
    key = result.stdout.splitlines()[0]
    assert key.startswith("hskey-")
    fakes.control.join(key, "guests-laptop", "100.64.0.9")
    result = runner.invoke(access_cli.app, ["devices"])
    assert "guests-laptop" in result.stdout

    who["as"] = ADMIN[0]
    result = runner.invoke(access_cli.app, ["public", "off"])
    assert "public access is off" in result.output
    result = runner.invoke(access_cli.app, ["status", "--json"])
    assert json.loads(result.stdout)["private"]["on"] is True


# -- this computer on the mesh -------------------------------------------------------
def unprivileged(calls: list[list[str]]):
    """Runs a command as meshjoin would, without the sudo or pkexec in front."""

    def run(cmd):
        cmd = list(cmd)
        calls.append(cmd)
        if cmd and cmd[0] in ("sudo", "pkexec"):
            cmd = cmd[1:]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    return run


def test_the_desktop_bridge_says_whether_this_computer_is_on_the_mesh_and_joins(
    cloud, tmp_path, monkeypatch
) -> None:
    app, fakes, _, api_for, tokens = cloud
    from tests.access_fakes import fake_tailscale

    local = fake_tailscale(tmp_path / "laptop-bin", "NeedsLogin")
    monkeypatch.setenv("PATH", f"{local}:{Path('/usr/bin')}:{Path('/bin')}")
    admin = api_for(tokens[ADMIN[0]])
    import asyncio

    asyncio.run(admin.claim_name("larsens", public=True, private=True))
    calls: list[list[str]] = []
    bridge = Bridge(
        ClientConfig(api_url="http://testserver"),
        api_factory=lambda config: api_for(tokens[GUEST[0]]),
        run=unprivileged(calls),
    )
    status = bridge.mesh_status()
    assert status["available"] is True and status["enrolled"] is False
    assert status["login_server"] == LOGIN_SERVER and status["tailscale_installed"] is True

    joined = bridge.mesh_join()
    assert joined["enrolled"] is True and joined["address"] == "100.64.0.7"
    up = next(c for c in calls if "up" in c)
    assert up[0] in ("pkexec", "sudo")
    assert up[up.index("--login-server") + 1] == LOGIN_SERVER
    assert up[up.index("--hostname") + 1] == meshjoin.device_name()
    minted = fakes.control.by_name("larsens").keys[-1]
    assert up[up.index("--authkey") + 1] == minted["key"]
    assert minted["for"] == f"guest: {meshjoin.device_name()}"
    assert any(c.startswith("up ") for c in tailscale_calls(local))
    assert bridge.mesh_status()["enrolled"] is True


def test_without_tailscale_the_bridge_says_how_to_get_it(cloud, tmp_path, monkeypatch) -> None:
    _, _, _, api_for, tokens = cloud
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(meshjoin, "MAC_CLI", str(tmp_path / "nope"))
    bridge = Bridge(ClientConfig(api_url="http://testserver"), api_factory=lambda c: api_for(tokens[GUEST[0]]))
    answer = bridge.mesh_join()
    assert answer.get("install") is True and "Tailscale is not on this computer" in answer["error"]


def test_join_installs_tailscale_only_with_consent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(meshjoin.platform, "system", lambda: "Linux")
    monkeypatch.setattr(meshjoin.shutil, "which", lambda name: "/usr/bin/curl" if name == "curl" else None)
    ran: list[list[str]] = []
    key = {"key": "k", "login_server": LOGIN_SERVER}
    with pytest.raises(meshjoin.JoinError, match="not installed"):
        meshjoin.join(key, install=lambda: False, run=lambda cmd: ran.append(list(cmd)))
    assert ran == []
    # On a Mac, the App Store is the way, and this says so.
    monkeypatch.setattr(meshjoin.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(meshjoin, "MAC_CLI", str(tmp_path / "nope"))
    with pytest.raises(meshjoin.JoinError, match="App Store"):
        meshjoin.join(key, install=lambda: True, run=lambda cmd: ran.append(list(cmd)))


def test_device_names_are_hostnames(monkeypatch) -> None:
    monkeypatch.setattr(meshjoin.socket, "gethostname", lambda: "Anna's MacBook.local")
    assert meshjoin.device_name() == "anna-s-macbook"


# -- the client installer ------------------------------------------------------------
def test_the_installer_dry_run_with_private_signs_in_and_joins(client, tmp_path) -> None:
    script = tmp_path / "install.sh"
    script.write_text(client.get("/install.sh").text)
    result = subprocess.run(
        ["sh", str(script), "--dry-run", "--private", "--yes", "--no-desktop"],
        capture_output=True,
        text=True,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "would run:" in out and "pip install" in out
    assert "cloudmorrow login --server" in out
    assert "cloudmorrow access join --yes" in out
    assert "lists the clouds it finds" in out
    # Nothing was installed.
    assert not (tmp_path / ".local" / "share" / "cloudmorrow").exists()


def test_the_installer_without_private_mentions_joining(client, tmp_path) -> None:
    script = tmp_path / "install.sh"
    script.write_text(client.get("/install.sh").text)
    result = subprocess.run(
        ["sh", str(script), "--dry-run", "--no-desktop"],
        capture_output=True, text=True, env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "access join" in result.stdout and "--server" not in result.stdout.split("Installed.")[0]
