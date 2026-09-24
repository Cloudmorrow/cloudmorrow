"""Updating a deployment from git, against real temporary repositories."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cloudmorrow.server.update import (
    UpdateError,
    current_commit,
    find_source_dir,
    update,
    working_tree_is_dirty,
)


def git(*args: str, cwd) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture()
def deployment(tmp_path):
    """An 'origin' repo and a clone of it, standing in for a deployed server."""
    origin = tmp_path / "origin"
    origin.mkdir()
    git("init", "--quiet", "--initial-branch", "main", cwd=origin)
    git("config", "user.email", "test@example.com", cwd=origin)
    git("config", "user.name", "Test", cwd=origin)
    (origin / "version.txt").write_text("1\n")
    git("add", "-A", cwd=origin)
    git("commit", "--quiet", "-m", "first", cwd=origin)

    checkout = tmp_path / "checkout"
    git("clone", "--quiet", str(origin), str(checkout), cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=checkout)
    git("config", "user.name", "Test", cwd=checkout)
    return origin, checkout


def push_commit(origin, message: str = "second") -> None:
    (origin / "version.txt").write_text("2\n")
    git("add", "-A", cwd=origin)
    git("commit", "--quiet", "-m", message, cwd=origin)


def test_update_fast_forwards(deployment):
    origin, checkout = deployment
    before = current_commit(checkout)
    push_commit(origin)

    result = update(source=checkout, restart=False, reinstall=False)

    assert result.changed
    assert result.old_commit == before
    assert result.new_commit == current_commit(origin)
    assert result.changed_files == 1
    assert (checkout / "version.txt").read_text() == "2\n"
    assert result.restarted is False


def test_update_with_nothing_new_is_a_no_op(deployment):
    _, checkout = deployment
    result = update(source=checkout, restart=False, reinstall=False)
    assert not result.changed
    assert result.changed_files == 0
    assert result.reinstalled is False


def test_local_changes_block_the_update(deployment):
    origin, checkout = deployment
    push_commit(origin)
    (checkout / "version.txt").write_text("edited on the server\n")
    assert working_tree_is_dirty(checkout)

    with pytest.raises(UpdateError, match="uncommitted changes"):
        update(source=checkout, restart=False, reinstall=False)
    # The refusal must not have touched anything.
    assert (checkout / "version.txt").read_text() == "edited on the server\n"


def test_force_updates_despite_local_changes(deployment):
    origin, checkout = deployment
    push_commit(origin)
    (checkout / "untracked.txt").write_text("scratch\n")

    result = update(source=checkout, restart=False, reinstall=False, force=True)
    assert result.changed


def tag(repo, name: str) -> None:
    git("tag", "-a", name, "-m", name, cwd=repo)


def test_a_deploy_reports_the_release_it_moved_between(deployment):
    """The version is the tag, so a deploy can name both ends of itself."""
    origin, checkout = deployment
    tag(origin, "v0.1.0")
    git("fetch", "--quiet", "--tags", "origin", cwd=checkout)
    push_commit(origin)
    tag(origin, "v0.2.0")

    result = update(source=checkout, restart=False, reinstall=False)

    assert (result.old_version, result.new_version) == ("0.1.0", "0.2.0")


def test_an_untagged_commit_has_no_version(deployment):
    """No tag behind it is not a release, and it does not pretend to be one."""
    origin, checkout = deployment
    push_commit(origin)

    result = update(source=checkout, restart=False, reinstall=False)

    assert result.new_version == ""


def test_a_deploy_fetches_the_tags_it_reads_versions_from(deployment):
    """A tag made after the checkout was cloned still names the new release."""
    origin, checkout = deployment
    push_commit(origin)
    tag(origin, "v0.4.0")
    assert git("tag", "--list", cwd=checkout) == ""

    result = update(source=checkout, restart=False, reinstall=False)

    assert result.new_version == "0.4.0"


def test_a_commit_past_a_release_says_how_far_past(deployment):
    """Commits after a release belong to it, and are not it: 0.5.0+1 says both."""
    origin, checkout = deployment
    tag(origin, "v0.5.0")
    push_commit(origin, "work after the release")

    result = update(source=checkout, restart=False, reinstall=False)

    assert result.new_version == "0.5.0+1"
    # It really is past the tag, not sitting on it.
    assert result.new_commit != git("rev-parse", "v0.5.0^{commit}", cwd=checkout)


def test_two_deploys_between_the_same_two_tags_are_told_apart(deployment):
    """The complaint this came from: a deploy announcing 0.23.0 → 0.23.0."""
    origin, checkout = deployment
    tag(origin, "v0.6.0")
    push_commit(origin, "one after the release")
    update(source=checkout, restart=False, reinstall=False)
    (origin / "version.txt").write_text("3\n")
    git("commit", "--quiet", "-a", "-m", "and another", cwd=origin)

    result = update(source=checkout, restart=False, reinstall=False)

    assert (result.old_version, result.new_version) == ("0.6.0+1", "0.6.0+2")


def test_an_ordinary_deploy_discards_nothing(deployment):
    origin, checkout = deployment
    push_commit(origin)

    result = update(source=checkout, restart=False, reinstall=False)

    assert result.discarded == 0
    assert result.rewound is False


def test_a_force_pushed_branch_still_deploys(deployment):
    """The case that wedged a real server: the commit it holds was un-published.

    The checkout fast-forwarded onto a commit that was the tip at the time, and
    the branch was then rewritten. Nothing was done wrong here by anyone, and
    the deploy has to survive it.
    """
    origin, checkout = deployment
    push_commit(origin, "before the rewrite")
    update(source=checkout, restart=False, reinstall=False)
    deployed = current_commit(checkout)

    # The branch is rewritten: same content, different commit.
    git("commit", "--quiet", "--amend", "-m", "after the rewrite", cwd=origin)
    rewritten = current_commit(origin)
    assert rewritten != deployed

    result = update(source=checkout, restart=False, reinstall=False)

    assert result.new_commit == rewritten
    assert result.discarded == 1
    assert result.rewound is True


def test_a_rolled_back_branch_still_deploys(deployment):
    """Moving the branch backwards is a deploy too, and used to be impossible."""
    origin, checkout = deployment
    first = current_commit(origin)
    push_commit(origin, "a release worth undoing")
    update(source=checkout, restart=False, reinstall=False)
    assert (checkout / "version.txt").read_text() == "2\n"

    git("reset", "--hard", "--quiet", first, cwd=origin)

    result = update(source=checkout, restart=False, reinstall=False)

    assert result.new_commit == first
    assert result.rewound is True
    assert (checkout / "version.txt").read_text() == "1\n"


def test_a_deploy_never_makes_a_merge_commit(deployment):
    """The rule the old --ff-only was there to keep. Reset keeps it too."""
    origin, checkout = deployment
    push_commit(origin, "upstream work")
    (checkout / "local.txt").write_text("committed on the server\n")
    git("add", "-A", cwd=checkout)
    git("commit", "--quiet", "-m", "local work", cwd=checkout)

    result = update(source=checkout, restart=False, reinstall=False)

    assert result.new_commit == current_commit(origin)
    # Exactly the remote's history, with nothing of the server's spliced in.
    assert git("rev-list", "--count", "HEAD", cwd=checkout) == git(
        "rev-list", "--count", "HEAD", cwd=origin
    )
    assert not (checkout / "local.txt").exists()


def test_a_commit_made_on_the_server_is_reported_before_it_goes(deployment):
    """The one case worth hearing about, so it does not pass unnoticed."""
    origin, checkout = deployment
    push_commit(origin, "upstream work")
    (checkout / "local.txt").write_text("committed on the server\n")
    git("add", "-A", cwd=checkout)
    git("commit", "--quiet", "-m", "local work", cwd=checkout)

    result = update(source=checkout, restart=False, reinstall=False)

    assert result.discarded == 1
    assert result.rewound is True


def test_detached_head_is_refused(deployment):
    origin, checkout = deployment
    push_commit(origin)
    git("checkout", "--quiet", "--detach", "HEAD", cwd=checkout)
    with pytest.raises(UpdateError, match="detached HEAD"):
        update(source=checkout, restart=False, reinstall=False)


def test_a_directory_that_is_not_a_checkout(tmp_path):
    with pytest.raises(UpdateError, match="not a git checkout"):
        find_source_dir(tmp_path)


def test_source_dir_from_the_environment(deployment, monkeypatch):
    _, checkout = deployment
    monkeypatch.setenv("CLOUDMORROW_SOURCE_DIR", str(checkout))
    assert find_source_dir() == checkout.resolve()


def test_update_follows_an_explicit_branch(deployment):
    origin, checkout = deployment
    git("checkout", "--quiet", "-b", "deploy", cwd=origin)
    push_commit(origin, "work on deploy")
    git("fetch", "--quiet", "origin", cwd=checkout)
    git("checkout", "--quiet", "-b", "deploy", "origin/deploy", cwd=checkout)

    result = update(source=checkout, branch="deploy", restart=False, reinstall=False)
    assert result.branch == "deploy"
    assert not result.changed  # already at the tip after checking it out


def test_exit_status_signals_nothing_to_pull(deployment):
    """cloudmorrow-update leans on exit 3 to skip a pointless restart."""
    from typer.testing import CliRunner

    from cloudmorrow.server.cli import app

    _, checkout = deployment
    runner = CliRunner()
    args = ["update", "--source", str(checkout), "--no-restart", "--no-reinstall"]

    unchanged = runner.invoke(app, [*args, "--exit-status"])
    assert unchanged.exit_code == 3
    assert "Already up to date" in unchanged.stdout

    # Without the flag it stays a plain success, for a human at a prompt.
    assert runner.invoke(app, args).exit_code == 0


def test_exit_status_is_zero_when_something_was_pulled(deployment):
    from typer.testing import CliRunner

    from cloudmorrow.server.cli import app

    origin, checkout = deployment
    push_commit(origin)
    result = CliRunner().invoke(
        app,
        [
            "update",
            "--source",
            str(checkout),
            "--no-restart",
            "--no-reinstall",
            "--exit-status",
        ],
    )
    assert result.exit_code == 0
    assert "Updated" in result.stdout


def test_build_wheel_publishes_the_checkout(tmp_path):
    """The server is where clients get Cloudmorrow, so it builds its own wheel."""
    from cloudmorrow.server.update import build_wheel

    dist = tmp_path / "dist"
    wheel = build_wheel(Path(__file__).resolve().parents[1], dist)
    assert wheel.is_file()
    assert wheel.name.startswith("cloudmorrow-") and wheel.suffix == ".whl"
    assert wheel.parent == dist


def test_build_wheel_prunes_old_builds(tmp_path):
    from cloudmorrow.server.update import build_wheel

    dist = tmp_path / "dist"
    dist.mkdir()
    for index in range(5):
        (dist / f"cloudmorrow-0.0.{index}-py3-none-any.whl").write_bytes(b"old")
    build_wheel(Path(__file__).resolve().parents[1], dist, keep=2)
    assert len(list(dist.glob("*.whl"))) == 2


# -- stopping the server so systemd starts it again -------------------------
def test_it_will_not_stop_itself_outside_systemd(monkeypatch):
    """Nothing would bring it back, so exiting would just end the service."""
    from cloudmorrow.server import update as update_module

    monkeypatch.delenv("INVOCATION_ID", raising=False)
    assert "not started by systemd" in update_module.self_restart_blocker("cloudmorrow")


def test_it_will_not_stop_itself_when_the_unit_would_not_restart(monkeypatch):
    from cloudmorrow.server import update as update_module

    monkeypatch.setenv("INVOCATION_ID", "deadbeef")
    monkeypatch.setattr(update_module, "unit_property", lambda service, name: "on-failure")
    blocker = update_module.self_restart_blocker("cloudmorrow")
    assert "Restart=on-failure" in blocker
    assert "Restart=always" in blocker


def test_it_stops_itself_when_systemd_will_start_it_again(monkeypatch):
    from cloudmorrow.server import update as update_module

    monkeypatch.setenv("INVOCATION_ID", "deadbeef")
    monkeypatch.setattr(update_module, "unit_property", lambda service, name: "always")
    assert update_module.self_restart_blocker("cloudmorrow") == ""
