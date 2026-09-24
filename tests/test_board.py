"""The board, driven with the mouse: clicking a card, and dragging one.

The claim the Tasks tab makes is that a card moves lane by being dragged
there, so the drag is what these press, move and release — not the API call
underneath it.
"""

from __future__ import annotations

import pytest
from textual.widgets import Tab, Tabs

from cloudmorrow.tui.panes.tasks import NEW_BOARD_TAB, TasksPane
from cloudmorrow.tui.screens.modals import TaskModal
from cloudmorrow.tui.widgets.board import (
    Lane,
    TaskCard,
    days_left,
    neighbour_lane,
    subtask_progress,
)
from tests.tui_harness import settle, start


async def open_tasks(app, pilot):
    """Land on the Tasks tab with its board loaded."""
    screen = await start(app, pilot)
    await pilot.click("#tab-tasks")
    await settle(app, pilot)
    return screen, screen.query_one(TasksPane)


async def drag(pilot, card: TaskCard, target: Lane, *, row: int | None = None) -> None:
    """Press on a card, move the pointer into a lane, and let go there."""
    from textual import events

    await pilot.mouse_down(card)
    where = target.region
    x = where.x + where.width // 2
    y = where.y + 2 if row is None else row
    # Pilot has no mouse_move, so the drag itself is posted the way the
    # terminal would send it — held button, new position.
    card.post_message(
        events.MouseMove(
            widget=card,
            x=0,
            y=0,
            delta_x=0,
            delta_y=0,
            button=1,
            shift=False,
            meta=False,
            ctrl=False,
            screen_x=x,
            screen_y=y,
        )
    )
    await pilot.pause()
    card.post_message(
        events.MouseUp(
            widget=card,
            x=0,
            y=0,
            delta_x=0,
            delta_y=0,
            button=1,
            shift=False,
            meta=False,
            ctrl=False,
            screen_x=x,
            screen_y=y,
        )
    )
    await pilot.pause()


# -- what a card says --------------------------------------------------------


def test_subtasks_are_the_checkboxes_in_the_body():
    assert subtask_progress("- [ ] one\n- [x] two\n- [X] three\n") == (2, 3)


def test_prose_is_not_a_subtask():
    assert subtask_progress("Just a paragraph.\n\n- a bullet\n") == (0, 0)


def test_a_task_with_no_body_has_no_subtasks():
    assert subtask_progress("") == (0, 0)


def test_days_left_counts_down_from_a_week():
    """Finished two days ago, kept seven: five left, not four."""
    import datetime as dt

    done = (dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=2)).isoformat()
    assert days_left(done) == 5


def test_a_task_past_its_week_has_no_days_left():
    import datetime as dt

    done = (dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=9)).isoformat()
    assert days_left(done) == 0


def test_a_task_that_is_not_done_has_no_clock():
    assert days_left(None) is None


@pytest.mark.parametrize(
    ("lane", "delta", "expected"),
    [
        ("todo", 1, "doing"),
        ("doing", 1, "done"),
        ("done", 1, "done"),  # clamped: there is nothing past Done
        ("todo", -1, "todo"),  # and nothing before ToDo
        ("doing", -1, "todo"),
    ],
)
def test_the_board_ends_where_it_ends(lane, delta, expected):
    assert neighbour_lane(lane, delta) == expected


# -- the board on screen -----------------------------------------------------


