"""Agent enrolment and the job queue, including a real runner pass."""

from __future__ import annotations

import pytest

from cloudmorrow.agent.client import AgentClient
from cloudmorrow.agent.config import AgentConfig
from cloudmorrow.agent.runner import AgentRunner
from tests.conftest import GUEST, token_for


def enroll_agent(client, auth, name="testbox") -> dict:
    token = client.post(
        "/api/agents/enroll-token", json={"label": name}, headers=auth
    ).json()["enrollment_token"]
    response = client.post(
        "/api/agent/enroll",
        json={
            "enrollment_token": token,
            "name": name,
            "hostname": "testbox.local",
            "platform": "Linux-test",
            "version": "0.1.0",
            "capabilities": ["ping", "sysinfo", "backup"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def agent_headers(enrolled: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {enrolled['agent_token']}"}


def runner_for(test_client, enrolled: dict, tmp_path) -> AgentRunner:
    """An AgentRunner whose HTTP client is the FastAPI test client."""
    config = AgentConfig(
        server_url="",
        agent_token=enrolled["agent_token"],
        name=enrolled["name"],
        backup_roots=[str(tmp_path)],
        backup_dir=str(tmp_path / "backups"),
    )
    api = AgentClient(config)
    api._client.close()
    api._client = test_client
    return AgentRunner(config, api)


def test_enrollment_token_is_single_use(client, auth):
    token = client.post("/api/agents/enroll-token", json={}, headers=auth).json()[
        "enrollment_token"
    ]
    body = {"enrollment_token": token, "name": "box-a"}
    assert client.post("/api/agent/enroll", json=body).status_code == 200
    again = client.post("/api/agent/enroll", json={**body, "name": "box-b"})
    assert again.status_code == 403
    assert "already been used" in again.json()["detail"]


def test_enrollment_rejects_an_unknown_token(client):
    response = client.post(
        "/api/agent/enroll", json={"enrollment_token": "bce_nope", "name": "box"}
    )
    assert response.status_code == 403


def test_enrolled_agent_is_listed(client, auth):
    enrolled = enroll_agent(client, auth)
    agents = client.get("/api/agents", headers=auth).json()
    assert [a["name"] for a in agents] == ["testbox"]
    assert agents[0]["id"] == enrolled["agent_id"]
    assert agents[0]["online"] is False  # no heartbeat yet


def test_heartbeat_marks_the_agent_online(client, auth):
    enrolled = enroll_agent(client, auth)
    beat = client.post(
        "/api/agent/heartbeat",
        json={"hostname": "testbox.local", "platform": "Linux"},
        headers=agent_headers(enrolled),
    )
    assert beat.json()["queued_jobs"] == 0
    assert client.get("/api/agents", headers=auth).json()[0]["online"] is True


def test_agent_token_cannot_read_notes(client, auth):
    enrolled = enroll_agent(client, auth)
    assert client.get("/api/notes/tree", headers=agent_headers(enrolled)).status_code == 401


def test_user_token_cannot_claim_jobs(client, auth):
    enroll_agent(client, auth)
    assert client.post("/api/agent/jobs/claim", headers=auth).status_code == 401


def test_agents_are_per_user(client, auth):
    enroll_agent(client, auth)
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    assert client.get("/api/agents", headers=guest).json() == []


def test_unknown_job_type_is_refused(client, auth):
    enrolled = enroll_agent(client, auth)
    response = client.post(
        f"/api/agents/{enrolled['agent_id']}/jobs",
        json={"type": "rm-rf", "payload": {}},
        headers=auth,
    )
    assert response.status_code == 400


def test_job_round_trip_through_the_runner(client, auth, tmp_path):
    enrolled = enroll_agent(client, auth)
    queued = client.post(
        f"/api/agents/{enrolled['agent_id']}/jobs",
        json={"type": "ping", "payload": {"echo": "hello"}},
        headers=auth,
    ).json()
    assert queued["status"] == "queued"

    runner = runner_for(client, enrolled, tmp_path)
    runner.tick()

    jobs = client.get(f"/api/agents/{enrolled['agent_id']}/jobs", headers=auth).json()
    assert len(jobs) == 1
    assert jobs[0]["status"] == "done"
    assert jobs[0]["result"]["echo"] == "hello"
    assert runner.stats.jobs_done == 1


def test_backup_job_round_trip(client, auth, tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.md").write_text("back me up")
    enrolled = enroll_agent(client, auth)
    client.post(
        f"/api/agents/{enrolled['agent_id']}/jobs",
        json={"type": "backup", "payload": {"paths": [str(tmp_path / "docs")], "name": "docs"}},
        headers=auth,
    )

    runner = runner_for(client, enrolled, tmp_path)
    runner.tick()

    job = client.get(f"/api/agents/{enrolled['agent_id']}/jobs", headers=auth).json()[0]
    assert job["status"] == "done", job
    assert job["result"]["files"] == 1
    assert (tmp_path / "backups").is_dir()


def test_refused_job_comes_back_as_failed(client, auth, tmp_path):
    enrolled = enroll_agent(client, auth)
    client.post(
        f"/api/agents/{enrolled['agent_id']}/jobs",
        json={"type": "shell", "payload": {"command": "echo nope"}},
        headers=auth,
    )
    runner = runner_for(client, enrolled, tmp_path)  # allow_shell defaults to False
    runner.tick()

    job = client.get(f"/api/agents/{enrolled['agent_id']}/jobs", headers=auth).json()[0]
    assert job["status"] == "failed"
    assert "disabled" in job["result"]["error"]
    assert runner.stats.jobs_failed == 1


def test_jobs_are_listed_for_the_machine(client, auth):
    enrolled = enroll_agent(client, auth)
    for _ in range(2):
        client.post(f"/api/agents/{enrolled['agent_id']}/jobs", json={"type": "ping"}, headers=auth)
    listed = client.get(f"/api/agents/{enrolled['agent_id']}/jobs", headers=auth).json()
    assert len(listed) == 2
    assert {job["type"] for job in listed} == {"ping"}
    assert "project" not in listed[0]


def test_agent_can_be_removed(client, auth):
    enrolled = enroll_agent(client, auth)
    assert client.delete(f"/api/agents/{enrolled['agent_id']}", headers=auth).status_code == 204
    assert client.get("/api/agents", headers=auth).json() == []
    # Its token stops working immediately.
    assert client.post("/api/agent/jobs/claim", headers=agent_headers(enrolled)).status_code == 401


def test_duplicate_agent_name_is_refused(client, auth):
    enroll_agent(client, auth, name="dup")
    token = client.post("/api/agents/enroll-token", json={}, headers=auth).json()[
        "enrollment_token"
    ]
    response = client.post(
        "/api/agent/enroll", json={"enrollment_token": token, "name": "dup"}
    )
    assert response.status_code == 409


@pytest.mark.parametrize("name", ["", "has space", "-", "a" * 65])
def test_invalid_agent_names(client, auth, name):
    token = client.post("/api/agents/enroll-token", json={}, headers=auth).json()[
        "enrollment_token"
    ]
    response = client.post(
        "/api/agent/enroll", json={"enrollment_token": token, "name": name}
    )
    assert response.status_code == 400
