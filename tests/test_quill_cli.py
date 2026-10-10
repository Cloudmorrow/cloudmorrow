"""`cm quill`: a new Quill checks out, the reference's own example checks out, and `cm <quill>` routes."""

from __future__ import annotations

import re

import pytest
import typer
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
    checked = runner.invoke(quill_cli.app, ["check", str(manifest.parent), "--datamodels", str(DATAMODELS)])
    assert checked.exit_code == 1
    assert "colour" in checked.output


def test_the_references_own_example_is_a_quill_that_installs(tmp_path):
    """What an assistant is shown as the example must pass the check it is told to run."""
    blocks = re.findall(r"```toml\n(.*?)```", quill_reference(), re.DOTALL)
    manifest = blocks[0]
    code = next(block for block in blocks if "[[services]]" in block)
    datamodel = next(block for block in blocks if "[datamodel]" in block)
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


def test_the_datamodels_folder_in_the_environment_is_honoured(tmp_path, monkeypatch):
    """What a Quill's workflow checks out, and the test harness reads: `cm quill check`
    and `cm quill test` read it too, instead of fetching the release the catalog pins."""
    from cloudmorrow.cli.quill import _datamodels_folder

    monkeypatch.setenv("CLOUDMORROW_DATAMODELS", str(DATAMODELS))
    assert _datamodels_folder(None, tmp_path) == DATAMODELS
    monkeypatch.setenv("CLOUDMORROW_DATAMODELS", str(tmp_path / "nowhere"))
    with pytest.raises(typer.Exit):
        _datamodels_folder(None, tmp_path)


# -- Quills of your own (docs/SHARING.md) -------------------------------------------
def test_the_shelf_commands_are_there_and_say_whose_a_quill_is():
    helped = runner.invoke(quill_cli.app, ["--help"])
    for command in ("mine", "share", "accept", "request", "approve", "promote", "export", "fork", "policy", "audience"):
        assert command in helped.output, command
    assert quill_cli._whose({"mine": True}) == "yours"
    assert quill_cli._whose({"shared_by": "alice"}) == "alice's, shared"
    assert quill_cli._whose({"audience": {"circles": ["Parents"], "people": []}}) == "the server's, for Parents"
    assert quill_cli._whose({}) == "the server's"
    assert quill_cli._owner_and_id("alice/budget") == ("alice", "budget")
    with pytest.raises(typer.Exit):
        quill_cli._owner_and_id("budget")


def test_mine_lists_what_the_server_says(monkeypatch):
    class FakeApi:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def my_quills(self):
            return {
                "may": {"have": True, "install": False, "ask": True, "code": True, "share": True},
                "quills": [
                    {
                        "id": "budget",
                        "name": "Budget",
                        "version": "0.2.0",
                        "enabled": True,
                        "shared_with": [
                            {"username": "bob", "state": "accepted"},
                            {"username": "carol", "state": "offered"},
                        ],
                        "webhook_urls": [{"id": "bank", "url": "https://x/hooks/~alice.budget/bank", "secret": "s3"}],
                    }
                ],
                "offers": [{"owner": "dan", "quill": "plants", "name": "Plants", "state": "offered"}],
                "requests": [{"id": 4, "kind": "install", "quill": "tasks", "source": "", "state": "open"}],
            }

    monkeypatch.setattr(quill_cli, "client", lambda: (None, FakeApi()))
    shown = runner.invoke(quill_cli.app, ["mine"])
    assert shown.exit_code == 0, shown.output
    assert "cm quill request" in shown.output
    assert "bob, carol (offered)" in shown.output
    assert "https://x/hooks/~alice.budget/bank?token=s3" in shown.output
    assert "cm quill accept dan/plants" in shown.output
    assert "request 4: install tasks" in shown.output
