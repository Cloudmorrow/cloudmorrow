"""Signing in to a linked cloud puts the computer on its mesh, and never gets in the way."""

from __future__ import annotations

import asyncio
import json
import subprocess

import pytest

from cloudmorrow.client import autojoin, meshjoin
from cloudmorrow.client.config import ClientConfig

LOGIN = "https://mesh.cloudmorrow.test"


class FakeApi:
    def __init__(self, mesh_on: bool = True) -> None:
        self.mesh_on = mesh_on
        self.claimed: list[tuple[str, str]] = []
        self.keys = 0

    async def access(self) -> dict:
        return {"host": "larsens.cloudmorrow.test", "mesh": {"on": self.mesh_on, "login_server": LOGIN}}

    async def mesh_key(self) -> dict:
        self.keys += 1
        return {"key": "hskey-1", "login_server": LOGIN, "hostname": "cm-abc123"}

    async def claim_mesh_device(self, address: str, device: str) -> dict:
        self.claimed.append((address, device))
        return {}


class FakeTailscale:
    """`tailscale status`, `debug prefs` and `up`, as a runner meshjoin takes."""

    def __init__(self, running_on: str = "") -> None:
        self.running_on = running_on
        self.commands: list[list[str]] = []

    def __call__(self, cmd) -> subprocess.CompletedProcess:
        cmd = list(cmd)
        self.commands.append(cmd)
        if "status" in cmd:
            state = "Running" if self.running_on else "NeedsLogin"
            ips = ["100.64.0.9"] if self.running_on else []
            out = json.dumps({"BackendState": state, "Self": {"TailscaleIPs": ips}})
        elif "prefs" in cmd:
            out = json.dumps({"ControlURL": self.running_on})
        elif "up" in cmd:
            self.running_on = LOGIN
            out = ""
        else:
            out = ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")


@pytest.fixture()
def installed(monkeypatch):
    monkeypatch.setattr(meshjoin, "tailscale_binary", lambda: "/usr/bin/tailscale")


def join(api, config, runner, ask=lambda: True):
    return asyncio.run(autojoin.join_after_signin(api, config, ask_install=ask, run=runner, device="laptop"))


def test_it_joins_and_says_whose_it_is(installed) -> None:
    api, runner = FakeApi(), FakeTailscale()
    joined = join(api, ClientConfig(), runner)
    assert joined.outcome == "joined" and joined.address == "100.64.0.9"
    assert any("up" in c and "--login-server" in c and LOGIN in c for c in runner.commands)
    assert api.claimed == [("100.64.0.9", "laptop")]


def test_on_the_mesh_already_it_only_says_whose(installed) -> None:
    api, runner = FakeApi(), FakeTailscale(running_on=LOGIN)
    assert asyncio.run(autojoin.wanted(api, ClientConfig(), run=runner)) is False
    joined = join(api, ClientConfig(), runner)
    assert joined.outcome == "already" and api.keys == 0
    assert not any("up" in c for c in runner.commands)


def test_nothing_to_join_is_nothing_done(installed) -> None:
    runner = FakeTailscale()
    assert join(FakeApi(mesh_on=False), ClientConfig(), runner).outcome == ""
    config = ClientConfig()
    config.mesh = False
    assert join(FakeApi(), config, runner).outcome == ""
    assert runner.commands == []


def test_saying_no_to_tailscale_is_remembered(monkeypatch) -> None:
    monkeypatch.setattr(meshjoin, "tailscale_binary", lambda: None)
    monkeypatch.setattr(meshjoin, "install_command", lambda: ["sh", "-c", "true"])
    config = ClientConfig()
    joined = join(FakeApi(), config, FakeTailscale(), ask=lambda: False)
    assert joined.outcome == "declined" and "relay" in joined.sentence()
    assert ClientConfig.load().mesh is False


def test_a_failure_is_a_sentence_and_not_a_crash(installed) -> None:
    def broken(cmd):
        if "up" in list(cmd):
            return subprocess.CompletedProcess(list(cmd), 1, stdout="", stderr="sudo: a password is required")
        return FakeTailscale()(cmd)

    joined = join(FakeApi(), ClientConfig(), broken)
    assert joined.outcome == "failed" and "password is required" in joined.sentence()
