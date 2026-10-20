"""Flows: when something happens, do these steps, as whoever made the flow (docs/FLOWS.md)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cloudmorrow.server import flows
from cloudmorrow.server.app import create_app
from cloudmorrow.server.security import hash_password
from tests.conftest import ADMIN, GUEST, token_for

LEAVE = Path(__file__).parent / "fixtures" / "quill-leave"
FLEET = Path(__file__).parent / "fixtures" / "quill-fleet"
CAROL = ("carol", "carolsecret1")


@pytest.fixture()
def server(config, users):
    """Leave and Fleet installed, the admin the team lead, carol an outsider."""
    config.quill_code = "trusted"
    users.create(CAROL[0], hash_password(CAROL[1]))
    client = TestClient(create_app(config))
    admin = {"Authorization": "Bearer " + token_for(client, *ADMIN)}
    for folder in (LEAVE, FLEET):
        assert client.post("/api/quills", json={"source": str(folder)}, headers=admin).status_code == 201
    client.app.state.cloudmorrow.roles.give("team_lead", ADMIN[0])
    guest = {"Authorization": "Bearer " + token_for(client, *GUEST)}
    carol = {"Authorization": "Bearer " + token_for(client, *CAROL)}
    return client, admin, guest, carol


def state_of(client):
    return client.app.state.cloudmorrow


def make_flow(client, headers, **fields) -> dict:
    fields.setdefault("name", "A flow")
    made = client.post("/api/records/flow", json={"fields": fields}, headers=headers)
    assert made.status_code == 201, made.text
    return made.json()


def runs_of(client, headers, flow_id) -> list[dict]:
    return client.get(f"/api/records/flow_run?flow={flow_id}", headers=headers).json()


def _employment(client, headers) -> str:
    book = client.post("/api/records/book", json={"fields": {"name": "People"}}, headers=headers).json()
    contact = client.post("/api/records/contact", json={"fields": {"book": book["id"], "name": "Me"}}, headers=headers)
    return client.post(
        "/api/records/employment", json={"fields": {"contact": contact.json()["id"], "role": "Clerk"}}, headers=headers
    ).json()["id"]


def _leave(client, headers, what="Dentist") -> dict:
    made = client.post(
        "/api/records/leave",
        json={
            "fields": {
                "employment": _employment(client, headers),
                "what": what,
                "starts": "2026-11-02",
                "ends": "2026-11-03",
            }
        },
        headers=headers,
    )
    assert made.status_code == 201, made.text
    return made.json()


LEAVE_FLOW = {
    "trigger": {"kind": "record", "model": "leave", "when": ["created"]},
    "steps": [
        {"id": "ask", "kind": "approval", "role": "team_lead", "question": "Approve {{trigger.record.fields.what}}?"},
        {
            "id": "yes",
            "kind": "set",
            "model": "leave",
            "record": "{{trigger.record.id}}",
            "fields": {"status": "approved"},
            "only_if": {"path": "approval.status", "equals": "approved"},
        },
        {
            "id": "no",
            "kind": "set",
            "model": "leave",
            "record": "{{trigger.record.id}}",
            "fields": {"status": "declined"},
            "only_if": {"path": "approval.status", "equals": "declined"},
        },
        {
            "id": "tell",
            "kind": "notify",
            "to": "{{trigger.record.owner}}",
            "title": "Your leave was {{approval.status}}",
            "body": "{{approval.note}}",
        },
    ],
}


# -- the pieces on their own -------------------------------------------------------------------------
def test_placeholders_read_the_context_and_keep_a_lone_values_type():
    context = {
        "trigger": {"record": {"id": "r1", "fields": {"what": "Dentist", "days": 2, "on": True}}},
        "approval": None,
    }
    assert flows.render("Approve {{trigger.record.fields.what}}?", context) == "Approve Dentist?"
    assert flows.render("{{trigger.record.fields.days}}", context) == 2
    assert flows.render({"record": "{{ trigger.record.id }}", "n": ["{{trigger.record.fields.on}}"]}, context) == {
        "record": "r1",
        "n": [True],
    }
    # A path that ends early is nothing, and nothing in words.
    assert flows.render("{{approval.status}}", context) is None
    assert flows.render("was {{approval.status}}", context) == "was "


def test_only_if_is_read_the_same_way():
    context = {"approval": {"status": "approved", "note": ""}}
    assert flows.applies({"only_if": {"path": "approval.status", "equals": "approved"}}, context)
    assert not flows.applies({"only_if": {"path": "approval.status", "not_equals": "approved"}}, context)
    assert flows.applies({"only_if": {"path": "approval.note", "empty": True}}, context)
    assert flows.applies({}, context)


@pytest.mark.parametrize(
    ("trigger", "steps", "words"),
    [
        ({"kind": "sometimes"}, [], "one of"),
        ({"kind": "record"}, [], "names a datamodel"),
        ({"kind": "record", "model": "leave", "when": "renamed"}, [], "when is"),
        ({"kind": "schedule", "every": "soon"}, [], "every"),
        ({"kind": "manual"}, [{"kind": "dance"}], "kind is one of"),
        ({"kind": "manual"}, [{"kind": "set", "model": "leave"}], "names the record"),
        ({"kind": "manual"}, [{"kind": "approval", "role": "team_lead"}], "asks a question"),
        ({"kind": "manual"}, [{"kind": "wait"}], "one of them"),
        ({"kind": "manual"}, [{"kind": "stop", "id": "a"}, {"kind": "stop", "id": "a"}], "id of its own"),
        ({"kind": "manual"}, [{"kind": "stop", "only_if": {"path": "x"}}], "only_if is"),
    ],
)
def test_a_flow_is_checked_before_it_runs(client, auth, trigger, steps, words):
    checked = client.post("/api/flows/check", json={"trigger": trigger, "steps": steps}, headers=auth).json()
    assert checked["ok"] is False and words in checked["problem"]


def test_a_good_flow_checks_out_with_its_defaults_filled(client, auth):
    checked = client.post(
        "/api/flows/check",
        json={"trigger": {"kind": "record", "model": "leave"}, "steps": [{"kind": "stop"}]},
        headers=auth,
    ).json()
    assert checked == {
        "ok": True,
        "trigger": {"kind": "record", "model": "leave", "when": ["created"]},
        "steps": [{"kind": "stop", "id": "step1"}],
    }
    assert client.get("/api/flows/kinds", headers=auth).json()["steps"] == list(flows.STEP_KINDS)


# -- the first customer ----------------------------------------------------------------------------------
def test_a_leave_asks_the_team_lead_and_the_answer_sets_its_status(server):
    client, admin, guest, _ = server
    state = state_of(client)
    flow = make_flow(client, guest, name="Leave requests", **LEAVE_FLOW)
    leave = _leave(client, guest)
    state.flows.drain()
    # One run, waiting on the approval the flow asked, as the guest.
    (run,) = runs_of(client, guest, flow["id"])
    assert run["fields"]["status"] == "waiting" and run["fields"]["step"] == 0
    approval_id = run["fields"]["waiting_on"]
    asked = client.get(f"/api/records/approval/{approval_id}", headers=guest).json()
    assert asked["fields"]["question"] == "Approve Dentist?" and asked["fields"]["about"] == leave["id"]
    assert asked["fields"]["about_model"] == "leave" and asked["fields"]["about_title"] == "Dentist"
    assert asked["fields"]["flow_run"] == run["id"] and asked["written_by"] == "flow"
    assert [a["id"] for a in client.get("/api/approvals", headers=admin).json()["waiting"]] == [approval_id]
    # The team lead says yes: the run picks up, skips the "no" step, sets the status, tells the guest.
    answered = client.post(
        f"/api/approvals/{approval_id}/answer", json={"status": "approved", "note": "Fine"}, headers=admin
    )
    assert answered.status_code == 200, answered.text
    state.flows.drain()
    (run,) = runs_of(client, guest, flow["id"])
    assert run["fields"]["status"] == "done" and run["fields"]["step"] == 4, run["fields"]
    assert run["fields"]["context"]["approval"]["status"] == "approved"
    assert run["fields"]["context"]["steps"]["yes"]["fields"]["status"] == "approved"
    assert "no" not in run["fields"]["context"]["steps"]
    changed = client.get(f"/api/records/leave/{leave['id']}", headers=guest).json()
    assert changed["fields"]["status"] == "approved" and changed["written_by"] == "flow"
    notes = state.notifications.list(GUEST[0])
    assert [n.title for n in notes if n.kind == "flow"] == ["Your leave was approved"]
    assert next(n for n in notes if n.kind == "flow").body == "Fine"


def test_declined_takes_the_other_branch(server):
    client, admin, guest, _ = server
    state = state_of(client)
    flow = make_flow(client, guest, name="Leave requests", **LEAVE_FLOW)
    leave = _leave(client, guest, "Golf")
    state.flows.drain()
    (run,) = runs_of(client, guest, flow["id"])
    client.post(f"/api/approvals/{run['fields']['waiting_on']}/answer", json={"status": "declined"}, headers=admin)
    state.flows.drain()
    assert client.get(f"/api/records/leave/{leave['id']}", headers=guest).json()["fields"]["status"] == "declined"
    (run,) = runs_of(client, guest, flow["id"])
    assert run["fields"]["status"] == "done" and "yes" not in run["fields"]["context"]["steps"]


def test_a_flow_runs_as_its_owner_and_over_what_they_may_see(server):
    client, admin, guest, carol = server
    state = state_of(client)
    # Carol's flow on leaves: the guest's personal leave is not hers to see, so it does not fire.
    flow = make_flow(client, carol, name="Carol watches", **LEAVE_FLOW)
    _leave(client, guest)
    state.flows.drain()
    assert runs_of(client, carol, flow["id"]) == []
    # A flow switched off does not fire either.
    off = make_flow(client, guest, name="Off", on=False, **LEAVE_FLOW)
    _leave(client, guest, "Away")
    state.flows.drain()
    assert runs_of(client, guest, off["id"]) == []


def test_an_action_step_carries_its_result_to_the_next(server):
    """A manual flow makes a van, logs a service on it through Fleet's action, and says so."""
    client, admin, guest, _ = server
    state = state_of(client)
    flow = make_flow(
        client,
        guest,
        name="New van",
        trigger={"kind": "manual"},
        steps=[
            {"id": "van", "kind": "create", "model": "vehicle", "fields": {"name": "Flow van", "registration": "FL 1"}},
            {
                "id": "service",
                "kind": "action",
                "quill": "fleet",
                "action": "log-service",
                "record": "{{steps.van.id}}",
                "fields": {"date": "2026-10-20", "km": "1200"},
            },
            {"id": "note", "kind": "notify", "to": "{{owner}}", "title": "Van {{steps.van.fields.name}} is in"},
        ],
    )
    ran = client.post(f"/api/flows/{flow['id']}/run", json={}, headers=guest)
    assert ran.status_code == 200, ran.text
    assert ran.json()["fields"]["status"] == "done", ran.json()["fields"]
    state.code.drain()
    (van,) = client.get("/api/records/vehicle", headers=guest).json()
    assert van["fields"]["name"] == "Flow van" and van["owner"] == GUEST[0]
    # Fleet's hook on the visit moved the odometer: the action really ran, as the guest.
    assert van["fields"]["fleet.odometer"] == 1200
    (visit,) = client.get("/api/records/fleet.visit", headers=guest).json()
    assert visit["fields"]["km"] == 1200 and visit["written_by"] == "fleet"
    assert [n.title for n in state.notifications.list(GUEST[0])] == ["Van Flow van is in"]
    # Not somebody else's flow to run.
    assert client.post(f"/api/flows/{flow['id']}/run", json={}, headers=admin).status_code == 404


