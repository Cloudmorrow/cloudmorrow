"""The timeline in the browser: wired in, generic, and its arithmetic the spec's.

The editor is driven in a browser, not from here (see the screenshots in the
report). What a test can hold is what goes wrong quietly: the kit not drawing
a screen the server installs, a word from one Quill in the code that draws all
of them, a call to an address the server does not answer — and the rules in
kit_timeline_rules.js, which are pure, and run here under node: which piece is
on top, where a box is between keyframes, what a split and a trim do to them
(docs/TIMELINE.md).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from cloudmorrow.quill.screens import TRACKS
from cloudmorrow.server.routes.web import WEB, asset_version
from tests.conftest import ADMIN, QUILL_CATALOG, js_code, token_for

TIMELINE_JS = (WEB / "kit_timeline.js").read_text(encoding="utf-8")
RULES_JS = (WEB / "kit_timeline_rules.js").read_text(encoding="utf-8")
TIMELINE_CSS = (WEB / "kit_timeline.css").read_text(encoding="utf-8")
KIT_JS = (WEB / "kit.js").read_text(encoding="utf-8")
node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


# -- wired in ------------------------------------------------------------------------
def test_the_timeline_is_its_own_file_registered_from_the_kit(client):
    assert 'import { renderTimeline, timelineSheet } from "./kit_timeline.js";' in KIT_JS
    assert "timeline: renderTimeline" in KIT_JS and "timeline: timelineSheet" in KIT_JS
    assert '@import "./kit_timeline.css";' in (WEB / "app.css").read_text(encoding="utf-8")
    version = asset_version()
    for name in ("kit_timeline.js", "kit_timeline.css", "kit_timeline_rules.js"):
        assert client.get(f"/app/{version}/{name}").status_code == 200, name


def test_nothing_in_the_timeline_is_named_for_one_quill():
    """Field names are the kit's (start, offset, keyframes…); datamodels and labels the screen's."""
    for source, name in ((TIMELINE_JS, "kit_timeline.js"), (RULES_JS, "rules"), (TIMELINE_CSS, "css")):
        body = js_code(source)
        for word in ("cutter", "vidmorrow", "Videos", "my-files"):
            assert word not in body, f"{name} names {word!r}"


def test_it_writes_only_where_it_may():
    code = js_code(TIMELINE_JS)
    assert "writes: mayWrite(b.pieces)" in code
    assert "writesEffects: !!b.effects && mayWrite(b.effects)" in code
    assert "writesProject: mayWrite(b.model)" in code
    assert ".access" not in code


def test_it_never_opens_a_browser_window():
    assert not re.search(r"(?<![.\w])(confirm|prompt|alert)\(", js_code(TIMELINE_JS))


def test_the_tracks_are_the_servers():
    """The kit's four tracks, the same in Python and JavaScript."""
    block = RULES_JS.split("export const TRACKS = [", 1)[1].split("];", 1)[0]
    found = [
        dict(zip(("id", "kind", "name"), m, strict=True))
        for m in re.findall(r'\{ id: "(\w+)", kind: "(\w+)", name: "([\w ]+)" \}', block)
    ]
    assert found == TRACKS


def test_media_plays_from_links_and_the_export_is_the_actions():
    code = js_code(TIMELINE_JS)
    assert 'recordsUrl("file", fileId, "/media")' in code
    assert "LINK_SPARE" in code and "Date.parse(made.expires)" in code
    assert "press(ed.at.quill, exportable," in code
    # A Quill's go("editor", project=<id>) opens the editor.
    assert 'new URLSearchParams(arg).get("project")' in code


