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
        {"name": "The Larsens", "version": "0.4.0", "url": f"https://{HOST}", "mesh": HOST},
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
        # Python 3.13's strict verification wants these, as real certificates have.
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
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
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
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
                sni = getattr(self.connection, "server_hostname", None)
                seen.append({"host": self.headers.get("Host"), "sni": sni})
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
        api._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
        return api

    monkeypatch.setattr(access_cli, "client", lambda: (ClientConfig(), api_for(tokens[who["as"]])))
    return app, fakes, who, api_for, tokens


def linked(app, fakes, api_for, tokens, name="larsens") -> None:
    import asyncio

    admin = api_for(tokens[ADMIN[0]])
    started = asyncio.run(admin.start_link())
    fakes.control.approve(started["link"]["code"], name)
    assert app.state.cloudmorrow.access.poll_once() == "linked"
    fakes.control.only().mesh_address = "100.64.0.7"


def test_cm_access_link_invite_devices(cloud, monkeypatch) -> None:
    app, fakes, who, api_for, tokens = cloud
    runner = CliRunner()
    result = runner.invoke(access_cli.app, ["status"])
    assert result.exit_code == 0, result.output
    assert "cm access link" in result.output

    result = runner.invoke(access_cli.app, ["link", "--no-wait"])
    assert result.exit_code == 0, result.output
    code = next(iter(fakes.control.links))
    assert f"Open cloudmorrow.test/link and enter {code}" in result.output
    fakes.control.approve(code, "larsens")
    app.state.cloudmorrow.access.poll_once()
    fakes.control.only().mesh_address = "100.64.0.7"
    result = runner.invoke(access_cli.app, ["status", "--json"])
    assert json.loads(result.stdout)["mesh"]["on"] is True

    who["as"] = GUEST[0]
    assert runner.invoke(access_cli.app, ["unlink", "--yes"]).exit_code == 1
    result = runner.invoke(access_cli.app, ["invite"])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0] == fakes.control.only().invites[-1]
    assert f"curl -fsSL https://{HOST}/install.sh | sh" in result.output and LOGIN_SERVER in result.output

    # A computer that joined with a key, and told the cloud it is the guest's.
    import asyncio

    key = asyncio.run(api_for(tokens[GUEST[0]]).mesh_key())
    fakes.control.join(key["key"], "100.64.0.9")
    asyncio.run(api_for(tokens[GUEST[0]]).claim_mesh_device("100.64.0.9", "laptop"))
    result = runner.invoke(access_cli.app, ["devices"])
    assert "guest: laptop" in result.stdout and "100.64.0.9" in result.stdout

    who["as"] = ADMIN[0]
    result = runner.invoke(access_cli.app, ["unlink", "--yes"])
    assert result.exit_code == 0 and "home network" in result.output
    assert "guest" not in fakes.control.bodies() and "laptop" not in fakes.control.bodies()


def test_bare_cm_access_is_your_own_access(cloud, monkeypatch) -> None:
    called = []
    monkeypatch.setattr(access_cli.circle, "access", lambda: called.append(True))
    result = CliRunner().invoke(access_cli.app, [])
    assert result.exit_code == 0 and called == [True]


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


def test_the_desktop_bridge_says_whether_this_computer_is_on_the_mesh_and_joins(cloud, tmp_path, monkeypatch) -> None:
    app, fakes, _, api_for, tokens = cloud
    from tests.access_fakes import fake_tailscale

    local = fake_tailscale(tmp_path / "laptop-bin", "NeedsLogin", ip="100.64.0.9")
    monkeypatch.setenv("PATH", f"{local}:{Path('/usr/bin')}:{Path('/bin')}")
    linked(app, fakes, api_for, tokens)
    calls: list[list[str]] = []
    bridge = Bridge(
        ClientConfig(api_url="http://testserver"),
        api_factory=lambda config: api_for(tokens[GUEST[0]]),
        run=unprivileged(calls),
    )
    status = bridge.mesh_status()
    assert status["available"] is True and status["enrolled"] is False
    assert status["login_server"] == LOGIN_SERVER and status["tailscale_installed"] is True

    # The fake relay lists what joins with its keys; the fake tailscale here joins
    # nothing there, so the bridge's key is joined by hand as the device would.
    real_join = meshjoin.join

    def join_and_appear(key, **kwargs):
        done = real_join(key, **kwargs)
        fakes.control.join(key["key"], done.address)
        return done

    monkeypatch.setattr(meshjoin, "join", join_and_appear)
    joined = bridge.mesh_join()
    assert joined["enrolled"] is True and joined["address"] == "100.64.0.9"
    up = next(c for c in calls if "up" in c)
    assert up[0] in ("pkexec", "sudo")
    assert up[up.index("--login-server") + 1] == LOGIN_SERVER
    hostname = up[up.index("--hostname") + 1]
    assert hostname.startswith("cm-") and len(hostname) == 9
    assert any(c.startswith("up ") for c in tailscale_calls(local))
    assert bridge.mesh_status()["enrolled"] is True
    # The cloud labelled it the guest's; the relay heard neither the name nor whose.
    labels = app.state.cloudmorrow.access.labels.all()
    assert [(label.owner, label.device) for label in labels.values()] == [("guest", meshjoin.device_name())]
    assert meshjoin.device_name() not in fakes.control.bodies()


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


