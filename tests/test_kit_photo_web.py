"""The photo editor in the browser: wired in, generic, and its arithmetic the spec's.

The editor is driven in a browser, not from here. What a test can hold is
what goes wrong quietly: the kit not drawing a screen the server installs, a
word from one Quill in the code that draws all of them, a call to an address
the server does not answer — and the rules in kit_photo_rules.js, which are
pure, and run here under node: the turn, the crop, the export's size, a
text's place (docs/PHOTO.md).
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
    """Field names are the kit's (rotate, crop, out_width…); datamodels and labels the screen's."""
    for source, name in ((PHOTO_JS, "kit_photo.js"), (RULES_JS, "rules"), (PHOTO_CSS, "css")):
        body = js_code(source)
        for word in ("cropper", "retouch", "Photos", "my-files"):
            assert word not in body, f"{name} names {word!r}"


def test_it_writes_only_where_it_may():
    code = js_code(PHOTO_JS)
    assert "writes: mayWrite(b.model)" in code
    assert "writesTexts: !!b.texts && mayWrite(b.texts)" in code
    assert ".access" not in code


def test_it_never_opens_a_browser_window():
    assert not re.search(r"(?<![.\w])(confirm|prompt|alert)\(", js_code(PHOTO_JS))


def test_the_source_is_the_servers_large_copy_and_the_export_is_the_actions():
    code = js_code(PHOTO_JS)
    assert "/thumb?size=" in code and "const LARGE = 2048" in code
    assert 'recordsUrl("file", source, "/media")' in code
    assert "press(ed.at.quill, exportable," in code
    # A Quill's go("editor", edit=<id>) opens the editor.
    assert 'new URLSearchParams(arg).get("edit")' in code
    # The words are drawn in the app's own font, as the export draws them.
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
    text = client.post(
        "/api/records/cropper.text",
        json={"fields": {"edit": edit["id"], "text": "Hello", "x": 6, "y": 6, "size": 6, "colour": "#ffffff"}},
        headers=auth,
    )
    assert text.status_code == 201, text.text
    on = client.get(f"/api/records/cropper.text?edit={edit['id']}", headers=auth).json()
    assert [t["id"] for t in on] == [text.json()["id"]]
    moved = client.patch(f"/api/records/cropper.text/{text.json()['id']}", json={"fields": {"x": 40.5}}, headers=auth)
    assert float(moved.json()["fields"]["x"]) == 40.5
    crop = {"x": 10, "y": 0, "w": 80, "h": 100}
    turned = client.patch(
        f"/api/records/cropper.edit/{edit['id']}",
        json={"fields": {"rotate": 90, "mirror": True, "crop": crop, "out_width": 800, "width": 4000, "height": 3000}},
        headers=auth,
    ).json()["fields"]
    assert (turned["rotate"], turned["mirror"], turned["crop"], turned["out_width"]) == (90, True, crop, 800)
    ran = client.post("/api/quills/cropper/actions/export", json={"record": edit["id"], "fields": {}}, headers=auth)
    assert ran.status_code == 200, ran.text
    assert client.get(f"/api/records/cropper.edit/{edit['id']}", headers=auth).json()["fields"]["status"] == "queued"
    assert client.delete(f"/api/records/cropper.text/{text.json()['id']}", headers=auth).status_code == 204
    # The edit goes, and its texts with it.
    again = client.post(
        "/api/records/cropper.text",
        json={"fields": {"edit": edit["id"], "text": "Bye", "x": 6, "y": 6}},
        headers=auth,
    )
    assert again.status_code == 201
    assert client.delete(f"/api/records/cropper.edit/{edit['id']}", headers=auth).status_code == 204
    assert client.get("/api/records/cropper.text", headers=auth).json() == []


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
def test_a_crop_held_to_a_shape_stays_inside(tmp_path):
    square, tall, crop = run(
        tmp_path,
        ["boxWithRatio", {"x": 10, "y": 10, "w": 60, "h": 90}, 1, {"w": 4000, "h": 3000}],
        ["boxWithRatio", {"x": 0, "y": 0, "w": 100, "h": 100}, 9 / 16, {"w": 4000, "h": 3000}],
        ["cropOf", {"x": 98, "y": -5, "w": 1, "h": 200}],
    )
    # 60% of 4000 is 2400 wide: a square is 2400 tall, 80% of 3000.
    assert square == {"x": 10, "y": 10, "w": 60, "h": 80}
    # The whole picture cannot be tall: the width shrinks to what fits.
    assert tall["h"] == 100 and tall["w"] == pytest.approx(42.1875)
    assert crop == {"x": 95, "y": 0, "w": 5, "h": 100}


@node
def test_a_text_and_a_colour_are_the_kits(tmp_path):
    text, named, short, none, lines, photo, not_photo = run(
        tmp_path,
        ["textOf", {"text": "Hi", "x": "120", "y": -3, "size": "0.1", "colour": "sky"}],
        ["colourFrom", "amber"],
        ["colourFrom", "#fff"],
        ["colourFrom", "#12"],
        ["textLines", {"text": "Two\nlines", "size": 10}, 3000],
        ["isPhoto", "a.HEIC"],
        ["isPhoto", "a.mp4", "video/mp4"],
    )
    assert text == {"text": "Hi", "x": 100, "y": 0, "size": 0.5, "colour": "#5aa6e0"}
    assert named == "#f0a81e" and short == "#ffffff" and none is None
    assert lines == {"lines": ["Two", "lines"], "px": 300, "lineHeight": 360}
    assert photo is True and not_photo is False
