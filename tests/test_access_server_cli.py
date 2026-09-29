"""`cloudmorrow-server access`, the installer's way to claim a name and join the mesh."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from cloudmorrow.server import cli_access
from cloudmorrow.server.access_ways import Access
from tests.access_fakes import LOGIN_SERVER, ZONE, wire


@pytest.fixture()
def wired(config, users, tmp_path, monkeypatch):
    access = Access(config, lambda: "The Larsens")
    fakes = wire(access, tmp_path)
    monkeypatch.setattr(cli_access, "_access", lambda path: access)
    return access, fakes


def run(*args: str):
    return CliRunner().invoke(cli_access.app, list(args))


def test_status_before_a_name(wired) -> None:
    result = run("status")
    assert result.exit_code == 0, result.output
    assert "claim the-larsens" in result.output


def test_claim_public_and_private_then_status(wired) -> None:
    access, fakes = wired
    result = run("claim", "larsens", "--private")
    assert result.exit_code == 0, result.output
    assert f"larsens.{ZONE}" in result.output and "public, private" in result.output
    status = json.loads(run("status", "--json").output)
    assert status["public"]["on"] and status["private"]["on"]
    assert status["private"]["address"] == "100.64.0.7"


def test_mesh_key_prints_the_login_server_and_the_key_only(wired) -> None:
    access, fakes = wired
    assert run("mesh-key").exit_code == 1
    run("claim", "larsens", "--no-public")
    result = CliRunner().invoke(cli_access.app, ["mesh-key"])
    login, key = result.stdout.split()
    assert login == LOGIN_SERVER and key.startswith("hskey-")
    assert fakes.control.by_name("larsens").keys[-1]["for"] == "the box"


def test_switches_and_release(wired) -> None:
    access, fakes = wired
    run("claim", "larsens")
    assert run("public", "off").exit_code == 0
    assert access.cloud().public is False
    assert run("public", "maybe").exit_code != 0
    assert run("release", "--yes").exit_code == 0
    assert access.cloud() is None and fakes.control.clouds == {}


def test_a_taken_name_fails_with_the_sentence(wired) -> None:
    access, fakes = wired
    run("claim", "larsens")
    access.store.clear()
    result = run("claim", "larsens")
    assert result.exit_code == 1
    assert "larsens is taken" in result.output
