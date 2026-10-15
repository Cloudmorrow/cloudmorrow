"""A reverse proxy on another machine, believed about https."""

from __future__ import annotations

from cloudmorrow.server.config import ServerConfig, load_config


def test_nothing_configured_leaves_uvicorn_to_its_own_default():
    assert ServerConfig().forwarded_allow_ips is None
    assert ServerConfig(trusted_proxies=[" "]).forwarded_allow_ips is None


def test_a_named_proxy_is_trusted_alongside_the_loopback():
    config = ServerConfig(trusted_proxies=["100.115.4.117", "10.0.0.0/8"])
    assert config.forwarded_allow_ips == "127.0.0.1, 100.115.4.117, 10.0.0.0/8"
    assert ServerConfig(trusted_proxies=["127.0.0.1"]).forwarded_allow_ips == "127.0.0.1"
    assert ServerConfig(trusted_proxies=["10.0.0.1", "*"]).forwarded_allow_ips == "*"


def test_it_is_read_from_the_config_and_the_environment(tmp_path, monkeypatch):
    toml = tmp_path / "server.toml"
    toml.write_text('[server]\ntrusted_proxies = ["100.115.4.117"]\n')
    assert load_config(toml).trusted_proxies == ["100.115.4.117"]
    toml.write_text('[server]\ntrusted_proxies = "100.115.4.117, 10.0.0.0/8"\n')
    assert load_config(toml).trusted_proxies == ["100.115.4.117", "10.0.0.0/8"]
    monkeypatch.setenv("CLOUDMORROW_TRUSTED_PROXIES", "192.168.10.88")
    assert load_config(toml).trusted_proxies == ["192.168.10.88"]
