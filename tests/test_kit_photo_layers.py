"""The photo kit's layers as groups: an edit's `layers`, the elements on them,
and what each surface makes of that (docs/PHOTO.md)."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from cloudmorrow.quill import photo as ph
from cloudmorrow.server.quills import QuillError
from cloudmorrow.server.routes.web import WEB
from tests.conftest import QUILL_CATALOG, js_code

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
TWO = {"layers": [{"id": "a", "name": "Sky"}, {"id": "b", "hidden": True}]}
RECORDS = [
    {"id": "x", "fields": {"layer": "b", "order": 0}},
    {"id": "y", "fields": {"order": 5}},
    {"id": "z", "fields": {"layer": "a", "order": 1}},
    {"id": "w", "fields": {"layer": "gone", "order": 0, "hidden": True}},
]


def test_an_edit_has_one_layer_until_it_says_otherwise():
    assert ph.groups_of({}) == [{"id": "1", "name": "Layer 1", "hidden": False}]
    assert ph.groups_of({"layers": "junk"}) == [dict(ph.FIRST_LAYER)]
    groups = ph.groups_of(TWO)
    assert groups == [{"id": "a", "name": "Sky", "hidden": False}, {"id": "b", "name": "Layer 2", "hidden": True}]
    # Two the same id: the second is dropped; a layer without an id is numbered by its place.
    assert [g["id"] for g in ph.groups_of({"layers": [{"id": "a"}, {"id": "a"}, {"name": "Third"}]})] == ["a", "3"]
    assert ph.new_layer_id(groups) == "3" and ph.new_layer_id([{"id": "3"}, {"id": "4"}]) == "5"


def test_elements_go_by_their_layer_first_and_the_hidden_are_not_drawn():
    groups = ph.groups_of(TWO)
    # y names no layer and w a layer that is gone: both are on the first.
    assert [ph.layer_of_element(r["fields"], groups) for r in RECORDS] == ["b", "a", "a", "a"]
    assert [r["id"] for r in ph.elements_in_order(RECORDS, groups)] == ["w", "z", "y", "x"]
    assert [r["id"] for r in ph.drawn(RECORDS, groups)] == ["z", "y"], "x is on a hidden layer, w is hidden itself"


RUNNER = """
import * as rules from "%s";
import { readFileSync } from "node:fs";
const calls = JSON.parse(readFileSync(0, "utf8"));
console.log(JSON.stringify(calls.map(([name, ...args]) => rules[name](...args))));
"""


@node
def test_the_browser_does_the_same_sums(tmp_path):
    script = tmp_path / "rules.mjs"
    script.write_text(RUNNER % (WEB / "kit_photo_rules.js").as_uri(), encoding="utf-8")
    calls = [
        ["groupsOf", {}],
        ["groupsOf", TWO],
        ["elementsInOrder", RECORDS, ph.groups_of(TWO)],
        ["newLayerId", ph.groups_of(TWO)],
        ["layerOfElement", {"layer": "gone"}, ph.groups_of(TWO)],
    ]
    done = subprocess.run(["node", str(script)], input=json.dumps(calls), capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    one, two, order, next_id, fallen = json.loads(done.stdout)
    assert one == ph.groups_of({}) and two == ph.groups_of(TWO)
    assert [r["id"] for r in order] == ["w", "z", "y", "x"] and next_id == "3" and fallen == "a"


def test_the_editor_keeps_layers_as_groups_and_pins_them_to_the_foot():
    code = js_code((WEB / "kit_photo.js").read_text(encoding="utf-8"))
    css = (WEB / "kit_photo.css").read_text(encoding="utf-8")
    for name in (
        "function setGroups",
        "function addGroup",
        "function toggleGroup",
        "function moveGroup",
        "function renameGroup",
        "function removeGroup",
    ):
        assert name in code, name
    # New elements land on the current layer; the layers are written on the edit.
    assert "if (ed.b.grouped) record.layer = group.id;" in code
    assert "patch(ed.b.model.id, ed.id, { layers: groups })" in code
    # Nothing on a hidden layer is drawn or hit.
    assert code.count("if (!visible(ed, layer)) continue;") == 2
    # The side is as tall as the picture, with the layers at its foot; the tools start at the top.
    assert "function syncSide(ed)" in code and "side.style.height = desk" in code
    assert "margin: auto 0 0" in css and "justify-content: flex-start" in css
    # `elements` is the binding, `layers` its first name.
    assert "screen.elements || screen.layers" in code


def test_the_checks_take_elements_and_still_layers(client, tmp_path):
    state = client.app.state.cloudmorrow
    state.quills.install_from_catalog("files")
    folder = tmp_path / "quill-cropper"
    shutil.copytree(QUILL_CATALOG / "quill-cropper", folder)
    toml = folder / "quill.toml"
    text = toml.read_text()
    toml.write_text(text.replace('elements = "cropper.layer"', 'layers = "cropper.layer"'))
    state.quills.install(folder, QUILL_CATALOG / "datamodels")
    state.quills.uninstall("cropper")
    toml.write_text(text.replace('elements = "cropper.layer"', 'elements = "cropper.layer"\nlayers = "cropper.edit"'))
    with pytest.raises(QuillError, match="elements and layers name the same datamodel"):
        state.quills.install(folder, QUILL_CATALOG / "datamodels")
