"""Linking a box to a cloudmorrow.com account, and what follows it, against a fake relay.

Pending → entered on the website → linked → on the mesh with Caddy holding
the name; a code that runs out or is refused; a server restarted halfway;
a rename and an unlink done on the website; and the rule the rest keeps
to: nothing about a person is ever sent to the relay.
"""

from __future__ import annotations

import datetime as dt
import sqlite3

import pytest

from cloudmorrow.server.access_control import AccessStore, valid_name
from cloudmorrow.server.access_ways import Access, AccessError
from tests.access_fakes import LINK_PAGE, LOGIN_SERVER, ZONE, tailscale_calls, wire


@pytest.fixture()
def access(config, users):
    return Access(config, lambda: "The Larsens", addresses=lambda: ["192.168.1.20"])


@pytest.fixture()
def fakes(access, tmp_path):
    return wire(access, tmp_path)


def test_names_are_five_to_forty():
    assert valid_name("larsens") and valid_name("a1b2c") and valid_name("x" * 40)
    for bad in ("abcd", "x" * 41, "-abcde", "abcde-", "Larsens", "lar sens", "lars.ens", "lar--sens", ""):
        assert not valid_name(bad), bad


def test_a_link_code_is_shown_and_kept(access, fakes):
    shown = access.link()
    assert shown["url"] == LINK_PAGE and shown["place"] == "cloudmorrow.test/link"
    assert shown["link"] == f"{LINK_PAGE}?code={shown['code']}"
    assert "poll" not in shown
    # Asked again, the same code: a person may be typing it.
    assert access.link()["code"] == shown["code"]
    assert [c[:2] for c in fakes.control.calls] == [("POST", "/v1/links")]
    # POST /v1/links goes with no token and nothing in the body.
    assert fakes.control.calls[0][2] == {}
    status = access.status(admin=True)
    assert status["link_state"] == "waiting" and status["link"]["code"] == shown["code"]
    assert status["linked"] is False
    # The poll secret is sealed at rest.
    raw = sqlite3.connect(access.config.db_path).execute("SELECT poll FROM access_link").fetchone()[0]
    assert raw.startswith("s1:") and "poll_" not in raw


def test_waiting_then_linked_then_set_up(access, fakes, config):
    shown = access.link()
    assert access.poll_once() == "waiting"
    assert config.public_url == ""
    fakes.control.approve(shown["code"], "larsens")
    assert access.poll_once() == "linked"

    cloud = access.cloud()
    assert cloud is not None and cloud.host == f"larsens.{ZONE}" and cloud.set_up
    assert cloud.login_server == LOGIN_SERVER and cloud.mesh_address == "100.64.0.7"
    assert access.pending() is None
    # The box joined as `cloud`, with a key it asked for with no label.
    up = next(line for line in tailscale_calls(fakes.tailscale_dir) if line.startswith("up "))
    assert f"--login-server {LOGIN_SERVER}" in up and "--hostname cloud" in up and "--authkey hskey-" in up
    # The box keeps its own resolver: the mesh's names are for its devices.
    assert "--accept-dns=false" in up
    key_calls = [c for c in fakes.control.calls if c[1] == "/v1/clouds/me/mesh/keys"]
    assert key_calls and set(key_calls[0][2]) <= {"ephemeral", "expires_in"}
    # Caddy's site is the name, by the DNS challenge with the link's acme-dns account.
    site = (config.access_caddy_dir / "cloudmorrow.caddy").read_text()
    assert f"larsens.{ZONE} {{" in site and "dns acmedns" in site
    assert '"p-acme-secret"' in site and "reverse_proxy 127.0.0.1:8787" in site
    assert fakes.caddy_loads
    # public_url, and with it require_tls, follow the name.
    assert config.public_url == f"https://larsens.{ZONE}" and config.tls_required
    # The token and the acme account are sealed at rest.
    row = sqlite3.connect(config.db_path).execute("SELECT token, acme FROM access_cloud").fetchone()
    assert all(value.startswith("s1:") for value in row)
    assert fakes.control.only().token not in row[0]


