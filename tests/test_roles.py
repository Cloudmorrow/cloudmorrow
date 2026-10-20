"""Roles: who is responsible for what, by name — and nothing about data (docs/FLOWS.md)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cloudmorrow.server.app import create_app
from cloudmorrow.server.quills import QuillError, parse_manifest
from cloudmorrow.server.roles import RoleError, RoleStore, UnknownRoleError
from cloudmorrow.server.security import hash_password
from tests.conftest import ADMIN, GUEST, token_for

LEAVE = Path(__file__).parent / "fixtures" / "quill-leave"


@pytest.fixture()
def roles(client) -> RoleStore:
    return client.app.state.cloudmorrow.roles


@pytest.fixture()
def leave(config, users):
    """A server with the Leave Quill, which declares the team_lead role."""
    config.quill_code = "trusted"
    client = TestClient(create_app(config))
    admin = {"Authorization": "Bearer " + token_for(client, *ADMIN)}
    answer = client.post("/api/quills", json={"source": str(LEAVE)}, headers=admin)
    assert answer.status_code == 201, answer.text
    guest = {"Authorization": "Bearer " + token_for(client, *GUEST)}
    return client, admin, guest


# -- the store ----------------------------------------------------------------------------------
def test_a_role_is_a_name_and_who_holds_it(roles, users):
    made = roles.create("Team lead", "approves time off")
    assert made.id == "team_lead" and made.holders == ()
    roles.give("team_lead", GUEST[0])
    assert roles.people("team_lead") == [GUEST[0]]
    assert roles.holds(GUEST[0], "Team lead") and not roles.holds(ADMIN[0], "team_lead")
    assert roles.roles_of(GUEST[0]) == [{"id": "team_lead", "name": "Team lead", "circle": ""}]
    roles.take("team_lead", GUEST[0])
    assert roles.people("team_lead") == []
    # Found by id or by name, either case; a role nobody made is held by nobody.
    assert roles.get("TEAM LEAD").id == "team_lead"
    assert roles.people("nothing") == []
    with pytest.raises(UnknownRoleError):
        roles.get("nothing")


def test_a_role_is_held_everywhere_or_within_a_circle(client, roles, users):
    circles = client.app.state.cloudmorrow.circles
    circles.create("Sales", {"*": "write"}, [GUEST[0]])
    users.create("carol", hash_password("carolsecret1"))
    roles.create("Team lead")
    roles.give("team_lead", GUEST[0], "Sales")
    roles.give("team_lead", "carol")
    # Asked plainly: those who hold it everywhere. Asked for Sales: both.
    assert roles.people("team_lead") == ["carol"]
    assert roles.people("team_lead", "sales") == ["carol", GUEST[0]]
    assert roles.holds(GUEST[0], "team_lead", "Sales") and not roles.holds(GUEST[0], "team_lead")
    with pytest.raises(RoleError):
        roles.give("team_lead", GUEST[0], "Warehouse")
    # The circle goes: the hat worn in it comes off.
    circles.delete("sales")
    roles.forget_circle("sales")
    assert roles.people("team_lead", "") == ["carol"] and roles.get("team_lead").holders == (("carol", ""),)
    # The account goes: no hats.
    users.delete("carol")
    assert roles.people("team_lead") == []


def test_names_and_people_are_checked(roles):
    with pytest.raises(RoleError):
        roles.create("   ")
    roles.create("Team lead")
    with pytest.raises(RoleError):
        roles.create("team lead")
    with pytest.raises(RoleError):
        roles.give("team_lead", "nobody-here")


# -- the API ---------------------------------------------------------------------------------
def test_everybody_reads_roles_and_administrators_change_them(client, auth, guest_auth):
    made = client.post(
        "/api/roles", json={"name": "Product owner", "description": "says yes to features"}, headers=auth
    )
    assert made.status_code == 201 and made.json()["id"] == "product_owner"
    assert client.post("/api/roles", json={"name": "Nope"}, headers=guest_auth).status_code == 403
    given = client.put(f"/api/roles/product_owner/holders/{GUEST[0]}", headers=auth)
    assert given.status_code == 200 and given.json()["holders"] == [{"username": GUEST[0], "circle": ""}]
    listed = client.get("/api/roles", headers=guest_auth).json()
    assert [r["id"] for r in listed] == ["product_owner"]
    mine = client.get("/api/me/roles", headers=guest_auth).json()
    assert [r["id"] for r in mine["roles"]] == ["product_owner"]
    assert client.get("/api/me/roles", headers=auth).json()["roles"] == []
    taken = client.delete(f"/api/roles/product_owner/holders/{GUEST[0]}", headers=auth)
    assert taken.json()["holders"] == []
    assert client.get("/api/roles/nothing", headers=auth).status_code == 404
    assert client.delete("/api/roles/product_owner", headers=auth).status_code == 204
    assert client.get("/api/roles", headers=auth).json() == []


# -- what a Quill declares ----------------------------------------------------------------------
def test_a_quill_declares_the_roles_it_expects(leave):
    client, admin, _ = leave
    roles = client.app.state.cloudmorrow.roles
    found = roles.get("team_lead")
    assert found.name == "Team lead" and found.declared_by == "leave" and found.holders == ()
    assert found.description == "to approve or decline time off"
    quill = next(q for q in client.get("/api/quills", headers=admin).json() if q["id"] == "leave")
    assert quill["roles"] == [{"id": "team_lead", "label": "Team lead", "why": "to approve or decline time off"}]
    # Deleted, it comes back empty when the Quills are read again.
    roles.delete("team_lead")
    client.app.state.cloudmorrow.quills.reload()
    assert roles.get("team_lead").holders == ()


def _manifest(extra: str) -> dict:
    import tomllib

    return tomllib.loads('[quill]\nid = "demo"\nname = "Demo"\nversion = "1.0.0"\n' + extra)


@pytest.mark.parametrize(
    ("extra", "words"),
    [
        ('[[roles]]\nid = "Team Lead"\nwhy = "x"\n', "lowercase"),
        ('[[roles]]\nid = "team_lead"\n', "says why"),
        ('[[roles]]\nid = "team_lead"\nwhy = "x"\n[[roles]]\nid = "team_lead"\nwhy = "y"\n', "two roles"),
        ('[[roles]]\nid = "team_lead"\nwhy = "x"\ncolour = "red"\n', "unknown keys"),
    ],
)
def test_a_declared_role_is_checked(extra, words):
    with pytest.raises(QuillError, match=words):
        parse_manifest(_manifest(extra))


def test_the_code_knows_who_holds_a_role(leave):
    client, admin, guest = leave
    state = client.app.state.cloudmorrow
    state.roles.give("team_lead", ADMIN[0])
    employment = client.post(
        "/api/records/employment", json={"fields": {"contact": _contact(client, guest), "role": "Clerk"}}, headers=guest
    ).json()
    leave_id = client.post(
        "/api/records/leave",
        json={
            "fields": {"employment": employment["id"], "what": "Dentist", "starts": "2026-11-02", "ends": "2026-11-02"}
        },
        headers=guest,
    ).json()["id"]
    pressed = client.post("/api/quills/leave/actions/who-approves", json={"record": leave_id}, headers=guest)
    assert pressed.status_code == 200, pressed.text
    values = next(e for e in pressed.json()["effects"] if e["effect"] == "result")["values"]
    assert values == {"people": [ADMIN[0]], "mine": []}
    # As the admin, who holds it: ctx.user.roles says so.
    pressed = client.post(
        "/api/quills/leave/actions/who-approves", json={"record": _own_leave(client, admin)}, headers=admin
    )
    assert next(e for e in pressed.json()["effects"] if e["effect"] == "result")["values"]["mine"] == ["team_lead"]


def _contact(client, headers) -> str:
    book = client.post("/api/records/book", json={"fields": {"name": "People"}}, headers=headers).json()
    made = client.post(
        "/api/records/contact", json={"fields": {"book": book["id"], "name": "Someone"}}, headers=headers
    )
    assert made.status_code == 201, made.text
    return made.json()["id"]


def _own_leave(client, headers) -> str:
    employment = client.post(
        "/api/records/employment",
        json={"fields": {"contact": _contact(client, headers), "role": "Boss"}},
        headers=headers,
    ).json()
    return client.post(
        "/api/records/leave",
        json={"fields": {"employment": employment["id"], "what": "Golf", "starts": "2026-11-03", "ends": "2026-11-03"}},
        headers=headers,
    ).json()["id"]