# -- the calls it makes -----------------------------------------------------------------
def test_the_calls_it_makes_exist(client, config):
    """What the editor does, by the same calls it makes, against the fixture Quill."""
    state = client.app.state.cloudmorrow
    state.quills.install_from_catalog("files")
    state.quills.install(QUILL_CATALOG / "quill-cutter", QUILL_CATALOG / "datamodels")
    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    assert client.post("/api/records/file/_folders?share=my-files", json={"path": "Videos"}, headers=auth).is_success
    clip = client.post("/api/records/file/upload?share=my-files&folder=Videos&name=a.mp4", content=b"00", headers=auth)
    assert clip.status_code == 201
    listed = client.get("/api/records/file?share=my-files&within=Videos", headers=auth).json()
    assert [r["fields"]["name"] for r in listed] == ["a.mp4"]
    project = client.post("/api/records/cutter.project", json={"fields": {"name": "Cut"}}, headers=auth).json()
    fields = {
        "project": project["id"],
        "track": "V1",
        "source": clip.json()["id"],
        "name": "a.mp4",
        "start": 0,
        "offset": 0,
        "length": 8,
    }
    piece = client.post("/api/records/cutter.piece", json={"fields": fields}, headers=auth).json()
    on = client.get(f"/api/records/cutter.piece?project={project['id']}", headers=auth).json()
    assert [p["id"] for p in on] == [piece["id"]]
    keyframes = [{"t": 0, "x": 35, "y": 25, "w": 30, "h": 40}]
    effect = client.post(
        "/api/records/cutter.effect",
        json={
            "fields": {"piece": piece["id"], "kind": "blur", "label": "A face", "strength": 20, "keyframes": keyframes}
        },
        headers=auth,
    )
    assert effect.status_code == 201
    moved = client.patch(f"/api/records/cutter.piece/{piece['id']}", json={"fields": {"start": 1.5}}, headers=auth)
    # A decimal comes back as its digits: the kit reads every time with Number().
    assert float(moved.json()["fields"]["start"]) == 1.5
    crop = {"x": 10, "y": 0, "w": 80, "h": 100}
    assert (
        client.patch(
            f"/api/records/cutter.project/{project['id']}", json={"fields": {"crop": crop}}, headers=auth
        ).json()["fields"]["crop"]
        == crop
    )
    ran = client.post("/api/quills/cutter/actions/export", json={"record": project["id"], "fields": {}}, headers=auth)
    assert ran.status_code == 200, ran.text
    assert (
        client.get(f"/api/records/cutter.project/{project['id']}", headers=auth).json()["fields"]["status"] == "queued"
    )
    assert client.delete(f"/api/records/cutter.piece/{piece['id']}", headers=auth).status_code == 204
    assert client.get("/api/records/cutter.effect", headers=auth).json() == []


# -- the rules, under node ------------------------------------------------------------------
RUNNER = """
import * as rules from "%s";
import { readFileSync } from "node:fs";
const calls = JSON.parse(readFileSync(0, "utf8"));
console.log(JSON.stringify(calls.map(([name, ...args]) => rules[name](...args))));
"""


