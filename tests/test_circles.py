"""Circles: who may use which data, and Quills that do what the data lets them."""

from __future__ import annotations

import base64

import pytest

from cloudmorrow.server.circles import Access, CircleError
from cloudmorrow.server.security import hash_password
from tests.conftest import ADMIN, GUEST, token_for


def headers(client, who) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(client, *who)}"}


@pytest.fixture()
def circles(client):
    return client.app.state.cloudmorrow.circles


def kids(circles, rules: dict[str, str]) -> None:
    """Guest out of Members and into Kids, with *rules*."""
    circles.leave("members", GUEST[0])
    circles.create("Kids", rules, [GUEST[0]])


# -- the store -------------------------------------------------------------------
def test_a_fresh_server_has_members_with_everything_and_everybody_in_it(circles, users):
    (members,) = circles.list()
    assert members.name == "Members" and members.is_default
    assert members.rules == {"*": "write"}
    assert members.members == [ADMIN[0], GUEST[0]]
    # A new account goes into the default circle.
    users.create("carol", hash_password("carolsecret1"))
    assert "carol" in circles.get("Members").members
    # And leaves every circle when it goes.
    users.delete("carol")
    assert "carol" not in circles.get("Members").members


def test_access_is_the_most_any_circle_gives_and_a_named_rule_beats_star():
    access = Access(
        "alice",
        {
            "Kids": {"task": "write", "event": "read"},
            "Readers": {"*": "read", "secret": "none"},
        },
    )
    assert access.level("task") == "write"
    assert access.level("event") == "read"
    assert access.level("contact") == "read"
    # Within Readers, secret's own line beats its star; no other circle gives it.
    assert access.level("secret") == "none"
    assert access.may("read", "event") and not access.may("write", "event")
    assert access.of(["task", "secret", "contact"]) == {"task": "write", "contact": "read"}
    assert Access("nobody").level("task") == "none"


def test_rules_and_members_are_checked(circles):
    with pytest.raises(CircleError):
        circles.create("Kids", {"task": "sometimes"})
    with pytest.raises(CircleError):
        circles.create("Kids", members=["nobody-here"])
    with pytest.raises(CircleError):
        circles.create("Members")
    circles.create("Kids", {"task": "read"})
    circle = circles.set_rule("kids", "task", "write")
    assert circle.rules == {"task": "write"}
    # None on * is no * at all; none on a datamodel stays, to beat a *.
    circles.set_rule("Kids", "*", "read")
    circles.set_rule("Kids", "secret", "none")
    assert circles.set_rule("Kids", "*", "none").rules == {"task": "write", "secret": "none"}


# -- the gate ----------------------------------------------------------------------
def test_read_only_data_is_seen_and_not_changed(tasks_quill, circles):
    admin = headers(tasks_quill, ADMIN)
    guest = headers(tasks_quill, GUEST)
    kids(circles, {"task": "read", "board": "read"})
    # Their first board is still laid for them: the Quill's dataset, not them writing.
    boards = tasks_quill.get("/api/records/board", headers=guest)
    assert boards.status_code == 200 and len(boards.json()) == 1
    board = boards.json()[0]["id"]
    made = tasks_quill.post("/api/records/task", json={"fields": {"board": board, "title": "Tidy"}}, headers=guest)
    assert made.status_code == 403 and "not change" in made.json()["detail"]
    renamed = tasks_quill.patch(f"/api/records/board/{board}", json={"fields": {"title": "Mine"}}, headers=guest)
    assert renamed.status_code == 403
    # Administrators are in Members, and Members has everything.
    assert tasks_quill.get("/api/records/board", headers=admin).status_code == 200


def test_data_no_circle_gives_is_not_there(tasks_quill, circles):
    guest = headers(tasks_quill, GUEST)
    kids(circles, {"task": "write"})
    assert tasks_quill.get("/api/records/board", headers=guest).status_code == 404
    listed = {m["id"]: m for m in tasks_quill.get("/api/datamodels", headers=guest).json()}
    assert "board" not in listed and listed["task"]["access"] == "write"


def test_somebody_in_no_circle_reaches_nothing(tasks_quill, circles):
    guest = headers(tasks_quill, GUEST)
    circles.leave("members", GUEST[0])
    assert tasks_quill.get("/api/records/task", headers=guest).status_code == 404
    mine = tasks_quill.get("/api/me/access", headers=guest).json()
    assert mine == {"username": GUEST[0], "access": {}, "circles": [], "own": {}}


