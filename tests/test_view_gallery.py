"""`gallery`: records as tiles with their pictures and stars — what a photo library draws."""

from __future__ import annotations

import pytest

from cloudmorrow.quill import ui
from cloudmorrow.quill.text import render, stars_text
from cloudmorrow.quill.ui import TreeError
from cloudmorrow.tui.widgets.view_nodes import GalleryNode
from tests.test_kit_view_tui import fleet, open_garage, vans  # noqa: F401 - the fixture
from tests.tui_harness import settle

PHOTO = {"model": "file", "id": "f1", "rev": 1, "fields": {"name": "sunset.jpg", "where": "Photos", "stars": 3}}
CLIP = {"model": "file", "id": "f2", "rev": 1, "fields": {"name": "waves.mp4", "length": "0:12", "stars": 0}}


def test_a_gallery_is_checked_like_the_rest():
    tree = ui.gallery([PHOTO, CLIP], title="name", subtitle="where", badge="length", stars="stars", rate="rate")
    assert ui.check(tree, actions={"rate"})["ui"] == "gallery"
    with pytest.raises(TreeError, match="does not declare"):
        ui.check(tree, actions={"something-else"})
    with pytest.raises(TreeError, match="which field holds the stars"):
        ui.check(ui.gallery([PHOTO], title="name", rate="rate"))
    with pytest.raises(TreeError, match="does not declare"):
        ui.check(ui.gallery([PHOTO], title="name", actions=["edit"]), actions={"rate"})


def test_a_gallery_as_text_says_each_tile_with_its_stars():
    text = render(ui.gallery([PHOTO, CLIP], title="name", subtitle="where", badge="length", stars="stars"))
    assert "▣ ★★★☆☆  sunset.jpg — Photos" in text
    assert "▣ ☆☆☆☆☆  waves.mp4 [0:12]" in text
    assert render(ui.gallery([], title="name", empty="No pictures yet.")).strip() == "(No pictures yet.)"
    assert stars_text(9) == "★★★★★" and stars_text("x") == "☆☆☆☆☆"


async def test_in_the_terminal_the_number_keys_rate_the_row_you_are_on(fleet):  # noqa: F811
    app = fleet
    async with app.run_test(size=(120, 50)) as pilot:
        pane = await open_garage(app, pilot)
        van = vans(app)[0]
        van["fields"]["stars"] = 2
        pane.view_tree = ui.check(
            ui.gallery([van], title="name", subtitle="registration", stars="stars", rate="log-service")
        )
        await pane.draw()
        await settle(app, pilot)
        gallery = pane.query_one(GalleryNode)
        assert "★★☆☆☆" in str(gallery.table.get_row_at(0)[0])
        pressed: list[dict] = []
        pane.act_on = pressed.append
        gallery.table.focus()
        await pilot.press("4")
        await pilot.pause()
        assert pressed and pressed[0]["action"] == "log-service" and pressed[0]["args"] == {"stars": 4}
        assert pressed[0]["record"]["id"] == van["id"]


def test_a_split_and_the_current_card_are_said_as_text():
    from cloudmorrow.quill import text as _text
    from cloudmorrow.quill import ui

    rows = [{"id": "a", "model": "m", "fields": {"t": "One"}}, {"id": "b", "model": "m", "fields": {"t": "Two"}}]
    tree = ui.split(ui.cards(rows, title="t", current="b"), ui.text("Two, open"), show="main")
    said = _text.render(ui.check(tree))
    assert "• One" in said and "▶ Two" in said and "Two, open" in said
    assert ui.children(tree) == [tree["side"], tree["main"]]
    with pytest.raises(ui.TreeError, match="show is side or main"):
        ui.split(ui.text("a"), ui.text("b"), show="both")
