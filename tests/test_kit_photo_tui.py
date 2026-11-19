"""The kit's `photo` in the terminal: the edits, then the editor (docs/PHOTO.md).

Drawn from the Cropper fixture's screen, against the fake server's record
store, with a pictures API the fake answers with a picture Pillow makes — the
real one is the Quill's own service.
"""

from __future__ import annotations

import copy
import io
import tempfile
from pathlib import Path

import httpx
import pytest
from PIL import Image
from textual.widgets import DataTable, Input, Static

from cloudmorrow.client.api import ApiError
from cloudmorrow.quill import photo as ph
from cloudmorrow.server.quills import QuillRegistry
from cloudmorrow.tui.panes.kit_photo import PhotoPane, PickPhotoModal, viewer_words
from cloudmorrow.tui.screens.modals import PromptModal
from cloudmorrow.tui.widgets.picture import TerminalImage
from tests.conftest import QUILL_CATALOG
from tests.tui_harness import feature_row, settle, start
from tests.tui_quills import record_row

CROPPER = QUILL_CATALOG / "quill-cropper"


def cropper_quill(*, pictures: bool) -> dict:
    """The Cropper as the server sends it: its plan, datamodels and all."""
    with tempfile.TemporaryDirectory() as tmp:
        registry = QuillRegistry(Path(tmp) / "quills", Path(tmp) / "datamodels")
        quill = registry.plan(CROPPER, QUILL_CATALOG / "datamodels")
    quill = copy.deepcopy(quill)
    if pictures:
        quill["apis"] = [{"id": "pictures", "service": "draw", "prefix": "pictures"}]
        quill["screens"][0]["pictures"] = "pictures"
    return quill


def jpeg(colour: str = "red") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 36), colour).save(out, format="JPEG")
    return out.getvalue()


def files() -> list[dict]:
    def one(record_id: str, name: str, mime: str, folder: str = "Photos") -> dict:
        return record_row(
            "file",
            record_id,
            0,
            share="my-files",
            name=name,
            folder=folder,
            path=f"{folder}/{name}",
            kind="file",
            mime=mime,
        )

    return [
        one("r_beach", "beach.jpg", "image/jpeg"),
        one("r_dog", "dog.png", "image/png", "Photos/Pets"),
        one("r_notes", "notes.txt", "text/plain"),
        one("r_away", "away.jpg", "image/jpeg", "Elsewhere"),
    ]


def with_cropper(app, *, pictures: bool = False) -> None:
    client = app.client
    client.quill_list.append(cropper_quill(pictures=pictures))
    client.feature_list.append(feature_row("cropper", "Cropper"))
    client.record_store["cropper.edit"] = [
        record_row(
            "cropper.edit", "r_old", 0, name="Last summer", source="r_beach", status="done", width=4000, height=3000
        ),
        record_row(
            "cropper.edit", "r_trip", 1, name="Road trip", source="r_beach", status="editing", width=4000, height=3000
        ),
    ]
    client.record_store["cropper.edit"][0]["created_at"] = "2026-01-01T10:00:00"
    client.record_store["cropper.edit"][1]["created_at"] = "2026-10-01T10:00:00"
    client.record_store["cropper.layer"] = [
        record_row(
            "cropper.layer",
            "r_t1",
            0,
            edit="r_trip",
            kind="text",
            text="Summer",
            x=6,
            y=6,
            size=8,
            colour="#f0a81e",
            order=0,
        ),
        record_row(
            "cropper.layer",
            "r_m1",
            1,
            edit="r_trip",
            kind="mark",
            points=[[10, 10], [20, 20]],
            x=10,
            y=10,
            colour="#e0323c",
            width=1.5,
            order=1,
        ),
    ]
    plain = client.records
    plain_record = client.record

    async def record(model: str, record_id: str) -> dict:
        # The fake serves files as notes; the photos here are the drive's.
        if model == "file":
            found = next((r for r in files() if r["id"] == record_id), None)
            if found is None:
                raise ApiError("no such record", status_code=404)
            return found
        return await plain_record(model, record_id)

    client.record = record

    async def records(model: str, **where: object) -> list[dict]:
        if model == "file":
            within = str(where.get("within") or "") + "/"
            mine = [r for r in files() if r["fields"]["share"] == where.get("share")]
            return [r for r in mine if (r["fields"]["folder"] + "/").startswith(within)]
        return await plain(model, **where)

    client.records = records
    client.api_calls = []

    async def quill_api(path: str, params: dict | None = None) -> httpx.Response:
        client.api_calls.append((path, dict(params or {})))
        if path.endswith("/info"):
            return httpx.Response(200, json={"width": 1280, "height": 720, "image": True})
        return httpx.Response(200, content=jpeg(), headers={"content-type": "image/jpeg"})

    client.quill_api = quill_api
    client.pressed = []

    async def quill_action(quill_id, action_id, *, record="", fields=None):
        client.pressed.append((quill_id, action_id, record, dict(fields or {})))
        message = "over the photo" if (fields or {}).get("overwrite") else f"as {(fields or {}).get('name') or 'jpeg'}"
        await client.update_record("cropper.edit", record, {"status": "queued", "message": message})
        return [{"effect": "toast", "text": "Saving"}]

    client.quill_action = quill_action