def test_a_quill_is_fitted_to_the_person_asking(tasks_quill, circles):
    guest = headers(tasks_quill, GUEST)

    def tasks() -> dict:
        (quill,) = [q for q in tasks_quill.get("/api/quills", headers=guest).json() if q["id"] == "tasks"]
        return quill

    whole = tasks()
    assert whole["available"] and whole["enabled"]
    assert whole["models"]["task"]["access"] == "write"

    kids(circles, {"task": "read", "board": "read"})
    looking = tasks()
    assert looking["available"] and [s["id"] for s in looking["screens"]] == ["board"]
    assert {m["access"] for m in looking["models"].values()} == {"read"}

    # Tasks but not boards: the board screen is drawn within boards, so it goes,
    # and so does the Quill; the task's link to its board goes with its data.
    circles.update("kids", rules={"task": "write"})
    gone = tasks()
    assert gone["screens"] == [] and not gone["available"] and not gone["enabled"]
    assert "board" not in gone["models"]
    assert "board" not in [f["name"] for f in gone["models"]["task"]["fields"]]


# -- the circles API -----------------------------------------------------------------
def test_only_administrators_change_circles(client, circles):
    guest = headers(client, GUEST)
    assert client.get("/api/circles", headers=guest).status_code == 403
    assert client.post("/api/circles", json={"name": "Kids"}, headers=guest).status_code == 403


def test_circles_are_made_changed_joined_and_deleted(client, auth, circles):
    made = client.post(
        "/api/circles",
        json={"name": "Kids", "rules": {"task": "write"}, "members": [GUEST[0]]},
        headers=auth,
    )
    assert made.status_code == 201, made.text
    assert made.json() == {
        "id": "kids",
        "name": "Kids",
        "default": False,
        "rules": {"task": "write"},
        "members": [GUEST[0]],
    }
    assert client.post("/api/circles", json={"name": "kids"}, headers=auth).status_code == 400
    changed = client.patch("/api/circles/kids", json={"rules": {"event": "read"}, "default": True}, headers=auth).json()
    assert changed["rules"] == {"event": "read"} and changed["default"]
    joined = client.put(f"/api/circles/kids/members/{ADMIN[0]}", headers=auth).json()
    assert joined["members"] == [ADMIN[0], GUEST[0]]
    assert client.put("/api/circles/kids/members/nobody", headers=auth).status_code == 400
    left = client.delete(f"/api/circles/Kids/members/{GUEST[0]}", headers=auth).json()
    assert left["members"] == [ADMIN[0]]
    assert client.delete("/api/circles/kids", headers=auth).status_code == 204
    assert client.get("/api/circles/kids", headers=auth).status_code == 404
    mine = client.get("/api/me/access", headers=auth).json()
    assert mine["circles"] == ["Members"]


def test_one_rule_is_set_and_the_others_are_kept(client, auth):
    set_once = client.put("/api/circles/members/rules/task", json={"access": "read"}, headers=auth)
    assert set_once.status_code == 200, set_once.text
    assert set_once.json()["rules"] == {"*": "write", "task": "read"}
    bad = client.put("/api/circles/members/rules/task", json={"access": "maybe"}, headers=auth)
    assert bad.status_code == 400
    missing = client.put("/api/circles/nope/rules/task", json={"access": "read"}, headers=auth)
    assert missing.status_code == 404


# -- the doors that are not the record API -------------------------------------------
def test_notes_follow_the_file_datamodel(notes_quill, circles):
    guest = headers(notes_quill, GUEST)
    kids(circles, {"file": "read"})
    pages = "/api/records/file?share=my-files&within=Notes&suffix=.md"
    assert notes_quill.get(pages, headers=guest).status_code == 200
    diary = {"fields": {"share": "my-files", "path": "Notes/diary.md", "text": ""}}
    assert notes_quill.post("/api/records/file", json=diary, headers=guest).status_code == 403
    circles.update("kids", rules={})
    assert notes_quill.get(pages, headers=guest).status_code == 404


def test_an_assistant_reaches_what_the_person_may(notes_quill, circles):
    from cloudmorrow.server import mcptools

    state = notes_quill.app.state.cloudmorrow
    guest = state.users.require(GUEST[0])
    kids(circles, {"file": "read"})
    page = {"model": "file", "fields": {"share": "my-files", "path": "Notes/x.md", "text": ""}}
    refused = mcptools.call(state, guest, "create_record", page)
    assert refused["isError"] and "not change" in refused["content"][0]["text"]
    models = mcptools.call(state, guest, "list_datamodels", {})["structuredContent"]
    assert [m["id"] for m in models["datamodels"]] == ["file"]


def test_a_mount_is_read_only_for_whoever_may_only_read_files(client, circles):
    kids(circles, {"file": "read"})
    basic = base64.b64encode(f"{GUEST[0]}:{GUEST[1]}".encode()).decode()
    auth = {"Authorization": f"Basic {basic}"}
    put = client.put("/dav/drive/hello.txt", content=b"hi", headers=auth)
    assert put.status_code == 403
    circles.update("kids", rules={})
    listing = client.request("PROPFIND", "/dav/", headers={**auth, "Depth": "1"})
    assert listing.status_code == 207 and b"drive" not in listing.content.lower()


