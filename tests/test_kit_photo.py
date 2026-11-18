"""The photo kit's server side: what a manifest must say (docs/PHOTO.md)."""

from __future__ import annotations

import shutil

import pytest

from cloudmorrow.quill.screens import api_path, photo_fields, pictures_path
from cloudmorrow.server.quills import QuillError, QuillRegistry
from tests.conftest import QUILL_CATALOG

CROPPER = QUILL_CATALOG / "quill-cropper"


def test_pictures_path_is_the_apis_prefix():
    quill = {"id": "snap", "apis": [{"id": "pictures", "service": "draw", "prefix": "pictures"}]}
    assert pictures_path(quill, {"pictures": "pictures"}) == "/api/q/snap/pictures"
    assert pictures_path(quill, {}) is None
    assert api_path(quill, "pictures") == "/api/q/snap/pictures" and api_path(quill, "nope") is None


def test_photo_fields_find_the_link():
    models = {"s.layer": {"id": "s.layer", "fields": [{"name": "edit", "kind": "link", "to": "s.edit"}]}}
    screen = {
        "model": "s.edit",
        "layers": "s.layer",
        "media": {"share": "my-files", "within": "Photos"},
        "save": "save",
    }
    bound = photo_fields(screen, {"id": "s.edit", "title": "name", "fields": [{"name": "rotate"}]}, models)
    assert bound["layer_edit"] == "edit" and bound["layers"] == "s.layer" and bound["save"] == "save"
    assert bound["media"] == {"share": "my-files", "within": "Photos"} and bound["fields"] == {"rotate"}
    assert photo_fields({"model": "s.edit"}, {"id": "s.edit", "fields": []}, models)["layers"] == ""


# -- the manifest ------------------------------------------------------------------------
def cropper_copy(tmp_path, **replace: str):
    folder = tmp_path / f"cropper{len(list(tmp_path.iterdir()))}"
    shutil.copytree(CROPPER, folder)
    for name, (old, new) in replace.items():
        path = folder / name
        text = path.read_text(encoding="utf-8")
        assert old in text
        path.write_text(text.replace(old, new), encoding="utf-8")
    return folder


@pytest.fixture()
def registry(tmp_path) -> QuillRegistry:
    return QuillRegistry(tmp_path / "quills", tmp_path / "datamodels", str(QUILL_CATALOG))


def test_the_cropper_plans(registry):
    plan = registry.plan(CROPPER, QUILL_CATALOG / "datamodels")
    assert plan["id"] == "cropper"
    (screen,) = plan["screens"]
    assert screen["kit"] == "photo" and screen["layers"] == "cropper.layer"
    assert screen["export"] == "export" and screen["save"] == "save"


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"datamodels/edit.toml": ('source = { kind = "string"', 'source = { kind = "int"')}, "source"),
        (
            {
                "datamodels/edit.toml": (
                    'width = { kind = "int", description = "The photo\'s width in pixels; filled in when blank" }\n',
                    "",
                )
            },
            "width",
        ),
        ({"datamodels/edit.toml": ('rotate = { kind = "int"', 'rotate = { kind = "string"')}, "rotate"),
        ({"datamodels/layer.toml": ('x = { kind = "decimal"', 'x = { kind = "string"')}, "'x'"),
        ({"datamodels/layer.toml": ('points = { kind = "json"', 'points = { kind = "string"')}, "points"),
        (
            {
                "datamodels/layer.toml": (
                    'values = ["text", "mark", "piece"], labels = ["Text", "Mark", "Piece"]',
                    'values = ["text", "mark"], labels = ["Text", "Mark"]',
                )
            },
            "missing piece",
        ),
        ({"quill.toml": ('export = "export"', 'export = "nope"')}, "export"),
        ({"quill.toml": ('save = "save"', 'save = "export"')}, "overwrite"),
        ({"quill.toml": ('export = "export"', 'pictures = "pictures"')}, "pictures"),
        ({"quill.toml": ('media = { share = "my-files", within = "Photos" }', 'media = "Photos"')}, "media"),
        ({"quill.toml": ('datamodels = ["file"]', "datamodels = []")}, "file"),
        (
            {"datamodels/layer.toml": ("kind = {", 'again = { kind = "link", to = "cropper.edit" }\nkind = {')},
            "exactly one link",
        ),
    ],
)
def test_a_photo_editor_says_what_is_missing(registry, tmp_path, change, said):
    with pytest.raises(QuillError, match=said):
        registry.plan(cropper_copy(tmp_path, **change), QUILL_CATALOG / "datamodels")


def test_the_layers_and_the_save_are_optional(registry, tmp_path):
    plan = registry.plan(
        cropper_copy(tmp_path, **{"quill.toml": ('layers = "cropper.layer"\nmedia', "media")}),
        QUILL_CATALOG / "datamodels",
    )
    assert "layers" not in plan["screens"][0]
    plan = registry.plan(
        cropper_copy(tmp_path, **{"quill.toml": ('save = "save"\n', "")}), QUILL_CATALOG / "datamodels"
    )
    assert "save" not in plan["screens"][0]
