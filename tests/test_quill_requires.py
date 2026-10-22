"""`[requires] quills`: a Quill that works with another installs it first, from
the catalog, and the other cannot be removed while it is here."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from cloudmorrow.server.quills import QuillError, QuillRegistry, parse_manifest, removal
from cloudmorrow.server.records import RecordStore
from tests.conftest import QUILL_CATALOG
from tests.test_quills import write_quill

LIBRARY = """
[quill]
id = "library"
name = "Library"
version = "1.2.0"
summary = "Every picture, rated."
category = "personal"
publisher = "Cloudmorrow"
license = "AGPL-3.0-or-later"

[uses]
datamodels = ["file"]
"""

EDITOR = """
[quill]
id = "editor"
name = "Editor"
version = "1.0.0"
summary = "Cuts what the Library holds."
category = "personal"
publisher = "Cloudmorrow"
license = "AGPL-3.0-or-later"

[uses]
datamodels = ["file"]

[requires]
quills = ["library"]
"""


def write_catalog(folder: Path, quills: dict[str, str]) -> Path:
    """A catalog whose Quills are folders beside it."""
    folder.mkdir(parents=True, exist_ok=True)
    entries = ""
    for quill_id, manifest in quills.items():
        write_quill(folder / quill_id, manifest)
        name = tomllib.loads(manifest)["quill"]["name"]
        entries += f'\n[[quills]]\nid = "{quill_id}"\nname = "{name}"\nsummary = "{name}."\n'
        entries += f'repo = "{quill_id}"\nref = "v1.2.0"\n'
    (folder / "catalog.toml").write_text(
        f'[datamodels]\nrepo = "{QUILL_CATALOG / "datamodels"}"\n\n'
        '[[categories]]\nid = "personal"\nlabel = "Personal"\ndescription = "Yours."\n' + entries,
        encoding="utf-8",
    )
    return folder


@pytest.fixture()
def registry(tmp_path) -> QuillRegistry:
    catalog = write_catalog(tmp_path / "catalog", {"library": LIBRARY})
    return QuillRegistry(tmp_path / "quills", tmp_path / "datamodels", str(catalog))


def test_requires_quills_is_read_and_held_to_its_shape():
    manifest = parse_manifest(tomllib.loads(EDITOR))
    assert manifest.quills == ("library",)
    assert manifest.to_dict()["requires"] == {"runtimes": [], "quills": ["library"]}
    with pytest.raises(QuillError, match="Quill ids"):
        parse_manifest(tomllib.loads(EDITOR.replace('["library"]', '["The Library"]')))
    with pytest.raises(QuillError, match="twice"):
        parse_manifest(tomllib.loads(EDITOR.replace('["library"]', '["library", "library"]')))
    with pytest.raises(QuillError, match="itself"):
        parse_manifest(tomllib.loads(EDITOR.replace('["library"]', '["editor"]')))


def test_the_install_sheet_says_what_comes_with_it_and_the_install_brings_it(registry, tmp_path):
    folder = write_quill(tmp_path / "src", EDITOR)
    plan = registry.plan(folder, QUILL_CATALOG / "datamodels")
    assert plan["quills"] == [
        {"id": "library", "name": "Library", "version": "1.2.0", "installed": False, "summary": "Library."}
    ]
    assert registry.quills == {}  # planning installs nothing

    done = registry.install(folder, QUILL_CATALOG / "datamodels")
    assert done["quills_installed"] == ["library"]
    assert set(registry.quills) == {"library", "editor"}
    assert registry.quills["library"].origin["catalog"] is True
    # Installed again: it is here, and nothing more is installed.
    again = registry.install(folder, QUILL_CATALOG / "datamodels")
    assert again["quills_installed"] == [] and again["quills"][0]["installed"] is True


def test_a_quill_the_catalog_lacks_is_refused_before_anything_is_installed(registry, tmp_path):
    folder = write_quill(tmp_path / "src", EDITOR.replace('["library"]', '["atlas"]'))
    with pytest.raises(QuillError, match="neither installed nor in the catalog"):
        registry.install(folder, QUILL_CATALOG / "datamodels")
    assert registry.quills == {}


def test_without_a_catalog_it_installs_alone_and_says_so(tmp_path):
    registry = QuillRegistry(tmp_path / "quills", tmp_path / "datamodels", str(tmp_path / "no-catalog"))
    folder = write_quill(tmp_path / "src", EDITOR)
    assert "could not be read" in registry.plan(folder, QUILL_CATALOG / "datamodels")["quills"][0]["problem"]
    done = registry.install(folder, QUILL_CATALOG / "datamodels")
    assert done["quills_installed"] == [] and done["quills_skipped"] == ["library"]
    assert set(registry.quills) == {"editor"}


def test_two_that_require_each_other_install_once_each(tmp_path):
    library = LIBRARY + '\n[requires]\nquills = ["editor"]\n'
    catalog = write_catalog(tmp_path / "catalog", {"library": library, "editor": EDITOR})
    registry = QuillRegistry(tmp_path / "quills", tmp_path / "datamodels", str(catalog))
    done = registry.install(write_quill(tmp_path / "src", EDITOR), QUILL_CATALOG / "datamodels")
    assert done["quills_installed"] == ["library"] and set(registry.quills) == {"library", "editor"}


def test_a_required_quill_cannot_be_removed_while_it_is_needed(registry, tmp_path):
    registry.install(write_quill(tmp_path / "src", EDITOR), QUILL_CATALOG / "datamodels")
    records = RecordStore(tmp_path / "cm.db", registry.models, registry.expiries)
    with pytest.raises(QuillError, match="Editor needs library; remove it first"):
        removal.remove(registry, records, "library")
    with pytest.raises(QuillError, match="Editor needs library"):
        registry.uninstall("library")
    assert "library" in registry.quills
    # Once nothing needs it, it goes like any other.
    removal.remove(registry, records, "editor")
    removal.remove(registry, records, "library")
    assert registry.quills == {}


def test_somebody_s_own_quill_is_satisfied_by_the_server_s(registry, tmp_path):
    registry.install_from_catalog("library")
    plan = registry.plan(write_quill(tmp_path / "mine", EDITOR), QUILL_CATALOG / "datamodels", owner="alice")
    assert plan["quills"][0]["installed"] is True
    registry.install(write_quill(tmp_path / "mine", EDITOR), QUILL_CATALOG / "datamodels", owner="alice")
    assert "library" not in registry.personal.get("alice", {})
    # Alice's Editor leans on the server's Library, so that cannot go.
    with pytest.raises(QuillError, match="needs library"):
        registry.uninstall("library")