async def open_cropper(app, pilot) -> PhotoPane:
    screen = await start(app, pilot)
    await pilot.click("#nav-cropper")
    await settle(app, pilot)
    return screen.query_one(PhotoPane)


async def open_trip(app, pilot) -> PhotoPane:
    pane = await open_cropper(app, pilot)
    pane.query_one("#ph-edits", DataTable).move_cursor(row=0)
    pane.act_open()
    await settle(app, pilot)
    return pane


async def modal_up(pilot) -> None:
    await pilot.pause()
    await pilot.pause()


def edit(app, edit_id: str = "r_trip") -> dict:
    return next(e for e in app.client.record_store["cropper.edit"] if e["id"] == edit_id)["fields"]


def layers(app) -> list[dict]:
    return app.client.record_store["cropper.layer"]


# -- words -----------------------------------------------------------------------------------
def test_without_a_picture_the_viewer_says_what_the_edit_does():
    fields = {"width": 4000, "height": 3000, "rotate": 90, "mirror": True, "crop": {"x": 0, "y": 0, "w": 50, "h": 50}}
    said = viewer_words(
        fields,
        [{"fields": {"kind": "text", "text": "Hi"}}, {"fields": {"kind": "mark", "points": [[1, 1]], "hidden": True}}],
    )
    assert "4000 × 3000" in said and "turned 90°" in said and "mirrored" in said
    # Turned, the picture is 3000 × 4000; half of that is kept. A hidden layer is not said.
    assert "cropped to 0 0 50 50" in said and "comes out" in said and "1500 × 2000" in said and "“Hi”" in said
    assert "mark" not in said
    assert "not known" in viewer_words({}, [])


# -- the edits ------------------------------------------------------------------------------
async def test_the_edits_are_listed_newest_first(app):
    with_cropper(app)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_cropper(app, pilot)
        table = pane.query_one("#ph-edits", DataTable)
        assert [str(table.get_row_at(i)[0]) for i in range(table.row_count)] == ["Road trip", "Last summer"]
        assert str(table.get_row_at(0)[1]) == "4000 × 3000"
        assert pane.query_one("#do-new_record").display and not pane.query_one("#do-turn_right").display


async def test_new_picks_a_photo_of_the_drive_and_opens_the_edit(app):
    with_cropper(app)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_cropper(app, pilot)
        pane.act_new_record()
        await modal_up(pilot)
        await modal_up(pilot)
        modal = app.screen
        assert isinstance(modal, PickPhotoModal)
        # Photos under Photos only: not the text file, not what is elsewhere; a subfolder is said.
        assert [p["id"] for p in modal.photos] == ["r_beach", "r_dog"]
        table = modal.query_one("#ph-pick-photos", DataTable)
        assert "Pets/" in str(table.get_row_at(1)[0])
        table.move_cursor(row=1)
        await pilot.press("enter")
        await settle(app, pilot)
        assert pane.editing and pane.edit["fields"]["name"] == "dog" and pane.edit["fields"]["source"] == "r_dog"
        await pilot.press("escape")
        await settle(app, pilot)
        assert not pane.editing and pane.query_one("#ph-edits", DataTable).row_count == 3


