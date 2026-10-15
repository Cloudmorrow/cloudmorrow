from __future__ import annotations

import subprocess


def test_install_page_shows_the_command(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "curl -fsSL" in body
    assert "/install.sh | sh" in body


def test_install_page_offers_only_the_one_command(client):
    """Enrolling an agent is a CLI job; the page stays a single command."""
    body = client.get("/").text
    assert body.count("curl -fsSL") == 1
    assert "--agent-token" not in body


def test_install_script_is_valid_posix_shell(client, tmp_path):
    response = client.get("/install.sh")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/x-shellscript")
    script = tmp_path / "install.sh"
    script.write_text(response.text)
    # `sh -n` parses without running: the script must be syntactically sound
    # before anyone pipes it into a shell.
    subprocess.run(["sh", "-n", str(script)], check=True)


def test_install_script_carries_no_unreplaced_placeholders(client):
    assert "__" not in client.get("/install.sh").text.replace("__BASE", "")


def test_install_script_uses_the_public_url_when_configured(config, users):
    from fastapi.testclient import TestClient

    from cloudmorrow.server.app import create_app

    config.public_url = "https://cm.hl.bramlabs.io"
    with TestClient(create_app(config)) as client:
        assert "https://cm.hl.bramlabs.io/install.sh" in client.get("/install.sh").text
        assert 'PACKAGE="cloudmorrow[tui,agent]"' in client.get("/install.sh").text


# -- behind a proxy the server was not told about ------------------------------------
PROXIED = {"X-Forwarded-Proto": "https", "X-Forwarded-Host": "cm.example.net"}


def test_the_install_command_is_the_address_the_proxy_was_asked_for(client):
    """A proxy on another machine reaches us as http; the page still says https."""
    page = client.get("/install", headers=PROXIED).text
    assert "curl -fsSL https://cm.example.net/install.sh | sh" in page
    assert "http://testserver" not in page


def test_the_script_and_the_client_sign_in_where_the_person_did(client):
    script = client.get("/install.sh", headers=PROXIED).text
    assert 'CLOUDMORROW_URL="https://cm.example.net"' in script
    assert "http://testserver" not in script
    release = client.get("/api/client", headers=PROXIED).json()
    assert release["base_url"] == "https://cm.example.net"


def test_a_proxy_that_keeps_the_host_only_needs_to_say_https(client):
    script = client.get("/install.sh", headers={"X-Forwarded-Proto": "https"}).text
    assert 'CLOUDMORROW_URL="https://testserver"' in script


def test_the_rfc_7239_forwarded_header_counts_too(client):
    headers = {"Forwarded": 'for=203.0.113.9;proto=https;host="cm.example.net", for=10.0.0.2'}
    script = client.get("/install.sh", headers=headers).text
    assert 'CLOUDMORROW_URL="https://cm.example.net"' in script


def test_nonsense_in_the_forwarded_headers_is_ignored(client):
    """A host with a path or a userinfo, or a scheme that is neither, is not an address."""
    for host in ("evil.example/steal?x=", "user@cm.example.net", "cm.example.net/", " "):
        script = client.get("/install.sh", headers={"X-Forwarded-Host": host}).text
        assert 'CLOUDMORROW_URL="http://testserver"' in script, host
    script = client.get("/install.sh", headers={"X-Forwarded-Proto": "gopher"}).text
    assert 'CLOUDMORROW_URL="http://testserver"' in script


def test_without_a_proxy_the_request_itself_is_the_address(client):
    assert 'CLOUDMORROW_URL="http://testserver"' in client.get("/install.sh").text


def test_public_url_still_wins_over_what_a_proxy_says(config, users):
    from fastapi.testclient import TestClient

    from cloudmorrow.server.app import create_app

    config.public_url = "https://cm.hl.bramlabs.io"
    # An https public_url requires https, and a proxy nobody trusts gets a 426
    # for its trouble; that is the other half of the story, and not this test's.
    config.require_tls = False
    with TestClient(create_app(config)) as client:
        script = client.get("/install.sh", headers=PROXIED).text
        assert 'CLOUDMORROW_URL="https://cm.hl.bramlabs.io"' in script


def test_published_wheel_is_served_and_used(config, users):
    from fastapi.testclient import TestClient

    from cloudmorrow.server.app import create_app

    config.public_url = "https://cm.hl.bramlabs.io"
    config.dist_dir.mkdir(parents=True, exist_ok=True)
    wheel = config.dist_dir / "cloudmorrow-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"PK\x03\x04not-really-a-wheel")

    with TestClient(create_app(config)) as client:
        script = client.get("/install.sh").text
        assert "cloudmorrow[tui,agent] @ https://cm.hl.bramlabs.io/dist/cloudmorrow-0.1.0-py3-none-any.whl" in script
        served = client.get("/dist/cloudmorrow-0.1.0-py3-none-any.whl")
        assert served.status_code == 200
        assert served.content == b"PK\x03\x04not-really-a-wheel"


def test_dist_path_traversal_is_refused(client):
    assert client.get("/dist/..%2F..%2Fcloudmorrow.db").status_code in (400, 404)
    assert client.get("/dist/.secret").status_code == 400


def test_install_page_needs_no_auth(client):
    assert client.get("/install").status_code == 200