def test_device_names_are_what_you_call_it_and_hostnames_say_nothing(monkeypatch) -> None:
    monkeypatch.setattr(meshjoin.socket, "gethostname", lambda: "Anna's MacBook.local")
    assert meshjoin.device_name() == "anna-s-macbook"
    names = {meshjoin.new_hostname() for _ in range(20)}
    assert all(n.startswith("cm-") and len(n) == 9 and "anna" not in n for n in names)
    assert len(names) > 1


# -- an invite -----------------------------------------------------------------------
def test_an_invite_is_redeemed_at_the_relay_with_only_the_name_and_the_code(config, users, tmp_path) -> None:
    from cloudmorrow.server.access_ways import Access

    access = Access(config, lambda: "The Larsens")
    fakes = wire(access, tmp_path)
    fakes.control.approve(access.link()["code"], "larsens")
    access.poll_once()
    code = access.invite()["code"]
    relay = TestClient(fakes.control.app)
    before = len(fakes.control.calls)
    key = meshjoin.redeem(f"https://{HOST}", code.lower()[:3] + "-" + code.lower()[3:], http=relay)
    assert key["key"].startswith("hskey-") and key["login_server"] == LOGIN_SERVER
    ((method, path, body),) = fakes.control.calls[before:]
    assert (method, path) == ("POST", "/v1/invites/redeem") and body == {"name": "larsens", "code": code}
    # Once.
    with pytest.raises(meshjoin.JoinError, match="wrong, used, or ran out"):
        meshjoin.redeem(f"https://{HOST}", code, http=relay)
    assert meshjoin.relay_for(f"https://{HOST}") == "https://relay.cloudmorrow.test"
    assert meshjoin.relay_for(f"https://{HOST}", "https://relay.example.org/") == "https://relay.example.org"
    with pytest.raises(meshjoin.JoinError):
        meshjoin.cloud_name_of("http://localhost:8787")


def test_cm_access_join_with_an_invite(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        meshjoin, "redeem", lambda server, code, access_control="": {"key": "hskey-1", "login_server": LOGIN_SERVER}
    )
    joined_with: list[tuple] = []

    def fake_join(key, *, hostname="", install=None, **kwargs):
        joined_with.append((key["key"], hostname))
        return meshjoin.MeshState(installed=True, running=True, address="100.64.0.9")

    monkeypatch.setattr(meshjoin, "join", fake_join)
    result = CliRunner().invoke(access_cli.app, ["join", "--invite", "ABC123", "--server", f"https://{HOST}"])
    assert result.exit_code == 0, result.output
    assert joined_with and joined_with[0][0] == "hskey-1" and joined_with[0][1].startswith("cm-")
    assert "on the mesh" in result.output and "access mine" in result.output


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


def test_the_installer_dry_run_with_an_invite_joins_then_signs_in(client, tmp_path) -> None:
    result = dry_run(client.get("/install.sh").text, tmp_path, "--invite", "--yes")
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "would run:" in out and "pip install" in out
    assert "would ask: the invite code" in out
    join = next(line for line in out.splitlines() if "access join --invite" in line)
    assert "--server http://testserver" in join and join.rstrip().endswith("--yes")
    assert out.index("access join --invite") < out.index("cloudmorrow login --server") < out.index("access mine")
    # Nothing was installed.
    assert not (tmp_path / ".local" / "share" / "cloudmorrow").exists()


def test_the_installer_takes_the_code_and_a_relay_of_its_own(client, tmp_path) -> None:
    result = dry_run(
        client.get("/install.sh").text, tmp_path, "--invite", "7QX2MP", "--access-control", "https://relay.example.org"
    )
    assert result.returncode == 0, result.stderr
    assert "would ask: the invite code" not in result.stdout
    assert "access join --invite 7QX2MP --server http://testserver --access-control https://relay.example.org" in (
        result.stdout
    )


def test_the_installer_signs_in_and_asks_for_no_code(client, tmp_path) -> None:
    """Signing in is what joins the mesh now (client/autojoin.py): no invite, no code."""
    result = dry_run(client.get("/install.sh").text, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "cloudmorrow login --server http://testserver" in result.stdout
    assert "invite" not in result.stdout.lower()
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
    # As the landing page runs it.
    ran = dry_run(text, tmp_path, "--server", f"https://{HOST}/", "--invite", "7QX2MP")
    assert ran.returncode == 0, ran.stderr
    assert f"access join --invite 7QX2MP --server https://{HOST}" in ran.stdout
    assert "releases/download/v9.9.9" in ran.stdout


def test_the_release_workflow_publishes_the_installer() -> None:
    workflow = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "release.yml").read_text()
    assert 'tags: ["v*"]' in workflow
    assert "scripts/release_installer.py" in workflow
    assert "gh release create" in workflow and "dist/install.sh" in workflow and "dist/*.whl" in workflow