# -- the editor -------------------------------------------------------------------------------
async def test_the_editor_draws_the_head_the_words_and_the_layers_top_first(app):
    with_cropper(app)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_trip(app, pilot)
        assert pane.editing
        head = str(pane.query_one("#ph-head", Static).render())
        assert "Road trip" in head and "4000 × 3000" in head
        words = pane.query_one("#ph-viewer-words", Static)
        assert words.display and "Summer" in str(words.render())
        table = pane.query_one("#ph-layers", DataTable)
        # The one layer first, then what is on it: the mark is on top of the words, so it is listed first.
        assert table.row_count == 3
        assert "Layer 1" in str(table.get_row_at(0)[0])
        assert "Mark" in str(table.get_row_at(1)[0]) and "2 points" in str(table.get_row_at(1)[1])
        assert "Summer" in str(table.get_row_at(2)[0]) and "6 6 · 8%" in str(table.get_row_at(2)[1])


async def test_turn_mirror_crop_and_size_write_the_edit(app):
    with_cropper(app)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_trip(app, pilot)
        pane.query_one("#ph-layers", DataTable).focus()
        await pilot.press("r")
        await settle(app, pilot)
        assert edit(app)["rotate"] == 90
        await pilot.press("R")
        await pilot.press("R")
        await settle(app, pilot)
        assert edit(app)["rotate"] == 270
        assert "turned 270°" in str(pane.query_one("#ph-head", Static).render())
        await pilot.press("m")
        await settle(app, pilot)
        assert edit(app)["mirror"] is True
        await pilot.press("c")
        await modal_up(pilot)
        assert isinstance(app.screen, PromptModal)
        app.screen.query_one(Input).value = "10 10 80 80"
        await pilot.press("enter")
        await settle(app, pilot)
        assert edit(app)["crop"] == {"x": 10, "y": 10, "w": 80, "h": 80}
        assert "crop 10 10 80 80" in str(pane.query_one("#ph-head", Static).render())
        await pilot.press("s")
        await modal_up(pilot)
        app.screen.query_one(Input).value = "50%"
        await pilot.press("enter")
        await settle(app, pilot)
        # Turned, the picture is 3000 × 4000; cropped to 80%, 2400 × 3200; half of that.
        assert (edit(app)["out_width"], edit(app)["out_height"]) == (1200, 1600)
        assert "1200 × 1600" in str(pane.query_one("#ph-head", Static).render())
        await pilot.press("C")
        await settle(app, pilot)
        assert edit(app)["crop"] is None


async def test_layers_are_laid_on_moved_hidden_restacked_and_taken_off(app):
    with_cropper(app)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_trip(app, pilot)
        table = pane.query_one("#ph-layers", DataTable)
        table.focus()
        await pilot.press("t")
        await modal_up(pilot)
        app.screen.query_one(Input).value = "Hello"
        await pilot.press("enter")
        await settle(app, pilot)
        made = layers(app)[-1]["fields"]
        assert (made["edit"], made["kind"], made["text"], made["x"], made["y"], made["order"]) == (
            "r_trip",
            "text",
            "Hello",
            6.0,
            6.0,
            2,
        )
        # On top, so first under its layer, and the cursor on it.
        assert table.row_count == 4 and table.cursor_row == 1
        await pilot.press("k")
        await modal_up(pilot)
        app.screen.query_one(Input).value = "50 80 12"
        await pilot.press("enter")
        await settle(app, pilot)
        made = layers(app)[-1]["fields"]
        assert (made["x"], made["y"], made["size"]) == (50.0, 80.0, 12.0)
        # h hides the layer the cursor is on, with everything on it; again shows it.
        await pilot.press("h")
        await settle(app, pilot)
        assert edit(app)["layers"] == [{"id": "1", "name": "Layer 1", "hidden": True}]
        await pilot.press("h")
        await settle(app, pilot)
        assert edit(app)["layers"][0]["hidden"] is False
        # Sent back one step: under the mark.
        await pilot.press("shift+down")
        await settle(app, pilot)
        orders = {r["id"]: r["fields"].get("order") for r in layers(app)}
        hello = layers(app)[-1]["id"]
        assert orders[hello] == 1 and orders["r_m1"] == 2 and orders["r_t1"] == 0
        assert table.cursor_row == 2
        # The mark moves as a whole.
        table.move_cursor(row=1)
        await pilot.press("k")
        await modal_up(pilot)
        app.screen.query_one(Input).value = "20 20"
        await pilot.press("enter")
        await settle(app, pilot)
        mark = next(r for r in layers(app) if r["id"] == "r_m1")["fields"]
        assert mark["points"] == [[20.0, 20.0], [30.0, 30.0]]
        await pilot.press("x")
        await settle(app, pilot)
        assert all(r["id"] != "r_m1" for r in layers(app))


