"""The agent mounts again the shares this machine had mounted."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudmorrow.agent import remounts
from cloudmorrow.client import mounts
from cloudmorrow.client.config import StoredCredentials


@pytest.fixture()
def calls(monkeypatch):
    seen: list[tuple[str, str, set]] = []
    outcomes: dict = {}

    def restore(username, secret, *, skip=frozenset()):
        seen.append((username, secret, set(skip)))
        return {name: value for name, value in outcomes.items() if name not in skip}

    monkeypatch.setattr(remounts.mounts, "restore", restore)
    mounts.remember(mounts.Mount("media", Path("/nowhere/media"), "https://x/dav/media/", "rclone"))
    return seen, outcomes


def _sign_in(expires_at: str = "") -> None:
    StoredCredentials("https://x", "bram", "the-token", expires_at).save()


def test_nothing_is_tried_signed_out(calls):
    seen, _ = calls
    assert remounts.Remounts().tick() == []
    assert seen == []


def test_nothing_is_tried_with_a_token_that_ran_out(calls):
    seen, _ = calls
    _sign_in("2000-01-01T00:00:00+00:00")
    remounts.Remounts().tick()
    assert seen == []


def test_signed_in_the_shares_come_back_as_that_person(calls):
    seen, outcomes = calls
    _sign_in()
    outcomes["media"] = mounts.Mount("media", Path("/nowhere/media"), "https://x/dav/media/", "rclone")
    assert remounts.Remounts().tick() == ["media"]
    assert seen == [("bram", "the-token", set())]


def test_a_share_that_failed_waits_before_the_next_try(calls):
    seen, outcomes = calls
    _sign_in()
    outcomes["media"] = mounts.MountError("no such host")
    now = [1000.0]
    remounting = remounts.Remounts(clock=lambda: now[0])
    remounting.tick()
    now[0] += 30
    remounting.tick()
    assert seen[-1][2] == {"media"}
    now[0] += remounts.RETRY_SECONDS
    remounting.tick()
    assert seen[-1][2] == set()


def test_nothing_written_down_means_nothing_read(monkeypatch):
    monkeypatch.setattr(StoredCredentials, "load", lambda: pytest.fail("credentials read"))
    assert remounts.Remounts().tick() == []
