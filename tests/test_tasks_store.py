"""Boards, lanes, and the week a finished task has left.

The store, on its own: the API is tested where it lives, and the rules about
what a lane means belong here.
"""

from __future__ import annotations

import datetime as dt

import pytest

from cloudmorrow.server.tasks import (
    DOING,
    DONE,
    DONE_TTL_DAYS,
    TODO,
    BoardExistsError,
    InvalidLaneError,
    TaskStore,
    UnknownBoardError,
    UnknownTaskError,
)

OWNER = "bram"


@pytest.fixture()
def store(tmp_path) -> TaskStore:
    return TaskStore(tmp_path / "cloudmorrow.db")


@pytest.fixture()
def board(store) -> str:
    return store.create_board(OWNER, "Home Lab").slug


def stamp(days_ago: float) -> str:
    moment = dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=days_ago)
    return moment.isoformat(timespec="seconds")


# -- boards ------------------------------------------------------------------


def test_a_board_gets_a_slug_from_its_title(store):
    assert store.create_board(OWNER, "Home Lab").slug == "home-lab"


def test_you_start_with_a_board_of_your_own(store):
    """There is never nothing: the first listing seeds the board you get."""
    assert [(board.slug, board.title) for board in store.boards(OWNER)] == [
        ("bram-tasks", "bram's tasks")
    ]


def test_the_board_you_start_with_is_seeded_once(store):
    first = store.boards(OWNER)
    store.create_task(OWNER, first[0].slug, "Wire the rack")
    again = store.boards(OWNER)
    assert [board.slug for board in again] == ["bram-tasks"]
    assert [task.title for task in store.tasks(OWNER, "bram-tasks")] == ["Wire the rack"]


def test_the_board_you_start_with_renames_like_any_other(store):
    store.boards(OWNER)
    renamed = store.rename_board(OWNER, "bram-tasks", "Home Lab")
    assert (renamed.slug, renamed.title) == ("bram-tasks", "Home Lab")
    # And renaming it does not make a second one appear beside it.
    assert [board.title for board in store.boards(OWNER)] == ["Home Lab"]


def test_a_board_you_made_yourself_is_not_joined_by_a_default(store):
    store.create_board(OWNER, "Home Lab")
    assert [board.slug for board in store.boards(OWNER)] == ["home-lab"]


def test_deleting_your_last_board_gets_you_another(store):
    """A board strip with nothing in it is not a state worth having."""
    store.create_board(OWNER, "Home Lab")
    store.delete_board(OWNER, "home-lab")
    assert [board.slug for board in store.boards(OWNER)] == ["bram-tasks"]


def test_two_boards_cannot_share_an_id(store):
    store.create_board(OWNER, "Home Lab")
    with pytest.raises(BoardExistsError):
        store.create_board(OWNER, "home lab")


def test_boards_are_per_owner(store):
    store.create_board(OWNER, "Home Lab")
    store.create_board("guest", "Home Lab")
    assert [board.slug for board in store.boards("guest")] == ["home-lab"]


def test_renaming_keeps_the_id_a_board_is_known_by(store, board):
    renamed = store.rename_board(OWNER, board, "The Lab")
    assert (renamed.slug, renamed.title) == ("home-lab", "The Lab")


def test_deleting_a_board_takes_its_tasks_with_it(store, board):
    store.create_task(OWNER, board, "Wire the rack")
    store.delete_board(OWNER, board)
    with pytest.raises(UnknownBoardError):
        store.require_board(OWNER, board)
    assert store.tasks(OWNER, board) == []


def test_a_task_needs_a_board_that_exists(store):
    with pytest.raises(UnknownBoardError):
        store.create_task(OWNER, "nothing-here", "Orphan")


# -- lanes -------------------------------------------------------------------


def test_new_work_starts_in_todo(store, board):
    assert store.create_task(OWNER, board, "Wire the rack").lane == TODO


def test_tasks_stack_in_the_order_they_arrive(store, board):
    for title in ("first", "second", "third"):
        store.create_task(OWNER, board, title)
    assert [task.position for task in store.tasks(OWNER, board)] == [0, 1, 2]


def test_there_is_no_fourth_lane(store, board):
    task = store.create_task(OWNER, board, "Wire the rack")
    with pytest.raises(InvalidLaneError):
        store.move_task(OWNER, task.id, "someday")