def test_the_announcement_says_the_mesh_name_once_linked(access, fakes):
    before = access.announcement()
    assert before.properties() == {
        "name": "The Larsens",
        "version": before.version,
        "url": "http://the-larsens.local:8787",
    }
    fakes.control.approve(access.link()["code"], "larsens")
    access.poll_once()
    after = access.announcement()
    assert after.port == 443 and after.label == "larsens"
    assert after.properties() == {
        "name": "The Larsens",
        "version": after.version,
        "url": f"https://larsens.{ZONE}",
        "mesh": f"larsens.{ZONE}",
    }


def test_a_refused_code_and_an_expired_one(access, fakes):
    fakes.control.refuse(access.link()["code"])
    assert access.poll_once() == "expired"
    assert access.pending() is None and access.cloud() is None
    assert access.status(admin=True)["link_state"] == "expired"
    # A new code is a new one.
    second = access.link()
    fakes.control.links[second["code"]].expires_at = "2020-01-01T00:00:00+00:00"
    assert access.poll_once() == "expired"
    assert access.status(admin=True)["link_state"] == "expired"


def test_an_expired_code_is_not_offered_again(access, fakes):
    first = access.link()
    store = AccessStore(access.config.db_path)
    pending = store.pending()
    pending.expires_at = (dt.datetime.now(tz=dt.UTC) - dt.timedelta(minutes=1)).isoformat()
    store.save_pending(pending)
    assert access.link()["code"] != first["code"]


def test_a_relay_that_cannot_be_reached_keeps_waiting(access, fakes, monkeypatch):
    access.link()
    import httpx

    def down(*args, **kwargs):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(access.http, "request", down)
    assert access.poll_once() == "waiting"
    assert "cannot reach" in access.link_error
    assert access.pending() is not None


def test_a_restart_while_the_code_waits_picks_it_up(config, users, tmp_path):
    first = Access(config, lambda: "The Larsens")
    fakes = wire(first, tmp_path)
    shown = first.link()
    fakes.control.approve(shown["code"], "larsens")

    # The server stops before it polled again; a new one starts.
    second = Access(config, lambda: "The Larsens")
    second.http, second.mesh, second.caddy = first.http, first.mesh, first.caddy
    second.refresh_seconds = 3600
    second.start()
    try:
        import time

        for _ in range(100):
            cloud = second.cloud()
            if cloud is not None and cloud.set_up:
                break
            time.sleep(0.05)
        assert cloud is not None and cloud.set_up and cloud.name == "larsens"
    finally:
        second.stop()


def test_linked_but_not_set_up_is_finished_at_the_next_start(config, users, tmp_path, monkeypatch):
    first = Access(config, lambda: "The Larsens")
    fakes = wire(first, tmp_path)
    # No tailscale yet: linked, but not on the mesh.
    real_status = first.mesh.status
    from cloudmorrow.server.access_mesh import MeshStatus

    monkeypatch.setattr(first.mesh, "status", lambda: MeshStatus(installed=False))
    fakes.control.approve(first.link()["code"], "larsens")
    assert first.poll_once() == "linked"
    cloud = first.cloud()
    assert cloud is not None and not cloud.set_up
    assert "tailscale is not installed" in first.setup_error
    assert config.public_url == ""
    with pytest.raises(AccessError):
        first.invite()

    # Tailscale arrives; the server restarts and reads its record, which finishes the job.
    monkeypatch.setattr(first.mesh, "status", real_status)
    second = Access(config, lambda: "The Larsens")
    second.http, second.mesh, second.caddy = first.http, first.mesh, first.caddy
    assert second.refresh() is not None
    assert second.cloud().set_up
    assert config.public_url == f"https://larsens.{ZONE}"


def test_a_rename_on_the_website_moves_caddy_and_the_address(access, fakes, config):
    fakes.control.approve(access.link()["code"], "larsens")
    access.poll_once()
    fakes.control.rename("larsen-family")
    access.refresh()
    assert access.cloud().host == f"larsen-family.{ZONE}"
    site = (config.access_caddy_dir / "cloudmorrow.caddy").read_text()
    assert f"larsen-family.{ZONE} {{" in site and f"larsens.{ZONE}" not in site
    assert config.public_url == f"https://larsen-family.{ZONE}"


