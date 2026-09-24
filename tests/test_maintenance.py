"""Finding what an older layout left behind, and leaving everything else alone."""

from __future__ import annotations

from cloudmorrow.server.maintenance import delete_orphans, find_orphans
from tests.conftest import ADMIN


def test_a_deployment_with_nothing_wrong_reports_nothing(config, users):
    assert find_orphans(config).empty


def test_a_leftover_project_directory_is_an_orphan(config, users):
    config.ensure_dirs()
    base = config.user_base(ADMIN[0])
    (base / "notes").mkdir(parents=True, exist_ok=True)
    stale = base / "projects" / "verticore" / "notes"
    stale.mkdir(parents=True)

    found = find_orphans(config)
    assert found.directories == [base / "projects"]

    delete_orphans(config, found)
    assert not (base / "projects").exists()


def test_notes_in_a_leftover_directory_are_kept_not_deleted(config, users):
    """Deleting the directory must never mean deleting what was in it."""
    config.ensure_dirs()
    base = config.user_base(ADMIN[0])
    (base / "notes").mkdir(parents=True, exist_ok=True)
    stale = base / "projects" / "verticore" / "notes"
    stale.mkdir(parents=True)
    (stale / "runbook.md").write_text("how to deploy", encoding="utf-8")

    delete_orphans(config, find_orphans(config))

    assert not (base / "projects").exists()
    assert (base / "notes" / "verticore" / "runbook.md").read_text() == "how to deploy"


def test_orphans_are_only_read_until_told_otherwise(config, users):
    config.ensure_dirs()
    base = config.user_base(ADMIN[0])
    (base / "projects" / "old").mkdir(parents=True)

    found = find_orphans(config)

    assert found.deleted is False
    assert (base / "projects").is_dir()


def test_a_leftover_directory_holding_something_else_is_left_alone(config, users):
    """Emptying a directory is not a licence to delete what is in it."""
    config.ensure_dirs()
    base = config.user_base(ADMIN[0])
    (base / "notes").mkdir(parents=True, exist_ok=True)
    project = base / "projects" / "verticore"
    project.mkdir(parents=True)
    (project / "something-else.json").write_text("{}", encoding="utf-8")

    delete_orphans(config, find_orphans(config))

    assert (project / "something-else.json").is_file()
    # And it still says so, rather than claiming to have tidied up.
    assert find_orphans(config).directories == [base / "projects"]


def test_an_empty_project_directory_goes(config, users):
    config.ensure_dirs()
    base = config.user_base(ADMIN[0])
    (base / "notes").mkdir(parents=True, exist_ok=True)
    (base / "projects" / "verticore" / "notes").mkdir(parents=True)

    delete_orphans(config, find_orphans(config))

    assert not (base / "projects").exists()
    assert find_orphans(config).empty
