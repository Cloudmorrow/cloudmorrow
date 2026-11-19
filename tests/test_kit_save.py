"""A kit's Save: the photo kit's and the timeline's `save` binding are checked
the same way at install — an action on the edit (the project) with the fields
`overwrite` and `name`, and for a timeline a `source` on the project to write
over (docs/PHOTO.md, docs/TIMELINE.md)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from cloudmorrow.server.quills import QuillError
from tests.conftest import QUILL_CATALOG


def _copy(tmp_path: Path, name: str) -> Path:
    folder = tmp_path / name
    shutil.copytree(QUILL_CATALOG / name, folder)
    return folder


def _install(client, folder: Path):
    state = client.app.state.cloudmorrow
    state.quills.install_from_catalog("files")
    return state.quills.install(folder, QUILL_CATALOG / "datamodels")


def test_the_fixtures_save_is_taken(client, tmp_path):
    for name in ("quill-cropper", "quill-cutter"):
        _install(client, _copy(tmp_path, name))


def test_a_save_without_both_fields_is_refused(client, tmp_path):
    folder = _copy(tmp_path, "quill-cutter")
    toml = folder / "quill.toml"
    toml.write_text(toml.read_text().replace('overwrite = { kind = "bool", default = false }\n', ""))
    with pytest.raises(QuillError, match="save is an action with the fields overwrite"):
        _install(client, folder)


def test_a_timeline_save_needs_a_source_to_write_over(client, tmp_path):
    folder = _copy(tmp_path, "quill-cutter")
    project = folder / "datamodels" / "project.toml"
    project.write_text(project.read_text().replace('source = { kind = "string" }\n', ""))
    with pytest.raises(QuillError, match="has a string field source"):
        _install(client, folder)


def test_a_save_names_one_of_the_quills_actions_on_the_project(client, tmp_path):
    folder = _copy(tmp_path, "quill-cutter")
    toml = folder / "quill.toml"
    toml.write_text(toml.read_text().replace('save = "save"', 'save = "export-all"'))
    with pytest.raises(QuillError, match="save names one of its actions on cutter.project"):
        _install(client, folder)