def test_nobody_is_told_about_data_they_may_not_read(client, circles, tmp_path):
    from tests.test_spaces import CAL, install

    install(client, CAL, tmp_path, "cal")
    admin = headers(client, ADMIN)
    guest = headers(client, GUEST)
    kids(circles, {"event": "read"})
    house = client.post("/api/records/calendar", json={"fields": {"name": "House"}}, headers=admin)
    added = client.post(
        f"/api/records/calendar/{house.json()['id']}/members",
        json={"username": GUEST[0]},
        headers=admin,
    )
    assert added.status_code == 200, added.text
    bell = client.get("/api/notifications", headers=guest).json()
    assert not any("House" in n["title"] for n in bell)


# -- a person's own rules --------------------------------------------------------
def test_a_person_may_have_rules_of_their_own_beside_their_circles(circles):
    """The one person who needs the budget, without a circle made for them."""
    circles.leave("members", GUEST[0])
    assert circles.access_for(GUEST[0]).level("task") == "none"
    circles.set_person_rule(GUEST[0], "task", "read")
    access = circles.access_for(GUEST[0])
    assert access.level("task") == "read" and access.own == {"task": "read"}
    assert access.may("read", "task") and not access.may("write", "task")
    # The most of all of it: a circle's write beats their own read.
    circles.create("Readers", {"task": "write"}, [GUEST[0]])
    assert circles.access_for(GUEST[0]).level("task") == "write"
    # A `*` of their own, and a named none that beats it; none on `*` takes it away.
    circles.set_person_rule(GUEST[0], "*", "write")
    circles.set_person_rule(GUEST[0], "board", "none")
    assert circles.access_for(GUEST[0]).level("event") == "write"
    assert circles.rules_of(GUEST[0]) == {"*": "write", "board": "none", "task": "read"}
    circles.set_person_rule(GUEST[0], "*", "none")
    assert circles.rules_of(GUEST[0]) == {"board": "none", "task": "read"}
    circles.clear_person_rule(GUEST[0], "task")
    assert circles.rules_of(GUEST[0]) == {"board": "none"}
    with pytest.raises(CircleError):
        circles.set_person_rule("nobody", "task", "read")
    with pytest.raises(CircleError):
        circles.set_person_rule(GUEST[0], "task", "maybe")
    circles.forget(GUEST[0])
    assert circles.rules_of(GUEST[0]) == {} and circles.circles_of(GUEST[0]) == []


def test_a_rule_of_their_own_opens_the_data_through_the_gate(tasks_quill, circles):
    client = tasks_quill
    guest = headers(client, GUEST)
    circles.leave("members", GUEST[0])
    assert client.get("/api/records/board", headers=guest).status_code == 404
    admin = headers(client, ADMIN)
    given = client.put("/api/access/guest/board", json={"access": "read"}, headers=admin)
    assert given.status_code == 200, given.text
    assert given.json()["own"] == {"board": "read"} and given.json()["access"] == {"board": "read"}
    assert client.get("/api/records/board", headers=guest).status_code == 200
    assert client.post("/api/records/board", json={"fields": {"title": "x"}}, headers=guest).status_code == 403
    # Their own access says so, and a Quill is fitted to it.
    mine = client.get("/api/me/access", headers=guest).json()
    assert mine["own"] == {"board": "read"} and mine["circles"] == [] and mine["access"] == {"board": "read"}
    theirs = client.get("/api/access/guest", headers=admin).json()
    assert theirs["username"] == "guest" and theirs["own"] == {"board": "read"}
    # Only administrators give, and only to people there are.
    assert client.put("/api/access/guest/task", json={"access": "write"}, headers=guest).status_code == 403
    assert client.get("/api/access/nobody", headers=admin).status_code == 404
    assert client.put("/api/access/guest/task", json={"access": "maybe"}, headers=admin).status_code == 400
    whole = client.put("/api/access/guest", json={"rules": {"board": "read", "task": "write"}}, headers=admin)
    assert whole.status_code == 200 and whole.json()["own"] == {"board": "read", "task": "write"}
    assert client.put("/api/access/guest", json={"rules": {"task": "maybe"}}, headers=admin).status_code == 400
    client.put("/api/access/guest", json={"rules": {"board": "read"}}, headers=admin)
    cleared = client.delete("/api/access/guest/board", headers=admin)
    assert cleared.status_code == 200 and cleared.json()["own"] == {}
    assert client.get("/api/records/board", headers=guest).status_code == 404