async def test_save_asks_a_name_and_the_photos_name_writes_over_it(app):
    with_cropper(app)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_trip(app, pilot)
        await pilot.press("w")
        await modal_up(pilot)
        modal = app.screen
        assert isinstance(modal, PromptModal) and modal.query_one(Input).value == "beach.jpg"
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.client.pressed == [("cropper", "save", "r_trip", {"overwrite": True, "name": "beach.jpg"})]
        head = str(pane.query_one("#ph-head", Static).render())
        assert "queued" in head and "over the photo" in head
        assert pane._poll._active.is_set()
        # Another name is a new file.
        await pilot.press("w")
        await modal_up(pilot)
        app.screen.query_one(Input).value = "beach edited.png"
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.client.pressed[-1] == ("cropper", "save", "r_trip", {"overwrite": False, "name": "beach edited.png"})


async def test_export_runs_the_action_with_its_form(app):
    with_cropper(app)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_trip(app, pilot)
        await pilot.press("e")
        await modal_up(pilot)
        await pilot.press("ctrl+s")
        await settle(app, pilot)
        assert app.client.pressed == [("cropper", "export", "r_trip", {"format": "jpeg"})]
        assert pane._poll._active.is_set()


# -- with a pictures API ---------------------------------------------------------------------
async def test_with_a_pictures_api_the_viewer_is_the_picture_and_new_reads_the_size(app):
    with_cropper(app, pictures=True)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_trip(app, pilot)
        await settle(app, pilot)
        asked = [c for c in app.client.api_calls if c[0].endswith("/picture")]
        assert asked and asked[0][0] == "/api/q/cropper/pictures/picture" and asked[0][1]["edit"] == "r_trip"
        if TerminalImage is not None:
            assert pane.query_one("#ph-picture").image is not None
        await pilot.press("escape")
        await settle(app, pilot)
        pane.act_new_record()
        await modal_up(pilot)
        await modal_up(pilot)
        app.screen.query_one("#ph-pick-photos", DataTable).move_cursor(row=0)
        await pilot.press("enter")
        await settle(app, pilot)
        made = app.client.record_store["cropper.edit"][-1]["fields"]
        assert (made["source"], made["width"], made["height"]) == ("r_beach", 1280, 720)


async def test_a_quills_go_opens_an_edit_in_the_editor(app):
    from cloudmorrow.tui.quill_actions import go_to

    with_cropper(app)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_cropper(app, pilot)
        assert not pane.editing
        go_to(app, "cropper", "editor", {"edit": "r_old"})
        await settle(app, pilot)
        assert pane.editing and pane.edit["id"] == "r_old"
        assert "Last summer" in str(pane.query_one("#ph-head", Static).render())


def test_the_terminal_draws_a_photo_editor():
    from cloudmorrow.tui.panes.kit import pane_for

    quill = cropper_quill(pictures=False)
    assert isinstance(pane_for(quill, quill["screens"][0]), PhotoPane)
    assert ph.WHOLE == {"x": 0.0, "y": 0.0, "w": 100.0, "h": 100.0}


@pytest.mark.parametrize("key", ["r", "m", "c", "s", "t", "w"])
async def test_the_editors_keys_do_nothing_on_the_list(app, key):
    with_cropper(app)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_cropper(app, pilot)
        await pilot.press(key)
        await settle(app, pilot)
        assert not pane.editing and app.screen is pane.screen
        assert edit(app).get("rotate") in (None, 0) and app.client.pressed == []
