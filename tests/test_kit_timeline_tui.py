"""The kit's `timeline` in the terminal: the projects, then the editor (docs/TIMELINE.md).

Drawn from the Cutter fixture's screen, against the fake server's record
store, with a frames API the fake answers with a picture Pillow makes — the
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

from cloudmorrow.quill import timeline as tl
from cloudmorrow.quill.screens import TRACKS
from cloudmorrow.server.quills import QuillRegistry
from cloudmorrow.tui.panes.kit_timeline import LABEL, TimelinePane, TrackRows, track_lines, viewer_words
from cloudmorrow.tui.screens.modals import PromptModal
from cloudmorrow.tui.widgets.picture import TerminalImage
from tests.conftest import QUILL_CATALOG
from tests.tui_harness import feature_row, settle, start
from tests.tui_quills import record_row

CUTTER = QUILL_CATALOG / "quill-cutter"


def cutter_quill(*, frames: bool) -> dict:
    """The Cutter as the server sends it: its plan, datamodels and all."""
    with tempfile.TemporaryDirectory() as tmp:
        registry = QuillRegistry(Path(tmp) / "quills", Path(tmp) / "datamodels")
        quill = registry.plan(CUTTER, QUILL_CATALOG / "datamodels")
    quill = copy.deepcopy(quill)
    if frames:
        quill["apis"] = [{"id": "frames", "service": "render", "prefix": "frames"}]
        quill["screens"][0]["frames"] = "frames"
    return quill


def jpeg(colour: str = "red") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 36), colour).save(out, format="JPEG")
    return out.getvalue()


def files() -> list[dict]:
    def one(record_id: str, name: str, mime: str, folder: str = "Videos") -> dict:
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
        one("r_beach", "beach.mp4", "video/mp4"),
        one("r_song", "song.mp3", "audio/mpeg", "Videos/Music"),
        one("r_notes", "notes.txt", "text/plain"),
        one("r_away", "away.mp4", "video/mp4", "Elsewhere"),
    ]


def with_cutter(app, *, frames: bool = False) -> None:
    client = app.client
    client.quill_list.append(cutter_quill(frames=frames))
    client.feature_list.append(feature_row("cutter", "Cutter"))
    client.record_store["cutter.project"] = [
        record_row("cutter.project", "r_old", 0, name="Last summer", status="done"),
        record_row("cutter.project", "r_trip", 1, name="Road trip", status="editing"),
    ]
    client.record_store["cutter.project"][0]["created_at"] = "2026-01-01T10:00:00"
    client.record_store["cutter.project"][1]["created_at"] = "2026-10-01T10:00:00"
    client.record_store["cutter.piece"] = [
        record_row(
            "cutter.piece",
            "r_p1",
            0,
            project="r_trip",
            track="V1",
            source="r_beach",
            name="beach.mp4",
            start="0.0",
            offset="0.0",
            length="6.0",
        ),
        record_row(
            "cutter.piece",
            "r_p2",
            1,
            project="r_trip",
            track="A1",
            source="r_song",
            name="song.mp3",
            start="1.0",
            offset="0.0",
            length="8.0",
        ),
    ]
    client.record_store["cutter.effect"] = [
        record_row(
            "cutter.effect",
            "r_e1",
            0,
            piece="r_p1",
            kind="blur",
            label="Face",
            strength=20,
            keyframes=[{"t": 1, "x": 10, "y": 10, "w": 20, "h": 20}, {"t": 5, "x": 50, "y": 10, "w": 20, "h": 20}],
        )
    ]
    plain = client.records

    async def records(model: str, **where: object) -> list[dict]:
        if model == "file":
            # As the server reads `share` and `within`: everything under the folder.
            within = str(where.get("within") or "") + "/"
            mine = [r for r in files() if r["fields"]["share"] == where.get("share")]
            return [r for r in mine if (r["fields"]["folder"] + "/").startswith(within)]
        return await plain(model, **where)

    client.records = records
    client.api_calls = []

    async def quill_api(path: str, params: dict | None = None) -> httpx.Response:
        client.api_calls.append((path, dict(params or {})))
        if path.endswith("/info"):
            length = {"r_beach": 12.0, "r_song": 30.0}.get(params["file"], 3.0)
            return httpx.Response(200, json={"duration": length, "width": 1280, "height": 720, "fps": 25})
        return httpx.Response(200, content=jpeg(), headers={"content-type": "image/jpeg"})

    client.quill_api = quill_api
    client.pressed = []

    async def quill_action(quill_id, action_id, *, record="", fields=None):
        client.pressed.append((quill_id, action_id, record, dict(fields or {})))
        await client.update_record("cutter.project", record, {"status": "queued", "message": "as mp4"})
        return [{"effect": "toast", "text": "Queued"}]

    client.quill_action = quill_action


async def open_cutter(app, pilot) -> TimelinePane:
    screen = await start(app, pilot)
    await pilot.click("#nav-cutter")
    await settle(app, pilot)
    return screen.query_one(TimelinePane)


async def open_trip(app, pilot) -> TimelinePane:
    pane = await open_cutter(app, pilot)
    pane.query_one("#tl-projects", DataTable).move_cursor(row=0)
    pane.act_open()
    await settle(app, pilot)
    return pane


async def modal_up(pilot) -> None:
    await pilot.pause()
    await pilot.pause()


def rows(pane: TimelinePane) -> list[str]:
    tracks = pane.query_one(TrackRows)
    return [line.plain for line in tracks.render().renderables]


# -- drawing ---------------------------------------------------------------------------------
def test_pieces_are_blocks_to_scale_with_the_playhead_through_them():
    pieces = [{"id": "a", "track": "V1", "name": "beach", "start": 0, "length": 4}]
    lines = track_lines(TRACKS, pieces, first=0, per_cell=0.5, width=20, playhead=1, selected="a")
    assert len(lines) == 5 and "╵0:00" in lines[0].plain
    v1 = lines[2].plain
    assert v1.startswith("V1") and "▏b┃ach" in v1
    # The selected piece is amber.
    assert any("#" in str(span.style) for span in lines[2].spans)


def test_without_a_picture_the_viewer_says_what_is_at_the_playhead():
    pieces = [{"id": "a", "track": "V1", "name": "beach", "start": 2, "length": 4, "offset": 1}]
    effects = {"a": [{"fields": {"kind": "blur", "label": "Face", "keyframes": [{"t": 0, **tl.MIDDLE}]}}]}
    said = viewer_words(TRACKS, pieces, effects, 3, {"x": 0, "y": 0, "w": 50, "h": 100})
    assert "beach" in said and "0:02.00 into it" in said and "Face" in said and "cropped to 0 0 50 100" in said
    assert "Nothing at the playhead" in viewer_words(TRACKS, pieces, effects, 9, tl.WHOLE)


# -- the projects ----------------------------------------------------------------------------
async def test_the_projects_are_listed_newest_first(app):
    with_cutter(app)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_cutter(app, pilot)
        table = pane.query_one("#tl-projects", DataTable)
        assert [str(table.get_row_at(i)[0]) for i in range(table.row_count)] == ["Road trip", "Last summer"]
        assert pane.query_one("#do-new_record").display and not pane.query_one("#do-split").display


async def test_new_makes_a_project_and_opens_it(app):
    with_cutter(app)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_cutter(app, pilot)
        pane.act_new_record()
        await modal_up(pilot)
        app.screen.query_one(Input).value = "Holiday"
        await pilot.press("enter")
        await settle(app, pilot)
        assert pane.editing and pane.project["fields"]["name"] == "Holiday"
        await pilot.press("escape")
        await settle(app, pilot)
        assert not pane.editing and pane.query_one("#tl-projects", DataTable).row_count == 3


# -- the editor ------------------------------------------------------------------------------
async def test_the_editor_draws_material_tracks_and_effects(app):
    with_cutter(app)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_trip(app, pilot)
        assert pane.editing
        material = pane.query_one("#tl-material", DataTable)
        # Videos and sounds under Videos only: not the text file, not what is elsewhere.
        assert [r["id"] for r in pane.material] == ["r_beach", "r_song"]
        assert "Music/" in str(material.get_row_at(1)[0])
        drawn = rows(pane)
        assert drawn[2].startswith("V1") and "beach.mp4" in drawn[2]
        assert drawn[3].startswith("A1") and "song.mp3" in drawn[3]
        # No frames API: the viewer is words.
        words = pane.query_one("#tl-viewer-words", Static)
        assert words.display and "beach.mp4" in str(words.render())
        # Picking the piece at the playhead shows its blur and keyframes.
        pane.pick_at_playhead()
        await settle(app, pilot)
        assert pane.selected_id == "r_p1"
        assert pane.query_one("#tl-effects", DataTable).row_count == 1
        assert pane.query_one("#tl-keys", DataTable).row_count == 2


async def test_the_playhead_steps_by_a_frame_and_a_second(app):
    with_cutter(app)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_trip(app, pilot)
        pane.query_one(TrackRows).focus()
        await pilot.press("right")
        assert pane.playhead == pytest.approx(1 / 30)
        await pilot.press("shift+right")
        assert pane.playhead == pytest.approx(1 + 1 / 30)
        await pilot.press("end")
        assert pane.playhead == 9.0
        await pilot.press("home")
        assert pane.playhead == 0.0


async def test_split_trim_and_move_write_the_pieces_and_their_blurs(app):
    with_cutter(app)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_trip(app, pilot)
        store = app.client.record_store
        pane.choose("r_p1")
        pane.seek(3.0)
        await pilot.press("s")
        await settle(app, pilot)
        pieces = sorted((p for p in store["cutter.piece"] if p["fields"]["track"] == "V1"), key=lambda p: p["id"])
        first, second = next(p for p in pieces if p["id"] == "r_p1"), next(p for p in pieces if p["id"] != "r_p1")
        assert float(first["fields"]["length"]) == 3.0
        assert (second["fields"]["start"], second["fields"]["offset"], second["fields"]["length"]) == (3.0, 3.0, 3.0)
        # The blur across the cut went to both halves, its times counted from each.
        blurs = {e["fields"]["piece"]: e["fields"]["keyframes"] for e in store["cutter.effect"]}
        assert [k["t"] for k in blurs["r_p1"]] == [1, 3] and [k["t"] for k in blurs[second["id"]]] == [0, 2]
        assert pane.selected_id == second["id"]
        # Trim the second's start to 4: its offset follows, and its blur's times move back by one.
        pane.seek(4.0)
        await pilot.press("left_square_bracket")
        await settle(app, pilot)
        second = next(p for p in store["cutter.piece"] if p["id"] == second["id"])
        assert (second["fields"]["start"], second["fields"]["offset"], second["fields"]["length"]) == (4.0, 4.0, 2.0)
        blur = next(e for e in store["cutter.effect"] if e["fields"]["piece"] == second["id"])
        assert [k["t"] for k in blur["fields"]["keyframes"]] == [-1, 1]
        # Up to V2 and back to 1 s.
        pane.query_one(TrackRows).focus()
        await pilot.press("up")
        await settle(app, pilot)
        assert next(p for p in store["cutter.piece"] if p["id"] == second["id"])["fields"]["track"] == "V2"
        pane.seek(1.0)
        await pilot.press("m")
        await settle(app, pilot)
        assert next(p for p in store["cutter.piece"] if p["id"] == second["id"])["fields"]["start"] == 1.0
        # x takes it out, and its blur with it.
        await pilot.press("x")
        await settle(app, pilot)
        assert all(p["id"] != second["id"] for p in store["cutter.piece"])
        assert all(e["fields"]["piece"] != second["id"] for e in store["cutter.effect"])


async def test_add_asks_the_length_without_a_frames_api(app):
    with_cutter(app)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_trip(app, pilot)
        pane.seek(6.0)
        pane.query_one("#tl-material", DataTable).move_cursor(row=0)
        pane.act_add()
        await modal_up(pilot)
        assert isinstance(app.screen, PromptModal)
        app.screen.query_one(Input).value = "0:04"
        await pilot.press("enter")
        await settle(app, pilot)
        made = app.client.record_store["cutter.piece"][-1]["fields"]
        assert (made["track"], made["start"], made["length"], made["source"]) == ("V1", 6.0, 4.0, "r_beach")
        assert app.client.api_calls == []


async def test_a_blur_a_keyframe_and_a_crop(app):
    with_cutter(app)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_trip(app, pilot)
        store = app.client.record_store
        pane.choose("r_p2")
        pane.seek(2.0)
        await pilot.press("b")
        await settle(app, pilot)
        blur = next(e for e in store["cutter.effect"] if e["fields"]["piece"] == "r_p2")
        assert blur["fields"]["keyframes"] == [{"t": 1.0, **tl.MIDDLE}]
        pane.seek(4.0)
        await pilot.press("k")
        await modal_up(pilot)
        app.screen.query_one(Input).value = "1 2 3 4"
        await pilot.press("enter")
        await settle(app, pilot)
        blur = next(e for e in store["cutter.effect"] if e["fields"]["piece"] == "r_p2")
        assert blur["fields"]["keyframes"][-1] == {"t": 3.0, "x": 1, "y": 2, "w": 3, "h": 4}
        await pilot.press("c")
        await modal_up(pilot)
        app.screen.query_one(Input).value = "10 10 80 80"
        await pilot.press("enter")
        await settle(app, pilot)
        assert store["cutter.project"][1]["fields"]["crop"] == {"x": 10, "y": 10, "w": 80, "h": 80}
        assert "crop 10 10 80 80" in str(pane.query_one("#tl-head", Static).render())
        await pilot.press("C")
        await settle(app, pilot)
        assert store["cutter.project"][1]["fields"]["crop"] is None


async def test_export_runs_the_action_with_its_form_and_the_header_follows(app):
    with_cutter(app)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_trip(app, pilot)
        await pilot.press("e")
        await modal_up(pilot)
        await pilot.press("ctrl+s")
        await settle(app, pilot)
        assert app.client.pressed == [("cutter", "export", "r_trip", {"format": "mp4"})]
        head = str(pane.query_one("#tl-head", Static).render())
        assert "queued" in head and "as mp4" in head
        assert pane._poll._active.is_set()


# -- with a frames API ------------------------------------------------------------------------
async def test_with_a_frames_api_the_viewer_is_the_frame_and_add_reads_the_length(app):
    with_cutter(app, frames=True)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_trip(app, pilot)
        await settle(app, pilot)
        frames = [c for c in app.client.api_calls if c[0].endswith("/frame")]
        assert frames and frames[0][0] == "/api/q/cutter/frames/frame" and frames[0][1]["project"] == "r_trip"
        if TerminalImage is not None:
            assert pane.query_one("#tl-picture").image is not None
        # The material's lengths, from /info.
        assert "0:12.00" in str(pane.query_one("#tl-material", DataTable).get_row_at(0)[1])
        project = app.client.record_store["cutter.project"][1]
        project["fields"].update(width=None, height=None, fps=None)
        pane.seek(9.0)
        pane.query_one("#tl-material", DataTable).move_cursor(row=0)
        pane.act_add()
        await settle(app, pilot)
        made = app.client.record_store["cutter.piece"][-1]["fields"]
        assert (made["start"], made["length"]) == (9.0, 12.0)
        assert (project["fields"]["width"], project["fields"]["height"], project["fields"]["fps"]) == (1280, 720, 25)


async def test_playing_asks_for_one_frame_at_a_time(app):
    with_cutter(app, frames=True)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_trip(app, pilot)
        await settle(app, pilot)
        before = len(app.client.api_calls)
        await pilot.press("space")
        assert pane.playing
        await pilot.pause(0.8)
        await pilot.press("space")
        assert not pane.playing and pane.playhead > 0.5
        asked = len(app.client.api_calls) - before
        # A few a second, and never a pile of them.
        assert 1 <= asked <= 8


async def test_a_quills_go_opens_a_project_in_the_editor(app):
    """go("editor", project=<id>), as Vidmorrow's actions answer: straight into that project."""
    from cloudmorrow.tui.quill_actions import go_to

    with_cutter(app)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_cutter(app, pilot)
        assert not pane.editing
        go_to(app, "cutter", "editor", {"project": "r_old"})
        await settle(app, pilot)
        assert pane.editing and pane.project["id"] == "r_old"
        assert pane.project["fields"]["name"] == "Last summer"
        assert "Last summer" in str(pane.query_one("#tl-head", Static).render())


