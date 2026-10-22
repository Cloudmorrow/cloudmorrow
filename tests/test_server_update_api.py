"""Deploying the server over the API, which is what `cloudmorrow update server` does.

The git and pip mechanics are test_update.py's job. What matters here is who
is allowed to ask, what the answer says, and — the part with teeth — that the
server only stops itself when something will start it again.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cloudmorrow.server.app import create_app
from cloudmorrow.server.update import Release, ReleasesAhead, UpdateError, UpdateResult, validate_branch
from tests.conftest import GUEST, token_for

DEPLOYED = UpdateResult(
    source=Path("/opt/cloudmorrow/src"),
    branch="main",
    old_commit="a" * 40,
    new_commit="b" * 40,
    changed_files=3,
    reinstalled=True,
    restarted=False,
)

NOTHING_NEW = UpdateResult(
    source=Path("/opt/cloudmorrow/src"),
    branch="main",
    old_commit="a" * 40,
    new_commit="a" * 40,
    changed_files=0,
    reinstalled=False,
    restarted=False,
)


AHEAD = ReleasesAhead(
    running_version="0.43.0",
    running_commit="a" * 40,
    latest_version="0.45.0",
    latest_tag="v0.45.0",
    releases=(
        Release("v0.45.0", "0.45.0", "2026-10-22", "Every button is a pixel", ("Every button is a pixel",)),
        Release("v0.44.0", "0.44.0", "2026-10-22", "Timeline: the sheet", ("Timeline: the sheet", "Typing in a note")),
    ),
)


@pytest.fixture()
def deploy(monkeypatch):
    """Stand in for the git pull, the pip install and the wheel build.

    Records what the route asked for, and what it did afterwards.
    """
    import cloudmorrow.server.routes.server as route

    calls: dict = {"update": None, "wheel": 0, "restarted": 0, "blocker": ""}

    def fake_update(**kwargs):
        calls["update"] = kwargs
        result = calls.get("result", DEPLOYED)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(route, "update", fake_update)

    def fake_releases_ahead(**kwargs):
        calls["looked"] = calls.get("looked", 0) + 1
        ahead = calls.get("ahead", AHEAD)
        if isinstance(ahead, Exception):
            raise ahead
        return ahead

    monkeypatch.setattr(route, "releases_ahead", fake_releases_ahead)
    monkeypatch.setattr(route, "build_wheel", lambda *a, **k: Path("cloudmorrow-0.1.0.whl"))
    monkeypatch.setattr(route, "describe", lambda source, commit: "bbbbbbb a real commit")
    monkeypatch.setattr(route, "self_restart_blocker", lambda service: calls["blocker"])
    monkeypatch.setattr(route, "self_restart", lambda: calls.__setitem__("restarted", calls["restarted"] + 1))
    return calls


def test_a_deploy_pulls_publishes_and_restarts(client, auth, deploy):
    response = client.post("/api/server/update", json={}, headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["changed"] is True
    assert body["old_commit"] == "a" * 40
    assert body["new_commit"] == "b" * 40
    assert body["changed_files"] == 3
    assert body["reinstalled"] is True
    assert body["published_wheel"] == "cloudmorrow-0.1.0.whl"
    # The wheel is how every other machine follows this deploy.
    assert body["restarting"] is True
    assert deploy["restarted"] == 1
    # The route never asks update() to restart: it has no privilege to.
    assert deploy["update"]["restart"] is False


def test_nothing_new_changes_nothing_and_restarts_nothing(client, auth, deploy):
    deploy["result"] = NOTHING_NEW
    body = client.post("/api/server/update", json={}, headers=auth).json()

    assert body["changed"] is False
    assert body["restarting"] is False
    assert body["published_wheel"] == ""
    assert deploy["restarted"] == 0


def test_the_server_refuses_to_stop_when_nothing_would_start_it(client, auth, deploy):
    """The failure that would take the box offline until someone walks to it."""
    deploy["blocker"] = "cloudmorrow.service has Restart=on-failure"

    body = client.post("/api/server/update", json={}, headers=auth).json()

    assert body["restarting"] is False
    assert "Restart=on-failure" in body["restart_blocked"]
    assert deploy["restarted"] == 0
    # The code is still deployed — it is only the restart that did not happen.
    assert body["changed"] is True


def test_no_restart_leaves_the_old_code_serving(client, auth, deploy):
    body = client.post("/api/server/update", json={"restart": False}, headers=auth).json()
    assert body["changed"] is True
    assert body["restarting"] is False
    assert deploy["restarted"] == 0


def test_an_update_error_is_a_conflict_not_a_crash(client, auth, deploy):
    deploy["result"] = UpdateError("the checkout has uncommitted changes")
    response = client.post("/api/server/update", json={}, headers=auth)
    assert response.status_code == 409
    assert "uncommitted changes" in response.json()["detail"]
    assert deploy["restarted"] == 0


def test_only_an_admin_may_deploy(client, deploy):
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    response = client.post("/api/server/update", json={}, headers=guest)
    assert response.status_code == 403
    assert deploy["update"] is None


def test_a_stranger_may_not_deploy(client, deploy):
    assert client.post("/api/server/update", json={}).status_code == 401
    assert deploy["update"] is None


def test_a_server_can_refuse_api_deploys_entirely(config, users, deploy):
    """allow_api_update = false puts it back to ssh-only."""
    config.allow_api_update = False
    with TestClient(create_app(config)) as offline:
        auth = {"Authorization": f"Bearer {token_for(offline, 'bram', 'supersecret1')}"}
        response = offline.post("/api/server/update", json={}, headers=auth)
    assert response.status_code == 403
    assert "allow_api_update" in response.json()["detail"]
    assert deploy["update"] is None


def test_the_branch_is_a_branch_and_not_a_git_flag(client, auth, deploy):
    response = client.post("/api/server/update", json={"branch": "--upload-pack=touch /tmp/pwned"}, headers=auth)
    assert response.status_code == 409
    assert deploy["update"] is None


@pytest.mark.parametrize("branch", ["--upload-pack=x", "-x", "", "   ", "a/../../etc", "x" * 200])
def test_branch_names_that_are_refused(branch):
    with pytest.raises(UpdateError):
        validate_branch(branch)


@pytest.mark.parametrize("branch", ["main", "release/1.2", "feature/thing-2", "v1.0.0"])
def test_branch_names_that_are_fine(branch):
    assert validate_branch(branch) == branch


def test_health_says_which_commit_is_running(client):
    """The only honest answer to "did my deploy land": the version never moves."""
    body = client.get("/api/health").json()
    assert "commit" in body


def test_a_deploy_says_which_commands_it_could_not_put_on_the_path(client, auth, deploy):
    """`cm` reaches the venv as the service user; /usr/local/bin is root's, and the answer says so."""
    from dataclasses import replace

    deploy["result"] = replace(DEPLOYED, unlinked=["cm"])
    body = client.post("/api/server/update", json={}, headers=auth).json()
    assert body["commands_unlinked"] == ["cm"]
    deploy["result"] = DEPLOYED
    assert client.post("/api/server/update", json={}, headers=auth).json()["commands_unlinked"] == []


