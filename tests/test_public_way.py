"""From anywhere: the relay's visitors, the switch for them, and the brakes that come with them."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cloudmorrow.server.app import create_app
from cloudmorrow.server.signin_limits import SigninLimits
from tests.access_fakes import wire
from tests.conftest import ADMIN, GUEST, token_for

PUBLIC = {"Cloudmorrow-Way": "public"}


@pytest.fixture()
def wired(config, users, tmp_path):
    app = create_app(config)
    fakes = wire(app.state.cloudmorrow.access, tmp_path)
    client = TestClient(app)
    admin = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    return client, fakes, admin, app


def linked(client, fakes, admin):
    started = client.post("/api/access/link", headers=admin)
    fakes.control.approve(started.json()["link"]["code"], "larsens")
    assert client.app.state.cloudmorrow.access.poll_once() == "linked"


# -- the switch --------------------------------------------------------------------------
def test_a_linked_cloud_is_reachable_from_anywhere_until_turned_off(wired) -> None:
    client, fakes, admin, _ = wired
    linked(client, fakes, admin)
    status = client.get("/api/access", headers=admin).json()
    assert status["public"] == {"on": True, "live": True}
    assert ":8443 {" in _site(client)

    off = client.put("/api/access/public", json={"public": False}, headers=admin)
    assert off.status_code == 200 and off.json()["public"] == {"on": False, "live": False}
    assert ":8443" not in _site(client)
    assert fakes.control.only().public is False
    assert ("PATCH", "/v1/clouds/me", {"public": False}) in fakes.control.calls

    client.put("/api/access/public", json={"public": True}, headers=admin)
    assert ":8443 {" in _site(client) and fakes.control.only().public is True


def test_the_box_puts_the_relay_right_when_they_disagree(wired) -> None:
    client, fakes, admin, app = wired
    linked(client, fakes, admin)
    fakes.control.only().public = False  # the relay forgot, or was restored from a backup
    app.state.cloudmorrow.access.refresh()
    assert fakes.control.only().public is True


def test_only_an_administrator_flips_it(wired) -> None:
    client, _, _, _ = wired
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    assert client.put("/api/access/public", json={"public": False}, headers=guest).status_code == 403


def _site(client) -> str:
    config = client.app.state.cloudmorrow.config
    return (config.access_caddy_dir / "cloudmorrow.caddy").read_text(encoding="utf-8")


# -- what a visit from anywhere cannot do ---------------------------------------------------
def test_nobody_on_the_internet_sets_a_cloud_up(config) -> None:
    config.ensure_dirs()
    client = TestClient(create_app(config))
    page = client.get("/setup", headers=PUBLIC)
    assert page.status_code == 404 and "Not set up yet" in page.text
    assert client.get("/api/setup/quills", headers=PUBLIC).status_code == 404
    made = client.post(
        "/api/setup", headers=PUBLIC, json={"name": "Mine now", "username": "mallory", "password": "hunter22hunter"}
    )
    assert made.status_code == 404
    assert client.app.state.cloudmorrow.users.count() == 0
    # At home, the page is there.
    assert client.get("/setup").status_code == 200
    assert client.get("/setup", headers={"Cloudmorrow-Way": "home"}).status_code == 200


def test_the_name_opens_on_the_sign_in_from_anywhere(client) -> None:
    assert client.get("/", headers=PUBLIC, follow_redirects=False).headers["location"] == "/app"
    assert client.get("/", follow_redirects=False).status_code == 200


# -- guessing passwords ----------------------------------------------------------------------
class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_limits_per_address_and_per_account_with_a_sliding_window() -> None:
    clock = Clock()
    limits = SigninLimits(per_address=(3, 60), per_account=(5, 600), clock=clock)
    for _ in range(3):
        assert limits.retry_after("1.2.3.4", "anna") == 0
        limits.failed("1.2.3.4", "anna")
    assert limits.retry_after("1.2.3.4", "anna") == 60
    assert limits.retry_after("1.2.3.4", "bo") == 60  # the address is stopped, whoever it tries
    assert limits.retry_after("5.6.7.8", "anna") == 0  # the account is not, yet
    limits.failed("5.6.7.8", "Anna")
    limits.failed("9.9.9.9", "anna")
    assert limits.retry_after("10.0.0.1", "anna") == 600  # five for the account, from anywhere
    clock.now += 61
    assert limits.retry_after("1.2.3.4", "bo") == 0
    clock.now += 600
    assert limits.retry_after("10.0.0.1", "anna") == 0


def test_sign_in_says_429_after_ten_wrong_passwords_even_to_the_right_one(client) -> None:
    for _ in range(10):
        wrong = client.post("/api/auth/login", json={"username": ADMIN[0], "password": "not it"})
        assert wrong.status_code == 401
    stopped = client.post("/api/auth/login", json={"username": ADMIN[0], "password": ADMIN[1]})
    assert stopped.status_code == 429
    assert int(stopped.headers["Retry-After"]) > 0


def test_webdav_counts_wrong_passwords_against_the_account(config, users) -> None:
    app = create_app(config)
    check = app.state.cloudmorrow.credential_check
    limits = app.state.signin_limits
    limits.per_account = (2, 600)
    assert check(ADMIN[0], "nope") is False
    assert check(ADMIN[0], "nope again") is False
    assert check(ADMIN[0], ADMIN[1]) is False  # stopped, right password or not
    assert check(GUEST[0], GUEST[1]) is True