def test_moving_renumbers_both_lanes(store, board):
    first = store.create_task(OWNER, board, "first")
    second = store.create_task(OWNER, board, "second")
    third = store.create_task(OWNER, board, "third")

    store.move_task(OWNER, first.id, DOING)

    lanes = {task.id: (task.lane, task.position) for task in store.tasks(OWNER, board)}
    assert lanes[first.id] == (DOING, 0)
    # The hole the move left in ToDo closed up behind it.
    assert lanes[second.id] == (TODO, 0)
    assert lanes[third.id] == (TODO, 1)


def test_a_task_can_be_dropped_between_two_others(store, board):
    for title in ("first", "second", "third"):
        store.create_task(OWNER, board, title)
    last = store.tasks(OWNER, board)[-1]

    store.move_task(OWNER, last.id, TODO, index=0)

    assert [task.title for task in store.tasks(OWNER, board)] == [
        "third",
        "first",
        "second",
    ]


def test_dropping_past_the_end_lands_at_the_end(store, board):
    first = store.create_task(OWNER, board, "first")
    store.create_task(OWNER, board, "second")

    store.move_task(OWNER, first.id, TODO, index=99)

    assert [task.title for task in store.tasks(OWNER, board)] == ["second", "first"]


# -- the week a finished task has left ---------------------------------------


def test_reaching_done_starts_the_clock(store, board):
    task = store.create_task(OWNER, board, "Wire the rack")
    assert task.done_at is None
    assert store.move_task(OWNER, task.id, DONE).done_at is not None


def test_coming_back_out_of_done_stops_it(store, board):
    task = store.create_task(OWNER, board, "Wire the rack")
    store.move_task(OWNER, task.id, DONE)
    assert store.move_task(OWNER, task.id, DOING).done_at is None


def test_moving_within_done_does_not_restart_the_week(store, board):
    task = store.create_task(OWNER, board, "Wire the rack")
    store.move_task(OWNER, task.id, DONE)
    was = store.require_task(OWNER, task.id).done_at
    assert store.move_task(OWNER, task.id, DONE, index=0).done_at == was


def test_a_task_done_for_a_week_is_gone(store, board):
    task = store.create_task(OWNER, board, "Wire the rack")
    store.move_task(OWNER, task.id, DONE)
    _age(store, task.id, DONE_TTL_DAYS + 0.5)

    assert store.tasks(OWNER, board) == []
    with pytest.raises(UnknownTaskError):
        store.require_task(OWNER, task.id)


def test_a_task_done_yesterday_stays(store, board):
    task = store.create_task(OWNER, board, "Wire the rack")
    store.move_task(OWNER, task.id, DONE)
    _age(store, task.id, 1)

    assert [t.id for t in store.tasks(OWNER, board)] == [task.id]


def test_an_old_task_that_is_not_done_is_left_alone(store, board):
    """Something sitting in ToDo for a month is a reproach, not rubbish."""
    task = store.create_task(OWNER, board, "Wire the rack")
    _age(store, task.id, 90)

    assert [t.id for t in store.tasks(OWNER, board)] == [task.id]


def _age(store: TaskStore, task_id: int, days: float) -> None:
    """Backdate a task's done_at, so the sweep sees an old one."""
    from cloudmorrow.server.db import connect

    with connect(store.db_path) as conn:
        conn.execute(
            "UPDATE tasks SET done_at = ? WHERE id = ?", (stamp(days), task_id)
        )


# -- the text ----------------------------------------------------------------


def test_the_body_is_kept_as_written(store, board):
    body = "Rack it, then:\n\n- [ ] label the cables\n- [x] buy the shelf\n"
    task = store.create_task(OWNER, board, "Wire the rack", body=body)
    assert store.require_task(OWNER, task.id).body == body


def test_a_task_needs_a_title(store, board):
    with pytest.raises(ValueError):
        store.create_task(OWNER, board, "   ")
    task = store.create_task(OWNER, board, "Wire the rack")
    with pytest.raises(ValueError):
        store.edit_task(OWNER, task.id, title="  ")


def test_editing_leaves_what_was_not_named(store, board):
    task = store.create_task(OWNER, board, "Wire the rack", body="the detail")
    edited = store.edit_task(OWNER, task.id, title="Wire the whole rack")
    assert (edited.title, edited.body) == ("Wire the whole rack", "the detail")


def test_one_owner_cannot_reach_anothers_task(store, board):
    task = store.create_task(OWNER, board, "Wire the rack")
    assert store.get_task("guest", task.id) is None
    with pytest.raises(UnknownTaskError):
        store.delete_task("guest", task.id)
