"""The kit's board, driven with the mouse: clicking a card, and dragging one.

Tasks is the board these drive — the first Quill, with its screen and its
datamodels exactly as the server sends them — but the pane under test is the
generic one: nothing in it knows it is holding tasks. The claim the board
makes is that a card moves lane by being dragged there, so the drag is what
these press, move and release — not the API call underneath it.
"""

from __future__ import annotations

import pytest
from textual.widgets import Tab, Tabs

from cloudmorrow.tui.panes.kit_board import NEW_GROUP_TAB, BoardPane
from cloudmorrow.tui.screens.record_sheet import RecordSheet
from cloudmorrow.tui.widgets.kit import (
    Lane,
    RecordCard,
    days_left,
    how_long,
    neighbour_lane,
    subtask_progress,
)
from tests.tui_harness import settle, start


async def open_tasks(app, pilot):
    """Land on the Tasks tab with its board loaded."""
    screen = await start(app, pilot)
    await pilot.click("#nav-tasks")
    await settle(app, pilot)
    return screen, screen.query_one(BoardPane)


def titles(lane: Lane) -> list[str]:
    return [card.fields["title"] for card in lane.cards()]


async def drag(pilot, card: RecordCard, target: Lane, *, row: int | None = None) -> None:
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


def test_days_left_counts_down_to_the_sweep():
    """Going in four days and a bit: five left, not four."""
    import datetime as dt

    expires = (dt.datetime.now(tz=dt.UTC) + dt.timedelta(days=4, hours=2)).isoformat()
    assert days_left(expires) == 5


def test_a_record_past_its_sweep_has_no_days_left():
    import datetime as dt

    expires = (dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=2)).isoformat()
    assert days_left(expires) == 0


def test_a_record_nothing_will_sweep_has_no_clock():
    assert days_left(None) is None


@pytest.mark.parametrize(
    ("after", "said"), [("7d", "a week"), ("1d", "1 day"), ("12h", "12 hours"), ("soon", "soon")]
)
def test_an_expire_job_is_said_the_way_a_person_would(after, said):
    assert how_long(after) == said


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
    assert neighbour_lane(["todo", "doing", "done"], lane, delta) == expected


# -- the board on screen -----------------------------------------------------


async def test_the_lanes_are_the_enum_values_in_order(app):
    """To Do, Doing, Done: the lane field's values and labels, as declared."""
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_tasks(app, pilot)

        lanes = list(pane.query(Lane))
        assert [(lane.value, lane.label) for lane in lanes] == [
            ("todo", "To Do"),
            ("doing", "Doing"),
            ("done", "Done"),
        ]


async def test_the_lanes_are_filled_from_the_board(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_tasks(app, pilot)

        assert titles(pane.lane_widget("todo")) == ["Wire the rack", "Repaint"]
        assert titles(pane.lane_widget("doing")) == ["Swap the switch"]
        assert pane.lane_widget("done").cards() == []
        # Asked for the group on the strip, by its link field.
        assert ("task", {"board": "r_homelab"}) in app.client.record_calls


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
            "group-r_homelab",
            "group-r_errands",
            NEW_GROUP_TAB,
        ]
        assert [str(tab.label) for tab in tabs[:2]] == ["Home Lab", "Errands"]
        # And the board being shown is the one the strip highlights.
        assert strip.active == f"group-{pane.group}"