def test_an_action_trigger_starts_a_flow_with_the_actions_result(server):
    client, admin, guest, _ = server
    state = state_of(client)
    flow = make_flow(
        client,
        guest,
        name="After asking",
        trigger={"kind": "action", "quill": "leave", "action": "request"},
        steps=[
            {
                "id": "note",
                "kind": "notify",
                "to": "{{owner}}",
                "title": "Asked about {{trigger.fields.what}} ({{trigger.result.approval}})",
            }
        ],
    )
    pressed = client.post(
        "/api/quills/leave/actions/request",
        json={
            "fields": {
                "employment": _employment(client, guest),
                "what": "Dentist",
                "starts": "2026-11-02",
                "ends": "2026-11-03",
            }
        },
        headers=guest,
    )
    assert pressed.status_code == 200, pressed.text
    approval = next(e for e in pressed.json()["effects"] if e["effect"] == "result")["values"]["approval"]
    state.flows.drain()
    (run,) = runs_of(client, guest, flow["id"])
    assert run["fields"]["status"] == "done"
    assert [n.title for n in state.notifications.list(GUEST[0]) if n.kind == "flow"] == [
        f"Asked about Dentist ({approval})"
    ]


def test_a_wait_step_sleeps_until_the_clock_wakes_it(server):
    client, admin, guest, _ = server
    state = state_of(client)
    flow = make_flow(
        client,
        guest,
        name="Patience",
        trigger={"kind": "manual"},
        steps=[
            {"id": "nap", "kind": "wait", "for": "1h"},
            {"id": "note", "kind": "notify", "to": "{{owner}}", "title": "Woke up"},
        ],
    )
    run = client.post(f"/api/flows/{flow['id']}/run", json={}, headers=guest).json()
    assert run["fields"]["status"] == "waiting" and run["fields"]["wake_at"]
    # Not yet.
    assert state.flows.run_due() == []
    # Time passes.
    past = (dt.datetime.now(tz=dt.UTC) - dt.timedelta(minutes=1)).isoformat(timespec="seconds")
    state.records.update(flows.Principal(flows.KIND, GUEST[0]), "flow_run", run["id"], {"wake_at": past})
    assert state.flows.run_due() == [run["id"]]
    state.flows.drain()
    (run,) = runs_of(client, guest, flow["id"])
    assert run["fields"]["status"] == "done"
    assert [n.title for n in state.notifications.list(GUEST[0])] == ["Woke up"]