# -- a newer version ----------------------------------------------------------------
def test_the_server_says_which_releases_are_out_past_the_one_it_runs(client, auth, deploy):
    body = client.get("/api/server/updates", headers=auth).json()
    assert body["available"] is True
    assert (body["running_version"], body["latest_version"]) == ("0.43.0", "0.45.0")
    assert [r["version"] for r in body["releases"]] == ["0.45.0", "0.44.0"]
    assert body["releases"][1]["changes"] == ["Timeline: the sheet", "Typing in a note"]
    assert body["releases"][0]["notes"] == "Every button is a pixel"
    assert body["checked_at"] and body["error"] == ""


def test_the_look_is_kept_for_a_while_and_refreshed_on_request(client, auth, deploy):
    client.get("/api/server/updates", headers=auth)
    client.get("/api/server/updates", headers=auth)
    assert deploy["looked"] == 1
    client.get("/api/server/updates?refresh=1", headers=auth)
    assert deploy["looked"] == 2
    # A deploy makes whatever was known stale.
    client.post("/api/server/update", json={}, headers=auth)
    client.get("/api/server/updates", headers=auth)
    assert deploy["looked"] == 3


def test_a_server_that_cannot_look_says_so_instead_of_failing(client, auth, deploy):
    deploy["ahead"] = UpdateError("no checkout here")
    body = client.get("/api/server/updates", headers=auth).json()
    assert body["available"] is False and body["releases"] == []
    assert body["error"] == "no checkout here"


def test_only_an_administrator_asks_about_releases(client, deploy):
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    assert client.get("/api/server/updates", headers=guest).status_code == 403
