"""`cloudmorrow-server access`, the installer's way to link the box and put it on its mesh."""

from __future__ import annotations

import json
import threading

import pytest
from typer.testing import CliRunner

from cloudmorrow.server import cli_access
from cloudmorrow.server.access_ways import Access
from tests.access_fakes import ZONE, wire


@pytest.fixture()
def wired(config, users, tmp_path, monkeypatch):
    access = Access(config, lambda: "The Larsens")
    fakes = wire(access, tmp_path)
    monkeypatch.setattr(cli_access, "_access", lambda path: access)
    return access, fakes


def run(*args: str):
    return CliRunner().invoke(cli_access.app, list(args))


def test_status_before_linking(wired) -> None:
    result = run("status")
    assert result.exit_code == 0, result.output
    assert "cloudmorrow-server access link" in result.output


def test_link_without_waiting_shows_the_code(wired) -> None:
    access, _ = wired
    result = run("link", "--no-wait")
    assert result.exit_code == 0, result.output
    code = access.pending().code
    assert f"Open cloudmorrow.test/link and enter {code}" in result.output
    assert f"https://cloudmorrow.test/link?code={code}" in result.output
    status = json.loads(run("status", "--json").output)
    assert status["link_state"] == "waiting"


def test_link_waits_for_the_code_and_sets_up(wired, monkeypatch) -> None:
    access, fakes = wired
    monkeypatch.setattr("cloudmorrow.server.access_ways.time.sleep", lambda s: None)
    polls = {"n": 0}
    real = access.poll_once

    def poll():
        # The person enters the code while the box waits.
        polls["n"] += 1
        if polls["n"] == 3:
            fakes.control.approve(None, "larsens")
        return real()

    monkeypatch.setattr(access, "poll_once", poll)
    result = run("link")
    assert result.exit_code == 0, result.output
    assert f"linked as larsens.{ZONE}, and on its mesh" in result.output
    status = json.loads(run("status", "--json").output)
    assert status["linked"] and status["mesh"]["on"] and status["mesh"]["address"] == "100.64.0.7"
    assert "linked" in run("status").output and f"larsens.{ZONE}" in run("status").output
    # Asked again: already linked, nothing new at the relay.
    before = len(fakes.control.calls)
    assert "already linked" in run("link").output
    assert len(fakes.control.calls) == before


def test_a_code_that_runs_out_fails_the_command(wired, monkeypatch) -> None:
    access, fakes = wired
    monkeypatch.setattr("cloudmorrow.server.access_ways.time.sleep", lambda s: None)
    real = access.poll_once

    def poll():
        fakes.control.refuse(None)
        return real()

    monkeypatch.setattr(access, "poll_once", poll)
    result = run("link")
    assert result.exit_code == 1
    assert "ran out" in result.output


def test_invite(wired) -> None:
    access, fakes = wired
    result = CliRunner().invoke(cli_access.app, ["invite"])
    assert result.exit_code == 1 and "link" in result.output.lower()
    fakes.control.approve(access.link()["code"], "larsens")
    access.poll_once()
    result = CliRunner().invoke(cli_access.app, ["invite"])
    assert result.exit_code == 0, result.output
    code = result.stdout.strip()
    assert len(code) == 6 and code.isalnum()
    assert f"curl -fsSL https://larsens.{ZONE}/install.sh | sh -s -- {code}" in result.stderr


def test_unlink_asks_unless_told(wired) -> None:
    access, fakes = wired
    fakes.control.approve(access.link()["code"], "larsens")
    access.poll_once()
    result = CliRunner().invoke(cli_access.app, ["unlink"], input="n\n")
    assert result.exit_code == 1 and access.cloud() is not None
    result = run("unlink", "--yes")
    assert result.exit_code == 0, result.output
    assert "unlinked" in result.output and access.cloud() is None


def test_unlink_while_waiting_lets_the_code_go(wired) -> None:
    access, _ = wired
    access.link()
    result = run("unlink")
    assert result.exit_code == 0 and "stopped waiting" in result.output
    assert access.pending() is None


def test_nothing_waits_forever_on_a_thread(wired) -> None:
    # The CLI polls in the foreground; it starts no thread of its own.
    before = threading.active_count()
    run("link", "--no-wait")
    assert threading.active_count() == before
