"""Pictures in the TUI: shown beside the editor, and put there from a file."""

from __future__ import annotations

from textual.widgets import Static

from cloudmorrow.tui.widgets.editor import LiveMarkdownEditor
from cloudmorrow.tui.widgets.picture import Picture, image_refs
from tests.tui_harness import PNG_1PX, settle, start

NOTE = "# rack\n\nBefore:\n![front](img/20260901-090000-aaaaaa-front.png)\n\nand after\n"


def test_image_refs_are_found_once_each_in_order():
    text = "![a](img/one.png) x ![b](img/two.jpg) ![again](img/one.png) ![web](https://x/y.png)"
    assert image_refs(text) == [("one.png", "a"), ("two.jpg", "b")]


async def open_rack(app, pilot):
    app.client.read = _read_rack
    screen = await start(app, pilot)
    pane = screen.query_one("#pane-notes")
    pane.open_note("rack.md")
    await settle(app, pilot)
    return screen, pane


async def _read_rack(path: str) -> dict:
    return {"path": path, "content": NOTE, "rev": "1-1", "size": len(NOTE), "modified": 0}


async def test_a_note_with_a_picture_shows_it_beside_the_text(app):
    async with app.run_test(size=(140, 34)) as pilot:
        screen, pane = await open_rack(app, pilot)
        panel = screen.query_one("#pane-notes").query_one(Picture)
        assert panel.display and panel.shown == "20260901-090000-aaaaaa-front.png"
        assert app.client.fetched == ["20260901-090000-aaaaaa-front.png"]
        assert "front" in screen.query_one("#pane-notes").query_one("#picture-caption", Static).visual.plain
        # Something is drawn under the caption: the picture, however the
        # terminal can draw it.
        assert panel.query(".picture-image")


async def test_a_note_without_pictures_keeps_the_panel_away(app):
    async with app.run_test(size=(140, 34)) as pilot:
        screen = await start(app, pilot)
        screen.query_one("#pane-notes").open_note("architecture.md")
        await settle(app, pilot)
        assert not screen.query_one("#pane-notes").query_one(Picture).display


async def test_a_picture_is_fetched_once(app):
    async with app.run_test(size=(140, 34)) as pilot:
        screen, pane = await open_rack(app, pilot)
        editor = screen.query_one(LiveMarkdownEditor)
        editor.cursor_row = 5
        await settle(app, pilot)
        editor.cursor_row = 3
        await settle(app, pilot)
        assert app.client.fetched == ["20260901-090000-aaaaaa-front.png"]


async def test_photo_uploads_a_file_and_writes_it_into_the_note(app, tmp_path):
    photo = tmp_path / "Rack Front.png"
    photo.write_bytes(PNG_1PX)
    async with app.run_test(size=(140, 34)) as pilot:
        screen = await start(app, pilot)
        pane = screen.query_one("#pane-notes")
        pane.open_note("architecture.md")
        await settle(app, pilot)
        editor = screen.query_one(LiveMarkdownEditor)
        editor.cursor_row, editor.cursor_col = 0, 0
        await pilot.click("#pane-notes #do-insert_image")
        await pilot.pause()
        await pilot.pause()
        await pilot.press(*str(photo), "enter")
        await settle(app, pilot)
        assert app.client.uploads == [("Rack Front.png", PNG_1PX)]
        assert editor.text.startswith("![Rack Front](img/20260917-120000-abc123-rack-front.png)\n")
        # And it is on screen straight away, without a round trip.
        assert screen.query_one("#pane-notes").query_one(Picture).display
        assert app.client.fetched == []
