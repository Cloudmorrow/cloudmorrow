"""Answering a dialog with the keyboard.

Tab moves focus everywhere in Textual, and nowhere is that less discoverable
than in a box with two buttons in it — so the arrows move between them here,
and enter presses the one you are on. What these check is that the arrows still
belong to the focused widget when it has a use for them: a cursor in an input
still moves, a selection in a list still moves.
"""

from __future__ import annotations

from textual.widgets import Button, Input

from cloudmorrow.tui.screens.modals import ConfirmModal, ConflictModal, PromptModal
from tests.tui_harness import settle, start


async def push(app, pilot, screen):
    """Open a dialog and hand back what it dismisses with."""
    answers: list = []
    app.push_screen(screen, answers.append)
    await settle(app, pilot)
    return answers


async def test_the_arrows_move_between_a_confirms_buttons(app):
    async with app.run_test(size=(80, 24)) as pilot:
        await start(app, pilot)
        answers = await push(app, pilot, ConfirmModal("Delete the note?"))
        dialog = app.screen

        assert app.screen.focused is dialog.query_one("#confirm", Button)
        await pilot.press("right")
        assert app.screen.focused is dialog.query_one("#cancel", Button)

        await pilot.press("enter")
        await settle(app, pilot)
        assert answers == [False]


async def test_enter_on_the_first_button_answers_yes(app):
    async with app.run_test(size=(80, 24)) as pilot:
        await start(app, pilot)
        answers = await push(app, pilot, ConfirmModal("Delete the note?"))

        await pilot.press("enter")
        await settle(app, pilot)
        assert answers == [True]


async def test_three_buttons_step_one_at_a_time(app):
    async with app.run_test(size=(80, 24)) as pilot:
        await start(app, pilot)
        answers = await push(app, pilot, ConflictModal("architecture.md"))
        dialog = app.screen

        assert app.screen.focused is dialog.query_one("#overwrite", Button)
        await pilot.press("down")
        assert app.screen.focused is dialog.query_one("#reload", Button)
        await pilot.press("down")
        assert app.screen.focused is dialog.query_one("#cancel", Button)
        await pilot.press("up")
        assert app.screen.focused is dialog.query_one("#reload", Button)

        await pilot.press("enter")
        await settle(app, pilot)
        assert answers == ["reload"]


async def test_an_input_keeps_the_arrows_that_mean_something_to_it(app):
    """Left and right are the cursor's while it is typing, not the dialog's."""
    async with app.run_test(size=(80, 24)) as pilot:
        await start(app, pilot)
        await push(app, pilot, PromptModal("New note", value="architecture"))
        field = app.screen.query_one(Input)

        assert app.screen.focused is field
        assert field.cursor_position == len("architecture")
        await pilot.press("left", "left")
        assert app.screen.focused is field
        assert field.cursor_position == len("architecture") - 2
