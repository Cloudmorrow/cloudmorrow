"""The record store and its API, through the Tasks Quill: the proof it is enough."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3

import pytest

from cloudmorrow.server.crypto import SealError
from cloudmorrow.server.records import Principal, RecordError, Refused, check
from tests.conftest import ADMIN, GUEST, token_for


@pytest.fixture()
def api(tasks_quill):
    headers = {"Authorization": f"Bearer {token_for(tasks_quill, *ADMIN)}"}

    def call(
        method: str,
        path: str,
        body: dict | None = None,
        *,
        expect: int = 200,
        as_: dict | None = None,
    ):
        response = tasks_quill.request(method, path, json=body, headers=as_ or headers)
        assert response.status_code == expect, response.text
        return response.json() if response.content else None

    call.client = tasks_quill
    return call


def board_of(api) -> str:
    return api("GET", "/api/records/board")[0]["id"]


def test_the_first_board_is_seeded_once_and_named_after_you(api):
    boards = api("GET", "/api/records/board")
    assert [b["fields"]["title"] for b in boards] == ["bram's tasks"]
    assert boards[0]["written_by"] == "tasks"
    api("DELETE", f"/api/records/board/{boards[0]['id']}", expect=204)
    # Deleted down to none, it comes back: there is never no board.
    again = api("GET", "/api/records/board")
    assert len(again) == 1 and again[0]["id"] != boards[0]["id"]


def test_a_task_starts_in_todo_at_the_bottom_and_moves_between_lanes(api):
    board = board_of(api)
    first = api(
        "POST",
        "/api/records/task",
        {"fields": {"board": board, "title": "Repot the fig"}},
        expect=201,
    )
    second = api(
        "POST", "/api/records/task", {"fields": {"board": board, "title": "Water it"}}, expect=201
    )
    assert first["fields"]["lane"] == "todo" and first["position"] == 0
    assert second["position"] == 1 and first["rev"] == 1

    moved = api(
        "POST", f"/api/records/task/{second['id']}/move", {"fields": {"lane": "doing"}, "index": 0}
    )
    assert moved["fields"]["lane"] == "doing" and moved["position"] == 0 and moved["rev"] == 2

    todo = api("GET", f"/api/records/task?board={board}&lane=todo")
    assert [t["id"] for t in todo] == [first["id"]] and todo[0]["position"] == 0

    # Back into todo, at the top: the lane renumbers around it.
    api("POST", f"/api/records/task/{second['id']}/move", {"fields": {"lane": "todo"}, "index": 0})
    todo = api("GET", f"/api/records/task?board={board}&lane=todo")
    assert [(t["id"], t["position"]) for t in todo] == [(second["id"], 0), (first["id"], 1)]


def test_done_is_stamped_on_entering_kept_while_there_and_cleared_on_leaving(api):
    board = board_of(api)
    task = api(
        "POST", "/api/records/task", {"fields": {"board": board, "title": "Finish"}}, expect=201
    )
    assert task["fields"]["done_at"] is None and task["expires_at"] is None
    done = api("POST", f"/api/records/task/{task['id']}/move", {"fields": {"lane": "done"}})
    stamped = done["fields"]["done_at"]
    assert stamped and done["expires_at"]
    expires = dt.datetime.fromisoformat(done["expires_at"]) - dt.datetime.fromisoformat(stamped)
    assert expires == dt.timedelta(days=7)
    # Editing the text does not restart the week.
    edited = api("PATCH", f"/api/records/task/{task['id']}", {"fields": {"body": "- [x] it"}})
    assert edited["fields"]["done_at"] == stamped
    back = api("POST", f"/api/records/task/{task['id']}/move", {"fields": {"lane": "doing"}})
    assert back["fields"]["done_at"] is None and back["expires_at"] is None
    # And it cannot be set by hand.
    api("PATCH", f"/api/records/task/{task['id']}", {"fields": {"done_at": stamped}}, expect=400)


def test_a_task_done_for_a_week_is_swept_when_the_board_is_read(api, config):
    board = board_of(api)
    old = api("POST", "/api/records/task", {"fields": {"board": board, "title": "Old"}}, expect=201)
    api("POST", f"/api/records/task/{old['id']}/move", {"fields": {"lane": "done"}})
    fresh = api(
        "POST",
        "/api/records/task",
        {"fields": {"board": board, "title": "Fresh", "lane": "done"}},
        expect=201,
    )
    # Eight days ago, as far as the store can tell.
    long_ago = (dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=8)).isoformat(timespec="seconds")
    with sqlite3.connect(config.db_path) as conn:
        indexed = json.loads(
            conn.execute("SELECT indexed FROM records WHERE id = ?", (old["id"],)).fetchone()[0]
        )
        indexed["done_at"] = long_ago
        conn.execute(
            "UPDATE records SET indexed = ? WHERE id = ?", (json.dumps(indexed), old["id"])
        )
    left = api("GET", f"/api/records/task?board={board}")
    assert [t["id"] for t in left] == [fresh["id"]]
    changes = api.client.app.state.cloudmorrow.records.changes("bram")
    assert ("expired", old["id"]) in [(c["action"], c["record_id"]) for c in changes]


def test_deleting_a_board_takes_its_tasks(api):
    board = board_of(api)
    other = api("POST", "/api/records/board", {"fields": {"title": "Garden"}}, expect=201)
    api("POST", "/api/records/task", {"fields": {"board": board, "title": "Stays"}}, expect=201)
    api(
        "POST", "/api/records/task", {"fields": {"board": other["id"], "title": "Goes"}}, expect=201
    )
    api("DELETE", f"/api/records/board/{other['id']}", expect=204)
    assert [t["fields"]["title"] for t in api("GET", "/api/records/task")] == ["Stays"]


def test_fields_are_checked_against_the_datamodel(api):
    board = board_of(api)
    api("POST", "/api/records/task", {"fields": {"board": board}}, expect=400)  # no title
    api(
        "POST",
        "/api/records/task",
        {"fields": {"board": board, "title": "x", "lane": "later"}},
        expect=400,
    )
    api(
        "POST",
        "/api/records/task",
        {"fields": {"board": board, "title": "x", "colour": "red"}},
        expect=400,
    )
    api("POST", "/api/records/task", {"fields": {"board": "r_nothere00", "title": "x"}}, expect=400)
    api(
        "POST",
        "/api/records/task",
        {"fields": {"board": board, "title": "x", "due": "tomorrow"}},
        expect=400,
    )
    api("GET", "/api/records/task?body=secret", expect=400)  # not indexed, not filterable
    api("GET", "/api/records/spaceship", expect=404)


def test_a_stale_write_is_a_conflict_not_a_loss(api):
    board = board_of(api)
    task = api(
        "POST", "/api/records/task", {"fields": {"board": board, "title": "One"}}, expect=201
    )
    api("PATCH", f"/api/records/task/{task['id']}", {"fields": {"title": "Two"}, "rev": 1})
    conflict = api(
        "PATCH",
        f"/api/records/task/{task['id']}",
        {"fields": {"title": "Three"}, "rev": 1},
        expect=409,
    )
    assert conflict["detail"]["current"]["fields"]["title"] == "Two"


def test_records_are_their_owners_alone(api):
    board = board_of(api)
    task = api(
        "POST", "/api/records/task", {"fields": {"board": board, "title": "Mine"}}, expect=201
    )
    guest = {"Authorization": f"Bearer {token_for(api.client, *GUEST)}"}
    api("GET", f"/api/records/task/{task['id']}", expect=404, as_=guest)
    api(
        "PATCH",
        f"/api/records/task/{task['id']}",
        {"fields": {"title": "Theirs"}},
        expect=404,
        as_=guest,
    )
    # Nor may a guest put a task on somebody else's board.
    api(
        "POST",
        "/api/records/task",
        {"fields": {"board": board, "title": "x"}},
        expect=400,
        as_=guest,
    )
    assert [b["fields"]["title"] for b in api("GET", "/api/records/board", as_=guest)] == [
        "guest's tasks"
    ]


def test_content_is_sealed_at_rest_and_lanes_are_not(api, config):
    board = board_of(api)
    api(
        "POST",
        "/api/records/task",
        {"fields": {"board": board, "title": "Buy a ring", "body": "the secret"}},
        expect=201,
    )
    with sqlite3.connect(config.db_path) as conn:
        rows = conn.execute("SELECT indexed, body FROM records WHERE model = 'task'").fetchall()
    raw = json.dumps(rows)
    assert "Buy a ring" not in raw and "the secret" not in raw
    assert '"lane": "todo"' in rows[0][0]


def test_a_sealed_record_moved_to_another_owner_does_not_open(api, config):
    board = board_of(api)
    task = api(
        "POST", "/api/records/task", {"fields": {"board": board, "title": "Mine"}}, expect=201
    )
    with sqlite3.connect(config.db_path) as conn:
        conn.execute("UPDATE records SET owner = 'guest' WHERE id = ?", (task["id"],))
    store = api.client.app.state.cloudmorrow.records
    with pytest.raises(SealError):
        store.get(Principal.person("guest"), "task", task["id"])


def test_the_gate():
    check(Principal.person("bram"), "read", "secret")
    with pytest.raises(Refused):
        check(Principal.assistant("bram"), "read", "secret")
    quill = Principal("quill", "bram", quill="tasks", models=frozenset({"task", "board"}))
    check(quill, "write", "task")
    with pytest.raises(Refused):
        check(quill, "read", "contact")
    with pytest.raises(Refused):
        check(Principal.person("bram"), "delete-everything", "task")


def test_datamodels_are_listed_with_who_uses_them(api):
    models = {m["id"]: m for m in api("GET", "/api/datamodels")}
    assert set(models) == {"board", "task"}
    assert models["task"]["used_by"] == ["tasks"] and models["task"]["foundation"]
    lane = next(f for f in models["task"]["fields"] if f["name"] == "lane")
    assert lane["labels"] == ["To Do", "Doing", "Done"] and lane["indexed"]


def test_without_the_quill_there_is_no_datamodel(client, auth):
    assert client.get("/api/records/task", headers=auth).status_code == 404
    assert client.get("/api/datamodels", headers=auth).json() == []


def test_store_rejects_unknown_fields_directly(tasks_quill):
    store = tasks_quill.app.state.cloudmorrow.records
    with pytest.raises(RecordError):
        store.create(Principal.person("bram"), "board", {"name": "x"})
