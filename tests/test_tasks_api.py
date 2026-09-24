"""The boards API: who can see a board, and what a move does."""

from __future__ import annotations

import pytest

from tests.conftest import GUEST, token_for


@pytest.fixture()
def board(client, auth) -> str:
    created = client.post("/api/boards", json={"title": "Home Lab"}, headers=auth)
    assert created.status_code == 201, created.text
    return created.json()["slug"]


def add(client, auth, board: str, title: str, body: str = "") -> dict:
    created = client.post(
        f"/api/boards/{board}/tasks", json={"title": title, "body": body}, headers=auth
    )
    assert created.status_code == 201, created.text
    return created.json()


def test_a_board_is_created_and_listed(client, auth):
    client.post("/api/boards", json={"title": "Home Lab"}, headers=auth)
    listed = client.get("/api/boards", headers=auth)
    assert [board["title"] for board in listed.json()] == ["Home Lab"]


def test_listing_boards_before_you_have_any_gives_you_one(client, auth):
    """A new account opens Tasks onto a board, not onto nothing."""
    listed = client.get("/api/boards", headers=auth).json()
    assert len(listed) == 1
    # And it is an ordinary board: its tasks are there to be read and written.
    slug = listed[0]["slug"]
    assert client.get(f"/api/boards/{slug}/tasks", headers=auth).json() == []
    add(client, auth, slug, "Wire the rack")
    tasks = client.get(f"/api/boards/{slug}/tasks", headers=auth).json()
    assert [row["title"] for row in tasks] == ["Wire the rack"]


def test_the_board_you_start_with_can_be_renamed(client, auth):
    slug = client.get("/api/boards", headers=auth).json()[0]["slug"]
    renamed = client.patch(f"/api/boards/{slug}", json={"title": "Home Lab"}, headers=auth)
    assert renamed.status_code == 200, renamed.text
    assert [board["title"] for board in client.get("/api/boards", headers=auth).json()] == [
        "Home Lab"
    ]


def test_two_boards_cannot_share_an_id(client, auth):
    client.post("/api/boards", json={"title": "Home Lab"}, headers=auth)
    again = client.post("/api/boards", json={"title": "home lab"}, headers=auth)
    assert again.status_code == 409


def test_a_board_needs_a_title(client, auth):
    assert client.post("/api/boards", json={"title": "  "}, headers=auth).status_code == 400


def test_tasks_start_in_todo_and_come_back_in_order(client, auth, board):
    add(client, auth, board, "first")
    add(client, auth, board, "second")
    tasks = client.get(f"/api/boards/{board}/tasks", headers=auth).json()
    assert [(t["title"], t["lane"], t["position"]) for t in tasks] == [
        ("first", "todo", 0),
        ("second", "todo", 1),
    ]


def test_a_task_moves_between_lanes(client, auth, board):
    task = add(client, auth, board, "Wire the rack")
    moved = client.post(
        f"/api/boards/{board}/tasks/{task['id']}/move", json={"lane": "doing"}, headers=auth
    )
    assert moved.status_code == 200
    assert moved.json()["lane"] == "doing"
    assert moved.json()["done_at"] is None


def test_reaching_done_starts_the_week(client, auth, board):
    task = add(client, auth, board, "Wire the rack")
    moved = client.post(
        f"/api/boards/{board}/tasks/{task['id']}/move", json={"lane": "done"}, headers=auth
    )
    assert moved.json()["done_at"] is not None


def test_there_is_no_fourth_lane(client, auth, board):
    task = add(client, auth, board, "Wire the rack")
    refused = client.post(
        f"/api/boards/{board}/tasks/{task['id']}/move", json={"lane": "someday"}, headers=auth
    )
    assert refused.status_code == 400


def test_a_task_is_edited_in_place(client, auth, board):
    task = add(client, auth, board, "Wire the rack")
    edited = client.patch(
        f"/api/boards/{board}/tasks/{task['id']}",
        json={"body": "- [ ] label the cables"},
        headers=auth,
    )
    assert edited.json()["body"] == "- [ ] label the cables"
    # The title was not named, so it did not change.
    assert edited.json()["title"] == "Wire the rack"


def test_a_deleted_task_is_gone(client, auth, board):
    task = add(client, auth, board, "Wire the rack")
    assert (
        client.delete(f"/api/boards/{board}/tasks/{task['id']}", headers=auth).status_code
        == 204
    )
    assert client.get(f"/api/boards/{board}/tasks", headers=auth).json() == []


def test_deleting_a_board_takes_its_tasks(client, auth, board):
    add(client, auth, board, "Wire the rack")
    assert client.delete(f"/api/boards/{board}", headers=auth).status_code == 204
    assert client.get(f"/api/boards/{board}/tasks", headers=auth).status_code == 404


def test_a_board_you_do_not_own_does_not_exist(client, auth, board):
    add(client, auth, board, "Wire the rack")
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}

    assert client.get(f"/api/boards/{board}/tasks", headers=guest).status_code == 404
    # The guest sees their own starting board, and nothing of this one.
    assert [row["slug"] for row in client.get("/api/boards", headers=guest).json()] == [
        "guest-tasks"
    ]


def test_a_task_reached_through_the_wrong_board_does_not_exist(client, auth, board):
    """The URL says which board; a task that is not on it is not there."""
    task = add(client, auth, board, "Wire the rack")
    other = client.post("/api/boards", json={"title": "Other"}, headers=auth).json()["slug"]

    reached = client.patch(
        f"/api/boards/{other}/tasks/{task['id']}", json={"title": "hijacked"}, headers=auth
    )
    assert reached.status_code == 404


def test_boards_need_a_signed_in_user(client):
    assert client.get("/api/boards").status_code == 401
