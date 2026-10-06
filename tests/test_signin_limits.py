"""A brake on guessing passwords (server/signin_limits.py)."""

from __future__ import annotations

from cloudmorrow.server.app import create_app
from cloudmorrow.server.signin_limits import SigninLimits
from tests.conftest import ADMIN, GUEST


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