def test_a_name_the_core_cannot_use_is_not_written_into_caddy(access, fakes, config):
    fakes.control.approve(access.link()["code"], "larsens")
    access.poll_once()
    fakes.control.rename('evil" {\n}')
    access.refresh()
    assert access.cloud().name == "larsens"
    assert "evil" not in (config.access_caddy_dir / "cloudmorrow.caddy").read_text()


def test_unlinking_from_the_box(access, fakes, config):
    fakes.control.approve(access.link()["code"], "larsens")
    access.poll_once()
    access.unlink()
    assert fakes.control.clouds == {}
    assert ("DELETE", "/v1/clouds/me", {}) in fakes.control.calls
    assert access.cloud() is None
    assert tailscale_calls(fakes.tailscale_dir)[-1] == "down"
    assert not (config.access_caddy_dir / "cloudmorrow.caddy").exists()
    assert config.public_url == ""
    assert access.announcement().port == 8787
    with pytest.raises(AccessError):
        access.unlink()


def test_unlinked_on_the_website_goes_home_at_the_next_look(access, fakes, config):
    fakes.control.approve(access.link()["code"], "larsens")
    access.poll_once()
    fakes.control.unlink_from_website()
    assert access.refresh() is None
    assert access.cloud() is None and config.public_url == ""
    assert tailscale_calls(fakes.tailscale_dir)[-1] == "down"


def test_linking_twice_is_refused(access, fakes):
    fakes.control.approve(access.link()["code"], "larsens")
    access.poll_once()
    with pytest.raises(AccessError) as caught:
        access.link()
    assert caught.value.status_code == 409 and f"larsens.{ZONE}" in str(caught.value)


def test_devices_are_labelled_on_the_box_and_nothing_personal_goes_to_the_relay(access, fakes):
    fakes.control.approve(access.link()["code"], "larsens")
    access.poll_once()
    fakes.control.only().mesh_address = "100.64.0.7"
    # A computer: a key, a join, and the box told whose it is.
    key = access.mesh_key()
    assert key["hostname"].startswith("cm-") and len(key["hostname"]) == 9
    fakes.control.join(key["key"], "100.64.0.9")
    labelled = access.claim_device("bram", "100.64.0.9", "laptop")
    assert labelled["label"] == "bram: laptop" and labelled["owner"] == "bram"
    # A phone joined with an invite: nobody's, until an administrator says.
    invite = access.invite()
    assert len(invite["code"]) == 6 and invite["command"] == f"curl -fsSL https://larsens.{ZONE}/install.sh | sh"
    phone = fakes.control.join(_mint(fakes), "100.64.0.10")
    everyone = {d["address"]: d for d in access.devices(None)}
    assert everyone["100.64.0.10"]["label"] == "" and everyone["100.64.0.10"]["owner"] == ""
    access.label_device(phone["id"], "guest", "Anna's phone")
    assert [d["label"] for d in access.devices("guest")] == ["guest: Anna's phone"]
    assert [d["address"] for d in access.devices("bram")] == ["100.64.0.9"]
    # Somebody else's device is not yours to take or remove.
    with pytest.raises(AccessError):
        access.claim_device("bram", "100.64.0.10", "mine now")
    with pytest.raises(AccessError):
        access.remove_device(phone["id"], "bram")
    access.remove_device(phone["id"], "guest")
    assert "100.64.0.10" not in {d["address"] for d in access.devices(None)}

    sent = fakes.control.bodies()
    for personal in ("bram", "guest", "laptop", "Anna", "The Larsens", '"for"', '"owner"', '"label"'):
        assert personal not in sent, personal


def _mint(fakes) -> str:
    """A key as the relay would mint it for a redeemed invite."""
    import secrets

    key = "hskey-" + secrets.token_hex(12)
    fakes.control.only().keys.append(key)
    return key
