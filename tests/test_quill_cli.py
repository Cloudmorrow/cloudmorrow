"""`cm quill`: a new Quill checks out, the reference's own example checks out, and `cm <quill>` routes."""

from __future__ import annotations

import re

import pytest
from typer.testing import CliRunner

from cloudmorrow.cli import quill as quill_cli
from cloudmorrow.cli.quillrun import route
from cloudmorrow.quill_reference import quill_reference
from cloudmorrow.server.quills import QuillRegistry
from tests.conftest import QUILL_CATALOG

DATAMODELS = QUILL_CATALOG / "datamodels"
runner = CliRunner()


def test_a_new_quill_checks_out_as_it_is_made(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    made = runner.invoke(quill_cli.app, ["new", "plants", "--name", "Plants"])
    assert made.exit_code == 0, made.output
    folder = tmp_path / "quill-plants"
    assert (folder / ".github" / "workflows" / "check.yml").is_file()
    assert (folder / ".gitignore").is_file()
    claude = (folder / "CLAUDE.md").read_text()
    assert "cm quill check" in claude and "## The kit" in claude
    assert 'id = "plants.item"' in (folder / "datamodels" / "item.toml").read_text()
    checked = runner.invoke(quill_cli.app, ["check", str(folder), "--datamodels", str(DATAMODELS)])
    assert checked.exit_code == 0, checked.output
    assert "it checks out" in checked.output
    assert "introduces plants.item" in checked.output
    assert "◯ <name>" in checked.output


def test_a_quill_that_does_not_check_out_says_why_and_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(quill_cli.app, ["new", "plants"])
    manifest = tmp_path / "quill-plants" / "quill.toml"
    manifest.write_text(manifest.read_text().replace('title = "name"', 'title = "colour"'))
    checked = runner.invoke(
        quill_cli.app, ["check", str(manifest.parent), "--datamodels", str(DATAMODELS)]
    )
    assert checked.exit_code == 1
    assert "colour" in checked.output


def test_the_references_own_example_is_a_quill_that_installs(tmp_path):
    """What an assistant is shown as the example must pass the check it is told to run."""
    blocks = re.findall(r"```toml\n(.*?)```", quill_reference(), re.DOTALL)
    manifest, code, datamodel = blocks[0], blocks[1], blocks[2]
    folder = tmp_path / "plants"
    (folder / "datamodels").mkdir(parents=True)
    (folder / "quill.toml").write_text(manifest + "\n" + code)
    (folder / "datamodels" / "plant.toml").write_text(datamodel)
    registry = QuillRegistry(tmp_path / "quills", tmp_path / "datamodels")
    plan = registry.plan(folder, DATAMODELS)
    assert {row["id"]: row["how"] for row in plan["data"]} == {
        "plants.plant": "introduces",
        "task": "extends",
        "contact": "asks for",
    }
    assert plan["runs_code"] == ["python services/sync.py"]
    assert [h["path"] for h in plan["webhooks"]] == ["inbound"]


@pytest.mark.parametrize(
    ("argv", "routed"),
    [
        (["tasks", "list"], ["run-quill", "tasks", "list"]),
        (["tasks"], ["run-quill", "tasks"]),
        (["note", "list"], ["note", "list"]),
        (["--help"], ["--help"]),
        ([], []),
    ],
)
def test_a_word_that_is_not_a_command_is_a_quill(argv, routed):
    assert route(argv, {"note", "quill", "secret"}) == routed
