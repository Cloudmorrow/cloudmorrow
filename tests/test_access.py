"""The allowed_client_ips gate."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cloudmorrow.server.access import InvalidClientRule, is_allowed, parse_rules
from cloudmorrow.server.app import create_app


def app_for(config, rules: list[str], client_ip: str) -> TestClient:
    config.allowed_client_ips = rules
    return TestClient(create_app(config), client=(client_ip, 51234))


def test_no_rules_allows_everyone():
    assert is_allowed("203.0.113.7", parse_rules([]))


def test_single_address():
    rules = parse_rules(["192.168.10.88"])
    assert is_allowed("192.168.10.88", rules)
    assert not is_allowed("192.168.10.89", rules)


def test_cidr_range():
    rules = parse_rules(["192.168.10.0/24", "10.0.0.5"])
    assert is_allowed("192.168.10.200", rules)
    assert is_allowed("10.0.0.5", rules)
    assert not is_allowed("192.168.11.1", rules)


def test_ipv6():
    rules = parse_rules(["fd00::/8"])
    assert is_allowed("fd00::1", rules)
    assert not is_allowed("2001:db8::1", rules)


def test_unparseable_client_is_refused():
    rules = parse_rules(["192.168.10.88"])
    assert not is_allowed("not-an-ip", rules)
    assert not is_allowed(None, rules)


def test_blank_entries_are_ignored():
    assert parse_rules(["", "  "]) == []


def test_bad_rule_is_reported():
    with pytest.raises(InvalidClientRule):
        parse_rules(["192.168.10.999"])


def test_the_proxy_gets_through(config, users):
    with app_for(config, ["192.168.10.88"], "192.168.10.88") as client:
        assert client.get("/api/health").status_code == 200


def test_everyone_else_is_refused(config, users):
    with app_for(config, ["192.168.10.88"], "192.168.10.99") as client:
        assert client.get("/api/health").status_code == 403
        # Including the endpoints that need no auth.
        assert client.get("/").status_code == 403
        assert client.get("/install.sh").status_code == 403
        assert (
            client.post(
                "/api/auth/login", json={"username": "bram", "password": "supersecret1"}
            ).status_code
            == 403
        )


def test_forwarded_headers_cannot_spoof_the_check(config, users):
    """X-Forwarded-For is set by the caller, so it must not be trusted."""
    with app_for(config, ["192.168.10.88"], "203.0.113.7") as client:
        response = client.get(
            "/api/health",
            headers={"X-Forwarded-For": "192.168.10.88", "X-Real-IP": "192.168.10.88"},
        )
        assert response.status_code == 403


def test_default_config_lets_everything_through(client):
    assert client.get("/api/health").status_code == 200
