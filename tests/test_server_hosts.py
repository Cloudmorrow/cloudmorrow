"""A server answering on several addresses at once."""

from __future__ import annotations

from cloudmorrow.server.config import ServerConfig, load_config
from cloudmorrow.server.quills.services import loopback_url


def test_the_server_listens_on_each_address_it_is_given(tmp_path):
    assert ServerConfig(host="127.0.0.1, 10.0.0.2").hosts == ["127.0.0.1", "10.0.0.2"]
    # Every address already covers the rest.
    assert ServerConfig(host="10.0.0.2, 0.0.0.0").hosts == ["0.0.0.0"]
    toml = tmp_path / "server.toml"
    toml.write_text('[server]\nhost = ["127.0.0.1", "10.0.0.2"]\n')
    assert load_config(toml).hosts == ["127.0.0.1", "10.0.0.2"]


def test_a_quill_service_reaches_it_on_loopback_when_it_listens_there():
    assert loopback_url(ServerConfig(host="10.0.0.2, 127.0.0.1", port=9)) == "http://127.0.0.1:9"
    assert loopback_url(ServerConfig(host="10.0.0.2", port=9)) == "http://10.0.0.2:9"
    assert loopback_url(ServerConfig(host="0.0.0.0", port=9)) == "http://127.0.0.1:9"