async def test_the_toolbar_is_named_after_the_datamodels(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen, _ = await open_tasks(app, pilot)
        labels = [str(button.label) for button in screen.query("#pane-tasks Toolbar Button")]
        assert labels == ["New task ^n", "New board ^b", "Rename board", "Delete board"]


async def test_a_first_board_is_there_for_somebody_with_none(app):
    """The server seeds one per person; the board stands on it."""
    app.client.record_store = {"board": [], "task": []}
    async with app.run_test(size=(120, 34)) as pilot:
        screen, pane = await open_tasks(app, pilot)
        assert [str(tab.label) for tab in screen.query_one("#board-nav", Tabs).query(Tab)] == [
            "bram's tasks",
            "＋",
        ]
        assert pane.group == app.client.record_store["board"][0]["id"]


async def test_clicking_a_board_tab_opens_that_board(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen, pane = await open_tasks(app, pilot)
        assert pane.lane_widget("todo").cards()

        await pilot.click("#group-r_errands")
        await settle(app, pilot)

        assert pane.group == "r_errands"
        assert app.client.record_calls[-1] == ("task", {"board": "r_errands"})
        # Errands is empty, so the lanes emptied with it.
        assert pane.lane_widget("todo").cards() == []
        assert screen.query_one("#board-nav", Tabs).active == "group-r_errands"


async def test_the_plus_tab_leaves_the_board_where_it_was(app):
    """＋ opens the prompt; it does not become the selected board."""
    async with app.run_test(size=(120, 34)) as pilot:
        screen, pane = await open_tasks(app, pilot)

        await pilot.click(f"#{NEW_GROUP_TAB}")
        # Not `settle`: the prompt is open, so its worker is still waiting.
        await pilot.pause()
        await pilot.pause()

        assert pane.group == "r_homelab"
        assert screen.query_one("#board-nav", Tabs).active == "group-r_homelab"

        await pilot.press("escape")
        await settle(app, pilot)
        assert pane.group == "r_homelab"


async def test_a_new_board_is_made_and_stood_on(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen, pane = await open_tasks(app, pilot)

        await pilot.click("#do-new_group")
        await pilot.pause()
        await pilot.pause()
        for key in "Garden":
            await pilot.press(key)
        await pilot.press("enter")
        await settle(app, pilot)

        made = app.client.record_store["board"][-1]
        assert made["fields"]["title"] == "Garden"
        assert pane.group == made["id"]
        assert screen.query_one("#board-nav", Tabs).active == f"group-{made['id']}"


async def test_deleting_a_board_takes_its_tasks(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_tasks(app, pilot)

        await pilot.click("#do-delete_group")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("y")
        await settle(app, pilot)

        assert [row["id"] for row in app.client.record_store["board"]] == ["r_errands"]
        assert app.client.record_store["task"] == []
        assert pane.group == "r_errands"


# -- writing a task ----------------------------------------------------------


async def test_ctrl_s_saves_a_new_task_from_the_body(app):
    """The body swallows ctrl+s for its own save; the sheet has to hear it.

    Where you are when you have finished writing a task is the body, so a save
    shortcut that only works in the title is a save shortcut that does not.
    """
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_tasks(app, pilot)

        await pilot.click("#do-new_record")
        await pilot.pause()
        await pilot.pause()
        sheet = app.screen
        assert isinstance(sheet, RecordSheet)
        # The title is where you start.
        for key in "Rack":
            await pilot.press(key)
        sheet.query_one("#field-body").focus()
        await pilot.pause()
        for key in "wire":
            await pilot.press(key)
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()
        # Checked before settling: a sheet that is still open holds the worker
        # open too, and this would hang rather than say what went wrong.
        assert not isinstance(app.screen, RecordSheet), "ctrl+s in the body did not save"
        await settle(app, pilot)

        # On this board, in the first lane, at the end of it.
        assert titles(pane.lane_widget("todo")) == ["Wire the rack", "Repaint", "Rack"]
        made = app.client.record_store["task"][-1]["fields"]
        assert (made["body"], made["board"], made["lane"]) == ("wire", "r_homelab", "todo")


# -- dragging ----------------------------------------------------------------


async def test_dragging_a_card_moves_it_to_that_lane(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_tasks(app, pilot)
        card = pane.lane_widget("todo").cards()[0]

        await drag(pilot, card, pane.lane_widget("doing"))
        await settle(app, pilot)

        assert app.client.moves and app.client.moves[0][:2] == ("r_task1", {"lane": "doing"})
        # And the board redrew: the card is in Doing now, and out of To Do.
        assert "Wire the rack" in titles(pane.lane_widget("doing"))
        assert titles(pane.lane_widget("todo")) == ["Repaint"]


async def test_dragging_into_done_is_what_starts_the_week(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_tasks(app, pilot)
        card = pane.lane_widget("doing").cards()[0]

        await drag(pilot, card, pane.lane_widget("done"))
        await settle(app, pilot)

        assert app.client.moves[0][:2] == ("r_task3", {"lane": "done"})
        # The server stamped it, the expire job put it on a clock, and the
        # card and the lane both say so.
        card = pane.lane_widget("done").cards()[0]
        assert "7d left" in card.render_card().plain
        head = pane.query_one("#lane-head-done").visual.plain
        assert "kept a week" in head


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
        # The record sheet is what opened, with the card's own text in it.
        modal = app.screen
        assert isinstance(modal, RecordSheet)
        assert modal.query_one("#field-title").value == "Wire the rack"

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

        assert app.client.moves[0][:2] == ("r_task1", {"lane": "doing"})
        # Still holding it, so `]` again carries on to Done.
        assert app.screen.focused.record["id"] == "r_task1"


async def test_space_sends_a_card_to_the_done_lane_and_back(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_tasks(app, pilot)
        pane.lane_widget("doing").cards()[0].focus()
        await pilot.pause()

        await pilot.press("space")
        await settle(app, pilot)
        assert titles(pane.lane_widget("done")) == ["Swap the switch"]

        await pilot.press("space")
        await settle(app, pilot)
        assert titles(pane.lane_widget("done")) == []
        assert titles(pane.lane_widget("todo"))[-1] == "Swap the switch"


async def test_delete_takes_the_focused_card(app):
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_tasks(app, pilot)
        pane.lane_widget("todo").cards()[1].focus()
        await pilot.pause()

        await pilot.press("delete")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("y")
        await settle(app, pilot)

        assert titles(pane.lane_widget("todo")) == ["Wire the rack"]


async def test_where_a_card_is_dropped_decides_its_place_in_the_lane(app):
    """Dropped above the first card's middle, it goes in front of it."""
    async with app.run_test(size=(120, 34)) as pilot:
        _, pane = await open_tasks(app, pilot)
        doing = pane.lane_widget("doing")
        top = doing.cards()[0].region.y
        card = pane.lane_widget("todo").cards()[0]

        await drag(pilot, card, doing, row=top)
        await settle(app, pilot)

        assert app.client.moves[0] == ("r_task1", {"lane": "doing"}, 0)
        assert titles(doing) == ["Wire the rack", "Swap the switch"]
