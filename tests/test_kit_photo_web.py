"""The photo editor in the browser: wired in, generic, and its arithmetic the spec's.

The editor is driven in a browser, not from here. What a test can hold is
what goes wrong quietly: the kit not drawing a screen the server installs, a
word from one Quill in the code that draws all of them, a call to an address
the server does not answer — and the rules in kit_photo_rules.js, which are
pure, and run here under node: the turn, the crop, the saved size, where a
layer is, what is near a mark (docs/PHOTO.md).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from cloudmorrow.server.routes.web import WEB, asset_version
from tests.conftest import ADMIN, QUILL_CATALOG, js_code, token_for

PHOTO_JS = (WEB / "kit_photo.js").read_text(encoding="utf-8")
RULES_JS = (WEB / "kit_photo_rules.js").read_text(encoding="utf-8")
PHOTO_CSS = (WEB / "kit_photo.css").read_text(encoding="utf-8")
KIT_JS = (WEB / "kit.js").read_text(encoding="utf-8")
node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


# -- wired in ------------------------------------------------------------------------
def test_the_photo_editor_is_its_own_file_registered_from_the_kit(client):
    assert 'import { photoSheet, renderPhoto } from "./kit_photo.js";' in KIT_JS
    assert "photo: renderPhoto" in KIT_JS and "photo: photoSheet" in KIT_JS
    assert '@import "./kit_photo.css";' in (WEB / "app.css").read_text(encoding="utf-8")
    version = asset_version()
    for name in ("kit_photo.js", "kit_photo.css", "kit_photo_rules.js"):
        assert client.get(f"/app/{version}/{name}").status_code == 200, name


def test_nothing_in_the_photo_editor_is_named_for_one_quill():
    """Field names are the kit's (rotate, crop, points…); datamodels and labels the screen's."""
    for source, name in ((PHOTO_JS, "kit_photo.js"), (RULES_JS, "rules"), (PHOTO_CSS, "css")):
        body = js_code(source)
        for word in ("cropper", "retouch", "Photos", "my-files"):
            assert word not in body, f"{name} names {word!r}"


def test_it_writes_only_where_it_may():
    code = js_code(PHOTO_JS)
    assert "writes: mayWrite(b.model)" in code
    assert "writesLayers: !!b.layers && mayWrite(b.layers)" in code
    assert ".access" not in code


def test_it_never_opens_a_browser_window():
    assert not re.search(r"(?<![.\w])(confirm|prompt|alert)\(", js_code(PHOTO_JS))


def test_the_tools_the_save_and_the_source():
    code = js_code(PHOTO_JS)
    # The five tools, and the turns beside them.
    for tool in ("select", "move", "marquee", "crop", "text", "marker"):
        assert f'["{tool}", ' in code, tool
    # Select is first and the one everything comes back to; words laid hand back to it.
    assert 'const HOME = "select"' in code and "tool: HOME," in code
    assert "if (ed.tool !== HOME) setTool(ed, HOME);\n    const words" in code
    # The source is the server's large copy; the saved file opens through a media link.
    assert "/thumb?size=" in code and "const LARGE = 2048" in code
    assert 'recordsUrl("file", fileId, "/media")' in code
    # Save asks in a sheet of the kit's own and presses the action with both fields answered.
    assert "openSheet(" in code and "run({ overwrite: true, name: photoName })" in code
    assert "run({ overwrite: false, name })" in code
    # Export is the action with its form, as the timeline's is.
    assert "press(ed.at.quill, ed.b.exportAction," in code
    # Resize is a sheet from the bar, not a panel; the saved size is written as it is chosen.
    assert "function resizeSheet(ed)" in code and 'class="act-button ph-resize"' in code
    assert "imagePanel" not in code and "ph-size-pick" not in code


def test_a_drag_is_held_by_the_overlay_and_the_marker_meets_no_box():
    """A box is drawn anew as it moves, so the pointer is held by the overlay, which
    stays; a press on the whole-picture crop box draws a new crop; the Marker
    tool draws no layer box to get in the way of a stroke."""
    code = js_code(PHOTO_JS)
    drag = code[code.index("function dragBox(ed, what, event, handle)") : code.index("const r2 = ")]
    assert "over.setPointerCapture(event.pointerId)" in drag and "el.setPointerCapture" not in drag
    assert 'over.addEventListener("pointermove", move)' in drag and "el.addEventListener" not in drag
    for name in ("rubberBand", "drawStroke"):
        body = code[code.index(f"function {name}(ed, event, from") :]
        body = body[: body.index("\n}\n")]
        assert "ed.over.setPointerCapture(event.pointerId)" in body, name
    assert 'wholeFrame(crop(ed)) && ed.writes) rubberBand(ed, event, at, "crop")' in code
    overlay = code[code.index("function placeOverlay(ed)") : code.index("function pointAt(ed, event)")]
    assert 'ed.tool === "marker"' in overlay
    # Without layers, the tools that make them are not offered.
    assert "TOOLS.filter(([id]) => b.layers || !LAYER_TOOLS.has(id))" in code
    # A Quill's go("editor", edit=<id>) opens the editor.
    assert 'new URLSearchParams(arg).get("edit")' in code
    # The words are drawn in the app's own font, as the service draws them.
    assert "Barlow" in code


# -- the calls it makes -----------------------------------------------------------------
def test_the_calls_it_makes_exist(client, config):
    """What the editor does, by the same calls it makes, against the fixture Quill."""
    state = client.app.state.cloudmorrow
    state.quills.install_from_catalog("files")
    state.quills.install(QUILL_CATALOG / "quill-cropper", QUILL_CATALOG / "datamodels")
    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    assert client.post("/api/records/file/_folders?share=my-files", json={"path": "Photos"}, headers=auth).is_success
    photo = client.post("/api/records/file/upload?share=my-files&folder=Photos&name=a.jpg", content=b"00", headers=auth)
    assert photo.status_code == 201
    listed = client.get("/api/records/file?share=my-files&within=Photos", headers=auth).json()
    assert [r["fields"]["name"] for r in listed] == ["a.jpg"]
    edit = client.post(
        "/api/records/cropper.edit", json={"fields": {"name": "A", "source": photo.json()["id"]}}, headers=auth
    )
    assert edit.status_code == 201, edit.text
    edit = edit.json()
    layers = []
    for fields in (
        {"kind": "text", "text": "Hello", "x": 6, "y": 6, "size": 6, "colour": "#ffffff", "order": 0},
        {
            "kind": "mark",
            "points": [[10, 10], [20, 20]],
            "x": 10,
            "y": 10,
            "colour": "#e0323c",
            "width": 1.5,
            "opacity": 1,
            "order": 1,
        },
        {"kind": "piece", "source": {"x": 0, "y": 0, "w": 25, "h": 25}, "x": 50, "y": 50, "w": 25, "h": 25, "order": 2},
    ):
        made = client.post("/api/records/cropper.layer", json={"fields": {"edit": edit["id"], **fields}}, headers=auth)
        assert made.status_code == 201, made.text
        layers.append(made.json())
    on = client.get(f"/api/records/cropper.layer?edit={edit['id']}", headers=auth).json()
    assert {t["id"] for t in on} == {t["id"] for t in layers}
    moved = client.patch(
        f"/api/records/cropper.layer/{layers[0]['id']}",
        json={"fields": {"x": 40.5, "hidden": True, "order": 3}},
        headers=auth,
    )
    assert float(moved.json()["fields"]["x"]) == 40.5 and moved.json()["fields"]["hidden"] is True
    crop = {"x": 10, "y": 0, "w": 80, "h": 100}
    turned = client.patch(
        f"/api/records/cropper.edit/{edit['id']}",
        json={"fields": {"rotate": 90, "mirror": True, "crop": crop, "out_width": 800, "width": 4000, "height": 3000}},
        headers=auth,
    ).json()["fields"]
    assert (turned["rotate"], turned["mirror"], turned["crop"], turned["out_width"]) == (90, True, crop, 800)
    # Save, with both fields answered, runs at once; Export too, with its form's field.
    saved = client.post(
        "/api/quills/cropper/actions/save",
        json={"record": edit["id"], "fields": {"overwrite": True, "name": "a.jpg"}},
        headers=auth,
    )
    assert saved.status_code == 200, saved.text
    fields = client.get(f"/api/records/cropper.edit/{edit['id']}", headers=auth).json()["fields"]
    assert (fields["status"], fields["message"]) == ("queued", "over the photo")
    ran = client.post("/api/quills/cropper/actions/export", json={"record": edit["id"], "fields": {}}, headers=auth)
    assert ran.status_code == 200, ran.text
    assert client.delete(f"/api/records/cropper.layer/{layers[1]['id']}", headers=auth).status_code == 204
    # The edit goes, and its layers with it.
    assert client.delete(f"/api/records/cropper.edit/{edit['id']}", headers=auth).status_code == 204
    assert client.get("/api/records/cropper.layer", headers=auth).json() == []


# -- the rules, under node ------------------------------------------------------------------
RUNNER = """
import * as rules from "%s";
import { readFileSync } from "node:fs";
const calls = JSON.parse(readFileSync(0, "utf8"));
const answer = ([name, ...args]) => (typeof rules[name] === "function" ? rules[name](...args) : rules[name]);
console.log(JSON.stringify(calls.map(answer)));
"""


def run(tmp_path, *calls):
    script = tmp_path / "rules.mjs"
    script.write_text(RUNNER % (WEB / "kit_photo_rules.js").as_uri(), encoding="utf-8")
    done = subprocess.run(["node", str(script)], input=json.dumps(calls), capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


LANDSCAPE = {"width": 4000, "height": 3000}


@node
def test_a_turn_is_a_quarter_turn_and_swaps_the_sides(tmp_path):
    a, b, c, size = run(
        tmp_path,
        ["rotationOf", {"rotate": "270"}],
        ["rotationOf", {"rotate": -90}],
        ["rotationOf", {"rotate": 100}],
        ["pictureSize", {**LANDSCAPE, "rotate": 90}],
    )
    assert (a, b, c) == (270, 270, 90) and size == {"w": 3000, "h": 4000}


@node
def test_the_output_follows_the_crop_and_the_size_asked(tmp_path):
    cropped, own, wide, tall, both, typed, percent, bad = run(
        tmp_path,
        ["croppedSize", {**LANDSCAPE, "rotate": 90, "crop": {"x": 0, "y": 0, "w": 50, "h": 25}}],
        ["outputSize", LANDSCAPE],
        ["outputSize", {**LANDSCAPE, "out_width": 1000}],
        ["outputSize", {**LANDSCAPE, "out_height": 300}],
        ["outputSize", {**LANDSCAPE, "out_width": 100, "out_height": 100}],
        ["sizeFrom", "1920x1080"],
        ["sizeFrom", "50%", {"w": 4000, "h": 3000}],
        ["sizeFrom", "big"],
    )
    assert cropped == {"w": 1500, "h": 1000}
    assert own == {"w": 4000, "h": 3000} and wide == {"w": 1000, "h": 750} and tall == {"w": 400, "h": 300}
    assert both == {"w": 100, "h": 100}
    assert typed == {"out_width": 1920, "out_height": 1080} and percent == {"out_width": 2000, "out_height": 1500}
    assert bad is None


@node
def test_a_crop_held_to_a_shape_and_a_box_drawn_out_stay_inside(tmp_path):
    square, tall, crop, drawn = run(
        tmp_path,
        ["boxWithRatio", {"x": 10, "y": 10, "w": 60, "h": 90}, 1, {"w": 4000, "h": 3000}],
        ["boxWithRatio", {"x": 0, "y": 0, "w": 100, "h": 100}, 9 / 16, {"w": 4000, "h": 3000}],
        ["cropOf", {"x": 98, "y": -5, "w": 1, "h": 200}],
        ["boxBetween", {"x": 60, "y": 70}, {"x": 20, "y": 30}],
    )
    # 60% of 4000 is 2400 wide: a square is 2400 tall, 80% of 3000.
    assert square == {"x": 10, "y": 10, "w": 60, "h": 80}
    # The whole picture cannot be tall: the width shrinks to what fits.
    assert tall["h"] == 100 and tall["w"] == pytest.approx(42.1875)
    assert crop == {"x": 95, "y": 0, "w": 5, "h": 100}
    assert drawn == {"x": 20, "y": 30, "w": 40, "h": 40}


@node
def test_layers_are_the_kits(tmp_path):
    text, mark, piece, order, near, far, moved, thin, top, label = run(
        tmp_path,
        ["layerOf", {"kind": "text", "text": "Hi", "x": "120", "y": -3, "size": "0.1", "colour": "sky"}],
        [
            "layerOf",
            {"kind": "mark", "points": [[1, 2], "junk", [300, -5]], "colour": "red", "width": 99, "hidden": True},
        ],
        ["layerOf", {"kind": "piece", "source": {"x": 10, "y": 10, "w": 30, "h": 20}, "x": 50, "y": 50}],
        [
            "layersInOrder",
            [
                {"id": "b", "created_at": "2026-01-02", "fields": {"order": 0}},
                {"id": "a", "created_at": "2026-01-01", "fields": {"order": 0}},
                {"id": "c", "created_at": "2026-01-01", "fields": {"order": 5}},
            ],
        ],
        ["nearMark", {"points": [[0, 0], [10, 0]]}, 5, 1, 1.5],
        ["nearMark", {"points": [[0, 0], [10, 0]]}, 5, 5, 1.5],
        ["movedMark", {"points": [[0, 0], [10, 0]]}, -5, 2],
        ["thinned", [[0, 0], [0.1, 0.1], [1, 1], [1.05, 1.05]], 0.25],
        ["topOrder", [{"order": 2}, {"order": 7}]],
        ["layerLabel", {"kind": "text", "text": "Hello there\nagain"}],
    )
    assert text == {
        "kind": "text",
        "x": 100,
        "y": 0,
        "hidden": False,
        "order": 0,
        "colour": "#5aa6e0",
        "text": "Hi",
        "size": 0.5,
    }
    assert (
        mark["points"] == [[1, 2], [100, 0]] and mark["width"] == 25 and mark["opacity"] == 1 and mark["hidden"] is True
    )
    assert piece["source"] == {"x": 10, "y": 10, "w": 30, "h": 20} and (piece["w"], piece["h"]) == (30, 20)
    assert [r["id"] for r in order] == ["a", "b", "c"]
    assert near is True and far is False
    # Moved left by 5 it stops at the edge: the whole stroke keeps its shape.
    assert moved == [[0, 2], [10, 2]]
    assert thin == [[0, 0], [1, 1]]
    assert top == 8 and label == "Hello there"


@node
def test_a_colour_and_a_photo_are_told(tmp_path):
    named, short, none, lines, photo, not_photo = run(
        tmp_path,
        ["colourFrom", "amber"],
        ["colourFrom", "#fff"],
        ["colourFrom", "#12"],
        ["textLines", {"text": "Two\nlines", "size": 10}, 3000],
        ["isPhoto", "a.HEIC"],
        ["isPhoto", "a.mp4", "video/mp4"],
    )
    assert named == "#f0a81e" and short == "#ffffff" and none is None
    assert lines == {"lines": ["Two", "lines"], "px": 300, "lineHeight": 360}
    assert photo is True and not_photo is False