def run(tmp_path, *calls):
    script = tmp_path / "rules.mjs"
    script.write_text(RUNNER % (WEB / "kit_timeline_rules.js").as_uri(), encoding="utf-8")
    done = subprocess.run(["node", str(script)], input=json.dumps(calls), capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


TRACKS4 = [dict(t) for t in TRACKS]


def piece(id_, track, start, length, offset=0, **more):
    return {
        "id": id_,
        "track": track,
        "start": start,
        "length": length,
        "offset": offset,
        "volume": 1,
        "muted": False,
        **more,
    }


@node
def test_the_higher_video_track_covers_the_lower(tmp_path):
    pieces = [piece("low", "V1", 0, 10), piece("high", "V2", 2, 2), piece("sound", "A1", 0, 10)]
    top, gap, heard = run(
        tmp_path,
        ["pictureAt", pieces, TRACKS4, 3],
        ["pictureAt", pieces, TRACKS4, 12],
        ["soundsAt", [*pieces, piece("hush", "A2", 0, 5, muted=True)], TRACKS4, 3],
    )
    assert top["id"] == "high" and gap is None
    assert [p["id"] for p in heard] == ["low", "high", "sound"]


@node
def test_a_box_moves_in_a_straight_line_and_stays_put_outside(tmp_path):
    keys = [{"t": 0, "x": 0, "y": 0, "w": 10, "h": 10}, {"t": 2, "x": 50, "y": 20, "w": 30, "h": 10}]
    before, middle, after, on, off, one = run(
        tmp_path,
        ["boxAt", keys, -1],
        ["boxAt", keys, 1],
        ["boxAt", keys, 5],
        ["effectOn", keys, 1],
        ["effectOn", keys, 2.5],
        ["effectOn", keys[:1], 99],
    )
    assert before == {"x": 0, "y": 0, "w": 10, "h": 10}
    assert middle == {"x": 25, "y": 10, "w": 20, "h": 10}
    assert after == {"x": 50, "y": 20, "w": 30, "h": 10}
    assert on is True and off is False and one is True


@node
def test_a_keyframe_is_set_within_half_a_frame_and_kept_sorted(tmp_path):
    keys = [{"t": 0, "x": 0, "y": 0, "w": 10, "h": 10}, {"t": 2, "x": 0, "y": 0, "w": 10, "h": 10}]
    box = {"x": 5, "y": 5, "w": 20, "h": 20}
    changed, added = run(tmp_path, ["setKeyframe", keys, 2.01, box, 30], ["setKeyframe", keys, 1, box, 30])
    assert [k["t"] for k in changed] == [0, 2.01] and changed[1]["w"] == 20
    assert [k["t"] for k in added] == [0, 1, 2]


@node
def test_a_split_makes_two_pieces_and_shares_the_keyframes(tmp_path):
    keys = [{"t": 1, "x": 0, "y": 0, "w": 10, "h": 10}, {"t": 3, "x": 20, "y": 0, "w": 10, "h": 10}]
    halves, across, before, after, single = run(
        tmp_path,
        ["splitPiece", piece("p", "V1", 10, 5, offset=2), 12],
        ["splitKeyframes", keys, 2],
        ["splitKeyframes", keys, 3.5],
        ["splitKeyframes", keys, 0.5],
        ["splitKeyframes", keys[:1], 2],
    )
    assert halves == [{"start": 10, "offset": 2, "length": 2}, {"start": 12, "offset": 4, "length": 3}]
    left, right = across
    assert [k["t"] for k in left] == [1, 2] and left[1]["x"] == 10
    assert [k["t"] for k in right] == [0, 1] and right[0]["x"] == 10
    assert before[1] is None and [k["t"] for k in before[0]] == [1, 3]
    assert after[0] is None and [k["t"] for k in after[1]] == [0.5, 2.5]
    assert single[0][0]["t"] == 1 and single[1][0]["t"] == 0


@node
def test_trimming_the_start_shifts_the_source_and_the_keyframes(tmp_path):
    trimmed, too_far, end, longest = run(
        tmp_path,
        ["trimStart", piece("p", "V1", 4, 6, offset=1), 5.5],
        ["trimStart", piece("p", "V1", 4, 6, offset=1), 0],
        ["trimEnd", piece("p", "V1", 4, 6, offset=1), 8],
        ["trimEnd", piece("p", "V1", 4, 6, offset=1), 30, 8],
    )
    assert trimmed == {"start": 5.5, "offset": 2.5, "length": 4.5, "shift": -1.5}
    assert too_far == {"start": 3, "offset": 0, "length": 7, "shift": 1}
    assert end == {"length": 4} and longest == {"length": 7}


@node
def test_moves_snap_to_edges(tmp_path):
    by_start, by_end, free, never_before_zero = run(
        tmp_path,
        ["snapMove", 4.9, 2, [5, 20], 0.2],
        ["snapMove", 2.9, 2, [5, 20], 0.2],
        ["snapMove", 8, 2, [5, 20], 0.2],
        ["snapMove", -3, 2, [], 0.2],
    )
    assert (by_start, by_end, free, never_before_zero) == (5, 3, 8, 0)


@node
def test_tracks_material_and_the_crop(tmp_path):
    default, named, video, sound, other, on_audio, sound_on_video, first_video, crop, whole = run(
        tmp_path,
        ["tracksOf", {}],
        ["tracksOf", {"tracks": [{"id": "V1"}]}],
        ["mediaKind", "clip.MOV", ""],
        ["mediaKind", "x", "audio/mp4"],
        ["mediaKind", "notes.md", "text/markdown"],
        ["trackFor", TRACKS4, "video", "A2"],
        ["trackFor", TRACKS4, "audio", "V1"],
        ["trackFor", TRACKS4, "video", ""],
        ["cropOf", {"x": 90, "y": 0, "w": 50, "h": 100}],
        ["cropOf", None],
    )
    assert default == TRACKS4 and named == [{"id": "V1", "kind": "video", "name": "V1"}]
    assert (video, sound, other) == ("video", "audio", "")
    assert on_audio["id"] == "A2" and sound_on_video["id"] == "A1"
    # Counted out from the middle, as the terminal does: Video 1, then Audio 1.
    assert first_video["id"] == "V1"
    assert crop == {"x": 50, "y": 0, "w": 50, "h": 100} and whole == {"x": 0, "y": 0, "w": 100, "h": 100}
