"""Secrets as .env files in the terminal: a list of secrets, and a list of projects.

A list of `secret` gets `m` (a .env file into the environment on screen)
and `x` (the environment out to one); a list that binds `vault` is
kit_projects.py's, with init, update, clone and import on its toolbar. The
work is checkout.py's, tested in test_checkout.py and, against a real server
and git, in test_kit_projects_cli.py.
"""

from __future__ import annotations

import copy

from textual.widgets import Input

from cloudmorrow.tui.panes.kit import pane_for
from cloudmorrow.tui.panes.kit_grouped import GroupedListPane
from cloudmorrow.tui.panes.kit_projects import ProjectsPane
from cloudmorrow.tui.screens.modals import PromptModal
from tests.tui_harness import open_secrets, settle
from tests.tui_quills import SECRETS_QUILL


async def breathe(pilot) -> None:
    await pilot.pause()
    await pilot.pause()


def projects_quill() -> dict:
    project = {
        "id": "devlist.project",
        "label": "Project",
        "title": "name",
        "access": "write",
        "fields": [
            {"name": "name", "kind": "string", "label": "Name", "required": True},
            {"name": "repo", "kind": "url", "label": "Repository"},
            {"name": "vault", "kind": "string", "label": "Vault", "indexed": True},
            {"name": "env_files", "kind": "json", "label": "Env files"},
        ],
    }
    quill = copy.deepcopy(SECRETS_QUILL) | {"id": "devlist", "name": "Devlist"}
    quill["models"] = {**quill["models"], "devlist.project": project}
    quill["screens"] = [
        {
            "id": "projects",
            "kit": "list",
            "label": "Projects",
            "model": "devlist.project",
            "title": "name",
            "vault": "vault",
            "repo": "repo",
            "env_files": "env_files",
        },
        *quill["screens"],
    ]
    return quill


def test_a_list_that_binds_a_vault_is_projects_with_their_folders():
    quill = projects_quill()
    pane = pane_for(quill, quill["screens"][0])
    assert isinstance(pane, ProjectsPane)
    assert [a.id for a in pane.ACTIONS][:5] == ["new_record", "init", "update", "clone", "import_env"]
    secrets = pane_for(quill, quill["screens"][1])
    assert isinstance(secrets, GroupedListPane)
    assert {"import_env", "export_env"} <= {a.id for a in secrets.ACTIONS}


async def test_the_environment_on_screen_goes_out_to_a_file_and_comes_back_in(app, tmp_path):
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await open_secrets(app, pilot)
        pane = screen.query_one(GroupedListPane)
        pane.stand(0, "verticore")
        await settle(app, pilot)
        assert pane.place() == ("verticore", "local")

        out = tmp_path / ".env"
        pane.fire("export_env")
        await breathe(pilot)
        assert isinstance(app.screen, PromptModal)
        app.screen.query_one(Input).value = str(out)
        await pilot.press("enter")
        await breathe(pilot)
        await settle(app, pilot)
        assert "API_URL=" in out.read_text()
        assert out.stat().st_mode & 0o777 == 0o600

        (tmp_path / ".env.local").write_text("NEW_KEY=fresh\n")
        pane.fire("import_env")
        await breathe(pilot)
        app.screen.query_one(Input).value = str(tmp_path / ".env.local")
        await pilot.press("enter")
        await breathe(pilot)
        await settle(app, pilot)
        assert app.client.secret_imports == [("verticore", "local", {"NEW_KEY": "fresh"})]
        assert "NEW_KEY" in [r["fields"]["key"] for r in pane.records]
