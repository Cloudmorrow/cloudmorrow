"""Sweeping the mouse over text copies it, and the app says so."""

from __future__ import annotations

from textual.widgets import Static

from cloudmorrow.tui.widgets.editor import LiveMarkdownEditor
from tests.tui_harness import said, settle, start


async def sweep(pilot, selector: str, start: tuple[int, int], end: tuple[int, int]) -> None:
    """Press at *start*, drag to *end*, release — all relative to the widget."""
    await pilot.mouse_down(selector, offset=start)
    await pilot.hover(selector, offset=end)
    await pilot.mouse_up(selector, offset=end)
    await pilot.pause()


async def test_selecting_text_with_the_mouse_copies_it(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        await pilot.click("#nav-files")
        await settle(app, pilot)
        await pilot.click("#files-tab-local-backups")
        await settle(app, pilot)
        placeholder = screen.query_one("#backups-placeholder", Static)
        assert placeholder.text_selection is None
        # Offsets are on the widget, whose padding is 2 3, and the cell under
        # the pointer when the button comes up is part of the selection.
        await sweep(pilot, "#backups-placeholder", (3, 2), (15, 2))
        assert screen.get_selected_text() == "Local backups"
        assert app._clipboard == "Local backups"
        # And the status bar says so — nothing else needs pressing, and
        # nothing pops up: a notification is what a machine sends.
        assert "Copied" in said(screen)
        assert not app._notifications


async def test_selecting_in_the_editor_copies_the_source(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        editor = screen.query_one(LiveMarkdownEditor)
        editor.load_text("first line\nsecond line\nthird line")
        await pilot.pause()
        # Offsets are on the widget, whose padding is 1 2: column 6 of the
        # first line is at (8, 1). Plain lines render as they read, and the
        # cell under the pointer at the end is included.
        await sweep(pilot, LiveMarkdownEditor, (8, 1), (7, 2))
        assert app._clipboard == "line\nsecond"
        # The sweep is painted where it lands, not only remembered.
        assert editor.text_selection is not None


async def test_a_click_alone_copies_nothing(app):
    async with app.run_test(size=(120, 34)) as pilot:
        await start(app, pilot)
        await pilot.click("#nav-files")
        await settle(app, pilot)
        await pilot.click("#files-tab-local-backups")
        await settle(app, pilot)
        await sweep(pilot, "#backups-placeholder", (3, 2), (3, 2))
        assert app._clipboard == ""
        assert "Copied" not in said(app.screen)