def test_a_failing_step_leaves_the_run_failed_with_the_words(server):
    client, admin, guest, _ = server
    flow = make_flow(
        client,
        guest,
        name="Broken",
        trigger={"kind": "manual"},
        steps=[{"id": "x", "kind": "set", "model": "leave", "record": "nothing", "fields": {"status": "approved"}}],
    )
    run = client.post(f"/api/flows/{flow['id']}/run", json={}, headers=guest).json()
    assert run["fields"]["status"] == "failed" and "no such record" in run["fields"]["error"]


def test_a_flows_own_writes_do_not_start_it_again(server):
    client, admin, guest, _ = server
    state = state_of(client)
    flow = make_flow(
        client,
        guest,
        name="Echo",
        trigger={"kind": "record", "model": "vehicle", "when": ["created"]},
        steps=[
            {
                "id": "again",
                "kind": "create",
                "model": "vehicle",
                "fields": {"name": "Echo of {{trigger.record.fields.name}}"},
            }
        ],
    )
    client.post("/api/records/vehicle", json={"fields": {"name": "First"}}, headers=guest)
    state.flows.drain()
    names = sorted(v["fields"]["name"] for v in client.get("/api/records/vehicle", headers=guest).json())
    assert names == ["Echo of First", "First"]
    assert len(runs_of(client, guest, flow["id"])) == 1


def test_a_scheduled_flow_runs_on_the_clock_once_per_interval(server):
    client, admin, guest, _ = server
    state = state_of(client)
    flow = make_flow(
        client,
        guest,
        name="Daily",
        trigger={"kind": "schedule", "every": "1d"},
        steps=[{"id": "note", "kind": "notify", "to": "{{owner}}", "title": "Good morning"}],
    )
    assert state.flows.run_due() == [flow["id"]]
    state.flows.drain()
    assert state.flows.run_due() == []
    assert len(runs_of(client, guest, flow["id"])) == 1
