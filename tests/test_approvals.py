"""Approvals: a yes or a no asked of whoever holds a role (docs/FLOWS.md)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cloudmorrow.server.app import create_app
from cloudmorrow.server.records import Principal
from cloudmorrow.server.security import hash_password
from tests.conftest import ADMIN, GUEST, token_for

LEAVE = Path(__file__).parent / "fixtures" / "quill-leave"
CAROL = ("carol", "carolsecret1")


@pytest.fixture()
def leave(config, users):
    """Leave installed; the admin is the team lead; carol is nobody in particular."""
    config.quill_code = "trusted"
    users.create(*CAROL[:1], hash_password(CAROL[1]))
    client = TestClient(create_app(config))
    admin = {"Authorization": "Bearer " + token_for(client, *ADMIN)}
    assert client.post("/api/quills", json={"source": str(LEAVE)}, headers=admin).status_code == 201
    state = client.app.state.cloudmorrow
    state.roles.give("team_lead", ADMIN[0])
    guest = {"Authorization": "Bearer " + token_for(client, *GUEST)}
    carol = {"Authorization": "Bearer " + token_for(client, *CAROL)}
    return client, admin, guest, carol


def _employment(client, headers) -> str:
    book = client.post("/api/records/book", json={"fields": {"name": "People"}}, headers=headers).json()
    contact = client.post("/api/records/contact", json={"fields": {"book": book["id"], "name": "Me"}}, headers=headers)
    made = client.post(
        "/api/records/employment", json={"fields": {"contact": contact.json()["id"], "role": "Clerk"}}, headers=headers
    )
    assert made.status_code == 201, made.text
    return made.json()["id"]


def _ask(client, headers, what="Dentist") -> dict:
    """Guest asks for time off through the Quill: the leave, and the approval asked."""
    pressed = client.post(
        "/api/quills/leave/actions/request",
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
    assert pressed.status_code == 200, pressed.text
    return next(e for e in pressed.json()["effects"] if e["effect"] == "result")["values"]


def test_a_quill_asks_and_the_holders_of_the_role_see_it(leave):
    client, admin, guest, carol = leave
    asked = _ask(client, guest)
    # The asker's record: asked by them, about the leave, of the team lead.
    mine = client.get(f"/api/records/approval/{asked['approval']}", headers=guest).json()
    assert mine["owner"] == GUEST[0] and mine["fields"]["status"] == "requested"
    assert mine["fields"]["about_model"] == "leave" and mine["fields"]["about"] == asked["leave"]
    assert mine["fields"]["about_title"] == "Dentist" and mine["fields"]["role"] == "team_lead"
    assert mine["fields"]["question"] == "Approve Dentist (2026-11-02 to 2026-11-03)?"
    # The team lead sees it, under Waiting for you; the asker sees it under Asked by you.
    waiting = client.get("/api/approvals", headers=admin).json()
    assert [a["id"] for a in waiting["waiting"]] == [asked["approval"]] and waiting["asked"] == []
    assert client.get("/api/approvals/count", headers=admin).json() == {"waiting": 1}
    theirs = client.get("/api/approvals", headers=guest).json()
    assert theirs["waiting"] == [] and [a["id"] for a in theirs["asked"]] == [asked["approval"]]
    # And it reaches the team lead's listing of the datamodel itself.
    assert [a["id"] for a in client.get("/api/records/approval", headers=admin).json()] == [asked["approval"]]
    # Somebody who holds no role sees nothing of it, and cannot learn it exists.
    assert client.get("/api/records/approval", headers=carol).json() == []
    assert client.get(f"/api/records/approval/{asked['approval']}", headers=carol).status_code == 404
    assert client.get("/api/approvals", headers=carol).json() == {"waiting": [], "asked": []}
    # The team lead heard of the question; the asker did not hear their own.
    notes = client.app.state.cloudmorrow.notifications
    assert [n.kind for n in notes.list(ADMIN[0])] == ["approval.asked"]
    assert notes.list(GUEST[0]) == []


def test_only_a_holder_answers_and_the_quill_hears_it(leave):
    client, admin, guest, carol = leave
    asked = _ask(client, guest)
    url = f"/api/approvals/{asked['approval']}/answer"
    # Not carol's to answer, and not the asker's either.
    assert client.post(url, json={"status": "approved"}, headers=carol).status_code == 404
    refused = client.post(url, json={"status": "approved"}, headers=guest)
    assert refused.status_code == 403 and "holds the role" in refused.json()["detail"]
    # The team lead approves, with a word.
    answered = client.post(url, json={"status": "approved", "note": "Enjoy"}, headers=admin)
    assert answered.status_code == 200, answered.text
    fields = answered.json()["fields"]
    assert fields["status"] == "approved" and fields["answered_by"] == ADMIN[0] and fields["note"] == "Enjoy"
    assert fields["answered_at"]
    # Once.
    again = client.post(url, json={"status": "declined"}, headers=admin)
    assert again.status_code == 400 and "already approved" in again.json()["detail"]
    # The Quill's hook ran, as the team lead, and set the leave's status.
    client.app.state.cloudmorrow.code.drain()
    leave_record = client.get(f"/api/records/leave/{asked['leave']}", headers=guest).json()
    assert leave_record["fields"]["status"] == "approved"
    # The asker heard the answer.
    notes = client.app.state.cloudmorrow.notifications
    (note,) = notes.list(GUEST[0])
    assert note.kind == "approval.approved" and note.title.startswith("bram approved:") and note.body == "Enjoy"
    assert client.get("/api/approvals/count", headers=admin).json() == {"waiting": 0}


def test_the_asker_may_withdraw_and_nobody_else(leave):
    client, admin, guest, _ = leave
    asked = _ask(client, guest)
    url = f"/api/approvals/{asked['approval']}/answer"
    assert client.post(url, json={"status": "withdrawn"}, headers=admin).status_code == 403
    assert client.post(url, json={"status": "withdrawn"}, headers=guest).json()["fields"]["status"] == "withdrawn"
    assert client.get("/api/approvals", headers=admin).json()["waiting"] == []


def test_a_role_held_in_a_circle_answers_for_that_circle(leave):
    client, admin, guest, carol = leave
    state = client.app.state.cloudmorrow
    state.circles.create("Sales", {"*": "write"}, [GUEST[0]])
    state.roles.take("team_lead", ADMIN[0])
    state.roles.give("team_lead", CAROL[0], "Sales")
    # Asked in Sales: carol, the Sales team lead, sees it; asked plainly, she does not.
    in_sales = client.post(
        "/api/approvals", json={"role": "team_lead", "question": "Buy a van?", "circle": "sales"}, headers=guest
    )
    assert in_sales.status_code == 201, in_sales.text
    plain = client.post("/api/approvals", json={"role": "team_lead", "question": "Buy a lorry?"}, headers=guest)
    assert plain.status_code == 201
    waiting = client.get("/api/approvals", headers=carol).json()["waiting"]
    assert [a["fields"]["question"] for a in waiting] == ["Buy a van?"]
    assert client.get("/api/approvals", headers=admin).json()["waiting"] == []
    # A role nobody made cannot be asked.
    nothing = client.post("/api/approvals", json={"role": "ceo", "question": "Hm?"}, headers=guest)
    assert nothing.status_code == 400 and "no role called ceo" in nothing.json()["detail"]
    # A question is needed.
    assert client.post("/api/approvals", json={"role": "team_lead", "question": "  "}, headers=guest).status_code == 400


def test_a_quill_may_read_the_approvals_it_asked(leave):
    """ctx.approvals.get, and the Quill's own listing of approval, which it lists in [uses]."""
    client, admin, guest, _ = leave
    asked = _ask(client, guest)
    state = client.app.state.cloudmorrow
    manifest = state.quills.quills["leave"]
    principal = state.code.principal_for(manifest, GUEST[0], via="person")
    found = state.records.get(principal, "approval", asked["approval"])
    assert found.fields["question"].startswith("Approve Dentist")
    assert Principal.person(GUEST[0]).kind == "person"