async def test_the_lanes_are_filled_from_the_board(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_tasks(app, pilot)

        assert [card.record["title"] for card in pane.lane_widget("todo").cards()] == [
            "Wire the rack",
            "Repaint",
        ]
        assert [card.record["title"] for card in pane.lane_widget("doing").cards()] == [
            "Swap the switch"
        ]
        assert pane.lane_widget("done").cards() == []


async def test_a_card_shows_its_subtask_count(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_tasks(app, pilot)
        card = pane.lane_widget("todo").cards()[0]

        assert "1/2 subtasks" in card.render_card().plain


async def test_the_strip_shows_the_boards_and_a_way_to_add_one(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen, pane = await open_tasks(app, pilot)
        strip = screen.query_one("#board-nav", Tabs)

        tabs = list(strip.query(Tab))
        assert [tab.id for tab in tabs] == [
            "board-home-lab",
            "board-errands",
            NEW_BOARD_TAB,
        ]
        assert [str(tab.label) for tab in tabs[:2]] == ["Home Lab", "Errands"]
        # And the board being shown is the one the strip highlights.
        assert strip.active == f"board-{pane.board}"


async def test_clicking_a_board_tab_opens_that_board(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen, pane = await open_tasks(app, pilot)
        assert pane.lane_widget("todo").cards()

        await pilot.click("#board-errands")
        await settle(app, pilot)

        assert pane.board == "errands"
        assert app.client.asked_for[-1] == "errands"
        # Errands is empty, so the lanes emptied with it.
        assert pane.lane_widget("todo").cards() == []
        assert screen.query_one("#board-nav", Tabs).active == "board-errands"


async def test_the_plus_tab_leaves_the_board_where_it_was(app):
    """＋ opens the prompt; it does not become the selected board."""
    async with app.run_test(size=(120, 34)) as pilot:
        screen, pane = await open_tasks(app, pilot)

        await pilot.click(f"#{NEW_BOARD_TAB}")
        # Not `settle`: the prompt is open, so its worker is still waiting.
        await pilot.pause()
        await pilot.pause()

        assert pane.board == "home-lab"
        assert screen.query_one("#board-nav", Tabs).active == "board-home-lab"

        await pilot.press("escape")
        await settle(app, pilot)
        assert pane.board == "home-lab"


# -- writing a task ----------------------------------------------------------


async def test_ctrl_s_saves_a_new_task_from_the_body(app):
    """The body swallows ctrl+s for its own save; the modal has to hear it.

    Where you are when you have finished writing a task is the body, so a save
    shortcut that only works in the title is a save shortcut that does not.
    """
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_tasks(app, pilot)

        await pilot.click("#do-new_task")
        await pilot.pause()
        await pilot.pause()
        for key in "Rack":
            await pilot.press(key)
        # Enter moves to the body rather than saving half a task.
        await pilot.press("enter")
        await pilot.pause()
        for key in "wire":
            await pilot.press(key)
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()
        # Checked before settling: a modal that is still open holds the worker
        # open too, and this would hang rather than say what went wrong.
        assert not isinstance(app.screen, TaskModal), "ctrl+s in the body did not save"
        await settle(app, pilot)

        assert [card.record["title"] for card in pane.lane_widget("todo").cards()] == [
            "Wire the rack",
            "Repaint",
            "Rack",
        ]
        assert app.client.board_tasks[-1]["body"] == "wire"


# -- dragging ----------------------------------------------------------------


async def test_dragging_a_card_moves_it_to_that_lane(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_tasks(app, pilot)
        card = pane.lane_widget("todo").cards()[0]

        await drag(pilot, card, pane.lane_widget("doing"))
        await settle(app, pilot)

        assert app.client.moves and app.client.moves[0][:2] == (1, "doing")
        # And the board redrew: the card is in Doing now, and out of ToDo.
        assert "Wire the rack" in [
            c.record["title"] for c in pane.lane_widget("doing").cards()
        ]
        assert [c.record["title"] for c in pane.lane_widget("todo").cards()] == ["Repaint"]


async def test_dragging_into_done_is_what_starts_the_week(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_tasks(app, pilot)
        card = pane.lane_widget("doing").cards()[0]

        await drag(pilot, card, pane.lane_widget("done"))
        await settle(app, pilot)

        assert app.client.moves[0][:2] == (3, "done")


async def test_a_drag_that_lands_off_the_board_moves_nothing(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_tasks(app, pilot)
        card = pane.lane_widget("todo").cards()[0]
        from textual import events

        await pilot.mouse_down(card)
        for event_type in (events.MouseMove, events.MouseUp):
            card.post_message(
                event_type(
                    widget=card,
                    x=0,
                    y=0,
                    delta_x=0,
                    delta_y=0,
                    button=1,
                    shift=False,
                    meta=False,
                    ctrl=False,
                    # The top bar: on screen, but not a lane.
                    screen_x=4,
                    screen_y=0,
                )
            )
            await pilot.pause()
        await settle(app, pilot)

        assert app.client.moves == []


async def test_a_click_opens_a_card_rather_than_moving_it(app):
    """Press and release in one place is a click, however twitchy the hand."""
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_tasks(app, pilot)
        card = pane.lane_widget("todo").cards()[0]

        await pilot.click(card)
        # Not settle(): the worker that opened the editor is waiting on it, and
        # waiting for that worker here would be waiting for ourselves.
        await pilot.pause()
        await pilot.pause()

        assert app.client.moves == []
        # The task editor is what opened, with the card's own text in it.
        modal = app.screen
        assert modal.query("#task-modal")
        assert modal.query_one("#task-title").value == "Wire the rack"

        modal.action_cancel()
        await settle(app, pilot)


async def test_the_keyboard_moves_a_card_the_same_way(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_tasks(app, pilot)
        card = pane.lane_widget("todo").cards()[0]
        card.focus()
        await pilot.pause()

        await pilot.press("right_square_bracket")
        await settle(app, pilot)

        assert app.client.moves[0][:2] == (1, "doing")


async def test_where_a_card_is_dropped_decides_its_place_in_the_lane(app):
    """Dropped above the first card's middle, it goes in front of it."""
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_tasks(app, pilot)
        doing = pane.lane_widget("doing")
        top = doing.cards()[0].region.y
        card = pane.lane_widget("todo").cards()[0]

        await drag(pilot, card, doing, row=top)
        await settle(app, pilot)

        assert app.client.moves[0] == (1, "doing", 0)
