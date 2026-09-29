"""The Caddy site a linked cloud writes: its name, the DNS challenge, and two issuers."""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from cloudmorrow.server.access_caddy import ZEROSSL, site_block, upstream_host
from cloudmorrow.server.access_control import Cloud

ACME = {
    "username": "u-1",
    "password": 'p "quoted"',
    "subdomain": "sub-1",
    "server_url": "https://relay.x.test/v1/acme-dns",
}
CLOUD = Cloud(cloud_id="c1", token="t", name="larsens", zone="cloudmorrow.test", acme=ACME, set_up=True)
CONTROL = "https://relay.cloudmorrow.test"
# A Caddy built with the acmedns module, to check the site is one Caddy reads.
CADDY = os.environ.get("CLOUDMORROW_CADDY_BIN") or shutil.which("caddy")


def issuers(site: str) -> list[str]:
    return [line.strip() for line in site.splitlines() if line.strip().startswith(("issuer", "dir "))]


def test_lets_encrypt_first_then_zerossl_both_by_dns(config):
    config.access_acme_email = "owner@example.org"
    site = site_block(CLOUD, config, CONTROL)
    assert site.splitlines()[2] == "larsens.cloudmorrow.test {"
    assert issuers(site) == ["issuer acme {", "issuer acme {", f"dir {ZEROSSL}"]
    assert site.count("dns acmedns {") == 2
    assert site.count('email "owner@example.org"') == 2
    # Quoted, so nothing the relay hands over can close a block early.
    assert 'password "p \\"quoted\\""' in site
    assert "reverse_proxy 127.0.0.1:8787" in site


def test_without_an_email_there_is_no_fallback_and_it_says_why(config):
    site = site_block(CLOUD, config, CONTROL)
    assert issuers(site) == ["issuer acme {"]
    assert "access_acme_email" in site and "zerossl" not in site.replace("ZeroSSL", "")
    config.access_acme_email = "owner@example.org"
    config.access_acme_fallback = False
    assert issuers(site_block(CLOUD, config, CONTROL)) == ["issuer acme {"]


def test_the_relays_own_endpoint_when_the_link_names_none(config):
    cloud = Cloud(cloud_id="c1", token="t", name="larsens", zone="cloudmorrow.test", acme={"username": "u"})
    assert f'server_url "{CONTROL}/v1/acme-dns"' in site_block(cloud, config, CONTROL)


def test_the_upstream_is_where_the_server_listens(config):
    assert upstream_host(config) == "127.0.0.1"
    config.host = "10.0.0.2, 127.0.0.1"
    assert upstream_host(config) == "127.0.0.1"
    config.host = "10.0.0.2"
    assert upstream_host(config) == "10.0.0.2"
    config.host = "fd00::2"
    assert upstream_host(config) == "[fd00::2]"


def test_the_settings_are_read_from_the_config_file(tmp_path, monkeypatch):
    from cloudmorrow.server.config import load_config

    path = tmp_path / "server.toml"
    path.write_text('[server]\naccess_acme_fallback = false\naccess_acme_email = "a@b.test"\n')
    loaded = load_config(path)
    assert loaded.access_acme_fallback is False and loaded.access_acme_email == "a@b.test"
    monkeypatch.setenv("CLOUDMORROW_ACCESS_ACME_EMAIL", "c@d.test")
    assert load_config(path).access_acme_email == "c@d.test"


@pytest.mark.skipif(not CADDY, reason="no caddy here to read the site")
def test_caddy_reads_the_site(config, tmp_path):
    modules = subprocess.run([CADDY, "list-modules"], capture_output=True, text=True, timeout=30).stdout
    if "dns.providers.acmedns" not in modules:
        pytest.skip("this caddy has no acmedns module")
    config.access_acme_email = "owner@example.org"
    site = tmp_path / "Caddyfile"
    site.write_text(site_block(CLOUD, config, CONTROL))
    adapted = subprocess.run(
        [CADDY, "adapt", "--config", str(site), "--adapter", "caddyfile"], capture_output=True, text=True, timeout=30
    )
    assert adapted.returncode == 0, adapted.stderr
    assert ZEROSSL in adapted.stdout and '"name":"acmedns"' in adapted.stdout.replace(" ", "")