async def test_a_click_picks_a_piece_and_a_drag_moves_it_snapping(app):
    with_cutter(app)
    async with app.run_test(size=(140, 40)) as pilot:
        pane = await open_trip(app, pilot)
        tracks = pane.query_one(TrackRows)
        content = tracks.content_region
        left = content.x - tracks.region.x
        top = content.y - tracks.region.y

        def at(t: float, row: int) -> tuple[int, int]:
            return left + LABEL + int((t - pane.first) / pane.per_cell), top + 1 + row

        v1 = [t["id"] for t in pane.tracks].index("V1")
        await pilot.click(TrackRows, offset=at(2.0, v1))
        await settle(app, pilot)
        assert pane.selected_id == "r_p1" and pane.playhead == pytest.approx(2.0, abs=pane.per_cell)
        # Dragged up a track and along by about the gap to the song's start at 1 s: it snaps there.
        await pilot.mouse_down(TrackRows, offset=at(2.0, v1))
        await pilot.mouse_up(TrackRows, offset=at(3.0 + 0.2, v1 - 1))
        await settle(app, pilot)
        moved = next(p for p in app.client.record_store["cutter.piece"] if p["id"] == "r_p1")["fields"]
        assert moved["track"] == "V2" and moved["start"] == 1.0


def test_the_terminal_draws_a_timeline():
    from cloudmorrow.tui.panes.kit import pane_for

    quill = cutter_quill(frames=False)
    assert isinstance(pane_for(quill, quill["screens"][0]), TimelinePane)
